# SPDX-License-Identifier: GPL-3.0-or-later
"""Small, server-only GitHub Issues publisher for authenticated user reports."""

import json
import os
from http import HTTPStatus
from typing import Any

import requests

DEFAULT_REPOSITORY = "schiste/toolhub-evolved"
GITHUB_API = "https://api.github.com"
MAX_TITLE = 200
MAX_DESCRIPTION = 12000
MAX_CONTEXT_CHARS = 30000
MAX_BODY_CHARS = 50000


class IssuePublishError(RuntimeError):
    """A safe, user-facing failure from the GitHub Issues API.

    The text is carried by the subclass rather than passed in at the raise
    site, because it is not an internal detail: v1 returns `str(exc)` straight
    to the caller, so each message is part of the API's contract and belongs
    with the failure it describes.
    """

    message = "The issue could not be published."

    def __init__(self) -> None:
        """Raise with the subclass's message."""
        super().__init__(self.message)


class IssueNotConfiguredError(IssuePublishError):
    """No GitHub token or repository is configured for this deployment."""

    message = "Issue publishing is not configured."


class IssueUnreachableError(IssuePublishError):
    """The GitHub API could not be contacted at all."""

    message = "GitHub could not be reached."


class IssueRejectedError(IssuePublishError):
    """GitHub answered, but did not create the issue."""

    message = "GitHub did not accept the issue."


class IssueUnreadableError(IssuePublishError):
    """GitHub's response was not JSON."""

    message = "GitHub returned an invalid issue response."


class IssueIncompleteError(IssuePublishError):
    """GitHub's response was JSON but lacked the issue number or URL."""

    message = "GitHub returned an incomplete issue response."


def repository() -> str:
    """Return the configured owner/repository without exposing credentials."""
    return str(os.environ.get("TOOLHUB_GITHUB_REPOSITORY") or DEFAULT_REPOSITORY).strip()


def configured() -> bool:
    """Return whether the server has enough configuration to publish issues."""
    return bool(os.environ.get("TOOLHUB_GITHUB_TOKEN", "").strip() and repository())


def _labels() -> list[str]:
    return [
        label.strip()[:50] for label in os.environ.get("TOOLHUB_GITHUB_ISSUE_LABELS", "").split(",") if label.strip()
    ]


def _json_context(context: dict[str, Any]) -> str:
    try:
        encoded = json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True)
    except (TypeError, ValueError):
        encoded = "{}"
    return encoded[:MAX_CONTEXT_CHARS]


def render_body(description: str, context: dict[str, Any], reporter: str) -> str:
    """Build the public issue body from bounded, reviewable report fields."""
    body = "\n".join(
        [
            "## Report",
            description.strip()[:MAX_DESCRIPTION],
            "",
            "## Context",
            "```json",
            _json_context(context),
            "```",
            "",
            "_Submitted through Toolhub Evolved by an authenticated user._",
            f"\n<!-- toolhub-evolved-reporter: {reporter[:255]} -->",
        ]
    )
    return body[:MAX_BODY_CHARS]


def publish_issue(title: str, body: str) -> dict[str, Any]:
    """Create one issue through GitHub using the server-only configured token."""
    token = os.environ.get("TOOLHUB_GITHUB_TOKEN", "").strip()
    if not token or not repository():
        raise IssueNotConfiguredError
    url = f"{GITHUB_API}/repos/{repository()}/issues"
    payload: dict[str, Any] = {"title": title[:MAX_TITLE], "body": body[:MAX_BODY_CHARS]}
    labels = _labels()
    if labels:
        payload["labels"] = labels
    try:
        response = requests.post(
            url,
            json=payload,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "toolhub-evolved-issue-report",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise IssueUnreachableError from exc
    if response.status_code != HTTPStatus.CREATED:
        raise IssueRejectedError
    try:
        result = response.json()
    except ValueError as exc:
        raise IssueUnreadableError from exc
    number = result.get("number")
    html_url = result.get("html_url")
    if not isinstance(number, int) or not isinstance(html_url, str):
        raise IssueIncompleteError
    return {"number": number, "url": html_url, "repository": repository()}
