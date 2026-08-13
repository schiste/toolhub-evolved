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

from analyze_source import _local_git_context, _read_tree
from backend import db, graph_enrichment, job_runner, tool_summaries
from backend.models import CanonicalToolCache, RepositoryAnalysisState, SourceAnalysisReport, User, utcnow
from backend.source_analyzer import SourceAnalysisError, analyze_source_files
from backend.sync import REVIEW_APPROVED, SOURCE_REPOSITORY_SCAN, SYNC_ERROR, SYNC_EVOLVED_REAL, clean_error
from backend.v1_common import build_local_tool_summary

SCANNER_WM_SUB = "evolved:repository-scanner"
SCANNER_USERNAME = "Evolved repository scanner"
GIT_TIMEOUT_SECONDS = 180
MAX_CHECKOUT_BYTES = 64 * 1024 * 1024
MAX_URL_CHARS = 2000
MIN_HEAD_PARTS = 2
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


def _git(args: list[str], *, cwd: Path | None = None) -> str:
    """Run a non-interactive fixed Git command without shell expansion."""
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
    }
    try:
        result = subprocess.run(  # noqa: S603 - command is fixed to the resolved Git binary and args are validated URLs.
            [git_binary, *args],
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        message = "git command timed out or was unavailable"
        raise RepositoryScanError(message) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git command failed").strip().splitlines()[0][:500]
        raise RepositoryScanError(detail)
    return result.stdout.strip()


def repository_head(url: str) -> str:
    """Read the remote HEAD commit without downloading a repository."""
    output = _git(["ls-remote", "--symref", url, "HEAD"])
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= MIN_HEAD_PARTS and parts[-1] == "HEAD" and SHA_RE.fullmatch(parts[0]):
            return parts[0]
    message = "repository did not expose a usable HEAD commit"
    raise RepositoryScanError(message)


def _checkout_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file() and not path.is_symlink())


def _remove_symlinks(root: Path) -> None:
    """Remove repository symlinks before bounded traversal can follow them."""
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_symlink():
            path.unlink()


def checkout_repository(url: str, destination: Path) -> str:
    """Create a shallow, non-recursive checkout and return its local HEAD."""
    _git(
        [
            "clone",
            "--depth",
            "1",
            "--no-tags",
            "--single-branch",
            "--no-recurse-submodules",
            url,
            str(destination),
        ]
    )
    _remove_symlinks(destination)
    # This gate decides what gets *analyzed*; it does not bound what gets
    # *fetched*. By the time it runs, clone has already written the whole
    # working tree to disk. `--filter=blob:limit=` does not close that gap:
    # clone materializes the working tree and lazily re-fetches every filtered
    # blob it needs, so a filtered clone lands the same bytes as an unfiltered
    # one (measured, not assumed). Bounding the fetch would mean --no-checkout
    # plus reading blobs through `git cat-file`, i.e. rewriting _read_tree.
    # Until then the real limits on transient disk use are GIT_TIMEOUT_SECONDS
    # and the tool account's own quota — a full disk fails the clone inside
    # _git(), which surfaces as a RepositoryScanError and backs the tool off.
    if _checkout_size(destination) > MAX_CHECKOUT_BYTES:
        message = f"checkout exceeds {MAX_CHECKOUT_BYTES} bytes"
        raise RepositoryScanError(message)
    return _git(["rev-parse", "HEAD"], cwd=destination)


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
            local_head = checkout_repository(url, checkout)
            if local_head != head:
                head = local_head
            files = _read_tree([checkout])
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
