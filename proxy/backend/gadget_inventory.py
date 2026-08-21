# SPDX-License-Identifier: GPL-3.0-or-later
"""What gadgets a wiki declares, read from its definition page and stored.

One request per wiki. `MediaWiki:Gadgets-definition` is the whole inventory --
name, section, options and file set for every gadget the wiki offers -- so a
census that costs thousands of requests for user scripts costs one here.

This module is the acquisition half. It transcribes and stores; it does not
decide what deserves a catalogue entry. That judgement lives in
`gadget_toolinfo`, and keeping the two apart means the rules for what counts as
a tool can change without re-reading a single wiki.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend import db, wiki_api, wiki_sources
from backend.models import WikiGadget, utcnow
from backend.wikimedia_urls import without_format_marks

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from sqlalchemy.orm import Session

MAX_NAME_CHARS = 255
# A definition page is one wiki page; a wiki declaring more gadgets than this
# has something wrong with it, and an unbounded read is not the way to find out.
MAX_GADGETS = 2000

# Options whose presence alone is the fact, kept out of the free-form blob so
# the whole table can be filtered on them.
OPTION_HIDDEN = "hidden"
OPTION_DEFAULT = "default"
OPTION_RIGHTS = "rights"

# Every count one ingest reports, so a run that read nothing still answers
# the same questions as one that read a whole wiki.
COUNT_FIELDS = ("declared", "added", "updated", "folded", "retired")

# Why a read produced what it did. Reported on every run, including successful
# ones, so a run that read nothing says which kind of nothing it found.
REASON_READ = "read"
REASON_REQUEST_FAILED = "request-failed"
REASON_NO_DEFINITION = "no-definition"


def storage_key(name: str) -> str:
    """Return the spelling storage will compare this gadget name by.

    Production MySQL folds case and ignores invisible formatting marks;
    Python does neither. A unique index on the raw name would therefore accept
    two rows the database considers one, which is how the first Meta census
    died. Deriving the key here means the deduplication this module performs
    and the constraint the database enforces are the same question.
    """
    return without_format_marks(str(name or "")).strip().casefold()[:MAX_NAME_CHARS]


def definition_params() -> dict[str, Any]:
    """Parameters asking for the current text of a wiki's gadget definitions.

    `rvprop` must name `ids`: only the wikitext is wanted, but a revision that
    arrives without an id is discarded unread, so asking for content alone
    returns a payload this codebase treats as an empty page.
    """
    return {"action": "query", **wiki_api.DEFINITION_REVISION_PARAMS, "titles": wiki_sources.GADGET_DEFINITION_TITLE}


def _options(entry: wiki_sources.GadgetEntry) -> dict[str, list[str]]:
    return {option: list(values) for option, values in entry.options}


def _apply(row: WikiGadget, entry: wiki_sources.GadgetEntry, now: datetime) -> None:
    row.name = entry.name[:MAX_NAME_CHARS]
    row.section = entry.section[:MAX_NAME_CHARS]
    row.pages = list(entry.pages)
    row.options = _options(entry)
    row.hidden = entry.has(OPTION_HIDDEN)
    row.default_enabled = entry.has(OPTION_DEFAULT)
    row.rights = list(entry.values(OPTION_RIGHTS))
    row.last_seen_at = now
    # A gadget that came back is not gone, whatever a previous read concluded.
    row.deleted_at = None


def _store(session: Session, wiki: str, entries: tuple[wiki_sources.GadgetEntry, ...]) -> dict[str, int]:
    """Write one wiki's inventory, returning what changed."""
    now = utcnow()
    known = {row.name_key: row for row in session.execute(select(WikiGadget).where(WikiGadget.wiki == wiki)).scalars()}
    counts = {"declared": len(entries), "added": 0, "updated": 0, "folded": 0, "retired": 0}
    seen: set[str] = set()
    for entry in entries[:MAX_GADGETS]:
        key = storage_key(entry.name)
        if not key or key in seen:
            # Two declarations the database cannot tell apart. MediaWiki serves
            # the first, so the first is what the catalogue must describe.
            counts["folded"] += 1
            continue
        seen.add(key)
        row = known.get(key)
        if row is None:
            row = WikiGadget(wiki=wiki, name_key=key, first_seen_at=now)
            session.add(row)
            counts["added"] += 1
        else:
            counts["updated"] += 1
        _apply(row, entry, now)
    for key, row in known.items():
        if key not in seen and row.deleted_at is None:
            row.deleted_at = now
            counts["retired"] += 1
    return counts


def _unread(wiki: str, reason: str) -> dict[str, Any]:
    """Report a wiki that told us nothing, which is not a wiki with no gadgets.

    The reason is the difference between a wiki that refused us and a payload
    we failed to read: both retire nothing and both count zero, so without it
    a lane that has silently read every page as empty looks exactly like a
    lane whose wikis are all down.
    """
    return {"wiki": wiki, "read": False, "reason": reason, **dict.fromkeys(COUNT_FIELDS, 0)}


def ingest(request: Callable[[str, str, dict[str, Any]], Any], wiki: str) -> dict[str, Any]:
    """Read one wiki's gadget definitions and store what it declares.

    An unreadable or empty definition page retires nothing. A wiki that
    answered with an error has not told us its gadgets are gone, and treating
    silence as removal would empty the inventory on the first bad response.
    """
    try:
        payload = request(wiki, "GET", definition_params())
    except Exception:  # noqa: BLE001 - one wiki failing is not the job failing
        return _unread(wiki, REASON_REQUEST_FAILED)
    definition = wiki_api.definition_text(payload)
    if not definition.strip():
        return _unread(wiki, REASON_NO_DEFINITION)
    entries = wiki_sources.gadget_entries(definition)
    with db.session_scope() as session:
        counts = _store(session, wiki, entries)
    return {"wiki": wiki, "read": True, "reason": REASON_READ, **counts}


def live(session: Session, wiki: str) -> list[WikiGadget]:
    """Return the gadgets a wiki currently declares, ordered for stable output.

    Takes the caller's session rather than opening one: the catalogue records
    built from these rows are written in the same transaction that reads them,
    so a gadget cannot be retired between being read and being described.
    """
    return list(
        session.execute(
            select(WikiGadget)
            .where(WikiGadget.wiki == wiki, WikiGadget.deleted_at.is_(None))
            .order_by(WikiGadget.name_key)
        ).scalars()
    )
