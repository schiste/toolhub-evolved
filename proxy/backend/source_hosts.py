# SPDX-License-Identifier: GPL-3.0-or-later
"""Normalized project facts from the APIs of the hosts that carry tool source.

repository_scan.py learns everything it knows about a repository from a depth-1
clone, which is structurally blind to what the host already publishes: whether
a project is archived, which license the host detected, how many people have
ever committed. Two of those it does not merely miss, it gets wrong -- a
depth-1 clone reports exactly one commit and one contributor for every
repository, however large, and _maintenance_activity_assessment then deducts
twenty points from every scanned tool for both.

Deepening the clone would reverse the memory work recorded in jobs.yaml (a
measured 1.264Gi -> 159.7Mi over a 100-tool batch), so the facts come from the
host instead. This module is the pure half of that: URL to project identity,
and API payload to one normalized shape. It performs no I/O, so the awkward
part of every host -- what its URLs look like and what it calls each field --
is testable without a network.

Five API families cover the six hosts repository_scan.ALLOWED_HOSTS permits,
and a sixth kind is coming: gadgets and user scripts hosted on-wiki, where the
page history *is* the repository. HostMetadata is therefore a set of optional
facts rather than a forge record. A None means "this host does not publish
this", which is not the same as zero and must not be scored as one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse

if TYPE_CHECKING:
    from collections.abc import Mapping

# What a host is, as opposed to who runs it. The distinction earns its place
# once wiki-hosted gadgets arrive: a forge is cloned and has branches, a wiki
# page is fetched and has revisions, and the enrichment lane must not assume
# the former just because every host it sees today happens to be one.
KIND_FORGE = "forge"
KIND_WIKI = "wiki"

PROVIDER_GITHUB = "github"
PROVIDER_GITLAB = "gitlab"
PROVIDER_GITLAB_WIKIMEDIA = "gitlab-wikimedia"
PROVIDER_CODEBERG = "codeberg"
PROVIDER_BITBUCKET = "bitbucket"
PROVIDER_GERRIT_WIKIMEDIA = "gerrit-wikimedia"

# The API family each provider speaks. Two providers share GitLab's: gitlab.com
# and gitlab.wikimedia.org run the same v4 API behind different origins, so
# they differ only in base URL and credentials, never in parsing.
API_GITHUB = "github"
API_GITLAB = "gitlab"
API_FORGEJO = "forgejo"
API_BITBUCKET = "bitbucket"
API_GERRIT = "gerrit"

MAX_TOPICS = 20
MAX_TEXT_CHARS = 500
MIN_PATH_SEGMENTS = 2

# Gerrit answers ACTIVE, READ_ONLY, or HIDDEN. READ_ONLY is the closest thing
# it has to an archive flag; HIDDEN means the project is no longer listed at
# all, which is a stronger statement than archived but maps to the same
# "do not expect further work here" verdict.
GERRIT_ARCHIVED_STATES = frozenset({"READ_ONLY", "HIDDEN"})

# Every Gerrit JSON response is prefixed with this XSSI guard, which is not
# valid JSON and must be stripped before parsing.
GERRIT_XSSI_PREFIX = ")]}'"

# A paginated GitHub response advertises its last page in a Link header;
# asked for one item per page, that page number is the total item count.
REL_LAST = 'rel="last"'
PAGE_PARAM_RE = re.compile(r"[?&]page=(\d+)")

# GitLab marks the end of a project path with a literal "/-/" segment, which
# is what makes nested groups unambiguous: everything before it is the project,
# however many levels deep. The other forges have a fixed owner/name shape, so
# taking the leading two segments is enough and no separator is needed.
GITLAB_UI_SEPARATOR = "-"

# Where each API lives relative to the host that serves the web UI. GitHub and
# Bitbucket move theirs to a separate origin; the rest mount it under the same
# one, which is what lets gitlab.com and gitlab.wikimedia.org share a client.
API_ORIGINS = {
    API_GITHUB: "https://api.github.com",
    API_BITBUCKET: "https://api.bitbucket.org/2.0",
}
API_PATH_PREFIXES = {
    API_GITLAB: "/api/v4",
    API_FORGEJO: "/api/v1",
    API_GERRIT: "/r",
}

# A license identifier the host uses to mean "we could not tell", which is not
# the same as the project having no license and must not be stored as one.
LICENSE_UNKNOWN = frozenset({"NOASSERTION", "NONE", "OTHER", "UNKNOWN"})
MAX_LICENSE_CHARS = 64
MAX_TOPIC_CHARS = 80

# Gerrit web URLs wrap the real project name in one of several UI prefixes.
# Longest first, so "/r/plugins/gitiles/x" does not match the bare "/r/" rule
# and keep "plugins/gitiles/x" as the project name.
GERRIT_PATH_PREFIXES = (
    "r/plugins/gitiles/",
    "r/admin/repos/",
    "plugins/gitiles/",
    "g/",
    "r/",
)


@dataclass(frozen=True)
class ProjectRef:
    """One host-specific project identity resolved from a normalized source URL."""

    provider: str
    api: str
    kind: str
    path: str
    api_base: str

    @property
    def encoded_path(self) -> str:
        """Return the project path encoded for use as a single URL segment."""
        return quote(self.path, safe="")


@dataclass(frozen=True)
class HostMetadata:
    """Facts one source host published about one project, normalized across APIs.

    Every field is optional on purpose. The five API families answer different
    subsets -- Bitbucket has no stars, Gerrit has no topics, only GitHub and
    GitLab report a license -- and a caller must be able to tell "not published
    here" from "published as zero". Scoring code that cannot make that
    distinction will penalise projects for their host's API surface.
    """

    archived: bool | None = None
    default_branch: str | None = None
    description: str | None = None
    homepage: str | None = None
    # The host's own license identifier, upper-cased. Deliberately not called
    # spdx: GitHub returns a real spdx_id (and sometimes NOASSERTION), while
    # GitLab returns its own key. Storing the host's answer as the host gave
    # it keeps a later SPDX mapping honest about what it is mapping from.
    license_id: str | None = None
    topics: tuple[str, ...] = ()
    star_count: int | None = None
    fork_count: int | None = None
    open_issues_count: int | None = None
    contributor_count: int | None = None
    commit_count: int | None = None
    pushed_at: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class HostCapabilities:
    """Which extra requests a host can answer beyond its project record.

    The lane reads this instead of trying and handling the 404, because a
    request that is known to be unanswerable is rate budget spent for nothing.
    """

    contributor_count: bool = False
    commit_count: bool = False


PROVIDERS_BY_HOST = {
    "github.com": PROVIDER_GITHUB,
    "gitlab.com": PROVIDER_GITLAB,
    "gitlab.wikimedia.org": PROVIDER_GITLAB_WIKIMEDIA,
    "codeberg.org": PROVIDER_CODEBERG,
    "bitbucket.org": PROVIDER_BITBUCKET,
    "gerrit.wikimedia.org": PROVIDER_GERRIT_WIKIMEDIA,
}

API_BY_PROVIDER = {
    PROVIDER_GITHUB: API_GITHUB,
    PROVIDER_GITLAB: API_GITLAB,
    PROVIDER_GITLAB_WIKIMEDIA: API_GITLAB,
    PROVIDER_CODEBERG: API_FORGEJO,
    PROVIDER_BITBUCKET: API_BITBUCKET,
    PROVIDER_GERRIT_WIKIMEDIA: API_GERRIT,
}

CAPABILITIES_BY_API = {
    API_GITHUB: HostCapabilities(contributor_count=True, commit_count=True),
    # GitLab reports both as an X-Total header on a one-item page, so neither
    # count requires reading a body -- which is how the contributor count is
    # obtained without ever parsing the email addresses that body carries.
    API_GITLAB: HostCapabilities(contributor_count=True, commit_count=True),
    API_FORGEJO: HostCapabilities(contributor_count=False, commit_count=False),
    API_BITBUCKET: HostCapabilities(contributor_count=False, commit_count=False),
    API_GERRIT: HostCapabilities(contributor_count=False, commit_count=False),
}


def _text(value: object, limit: int = MAX_TEXT_CHARS) -> str | None:
    """Return a bounded, non-empty string, or None for anything else."""
    if not isinstance(value, str):
        return None
    return value.strip()[:limit] or None


def _count(value: object) -> int | None:
    """Return a non-negative count. Booleans are excluded: True is not one."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _flag(value: object) -> bool | None:
    """Return a real boolean, or None when the host did not publish one."""
    return value if isinstance(value, bool) else None


def _mapping(value: object) -> dict[str, Any]:
    """Return a nested object, or an empty one, so lookups never branch twice."""
    return value if isinstance(value, dict) else {}


def _topics(value: object) -> tuple[str, ...]:
    """Return bounded topic labels, dropping anything that is not a string."""
    if not isinstance(value, list):
        return ()
    cleaned = [text for item in value if (text := _text(item, MAX_TOPIC_CHARS)) is not None]
    return tuple(cleaned[:MAX_TOPICS])


def _license_id(container: object, key: str) -> str | None:
    """Return the host's license identifier, upper-cased, or None if it disclaims one."""
    raw = _text(_mapping(container).get(key), MAX_LICENSE_CHARS)
    if raw is None:
        return None
    upper = raw.upper()
    return None if upper in LICENSE_UNKNOWN else upper


def _segments(path: str) -> list[str]:
    """Split a URL path into non-empty segments."""
    return [segment for segment in path.split("/") if segment]


def _without_git_suffix(name: str) -> str:
    """Drop the .git a clone URL carries and a web URL does not."""
    return name.removesuffix(".git")


def _forge_path(segments: list[str]) -> str:
    """Take the leading owner/name pair, ignoring any UI path that follows it."""
    if len(segments) < MIN_PATH_SEGMENTS:
        return ""
    return f"{segments[0]}/{_without_git_suffix(segments[1])}"


def _gitlab_path(segments: list[str]) -> str:
    """Take everything before GitLab's "/-/" marker, so nested groups survive."""
    kept: list[str] = []
    for segment in segments:
        if segment == GITLAB_UI_SEPARATOR:
            break
        kept.append(segment)
    if len(kept) < MIN_PATH_SEGMENTS:
        return ""
    kept[-1] = _without_git_suffix(kept[-1])
    return "/".join(kept)


def _gerrit_path(path: str) -> str:
    """Strip whichever Gerrit UI prefix wraps the real project name."""
    trimmed = path.lstrip("/")
    for prefix in GERRIT_PATH_PREFIXES:
        if trimmed.startswith(prefix):
            return _without_git_suffix(trimmed[len(prefix) :].strip("/"))
    return ""


def _api_base(api: str, host: str) -> str:
    """Return where `api` is served for `host`."""
    origin = API_ORIGINS.get(api)
    if origin is not None:
        return origin
    return f"https://{host}{API_PATH_PREFIXES[api]}"


def project_ref(url: str) -> ProjectRef | None:
    """Resolve one normalized HTTPS source URL to a host project identity.

    Only the exact hosts in PROVIDERS_BY_HOST resolve. repository_scan also
    admits *.github.com and *.gitlab.com for cloning, but those subdomains are
    gist/raw/www rather than API-bearing instances, so guessing an API origin
    from them would aim authenticated requests at the wrong service. They
    simply get no enrichment.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    provider = PROVIDERS_BY_HOST.get(host)
    if provider is None:
        return None
    api = API_BY_PROVIDER[provider]
    if api == API_GERRIT:
        path = _gerrit_path(parsed.path)
    elif api == API_GITLAB:
        path = _gitlab_path(_segments(parsed.path))
    else:
        path = _forge_path(_segments(parsed.path))
    if not path:
        return None
    return ProjectRef(provider=provider, api=api, kind=KIND_FORGE, path=path, api_base=_api_base(api, host))


def capabilities(ref: ProjectRef) -> HostCapabilities:
    """Return which extra requests `ref`'s host can answer."""
    return CAPABILITIES_BY_API[ref.api]


def project_url(ref: ProjectRef) -> str:
    """Return the API URL for `ref`'s project record."""
    if ref.api == API_GITHUB:
        return f"{ref.api_base}/repos/{ref.path}"
    if ref.api == API_GITLAB:
        # license=true is what makes GitLab return the license object at all;
        # without it the field is simply absent rather than null.
        return f"{ref.api_base}/projects/{ref.encoded_path}?license=true"
    if ref.api == API_FORGEJO:
        return f"{ref.api_base}/repos/{ref.path}"
    if ref.api == API_BITBUCKET:
        return f"{ref.api_base}/repositories/{ref.path}"
    return f"{ref.api_base}/projects/{ref.encoded_path}"


def contributor_count_url(ref: ProjectRef) -> str:
    """Return the URL whose *headers* carry `ref`'s contributor count.

    Both supported hosts answer this without the body being read: GitHub puts
    the last page number in Link, GitLab puts the total in X-Total. That is not
    only cheaper, it is the reason this is safe to call at all -- GitLab's
    contributor body lists author email addresses, and this project stores no
    email anywhere. Asking for one item and reading a header never materializes
    them.
    """
    if ref.api == API_GITHUB:
        return f"{ref.api_base}/repos/{ref.path}/contributors?per_page=1&anon=1"
    return f"{ref.api_base}/projects/{ref.encoded_path}/repository/contributors?per_page=1"


def commit_count_url(ref: ProjectRef) -> str:
    """Return the URL whose headers carry `ref`'s total commit count."""
    if ref.api == API_GITHUB:
        return f"{ref.api_base}/repos/{ref.path}/commits?per_page=1"
    return f"{ref.api_base}/projects/{ref.encoded_path}/repository/commits?per_page=1"


def _github_metadata(payload: dict[str, Any]) -> HostMetadata:
    return HostMetadata(
        archived=_flag(payload.get("archived")),
        default_branch=_text(payload.get("default_branch")),
        description=_text(payload.get("description")),
        homepage=_text(payload.get("homepage")),
        license_id=_license_id(payload.get("license"), "spdx_id"),
        topics=_topics(payload.get("topics")),
        star_count=_count(payload.get("stargazers_count")),
        fork_count=_count(payload.get("forks_count")),
        open_issues_count=_count(payload.get("open_issues_count")),
        pushed_at=_text(payload.get("pushed_at")),
        created_at=_text(payload.get("created_at")),
    )


def _gitlab_metadata(payload: dict[str, Any]) -> HostMetadata:
    # GitLab has no homepage field, and last_activity_at is its pushed_at: it
    # moves on pushes and on issue activity alike, so it is a weaker freshness
    # signal than GitHub's and should not be read as a commit date.
    return HostMetadata(
        archived=_flag(payload.get("archived")),
        default_branch=_text(payload.get("default_branch")),
        description=_text(payload.get("description")),
        license_id=_license_id(payload.get("license"), "key"),
        topics=_topics(payload.get("topics")),
        star_count=_count(payload.get("star_count")),
        fork_count=_count(payload.get("forks_count")),
        open_issues_count=_count(payload.get("open_issues_count")),
        pushed_at=_text(payload.get("last_activity_at")),
        created_at=_text(payload.get("created_at")),
    )


def _forgejo_metadata(payload: dict[str, Any]) -> HostMetadata:
    # Forgejo's repository record carries no license, so license_id stays None
    # rather than being guessed from the repository's files.
    return HostMetadata(
        archived=_flag(payload.get("archived")),
        default_branch=_text(payload.get("default_branch")),
        description=_text(payload.get("description")),
        homepage=_text(payload.get("website")),
        topics=_topics(payload.get("topics")),
        star_count=_count(payload.get("stars_count")),
        fork_count=_count(payload.get("forks_count")),
        open_issues_count=_count(payload.get("open_issues_count")),
        pushed_at=_text(payload.get("updated_at")),
        created_at=_text(payload.get("created_at")),
    )


def _bitbucket_metadata(payload: dict[str, Any]) -> HostMetadata:
    # Bitbucket has no stars, no topics, no license, and no archive flag. Its
    # record is mostly description and dates, which is exactly the case
    # HostMetadata's optional fields exist for.
    return HostMetadata(
        default_branch=_text(_mapping(payload.get("mainbranch")).get("name")),
        description=_text(payload.get("description")),
        homepage=_text(payload.get("website")),
        pushed_at=_text(payload.get("updated_on")),
        created_at=_text(payload.get("created_on")),
    )


def _gerrit_metadata(payload: dict[str, Any]) -> HostMetadata:
    # Gerrit publishes a lifecycle state and a description, and nothing else
    # this module models. READ_ONLY and HIDDEN both mean no further work is
    # expected, which is what archived is asking.
    state = _text(payload.get("state"), MAX_LICENSE_CHARS)
    return HostMetadata(
        archived=None if state is None else state.upper() in GERRIT_ARCHIVED_STATES,
        description=_text(payload.get("description")),
    )


_METADATA_BY_API = {
    API_GITHUB: _github_metadata,
    API_GITLAB: _gitlab_metadata,
    API_FORGEJO: _forgejo_metadata,
    API_BITBUCKET: _bitbucket_metadata,
    API_GERRIT: _gerrit_metadata,
}


def metadata_from_payload(ref: ProjectRef, payload: object) -> HostMetadata:
    """Normalize one host's project record into the shape every caller reads."""
    return _METADATA_BY_API[ref.api](_mapping(payload))


def decode_payload(ref: ProjectRef, body: bytes) -> object:
    """Parse one API response body, undoing Gerrit's XSSI guard first.

    Gerrit prefixes every JSON response with )]}' on its own line so that a
    response cannot be executed as a script if it is ever loaded as one. It is
    not valid JSON and json.loads rejects it, so a caller that forgot this
    would read every Gerrit project as unreachable rather than as unparsed.
    """
    text = body.decode("utf-8", errors="replace")
    if ref.api == API_GERRIT:
        text = text.removeprefix(GERRIT_XSSI_PREFIX)
    return json.loads(text)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Look a header up without depending on the caller's casing."""
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


def _last_page(link: str) -> int | None:
    """Return the page number of the rel="last" link, if the header names one."""
    for part in link.split(","):
        if REL_LAST not in part.replace(" ", "") or (match := PAGE_PARAM_RE.search(part)) is None:
            continue
        return int(match.group(1))
    return None


def count_from_response(ref: ProjectRef, headers: Mapping[str, str], payload: object) -> int | None:
    """Read a total item count from a page requested one item wide.

    The point of asking for one item is that the total arrives in the headers,
    so a repository with thousands of commits costs the same single request as
    an empty one.

    GitLab is header-only *on purpose*, not merely for economy: its contributor
    response body lists author email addresses, and this project stores none
    anywhere. Never falling back to that body is what keeps that true even when
    the header is missing -- an unknown count is the correct answer there.

    GitHub omits Link entirely when the result fits on a single page, which for
    per_page=1 means zero or one item. Its contributor and commit bodies carry
    no email address, so measuring that page is both necessary and safe.
    """
    total = _header(headers, "X-Total")
    if total is not None and total.strip().isdigit():
        return int(total.strip())
    if ref.api != API_GITHUB:
        return None
    link = _header(headers, "Link")
    if link is not None and (last := _last_page(link)) is not None:
        return last
    return len(payload) if isinstance(payload, list) else None
