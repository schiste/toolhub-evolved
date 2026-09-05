# SPDX-License-Identifier: GPL-3.0-or-later
"""Read a description and keywords off a tool's own source, for tools that have none.

Every wiki lane in this catalogue is a transcription: it publishes what the
wiki already says and nothing else, which is why `description` and `keywords`
sat at exactly 0% across 37,791 user scripts while `repository`, `tool_type`
and `for_wikis` sat at 100%. Those two fields are not missing because nobody
collected them. They are missing because no wiki page states them, and no
amount of further crawling will produce one.

Descriptions are read for user scripts only, and gadgets are the reason to say
so out loud. A gadget *does* have a description on the wiki -- the interface
message `MediaWiki:Gadget-<name>`, which 79% of live declared gadgets have -- so
it is read and transcribed by `backend.gadget_inventory` and never composed
here. Where a real description exists, asking a model to write a second one
would replace a maintainer's sentence with a guess at it.

Keywords are a different matter, and that is why there are two lanes. No wiki
states a gadget's keywords, so all 10,882 gadget records sit at zero of them
with nothing upstream to transcribe. The gadget lane therefore asks for
keywords and nothing else, reading the maintainer's own description rather than
source code -- `wiki_gadgets` stores no body to read. `FIELDS_BY_LANE` is what
makes "keywords only" structural rather than a property of the prompt.

So this module does the one thing the rest of the catalogue refuses to do: it
asks a language model to read the source and say what the tool is for. That
makes every value here categorically weaker than anything else in the
projection, and the design follows from that:

* It only ever writes into a gap. `catalog_projection.FILL_ONLY_SOURCES` makes
  that structural rather than a promise -- a human correction, the canonical
  Toolhub record and any toolinfo.json all beat this source, and for list
  fields this source cannot even extend what they said.
* It asks for three fields, not twelve. `tool_type`, `technology_used` and
  `for_wikis` are already derived deterministically from the wiki and are
  already at 100%; asking a model to guess at them buys nothing and creates a
  way for a guess to contradict a known-true value. `audiences` is the third
  and the only one that is a choice from a closed list rather than free text,
  which is what makes it countable -- see `PUBLISHABLE_AUDIENCES` for what was
  counted and which part of the vocabulary survived it.
* It ignores the model's own confidence. Measured on
  `User:Anomie/linkclassifier.js`, the model reported 0.9 for an `audience` it
  got wrong and 0.9 for a `for_wikis` it inferred from where the page was
  hosted rather than from the code. Self-reported confidence tracks fluency,
  not correctness, and feeding it into `SOURCE_CONFIDENCE` would launder a
  guess into a ranked fact. `accept()` applies shape rules instead, which are
  checkable. `audiences` is now asked for again despite that reading, on the
  strength of counting it rather than trusting it: the vocabulary is closed, so
  agreement with 210 human-labelled records could be measured per value, and
  only the three values that survived are published.

Re-inference is keyed on what the answer was read from: `UserScriptPage.fingerprint`
in the user-script lane, `description_fingerprint` of the gadget's message in
the gadget lane. A source that has not changed is never sent twice, because the
answer would not change either and the corpus is large enough that resending it
is the whole cost.
"""

from __future__ import annotations

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from itertools import zip_longest
from typing import TYPE_CHECKING, Any, NamedTuple

import requests
from sqlalchemy import case, func, or_, select

from backend import db, digests, gadget_toolinfo, run_budget, userscripts
from backend.models import (
    LANE_GADGET,
    LANE_USER_SCRIPT,
    ToolInference,
    UserScriptDirectoryEntry,
    UserScriptPage,
    WikiGadget,
    utcnow,
)
from backend.userscript_toolinfo import STYLESHEET_MODELS, tool_name

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

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

# How many gadget rows the window reads to find `limit` worth of work. The
# fingerprint comparison happens in Python, so rows that turn out to be
# current are only discovered after they are read; a window exactly the size
# of the wave would return nothing the moment the lane caught up. Four is the
# ratio at which one sweep still fills its wave when 3 in 4 gadgets are done.
GADGET_WINDOW_SLACK = 4
#: How many tools are handed to `refresh_tool_names` at once. It batches
#: internally, but something it holds is not released between those batches, so
#: peak memory tracks the whole list rather than one batch: 3,000 tools reached
#: 281 MiB of a 512 MiB job and 9,500 was killed outright with exit 137. Sliced
#: at 2,000 the same 9,500 plateau at 260 MiB and finish in 175s.
#:
#: This only became reachable when a sweep got productive enough to fill it. The
#: run at 10:41 on 2026-09-05 converted 9,338 records -- 3.1x its predecessor,
#: from composing prompts and widening the wave -- and died in the republish
#: that followed, having committed every answer it paid for and lost only the
#: summary saying so.
REPUBLISH_SLICE = 2_000
MIN_SOURCE_CHARS = 120
# How many pages `infer` reads source for at once. `sweep` uses its wave width
# instead, because a wave is already the unit it asks and commits in; this is
# only for the serial path, where the choice is between one query per page and
# one per chunk and neither bound is interesting.
SOURCE_CHUNK = 50

MIN_DESCRIPTION_CHARS = 20
MAX_DESCRIPTION_CHARS = 600
MAX_KEYWORDS = 8
MIN_KEYWORD_CHARS = 2
MAX_KEYWORD_CHARS = 40

# Toolhub's audience vocabulary, as `public_html/lib/core/routing.js` spells it
# for the persona facets and as all 229 human-labelled records in the catalogue
# use it. A closed list makes this a classification rather than a generation, so
# a wrong answer is a wrong *choice* and can be counted.
AUDIENCE_VOCABULARY = ("editor", "developer", "reader", "researcher", "admin", "organizer")

# ...and the part of it worth publishing. Measured 2026-09-05 against the 210
# human-labelled tools that carry a description and at most three audiences,
# asking with the whole vocabulary above:
#
#     editor      p=0.91   72/79 published labels correct
#     developer   p=0.86   49/57
#     reader      p=0.80   28/35
#     researcher  p=0.36   16/45      <- worse than a coin flip
#     admin       p=0.38    9/24
#     organizer   p=0.42    5/12
#
# The overall 0.73 hides that split entirely. Publishing only the first three
# is 149/171 = 0.87, and it is the whole vocabulary that has to be *offered* to
# get it: asked with only these three, the model pushes a research or moderation
# tool onto the nearest survivor instead of declining, and developer falls to
# 0.76 and reader to 0.74. So the model is given somewhere correct to put a tool
# this catalogue will not publish an audience for, and that answer is dropped.
#
# This is also the field the module's own header records the model getting wrong
# at a self-reported 0.9. It was: under a prompt that asked for twelve fields at
# once and took the model's word for it. What changed is not the model but the
# question -- six named choices, and only the three that survive being counted.
PUBLISHABLE_AUDIENCES = frozenset({"editor", "developer", "reader"})
MAX_AUDIENCES = 3

# Which set of questions the prompts currently ask. Bumped whenever a field is
# added to `FIELDS_BY_LANE`, and never for a wording change: it decides whether
# a stored answer is missing something, not whether it could be phrased better.
#
# `source_fingerprint` says the source has not moved. That is not the same as
# the answer being complete, and conflating them is how `audiences` shipped to a
# corpus it could not reach: 36,545 user-script rows and 9,946 gadget rows sat
# `ready` with no audience, current on their fingerprints, and no window would
# ever have offered them again. A row answered by an older prompt is re-asked
# once, in the tier below untried pages so it can only use slots nothing newer
# wanted.
PROMPT_VERSION = 1


class Candidate(NamedTuple):
    """One thing the sweep may ask about, with everything the request needs.

    Shared by both lanes because the request is the same shape either way: a
    name, some text, and the fingerprint of the text so the answer can be tied
    to what produced it. Only `lane` decides which prompt the text goes into
    and which fields the answer may carry -- see `build_prompt` and `FIELDS_BY_LANE`.
    """

    tool_name: str
    page_id: int
    wiki: str
    title: str
    body: str
    fingerprint: str
    lane: str = LANE_USER_SCRIPT
    #: The fields this row is missing, in prompt order. Defaults to everything
    #: the lane can produce, which is what a page nobody has asked about needs.
    fields: tuple[str, ...] = ()


STATUS_READY = "ready"
STATUS_REJECTED = "rejected"
STATUS_ERROR = "error"

# How long an `error` row keeps its page out of the window before the page is
# offered again. An error is a statement about the endpoint -- a 503, a
# timeout, a dropped socket -- not about the source, so freezing it forever
# turns one bad minute at Lift Wing into a tool that can never acquire a
# description: 235 pages sat that way from a burst on 2026-08-26 and no later
# sweep would ever have looked at them again. Six hours is long enough that an outage is not
# hammered by an hourly job, short enough that a page recovers the same day.
# Rejections are deliberately not retried: those are statements about the
# answer, and re-asking the same model about unchanged bytes returns it again.
# `pending` carries one bounded exception, for rejections stored before the
# reply was kept; see its docstring.
RETRY_ERROR_AFTER = timedelta(hours=6)

MAX_DETAIL_CHARS = 500
# How much of the model's reply is kept when something in it was refused. A
# well-formed answer is a few hundred characters of JSON; this is generous
# enough to hold a malformed one whole and small enough that 4,260 of them are
# a rounding error beside the bodies they were read from.
MAX_REPLY_CHARS = 2_000

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


def _description_request() -> str:
    """Return the description fragment: what one field asks for, and nothing else."""
    return (
        '- "description": 1-3 sentences of plain text saying what the tool does for the '
        "person who runs it. Describe observable behaviour, not implementation. No marketing. "
        "null if the source does not make it clear.\n"
    )


def _keywords_request() -> str:
    """Return the keywords fragment.

    English is demanded rather than hoped for. 71% of gadget descriptions are
    written in the wiki's own language, and `_KEYWORD_RE` only admits ASCII, so
    a faithful tag in Abkhaz would be dropped by shape validation and read as
    the model having failed. Asking is what makes the shape rule and the
    request agree, and it costs a user script nothing.
    """
    return (
        f'- "keywords": array of up to {MAX_KEYWORDS} lowercase topical tags, in English. '
        "[] if there is not enough to tag. "
        "Do not include the wiki name or the author name.\n"
    )


def _audiences_request() -> str:
    """Return the audiences fragment.

    The whole vocabulary is offered even though only part of it is published: a
    model given nowhere correct to put a moderation or research tool puts it
    somewhere wrong instead, which cost developer and reader 10 and 6 points of
    precision when it was measured with the short list. See
    `PUBLISHABLE_AUDIENCES`.
    """
    return (
        f'- "audiences": array of who this is for, each exactly one of {json.dumps(list(AUDIENCE_VOCABULARY))}. '
        "[] if it is not clear.\n"
        "  editor edits articles; developer writes software; reader browses Wikimedia content; "
        "researcher analyses Wikimedia data; admin performs moderation or administrative actions; "
        "organizer runs campaigns or events.\n"
    )


GADGET_SYSTEM_PROMPT = (
    "You read Wikimedia gadget metadata from the description their own wiki shows. "
    "You answer with a single JSON object and nothing else: no prose, no markdown fence. "
    "You never invent facts. If the description does not support a field, leave it empty."
)


def _lane_preamble(lane: str, wiki: str, title: str) -> str:
    """Return what a lane says before its questions: which text follows, and whose."""
    if lane == LANE_GADGET:
        return (
            f"Below is the description a Wikimedia wiki shows for one of its gadgets.\n\nGadget: {title}\nWiki: {wiki}"
        )
    return f"Below is the complete source of a Wikimedia user script.\n\nPage: {title}\nWiki: {wiki}"


def _lane_body(lane: str, body: str) -> str:
    """Return the text a lane hands over, fenced as that lane's text should be."""
    if lane == LANE_GADGET:
        return "DESCRIPTION:\n" + body[:MAX_SOURCE_CHARS]
    return "SOURCE:\n```javascript\n" + body[:MAX_SOURCE_CHARS] + "\n```"


def build_prompt(lane: str, wiki: str, title: str, body: str, fields: Sequence[str]) -> str:
    """Compose the user turn from exactly the fields this row is missing.

    Composed rather than written out per lane, because the alternative is a
    prompt per (lane x field set) and those multiply: two lanes and three fields
    is already fourteen non-empty combinations, and every one of them would have
    to be kept in step by hand. Here a field contributes one fragment wherever
    it is asked, and a row that needs one field is charged for one question.

    `fields` is ordered by the caller so the same request is byte-identical run
    to run -- a prompt that reshuffles itself would defeat any caching upstream
    and make two runs impossible to compare.
    """
    asked = [FIELDS_BY_NAME[name] for name in fields if name in FIELDS_BY_NAME]
    if not asked:
        message = f"cannot build a prompt for {lane} asking nothing"
        raise ValueError(message)
    keys = "key" if len(asked) == 1 else "keys"
    return (
        f"{_lane_preamble(lane, wiki, title)}\n\n"
        f"Return a JSON object with exactly {'this' if len(asked) == 1 else 'these'} {keys}:\n\n"
        + "".join(field.request() for field in asked)
        + "\n"
        + _lane_body(lane, body)
    )


def payload_for(model: str, candidate: Candidate) -> dict[str, Any]:
    """Return the OpenAI-compatible chat body for one candidate.

    `max_tokens` is summed from the fields actually asked for rather than fixed
    per lane. A backfill re-ask that wants only `audiences` is a hundred tokens
    of answer, not the seven hundred a fresh user script needs for three
    sentences and eight tags -- and generation is most of what a call costs.
    """
    system = GADGET_SYSTEM_PROMPT if candidate.lane == LANE_GADGET else SYSTEM_PROMPT
    user = build_prompt(candidate.lane, candidate.wiki, candidate.title, candidate.body, candidate.fields)
    ceiling = TOKEN_OVERHEAD + sum(FIELDS_BY_NAME[name].tokens for name in candidate.fields if name in FIELDS_BY_NAME)
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        # Low but not zero: at 0 the model repeats a stock opening clause across
        # unrelated scripts, which reads as boilerplate in a directory listing.
        "temperature": 0.2,
        "max_tokens": ceiling,
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
        # At least two parts, always: the fence that `startswith` just found is
        # a separator, so the body after it is `parts[1]` even when it is empty.
        stripped = stripped.split("```")[1]
        stripped = stripped.removeprefix("json")
    try:
        parsed = json.loads(stripped.strip())
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


class Checked(NamedTuple):
    """One field's verdict: the value that survived, or why nothing did.

    The reason travels with the verdict rather than being re-derived from the
    reply afterwards, so the explanation stored on a row cannot drift away from
    the rule that actually refused the value.
    """

    value: Any
    reason: str = ""


def _description(value: object) -> Checked:
    if value is None:
        return Checked("", "absent or null in the reply")
    if not isinstance(value, str):
        return Checked("", f"not a string ({type(value).__name__})")
    text = " ".join(value.split())
    if len(text) < MIN_DESCRIPTION_CHARS or len(text) > MAX_DESCRIPTION_CHARS:
        return Checked("", f"{len(text)} chars, wanted {MIN_DESCRIPTION_CHARS}-{MAX_DESCRIPTION_CHARS}")
    lowered = text.casefold()
    if any(lowered.startswith(opener) for opener in REFUSAL_OPENERS):
        return Checked("", "refusal prose rather than a description")
    if _URL_LIKE.search(text):
        return Checked("", "contains a URL")
    return Checked(text)


def _keywords(value: object) -> Checked:
    if value is None:
        return Checked([], "absent or null in the reply")
    if not isinstance(value, list):
        return Checked([], f"not a list ({type(value).__name__})")
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
    if not found:
        return Checked([], "empty list" if not value else f"none of {len(value)} passed the shape rules")
    return Checked(found)


def _audiences(value: object) -> Checked:
    """Keep the audiences that are both in the vocabulary and worth publishing.

    Two filters rather than one, and the order matters. A value outside
    `AUDIENCE_VOCABULARY` is the model ignoring the list it was given, which is
    a malformed answer. A value inside it but outside `PUBLISHABLE_AUDIENCES` is
    a well-formed answer this catalogue has measured and will not publish -- so
    it is dropped silently rather than counted as the model failing, because
    offering it is what keeps the other three honest.
    """
    if value is None:
        return Checked([], "absent or null in the reply")
    if not isinstance(value, list):
        return Checked([], f"not a list ({type(value).__name__})")
    named = [tag for item in value if isinstance(item, str) and (tag := item.strip().casefold()) in AUDIENCE_VOCABULARY]
    if not named:
        return Checked([], "empty list" if not value else f"none of {len(value)} are audiences")
    kept: list[str] = []
    for tag in named:
        if tag in PUBLISHABLE_AUDIENCES and tag not in kept:
            kept.append(tag)
        if len(kept) == MAX_AUDIENCES:
            break
    # No reason recorded: the model answered inside the vocabulary and this
    # catalogue simply does not publish that part of it. Calling that a refusal
    # would file a correct answer as a fault.
    return Checked(kept)


class Field(NamedTuple):
    """One thing the model may be asked for, and everything needed to ask it.

    An allowlist rather than a denylist: a model that volunteers `license` or
    `tool_type` is answering a prompt that drifted, and storing it would let a
    later reader assume it was asked for. `tool_type`, `technology_used` and
    `for_wikis` in particular are already derived deterministically from the
    wiki and sit at 100% -- a guess there could only contradict something known.

    Everything about a field lives on the field: the words that ask for it, the
    rule its answer has to survive, the room that answer needs, and the lanes
    that may produce it at all. Adding one is adding an entry here, and the
    sweep, the prompts and the backfill follow without being told.
    """

    name: str
    validate: Callable[[object], Checked]
    request: Callable[[], str]
    #: Room for this answer in `max_tokens`. Summed over what a prompt asks, so
    #: a row that needs one field is not charged for three.
    tokens: int
    lanes: frozenset[str]


#: Every field, in the order a prompt lists them. Ordering is fixed rather than
#: incidental: it decides the byte-for-byte prompt, and a request that
#: reshuffles itself between runs cannot be compared with the one before it.
FIELD_ORDER: tuple[Field, ...] = (
    Field("description", _description, _description_request, 500, frozenset({LANE_USER_SCRIPT})),
    Field("keywords", _keywords, _keywords_request, 200, frozenset({LANE_USER_SCRIPT, LANE_GADGET})),
    Field("audiences", _audiences, _audiences_request, 100, frozenset({LANE_USER_SCRIPT, LANE_GADGET})),
)
FIELDS_BY_NAME: dict[str, Field] = {field.name: field for field in FIELD_ORDER}
#: Room for the JSON scaffolding around the answers themselves.
TOKEN_OVERHEAD = 100


def lane_fields(lane: str) -> tuple[str, ...]:
    """Return every field this lane may produce, in prompt order.

    A gadget is not asked for a description: it already has one on the wiki --
    `MediaWiki:Gadget-<name>`, which the inventory transcribes -- and offering a
    guess where a maintainer's sentence exists is the one thing this module
    refuses to do. That exclusion is a property of the field, not of a prompt
    somebody has to remember to leave it out of.
    """
    return tuple(field.name for field in FIELD_ORDER if lane in field.lanes)


def signature(names: Iterable[str]) -> str:
    """Return the durable spelling of a set of field names.

    Sorted and comma-joined so it can be compared in SQL as a scalar. This is
    what a row records about itself, and what the window compares against: a
    row whose signature is not the lane's current one is missing something,
    which is exactly the question the window needs to ask and the one a
    payload cannot answer -- `accept` stores nothing for a field the model
    declined, so an absent value cannot be told from an unasked one.
    """
    return ",".join(sorted(set(names)))


def lane_signature(lane: str) -> str:
    """Return the signature a fully-asked row of this lane carries."""
    return signature(lane_fields(lane))


def missing_asked(asked: str | None) -> tuple[str, ...]:
    """Return the field names a stored signature already records."""
    return tuple(name for name in (asked or "").split(",") if name)


def missing_fields(lane: str, asked: str | None) -> tuple[str, ...]:
    """Return the fields this lane can produce that `asked` does not record.

    A new field is missing from every row that predates it the moment it joins
    `FIELD_ORDER`, with nothing to bump and no migration to remember -- which is
    the whole point of recording what was asked rather than what came back.
    """
    already = {name for name in (asked or "").split(",") if name}
    return tuple(name for name in lane_fields(lane) if name not in already)


def check(parsed: dict[str, Any] | None, fields: Sequence[str]) -> dict[str, Checked]:
    """Run the shape rules for exactly the fields that were asked for.

    Split from `accept` so a caller that needs to say why a reply produced
    nothing reads the same verdicts that decided it, rather than a second
    implementation of the same rules written to explain the first. Grading a
    field nobody asked about would report it absent, which is true and useless.
    """
    return {name: FIELDS_BY_NAME[name].validate((parsed or {}).get(name)) for name in fields if name in FIELDS_BY_NAME}


def accept(parsed: dict[str, Any] | None, fields: Sequence[str]) -> dict[str, Any]:
    """Return only the fields that survive shape validation.

    A field that fails validation is simply absent, which the projection reads
    as a gap this source declined to fill. There is deliberately no partial or
    provisional state: a value is either good enough to publish under a person's
    nose or it is not stored at all.
    """
    if not parsed:
        return {}
    return {name: verdict.value for name, verdict in check(parsed, fields).items() if verdict.value}


def pending(session: Session, *, limit: int = BATCH) -> list[Candidate]:
    """Return the pages whose current source the model has not answered for.

    That is the pages never asked about, plus the ones whose last answer was an
    `error` older than `RETRY_ERROR_AFTER`. The second half exists because the
    first half alone made a transport failure permanent: the join is on the
    fingerprint, so any row at all -- including one recording that Lift Wing was
    briefly unreachable -- removed the page from every future window, and the
    source had to change before it came back. Never-asked pages are ordered
    first so a retry can only ever use a slot nobody else wanted, which is what
    `ask_one` promised when it started storing failures at all.

    Plus, once, the rejections stored before `ToolInference.reply` existed. A
    rejection is normally never retried -- the bytes have not changed, so the
    same model returns the same answer at full price -- and this is not a change
    to that rule. It is the one window in which those 4,260 rows can acquire
    what a rejection is for: `detail` names the rule the answer broke, but every
    one of them recorded it against a reply nobody kept, so "description too
    short" cannot be told from "the endpoint returned an error page". The re-ask
    stores the reply, and because `record` writes that column whatever the
    outcome, the row leaves this arm permanently on its first pass through it --
    the "once" is a property of the predicate, not a counter that could drift.

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

    Candidates come back with an empty `body`; `with_source` reads it for the
    handful of pages a wave is about to ask about. Selecting it here instead
    measured 546 MB resident against a 512Mi job -- 19,390 windowed pages carry
    260 MB of source, and the driver buffers the whole result before this loop
    copies it into `found` -- and one budgeted run asks about roughly 150 of
    them, so about 99% of that was read and dropped. The job was OOM-killed
    every run from 2026-08-27 13:41, which SIGKILL made silent: no summary, no
    `job_runs` row, and a lock `tools/job_guard.sh` never got to release, so
    every other tick then skipped on a lock whose owner was long gone.
    """
    retry_before = utcnow() - RETRY_ERROR_AFTER
    stale = (
        select(
            UserScriptPage.id,
            UserScriptPage.wiki,
            UserScriptPage.title,
            UserScriptPage.owner,
            UserScriptPage.basename,
            UserScriptPage.fingerprint,
            ToolInference.asked_signature,
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
            or_(
                ToolInference.tool_name.is_(None),
                (ToolInference.status == STATUS_ERROR) & (ToolInference.checked_at < retry_before),
                (ToolInference.status == STATUS_REJECTED) & ToolInference.reply.is_(None),
                ToolInference.asked_signature != lane_signature(LANE_USER_SCRIPT),
            ),
            # Was a Python skip over an already-loaded body. In SQL it also
            # keeps pages too short to describe out of the window, instead of
            # letting them occupy a slot on every sweep forever. MySQL counts
            # bytes here and SQLite characters, so on MySQL this admits a
            # little more than it should; `with_source` re-checks exactly.
            func.length(UserScriptPage.body) >= MIN_SOURCE_CHARS,
        )
        # Untried pages first, then error retries, then the rejection backfill.
        # Each tier can only use slots the tier above it did not want, so a page
        # nobody has ever asked about is never displaced by one whose only news
        # is that the endpoint was down, and neither is displaced by a re-ask of
        # an answer that has already been read once.
        .order_by(
            case(
                (ToolInference.tool_name.is_(None), 0),
                (ToolInference.status == STATUS_ERROR, 1),
                (ToolInference.asked_signature != lane_signature(LANE_USER_SCRIPT), 2),
                else_=3,
            ),
            UserScriptPage.id,
        )
        .limit(limit)
    )
    found: list[Candidate] = []
    for page_id, wiki, title, owner, basename, fingerprint, asked in session.execute(stale):
        # This skip is permanent for this page but leaves no row, so it is
        # re-evaluated every sweep. That is deliberate: it is cheap, it happens
        # before the model is involved, and a page that gains a name that slugs
        # to something should become eligible without a backfill.
        if not (name := tool_name(wiki, owner, basename)):
            continue
        # A row selected for an error retry has answered its questions already;
        # it is here because the endpoint failed, so it is asked them all again.
        wanted = missing_fields(LANE_USER_SCRIPT, asked) or lane_fields(LANE_USER_SCRIPT)
        found.append(Candidate(name, int(page_id), wiki, title, "", fingerprint or "", LANE_USER_SCRIPT, wanted))
    return found


def description_fingerprint(description: str) -> str:
    """Return the key a gadget answer is tied to: a hash of the text it read.

    The gadget lane has no `fingerprint` column of its own to borrow -- the
    inventory stores the description and not a digest of it -- so this computes
    the same guarantee the user-script lane gets for free: an answer stays
    current exactly while the words it was read from are unchanged, and a wiki
    that rewrites its description puts that gadget back in the window.

    Whitespace is collapsed first so a reflowed message is not mistaken for a
    rewritten one; 10,049 descriptions re-asked over a stray newline would cost
    the entire lane's budget for no new answer.
    """
    return sha256(" ".join((description or "").split()).encode("utf-8")).hexdigest()


def gadget_pending(session: Session, *, limit: int = BATCH) -> list[Candidate]:
    """Return the gadgets whose current description the model has not tagged.

    A gadget is eligible on exactly one condition the user-script lane does not
    share: it has a description. 21% do not -- the wiki declares the gadget and
    never wrote `MediaWiki:Gadget-<name>` -- and for those there is no text to
    tag and nothing this lane can do, so they are excluded here rather than sent
    and rejected. That keeps `rejected` meaning "asked, and the answer was no
    good" in both lanes.

    Deliberately per gadget, not per gadget name. `hotcat` is declared on 434
    wikis with 264 distinct descriptions between them, and asking once per name
    would be 3.2x cheaper -- but it would publish one wiki's reading of a gadget
    onto 433 others that may have diverged, and tie every row to a fingerprint
    computed from text that is not theirs, so a local edit could never put the
    gadget back in the window. The saving is not worth a keyword nobody on that
    wiki can trace to their own page.

    The join is on `page_id`, not on the catalogue name: `gadget_toolinfo.tool_name`
    slugs in Python and no SQL expression reproduces it, so the id the gadget
    lane stores in `page_id` is what makes this a join rather than a scan.

    Never-asked gadgets sort first, exactly as in `pending`, and for the same
    reason -- the fingerprint cannot be compared in SQL, so once every gadget
    has an answer the window would otherwise fill with rows that are already
    current and the sweep would stall while descriptions elsewhere went stale.
    Ordering means the window holds real work while any exists, and only then
    starts re-reading answered rows to find the ones whose description moved.
    """
    rows = session.execute(
        select(WikiGadget.id, WikiGadget.wiki, WikiGadget.name, WikiGadget.description, ToolInference)
        .outerjoin(
            ToolInference,
            (ToolInference.page_id == WikiGadget.id) & (ToolInference.lane == LANE_GADGET),
        )
        .where(
            WikiGadget.deleted_at.is_(None),
            WikiGadget.description != "",
        )
        .order_by(
            case(
                (ToolInference.tool_name.is_(None), 0),
                (ToolInference.status == STATUS_ERROR, 1),
                (ToolInference.asked_signature != lane_signature(LANE_GADGET), 2),
                else_=3,
            ),
            WikiGadget.id,
        )
        .limit(limit * GADGET_WINDOW_SLACK)
    )
    found: list[Candidate] = []
    for gadget_id, wiki, name, description, row in rows:
        if not (catalog_name := gadget_toolinfo.tool_name(wiki, name)):
            continue
        fingerprint = description_fingerprint(description)
        if (
            row is not None
            and row.source_fingerprint == fingerprint
            and row.status != STATUS_ERROR
            # ...and answered by the prompt now in use. The fingerprint says the
            # wiki has not rewritten the description; it cannot say the answer
            # covers every field currently asked for.
            and row.asked_signature == lane_signature(LANE_GADGET)
        ):
            continue
        wanted = missing_fields(LANE_GADGET, row.asked_signature if row is not None else "") or lane_fields(LANE_GADGET)
        found.append(Candidate(catalog_name, int(gadget_id), wiki, name, description, fingerprint, LANE_GADGET, wanted))
        if len(found) == limit:
            break
    return found


def with_source(session: Session, candidates: Sequence[Candidate]) -> list[Candidate]:
    """Return these candidates carrying their current source, dropping the rest.

    Source is read here rather than in `pending` so that a run holds bodies for
    one wave instead of for the whole window -- see `pending` for what that
    cost. `body` and `fingerprint` are read together, so the pair stays
    consistent: recording an answer against a fingerprint the source has since
    moved past would claim the page was checked at a revision nobody asked
    about. Reading both later than the window query narrows that race rather
    than widening it, because the census can rewrite a page mid-run.

    A page can go missing between the two reads -- deleted, or shrunk below
    `MIN_SOURCE_CHARS` -- and is simply dropped. It leaves no row, so the next
    sweep reconsiders it, which is what the window query already does for a
    page whose name does not slug.
    """
    if not candidates:
        return []
    # Gadget candidates already carry their text. A description is 83 characters
    # at the median against a script's 3,785, so the memory argument that put
    # this function here does not apply to them, and re-reading would only widen
    # the window between reading the description and hashing it.
    passthrough = [candidate for candidate in candidates if candidate.lane != LANE_USER_SCRIPT]
    candidates = [candidate for candidate in candidates if candidate.lane == LANE_USER_SCRIPT]
    if not candidates:
        return passthrough
    rows = session.execute(
        select(UserScriptPage.id, UserScriptPage.body, UserScriptPage.fingerprint).where(
            UserScriptPage.id.in_([candidate.page_id for candidate in candidates])
        )
    )
    source = {int(page_id): (body, fingerprint) for page_id, body, fingerprint in rows}
    ready: list[Candidate] = list(passthrough)
    # Driven by `candidates`, not by `source`: `IN` does not promise an order,
    # and a wave that reordered itself between runs would make the sweep harder
    # to reason about for nothing.
    for candidate in candidates:
        body, fingerprint = source.get(candidate.page_id, ("", ""))
        if not body or len(body) < MIN_SOURCE_CHARS:
            continue
        ready.append(candidate._replace(body=body, fingerprint=fingerprint or ""))
    return ready


class Outcome(NamedTuple):
    """What came of asking about one page: the accepted fields, or why none were."""

    status: str
    accepted: dict[str, Any]
    detail: str = ""
    # The reply itself, where `detail` says part of it was refused. Empty when
    # nothing was: a fully accepted answer is already stored, as `accepted`, and
    # keeping the prose it arrived in beside it stores the same thing twice.
    reply: str = ""


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
    # Merged, not replaced. A re-ask now covers only what was missing, so
    # replacing would drop the description and keywords a previous run paid for
    # in order to store the one field this run went back for.
    kept = dict(row.payload) if isinstance(row.payload, dict) else {}
    row.payload = {**kept, **outcome.accepted}
    # The union, so a field asked once is never asked again on this source --
    # including one the model declined, which is an answer and not a gap.
    row.asked_signature = signature([*missing_asked(row.asked_signature), *candidate.fields])
    row.lane = candidate.lane
    row.page_id = candidate.page_id
    row.source_fingerprint = candidate.fingerprint
    row.model = model[:64]
    row.status = outcome.status
    row.detail = outcome.detail[:MAX_DETAIL_CHARS]
    # Always assigned, including the empty string. `reply` being NULL is what
    # marks a row this code has never written, and a re-ask that stores "" has
    # still answered that question -- so a row leaves the backfill window on the
    # first re-ask whatever came of it, which is what makes "once" structural
    # rather than a counter somebody has to keep.
    row.reply = outcome.reply[:MAX_REPLY_CHARS]
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
        response = ask(payload_for(model, candidate))
    except Exception as exc:  # noqa: BLE001 - one page's outage must not end the sweep
        return Outcome(STATUS_ERROR, {}, f"{type(exc).__name__}: {exc}")
    text = model_text(response)
    collapsed = " ".join(text.split())
    parsed = parse_json(text)
    if parsed is None:
        # No field-level verdict exists when nothing parsed, so the reply is its
        # own evidence: a sample is what tells a reader whether the model went
        # off-format or the endpoint returned something that was never a model
        # reply at all.
        sample = " ".join(text.split())[:200]
        return Outcome(STATUS_REJECTED, {}, f"unparsed reply: {sample or '(empty)'}", collapsed)
    verdicts = check(parsed, candidate.fields)
    accepted = {name: verdict.value for name, verdict in verdicts.items() if verdict.value}
    # Written whatever the status, not only on rejection. A reply whose keywords
    # pass and whose description does not is stored `ready` carrying no
    # description -- exactly the gap this lane exists to close, and invisible in
    # the status alone.
    detail = "; ".join(f"{field}: {verdict.reason}" for field, verdict in verdicts.items() if verdict.reason)
    # The reply follows the detail, not the status. `detail` names the rule a
    # field broke; without the words that broke it, a reader can tell that a
    # description was too short but not whether the model wrote a bad one or the
    # prompt asked for the wrong thing -- which is the difference between a
    # rejection worth fixing and one worth accepting.
    return Outcome(STATUS_READY if accepted else STATUS_REJECTED, accepted, detail, collapsed if detail else "")


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
    candidates = pending(session, limit=limit)
    for start in range(0, len(candidates), SOURCE_CHUNK):
        for candidate in with_source(session, candidates[start : start + SOURCE_CHUNK]):
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


def _interleave(scripts: list[Candidate], gadgets: list[Candidate]) -> list[Candidate]:
    """Return both lanes' work in one list, alternating while both have some.

    Alternating rather than concatenating, because concatenating starves. About
    8,000 user scripts are still unasked and `pending` returns up to `BATCH` of
    them, so a gadget placed after them would wait weeks for the older lane to
    drain -- and the gadget lane is the one with 10,882 records at zero
    keywords. Alternating gives each lane half of every wave while both have
    work, and hands the whole wave to whichever lane still has any once the
    other runs dry.
    """
    merged: list[Candidate] = []
    for pair in zip_longest(scripts, gadgets):
        merged.extend(candidate for candidate in pair if candidate is not None)
    return merged


def sweep(limit: int = BATCH, *, budget: run_budget.Budget | None = None) -> dict[str, Any]:
    """Run one enrichment pass and return counts plus stored coverage.

    Waves rather than a single `map` over every candidate. A wave is
    `concurrency()` calls in flight, and the run checks its deadline between
    waves: a whole-batch map would have no point at which to stop, and the
    budget is what stops a run overrunning the hour. It costs the tail of each
    wave -- everyone waits for the slowest of six -- which at 2.1s a call is
    worth the two properties it buys.

    Source is read a wave at a time, not with the window: `pending` returns
    bodiless candidates and `with_source` fills in the six about to be asked
    about, which is what keeps a run's resident memory flat in the size of the
    backlog rather than growing with it.

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
        candidates = _interleave(pending(session, limit=limit), gadget_pending(session, limit=limit))
    enriched: list[str] = []
    with ThreadPoolExecutor(max_workers=width, thread_name_prefix="inference") as pool:
        for start in range(0, len(candidates), width):
            if not clock.remains():
                break
            with db.session_scope() as session:
                wave = with_source(session, candidates[start : start + width])
            # Everything in this slice went away or shrank below the floor
            # since the window was read. Nothing to ask, and nothing to record.
            if not wave:
                continue
            outcomes = list(pool.map(lambda candidate: _ask(candidate, ask, model=model), wave))
            with db.session_scope() as session:
                for candidate, outcome in zip(wave, outcomes, strict=True):
                    counts["asked"] += 1
                    counts[outcome.status] += 1
                    counts[f"{candidate.lane}Asked"] = counts.get(f"{candidate.lane}Asked", 0) + 1
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

    Sliced rather than handed over whole: see `REPUBLISH_SLICE`. Nothing is lost
    by a slice that fails -- the answers are already committed, and the next
    scheduled projection pass is the backstop this call exists to front-run.
    """
    if not tool_names:
        return {"requested": 0, "refreshed": 0, "changed": 0, "errors": 0}
    from backend import catalog_projection  # noqa: PLC0415 - deferred; that module imports from this one

    totals = {"requested": 0, "refreshed": 0, "changed": 0, "errors": 0}
    for start in range(0, len(tool_names), REPUBLISH_SLICE):
        part = catalog_projection.refresh_tool_names(tool_names[start : start + REPUBLISH_SLICE])
        for key in totals:
            totals[key] += part.get(key, 0)
    return totals


def coverage() -> dict[str, int]:
    """Return how much of each lane has been read, by outcome.

    Every count is scoped to one lane, which the row counts were not when the
    gadget lane was added: `by_status` was a tally of the whole table against a
    denominator of user-script pages only, so the first gadget answered would
    have pushed `ready` toward a figure larger than `eligiblePages` and made a
    lane that is 83% read look finished. That is the same failure this
    docstring already describes in the other direction, and it is why the two
    lanes are counted separately rather than summed.

    `eligiblePages` counts exactly what `pending` would consider -- copies,
    stylesheets and pages too short to describe excluded. The two have to
    agree: a denominator wider than the selection reports a sweep that can
    never finish, and this one read 166,399 while the work was 48,700, which is
    how a lane three weeks from done looked like one seven weeks away. Every
    filter added to `pending`'s window belongs here too, which is what
    `test_the_reported_denominator_is_the_one_the_sweep_actually_works_through`
    is for.
    """
    with db.session_scope() as session:
        by_status = dict(
            session.execute(
                select(ToolInference.status, func.count())
                .where(ToolInference.lane == LANE_USER_SCRIPT)
                .group_by(ToolInference.status)
            ).all()
        )
        gadget_by_status = dict(
            session.execute(
                select(ToolInference.status, func.count())
                .where(ToolInference.lane == LANE_GADGET)
                .group_by(ToolInference.status)
            ).all()
        )
        gadgets_eligible = session.execute(
            select(func.count())
            .select_from(WikiGadget)
            .where(WikiGadget.deleted_at.is_(None), WikiGadget.description != "")
        ).scalar_one()
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
                func.length(UserScriptPage.body) >= MIN_SOURCE_CHARS,
            )
        ).scalar_one()
    return {
        "eligiblePages": int(eligible),
        "ready": int(by_status.get(STATUS_READY, 0)),
        "rejected": int(by_status.get(STATUS_REJECTED, 0)),
        "error": int(by_status.get(STATUS_ERROR, 0)),
        "gadgetsEligible": int(gadgets_eligible),
        "gadgetsReady": int(gadget_by_status.get(STATUS_READY, 0)),
        "gadgetsRejected": int(gadget_by_status.get(STATUS_REJECTED, 0)),
        "gadgetsError": int(gadget_by_status.get(STATUS_ERROR, 0)),
    }
