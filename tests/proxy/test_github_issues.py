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


def test_json_context_falls_back_on_unserializable_values():
    class Unserializable:
        pass

    body = github_issues.render_body("A problem", {"bad": Unserializable()}, "Reporter")
    assert "```json\n{}\n```" in body


def test_publish_issue_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("TOOLHUB_GITHUB_TOKEN", raising=False)
    with pytest.raises(github_issues.IssueNotConfiguredError):
        github_issues.publish_issue("Title", "Body")


def test_publish_issue_sends_configured_labels(monkeypatch):
    monkeypatch.setenv("TOOLHUB_GITHUB_TOKEN", "secret-token")
    monkeypatch.setenv("TOOLHUB_GITHUB_ISSUE_LABELS", "bug, needs-triage")
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(201, {"number": 9, "html_url": "https://github.com/schiste/toolhub-evolved/issues/9"})

    monkeypatch.setattr(github_issues.requests, "post", post)
    github_issues.publish_issue("Title", "Body")
    assert calls[0][1]["json"]["labels"] == ["bug", "needs-triage"]


def test_publish_issue_wraps_request_exceptions(monkeypatch):
    monkeypatch.setenv("TOOLHUB_GITHUB_TOKEN", "secret-token")

    def post(*args, **kwargs):
        raise github_issues.requests.ConnectionError("network down")

    monkeypatch.setattr(github_issues.requests, "post", post)
    with pytest.raises(github_issues.IssueUnreachableError):
        github_issues.publish_issue("Title", "Body")


def test_publish_issue_raises_when_response_is_not_json(monkeypatch):
    monkeypatch.setenv("TOOLHUB_GITHUB_TOKEN", "secret-token")

    class UnreadableResponse(FakeResponse):
        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(github_issues.requests, "post", lambda *a, **k: UnreadableResponse(201, {}))
    with pytest.raises(github_issues.IssueUnreadableError):
        github_issues.publish_issue("Title", "Body")


def test_publish_issue_raises_when_response_is_incomplete(monkeypatch):
    monkeypatch.setenv("TOOLHUB_GITHUB_TOKEN", "secret-token")
    monkeypatch.setattr(github_issues.requests, "post", lambda *a, **k: FakeResponse(201, {"number": "not-an-int"}))
    with pytest.raises(github_issues.IssueIncompleteError):
        github_issues.publish_issue("Title", "Body")
