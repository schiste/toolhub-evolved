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
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests

CHUNK_BYTES = 64 * 1024

# Wikimedia Cloud hostnames are public names that resolve to internal addresses
# from inside the cluster, so a blanket is_global check would refuse legitimate
# Toolforge feeds. Suffixes keep their leading dot on purpose: without it,
# "eviltoolforge.org" would satisfy endswith("toolforge.org").
WIKIMEDIA_INGRESS_HOSTS = frozenset({"toolforge.org", "wmflabs.org"})
WIKIMEDIA_INGRESS_SUFFIXES = (".toolforge.org", ".wmcloud.org", ".wmflabs.org")


def is_wikimedia_ingress_host(host: str) -> bool:
    """Report whether a public Wikimedia Cloud hostname may resolve internally."""
    return host in WIKIMEDIA_INGRESS_HOSTS or host.endswith(WIKIMEDIA_INGRESS_SUFFIXES)


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
    allow_internal_host: Callable[[str], bool] | None = None


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
# URLs are curated upstream rather than arbitrary, they legitimately include
# plain-HTTP and Wikimedia Cloud ingress hosts, and real feeds are larger. The
# relaxation is bounded by re-validating every redirect hop, so following a
# redirect can never reach somewhere the first URL could not.
WIKIMEDIA_FEED = FetchPolicy(
    schemes=frozenset({"http", "https"}),
    max_body_bytes=8 * 1024 * 1024,
    follow_redirects=True,
    max_redirects=5,
    timeout=(5, 60),
    allow_internal_host=is_wikimedia_ingress_host,
)


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
    if policy.allow_internal_host is not None and policy.allow_internal_host(host):
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
            return _read_capped(resp, current_url, policy.max_body_bytes)
    msg = f"{url}: too many redirects"
    raise ValueError(msg)
