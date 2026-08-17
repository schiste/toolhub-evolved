# SPDX-License-Identifier: GPL-3.0-or-later
"""Fetch and deterministically analyze public repositories named by Toolhub."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from analyze_source import _local_git_context
from backend import db, graph_enrichment, job_runner, tool_summaries
from backend.models import CanonicalToolCache, RepositoryAnalysisState, SourceAnalysisReport, User, utcnow
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


def _report_context(report: dict[str, Any], *, url: str, provider: str, commit_sha: str) -> dict[str, Any]:
    context = report.get("repositoryContext") if isinstance(report.get("repositoryContext"), dict) else {}
    repository = context.get("repository") if isinstance(context.get("repository"), dict) else {}
    repository = {**repository, "url": url, "provider": provider, "commitSha": commit_sha, "dirty": False}
    return {**context, "repository": repository}


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
                repository_context=_report_context(context, url=url, provider=provider, commit_sha=head),
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


def run(limit: int = 100, *, force: bool = False, tool_name: str | None = None) -> dict[str, int]:
    results = dict.fromkeys(("candidates", "analyzed", "skipped", "backoff", "unsupported", "error"), 0)
    for name, record in candidate_tools(limit, tool_name):
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
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=int(os.environ.get("REPOSITORY_SCAN_LIMIT", "100")))
    parser.add_argument("--force", action="store_true", default=os.environ.get("REPOSITORY_SCAN_FORCE") == "1")
    parser.add_argument("--tool-name", default=os.environ.get("REPOSITORY_SCAN_TOOL_NAME", ""))
    args = parser.parse_args(argv)
    if args.limit <= 0:
        parser.error("--limit must be positive")
    return job_runner.run_job(
        "repository-analysis",
        lambda: run(args.limit, force=args.force, tool_name=args.tool_name.strip() or None),
    )


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
