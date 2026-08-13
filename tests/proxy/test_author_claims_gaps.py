# SPDX-License-Identifier: GPL-3.0-or-later
"""Small direct-unit coverage for author_claims helpers not reached elsewhere."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import author_claims  # noqa: E402


def test_toolsadmin_username_from_href_falls_through_when_marker_is_last_segment():
    # "profile" is present but has no following path segment, so the loop
    # must continue on to check "users" too, and finally return "" when
    # neither marker has anything after it.
    assert author_claims._toolsadmin_username_from_href("/profile/") == ""
    assert author_claims._toolsadmin_username_from_href("/other/path") == ""


def test_toolforge_maintainer_provider_fetch_uses_real_requests_get(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200
        text = "<html>maintainers</html>"

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(author_claims.requests, "get", fake_get)
    provider = author_claims.ToolforgeMaintainerProvider()

    status, body = provider._fetch("my-tool")

    assert status == 200
    assert body == "<html>maintainers</html>"
    assert calls[0][0] == "https://toolsadmin.wikimedia.org/tools/id/my-tool"
    assert calls[0][1]["headers"]["Accept"] == "text/html"
    assert calls[0][1]["timeout"] == author_claims.TOOLFORGE_TIMEOUT


def test_dedupe_toolsadmin_maintainers_skips_blank_and_duplicate_entries():
    entries = [
        author_claims.ToolsadminMaintainer(display_name="", username="blank-name"),
        author_claims.ToolsadminMaintainer(display_name="Ada", username="ada"),
        author_claims.ToolsadminMaintainer(display_name="Ada Duplicate", username="ada"),
    ]

    deduped = author_claims._dedupe_toolsadmin_maintainers(entries)

    assert [entry.display_name for entry in deduped] == ["Ada"]
