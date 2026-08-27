# SPDX-License-Identifier: GPL-3.0-or-later
"""Which of a wiki's user scripts are originals, and which are somebody's copy.

A directory of user scripts has to answer a question the wiki itself cannot:
of the 6,551 frwiki user-space pages that hold a real script, how many are
*distinct scripts*? The answer is 1,395, and getting there is not deduplication.
Most of the difference is not byte-identical copies at all -- it is per-user
configuration. 472 people have a page called `LiveRCparam.js`, each holding
their own settings for one shared tool. Hashing finds none of them, because no
two are the same.

What does find them is the filename. When many owners have a page under the
same name, the later ones are overwhelmingly instances of whatever the first
one was, and this module folds them onto it. That rule is blunt enough to be
dangerous on its own -- a genuinely popular name would bury real scripts -- so
it never fires alone:

**A page that other people demonstrably load keeps its identity, whatever it is
called.** The guard, not the threshold, is what protects real scripts. It also
pays for itself: protecting reused pages directly is what lets the crowd
threshold sit at 5 owners rather than 25, folding 1,066 more enwiki pages, 267
more on frwiki and 241 more on meta while losing nothing that anyone imports.

The rule then validates itself in a way worth stating, because it is the reason
to trust it on a wiki nobody has hand-checked. "Earliest wins" recovers tool
authors without being told what a tool author is: 471 of the 472
`LiveRCparam.js` pages fold onto EDUCA33E, who wrote LiveRC, and the
`AdvancedContribs.js` group folds onto Maloq, who wrote AdvancedContribs. The
472nd is somebody else's settings file that another editor loads, so the guard
keeps it -- which is exactly the case INDEPENDENT_DEMAND exists for.

Nothing is dropped for being unloaded. Roughly three quarters of the originals
on every censused wiki have no importer anybody can see, and they stay in the
directory under `TIER_ARCHIVE` rather than being filtered out of it -- see
`tier_of`.

Demand is supplied by the caller rather than computed here, because it arrives
through several channels -- personal skin slots, script-to-script imports, and
`global.js` on meta -- and a census that reads only one of them scores whole
libraries at zero.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from backend.userscripts import similarity, sketch_hashes

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

# How many distinct owners must share a filename before the later pages under
# it are presumed to be instances rather than scripts. Five is low on purpose;
# it is only safe because of INDEPENDENT_DEMAND below.
#
# Measured on all three censused wikis, the cost of lowering it accelerates and
# the return on raising it does not. Going 5 -> 4 buys back 102 originals on
# enwiki, 4 -> 3 buys 189 and 3 -> 2 buys 365; going 5 -> 8 costs about 94 an
# owner, 8 -> 12 about 37, and 12 -> 25 about 17. frwiki and meta trace the same
# convex curve at a tenth the size. Five is the last threshold before folding
# gets expensive, on three corpora rather than one -- see docs/USERSCRIPTS.md.
CROWDED_OWNERS = 5

# How many distinct sources must load a page for it to keep its identity
# regardless of what it is called. This is the one number here that is a
# judgement rather than a measurement -- it encodes what counts as reuse, which
# is a question about the directory, not a fact about the wiki. Measured on the
# three censused wikis, with the name rule alone as the baseline, the guard
# rescues pages back:
#
#                    enwiki   frwiki   meta
#     name rule only   6,028    1,338  2,412
#     >= 25 sources      +22       +2     +2
#     >= 5 sources       +28       +2     +5
#     >= 3 sources       +15       +3     +5
#     >= 2 sources       +19       +4     +9
#     >= 1 source        +95      +46   +169
#
# The largest single step is at 1 on every wiki, and everything above it is a
# thin tail, so the choice is really binary: either somebody other than the
# author loading a page is enough to make it its own script, or it is not. It
# is. A page that one other person loads is being
# used by somebody who is not its owner, and a directory that folds it away
# reports that the reuse never happened -- a false negative about the only thing
# this module exists to find. Folding a genuine instance into its tool costs a
# duplicate entry that demand ranking pushes to the bottom anyway; the reverse
# error is silent and unrecoverable.
INDEPENDENT_DEMAND = 1

# How much of two bodies must be shared before the later one is read as a fork
# of the earlier. Measured on frwiki's 6,551 script pages: 0.7 folds 1,610 pages
# into 444 groups, 0.8 folds 1,386, and 0.9 folds 1,104 into 367. The count
# barely moves across that range because the pairs are not spread evenly through
# it -- a fork of a real script is usually 95% of it and a coincidence is usually
# under 0.5, so almost nothing sits at the boundary wherever the boundary is put.
#
# 0.9 is chosen because what does change across the range is the mistakes:
# groups spanning more than three distinct filenames -- which is what an
# over-broad fold looks like, since a fork normally keeps the name it was copied
# under -- fall from 14 to 11 to 6. Given a sketch that places a similarity
# within about 0.1, 0.9 means "at least four fifths the same script, probably
# more", and the same reasoning as INDEPENDENT_DEMAND applies: folding a real
# fork one entry too late is a duplicate somebody can see, and folding two
# unrelated scripts together is silent.
NEAR_COPY_SIMILARITY = 0.9


@dataclass(frozen=True)
class Candidate:
    """One user-space script page, as offered to the directory.

    `created` orders pages against each other and must be comparable across the
    corpus as a plain string. A MediaWiki timestamp sorts correctly as-is, and a
    page whose creation date could not be established is given a stand-in that
    sorts behind every real date -- see `backend.userscript_projection`, which
    is the only thing that should be minting these. `fingerprint` is the
    normalized content hash from `backend.userscripts`; an empty one never
    matches anything, which is what keeps blank pages from clustering. `sketch`
    is the sample of the same body that `similarity` reads, and is empty on a
    page stored before sketches existed -- which resembles nothing, so such a
    page folds exactly as it did before rather than folding wrongly.

    `created_at_wiki` is the same date without the stand-in: the wiki's own
    timestamp, or empty. Two fields rather than one because they answer
    different questions. `created` must always order, so it is allowed to be
    invented; `created_at_wiki` is published to readers as a fact about the
    page, so it must never be. Deriving one from the other after the fact would
    mean identifying a minted key by its shape, which is exactly the kind of
    inference that ends with a stand-in on a tool page.
    """

    title: str
    owner: str
    basename: str
    created: str
    fingerprint: str
    sketch: str = ""
    created_at_wiki: str = ""
    # The page's last edit, carried through untouched. Unlike `created` it is
    # never stood in for: there is no ordering that needs it, so a page the
    # replica has not dated simply has no last-edit date and the catalogue
    # publishes none.
    touched_at_wiki: str = ""
    # Whoever wrote the page's first revision, carried through untouched and
    # never stood in for, on the same terms as `touched_at_wiki` above. The
    # collapse does not consult it: two scripts are near-copies because their
    # code matches, and who typed them has no bearing on that.
    first_author: str = ""

    @property
    def rank(self) -> tuple[str, str]:
        """Sort key placing the earliest page first, ties broken by title.

        The tiebreak is not decoration. Creation timestamps collide, and
        without a total order the directory would name a different original
        between two runs over identical data.
        """
        return (self.created, self.title)


@dataclass
class Origin:
    """One distinct script, plus every page found to be an instance of it."""

    original: Candidate
    copies: list[Candidate] = field(default_factory=list)
    forks: list[Candidate] = field(default_factory=list)
    variants: list[Candidate] = field(default_factory=list)

    @property
    def pages(self) -> list[Candidate]:
        """The original and everything folded onto it."""
        return [self.original, *self.copies, *self.forks, *self.variants]

    @property
    def instances(self) -> int:
        """How many pages other than the original belong to this script."""
        return len(self.copies) + len(self.forks) + len(self.variants)


def owner_of_user_page(title: str) -> str:
    """Return the user whose space a page lives in.

    **The caller must already know the page is in user space.** Everything
    before the first colon is taken to be the namespace prefix, whatever it is
    called, because that is the only assumption that holds across wikis: the
    search and recent-changes queries both ask for namespace 2 by number, but
    the titles come back in each wiki's own language -- `User:` on Meta,
    `Utilisateur:` on frwiki, `Benutzer:` on dewiki, and an alias like `U:` is
    valid too. Matching the English name is how every non-English wiki ends up
    storing no owner at all.

    Given a title from somewhere else this returns nonsense rather than "", so
    resolve an owner once, here, at the point where namespace 2 is known, and
    read it back from storage everywhere else.
    """
    _, separator, remainder = title.partition(":")
    if not separator:
        return ""
    return remainder.split("/", 1)[0].strip()


def basename_of(title: str) -> str:
    """Return the part of a user-space title below the owner.

    `User:Evpok/LiveRCparam.js` gives `LiveRCparam.js`, and a page with no
    subpage at all gives "" -- it cannot collide with anyone under a shared
    filename because it has no filename.
    """
    _, separator, remainder = title.partition(":")
    if not separator:
        return ""
    _, slash, below = remainder.partition("/")
    return below.strip() if slash else ""


def _demand_for(pages: Iterable[Candidate], demand: Mapping[str, set[str]]) -> set[str]:
    """Every distinct source that loads any page belonging to one script."""
    sources: set[str] = set()
    for page in pages:
        sources |= demand.get(page.title, set())
    return sources


def _fold_exact_copies(candidates: Iterable[Candidate]) -> list[Origin]:
    """Group byte-identical pages onto the earliest one that appeared.

    This is the uncontroversial half. A page with no fingerprint -- empty, or
    nothing but comments -- is its own group, so blank pages never merge.
    """
    groups: dict[str, list[Candidate]] = defaultdict(list)
    singles: list[Candidate] = []
    for candidate in candidates:
        if candidate.fingerprint:
            groups[candidate.fingerprint].append(candidate)
        else:
            singles.append(candidate)
    origins = [Origin(original=page) for page in singles]
    for group in groups.values():
        first, *rest = sorted(group, key=lambda page: page.rank)
        origins.append(Origin(original=first, copies=sorted(rest, key=lambda page: page.rank)))
    return origins


def _fold_near_copies(origins: list[Origin]) -> list[Origin]:
    """Fold a page that is nearly an earlier one onto it, as a fork rather than a copy.

    Answers the question a hash cannot. On frwiki 678 pairs of pages are more
    than 99% the same text and share no fingerprint, and the shape of the
    difference says what they are: `lrcParams["RCLimit"] = 35` against `= 30`,
    one `@import` line present in one page and not the other. Somebody took a
    script and changed their settings.

    Each page is compared against the *originals already accepted*, never
    against another fork, and always in creation order. Comparing everything
    against everything and joining what matches would let similarity chain --
    A resembles B and B resembles C, so A and C are the same script even where
    they share nothing -- and a chain has no bound on how far it can travel.
    Here every page in a group is `NEAR_COPY_SIMILARITY` of the one page the
    group is named after, which is a claim that stays true however large the
    group gets.

    Pages are found through an index of their sketch hashes rather than by
    comparing every pair. Two bodies that share none of the 64 sampled hashes
    cannot be 90% the same, so the pairs the index skips are pairs the
    comparison would have rejected.
    """
    accepted: list[Origin] = []
    seen: dict[bytes, list[int]] = defaultdict(list)
    for origin in sorted(origins, key=lambda origin: origin.original.rank):
        hashes, _truncated = sketch_hashes(origin.original.sketch)
        nearby: set[int] = set()
        for value in hashes:
            nearby.update(seen[value])
        host = max(
            (accepted[at] for at in nearby),
            key=lambda candidate: similarity(candidate.original.sketch, origin.original.sketch),
            default=None,
        )
        if host is not None and similarity(host.original.sketch, origin.original.sketch) >= NEAR_COPY_SIMILARITY:
            host.forks.extend(origin.pages)
            continue
        at = len(accepted)
        accepted.append(origin)
        # Only the original's hashes are indexed. A fork is reachable through
        # the page it folded onto, and indexing it too would let a group grow
        # by resembling its own members rather than its original.
        for value in hashes:
            seen[value].append(at)
    return accepted


def _fold_crowded_names(origins: list[Origin], demand: Mapping[str, set[str]]) -> list[Origin]:
    """Fold later pages under a crowded filename onto the earliest, unless loaded.

    Crowding is counted in distinct *owners*, not pages: one person with the
    same filename in four skin slots is one person's habit, not a convention
    shared across the wiki.
    """
    by_name: dict[str, list[Origin]] = defaultdict(list)
    kept: list[Origin] = []
    for origin in origins:
        name = origin.original.basename
        if name:
            by_name[name].append(origin)
        else:
            kept.append(origin)
    for group in by_name.values():
        owners = {origin.original.owner for origin in group}
        group.sort(key=lambda origin: origin.original.rank)
        if len(owners) < CROWDED_OWNERS:
            kept.extend(group)
            continue
        head, *rest = group
        kept.append(head)
        for origin in rest:
            if len(_demand_for(origin.pages, demand)) >= INDEPENDENT_DEMAND:
                kept.append(origin)  # stands on its own demand, whatever it is called
            else:
                head.variants.extend(origin.pages)
    return kept


def collapse(candidates: Iterable[Candidate], demand: Mapping[str, set[str]]) -> list[Origin]:
    """Reduce a corpus of script pages to the distinct scripts inside it.

    Two stages, in this order and not the other: exact copies fold first so that
    the filename rule sees one entry per distinct content rather than one per
    page, which is what lets the crowd threshold be counted in owners.

    `demand` maps a page title to the distinct sources that load it. Titles it
    does not mention are simply unloaded; the caller does not have to enumerate
    the corpus twice.
    """
    origins = _fold_crowded_names(_fold_near_copies(_fold_exact_copies(candidates)), demand)
    origins.sort(key=lambda origin: origin.original.rank)
    return origins


def rank_by_demand(origins: Iterable[Origin], demand: Mapping[str, set[str]]) -> list[tuple[Origin, int]]:
    """Order scripts by how many distinct sources load them, most first.

    Demand for an instance counts for its original: somebody who copied
    `xpatrol.js` and is loaded by four people is evidence about xpatrol. Ties
    are broken by the original's rank so the order is total.
    """
    scored = [(origin, len(_demand_for(origin.pages, demand))) for origin in origins]
    scored.sort(key=lambda pair: (-pair[1], pair[0].original.rank))
    return scored


# A script nothing loads is still a script. 661 of frwiki's 1,264 originals are
# in that state, and they are not one population but two: 123 are depth-2
# subpages that their own parent loads, and the rest is code somebody wrote,
# used, and left running -- some of it substantial, some of it a decade old.
# Dropping either would make the corpus look tidier than it is and would discard
# the only record of what a wiki's unattended JavaScript contains, which is
# precisely what a security review wants to read. So nothing is deleted here;
# it is filed.
TIER_ACTIVE = "active"
TIER_ARCHIVE = "archive"


def tier_of(origin: Origin, demand: Mapping[str, set[str]]) -> str:
    """Say whether a script belongs in the live directory or the archive.

    The boundary is one distinct source rather than a threshold, because the two
    tiers answer different questions. `active` is "what could become a gadget",
    and one person other than the author is the least evidence that can support
    that claim. `archive` is "what exists", which needs no evidence at all.

    It currently coincides with INDEPENDENT_DEMAND, which is arithmetic rather
    than design: that one settles whether a page is its own script, this one
    settles where a script already known to be its own gets filed. Moving either
    must not move the other.

    The split it produces is the steadiest number in this subsystem. On enwiki
    1,700 of 6,207 scripts are active, on frwiki 410 of 1,395 and on meta 720 of
    2,602 -- 27.4%, 29.4% and 27.7% of corpora that differ by a factor of four
    in size and completely in language and purpose. Whatever this boundary is
    measuring, it is not an frwiki habit.
    """
    return TIER_ACTIVE if _demand_for(origin.pages, demand) else TIER_ARCHIVE


def by_tier(origins: Iterable[Origin], demand: Mapping[str, set[str]]) -> dict[str, list[Origin]]:
    """Split scripts into the two tiers, each ordered the way its tier is read.

    Both come out of `rank_by_demand`, so `active` is most-loaded first. Every
    archived script scores zero, so that ordering falls through to creation
    order -- oldest first, which is the order the cold-storage question is
    actually asked in.
    """
    tiers: dict[str, list[Origin]] = {TIER_ACTIVE: [], TIER_ARCHIVE: []}
    for origin, _ in rank_by_demand(origins, demand):
        tiers[tier_of(origin, demand)].append(origin)
    return tiers
