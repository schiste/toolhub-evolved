# SPDX-License-Identifier: GPL-3.0-or-later
"""External identity discovery used to propose, never silently apply, links."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

from backend import toolhub

IdentityFetcher = Callable[[str], tuple[int, object]]
IDENTITY_LOOKUP_LIMIT = 2
HTTP_OK = 200


@dataclass(frozen=True)
class ToolhubIdentity:
    """One exact, stable Toolhub identity candidate."""

    toolhub_user_id: str
    toolhub_username: str
    wikimedia_global_user_id: str = ""

    def evidence_payload(self) -> dict[str, str]:
        """Return bounded evidence suitable for operator review."""
        return {
            "toolhubUserId": self.toolhub_user_id,
            "toolhubUsername": self.toolhub_username,
            "wikimediaGlobalUserId": self.wikimedia_global_user_id,
        }


class ToolhubIdentityProvider:
    """Resolve unique exact usernames through Toolhub's public users API."""

    def __init__(self, fetcher: IdentityFetcher | None = None) -> None:
        """Store an injectable public Toolhub user fetcher."""
        self.fetcher = fetcher or self._fetch

    def lookup_exact(self, label: str) -> ToolhubIdentity | None:
        """Return one exact identity, rejecting fuzzy, duplicate, or id-less rows."""
        clean_label = str(label or "").strip()[:255]
        if not clean_label:
            return None
        try:
            status, payload = self.fetcher(clean_label)
        except (OSError, TimeoutError, ValueError, requests.RequestException):
            return None
        if status != HTTP_OK or not isinstance(payload, dict):
            return None
        rows = payload.get("results")
        if not isinstance(rows, list):
            return None
        exact = [
            row
            for row in rows
            if isinstance(row, dict)
            and str(row.get("username") or "").strip().casefold() == clean_label.casefold()
            and str(row.get("id") or "").strip()
        ]
        if len(exact) != 1:
            return None
        row = exact[0]
        return ToolhubIdentity(
            toolhub_user_id=str(row["id"]).strip()[:64],
            toolhub_username=str(row["username"]).strip()[:255],
            wikimedia_global_user_id=toolhub.wikimedia_global_user_id(row),
        )

    @staticmethod
    def _fetch(label: str) -> tuple[int, object]:
        response = requests.get(
            f"{toolhub.base_url()}/api/users/",
            params={"username": label, "page_size": IDENTITY_LOOKUP_LIMIT},
            headers={"User-Agent": toolhub.USER_AGENT, "Accept": "application/json"},
            timeout=toolhub.REQUEST_TIMEOUT,
        )
        try:
            payload: Any = response.json()
        except ValueError:
            payload = None
        return response.status_code, payload
