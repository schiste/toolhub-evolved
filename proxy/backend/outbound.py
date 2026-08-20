# SPDX-License-Identifier: GPL-3.0-or-later
"""Validated, size-capped fetching of URLs this project does not control.

Three modules independently grew the same shape — check the URL, then fetch it
under limits — and drifted apart while doing it: different body caps, different
schemes, one with an exemption the others lack, and one copy that lost the
docstring explaining why any of it was there. The code survived being copied;
the reasoning did not.

Everything that varies between callers now lives in a named FetchPolicy, so a
relaxation has to be declared and read rather than discovered by diffing two
files. Callers supply only what is genuinely theirs: the user agent, the accept
header, and the wording of the scheme rejection.

Anything reachable from a URL that a user or an upstream registry supplied must
go through here. Fetches aimed at a hardcoded host (the Toolhub API, Toolsadmin)
do not need it, and are listed in tests/proxy/test_outbound_guards.py so that
exemption stays deliberate.
"""

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests

from backend.http_headers import clean_header_value, clean_secret_header_value

CHUNK_BYTES = 64 * 1024

# Names that are genuinely reachable from the public internet but resolve to
# private addresses from inside the cluster, because Cloud VPS runs split-horizon
# DNS. Exempting them is a correction, not a relaxation: is_global is a proxy for
# "is this publicly reachable", and inside the cluster that proxy returns the
# wrong answer for hosts anyone on the internet can already fetch.
#
# wmcloud.org is the public HTTPS-proxy/floating-IP domain (it replaced the
# deprecated wmflabs.org); toolforge.org serves tools publicly by definition.
#
# The internal domain is wikimedia.cloud — instance FQDNs of the form
# <instance>.<project>.eqiad1.wikimedia.cloud, reachable only via a bastion.
# It must never appear here, and a test asserts that it does not.
#
# Suffixes keep their leading dot on purpose: without it, "eviltoolforge.org"
# would satisfy endswith("toolforge.org").
SPLIT_HORIZON_HOSTS = frozenset({"toolforge.org", "wmflabs.org"})
SPLIT_HORIZON_SUFFIXES = (".toolforge.org", ".wmcloud.org", ".wmflabs.org")


def is_split_horizon_public_host(host: str) -> bool:
    """Report whether a host is public despite resolving privately in-cluster.

    Applied to every policy rather than opted into per caller: every fetcher here
    runs in the same cluster behind the same resolver, so this is a property of
    where the code is deployed, not of what any one caller is allowed to reach.
    """
    return host in SPLIT_HORIZON_HOSTS or host.endswith(SPLIT_HORIZON_SUFFIXES)


@dataclass(frozen=True)
class Caller:
    """What one fetch site contributes: its identity and its own error wording.

    scheme_error is a phrase, not a full message — outbound prefixes the URL — so
    it can be declared once per module as a constant.
    """

    user_agent: str
    accept: str
    scheme_error: str


@dataclass(frozen=True)
class FetchPolicy:
    """What one class of caller is allowed to reach, and how much of it to read."""

    schemes: frozenset[str]
    max_body_bytes: int
    # Two different refusals, deliberately kept apart: follow_redirects=False means
    # a 3xx is an error in itself, while exhausting max_redirects means the chain
    # was too long. Callers' tests distinguish them.
    follow_redirects: bool
    max_redirects: int
    timeout: int | tuple[int, int]


@dataclass(frozen=True)
class BoundedResponse:
    """Body plus safe response metadata captured by a bounded fetch."""

    body: bytes
    url: str
    content_type: str
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class ProbeResponse:
    """Headers-only result from a guarded public URL reachability probe."""

    url: str
    status_code: int
    content_type: str


# User-registered toolinfo URLs: anyone can point these anywhere, so they get the
# strictest treatment. HTTPS-only is not cosmetic — resolution happens just before
# the fetch, leaving a DNS-rebinding window, and requiring TLS means an internal
# service would still have to present a valid certificate for the name we checked.
# Redirects are refused rather than followed so a public host cannot bounce us
# somewhere internal.
STRICT_PUBLIC = FetchPolicy(
    schemes=frozenset({"https"}),
    max_body_bytes=2 * 1024 * 1024,
    follow_redirects=False,
    max_redirects=0,
    timeout=20,
)

# Feeds mirrored from Toolhub's own crawler registry. Looser on purpose: these
# URLs are curated upstream rather than arbitrary, some are still plain HTTP, and
# real feeds are larger. Following redirects is bounded by re-validating every
# hop, so a redirect can never reach somewhere the first URL could not.
WIKIMEDIA_FEED = FetchPolicy(
    schemes=frozenset({"http", "https"}),
    max_body_bytes=8 * 1024 * 1024,
    follow_redirects=True,
    max_redirects=5,
    timeout=(5, 60),
)

PUBLIC_IMAGE = FetchPolicy(
    schemes=frozenset({"https"}),
    max_body_bytes=512 * 1024,
    follow_redirects=True,
    max_redirects=3,
    timeout=(5, 20),
)

PUBLIC_PROBE = FetchPolicy(
    schemes=frozenset({"http", "https"}),
    max_body_bytes=0,
    follow_redirects=True,
    max_redirects=3,
    timeout=(5, 15),
)

# Source-host APIs (GitHub, GitLab, Forgejo, Bitbucket, Gerrit). The host set is
# ours rather than user-supplied -- the URL is built from a resolved ProjectRef,
# not pasted in -- but the SSRF checks still apply on every hop, because a host
# that answers with a redirect is choosing where we go next.
#
# Redirects are followed because a renamed GitHub repository 301s to its new
# name, which is a fact worth having rather than an error. The credential does
# NOT follow: see fetch_api.
PROVIDER_API = FetchPolicy(
    schemes=frozenset({"https"}),
    max_body_bytes=1024 * 1024,
    follow_redirects=True,
    max_redirects=3,
    timeout=(5, 20),
)

# The only response headers worth carrying back out of a provider fetch. An
# allowlist rather than the whole mapping: everything here is eligible to be
# stored or logged, and Set-Cookie, Authorization echoes, and per-request
# tracing ids are not.
#
# ETag makes the next poll conditional (a 304 costs no GitHub rate budget at
# all). Link and X-Total carry the contributor and commit totals. The
# X-RateLimit pair and Retry-After are how the lane knows to slow down.
API_RESPONSE_HEADERS = frozenset(
    {
        "etag",
        "link",
        "retry-after",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "x-total",
    }
)

# 304 and 404 are answers, not failures: unchanged since last poll, and no such
# project. Neither should raise, because the lane records both.
API_NOT_MODIFIED = 304


def require_allowed(url: str, policy: FetchPolicy, *, scheme_error: str) -> None:
    """Raise ValueError unless `url` is fetchable under `policy`.

    scheme_error is caller-supplied because the phrasing is site-specific
    ("crawled", "discovered", "indexed") and each caller's tests assert on it.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in policy.schemes or not host:
        msg = f"{url}: {scheme_error}"
        raise ValueError(msg)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        msg = f"{url}: cannot resolve host ({exc})"
        raise ValueError(msg) from exc
    if is_split_horizon_public_host(host):
        return
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            msg = f"{url}: resolves to a non-public address - refused"
            raise ValueError(msg)


def _read_capped(resp: requests.Response, url: str, limit: int) -> bytes:
    """Read a streamed body, refusing to buffer more than `limit` bytes."""
    body = bytearray()
    for chunk in resp.iter_content(CHUNK_BYTES):
        body.extend(chunk)
        if len(body) > limit:
            msg = f"{url}: response larger than {limit} bytes"
            raise ValueError(msg)
    return bytes(body)


def fetch_bounded(session: requests.Session, url: str, *, policy: FetchPolicy, caller: Caller) -> bytes:
    """Fetch one document under `policy`, validating every URL it reaches."""
    return fetch_bounded_response(session, url, policy=policy, caller=caller).body


def fetch_bounded_response(
    session: requests.Session, url: str, *, policy: FetchPolicy, caller: Caller
) -> BoundedResponse:
    """Fetch one document and retain only bounded, non-sensitive metadata."""
    current_url = url
    for _hop in range(policy.max_redirects + 1):
        require_allowed(current_url, policy, scheme_error=caller.scheme_error)
        with session.get(
            current_url,
            headers={"User-Agent": caller.user_agent, "Accept": caller.accept},
            timeout=policy.timeout,
            stream=True,
            allow_redirects=False,
        ) as resp:
            if resp.is_redirect or resp.is_permanent_redirect:
                if not policy.follow_redirects:
                    msg = f"{current_url}: redirects are not followed - use the final URL"
                    raise ValueError(msg)
                location = resp.headers.get("Location") or resp.headers.get("location") or ""
                if not location:
                    msg = f"{current_url}: redirect missing Location header"
                    raise ValueError(msg)
                # Loop back through require_allowed: a redirect must not reach
                # anywhere the original URL was not already allowed to.
                current_url = urljoin(current_url, location)
                continue
            resp.raise_for_status()
            headers = getattr(resp, "headers", {})
            return BoundedResponse(
                body=_read_capped(resp, current_url, policy.max_body_bytes),
                url=current_url,
                content_type=(headers.get("Content-Type") or "").split(";", 1)[0].strip().lower(),
                etag=(headers.get("ETag") or "")[:255] or None,
                last_modified=(headers.get("Last-Modified") or "")[:255] or None,
            )
    msg = f"{url}: too many redirects"
    raise ValueError(msg)


def probe_reachable(session: requests.Session, url: str, *, caller: Caller) -> ProbeResponse:
    """Check a URL under SSRF/redirect guards without downloading its body."""
    current_url = url
    for _hop in range(PUBLIC_PROBE.max_redirects + 1):
        require_allowed(current_url, PUBLIC_PROBE, scheme_error=caller.scheme_error)
        with session.get(
            current_url,
            headers={"User-Agent": caller.user_agent, "Accept": caller.accept},
            timeout=PUBLIC_PROBE.timeout,
            stream=True,
            allow_redirects=False,
        ) as resp:
            headers = getattr(resp, "headers", {})
            if resp.is_redirect or resp.is_permanent_redirect:
                location = headers.get("Location") or headers.get("location") or ""
                if not location:
                    message = f"{current_url}: redirect missing Location header"
                    raise ValueError(message)
                current_url = urljoin(current_url, location)
                continue
            resp.raise_for_status()
            return ProbeResponse(
                url=current_url,
                status_code=int(resp.status_code),
                content_type=(headers.get("Content-Type") or "").split(";", 1)[0].strip().lower(),
            )
    message = f"{url}: too many redirects"
    raise ValueError(message)


@dataclass(frozen=True)
class ApiResponse:
    """One provider API answer: its status, its bounded body, and safe headers.

    Unlike BoundedResponse this does not imply success. A 304 arrives with an
    empty body and is the cheapest useful answer there is; a 404 means the
    project is gone; a 403 with x-ratelimit-remaining: 0 means stop. The caller
    decides, so the status is data rather than an exception.
    """

    status_code: int
    url: str
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def not_modified(self) -> bool:
        """Report whether the host said the cached copy is still current."""
        return self.status_code == API_NOT_MODIFIED


def _safe_headers(headers: object) -> dict[str, str]:
    """Keep only the allowlisted response headers, lower-cased and bounded."""
    items = getattr(headers, "items", None)
    if items is None:
        return {}
    kept = {}
    for key, value in items():
        lowered = str(key).lower()
        if lowered in API_RESPONSE_HEADERS:
            kept[lowered] = str(value)[:1024]
    return kept


def fetch_api(
    session: requests.Session,
    url: str,
    *,
    caller: Caller,
    token: str | None = None,
    etag: str | None = None,
) -> ApiResponse:
    """Fetch one source-host API URL, returning its status rather than raising.

    The credential is bound to the host that was authorized for the *first*
    URL and is dropped the moment a redirect leaves it. GitHub issued this
    token to GitHub; a host that answers our request with a Location pointing
    somewhere else must not be able to collect it. That is the same rule curl
    applies, and it is the reason redirects can be followed here at all.

    require_allowed still runs on every hop, so dropping the header is the
    second guard rather than the only one.
    """
    current_url = url
    authorized_host = (urlparse(url).hostname or "").lower()
    headers = {"User-Agent": caller.user_agent, "Accept": caller.accept}
    if token:
        headers["Authorization"] = f"Bearer {clean_secret_header_value('token', token)}"
    if etag:
        headers["If-None-Match"] = clean_header_value("etag", etag)
    for _hop in range(PROVIDER_API.max_redirects + 1):
        require_allowed(current_url, PROVIDER_API, scheme_error=caller.scheme_error)
        hop_headers = dict(headers)
        if (urlparse(current_url).hostname or "").lower() != authorized_host:
            hop_headers.pop("Authorization", None)
        with session.get(
            current_url,
            headers=hop_headers,
            timeout=PROVIDER_API.timeout,
            stream=True,
            allow_redirects=False,
        ) as resp:
            raw = getattr(resp, "headers", {})
            if resp.is_redirect or resp.is_permanent_redirect:
                location = raw.get("Location") or raw.get("location") or ""
                if not location:
                    message = f"{current_url}: redirect missing Location header"
                    raise ValueError(message)
                current_url = urljoin(current_url, location)
                continue
            status = int(resp.status_code)
            # A 304 carries no body by definition; reading one would block on
            # some servers rather than return empty.
            body = b"" if status == API_NOT_MODIFIED else _read_capped(resp, current_url, PROVIDER_API.max_body_bytes)
            return ApiResponse(status_code=status, url=current_url, body=body, headers=_safe_headers(raw))
    message = f"{url}: too many redirects"
    raise ValueError(message)
