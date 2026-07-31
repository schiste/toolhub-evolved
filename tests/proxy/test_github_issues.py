# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the server-only GitHub issue adapter."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import github_issues  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


def test_render_body_bounds_context_and_keeps_report_sections():
    body = github_issues.render_body("A problem", {"path": "/tools/a", "large": "x" * 40000}, "Reporter")
    assert "## Report" in body
    assert "## Context" in body
    assert "A problem" in body
    assert len(body) <= github_issues.MAX_BODY_CHARS


def test_publish_issue_sends_server_token_and_returns_issue(monkeypatch):
    monkeypatch.setenv("TOOLHUB_GITHUB_TOKEN", "secret-token")
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(201, {"number": 7, "html_url": "https://github.com/schiste/toolhub-evolved/issues/7"})

    monkeypatch.setattr(github_issues.requests, "post", post)
    result = github_issues.publish_issue("Title", "Body")
    assert result["number"] == 7
    assert calls[0][0] == "https://api.github.com/repos/schiste/toolhub-evolved/issues"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer secret-token"


def test_publish_issue_rejects_github_failure(monkeypatch):
    monkeypatch.setenv("TOOLHUB_GITHUB_TOKEN", "secret-token")
    monkeypatch.setattr(github_issues.requests, "post", lambda *args, **kwargs: FakeResponse(403, {}))
    with pytest.raises(github_issues.IssuePublishError, match="did not accept"):
        github_issues.publish_issue("Title", "Body")
