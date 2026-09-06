# SPDX-License-Identifier: GPL-3.0-or-later
"""Read each gadget's own code, so the gadget lane has something to read.

A gadget's description message is 83 characters at the median -- one sentence,
and 2,726 of 12,777 gadgets have none at all. That is why the inference lane
reading it answers `keywords` and `audiences` and nothing else: a tech stack,
a set of interface languages or a target wiki cannot be read out of one line,
and asking anyway would produce guesses dressed as readings.

Every gadget has code, though: a median of one page and never zero, named by
the definition line the census already stores. This fetches it, on the same
terms `user_script_pages` keeps script bodies -- kept rather than analyzed and
discarded, because re-reading a wiki costs thousands of requests and the next
question about the same code should not have to pay for them again.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import requests
from sqlalchemy import select

from backend import db, outbound, wiki_api, wiki_sources
from backend.models import WikiGadget, utcnow

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

WIKI_CALLER = "gadget-source"
#: How many gadgets one run reads. Bounded like every other census pass: the
#: work is one API round trip per gadget and the wikis set the pace, not this.
DEFAULT_LIMIT = 400
#: Room for a gadget's concatenated pages. Above what the lane will send
#: anyway, so truncation here never decides what the model sees.
MAX_BODY_CHARS = 200_000


class GadgetSourceError(RuntimeError):
    """A wiki refused a query, so this run read nothing from it."""


def _titles(gadget: WikiGadget) -> tuple[str, ...]:
    """Return the full page titles a gadget's definition names.

    `pages` stores them as the definition writes them -- `HotCat.js` -- and the
    namespace is implied. Spelled out here rather than at the call site so the
    prefix lives beside the code that reads the pages.
    """
    return tuple(f"{wiki_sources.GADGET_PREFIX}{page}" for page in (gadget.pages or []) if str(page).strip())


def fingerprint(body: str) -> str:
    """Hash a gadget's code, so an unchanged re-read costs nothing downstream."""
    return hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()


def _query(session: requests.Session, url: str) -> Any:  # noqa: ANN401 - one decoded API payload
    """Run one Action API query, turning its in-band error into a failure.

    The Action API reports errors with HTTP 200 and an error object in the
    body, so a caller that only checked the status would store a rate-limited
    or lagged wiki as a gadget with no code at all -- and an empty body is
    indistinguishable from a gadget this deployment simply has not read yet.
    """
    payload = json.loads(outbound.fetch_bounded(session, url, policy=outbound.WIKI_API, caller=WIKI_CALLER))
    if code := wiki_api.api_error(payload):
        message = f"wiki API refused the query: {code}"
        raise GadgetSourceError(message)
    return payload


def _body_for(http: requests.Session, gadget: WikiGadget) -> str:
    """Return one gadget's pages concatenated, in the order its definition lists them.

    Definition order, not the order the API answers in: `titles` makes no
    promise about ordering, and a body that reshuffled itself between reads
    would change its own fingerprint without the gadget changing at all.
    """
    titles = _titles(gadget)
    if not titles:
        return ""
    found = wiki_api.revisions(_query(http, wiki_api.pages_url(gadget.wiki, titles)))
    by_title = {revision.title: revision.content for revision in found}
    parts = [f"/* {title} */\n{by_title[title]}" for title in titles if by_title.get(title)]
    return "\n\n".join(parts)[:MAX_BODY_CHARS]


def _stale(session: Session, limit: int) -> list[WikiGadget]:
    """Return the gadgets to read this run, never-read ones first."""
    return list(
        session.execute(
            select(WikiGadget)
            .where(WikiGadget.deleted_at.is_(None))
            .order_by(WikiGadget.body_fetched_at.is_(None).desc(), WikiGadget.body_fetched_at, WikiGadget.id)
            .limit(max(1, limit))
        ).scalars()
    )


def refresh(*, limit: int = DEFAULT_LIMIT) -> dict[str, int]:
    """Read and store the code of the gadgets least recently read."""
    summary = {"examined": 0, "stored": 0, "unchanged": 0, "empty": 0, "failed": 0}
    with db.session_scope() as session:
        gadgets = _stale(session, limit)
        summary["examined"] = len(gadgets)
        if not gadgets:
            return summary
        now = utcnow()
        with requests.Session() as http:
            for gadget in gadgets:
                try:
                    body = _body_for(http, gadget)
                except (GadgetSourceError, OSError, ValueError, requests.RequestException):
                    # One unreadable wiki must not end the pass: the rest of
                    # this run's gadgets are on other wikis and still readable.
                    summary["failed"] += 1
                    continue
                # Stamped even when empty, so a gadget whose pages are all
                # missing is not re-read every run forever.
                gadget.body_fetched_at = now
                if not body:
                    summary["empty"] += 1
                    continue
                digest = fingerprint(body)
                if digest == gadget.body_fingerprint:
                    summary["unchanged"] += 1
                    continue
                gadget.body = body
                gadget.body_fingerprint = digest
                summary["stored"] += 1
    return summary
