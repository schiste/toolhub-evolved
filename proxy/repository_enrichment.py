# SPDX-License-Identifier: GPL-3.0-or-later
"""Fetch what source hosts publish about the repositories Evolved already scans.

A separate lane from repository-analysis on purpose. That one is CPU and disk
bound, runs two streams at one clone per second, and derives everything from
files it read itself. This one is rate bound, spends a shared credential, and
records a third party's assertions. Sharing a loop would mean a clone that
stalls also stalls the rate budget accounting, and a host that starts 403ing
would look like a scan failure.

The budget is the whole design. GitHub allows 5000 authenticated requests an
hour and the same token publishes user-submitted issue reports, so this lane
must never be the reason that fails. Three things keep it clear: conditional
requests (a 304 is not charged at all), a reserve floor it refuses to spend
below, and a per-run cap so a cold catalog cannot drain an hour in one pass.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta
from hashlib import sha256
from http import HTTPStatus
from typing import Any

import requests
from sqlalchemy import select

from backend import db, job_runner, outbound, source_hosts
from backend.models import RepositoryAnalysisState, RepositoryHostMetadata, utcnow
from backend.sync import clean_error

# How many repositories one pass may look at. At worst three requests each,
# well inside an hourly 5000 even before the 304s that most polls become.
DEFAULT_LIMIT = 200

# Requests left on the token that this lane will not touch. The same credential
# publishes user-submitted issue reports, and a background refresh must never
# be the reason a person's report fails.
RESERVE_REMAINING = 1000

# How long a successfully fetched repository stays fresh. Archive state and
# license move on the scale of months; stars and pushes are re-read at this
# cadence and no faster, because none of them is worth a request per hour.
REFRESH_AFTER_HOURS = 24

MAX_BACKOFF_HOURS = 24
BACKOFF_EXPONENT_CAP = 5
MAX_ERROR_CHARS = 500

STATUS_PENDING = "pending"
STATUS_CURRENT = "current"
STATUS_UNSUPPORTED = "unsupported"
STATUS_MISSING = "missing"
STATUS_ERROR = "error"

CALLER = outbound.Caller(
    user_agent="toolhub-evolved-source-hosts (https://toolhub-evolved.toolforge.org)",
    accept="application/json",
    scheme_error="only known source-host APIs are fetched",
)

# GitHub is the only host this token belongs to. Sending it anywhere else would
# hand a credential to a service that never issued one, so the provider is
# checked rather than the request simply being authenticated by default.
TOKEN_PROVIDERS = frozenset({source_hosts.PROVIDER_GITHUB})

RATE_LIMITED = frozenset({HTTPStatus.FORBIDDEN, HTTPStatus.TOO_MANY_REQUESTS})
GONE = frozenset({HTTPStatus.NOT_FOUND, HTTPStatus.GONE})


def _token() -> str:
    """Return the shared GitHub token, or an empty string when unconfigured."""
    return os.environ.get("TOOLHUB_GITHUB_TOKEN", "").strip()


def _url_hash(url: str) -> str:
    """Return the index-safe key for a repository URL (see api_cache._key)."""
    return sha256(url.encode("utf-8")).hexdigest()


def _backoff(attempts: int) -> timedelta:
    """Return the wait after `attempts` consecutive failures, capped at a day."""
    return timedelta(hours=min(2 ** min(attempts, BACKOFF_EXPONENT_CAP), MAX_BACKOFF_HOURS))


@dataclass
class Budget:
    """What the lane may still spend, and why it stopped when it did.

    `remaining` is None until a host tells us: only GitHub reports a budget, and
    an unknown budget is not an exhausted one. Once a number arrives it is
    believed, because the host is the authority on its own accounting.
    """

    reserve: int = RESERVE_REMAINING
    remaining: int | None = None
    spent: int = 0
    exhausted: bool = False

    def observe(self, headers: dict[str, str]) -> None:
        """Record one request against the budget and read back what is left."""
        self.spent += 1
        reported = headers.get("x-ratelimit-remaining", "")
        if reported.isdigit():
            self.remaining = int(reported)

    def depleted(self) -> bool:
        """Report whether the lane has reached the floor it will not spend below."""
        return self.exhausted or (self.remaining is not None and self.remaining <= self.reserve)


@dataclass
class Results:
    """What one pass did, in the shape the job summary prints."""

    considered: int = 0
    fetched: int = 0
    unchanged: int = 0
    unsupported: int = 0
    missing: int = 0
    errors: int = 0
    requests: int = 0
    stopped_on_budget: bool = False
    remaining: int | None = None
    errors_seen: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """Return the operator-facing payload for this pass."""
        return {
            "considered": self.considered,
            "fetched": self.fetched,
            "unchanged": self.unchanged,
            "unsupported": self.unsupported,
            "missing": self.missing,
            "errors": self.errors,
            "requests": self.requests,
            "stoppedOnBudget": self.stopped_on_budget,
            "rateLimitRemaining": self.remaining,
            "sampleErrors": self.errors_seen[:5],
        }


@dataclass
class Lane:
    """One pass in flight: the connection it reuses, its budget, and its tally."""

    http: requests.Session
    budget: Budget
    results: Results


def _fetch(
    lane: Lane, url: str, ref: source_hosts.ProjectRef, *, etag: str | None = None
) -> outbound.ApiResponse | None:
    """Make one budgeted API request, or None when the lane must stop or failed."""
    if lane.budget.depleted():
        return None
    token = _token() if ref.provider in TOKEN_PROVIDERS else ""
    response = outbound.fetch_api(lane.http, url, caller=CALLER, token=token or None, etag=etag)
    lane.budget.observe(response.headers)
    if response.status_code in RATE_LIMITED:
        # A 403 here is nearly always the budget rather than the credential, and
        # the two are indistinguishable without reading the body. Treating it as
        # the budget is the safe reading: it stops, where a wrong guess the
        # other way would keep hammering a host that just said no.
        lane.budget.exhausted = True
        return None
    return response


def _counts(lane: Lane, ref: source_hosts.ProjectRef) -> tuple[int | None, int | None]:
    """Read the contributor and commit totals, for the hosts that publish them.

    Both come from the headers of a one-item page. Nothing here reads a
    contributor body: on GitLab that body carries author email addresses, and
    this project stores none.
    """
    caps = source_hosts.capabilities(ref)
    contributors = commits = None
    if caps.contributor_count:
        response = _fetch(lane, source_hosts.contributor_count_url(ref), ref)
        if response is not None and response.status_code == HTTPStatus.OK:
            contributors = source_hosts.count_from_response(
                ref, response.headers, source_hosts.decode_payload(ref, response.body)
            )
    if caps.commit_count:
        response = _fetch(lane, source_hosts.commit_count_url(ref), ref)
        if response is not None and response.status_code == HTTPStatus.OK:
            commits = source_hosts.count_from_response(
                ref, response.headers, source_hosts.decode_payload(ref, response.body)
            )
    return contributors, commits


def _row(s: Any, url: str) -> RepositoryHostMetadata:  # noqa: ANN401 - SQLAlchemy session
    """Return this repository's row, creating it on first sight."""
    key = _url_hash(url)
    row = s.get(RepositoryHostMetadata, key)
    if row is None:
        # The column defaults are applied by INSERT, so a row that has been
        # constructed but not yet flushed has None where the schema promises 0.
        # Every caller here reads the row before the flush, so state it now.
        row = RepositoryHostMetadata(url_hash=key, repository_url=url, status=STATUS_PENDING, attempts=0, topics=[])
        s.add(row)
    return row


def _settle(row: RepositoryHostMetadata, status: str, *, error: str | None = None) -> None:
    """Record a terminal-for-now outcome and when to look again."""
    row.status = status
    row.last_error = clean_error(error)
    if status == STATUS_ERROR:
        row.attempts += 1
        row.next_attempt_at = utcnow() + _backoff(row.attempts)
        return
    row.attempts = 0
    # Unsupported and missing are re-decided on the ordinary refresh cadence
    # rather than never: a project can move to a supported host, or come back.
    row.next_attempt_at = utcnow() + timedelta(hours=REFRESH_AFTER_HOURS)


def _apply(row: RepositoryHostMetadata, ref: source_hosts.ProjectRef, facts: source_hosts.HostMetadata) -> None:
    """Write one normalized answer onto the row, identity included."""
    row.provider = ref.provider
    row.api = ref.api
    row.kind = ref.kind
    row.project_path = ref.path[:512]
    row.archived = facts.archived
    row.default_branch = facts.default_branch
    row.description = facts.description
    row.homepage = facts.homepage
    row.license_id = facts.license_id
    row.topics = list(facts.topics)
    row.star_count = facts.star_count
    row.fork_count = facts.fork_count
    row.open_issues_count = facts.open_issues_count
    # contributor_count and commit_count are deliberately absent: they come
    # from their own endpoints, and writing HostMetadata's always-None values
    # here would erase last week's answer every time.
    row.pushed_at = facts.pushed_at
    row.created_at_upstream = facts.created_at


def candidates(limit: int = DEFAULT_LIMIT) -> list[str]:
    """Return repository URLs due for enrichment, most overdue first.

    Sourced from RepositoryAnalysisState rather than the catalog: this lane
    enriches what the scanner already decided is a real repository URL, so it
    inherits that normalization instead of repeating it. Several tools can name
    one URL, and this deduplicates them -- one row and one fetch per repository
    is the point of keying on the URL.
    """
    now = utcnow()
    due: dict[str, RepositoryHostMetadata | None] = {}
    with db.session_scope() as s:
        urls = [
            url
            for (url,) in s.execute(
                select(RepositoryAnalysisState.repository_url)
                .where(RepositoryAnalysisState.repository_url != "")
                .distinct()
            )
            if url
        ]
        rows = {
            row.url_hash: row
            for row in s.execute(
                select(RepositoryHostMetadata).where(
                    RepositoryHostMetadata.url_hash.in_([_url_hash(url) for url in urls])
                )
            ).scalars()
        }
        for url in urls:
            row = rows.get(_url_hash(url))
            if row is not None and row.next_attempt_at is not None and row.next_attempt_at > now:
                continue
            due[url] = row
    # Never-fetched repositories first, then the longest-overdue. datetime.min
    # is a sort key here, never a stored value.
    return sorted(due, key=lambda url: (due[url] is not None, _due_order(due[url]), url))[:limit]


def _due_order(row: RepositoryHostMetadata | None) -> float:
    """Return a sort key that puts the longest-overdue repository first."""
    if row is None or row.next_attempt_at is None:
        return 0.0
    return row.next_attempt_at.timestamp()


def _enrich_one(lane: Lane, url: str) -> None:
    """Fetch and store one repository's host facts, or record why it could not."""
    lane.results.considered += 1
    ref = source_hosts.project_ref(url)
    with db.session_scope() as s:
        row = _row(s, url)
        if ref is None:
            lane.results.unsupported += 1
            _settle(row, STATUS_UNSUPPORTED)
            return
        try:
            response = _fetch(lane, source_hosts.project_url(ref), ref, etag=row.etag)
        except (ValueError, requests.RequestException) as exc:
            lane.results.errors += 1
            lane.results.errors_seen.append(f"{url}: {exc}"[:MAX_ERROR_CHARS])
            _settle(row, STATUS_ERROR, error=str(exc))
            return
        if response is None:
            # The budget stopped us before the request, or the host did. Leave
            # the row exactly as it was: not attempted is not failed, and
            # charging it an attempt would back it off for a shortage that had
            # nothing to do with this repository.
            lane.results.stopped_on_budget = True
            return
        _record(lane, s, row, ref, response)


def _record(
    lane: Lane,
    s: Any,  # noqa: ANN401 - SQLAlchemy session
    row: RepositoryHostMetadata,
    ref: source_hosts.ProjectRef,
    response: outbound.ApiResponse,
) -> None:
    """Turn one project-record response into stored facts or a recorded verdict."""
    if response.not_modified:
        # Nothing changed, and on GitHub this cost no budget at all. The counts
        # are not re-read either: they move with commits, and no commits landed.
        lane.results.unchanged += 1
        row.fetched_at = utcnow()
        _settle(row, STATUS_CURRENT)
        return
    if response.status_code in GONE:
        lane.results.missing += 1
        _settle(row, STATUS_MISSING)
        return
    if response.status_code != HTTPStatus.OK:
        lane.results.errors += 1
        message = f"{ref.provider} answered {response.status_code}"
        lane.results.errors_seen.append(f"{row.repository_url}: {message}"[:MAX_ERROR_CHARS])
        _settle(row, STATUS_ERROR, error=message)
        return
    try:
        facts = source_hosts.metadata_from_payload(ref, source_hosts.decode_payload(ref, response.body))
    except ValueError as exc:
        lane.results.errors += 1
        lane.results.errors_seen.append(f"{row.repository_url}: unreadable payload ({exc})"[:MAX_ERROR_CHARS])
        _settle(row, STATUS_ERROR, error=f"unreadable payload: {exc}")
        return
    contributors, commits = _counts(lane, ref)
    _apply(row, ref, facts)
    # A count the host did not answer this time must not erase one it answered
    # last time: the budget running out mid-repository is not evidence that a
    # project lost its contributors.
    row.contributor_count = contributors if contributors is not None else row.contributor_count
    row.commit_count = commits if commits is not None else row.commit_count
    row.etag = response.headers.get("etag") or None
    row.fetched_at = utcnow()
    lane.results.fetched += 1
    _settle(row, STATUS_CURRENT)
    s.flush()


def run(limit: int = DEFAULT_LIMIT, *, reserve: int = RESERVE_REMAINING) -> dict[str, Any]:
    """Enrich one bounded batch of repositories and report what it cost."""
    lane = Lane(http=requests.Session(), budget=Budget(reserve=reserve), results=Results())
    try:
        for url in candidates(limit):
            if lane.budget.depleted():
                lane.results.stopped_on_budget = True
                break
            _enrich_one(lane, url)
    finally:
        lane.http.close()
    lane.results.requests = lane.budget.spent
    lane.results.remaining = lane.budget.remaining
    return lane.results.summary()


def _limit() -> int:
    """Read the per-pass cap from the environment, falling back to the default."""
    raw = os.environ.get("TOOLHUB_ENRICHMENT_LIMIT", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_LIMIT


def main() -> int:
    # Per backend.job_contract: repositories this pass could not reach are
    # retried by the next one with backoff, so they are not a failed sweep.
    # Stopping on the reserve floor is likewise the design working, not an error.
    return job_runner.run_job("repository-enrichment", lambda: run(_limit()), lock=True)


if __name__ == "__main__":  # pragma: no cover - exercised through main() tests and Toolforge Jobs
    raise SystemExit(main())
