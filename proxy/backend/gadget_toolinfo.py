# SPDX-License-Identifier: GPL-3.0-or-later
"""Catalogue records for the gadgets a wiki declares.

A gadget is a tool. It has a name, code anyone can read, an author, and users
who switch it on. It has never had a catalogue entry only because nobody
writes a toolinfo.json for one, and Toolhub's catalog knows exactly the tools
somebody registered. Everything needed to describe a gadget is already public
on the wiki that runs it, so this module writes the record nobody wrote.

It writes into `CanonicalToolCache` because in this codebase that table is what
"a tool exists" means: cards, facets, search and authorship are all reached by
looking a name up in it. A separate table would leave gadgets visible to
nothing. The row carries `SOURCE_WIKI_GADGET`, which is both what stops a
catalog snapshot deleting it and what stops the projection reporting that
Toolhub said any of this.

Only what the wiki actually declares is projected, and there is deliberately no
description. MediaWiki keeps a gadget's description in the interface message
`MediaWiki:Gadget-<name>`, written in the wiki's own language, and this lane
does not read it yet. A missing description is a gap somebody can fill; an
inferred one is this codebase putting words in a maintainer's mouth.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend import canonical_tools, db, gadget_inventory, wiki_replica, wiki_sources
from backend.models import CanonicalToolCache, utcnow
from backend.sync import SOURCE_WIKI_GADGET, SYNC_EVOLVED_REAL
from backend.wikimedia_urls import without_format_marks

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

    from backend.models import WikiGadget

TOOL_TYPE = "gadget"
NAME_PREFIX = "gadget"
MAX_TOOL_NAME = 255
SPECIAL_GADGETS = "Special:Gadgets"
# The row is rewritten by this lane's own job rather than fetched again from
# Toolhub, so freshness tracks that cadence and not the catalog's.
FRESH_SECONDS = 7 * 24 * 60 * 60
STALE_SECONDS = 30 * 24 * 60 * 60

# Catalogue names are compared by a database that folds case and ignores
# invisible marks. Building them out of one lowercase alphabet means two
# spellings the database calls equal cannot arrive here looking different.
UNSAFE_RE = re.compile(r"[^a-z0-9.]+")

# What a gadget is written in, read off the files it actually ships rather
# than guessed. Declared ResourceLoader dependencies are deliberately not
# projected: `mediawiki.util` is a module name, not a technology a reader of
# the catalogue is looking for.
LANGUAGE_BY_SUFFIX = ((".js", "JavaScript"), (".css", "CSS"), (".json", "JSON"))

COUNT_FIELDS = ("declared", "hidden", "unnamed", "duplicate", "conflicted", "written", "unchanged", "retired")


def _slug(value: str) -> str:
    return UNSAFE_RE.sub("-", without_format_marks(str(value or "")).casefold()).strip("-.")


def tool_name(wiki: str, name: str) -> str:
    """Return the catalogue name for one wiki's gadget, or "" if it has none.

    Both halves are required. A gadget whose name survives slugging as nothing
    -- one written entirely in a non-Latin script, say -- gets no entry rather
    than an entry called after its wiki alone, which would collide with every
    other such gadget there.
    """
    wiki_part, name_part = _slug(wiki), _slug(name)
    if not (wiki_part and name_part):
        return ""
    return f"{NAME_PREFIX}-{wiki_part}-{name_part}"[:MAX_TOOL_NAME]


def wiki_prefix(wiki: str) -> str:
    """Return the catalogue-name prefix every gadget of one wiki shares."""
    return f"{NAME_PREFIX}-{_slug(wiki)}-"


def _languages(pages: list[str]) -> list[str]:
    # Casefolded because the definition parser accepts a suffix that way, and a
    # gadget shipping `Foo.JS` is written in JavaScript either way.
    folded = [page.casefold() for page in pages]
    return [language for suffix, language in LANGUAGE_BY_SUFFIX if any(page.endswith(suffix) for page in folded)]


def gadget_url(wiki: str, name: str) -> str:
    """Return the public page describing one gadget.

    `Special:Gadgets` is the wiki's own account of what it offers, and it gives
    every gadget an anchor of its own. It is the only page that exists for a
    gadget without anybody creating one, which is what makes it usable for all
    of them rather than the handful with documentation.
    """
    return f"{wiki_sources.page_url(wiki, SPECIAL_GADGETS)}#gadget-{name}"


def toolinfo_record(gadget: WikiGadget) -> dict[str, Any]:
    """Return the toolinfo the wiki's own declaration amounts to.

    Every field here is a transcription. `title` is the name the wiki gives the
    gadget, `for_wikis` is where it runs, `repository` is the page its code
    lives on. Nothing is inferred, and fields the declaration says nothing
    about -- description, licence, audiences, a bug tracker -- are absent
    rather than filled with a plausible guess.

    `created_date`, `modified_date` and `author` are the fields the declaration
    does not carry itself: they come from the code pages' own history, stamped
    on the inventory row by `backend.gadget_creation_dates` and
    `backend.wiki_edit_dates`. All three are still transcriptions -- the wiki
    recorded those revisions -- and all three are omitted, never guessed, when
    blank.

    `author` has no equivalent of the user-script fallback, because a gadget has
    no owner to fall back to: `MediaWiki:Gadget-HotCat.js` sits in a namespace
    that belongs to the wiki, and its title names a namespace rather than a
    person. Whoever created the oldest of its code pages is the only claim the
    wiki makes, so a gadget no replica has answered for publishes no author --
    which is what every gadget record did before this field existed.
    """
    pages = list(gadget.pages or [])
    record: dict[str, Any] = {
        "name": tool_name(gadget.wiki, gadget.name),
        "title": gadget.name,
        "url": gadget_url(gadget.wiki, gadget.name),
        "tool_type": TOOL_TYPE,
        "for_wikis": [gadget.wiki],
    }
    if created := wiki_replica.iso_timestamp(gadget.created_at_wiki or ""):
        # The oldest first revision among the gadget's code pages: when the
        # gadget began to exist, not when this catalogue noticed it. Absent
        # rather than approximated wherever no replica has answered.
        record["created_date"] = created
    if touched := wiki_replica.iso_timestamp(gadget.touched_at_wiki or ""):
        # The newest current revision among the code pages: when the gadget was
        # last actually changed. Distinct from `last_seen_at` on the inventory
        # row, which is when this catalogue last read the wiki -- publishing
        # that would report every gadget as updated on whatever schedule the
        # census happens to run.
        record["modified_date"] = touched
    if gadget.first_author_wiki:
        # Whoever created the code page that supplied `created_date` above. The
        # gadget namespace is administrator-only, so this is reliably somebody
        # who could write there rather than the wider set of people who have
        # edited the gadget since -- the catalogue claims an author, not a
        # contributor list.
        record["author"] = [{"name": gadget.first_author_wiki, "wiki_username": gadget.first_author_wiki}]
    if pages:
        record["repository"] = wiki_sources.page_url(gadget.wiki, f"{wiki_sources.GADGET_PREFIX}{pages[0]}")
    if languages := _languages(pages):
        record["technology_used"] = languages
    return record


def _describe(row: CanonicalToolCache, record: dict[str, Any], now: datetime) -> None:
    row.record = record
    row.source_url = record["url"][: canonical_tools.MAX_SOURCE_URL]
    row.source = SOURCE_WIKI_GADGET
    row.sync_status = SYNC_EVOLVED_REAL
    row.fetched_at = now
    row.expires_at = now + timedelta(seconds=FRESH_SECONDS)
    row.stale_until = now + timedelta(seconds=STALE_SECONDS)


def _wanted(gadgets: list[WikiGadget], counts: dict[str, int]) -> dict[str, dict[str, Any]]:
    """Return the record each catalogue name should hold, counting what is left out."""
    wanted: dict[str, dict[str, Any]] = {}
    for gadget in gadgets:
        counts["declared"] += 1
        if gadget.hidden:
            # A hidden gadget cannot be switched on from preferences: it is
            # machinery another gadget loads, not something a reader chooses.
            # The inventory records it; deciding it is not a tool is this
            # module's job, and this is where that decision is made.
            counts["hidden"] += 1
        elif not (name := tool_name(gadget.wiki, gadget.name)):
            counts["unnamed"] += 1
        elif name in wanted:
            # Two gadget names that slug to one catalogue name. The first wins,
            # as it does everywhere else in this lane, and the loss is counted
            # rather than silently absorbed.
            counts["duplicate"] += 1
        else:
            wanted[name] = toolinfo_record(gadget)
    return wanted


def _write(session: Session, wiki: str, gadgets: list[WikiGadget], now: datetime) -> tuple[dict[str, int], list[str]]:
    counts = dict.fromkeys(COUNT_FIELDS, 0)
    wanted = _wanted(gadgets, counts)
    prefix = canonical_tools.escape_like(wiki_prefix(wiki))
    ours = {
        row.tool_name: row
        for row in session.execute(
            select(CanonicalToolCache).where(
                CanonicalToolCache.source == SOURCE_WIKI_GADGET,
                CanonicalToolCache.tool_name.like(f"{prefix}%", escape="\\"),
            )
        ).scalars()
    }
    for name, record in wanted.items():
        row = ours.get(name) or session.get(CanonicalToolCache, name)
        if row is not None and row.source != SOURCE_WIKI_GADGET:
            # Something else already owns this name. Whatever it is, it was not
            # synthesized from a wiki, and overwriting a real catalogue record
            # with a guess about a name collision is not a trade worth making.
            counts["conflicted"] += 1
            continue
        if row is None:
            row = CanonicalToolCache(tool_name=name)
            session.add(row)
        elif row.record == record:
            counts["unchanged"] += 1
            continue
        _describe(row, record, now)
        counts["written"] += 1
    retired = sorted(name for name in ours if name not in wanted)
    for name in retired:
        # The gadget is gone from the wiki that declared it, so the only thing
        # that ever asserted this tool exists has stopped saying so.
        session.delete(ours[name])
        counts["retired"] += 1
    return counts, retired


def synchronize(wiki: str) -> dict[str, Any]:
    """Bring one wiki's catalogue entries in step with its stored inventory.

    Reads no wiki. `gadget_inventory` is the only thing that talks to MediaWiki
    in this lane; this rebuilds records from what it stored, so re-deciding what
    counts as a tool costs nothing and never depends on a wiki being reachable.
    """
    from backend import api_cache, catalog_facets  # noqa: PLC0415 - avoid backend startup cycles.
    from backend.people_reconcile import enqueue_tool_names_in_session  # noqa: PLC0415

    now = utcnow()
    with db.session_scope() as session:
        counts, retired = _write(session, wiki, gadget_inventory.live(session, wiki), now)
        if retired:
            enqueue_tool_names_in_session(session, retired, reason="gadget_retired")
        if counts["written"] or retired:
            catalog_facets.mark_dirty(session)
    for name in retired:
        api_cache.invalidate_tool(name)
    return {"wiki": wiki, **counts}
