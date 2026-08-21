# SPDX-License-Identifier: GPL-3.0-or-later
"""Which of a wiki's user scripts are originals, and which are somebody's copy.

A directory of user scripts has to answer a question the wiki itself cannot:
of the 2,051 frwiki user-space pages that hold a real script, how many are
*distinct scripts*? The answer is 1,264, and getting there is not deduplication.
Two thirds of the difference is not byte-identical copies at all -- it is
per-user configuration. 472 people have a page called `LiveRCparam.js`, each
holding their own settings for one shared tool. Hashing finds none of them,
because no two are the same.

What does find them is the filename. When many owners have a page under the
same name, the later ones are overwhelmingly instances of whatever the first
one was, and this module folds them onto it. That rule is blunt enough to be
dangerous on its own -- a genuinely popular name would bury real scripts -- so
it never fires alone:

**A page that other people demonstrably load keeps its identity, whatever it is
called.** The guard, not the threshold, is what protects real scripts. It also
pays for itself: protecting reused pages directly let the crowd threshold drop
from 25 owners to 5, folding 787 pages instead of 670 while losing nothing that
anyone actually imports.

The rule then validates itself in a way worth stating, because it is the reason
to trust it on a wiki nobody has hand-checked. "Earliest wins" recovers tool
authors without being told what a tool author is: 471 of the 472
`LiveRCparam.js` pages fold onto EDUCA33E, who wrote LiveRC, and the
`AdvancedContribs.js` group folds onto Maloq, who wrote AdvancedContribs. The
472nd is somebody else's settings file that another editor loads, so the guard
keeps it -- which is exactly the case INDEPENDENT_DEMAND exists for.

Nothing is dropped for being unloaded. 661 of the 1,264 originals have no
importer anybody can see, and they stay in the directory under `TIER_ARCHIVE`
rather than being filtered out of it -- see `tier_of`.

Demand is supplied by the caller rather than computed here, because it arrives
through several channels -- personal skin slots, script-to-script imports, and
`global.js` on meta -- and a census that reads only one of them scores whole
libraries at zero.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

# How many distinct owners must share a filename before the later pages under
# it are presumed to be instances rather than scripts. Five is low on purpose;
# it is only safe because of INDEPENDENT_DEMAND below.
CROWDED_OWNERS = 5

# How many distinct sources must load a page for it to keep its identity
# regardless of what it is called. This is the one number here that is a
# judgement rather than a measurement -- it encodes what counts as reuse, which
# is a question about the directory, not a fact about the wiki. On frwiki the
# name rule alone leaves 1,229 originals, and the guard rescues pages back:
#
#     >= 1 source   1,264 originals   +35
#     >= 2 sources  1,239             +10
#     >= 3 sources  1,233              +4
#     >= 5 sources  1,232              +3
#     >= 25 sources 1,229              +0
#
# Nearly the whole effect sits between 1 and 2, so the choice is really binary:
# either somebody other than the author loading a page is enough to make it its
# own script, or it is not. It is. A page that one other person loads is being
# used by somebody who is not its owner, and a directory that folds it away
# reports that the reuse never happened -- a false negative about the only thing
# this module exists to find. Folding a genuine instance into its tool costs a
# duplicate entry that demand ranking pushes to the bottom anyway; the reverse
# error is silent and unrecoverable.
INDEPENDENT_DEMAND = 1


@dataclass(frozen=True)
class Candidate:
    """One user-space script page, as offered to the directory.

    `created` orders pages against each other and must be comparable across the
    corpus as a plain string. A MediaWiki timestamp sorts correctly as-is, and a
    page whose creation date could not be established is given a stand-in that
    sorts behind every real date -- see `backend.userscript_projection`, which
    is the only thing that should be minting these. `fingerprint` is the
    normalized content hash from `backend.userscripts`; an empty one never
    matches anything, which is what keeps blank pages from clustering.
    """

    title: str
    owner: str
    basename: str
    created: str
    fingerprint: str

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
    variants: list[Candidate] = field(default_factory=list)

    @property
    def pages(self) -> list[Candidate]:
        """The original and everything folded onto it."""
        return [self.original, *self.copies, *self.variants]

    @property
    def instances(self) -> int:
        """How many pages other than the original belong to this script."""
        return len(self.copies) + len(self.variants)


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
    origins = _fold_crowded_names(_fold_exact_copies(candidates), demand)
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
