# SPDX-License-Identifier: GPL-3.0-or-later
"""Catalogue records for the user scripts a wiki's directory found.

A user script is a tool. Somebody wrote it, other people install it by adding a
line to their `common.js`, and it has never had a catalogue entry only because
nobody writes a toolinfo.json for a `User:` subpage. `userscript_directory`
already decided which pages are distinct scripts and which are somebody's copy;
this module writes the record for each one nobody wrote.

It is deliberately the same shape as `gadget_toolinfo`: rows in
`CanonicalToolCache`, because in this codebase that table is what "a tool
exists" means, carrying `SOURCE_WIKI_USERSCRIPT` so a catalog snapshot cannot
delete them and the projection cannot report that Toolhub said any of this.

Two things are decided here rather than upstream, because they are questions
about what belongs in a catalogue and not about what a wiki contains:

**Stylesheets are not tools.** `classify()` reads a page's role off how many
code lines it has, so a long `User:Someone/monobook.css` is a "script" to that
test and reaches the directory as one. It is right that it does -- a `.css` page
can hold JavaScript, and the directory's job is to describe user space. It is
not right that it becomes a catalogue entry. The wiki itself settles this:
`content_model` is what MediaWiki reports about a page, not what its suffix
suggests, so a page the wiki parses as CSS is a stylesheet no matter what it is
called. Those are counted, not silently dropped.

**Archived scripts are catalogued, and said to be archived.** A script nobody
but its author loads still exists, and a catalogue that omits it reports a
smaller wiki than the real one -- the same reason `tier_of` files rather than
deletes. So every original is written, and the tier travels with it as the
record's `_lifecycle`, which the model denormalizes into a column a facet can
filter on. That is this codebase's observation about use; it is emphatically not
the toolinfo `deprecated` flag, which is a maintainer saying "stop using my
tool". Nothing here knows what any maintainer wants.

Everything in the record itself is a transcription. `title` is the filename the
page carries, `author` is the owner MediaWiki's own title rules put the page
under, `url` is the page. There is no description: a user script's documentation
lives wherever its author chose to put it, and this lane does not read prose. A
missing description is a gap somebody can fill; an inferred one is this codebase
putting words in an author's mouth.

`user_docs_url` is where that documentation turned out to live, which is a
different question and one the wiki answers itself: `backend.userscript_docs`
asks whether the page beside the script exists and follows any redirect. This
module only publishes the answer, and publishes nothing where there was none.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend import canonical_tools, db, wiki_replica, wiki_sources
from backend.models import CanonicalToolCache, UserScriptDirectoryEntry, UserScriptPage, utcnow
from backend.sync import LIFECYCLE_ACTIVE, LIFECYCLE_ARCHIVED, SOURCE_WIKI_USERSCRIPT, SYNC_EVOLVED_REAL
from backend.userscript_directory import TIER_ACTIVE
from backend.wikimedia_urls import without_format_marks

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

TOOL_TYPE = "user script"
NAME_PREFIX = "userscript"
MAX_TOOL_NAME = 255
# What MediaWiki calls a page it parses as a stylesheet. Read from the wiki
# rather than from the suffix, because the two demonstrably disagree: frwiki
# serves `User:Penquista/monobook.css` as javascript. The wiki is right about
# its own pages, and the suffix is a habit.
STYLESHEET_MODELS = frozenset({"css", "sanitized-css"})
# The row is rewritten by this lane's own job rather than fetched again from
# Toolhub, so freshness tracks that cadence and not the catalog's.
FRESH_SECONDS = 7 * 24 * 60 * 60
STALE_SECONDS = 30 * 24 * 60 * 60

# Catalogue names are compared by a database that folds case and ignores
# invisible marks. Building them out of one lowercase alphabet means two
# spellings the database calls equal cannot arrive here looking different.
UNSAFE_RE = re.compile(r"[^a-z0-9.]+")

LANGUAGE_BY_MODEL = {"javascript": "JavaScript", "css": "CSS", "sanitized-css": "CSS", "json": "JSON"}
LANGUAGE_BY_SUFFIX = ((".js", "JavaScript"), (".css", "CSS"), (".json", "JSON"))

COUNT_FIELDS = ("originals", "stylesheet", "unnamed", "duplicate", "conflicted", "written", "unchanged", "retired")


def _slug(value: str) -> str:
    return UNSAFE_RE.sub("-", without_format_marks(str(value or "")).casefold()).strip("-.")


def tool_name(wiki: str, owner: str, basename: str) -> str:
    """Return the catalogue name for one wiki's user script, or "" if it has none.

    All three parts are required. Owner and basename together are what makes a
    user script's title, so a name built from them is unique on a wiki for the
    same reason the page title is -- and unlike the title, it does not lead with
    a namespace that means nothing outside MediaWiki. A page whose owner or
    filename survives slugging as nothing -- both written in a non-Latin script,
    say -- gets no entry rather than one called after its wiki alone, which
    would collide with every other such page there.
    """
    parts = [_slug(wiki), _slug(owner), _slug(basename)]
    if not all(parts):
        return ""
    return f"{NAME_PREFIX}-{'-'.join(parts)}"[:MAX_TOOL_NAME]


def wiki_prefix(wiki: str) -> str:
    """Return the catalogue-name prefix every user script of one wiki shares."""
    return f"{NAME_PREFIX}-{_slug(wiki)}-"


def _languages(basename: str, content_model: str) -> list[str]:
    """Return what one page is written in, preferring the wiki's own answer.

    `content_model` is what MediaWiki parses the page as, which is the only
    account of this that cannot be wrong. The suffix is the fallback, for a page
    stored before the census recorded a model.
    """
    if language := LANGUAGE_BY_MODEL.get(content_model.casefold()):
        return [language]
    folded = basename.casefold()
    return [language for suffix, language in LANGUAGE_BY_SUFFIX if folded.endswith(suffix)]


def toolinfo_record(entry: UserScriptDirectoryEntry, content_model: str = "", docs_title: str = "") -> dict[str, Any]:
    """Return the toolinfo one directory entry amounts to.

    Every field is a transcription of something the wiki already says. `author`
    is the page's owner, which is a fact rather than a guess: MediaWiki's own
    title rules put `User:Lupin/popups.js` under Lupin and nowhere else.
    `repository` is the raw page, because for a user script the page *is* the
    source -- there is no forge behind it, which is the whole reason this census
    exists.

    `created_date` is the page's own first revision, carried here from the
    census by way of the projection. It is omitted when the Wiki Replicas have
    never dated the page -- the directory has a stand-in for that case, but it
    is an ordering device and is not a date anybody can be shown.

    `modified_date` is the same page's latest revision, and is the field that
    answers whether a script is still looked after. It has no stand-in at all:
    nothing orders by it, so an undated page publishes no date rather than
    borrowing one from when this catalogue last read the wiki.

    `user_docs_url` is the page beside the script, when `backend.userscript_docs`
    found one there. It is a transcription too -- the wiki was asked whether that
    page exists and said yes -- and it is omitted, never guessed at, for the
    scripts whose authors documented them somewhere else or not at all.

    `_lifecycle` is the exception, and is marked as one by its underscore: it is
    Evolved's reading of the directory's tier rather than anything the wiki
    published.
    """
    record: dict[str, Any] = {
        "name": tool_name(entry.wiki, entry.owner, entry.basename),
        "title": entry.basename,
        "url": wiki_sources.page_url(entry.wiki, entry.title),
        "tool_type": TOOL_TYPE,
        "for_wikis": [entry.wiki],
        "repository": f"{wiki_sources.page_url(entry.wiki, entry.title)}?action=raw",
        "_lifecycle": LIFECYCLE_ACTIVE if entry.tier == TIER_ACTIVE else LIFECYCLE_ARCHIVED,
    }
    if created := wiki_replica.iso_timestamp(entry.created_at_wiki or ""):
        record["created_date"] = created
    if touched := wiki_replica.iso_timestamp(entry.touched_at_wiki or ""):
        record["modified_date"] = touched
    if docs_title:
        record["user_docs_url"] = wiki_sources.page_url(entry.wiki, docs_title)
    if entry.owner:
        record["author"] = [{"name": entry.owner, "wiki_username": entry.owner}]
    if languages := _languages(entry.basename, content_model):
        record["technology_used"] = languages
    return record


def _describe(row: CanonicalToolCache, record: dict[str, Any], now: datetime) -> None:
    # Assigning `record` is also what sets `lifecycle`, `card_record` and
    # `search_text`; the model derives all three from it.
    row.record = record
    row.source_url = record["url"][: canonical_tools.MAX_SOURCE_URL]
    row.source = SOURCE_WIKI_USERSCRIPT
    row.sync_status = SYNC_EVOLVED_REAL
    row.fetched_at = now
    row.expires_at = now + timedelta(seconds=FRESH_SECONDS)
    row.stale_until = now + timedelta(seconds=STALE_SECONDS)


def _content_models(session: Session, wiki: str) -> dict[str, str]:
    """Return what the wiki parses each of its user-space pages as, by title."""
    rows = session.execute(
        select(UserScriptPage.title, UserScriptPage.content_model).where(UserScriptPage.wiki == wiki)
    ).all()
    return {title: model or "" for title, model in rows}


def _docs_titles(session: Session, wiki: str) -> dict[str, str]:
    """Return the documentation page found beside each of one wiki's script pages.

    Only the pages that have one. A page the wiki was asked about and had no
    answer for is stored as an empty string, and is left out here so that the
    record builder sees the same absence for "asked, and there is none" as for
    "never asked" -- both publish no `user_docs_url`, which is the only correct
    thing to publish in either case.
    """
    rows = session.execute(
        select(UserScriptPage.title, UserScriptPage.docs_title).where(
            UserScriptPage.wiki == wiki, UserScriptPage.docs_title != ""
        )
    ).all()
    return {title: docs for title, docs in rows if docs}


def _wanted(
    entries: list[UserScriptDirectoryEntry],
    models: dict[str, str],
    docs: dict[str, str],
    counts: dict[str, int],
) -> dict[str, dict[str, Any]]:
    """Return the record each catalogue name should hold."""
    wanted: dict[str, dict[str, Any]] = {}
    for entry in entries:
        counts["originals"] += 1
        model = models.get(entry.title, "")
        if model in STYLESHEET_MODELS:
            # A user stylesheet. It belongs in the directory, which describes
            # user space, and not in a catalogue of tools. See the module
            # docstring: the wiki's own content model settles this, and the
            # count is here so that the exclusion is visible in the job log
            # rather than being a silent difference between two numbers.
            counts["stylesheet"] += 1
        elif not (name := tool_name(entry.wiki, entry.owner, entry.basename)):
            counts["unnamed"] += 1
        elif name in wanted:
            # Two page titles that slug to one catalogue name. The first wins,
            # as it does everywhere else in this lane, and the loss is counted
            # rather than silently absorbed.
            counts["duplicate"] += 1
        else:
            wanted[name] = toolinfo_record(entry, model, docs.get(entry.title, ""))
    return wanted


def _write(
    session: Session, wiki: str, entries: list[UserScriptDirectoryEntry], now: datetime
) -> tuple[dict[str, int], list[str]]:
    counts = dict.fromkeys(COUNT_FIELDS, 0)
    wanted = _wanted(entries, _content_models(session, wiki), _docs_titles(session, wiki), counts)
    prefix = canonical_tools.escape_like(wiki_prefix(wiki))
    ours = {
        row.tool_name: row
        for row in session.execute(
            select(CanonicalToolCache).where(
                CanonicalToolCache.source == SOURCE_WIKI_USERSCRIPT,
                CanonicalToolCache.tool_name.like(f"{prefix}%", escape="\\"),
            )
        ).scalars()
    }
    for name, record in wanted.items():
        row = ours.get(name) or session.get(CanonicalToolCache, name)
        if row is not None and row.source != SOURCE_WIKI_USERSCRIPT:
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
        # The page is gone from the wiki, or has stopped being an original, or
        # has turned out to be a stylesheet. Either way the only thing that ever
        # asserted this tool exists has stopped saying so.
        session.delete(ours[name])
        counts["retired"] += 1
    return counts, retired


def live(session: Session, wiki: str) -> list[UserScriptDirectoryEntry]:
    """Return every original the last projection filed for one wiki."""
    return list(
        session.execute(select(UserScriptDirectoryEntry).where(UserScriptDirectoryEntry.wiki == wiki)).scalars()
    )


def synchronize(wiki: str) -> dict[str, Any]:
    """Bring one wiki's catalogue entries in step with its projected directory.

    Reads no wiki. The census is the only thing in this lane that talks to
    MediaWiki; this rebuilds records from what the directory concluded, so
    re-deciding what counts as a tool costs seconds and never depends on a wiki
    being reachable.
    """
    from backend import api_cache, catalog_facets  # noqa: PLC0415 - avoid backend startup cycles.
    from backend.people_reconcile import enqueue_tool_names_in_session  # noqa: PLC0415

    now = utcnow()
    with db.session_scope() as session:
        counts, retired = _write(session, wiki, live(session, wiki), now)
        if retired:
            enqueue_tool_names_in_session(session, retired, reason="userscript_retired")
        if counts["written"] or retired:
            catalog_facets.mark_dirty(session)
    for name in retired:
        api_cache.invalidate_tool(name)
    return {"wiki": wiki, **counts}
