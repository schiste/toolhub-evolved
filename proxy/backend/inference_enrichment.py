# SPDX-License-Identifier: GPL-3.0-or-later
"""Read a description and keywords off a tool's own source, for tools that have none.

Every wiki lane in this catalogue is a transcription: it publishes what the
wiki already says and nothing else, which is why `description` and `keywords`
sit at exactly 0% across 48,299 user scripts and gadgets while `repository`,
`tool_type` and `for_wikis` sit at 100%. Those two fields are not missing
because nobody collected them. They are missing because no wiki page states
them, and no amount of further crawling will produce one.

So this module does the one thing the rest of the catalogue refuses to do: it
asks a language model to read the source and say what the tool is for. That
makes every value here categorically weaker than anything else in the
projection, and the design follows from that:

* It only ever writes into a gap. `catalog_projection.FILL_ONLY_SOURCES` makes
  that structural rather than a promise -- a human correction, the canonical
  Toolhub record and any toolinfo.json all beat this source, and for list
  fields this source cannot even extend what they said.
* It asks for two fields, not twelve. `tool_type`, `technology_used` and
  `for_wikis` are already derived deterministically from the wiki and are
  already at 100%; asking a model to guess at them buys nothing and creates a
  way for a guess to contradict a known-true value.
* It ignores the model's own confidence. Measured on
  `User:Anomie/linkclassifier.js`, the model reported 0.9 for an `audience` it
  got wrong and 0.9 for a `for_wikis` it inferred from where the page was
  hosted rather than from the code. Self-reported confidence tracks fluency,
  not correctness, and feeding it into `SOURCE_CONFIDENCE` would launder a
  guess into a ranked fact. `accept()` applies shape rules instead, which are
  checkable.

Re-inference is keyed on `UserScriptPage.fingerprint`. A page whose body has
not changed is never sent twice, because the answer would not change either
and the corpus is large enough that resending it is the whole cost.
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING, Any, NamedTuple

import requests
from sqlalchemy import func, select

from backend import db, digests, userscripts
from backend.models import ToolInference, UserScriptPage, utcnow
from backend.userscript_toolinfo import tool_name

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

# One tool per request. Batching several tools into one prompt saves tokens and
# reliably produces answers that describe the wrong tool, because nothing in
# the response ties a description back to a name.
BATCH = 200

# `body` is truncated rather than skipped. A 200 KB script is not more
# informative than its first 24 KB for the purpose of saying what it does, and
# the tail is usually data tables.
MAX_SOURCE_CHARS = 24_000
MIN_SOURCE_CHARS = 120

MIN_DESCRIPTION_CHARS = 20
MAX_DESCRIPTION_CHARS = 600
MAX_KEYWORDS = 8
MIN_KEYWORD_CHARS = 2
MAX_KEYWORD_CHARS = 40


class Candidate(NamedTuple):
    """One page the sweep may ask about, with everything the request needs."""

    tool_name: str
    page_id: int
    wiki: str
    title: str
    body: str
    fingerprint: str


STATUS_READY = "ready"
STATUS_REJECTED = "rejected"
STATUS_ERROR = "error"

MAX_DETAIL_CHARS = 500

DEFAULT_USER_AGENT = "toolhub-evolved/0.2 (catalogue enrichment)"
DEFAULT_TIMEOUT_SECONDS = 60

# Refuses a keyword that is a URL, a bare number, or punctuation soup. Keywords
# are facet values: one bad one becomes a permanent entry in the facet sidebar
# for everyone, which a bad description never does.
# Character set only -- length is checked separately, so the bounds live in one
# place rather than half here and half in a quantifier.
_KEYWORD_RE = re.compile(r"^[a-z0-9][a-z0-9 .+#/-]*$")
_URL_LIKE = re.compile(r"https?://|www\.", re.IGNORECASE)

# A model that cannot answer sometimes says so in prose instead of returning
# null. Unguarded, that sentence becomes the tool's description and reads on
# the tool page as though the tool were unclear, rather than the reading of it.
REFUSAL_OPENERS = ("i cannot", "i can't", "as an ai", "unable to determine", "the source does not")

SYSTEM_PROMPT = (
    "You extract Wikimedia toolinfo metadata from source code. "
    "You answer with a single JSON object and nothing else: no prose, no markdown fence. "
    "You never invent facts. If the source does not support a field, use null for "
    "description and [] for keywords. Prefer null over a guess."
)


def build_prompt(wiki: str, title: str, body: str) -> str:
    """Return the user turn asking what one page's script is for."""
    return (
        "Below is the complete source of a Wikimedia user script.\n\n"
        f"Page: {title}\nWiki: {wiki}\n\n"
        "Return a JSON object with exactly these two keys:\n\n"
        '- "description": 1-3 sentences of plain text saying what the tool does for the '
        "person who runs it. Describe observable behaviour, not implementation. No marketing. "
        "null if the source does not make it clear.\n"
        f'- "keywords": array of up to {MAX_KEYWORDS} lowercase topical tags. [] if unclear. '
        'Do not include "user script", the wiki name, or the author name.\n\n'
        "SOURCE:\n```javascript\n" + body[:MAX_SOURCE_CHARS] + "\n```"
    )


def payload_for(model: str, wiki: str, title: str, body: str) -> dict[str, Any]:
    """Return the OpenAI-compatible chat body for one page."""
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(wiki, title, body)},
        ],
        # Low but not zero: at 0 the model repeats a stock opening clause across
        # unrelated scripts, which reads as boilerplate in a directory listing.
        "temperature": 0.2,
        "max_tokens": 700,
    }


def model_text(response: object) -> str:
    """Return the assistant message from a chat-completions response, or ""."""
    if not isinstance(response, dict):
        return ""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, str) else ""


def parse_json(text: str) -> dict[str, Any] | None:
    """Return the JSON object in a model reply, tolerating a markdown fence.

    A fence is the one deviation worth absorbing: the instruction not to emit
    one holds most of the time, and a reply that is otherwise perfect is not
    worth discarding over three backticks. Anything else that fails to parse is
    rejected rather than repaired, because a reply this module had to guess at
    is a reply it cannot vouch for.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        parts = stripped.split("```")
        if len(parts) < 2:  # noqa: PLR2004 - an unterminated fence has no body to read
            return None
        stripped = parts[1]
        stripped = stripped.removeprefix("json")
    try:
        parsed = json.loads(stripped.strip())
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _description(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    if len(text) < MIN_DESCRIPTION_CHARS or len(text) > MAX_DESCRIPTION_CHARS:
        return ""
    lowered = text.casefold()
    if any(lowered.startswith(opener) for opener in REFUSAL_OPENERS):
        return ""
    return text if not _URL_LIKE.search(text) else ""


def _keywords(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    found: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        tag = " ".join(item.split()).casefold()
        if len(tag) < MIN_KEYWORD_CHARS or len(tag) > MAX_KEYWORD_CHARS:
            continue
        if not _KEYWORD_RE.fullmatch(tag) or _URL_LIKE.search(tag):
            continue
        if tag not in found:
            found.append(tag)
        if len(found) == MAX_KEYWORDS:
            break
    return found


# The only fields this source may ever produce, each with what it has to survive.
# An allowlist rather than a denylist: a model that volunteers `license` or
# `tool_type` is answering a prompt that drifted, and storing it would let a
# later reader assume it was asked for. `tool_type`, `technology_used` and
# `for_wikis` in particular are already derived deterministically and sit at
# 100% on this lane -- a guess there could only contradict something known.
FIELDS: dict[str, Any] = {"description": _description, "keywords": _keywords}


def accept(parsed: dict[str, Any] | None) -> dict[str, Any]:
    """Return only the fields that survive shape validation.

    A field that fails validation is simply absent, which the projection reads
    as a gap this source declined to fill. There is deliberately no partial or
    provisional state: a value is either good enough to publish under a person's
    nose or it is not stored at all.
    """
    if not parsed:
        return {}
    return {field: validated for field, check in FIELDS.items() if (validated := check(parsed.get(field)))}


def pending(session: Session, *, limit: int = BATCH) -> list[Candidate]:
    """Return the pages whose current source has never been read by the model.

    The selection is a left join against `tool_inference` on (page, fingerprint)
    keeping the misses, so a sweep over an already-enriched corpus reads an
    index rather than 37,791 bodies. Doing it in Python instead -- load every
    stored fingerprint, walk the pages, compare -- is the same answer and reads
    the whole 1.8 GB table to get it.

    Named columns rather than entities for the same reason: `body` is the bulk
    of that table, and `limit` of them is already several megabytes.

    The filter is "no inference for these bytes yet", not "no description in the
    projection". The projection is rebuilt from its sources, so reading it here
    would make what this worker asks about depend on when it last ran.
    """
    stale = (
        select(
            UserScriptPage.id,
            UserScriptPage.wiki,
            UserScriptPage.title,
            UserScriptPage.owner,
            UserScriptPage.basename,
            UserScriptPage.body,
            UserScriptPage.fingerprint,
        )
        .outerjoin(
            ToolInference,
            (ToolInference.page_id == UserScriptPage.id)
            & (ToolInference.source_fingerprint == UserScriptPage.fingerprint),
        )
        .where(
            UserScriptPage.role == userscripts.ROLE_SCRIPT,
            UserScriptPage.deleted_at.is_(None),
            ToolInference.tool_name.is_(None),
        )
        .order_by(UserScriptPage.id)
        .limit(limit)
    )
    found: list[Candidate] = []
    for page_id, wiki, title, owner, basename, body, fingerprint in session.execute(stale):
        # Both skips are permanent for these bytes but leave no row, so they are
        # re-evaluated every sweep. That is deliberate: they are cheap, they
        # happen before the model is involved, and a page that grows a body or
        # gains a name that slugs to something should become eligible without
        # a backfill.
        if not body or len(body) < MIN_SOURCE_CHARS:
            continue
        if not (name := tool_name(wiki, owner, basename)):
            continue
        found.append(Candidate(name, int(page_id), wiki, title, body, fingerprint or ""))
    return found


class Outcome(NamedTuple):
    """What came of asking about one page: the accepted fields, or why none were."""

    status: str
    accepted: dict[str, Any]
    detail: str = ""


def record(session: Session, candidate: Candidate, outcome: Outcome, *, model: str) -> None:
    """Write one outcome, replacing whatever was stored for this tool.

    Replace rather than append: this table answers "what does the model say
    about this tool now", and a history of superseded guesses is not evidence of
    anything -- the source it was read from is already gone by then.
    """
    row = session.get(ToolInference, candidate.tool_name)
    if row is None:
        row = ToolInference(tool_name=candidate.tool_name)
        session.add(row)
    row.payload = outcome.accepted
    row.page_id = candidate.page_id
    row.source_fingerprint = candidate.fingerprint
    row.model = model[:64]
    row.status = outcome.status
    row.detail = outcome.detail[:MAX_DETAIL_CHARS]
    row.checked_at = utcnow()


def _counts() -> dict[str, int]:
    return {"asked": 0, "ready": 0, "rejected": 0, "error": 0}


def ask_one(
    session: Session,
    candidate: Candidate,
    ask: Callable[[dict[str, Any]], Any],
    *,
    model: str,
    counts: dict[str, int],
) -> None:
    """Ask about one page and store the outcome. Never raises.

    A failure for one page is recorded against that page and counted, per
    `backend.job_contract`: a per-item failure is a durable observation, not a
    reason to stop enriching the rest. It is stored rather than only logged so
    the next sweep can see this page was tried, instead of retrying it ahead of
    pages nobody has tried yet.
    """
    counts["asked"] += 1
    try:
        response = ask(payload_for(model, candidate.wiki, candidate.title, candidate.body))
    except Exception as exc:  # noqa: BLE001 - one page's outage must not end the sweep
        record(session, candidate, Outcome(STATUS_ERROR, {}, f"{type(exc).__name__}: {exc}"), model=model)
        counts["error"] += 1
        return
    accepted = accept(parse_json(model_text(response)))
    status = STATUS_READY if accepted else STATUS_REJECTED
    record(session, candidate, Outcome(status, accepted), model=model)
    counts["ready" if accepted else "rejected"] += 1


def infer(
    session: Session,
    ask: Callable[[dict[str, Any]], Any],
    *,
    model: str,
    limit: int = BATCH,
) -> dict[str, int]:
    """Run one pass inside a single session. Returns counts.

    `ask` is injected so this, the Toolforge sweep and a one-off preflight all
    drive the same validation path -- the part worth exercising is what happens
    to the answer, not how it arrived.
    """
    counts = _counts()
    for candidate in pending(session, limit=limit):
        ask_one(session, candidate, ask, model=model, counts=counts)
    return counts


def liftwing_caller() -> Callable[[dict[str, Any]], Any]:
    """Return an `ask` bound to the configured Lift Wing endpoint.

    Reuses `digests.clean_liftwing_endpoint`, which is the allowlist that keeps
    inference on Wikimedia's own public `llm-*` surface. Sharing it matters more
    than the few lines it saves: two independent notions of "an acceptable
    inference endpoint" is how one of them ends up pointing somewhere else.

    Raises `RuntimeError` when nothing is configured. That is a failed sweep, not
    a per-item failure -- there is no point recording 200 identical errors
    against 200 pages when none of them was the problem.
    """
    raw_endpoint = os.environ.get("LIFTWING_API_URL", "").strip()
    model = os.environ.get("LIFTWING_MODEL", "").strip()
    if not raw_endpoint or not model:
        message = "LIFTWING_API_URL and LIFTWING_MODEL must both be set to enrich from source"
        raise RuntimeError(message)
    endpoint = digests.clean_liftwing_endpoint(raw_endpoint, model=model)
    user_agent = digests.clean_header_value(
        "LIFTWING_USER_AGENT",
        os.environ.get("LIFTWING_USER_AGENT", DEFAULT_USER_AGENT),
    )
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": user_agent,
        "Api-User-Agent": user_agent,
    }
    timeout = max(1, int(os.environ.get("LIFTWING_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)))

    def ask(payload: dict[str, Any]) -> Any:  # noqa: ANN401 - the model's reply is untrusted JSON
        response = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.json()

    return ask


def configured_model() -> str:
    """Return the configured model name, or "" when inference is switched off."""
    return os.environ.get("LIFTWING_MODEL", "").strip()


def sweep(limit: int = BATCH) -> dict[str, Any]:
    """Run one enrichment pass and return counts plus stored coverage.

    Committing per page rather than once at the end: a sweep of 200 pages is
    several minutes of network, and a job killed partway through should keep the
    answers it already paid for. Each page's row is independent, so there is no
    consistency to preserve across them.
    """
    ask = liftwing_caller()
    model = configured_model()
    counts = _counts()
    with db.session_scope() as session:
        candidates = pending(session, limit=limit)
    for candidate in candidates:
        with db.session_scope() as session:
            ask_one(session, candidate, ask, model=model, counts=counts)
    return {"counts": counts, "model": model, "coverage": coverage()}


def coverage() -> dict[str, int]:
    """Return how much of the user-script lane has been read, by outcome."""
    with db.session_scope() as session:
        by_status = dict(
            session.execute(select(ToolInference.status, func.count()).group_by(ToolInference.status)).all()
        )
        eligible = session.execute(
            select(func.count())
            .select_from(UserScriptPage)
            .where(
                UserScriptPage.role == userscripts.ROLE_SCRIPT,
                UserScriptPage.deleted_at.is_(None),
            )
        ).scalar_one()
    return {
        "eligiblePages": int(eligible),
        "ready": int(by_status.get(STATUS_READY, 0)),
        "rejected": int(by_status.get(STATUS_REJECTED, 0)),
        "error": int(by_status.get(STATUS_ERROR, 0)),
    }
