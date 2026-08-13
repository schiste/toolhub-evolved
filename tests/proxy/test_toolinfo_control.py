# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend/toolinfo_control.py.

Pure-function unit tests: no Flask app, no database session. The module's
functions only touch plain Python objects and one ORM model that can be
constructed in memory without a session.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import toolinfo_control  # noqa: E402
from backend.models import ToolinfoControlChallenge, utcnow  # noqa: E402


def make_row(**overrides):
    defaults = {
        "id": 1,
        "user_id": 7,
        "tool_name": "alpha",
        "toolinfo_url": "https://example.org/toolinfo.json",
        "challenge_token": "secret-token",
        "status": toolinfo_control.CHALLENGE_STATUS_PENDING,
        "created_at": utcnow(),
        "expires_at": utcnow() + timedelta(hours=24),
        "verified_at": None,
        "last_checked_at": None,
        "last_error": None,
    }
    defaults.update(overrides)
    return ToolinfoControlChallenge(**defaults)


def test_new_token_is_unpredictable_and_url_safe():
    first = toolinfo_control.new_token()
    second = toolinfo_control.new_token()
    assert first != second
    assert len(first) > 32


def test_challenge_payload_includes_token_while_pending():
    row = make_row()
    payload = toolinfo_control.challenge_payload(row)
    assert payload["id"] == 1
    assert payload["toolName"] == "alpha"
    assert payload["field"] == toolinfo_control.CHALLENGE_FIELD
    assert payload["token"] == "secret-token"
    assert payload["verifiedAt"] == ""
    assert payload["lastCheckedAt"] == ""
    assert payload["lastError"] == ""


def test_challenge_payload_can_omit_token():
    row = make_row()
    payload = toolinfo_control.challenge_payload(row, include_token=False)
    assert "token" not in payload


def test_challenge_payload_omits_token_once_verified():
    now = utcnow()
    row = make_row(
        status=toolinfo_control.CHALLENGE_STATUS_VERIFIED,
        verified_at=now,
        last_checked_at=now,
        last_error="previous transient error",
    )
    payload = toolinfo_control.challenge_payload(row)
    assert "token" not in payload
    assert payload["verifiedAt"] == now.isoformat(timespec="seconds") + "Z"
    assert payload["lastCheckedAt"] == now.isoformat(timespec="seconds") + "Z"
    assert payload["lastError"] == "previous transient error"


def test_matching_item_finds_named_tool_in_a_single_object():
    assert toolinfo_control.matching_item({"name": "alpha"}, "alpha") == {"name": "alpha"}


def test_matching_item_finds_named_tool_in_a_list():
    data = [{"name": "alpha"}, {"name": "beta"}]
    assert toolinfo_control.matching_item(data, "beta") == {"name": "beta"}


def test_matching_item_bounds_the_search_to_first_200_entries():
    data = [{"name": f"tool-{i}"} for i in range(250)]
    data.append({"name": "tool-249-real"})
    assert toolinfo_control.matching_item(data, "tool-249-real") is None
    assert toolinfo_control.matching_item(data, "tool-199") == {"name": "tool-199"}


def test_matching_item_ignores_non_dict_entries_and_blank_names():
    data = ["not-a-dict", {"other": "field"}, {"name": "  "}, {"name": "alpha"}]
    assert toolinfo_control.matching_item(data, "alpha") == {"name": "alpha"}


def test_matching_item_returns_none_for_unsupported_shapes():
    assert toolinfo_control.matching_item("a string", "alpha") is None
    assert toolinfo_control.matching_item(None, "alpha") is None
    assert toolinfo_control.matching_item(42, "alpha") is None


def test_matching_item_returns_none_when_nothing_matches():
    assert toolinfo_control.matching_item([{"name": "beta"}], "alpha") is None


def test_fetch_matching_item_returns_matched_item(monkeypatch):
    monkeypatch.setattr(
        toolinfo_control.toolinfo_discovery,
        "fetch_toolinfo_json_once",
        lambda url: [{"name": "alpha"}],
    )
    item = toolinfo_control.fetch_matching_item("https://example.org/toolinfo.json", "alpha")
    assert item == {"name": "alpha"}


def test_fetch_matching_item_raises_when_no_match_found(monkeypatch):
    monkeypatch.setattr(
        toolinfo_control.toolinfo_discovery,
        "fetch_toolinfo_json_once",
        lambda url: [{"name": "beta"}],
    )
    with pytest.raises(ValueError, match="alpha: no matching item found at this toolinfo URL"):
        toolinfo_control.fetch_matching_item("https://example.org/toolinfo.json", "alpha")


def test_expired_reports_true_once_past_the_expiry_timestamp():
    row = make_row(expires_at=utcnow() - timedelta(hours=1))
    assert toolinfo_control.expired(row) is True


def test_expired_reports_false_before_the_expiry_timestamp():
    row = make_row(expires_at=utcnow() + timedelta(hours=1))
    assert toolinfo_control.expired(row) is False
