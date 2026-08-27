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
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, NamedTuple

import requests
from sqlalchemy import func, select

from backend import db, digests, run_budget, userscripts
from backend.models import ToolInference, UserScriptDirectoryEntry, UserScriptPage, utcnow
from backend.userscript_toolinfo import STYLESHEET_MODELS, tool_name

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

# One tool per request. Batching several tools into one prompt saves tokens and
# reliably produces answers that describe the wrong tool, because nothing in
# the response ties a description back to a name.
#
# Several requests at once is a different thing and is safe, because each is
# still about one tool. That is what `DEFAULT_CONCURRENCY` buys: the measured
# cost of a call is 2.1s and almost all of it is waiting, so a serial run spent
# 428 seconds of its hour and left ~48,700 pages queued behind it.
BATCH = 2_000
# How many Lift Wing calls are in flight at once. Wikimedia publishes no
# concurrency figure for the `llm-*` surface, so this starts modest and is
# tunable from the job definition rather than a deploy: raising it is a one-line
# change to jobs.yaml that can be reverted the same way if the endpoint
# complains. `MAX_CONCURRENCY` is there so a typo cannot open a hundred
# sockets against a shared Wikimedia service.
DEFAULT_CONCURRENCY = 6
MAX_CONCURRENCY = 24
# Forty minutes of the hour between runs, leaving the guard's --stale-after
# 4200 a wide margin over a run that overruns its last wave.
DEFAULT_BUDGET = 2_400

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

    It is, however, restricted to pages the directory calls originals. Role
    alone is 166,399 pages and the catalogue holds about 48,700 of them: the
    difference is per-user copies and configuration files -- 472 people with
    their own `LiveRCparam.js` -- which `userscript_directory.collapse` already
    folds onto the page they are instances of. Asking the model about each copy
    separately bought nothing that could ever be published, because only the
    original gets a catalogue record for a description to land in, and it was
    3.4x the corpus and 3.4x the Lift Wing spend. Stylesheets go for the same
    reason `userscript_toolinfo` drops them: they belong to a directory of user
    space, not to a catalogue of tools.

    The join is on `(wiki, title)`, which is the directory's unique key. The
    directory is rebuilt whole on every census run, so a page that is promoted
    to original -- or demoted out of it -- changes what this sweep asks about
    on the next tick, with no backfill.
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
        .join(
            UserScriptDirectoryEntry,
            (UserScriptDirectoryEntry.wiki == UserScriptPage.wiki)
            & (UserScriptDirectoryEntry.title == UserScriptPage.title),
        )
        .outerjoin(
            ToolInference,
            (ToolInference.page_id == UserScriptPage.id)
            & (ToolInference.source_fingerprint == UserScriptPage.fingerprint),
        )
        .where(
            UserScriptPage.role == userscripts.ROLE_SCRIPT,
            UserScriptPage.deleted_at.is_(None),
            UserScriptPage.content_model.not_in(STYLESHEET_MODELS),
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


def _ask(
    candidate: Candidate,
    ask: Callable[[dict[str, Any]], Any],
    *,
    model: str,
) -> Outcome:
    """Ask about one page and return what to store. Never raises, never touches the database.

    Split out from `ask_one` so it can run on a worker thread while every write
    stays on the one that owns the session. A failure for one page is a durable
    observation, not a reason to stop enriching the rest, per
    `backend.job_contract` -- so it comes back as an `Outcome` to store rather
    than as an exception to handle.
    """
    try:
        response = ask(payload_for(model, candidate.wiki, candidate.title, candidate.body))
    except Exception as exc:  # noqa: BLE001 - one page's outage must not end the sweep
        return Outcome(STATUS_ERROR, {}, f"{type(exc).__name__}: {exc}")
    accepted = accept(parse_json(model_text(response)))
    return Outcome(STATUS_READY if accepted else STATUS_REJECTED, accepted)


def ask_one(
    session: Session,
    candidate: Candidate,
    ask: Callable[[dict[str, Any]], Any],
    *,
    model: str,
    counts: dict[str, int],
) -> str:
    """Ask about one page, store the outcome, and return its status. Never raises.

    The outcome is stored rather than only logged so the next sweep can see this
    page was tried, instead of retrying it ahead of pages nobody has tried yet.
    """
    counts["asked"] += 1
    outcome = _ask(candidate, ask, model=model)
    record(session, candidate, outcome, model=model)
    counts[outcome.status] += 1
    return outcome.status


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

    # One `requests.Session` per worker thread, held in thread-local storage.
    # A bare `requests.post` reopens the connection -- TLS handshake included --
    # for every page, which at this concurrency is most of what the endpoint
    # sees; one shared Session across threads is the other way to get pooling
    # and is not documented as safe. Thread-local is both.
    local = threading.local()

    def ask(payload: dict[str, Any]) -> Any:  # noqa: ANN401 - the model's reply is untrusted JSON
        http = getattr(local, "session", None)
        if http is None:
            http = local.session = requests.Session()
        response = http.post(endpoint, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.json()

    return ask


def configured_model() -> str:
    """Return the configured model name, or "" when inference is switched off."""
    return os.environ.get("LIFTWING_MODEL", "").strip()


def concurrency() -> int:
    """How many Lift Wing calls this run may have in flight, from the environment."""
    try:
        wanted = int(os.environ.get("LIFTWING_CONCURRENCY", "").strip() or DEFAULT_CONCURRENCY)
    except ValueError:
        wanted = DEFAULT_CONCURRENCY
    return max(1, min(MAX_CONCURRENCY, wanted))


def sweep(limit: int = BATCH, *, budget: run_budget.Budget | None = None) -> dict[str, Any]:
    """Run one enrichment pass and return counts plus stored coverage.

    Waves rather than a single `map` over every candidate. A wave is
    `concurrency()` calls in flight, and the run checks its deadline between
    waves: a whole-batch map would have no point at which to stop, and the
    budget is what stops a run overrunning the hour. It costs the tail of each
    wave -- everyone waits for the slowest of six -- which at 2.1s a call is
    worth the two properties it buys.

    One transaction per wave, not per page and not one at the end. A sweep is
    many minutes of network and a job killed partway through should keep the
    answers it already paid Lift Wing for; a wave bounds what a kill can lose to
    the handful still in flight. Every write stays on this thread -- the workers
    only make the request -- so nothing here shares a session across threads.
    """
    ask = liftwing_caller()
    model = configured_model()
    clock = budget or run_budget.Budget(DEFAULT_BUDGET)
    width = concurrency()
    counts = _counts()
    with db.session_scope() as session:
        candidates = pending(session, limit=limit)
    enriched: list[str] = []
    with ThreadPoolExecutor(max_workers=width, thread_name_prefix="inference") as pool:
        for start in range(0, len(candidates), width):
            if not clock.remains():
                break
            wave = candidates[start : start + width]
            outcomes = list(pool.map(lambda candidate: _ask(candidate, ask, model=model), wave))
            with db.session_scope() as session:
                for candidate, outcome in zip(wave, outcomes, strict=True):
                    counts["asked"] += 1
                    counts[outcome.status] += 1
                    record(session, candidate, outcome, model=model)
                    if outcome.status == STATUS_READY:
                        enriched.append(candidate.tool_name)
    return {
        "counts": counts,
        "model": model,
        "concurrency": width,
        "spentSeconds": round(clock.spent(), 1),
        "budgeted": int(clock.seconds),
        "coverage": coverage(),
        "projection": _republish(enriched),
    }


def _republish(tool_names: list[str]) -> dict[str, int]:
    """Rebuild the projection for the tools this sweep just filled a gap on.

    Nothing else will do it soon enough. `catalog_projection.refresh_candidates`
    is a bounded backstop -- 500 tools an hour against a catalogue of tens of
    thousands -- so a description stored here would sit unread for days before
    the sweep happened to reach its tool. Every other producer refreshes what it
    changed; this is that call, made late because the import has to be, and
    kept out of the per-page loop so one rebuild failure cannot lose an answer
    the sweep already paid Lift Wing for.
    """
    if not tool_names:
        return {"requested": 0, "refreshed": 0, "changed": 0, "errors": 0}
    from backend import catalog_projection  # noqa: PLC0415 - deferred; that module imports from this one

    return catalog_projection.refresh_tool_names(tool_names)


def coverage() -> dict[str, int]:
    """Return how much of the user-script lane has been read, by outcome.

    `eligiblePages` counts exactly what `pending` would consider, copies and
    stylesheets excluded. The two have to agree: a denominator wider than the
    selection reports a sweep that can never finish, and this one read 166,399
    while the work was 48,700 -- which is how a lane three weeks from done
    looked like one that was seven weeks away.
    """
    with db.session_scope() as session:
        by_status = dict(
            session.execute(select(ToolInference.status, func.count()).group_by(ToolInference.status)).all()
        )
        eligible = session.execute(
            select(func.count())
            .select_from(UserScriptPage)
            .join(
                UserScriptDirectoryEntry,
                (UserScriptDirectoryEntry.wiki == UserScriptPage.wiki)
                & (UserScriptDirectoryEntry.title == UserScriptPage.title),
            )
            .where(
                UserScriptPage.role == userscripts.ROLE_SCRIPT,
                UserScriptPage.deleted_at.is_(None),
                UserScriptPage.content_model.not_in(STYLESHEET_MODELS),
            )
        ).scalar_one()
    return {
        "eligiblePages": int(eligible),
        "ready": int(by_status.get(STATUS_READY, 0)),
        "rejected": int(by_status.get(STATUS_REJECTED, 0)),
        "error": int(by_status.get(STATUS_ERROR, 0)),
    }
