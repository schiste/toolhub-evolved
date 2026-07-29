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
