# SPDX-License-Identifier: GPL-3.0-or-later
"""Evolved-local authorization policy.

Toolhub OAuth proves identity and official Toolhub decides official write
permissions. This module only governs Toolhub Evolved's own complementary data:
drafts, overlays, moderation queues, and operator-only local controls.
"""

import os
from dataclasses import dataclass
from typing import Any

ROLE_USER = "user"
ROLE_REVIEWER = "reviewer"
ROLE_ADMIN = "admin"
ROLE_VALUES = {ROLE_USER, ROLE_REVIEWER, ROLE_ADMIN}

ACTION_TOOLHUB_WRITE = "toolhub.write"
ACTION_PRIVATE_READ = "evolved.private.read"
ACTION_PRIVATE_WRITE = "evolved.private.write"
ACTION_PRIVATE_DELETE = "evolved.private.delete"
ACTION_PUBLIC_WRITE = "evolved.public.write"
ACTION_PUBLIC_REVIEW = "evolved.public.review"
ACTION_OPERATOR = "evolved.operator"

OWNED_ACTIONS = {ACTION_PRIVATE_READ, ACTION_PRIVATE_WRITE, ACTION_PRIVATE_DELETE}

BASELINE_PERMISSIONS = {
    ACTION_TOOLHUB_WRITE,
    ACTION_PRIVATE_READ,
    ACTION_PRIVATE_WRITE,
    ACTION_PRIVATE_DELETE,
    ACTION_PUBLIC_WRITE,
}
REVIEWER_PERMISSIONS = BASELINE_PERMISSIONS | {ACTION_PUBLIC_REVIEW}
ADMIN_PERMISSIONS = REVIEWER_PERMISSIONS | {ACTION_OPERATOR}

ROLE_PERMISSIONS = {
    ROLE_USER: BASELINE_PERMISSIONS,
    ROLE_REVIEWER: REVIEWER_PERMISSIONS,
    ROLE_ADMIN: ADMIN_PERMISSIONS,
}

ROLE_LABELS = {
    ROLE_USER: "Signed-in user",
    ROLE_REVIEWER: "Reviewer",
    ROLE_ADMIN: "Admin/operator",
}

REVIEWER_USERS_ENV = "TOOLHUB_EVOLVED_REVIEWER_USERS"
ADMIN_USERS_ENV = "TOOLHUB_EVOLVED_ADMIN_USERS"


@dataclass(frozen=True)
class Resource:
    """Small resource wrapper for policy checks that are not tied to an ORM row."""

    owner_user_id: int | None = None


def clean_role(value: Any) -> str:  # noqa: ANN401 - untrusted DB/config value
    """Return a known Evolved role."""
    return value if isinstance(value, str) and value in ROLE_VALUES else ROLE_USER


def role_label(role: str) -> str:
    """Human-readable label for a role."""
    return ROLE_LABELS[clean_role(role)]


def role_permissions(role: str) -> list[str]:
    """Sorted permission set for API/UI exposure."""
    return sorted(ROLE_PERMISSIONS[clean_role(role)])


def user_role(user: object) -> str:
    """Return the user's Evolved role, defaulting safely to baseline."""
    return clean_role(getattr(user, "role", ROLE_USER))


def _configured_subjects(name: str) -> set[str]:
    return {part.strip().casefold() for part in os.environ.get(name, "").split(",") if part.strip()}


def configured_login_role(toolhub_user_id: str, username: str) -> str:
    """Return the role configured for a Toolhub identity during OAuth login."""
    subjects = {str(toolhub_user_id).casefold(), username.casefold()}
    if subjects & _configured_subjects(ADMIN_USERS_ENV):
        return ROLE_ADMIN
    if subjects & _configured_subjects(REVIEWER_USERS_ENV):
        return ROLE_REVIEWER
    return ROLE_USER


def role_for_login(toolhub_user_id: str, username: str, current_role: str | None = None) -> str:
    """Choose the stored Evolved role after a successful Toolhub OAuth login."""
    configured = configured_login_role(toolhub_user_id, username)
    return configured if configured != ROLE_USER else clean_role(current_role)


def _resource_owner_id(resource: object | None) -> int | None:
    if resource is None:
        return None
    if isinstance(resource, Resource):
        return resource.owner_user_id
    for attr in ("owner_user_id", "user_id", "created_by_user_id"):
        value = getattr(resource, attr, None)
        if isinstance(value, int):
            return value
    return None


def can(user: object | None, action: str, resource: object | None = None) -> bool:
    """Return whether a local Evolved user may perform an Evolved action."""
    if user is None:
        return False
    role = user_role(user)
    if action not in ROLE_PERMISSIONS[role]:
        return False
    if action in OWNED_ACTIONS:
        return _resource_owner_id(resource) == getattr(user, "id", None)
    return True
