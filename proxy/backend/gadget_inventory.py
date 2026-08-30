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
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from sqlalchemy.orm import Session

MAX_NAME_CHARS = 255
# A definition page is one wiki page; a wiki declaring more gadgets than this
# has something wrong with it, and an unbounded read is not the way to find out.
MAX_GADGETS = 2000
# How many interface messages one request may ask for. `ammessages` is a
# multi-value parameter, and the API caps those at 50 for an anonymous client.
# A wiki like frwiki declares 445 gadgets, so descriptions cost a handful of
# requests where the definition page costs one.
MESSAGE_BATCH = 50
# A description is a sentence for a preferences screen. Anything past this is a
# manual somebody pasted into the message, and a catalogue card cannot show it.
MAX_DESCRIPTION_CHARS = 1000

# Options whose presence alone is the fact, kept out of the free-form blob so
# the whole table can be filtered on them.
OPTION_HIDDEN = "hidden"
OPTION_DEFAULT = "default"
OPTION_RIGHTS = "rights"

# Every count one ingest reports, so a run that read nothing still answers
# the same questions as one that read a whole wiki.
COUNT_FIELDS = ("declared", "added", "updated", "folded", "retired", "described")

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


def message_params(names: Sequence[str]) -> dict[str, Any]:
    """Parameters asking for the interface messages that describe these gadgets.

    `amincludelocal` is what makes this work at all. A gadget's description is a
    page somebody created in the MediaWiki namespace, not a message the software
    ships, and without the flag the API answers as though it did not exist.
    Enumerating by prefix is not an alternative: `amprefix=Gadget-` returns only
    the messages MediaWiki already knows about, which measured 12 on every wiki
    tried and not one of them a wiki's own. The names have to be asked for.

    `amenableparser` runs the templates and parser functions a message may be
    built from, so what arrives is the text a reader sees rather than the
    program that produces it.
    """
    return {
        "action": "query",
        "meta": "allmessages",
        "amincludelocal": "1",
        "amenableparser": "1",
        "ammessages": "|".join(f"{wiki_sources.GADGET_MESSAGE_PREFIX}{name}" for name in names),
    }


def _descriptions(
    request: Callable[[str, str, dict[str, Any]], Any], wiki: str, names: Sequence[str]
) -> dict[str, str] | None:
    """Return each gadget's own description, or None if the wiki did not answer.

    None and an empty mapping are different answers and the caller depends on
    the difference: empty means the wiki was asked and writes no descriptions,
    which should clear anything stored, while None means we learned nothing and
    must leave what is stored alone. A batch that fails part-way through
    discards the batches before it for the same reason -- a partial read would
    retire the descriptions of every gadget the request never reached.

    Replies are matched back to gadget names case-insensitively. Message keys
    are normalized by MediaWiki, so the name that comes back is not reliably the
    spelling that was asked for, and the definition page is the authority on how
    a gadget is spelled.
    """
    if not names:
        return {}
    wanted = {f"{wiki_sources.GADGET_MESSAGE_PREFIX}{name}".casefold(): name for name in names}
    found: dict[str, str] = {}
    for start in range(0, len(names), MESSAGE_BATCH):
        try:
            payload = request(wiki, "GET", message_params(names[start : start + MESSAGE_BATCH]))
        except Exception:  # noqa: BLE001 - one wiki failing is not the job failing
            return None
        for key, content in wiki_api.messages(payload).items():
            if (name := wanted.get(key.casefold())) is not None:
                found[name] = wiki_sources.plain_text(content)[:MAX_DESCRIPTION_CHARS]
    return found


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


def _store(
    session: Session,
    wiki: str,
    entries: tuple[wiki_sources.GadgetEntry, ...],
    described: dict[str, str] | None = None,
) -> dict[str, int | None]:
    """Write one wiki's inventory, returning what changed.

    `described` is applied separately from `_apply` because it comes from a
    different read. A wiki whose definition page answered and whose messages did
    not is a wiki we know the gadgets of and not the descriptions of, and it
    keeps the descriptions it already had.
    """
    now = utcnow()
    known = {row.name_key: row for row in session.execute(select(WikiGadget).where(WikiGadget.wiki == wiki)).scalars()}
    counts = dict.fromkeys(COUNT_FIELDS, 0) | {"declared": len(entries)}
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
        if described is not None:
            # A gadget the wiki declares but never wrote a message for is set
            # back to empty, not left holding a description the wiki has since
            # deleted. This is only reached when the messages were actually
            # read, so it can never mistake an unanswered request for a
            # retraction.
            row.description = described.get(entry.name, "")
            counts["described"] += bool(row.description)
    for key, row in known.items():
        if key not in seen and row.deleted_at is None:
            row.deleted_at = now
            counts["retired"] += 1
    if described is None:
        # No number is honest here. Zero would read as "this wiki wrote no
        # description messages", which is the one thing an unanswered request
        # cannot tell us -- the same distinction `_unread` draws for the
        # definition page, drawn again for the read that follows it.
        counts["described"] = None
    return counts


def _unread(wiki: str, reason: str) -> dict[str, Any]:
    """Report a wiki that told us nothing, which is not a wiki with no gadgets.

    The reason is the difference between a wiki that refused us and a payload
    we failed to read: both retire nothing and both count zero, so without it
    a lane that has silently read every page as empty looks exactly like a
    lane whose wikis are all down.
    """
    # `described` is absent rather than zero for the same reason the counts
    # above are qualified by `reason`: a wiki we never read told us nothing
    # about its descriptions either.
    return {"wiki": wiki, "read": False, "reason": reason, **dict.fromkeys(COUNT_FIELDS, 0), "described": None}


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
    described = _descriptions(request, wiki, [entry.name for entry in entries[:MAX_GADGETS]])
    with db.session_scope() as session:
        counts = _store(session, wiki, entries, described)
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
