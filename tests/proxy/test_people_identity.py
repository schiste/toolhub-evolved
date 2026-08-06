# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for conservative external identity discovery."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import people_identity  # noqa: E402


def test_exact_toolhub_identity_includes_stable_cross_system_ids():
    provider = people_identity.ToolhubIdentityProvider(
        fetcher=lambda _label: (
            200,
            {
                "count": 1,
                "results": [
                    {
                        "id": 152,
                        "username": "Magnus Manske",
                        "social_auth": [{"provider": "wikimedia", "uid": "160"}],
                    }
                ],
            },
        )
    )

    identity = provider.lookup_exact("magnus manske")

    assert identity is not None
    assert identity.evidence_payload() == {
        "toolhubUserId": "152",
        "toolhubUsername": "Magnus Manske",
        "wikimediaGlobalUserId": "160",
    }


def test_toolhub_identity_lookup_rejects_fuzzy_duplicate_and_idless_rows():
    payloads = [
        {"results": [{"id": 1, "username": "Magnus242"}]},
        {"results": [{"id": 1, "username": "Magnus"}, {"id": 2, "username": "MAGNUS"}]},
        {"results": [{"username": "Magnus"}]},
    ]

    for payload in payloads:
        provider = people_identity.ToolhubIdentityProvider(fetcher=lambda _label, value=payload: (200, value))
        assert provider.lookup_exact("Magnus") is None


def test_toolhub_identity_lookup_handles_upstream_failure_and_invalid_payload():
    assert people_identity.ToolhubIdentityProvider(fetcher=lambda _label: (503, {})).lookup_exact("Magnus") is None
    assert people_identity.ToolhubIdentityProvider(fetcher=lambda _label: (200, [])).lookup_exact("Magnus") is None
    assert people_identity.ToolhubIdentityProvider(fetcher=lambda _label: (200, {"results": None})).lookup_exact(
        "Magnus"
    ) is None
    assert (
        people_identity.ToolhubIdentityProvider(fetcher=lambda _label: (_ for _ in ()).throw(TimeoutError()))
        .lookup_exact("Magnus")
        is None
    )
