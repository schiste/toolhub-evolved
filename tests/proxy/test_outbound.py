# SPDX-License-Identifier: GPL-3.0-or-later
"""Policy behaviour of the shared outbound fetcher."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import outbound  # noqa: E402

PUBLIC = [(0, 0, 0, "", ("93.184.216.34", 443))]
PRIVATE = [(0, 0, 0, "", ("10.0.0.7", 443))]


def guard(url, policy=outbound.STRICT_PUBLIC):
    return outbound.require_allowed(url, policy, scheme_error="only https URLs are allowed")


def test_internal_wikimedia_cloud_domain_is_never_exempt(monkeypatch):
    # wikimedia.cloud is the *internal* instance domain — <instance>.<project>.
    # eqiad1.wikimedia.cloud, reachable only through a bastion. It sits one
    # keystroke away from the public wmcloud.org in anyone's memory, so pin it:
    # adding it to the exempt list must break this test.
    assert outbound.is_split_horizon_public_host("tools.wmcloud.org") is True
    for internal in ("mytool.myproject.eqiad1.wikimedia.cloud", "wikimedia.cloud", "db.wikimedia.cloud"):
        assert outbound.is_split_horizon_public_host(internal) is False, internal
    monkeypatch.setattr(outbound.socket, "getaddrinfo", lambda *a, **k: PRIVATE)
    with pytest.raises(ValueError, match="non-public"):
        guard("https://mytool.myproject.eqiad1.wikimedia.cloud/toolinfo.json")


def test_lookalike_domains_do_not_satisfy_the_suffix_check():
    # The leading dot is load-bearing: without it these would all match.
    for lookalike in ("eviltoolforge.org", "notwmcloud.org", "toolforge.org.evil.example", "xwmflabs.org"):
        assert outbound.is_split_horizon_public_host(lookalike) is False, lookalike


def test_split_horizon_exemption_applies_to_every_policy(monkeypatch):
    # The exemption is a property of running inside the cluster, not of any one
    # caller, so a policy cannot accidentally miss it.
    monkeypatch.setattr(outbound.socket, "getaddrinfo", lambda *a, **k: PRIVATE)
    for policy in (outbound.STRICT_PUBLIC, outbound.WIKIMEDIA_FEED):
        guard("https://magnustools.toolforge.org/toolinfo.json", policy)  # no raise
    with pytest.raises(ValueError, match="non-public"):
        guard("https://elsewhere.example/toolinfo.json")


def test_strict_public_still_refuses_http_everywhere(monkeypatch):
    # Fixing http-recorded Cloud URLs is the discovery layer's job; the strict
    # policy must not start accepting http to do it.
    monkeypatch.setattr(outbound.socket, "getaddrinfo", lambda *a, **k: PUBLIC)
    assert "http" not in outbound.STRICT_PUBLIC.schemes
    with pytest.raises(ValueError, match="only https"):
        guard("http://tools.wmflabs.org/toolinfo.json")


CALLER = outbound.Caller(
    user_agent="toolhub-evolved-tests/1.0 (https://example.org)",
    accept="*/*",
    scheme_error="only public URLs are probed",
)


class FakeProbeResp:
    """Headers-only fake: probe_reachable never reads a body."""

    def __init__(self, status=200, headers=None):
        self.status_code = status
        self.is_redirect = 300 <= status < 400
        self.is_permanent_redirect = status in (301, 308)
        self.headers = dict(headers or {})

    def raise_for_status(self):
        if self.status_code >= 400:
            raise outbound.requests.HTTPError(str(self.status_code))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeProbeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def _no_guard(monkeypatch):
    # require_allowed has its own tests above; probe_reachable's own tests
    # exercise the redirect/status/too-many-hops logic it wraps around it.
    monkeypatch.setattr(outbound, "require_allowed", lambda *_a, **_k: None)


def test_probe_reachable_reports_status_and_content_type(monkeypatch):
    _no_guard(monkeypatch)
    session = FakeProbeSession([FakeProbeResp(status=200, headers={"Content-Type": "text/html; charset=utf-8"})])

    result = outbound.probe_reachable(session, "https://tool.example/", caller=CALLER)

    assert result.url == "https://tool.example/"
    assert result.status_code == 200
    assert result.content_type == "text/html"


def test_probe_reachable_follows_a_redirect_to_its_final_url(monkeypatch):
    _no_guard(monkeypatch)
    session = FakeProbeSession(
        [
            FakeProbeResp(status=302, headers={"Location": "/new-path"}),
            FakeProbeResp(status=200, headers={"Content-Type": "application/json"}),
        ]
    )

    result = outbound.probe_reachable(session, "https://tool.example/old", caller=CALLER)

    assert result.url == "https://tool.example/new-path"
    assert result.status_code == 200
    assert result.content_type == "application/json"
    assert len(session.calls) == 2


def test_probe_reachable_requires_a_location_header_on_redirect(monkeypatch):
    _no_guard(monkeypatch)
    session = FakeProbeSession([FakeProbeResp(status=302, headers={})])

    with pytest.raises(ValueError, match="redirect missing Location header"):
        outbound.probe_reachable(session, "https://tool.example/", caller=CALLER)


def test_probe_reachable_gives_up_after_too_many_redirects(monkeypatch):
    _no_guard(monkeypatch)
    hops = outbound.PUBLIC_PROBE.max_redirects + 1
    session = FakeProbeSession([FakeProbeResp(status=302, headers={"Location": "/next"}) for _ in range(hops)])

    with pytest.raises(ValueError, match="too many redirects"):
        outbound.probe_reachable(session, "https://tool.example/", caller=CALLER)


def test_probe_reachable_propagates_a_non_redirect_http_error(monkeypatch):
    _no_guard(monkeypatch)
    session = FakeProbeSession([FakeProbeResp(status=404, headers={})])

    with pytest.raises(outbound.requests.HTTPError):
        outbound.probe_reachable(session, "https://tool.example/", caller=CALLER)
