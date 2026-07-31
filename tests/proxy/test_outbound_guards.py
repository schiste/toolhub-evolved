# SPDX-License-Identifier: GPL-3.0-or-later
"""Every outbound HTTP call is either aimed at a hardcoded host or validated.

The route-guard test in test_backend.py exists because /v1/recent/owners/ shipped
without an auth decorator and nobody noticed until a manual audit. This is the
same idea for the other pattern that keeps getting hand-copied: fetching a URL.
Adding a fetch that skips backend.outbound now has to be a deliberate, reviewed
edit to FIXED_TARGET_FETCHERS rather than an omission.

A `timeout` keyword is what identifies an HTTP call here: every outbound call in
proxy/ passes one, and nothing else does — dict.get and friends have no such
argument. That doubles as a check that no fetch is ever issued without a timeout.
"""

import ast
import pathlib

PROXY = pathlib.Path(__file__).resolve().parents[2] / "proxy"

# Fetches that need no URL validation because the destination is a constant in
# this repository, not something a user or upstream registry supplied. The value
# is the reason, so adding an entry is a claim somebody can check.
FIXED_TARGET_FETCHERS = {
    ("app.py", "_fetch_upstream"): "UPSTREAM constant; the read-only Toolhub proxy",
    ("cache_invalidation.py", "fetch_recent_change_rows"): "fixed RECENT_INVALIDATION_URL constant",
    ("cache_prewarm.py", "prewarm_endpoint"): "built from the static hot-endpoint list",
    ("crawl.py", "exists_upstream"): "UPSTREAM_TOOL constant",
    ("backend/toolhub.py", "exchange_code"): "official Toolhub token endpoint via base_url()",
    ("backend/toolhub.py", "refresh_grant"): "official Toolhub token endpoint via base_url()",
    ("backend/toolhub.py", "public_api_get"): "official Toolhub API via base_url()",
    ("backend/toolhub.py", "request_with_token"): "official Toolhub API via base_url()",
    ("backend/author_claims.py", "_fetch"): "TOOLFORGE_BASE_URL constant (Toolsadmin)",
    ("analyze_source.py", "_git_output"): "bounded local Git subprocess; no HTTP URL is fetched",
    ("repository_scan.py", "_git"): "bounded non-interactive Git subprocess with an explicit public-host allowlist",
}

# The shared implementation is itself allowed to call requests directly.
GUARDED_MODULE = "backend/outbound.py"


def _http_calls() -> list[tuple[str, str]]:
    """Return (module, enclosing function) for every outbound HTTP call in proxy/."""
    found = []
    for path in sorted(PROXY.rglob("*.py")):
        rel = path.relative_to(PROXY).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and any(kw.arg == "timeout" for kw in call.keywords):
                    found.append((rel, node.name))
                    break
    return found


def test_every_outbound_fetch_is_validated_or_aimed_at_a_fixed_host():
    unguarded = sorted(
        f"{module}::{func}"
        for module, func in _http_calls()
        if module != GUARDED_MODULE and (module, func) not in FIXED_TARGET_FETCHERS
    )
    assert unguarded == [], (
        f"outbound HTTP without URL validation: {unguarded}. Route it through "
        "backend.outbound.fetch_bounded, or add it to FIXED_TARGET_FETCHERS with "
        "the reason its destination is a constant."
    )


def test_fixed_target_allowlist_has_no_stale_entries():
    live = set(_http_calls())
    assert sorted(f"{m}::{f}" for m, f in set(FIXED_TARGET_FETCHERS) - live) == [], (
        "FIXED_TARGET_FETCHERS names fetches that no longer exist; drop them so the "
        "list keeps describing the real surface."
    )


def test_the_timeout_heuristic_still_finds_every_known_fetcher():
    # If this drops to zero the gate above silently passes forever, so pin the
    # floor: the allowlisted fixed-target fetches must all still be detected.
    detected = set(_http_calls())
    missing = sorted(f"{m}::{f}" for m, f in FIXED_TARGET_FETCHERS if (m, f) not in detected)
    assert missing == [], f"detector no longer sees known outbound calls: {missing}"
