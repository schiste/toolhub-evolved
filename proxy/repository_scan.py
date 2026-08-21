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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

import requests
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

import repository_enrichment
from analyze_source import _local_git_context
from backend import (
    db,
    graph_enrichment,
    job_runner,
    job_runs,
    outbound,
    source_hosts,
    tool_summaries,
    wiki_api,
    wiki_sources,
)
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
    MAX_WIKI_FILE_BYTES,
    SourceAnalysisError,
    analyze_source_files,
    is_supported_source_path,
    source_reading_rank,
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


def _wiki_repository_url(raw: str) -> str:
    """Return the canonical URL of a wiki page that holds tool source, or "".

    Wiki hosts cannot join ALLOWED_HOSTS: a gadget lives on whichever Wikimedia
    wiki hosts it, and the set is neither small nor fixed. What can be pinned
    instead is the shape -- a validated Wikimedia domain, a User: subpage or a
    MediaWiki:Gadget- page, and a code extension -- which is what wiki_sources
    checks. It also collapses the /wiki/X and index.php?title=X spellings onto
    one URL, so the same gadget cannot be scanned twice under two keys.
    """
    source = wiki_sources.wiki_source(raw)
    return wiki_sources.page_url(source.domain, source.title) if source is not None else ""


def repository_url(value: object) -> str:
    """Normalize one canonical HTTPS repository or wiki-page URL, or return ""."""
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
        return _wiki_repository_url(raw)
    path = parsed.path.rstrip("/")
    if not path or ".." in path.split("/"):
        return ""
    return urlunparse(("https", host, path, "", "", ""))


def provider_for(url: str) -> str:
    """Return the stable public provider label for a normalized URL."""
    host = (urlparse(url).hostname or "").lower()
    if host in SUPPORTED_PROVIDERS:
        return SUPPORTED_PROVIDERS[host]
    if wiki_sources.wiki_source(url) is not None:
        return source_hosts.PROVIDER_MEDIAWIKI_WIKIMEDIA
    return "github" if host.endswith(".github.com") else "gitlab"


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


def git_target(url: str) -> str:
    """Return the URL git should be pointed at for this source URL.

    A tool record names where a human should look, which is frequently not
    where git listens: a Gerrit browse URL, a deep link into a subdirectory, a
    branch view. source_hosts resolves all of those to one project, and the
    project is what gets cloned. A URL it cannot place -- a *.github.com or
    *.gitlab.com subdomain, which is a gist or a raw host rather than a forge
    -- is handed to git unchanged, exactly as before.
    """
    ref = source_hosts.project_ref(url)
    target = source_hosts.clone_url(ref) if ref is not None else ""
    return target or url


def repository_head(url: str) -> str:
    """Read the remote HEAD commit without downloading a repository."""
    output = _git(["ls-remote", "--symref", git_target(url), "HEAD"])
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
    candidates = sorted(
        (
            (oid, path)
            for oid, path in _tree_entries(repo)
            if not ({part.lower() for part in Path(path).parts} & IGNORED_SOURCE_DIRS)
            and is_supported_source_path(path)
        ),
        key=lambda entry: source_reading_rank(entry[1]),
    )
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


WIKI_CALLER = outbound.Caller(
    user_agent="toolhub-evolved-repository-scanner (https://toolhub-evolved.toolforge.org)",
    accept="application/json",
    scheme_error="only public Wikimedia wiki APIs are read",
)


@dataclass(frozen=True)
class _Source:
    """One tool's source as acquired, whatever kind of host it came from."""

    head: str
    files: list[dict[str, str]]
    context: dict[str, Any]
    #: The wiki page this came from, with its kind settled by what was fetched,
    #: or None for a clone. Carried because acquisition is the only step that
    #: reads the gadget definition, and the type suggestion depends on it.
    wiki_page: wiki_sources.WikiSource | None = None


def _wiki_query(session: requests.Session, url: str) -> Any:  # noqa: ANN401 - one decoded API payload
    """Run one Action API query, turning its in-band error into a scan failure.

    The Action API reports errors with HTTP 200 and an error object in the
    body, so a caller that only checked the status would record a rate-limited
    or lagged wiki as a tool with no source at all.
    """
    payload = json.loads(outbound.fetch_bounded(session, url, policy=outbound.WIKI_API, caller=WIKI_CALLER))
    code = wiki_api.api_error(payload)
    if code:
        message = f"wiki API refused the query: {code}"
        raise RepositoryScanError(message)
    return payload


def _wiki_revisions(source: wiki_sources.WikiSource) -> tuple[tuple[wiki_api.Revision, ...], wiki_sources.WikiSource]:
    """Fetch every page one wiki-hosted tool consists of, in one request or two.

    A user script costs one: the prefix search that finds its subpages is a
    generator feeding the revision fetch, so discovery is free. A gadget costs
    two, because its members are named in a page that has to be read first.

    Returns the source back alongside the revisions, because reading that second
    page is also what establishes whether this is a gadget at all -- an
    unregistered `MediaWiki:Gadget-` page is a leftover or a work in progress,
    and it is scanned alone rather than guessed at. Discarding the verdict here
    is how the page title ended up standing in for it downstream.
    """
    with requests.Session() as session:
        if source.kind in wiki_sources.GADGET_KINDS:
            definition = wiki_api.definition_text(_wiki_query(session, wiki_api.definition_url(source.domain)))
            source, titles = wiki_sources.registered_gadget(source, definition)
            found = wiki_api.revisions(_wiki_query(session, wiki_api.pages_url(source.domain, titles)))
            return found, source
        query = wiki_api.subpages_url(source.domain, source.namespace_id, source.prefix)
        found = wiki_api.revisions(_wiki_query(session, query))
    # The prefix search is broader than the script -- it also returns the same
    # author's next tool -- so what it fetched still has to be filtered down to
    # the pages that actually belong to this one.
    kept = set(wiki_sources.subpage_titles(source, [revision.title for revision in found]))
    return tuple(revision for revision in found if revision.title in kept), source


def _wiki_files(found: tuple[wiki_api.Revision, ...]) -> list[dict[str, str]]:
    """Select the analyzable pages, under the count and total caps of the reader.

    The per-file cap is the wiki one rather than the checkout one, for the reason
    MAX_WIKI_FILE_BYTES gives. The two others are shared: a page set that reaches
    120 files or 2 MiB is past what a tool's source plausibly is either way.

    The page title is the path. It already ends in .js, .css or .json, which is
    what the analyzer reads to choose a language, and keeping it means a finding
    is reported against a name a maintainer can paste into a wiki search box.
    """
    files: list[dict[str, str]] = []
    total = 0
    for revision in found:
        raw = len(revision.content.encode("utf-8"))
        if len(files) >= MAX_FILES or total + raw > MAX_TOTAL_BYTES:
            break
        if raw > MAX_WIKI_FILE_BYTES or not is_supported_source_path(revision.title):
            continue
        total += raw
        files.append({"path": revision.title, "content": revision.content})
    return files


def _wiki_context(found: tuple[wiki_api.Revision, ...]) -> dict[str, Any]:
    """Build the repository context a page set can honestly fill.

    Deliberately thin. _local_git_context reports a branch, a tag and a default
    branch because a clone has them; a wiki page has none of the three, and
    inventing them would be worse than their absence -- an absent key reads as
    "not measured" downstream, where a wrong value would be scored.
    """
    repository: dict[str, Any] = {"analyzedAt": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")}
    last_edit = wiki_api.last_edited_at(found)
    if last_edit:
        repository["lastCommitAt"] = last_edit
    return {"repository": repository}


def _acquire_wiki(source: wiki_sources.WikiSource) -> _Source:
    """Read one wiki-hosted tool: its pages, their text, and a head over the set."""
    found, resolved = _wiki_revisions(source)
    if not found:
        message = "wiki page set holds no readable revision"
        raise RepositoryScanError(message)
    files = _wiki_files(found)
    if not files:
        # Distinguished from the empty fetch above because the causes differ and
        # so do the fixes. Left to fall through, this arrives as the analyzer's
        # "files must be a non-empty list", which describes the argument rather
        # than the page set and sends a reader looking for a fetch failure that
        # did not happen -- the pages were read, and every one was filtered.
        largest = max(len(revision.content.encode("utf-8")) for revision in found)
        message = (
            f"wiki page set holds no analyzable page: {len(found)} read, "
            f"none under {MAX_WIKI_FILE_BYTES} bytes with a supported extension (largest {largest})"
        )
        raise RepositoryScanError(message)
    return _Source(
        head=wiki_api.head(found),
        files=files,
        context=_wiki_context(found),
        wiki_page=resolved,
    )


def _acquire_clone(url: str) -> _Source:
    """Read one repository from a bounded clone that is discarded immediately."""
    with tempfile.TemporaryDirectory(prefix="toolhub-repository-") as workspace:
        checkout = Path(workspace) / "checkout"
        head = clone_repository(git_target(url), checkout)
        return _Source(head=head, files=_read_repository_tree(checkout), context=_local_git_context([checkout]))


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


# A day was the longest a repository was ever left alone, which is the right
# ceiling for a repository having a bad week and the wrong one for a repository
# that is gone. Production settled at 199 failing rows, nearly all of them at
# the attempt cap: private, deleted, or an empty placeholder that will never
# hold code. Retried daily they were 84-99% of everything the backlog lane
# scanned, so the lane spent its budget re-confirming known-dead URLs while
# real work waited behind them.
#
# Doubling past a day turns that into roughly seven checks a day rather than
# 199, without ever writing a repository off: a month is short enough that one
# coming back is picked up, and one success resets attempts to zero, so a
# genuinely transient failure never reaches these intervals at all.
MAX_BACKOFF_HOURS = 30 * 24
MAX_BACKOFF_DOUBLINGS = 10


def _backoff(attempts: int) -> datetime:
    hours = min(MAX_BACKOFF_HOURS, 2 ** min(max(attempts, 0), MAX_BACKOFF_DOUBLINGS))
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

    `context` is what acquisition produced -- {"repository": {...}}, from a
    clone or from a wiki page set. It used to be read as though it were a
    finished report, looking for a "repositoryContext" key that a context does
    not have, so every measured fact was dropped: no lastCommitAt reached the
    analyzer and the dormancy assessment had nothing to score.
    SHALLOW_CLONE_BLIND above is what keeps that merge honest now that it
    happens.
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


UNSUPPORTED_HOST = "repository URL is not an allowed public HTTPS provider"
UNSUPPORTED_PATH = "repository URL names a known host but no project on it"


def _save_unsupported(
    tool_name: str, raw_url: str, *, provider: str = "unsupported", reason: str = UNSUPPORTED_HOST
) -> None:
    """Record a verdict no future request can change, keyed to this exact URL.

    Settled rather than failed, because the two cost different things. A
    failure is retried on a timer forever; this is a statement about the
    record, and _settled_unsupported compares the URL, so correcting the record
    upstream is what puts the tool back in the queue.
    """
    with db.session_scope() as s:
        row = _state(s, tool_name)
        row.repository_url = raw_url
        row.provider = provider
        row.status = "unsupported"
        row.checked_at = utcnow()
        row.next_attempt_at = None
        row.last_error = reason
        row.source = SOURCE_REPOSITORY_SCAN
        row.sync_status = SYNC_ERROR


def _settle_without_request(tool_name: str, raw_url: str, url: str, *, page: wiki_sources.WikiSource | None) -> bool:
    """Record and report a verdict that needs no request to reach.

    Two URL shapes get one. A URL on no allowed host at all, and a URL on a
    host we do know that names no project on it -- the bare
    `gerrit.wikimedia.org/r`, a `github.com/your-project` placeholder, a
    single-segment GitLab path. The second used to be cloned anyway, once an
    hour, for the same "remote: Not Found" every time.

    Both are statements about the tool record rather than about a repository,
    which is why they settle instead of failing: nothing the host could do
    would change the answer, and only an edit upstream should reopen it.
    """
    if not url:
        if raw_url:
            _save_unsupported(tool_name, raw_url)
        return True
    if page is None and source_hosts.names_no_project(url):
        _save_unsupported(tool_name, raw_url, provider=provider_for(url), reason=UNSUPPORTED_PATH)
        return True
    return False


def _current_head(state: RepositoryAnalysisState, url: str) -> str:
    """Return the commit whose report is already stored for this tool, or "".

    Empty means there is nothing to reuse: never analyzed, analyzed from a
    different URL, or the report itself has since been removed. Collapsing all
    three into one string is what lets both currency checks below be a plain
    comparison rather than the same four-clause condition written twice.
    """
    reusable = state.status == "analyzed" and state.repository_url == url and state.report_id is not None
    return (state.commit_sha or "") if reusable else ""


def scan_tool(tool_name: str, record: dict[str, Any], *, force: bool = False) -> str:
    """Scan one canonical tool, returning what became of it.

    "analyzed", "skipped", "backoff", "unsupported" or "error" -- plus
    CACHES_STALE, which is an analysis whose derived caches did not refresh.
    """
    raw_url = _raw_tool_repository(record)
    url = repository_url(raw_url)
    page = wiki_sources.wiki_source(url) if url else None
    if _settle_without_request(tool_name, raw_url, url, page=page):
        return "unsupported"
    provider = provider_for(url)
    try:
        # A wiki page set has no cheap head. Its members are only known once
        # they have been fetched -- a gadget's file list lives in a page of its
        # own -- so there is nothing to ask for that costs less than the fetch
        # itself, and the currency check moves to after acquisition instead.
        head = "" if page is not None else repository_head(url)
        with db.session_scope() as s:
            state = _state(s, tool_name)
            analyzed_head = _current_head(state, url)
            if not force and head and head == analyzed_head:
                state.checked_at = utcnow()
                return "skipped"
            if state.next_attempt_at is not None and state.next_attempt_at > utcnow() and not force:
                return "backoff"
            # Stamp the attempt before the fetch rather than after it. A pod
            # killed mid-clone leaves no other trace, and _scan_order puts a row
            # with no checked_at first, so every restart reselected the same
            # repository and died on it again. A scheduled job needed an
            # operator to break that; a continuous one would spin on it.
            state.checked_at = utcnow()
        acquired = _acquire_wiki(page) if page is not None else _acquire_clone(url)
        # Second check, and the only one a wiki tool gets. It also catches the
        # repository whose advertised HEAD and cloned HEAD disagree: analysis
        # and a report row are worth skipping for a commit already on file.
        if not force and analyzed_head and acquired.head == analyzed_head:
            return "skipped"
        head = acquired.head
        report = analyze_source_files(
            acquired.files,
            tool_name=tool_name,
            source_label=url,
            wiki_page=acquired.wiki_page,
            repository_context=_report_context(
                acquired.context, url=url, provider=provider, commit_sha=head, record=record
            ),
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
    except (RepositoryScanError, OSError, SourceAnalysisError, ValueError) as exc:
        _save_failure(tool_name, url, provider, str(exc))
        return "error"
    else:
        # Deliberately outside the try above. These two refresh caches derived
        # from a report that is already committed, so their failure cannot mean
        # the scan failed -- and until this moved, it said exactly that: a lock
        # timeout in either one returned "error", and _save_failure overwrote a
        # freshly analyzed row with a backoff. A one-tool run printed
        # `{"analyzed": 0, "candidates": 1, "error": 1}` over a stored report
        # that had already reached the live projection.
        return "analyzed" if _refresh_caches(tool_name) else CACHES_STALE


#: Analyzed, but the caches derived from the new report did not refresh. Not a
#: failure to scan: the report is stored and every lane that reads it will see
#: it. Counted beside "analyzed" rather than instead of it.
CACHES_STALE = "caches_stale"


def _refresh_caches(tool_name: str) -> bool:
    """Refresh what a stored report feeds, reporting rather than raising.

    Catches everything, because by the time this runs the report is durable and
    nothing raised here can undo it. Both refreshes rebuild from the database on
    their next pass, so a failure costs one lane a cycle of freshness; letting
    it propagate would cost the analysis itself.
    """
    try:
        graph_enrichment.refresh_tool_names([tool_name])
        tool_summaries.refresh([tool_name], build_local_tool_summary)
    except Exception as exc:  # noqa: BLE001 - a stored report must survive a cache that will not rebuild
        sys.stderr.write(f"repository-scan: analyzed {tool_name} but could not refresh its caches: {exc}\n")
        return False
    return True


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
    return dict.fromkeys(("candidates", "analyzed", "skipped", "backoff", "unsupported", "error", CACHES_STALE), 0)


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
    if result == CACHES_STALE:
        # A qualifier on an analysis, not a fifth outcome: the tool was
        # analyzed, so it is counted as analyzed, and this says what is behind.
        results["analyzed"] += 1
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


def _heartbeat_summary(results: dict[str, int], scanner: _Scanner, baseline: dict[str, int]) -> dict[str, Any]:
    """Report the process totals alongside what this one window did.

    `results` accumulates for the life of a worker that never exits, so a
    heartbeat carrying only totals reprints the same `error` count every ten
    minutes long after the last failure -- a fixed number that reads, line
    after line, like a fresh disaster. Production showed `error: 1243` held
    steady across a day of heartbeats while only 200 tools were in an error
    state; the count was a lifetime tally of retries against the same handful
    of private and deleted repositories. The window is what says whether
    anything is going wrong now.
    """
    window = {key: value - baseline.get(key, 0) for key, value in results.items()}
    return {**_continuous_summary(results, scanner), "window": window}


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
    baseline = dict(results)
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
            summary = _heartbeat_summary(results, scanner, baseline)
            sys.stdout.write("repository-analysis: " + json.dumps(summary, sort_keys=True) + "\n")
            sys.stdout.flush()
            _record_window(window_started)
            baseline = dict(results)
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
