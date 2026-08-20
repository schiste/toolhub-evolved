# SPDX-License-Identifier: GPL-3.0-or-later
"""Fetch and deterministically analyze public repositories named by Toolhub.

Runs either as one bounded batch (``--limit``) or continuously
(``--continuous``). Continuous mode paces two independent lanes: repositories
with no usable report yet, and re-checks of already analyzed ones. The two
have different economics -- backlog work is finite and every item is real
analysis, re-check work never ends and is usually one HEAD lookup -- so giving
them one shared rate made the cheap lane crowd out the expensive one.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

import repository_enrichment
from analyze_source import _local_git_context
from backend import db, graph_enrichment, job_runner, job_runs, tool_summaries
from backend.models import (
    CanonicalToolCache,
    RepositoryAnalysisState,
    RepositoryHostMetadata,
    SourceAnalysisReport,
    User,
    utcnow,
)
from backend.source_analyzer import (
    IGNORED_SOURCE_DIRS,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_TOTAL_BYTES,
    SourceAnalysisError,
    analyze_source_files,
    is_supported_source_path,
)
from backend.sync import REVIEW_APPROVED, SOURCE_REPOSITORY_SCAN, SYNC_ERROR, SYNC_EVOLVED_REAL, clean_error
from backend.v1_common import build_local_tool_summary

if TYPE_CHECKING:
    from collections.abc import Callable

SCANNER_WM_SUB = "evolved:repository-scanner"
SCANNER_USERNAME = "Evolved repository scanner"
GIT_TIMEOUT_SECONDS = 180
MAX_CHECKOUT_BYTES = 64 * 1024 * 1024
MAX_URL_CHARS = 2000
MIN_HEAD_PARTS = 2
MIN_TREE_FIELDS = 3
MIN_BATCH_FIELDS = 2
TYPED_HEADER_FIELDS = 3
BODILESS_REPLIES = frozenset({"missing", "ambiguous"})
REGULAR_FILE_MODES = frozenset({"100644", "100755"})
EARLIEST_CHECK = datetime.min  # noqa: DTZ901 - database timestamps are stored as naive UTC.
# Continuous mode paces two streams independently. Backlog work -- tools with no
# usable report yet -- runs at one repository per second so a cold catalog and
# newly registered tools drain quickly. Re-checking already analyzed tools for
# new commits runs at one per minute, because that stream never ends and its
# only job is to notice movement. Both intervals are a minimum spacing between
# starts, not a guarantee: a clone that takes longer simply delays the next one.
BACKLOG_INTERVAL_SECONDS = 1.0
REFRESH_INTERVAL_SECONDS = 60.0
# One catalog pass fills both queues. Re-reading the whole cache per item would
# cost a full table scan every second for one row of work.
QUEUE_REFILL_SECONDS = 300.0
QUEUE_DEPTH = 500
# A line per scanned tool would be 86400 lines a day against logs that are only
# rotated nightly, so the loop reports cumulative totals on an interval instead.
HEARTBEAT_SECONDS = 300.0
SHUTDOWN_POLL_SECONDS = 0.25
SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
ALLOWED_HOSTS = frozenset(
    {
        "bitbucket.org",
        "codeberg.org",
        "github.com",
        "gitlab.com",
        "gitlab.wikimedia.org",
        "gerrit.wikimedia.org",
    }
)
ALLOWED_SUFFIXES = (".github.com", ".gitlab.com")
SUPPORTED_PROVIDERS = {
    "bitbucket.org": "bitbucket",
    "codeberg.org": "codeberg",
    "github.com": "github",
    "gitlab.com": "gitlab",
    "gitlab.wikimedia.org": "gitlab-wikimedia",
    "gerrit.wikimedia.org": "gerrit-wikimedia",
}


class RepositoryScanError(RuntimeError):
    """A bounded repository acquisition or analysis failure."""


def repository_url(value: object) -> str:
    """Normalize one canonical HTTPS repository URL or return an empty string."""
    if not isinstance(value, str):
        return ""
    raw = value.strip()
    if not raw or len(raw) > MAX_URL_CHARS:
        return ""
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() != "https" or parsed.username or parsed.password or not host:
        return ""
    if host not in ALLOWED_HOSTS and not host.endswith(ALLOWED_SUFFIXES):
        return ""
    path = parsed.path.rstrip("/")
    if not path or ".." in path.split("/"):
        return ""
    return urlunparse(("https", host, path, "", "", ""))


def provider_for(url: str) -> str:
    """Return the stable public provider label for a normalized URL."""
    host = (urlparse(url).hostname or "").lower()
    return SUPPORTED_PROVIDERS.get(host, "github" if host.endswith(".github.com") else "gitlab")


def _git_raw(args: list[str], *, cwd: Path | None = None, stdin: bytes | None = None) -> bytes:
    """Run a non-interactive fixed Git command without shell expansion, returning bytes."""
    git_binary = shutil.which("git")
    if git_binary is None:
        message = "git command is unavailable"
        raise RepositoryScanError(message)
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0",
        # A partial clone refetches any blob the filter omitted the moment
        # something reads it, and that refetch pulls the whole blob set rather
        # than the object asked for. Refusing it keeps an omitted blob omitted.
        "GIT_NO_LAZY_FETCH": "1",
    }
    try:
        result = subprocess.run(  # noqa: S603 - command is fixed to the resolved Git binary and args are validated URLs.
            [git_binary, *args],
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            input=stdin,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        message = "git command timed out or was unavailable"
        raise RepositoryScanError(message) from exc
    if result.returncode != 0:
        stream = result.stderr or result.stdout or b"git command failed"
        detail = stream.decode("utf-8", "replace").strip().splitlines()[0][:500]
        raise RepositoryScanError(detail)
    return result.stdout


def _git(args: list[str], *, cwd: Path | None = None) -> str:
    """Run a Git command whose output is known to be text."""
    # Repository paths are not guaranteed to be UTF-8, and `ls-tree -z` prints
    # them unquoted, so decoding is lenient rather than strict here.
    return _git_raw(args, cwd=cwd).decode("utf-8", "replace").strip()


def repository_head(url: str) -> str:
    """Read the remote HEAD commit without downloading a repository."""
    output = _git(["ls-remote", "--symref", url, "HEAD"])
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= MIN_HEAD_PARTS and parts[-1] == "HEAD" and SHA_RE.fullmatch(parts[0]):
            return parts[0]
    message = "repository did not expose a usable HEAD commit"
    raise RepositoryScanError(message)


def _repository_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file() and not path.is_symlink())


def clone_repository(url: str, destination: Path) -> str:
    """Clone without a working tree, fetching only analyzable blobs, and return HEAD."""
    # Three flags have to hold together, because each one alone is defeated by
    # the others. `--filter` omits large blobs from the pack, but any later read
    # of a missing blob makes Git lazily refetch from the promisor remote — and
    # that refetch is not object-granular: asking for one 233-byte blob pulled
    # the repository's entire blob set (measured on pallets/flask, 132K -> 3.4M).
    # `--no-checkout` is what stops the clone from reading every blob to write a
    # working tree, which is the read that used to trigger exactly that refetch.
    # GIT_NO_LAZY_FETCH below then makes a missing blob stay missing instead of
    # silently restoring the unbounded fetch. Dropping any one of the three
    # returns the full-clone behaviour that pushed the pod past its memory limit.
    _git(
        [
            "clone",
            "--depth",
            "1",
            f"--filter=blob:limit={MAX_FILE_BYTES}",
            "--no-checkout",
            "--no-tags",
            "--single-branch",
            "--no-recurse-submodules",
            url,
            str(destination),
        ]
    )
    # The filter bounds each blob, not how many there are, so a repository of
    # very many small files can still fetch a lot. This gate is still after the
    # fetch, but it now bounds the git directory rather than a working tree that
    # only existed because every blob had already been pulled to build it.
    if _repository_size(destination) > MAX_CHECKOUT_BYTES:
        message = f"repository exceeds {MAX_CHECKOUT_BYTES} bytes"
        raise RepositoryScanError(message)
    return _git(["rev-parse", "HEAD"], cwd=destination)


def _tree_entries(repo: Path) -> list[tuple[str, str]]:
    """List (oid, path) for regular files at HEAD without reading any blob."""
    # -z keeps paths intact when they contain newlines or quotes; the long
    # format is deliberately not used, because printing a blob's size requires
    # having the blob, which is itself a lazy fetch of everything.
    listing = _git(["ls-tree", "-r", "-z", "HEAD"], cwd=repo)
    entries: list[tuple[str, str]] = []
    for record in listing.split("\0"):
        if not record:
            continue
        meta, _, path = record.partition("\t")
        fields = meta.split()
        if len(fields) < MIN_TREE_FIELDS or not path:
            continue
        mode, kind, oid = fields[0], fields[1], fields[2]
        # Skips symlinks (120000) and submodule gitlinks (160000) by mode. The
        # working-tree version had to delete symlinks from disk to stop the
        # traversal following them off the checkout; a mode check cannot be
        # raced and needs nothing materialized.
        if kind != "blob" or mode not in REGULAR_FILE_MODES:
            continue
        entries.append((oid, path))
    return sorted(entries, key=lambda entry: entry[1])


def _read_blobs(repo: Path, oids: list[str]) -> dict[str, bytes]:
    """Read the named blobs in one batch, treating absent ones as absent."""
    if not oids:
        return {}
    stdin = "".join(f"{oid}\n" for oid in oids).encode("ascii")
    return _parse_batch(_git_raw(["cat-file", "--batch"], cwd=repo, stdin=stdin))


def _parse_batch(stream: bytes) -> dict[str, bytes]:
    """Split `cat-file --batch` output, which is length-delimited, not line-delimited."""
    blobs: dict[str, bytes] = {}
    offset = 0
    while offset < len(stream):
        end = stream.find(b"\n", offset)
        if end < 0:
            break
        header = stream[offset:end].decode("ascii", "replace").split()
        offset = end + 1
        # A filtered-out blob answers "<oid> missing" and carries no body. That
        # is the expected reply for anything over MAX_FILE_BYTES, which the
        # analyzer would have discarded anyway, so it is not an error.
        # "ambiguous" is the other bodiless reply and is equally two fields, so
        # both are recognised before anything indexes a third field.
        if len(header) < MIN_BATCH_FIELDS or header[1] in BODILESS_REPLIES:
            continue
        if len(header) < TYPED_HEADER_FIELDS:
            break
        try:
            size = int(header[2])
        except ValueError:
            break
        body = stream[offset : offset + size]
        offset += size + 1  # trailing newline after the body
        # Consume the body for any object type before deciding to keep it, so an
        # unexpected type advances the cursor instead of desynchronising the rest.
        if header[1] == "blob":
            blobs[header[0]] = body
    return blobs


def _read_repository_tree(repo: Path) -> list[dict[str, str]]:
    """Select and read analyzable sources under the same caps as the local reader."""
    candidates = [
        (oid, path)
        for oid, path in _tree_entries(repo)
        if not ({part.lower() for part in Path(path).parts} & IGNORED_SOURCE_DIRS) and is_supported_source_path(path)
    ]
    files: list[dict[str, str]] = []
    total = 0
    # Read in chunks rather than all at once. MAX_FILES counts files that were
    # *accepted*, so a chunk that loses entries to the size or decode checks has
    # to be topped up from the next one, exactly as the local reader walks on
    # past a file it rejects. Chunking is what keeps that from meaning "hold
    # every candidate blob in memory at once" on a repository of many files.
    for start in range(0, len(candidates), MAX_FILES):
        if len(files) >= MAX_FILES:
            break
        chunk = candidates[start : start + MAX_FILES]
        blobs = _read_blobs(repo, [oid for oid, _ in chunk])
        for oid, path in chunk:
            if len(files) >= MAX_FILES:
                break
            raw = blobs.get(oid)
            # Absent means the clone filter omitted it for being oversized,
            # which is the same verdict the next check would reach anyway.
            if raw is None or len(raw) > MAX_FILE_BYTES:
                continue
            total += len(raw)
            if total > MAX_TOTAL_BYTES:
                return files
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            files.append({"path": path, "content": content})
    return files


def _tool_repository(record: dict[str, Any]) -> str:
    for key in ("repository", "repository_url", "source_repository"):
        value = repository_url(record.get(key))
        if value:
            return value
    return ""


def _raw_tool_repository(record: dict[str, Any]) -> str:
    for key in ("repository", "repository_url", "source_repository"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:MAX_URL_CHARS]
    return ""


def _scanner_user(s: Any) -> User:  # noqa: ANN401 - SQLAlchemy session
    user = s.execute(select(User).where(User.wm_sub == SCANNER_WM_SUB)).scalar_one_or_none()
    if user is None:
        user = User(wm_sub=SCANNER_WM_SUB, username=SCANNER_USERNAME, role="system")
        s.add(user)
        s.flush()
    return user


def _state(s: Any, tool_name: str) -> RepositoryAnalysisState:  # noqa: ANN401 - SQLAlchemy session
    row = s.get(RepositoryAnalysisState, tool_name)
    if row is None:
        row = RepositoryAnalysisState(tool_name=tool_name)
        s.add(row)
    return row


def _backoff(attempts: int) -> datetime:
    hours = min(24, 2 ** min(max(attempts, 0), 5))
    return utcnow() + timedelta(hours=hours)


# A --depth 1 clone has exactly one commit by one author, for every repository
# that has ever existed. _local_git_context measures the checkout honestly, so
# these two keys arrive as 1 and 1 no matter what is upstream -- and the
# maintenance assessment deducts ten points for each. They are not facts about
# the tool, they are facts about how we cloned it, and the only place that can
# see the real numbers is the provider API.
SHALLOW_CLONE_BLIND = ("contributorCount", "commitCount")


def _host_facts(url: str) -> dict[str, Any]:
    """Return whatever the enrichment lane knows about this repository.

    False is kept and None is dropped: a host that says "not archived" has
    told us something, a host that has no such field has not.
    """
    with db.session_scope() as s:
        row = s.get(RepositoryHostMetadata, repository_enrichment.url_hash(url))
        if row is None:
            return {}
        facts = {
            "contributorCount": row.contributor_count,
            "commitCount": row.commit_count,
            "archived": row.archived,
        }
    return {key: value for key, value in facts.items() if value is not None}


def _lifecycle_context(record: dict[str, Any]) -> dict[str, Any]:
    """Lifecycle as the maintainer declared it, not as we inferred it.

    An empty replacedBy is dropped by the context cleaner, so "no successor
    recorded" and "successor recorded" stay distinguishable downstream.
    """
    return {
        "deprecated": record.get("deprecated") is True,
        "replacedBy": str(record.get("replaced_by") or "").strip(),
    }


def _report_context(
    context: dict[str, Any], *, url: str, provider: str, commit_sha: str, record: dict[str, Any]
) -> dict[str, Any]:
    """Merge what the checkout measured into the context the analyzer scores.

    `context` is what acquisition produced -- {"repository": {...}}. It used to
    be read as though it were a finished report, looking for a
    "repositoryContext" key that a context does not have, so every measured
    fact was dropped: no lastCommitAt reached the analyzer and the dormancy
    assessment had nothing to score. SHALLOW_CLONE_BLIND above is what keeps
    that merge honest now that it happens.
    """
    repository = context.get("repository") if isinstance(context.get("repository"), dict) else {}
    repository = {key: value for key, value in repository.items() if key not in SHALLOW_CLONE_BLIND}
    repository = {
        **repository,
        "url": url,
        "provider": provider,
        "commitSha": commit_sha,
        "dirty": False,
        **_host_facts(url),
    }
    return {**context, "repository": repository, "lifecycle": _lifecycle_context(record)}


def _save_failure(tool_name: str, url: str, provider: str, error: str) -> None:
    with db.session_scope() as s:
        row = _state(s, tool_name)
        row.repository_url = url
        row.provider = provider
        row.status = "error"
        row.attempts = (row.attempts or 0) + 1
        row.checked_at = utcnow()
        row.next_attempt_at = _backoff(row.attempts)
        row.last_error = clean_error(error)
        row.source = SOURCE_REPOSITORY_SCAN
        row.sync_status = SYNC_ERROR


def _save_unsupported(tool_name: str, raw_url: str) -> None:
    with db.session_scope() as s:
        row = _state(s, tool_name)
        row.repository_url = raw_url
        row.provider = "unsupported"
        row.status = "unsupported"
        row.checked_at = utcnow()
        row.next_attempt_at = None
        row.last_error = "repository URL is not an allowed public HTTPS provider"
        row.source = SOURCE_REPOSITORY_SCAN
        row.sync_status = SYNC_ERROR


def scan_tool(tool_name: str, record: dict[str, Any], *, force: bool = False) -> str:
    """Scan one canonical tool, returning analyzed, skipped, unsupported, or error."""
    raw_url = _raw_tool_repository(record)
    url = repository_url(raw_url)
    if not url:
        if raw_url:
            _save_unsupported(tool_name, raw_url)
            return "unsupported"
        return "unsupported"
    provider = provider_for(url)
    try:
        head = repository_head(url)
        with db.session_scope() as s:
            state = _state(s, tool_name)
            if (
                not force
                and state.status == "analyzed"
                and state.repository_url == url
                and state.commit_sha == head
                and state.report_id is not None
            ):
                state.checked_at = utcnow()
                return "skipped"
            if state.next_attempt_at is not None and state.next_attempt_at > utcnow() and not force:
                return "backoff"
            # Stamp the attempt before the clone rather than after it. A pod
            # killed mid-clone leaves no other trace, and _scan_order puts a row
            # with no checked_at first, so every restart reselected the same
            # repository and died on it again. A scheduled job needed an
            # operator to break that; a continuous one would spin on it.
            state.checked_at = utcnow()
        with tempfile.TemporaryDirectory(prefix="toolhub-repository-") as workspace:
            checkout = Path(workspace) / "checkout"
            local_head = clone_repository(url, checkout)
            if local_head != head:
                head = local_head
            files = _read_repository_tree(checkout)
            context = _local_git_context([checkout])
            report = analyze_source_files(
                files,
                tool_name=tool_name,
                source_label=url,
                repository_context=_report_context(context, url=url, provider=provider, commit_sha=head, record=record),
            )
        with db.session_scope() as s:
            user = _scanner_user(s)
            stored = SourceAnalysisReport(
                user_id=user.id,
                created_by_user_id=user.id,
                tool_name=tool_name,
                source_label=url,
                report=report,
                review_status=REVIEW_APPROVED,
                reviewed_at=utcnow(),
                source=SOURCE_REPOSITORY_SCAN,
                sync_status=SYNC_EVOLVED_REAL,
            )
            s.add(stored)
            s.flush()
            state = _state(s, tool_name)
            state.repository_url = url
            state.provider = provider
            state.commit_sha = head
            state.status = "analyzed"
            state.report_id = stored.id
            state.attempts = 0
            state.checked_at = utcnow()
            state.analyzed_at = utcnow()
            state.next_attempt_at = None
            state.last_error = None
            state.source = SOURCE_REPOSITORY_SCAN
            state.sync_status = SYNC_EVOLVED_REAL
        graph_enrichment.refresh_tool_names([tool_name])
        tool_summaries.refresh([tool_name], build_local_tool_summary)
    except (RepositoryScanError, OSError, SourceAnalysisError, ValueError) as exc:
        _save_failure(tool_name, url, provider, str(exc))
        return "error"
    else:
        return "analyzed"


def _scan_order(state: RepositoryAnalysisState | None) -> tuple[bool, datetime]:
    """Order never-recorded tools first, then the least recently checked.

    A state row can legitimately exist with no ``checked_at``. The first
    transaction in scan_tool() commits a pending row before the scan itself
    runs, so any run that dies between the two -- which is exactly what a job
    timeout does -- leaves one behind. Sorting that None against a datetime
    raised TypeError on every later run, so one killed run permanently broke
    the job: the same SIGKILL that leaked the guard lock also planted this.
    """
    if state is None:
        return (False, EARLIEST_CHECK)
    return (True, state.checked_at or EARLIEST_CHECK)


def candidate_tools(limit: int, tool_name: str | None = None) -> list[tuple[str, dict[str, Any]]]:
    with db.session_scope() as s:
        rows = list(s.execute(select(CanonicalToolCache).order_by(CanonicalToolCache.tool_name)).scalars())
        states = {
            row.tool_name: row
            for row in s.execute(
                select(RepositoryAnalysisState).where(
                    RepositoryAnalysisState.tool_name.in_([row.tool_name for row in rows])
                )
            ).scalars()
        }
    candidates = [
        (row.tool_name, row.record if isinstance(row.record, dict) else {})
        for row in rows
        if (not tool_name or row.tool_name == tool_name)
        and _raw_tool_repository(row.record if isinstance(row.record, dict) else {})
    ]
    return sorted(candidates, key=lambda item: (*_scan_order(states.get(item[0])), item[0]))[: max(1, limit)]


def _new_results() -> dict[str, int]:
    return dict.fromkeys(("candidates", "analyzed", "skipped", "backoff", "unsupported", "error"), 0)


def _scan_one(name: str, record: dict[str, Any], results: dict[str, int], *, force: bool) -> str:
    """Scan one tool into `results`, absorbing whatever it raises."""
    results["candidates"] += 1
    try:
        result = scan_tool(name, record, force=force)
    except Exception as exc:  # noqa: BLE001 - one malformed repository must not abort the batch
        result = "error"
        try:
            raw_url = _raw_tool_repository(record)
            _save_failure(name, repository_url(raw_url), provider_for(repository_url(raw_url)), str(exc))
        except SQLAlchemyError as save_exc:
            # One tool's failure must not abort the batch, but swallowing this
            # silently would hide a database problem behind a run that merely
            # looks like a lot of scan errors. Report it and carry on.
            sys.stderr.write(f"repository-scan: could not record the failure for {name}: {save_exc}\n")
    results[result] += 1
    return result


def run(limit: int = 100, *, force: bool = False, tool_name: str | None = None) -> dict[str, int]:
    results = _new_results()
    for name, record in candidate_tools(limit, tool_name):
        _scan_one(name, record, results, force=force)
    return results


def _has_report(state: RepositoryAnalysisState | None) -> bool:
    return state is not None and state.status == "analyzed" and state.report_id is not None


def _settled_unsupported(state: RepositoryAnalysisState | None, raw_url: str) -> bool:
    """Report whether this exact URL was already rejected as an unsupported host.

    Re-deciding it costs no network, so the batch runner simply reported it
    again every hour. At one candidate per second it would instead occupy the
    backlog stream permanently. Comparing the URL keeps a tool whose record
    later names a supported host from being stuck behind the old verdict.
    """
    return state is not None and state.status == "unsupported" and state.repository_url == raw_url


def partition_candidates(depth: int = QUEUE_DEPTH) -> tuple[list[tuple[str, dict[str, Any]]], ...]:
    """Split the catalog into backlog work and re-check work, oldest first.

    Backlog is everything without a usable report: never scanned, previously
    failed and out of backoff, or analyzed but missing its report row. Refresh
    is everything already analyzed, which only needs its HEAD compared. Every
    state attribute is read inside the session, because the rows detach when it
    closes.
    """
    now = utcnow()
    backlog: list[tuple[tuple[bool, datetime], str, dict[str, Any]]] = []
    refresh: list[tuple[tuple[bool, datetime], str, dict[str, Any]]] = []
    with db.session_scope() as s:
        rows = list(s.execute(select(CanonicalToolCache).order_by(CanonicalToolCache.tool_name)).scalars())
        states = {
            row.tool_name: row
            for row in s.execute(
                select(RepositoryAnalysisState).where(
                    RepositoryAnalysisState.tool_name.in_([row.tool_name for row in rows])
                )
            ).scalars()
        }
        for row in rows:
            record = row.record if isinstance(row.record, dict) else {}
            raw_url = _raw_tool_repository(record)
            if not raw_url:
                continue
            state = states.get(row.tool_name)
            if _has_report(state):
                refresh.append((_scan_order(state), row.tool_name, record))
                continue
            if _settled_unsupported(state, raw_url):
                continue
            if state is not None and state.next_attempt_at is not None and state.next_attempt_at > now:
                continue
            backlog.append((_scan_order(state), row.tool_name, record))
    return tuple(
        [(name, record) for _, name, record in sorted(bucket, key=lambda entry: (*entry[0], entry[1]))][:depth]
        for bucket in (backlog, refresh)
    )


@dataclass
class _Stream:
    """One paced lane of work with its own interval and pending queue."""

    name: str
    interval: float
    rank: int
    queue: deque[tuple[str, dict[str, Any]]] = field(default_factory=deque)
    due_at: float = 0.0
    scanned: int = 0


@dataclass
class _Scanner:
    backlog: _Stream
    refresh: _Stream
    depth: int = QUEUE_DEPTH
    refill_at: float = 0.0

    def streams(self) -> tuple[_Stream, _Stream]:
        return (self.backlog, self.refresh)

    def take(self, stream: _Stream, *, now: float) -> tuple[str, dict[str, Any]] | None:
        """Pop the next tool for `stream`, refilling both queues when due.

        One catalog pass serves both lanes. Refilling per empty queue instead
        would make an exhausted backlog scan the whole cache every second.
        """
        if now >= self.refill_at:
            self.backlog.queue, self.refresh.queue = (deque(bucket) for bucket in partition_candidates(self.depth))
            self.refill_at = now + QUEUE_REFILL_SECONDS
        return stream.queue.popleft() if stream.queue else None


def _sleep_until(deadline: float, should_stop: Callable[[], bool]) -> bool:
    """Wait for `deadline`, returning False if shutdown was requested first."""
    while not should_stop():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(remaining, SHUTDOWN_POLL_SECONDS))
    return False


def _continuous_summary(results: dict[str, int], scanner: _Scanner) -> dict[str, int]:
    return {
        **results,
        "backlog_queued": len(scanner.backlog.queue),
        "backlog_scanned": scanner.backlog.scanned,
        "refresh_queued": len(scanner.refresh.queue),
        "refresh_scanned": scanner.refresh.scanned,
    }


def _record_window(window_started: datetime) -> None:
    """Publish one heartbeat window to /workers.

    A process that never exits has no run boundary for tools/job_guard.sh to
    record, so without this the worker reads as absent rather than as busy.
    Publishing is observability and must never take the loop down with it: a
    database that cannot accept the heartbeat is already visible as silence.
    """
    try:
        job_runs.record("repository-analysis", window_started, utcnow(), 0)
    except SQLAlchemyError as exc:
        sys.stderr.write(f"repository-scan: could not publish the heartbeat: {exc}\n")


@dataclass(frozen=True)
class ScanPace:
    """How fast each lane runs, and how often the loop reports and refills."""

    backlog_interval: float = BACKLOG_INTERVAL_SECONDS
    refresh_interval: float = REFRESH_INTERVAL_SECONDS
    heartbeat: float = HEARTBEAT_SECONDS
    depth: int = QUEUE_DEPTH


def run_continuous(
    *,
    pace: ScanPace | None = None,
    force: bool = False,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, int]:
    """Scan without stopping, pacing backlog and re-check work independently.

    Each interval is a minimum spacing between starts. Whichever lane is most
    overdue runs next, so a clone that outlasts its own interval delays the
    next backlog tool but cannot starve the slower refresh lane: refresh only
    ever waits for the one tool in flight.
    """
    pace = pace or ScanPace()
    stop = should_stop or (lambda: False)
    scanner = _Scanner(
        backlog=_Stream("backlog", pace.backlog_interval, rank=0),
        refresh=_Stream("refresh", pace.refresh_interval, rank=1),
        depth=pace.depth,
    )
    results = _new_results()
    next_heartbeat = time.monotonic() + pace.heartbeat
    window_started = utcnow()
    while not stop():
        stream = min(scanner.streams(), key=lambda lane: (lane.due_at, lane.rank))
        if not _sleep_until(stream.due_at, stop):
            break
        now = time.monotonic()
        item = scanner.take(stream, now=now)
        if item is None:
            # This lane is drained. Nothing can enter it before the next
            # catalog pass, so wait for that rather than spinning on an
            # empty queue at one wakeup per interval.
            stream.due_at = max(scanner.refill_at, now + stream.interval)
            continue
        stream.due_at = now + stream.interval
        stream.scanned += 1
        _scan_one(item[0], item[1], results, force=force)
        if time.monotonic() >= next_heartbeat:
            sys.stdout.write(
                "repository-analysis: " + json.dumps(_continuous_summary(results, scanner), sort_keys=True) + "\n"
            )
            sys.stdout.flush()
            _record_window(window_started)
            window_started = utcnow()
            next_heartbeat = time.monotonic() + pace.heartbeat
    # run_job() prints the returned summary, so the shutdown window only needs
    # publishing, not reprinting.
    _record_window(window_started)
    return _continuous_summary(results, scanner)


def _install_shutdown() -> Callable[[], bool]:
    """Ask the loop to stop after the tool in flight rather than mid-clone."""
    requested = {"stop": False}

    def request(_signum: int, _frame: object) -> None:
        requested["stop"] = True

    for received in (signal.SIGTERM, signal.SIGINT):
        signal.signal(received, request)
    return lambda: requested["stop"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=int(os.environ.get("REPOSITORY_SCAN_LIMIT", "100")))
    parser.add_argument("--force", action="store_true", default=os.environ.get("REPOSITORY_SCAN_FORCE") == "1")
    parser.add_argument("--tool-name", default=os.environ.get("REPOSITORY_SCAN_TOOL_NAME", ""))
    parser.add_argument(
        "--continuous",
        action="store_true",
        default=os.environ.get("REPOSITORY_SCAN_CONTINUOUS") == "1",
        help="scan forever, pacing backlog and re-check work separately, instead of one bounded batch",
    )
    parser.add_argument(
        "--backlog-interval",
        type=float,
        default=float(os.environ.get("REPOSITORY_SCAN_BACKLOG_INTERVAL") or BACKLOG_INTERVAL_SECONDS),
        help="minimum seconds between starting two not-yet-analyzed repositories",
    )
    parser.add_argument(
        "--refresh-interval",
        type=float,
        default=float(os.environ.get("REPOSITORY_SCAN_REFRESH_INTERVAL") or REFRESH_INTERVAL_SECONDS),
        help="minimum seconds between re-checking two already analyzed repositories",
    )
    args = parser.parse_args(argv)
    if args.continuous:
        if args.backlog_interval <= 0 or args.refresh_interval <= 0:
            parser.error("--backlog-interval and --refresh-interval must be positive")
        if args.tool_name.strip():
            parser.error("--tool-name scans one repository, which --continuous does not do")
        should_stop = _install_shutdown()
        return job_runner.run_job(
            "repository-analysis",
            lambda: run_continuous(
                pace=ScanPace(
                    backlog_interval=args.backlog_interval,
                    refresh_interval=args.refresh_interval,
                ),
                force=args.force,
                should_stop=should_stop,
            ),
        )
    if args.limit <= 0:
        parser.error("--limit must be positive")
    return job_runner.run_job(
        "repository-analysis",
        lambda: run(args.limit, force=args.force, tool_name=args.tool_name.strip() or None),
    )


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
