# SPDX-License-Identifier: GPL-3.0-or-later
"""Authorization and validation for verified wiki user-script listing edits."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend import catalog_projection, identity_graph, wikimedia_urls
from backend.models import CanonicalToolCache, PersonAccountBinding, User
from backend.sync import CURATION_KIND_WIKI_USERSCRIPT_OWNER, SOURCE_WIKI_USERSCRIPT

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

OWNER_EDIT_KIND = CURATION_KIND_WIKI_USERSCRIPT_OWNER
OWNER_EDIT_FIELDS = frozenset(
    {
        "title",
        "subtitle",
        "description",
        "license",
        "keywords",
        "for_wikis",
        "technology_used",
        "tasks",
        "audiences",
        "available_ui_languages",
        "content_types",
        "subject_domains",
        "sponsor",
        "url_alternates",
        "user_docs_url",
        "developer_docs_url",
        "feedback_url",
        "privacy_policy_url",
        "bugtracker_url",
        "translate_url",
    }
)

IdentityMatcher = Callable[[str, str, str], bool]


def _verified_wikimedia_id(session: Session, user: User) -> str:
    """Return the Wikimedia id only when both verified bindings share a person."""
    global_id = str(user.wikimedia_global_user_id or "").strip()
    toolhub_id = str(user.wm_sub or "").strip()
    if not global_id or not toolhub_id:
        return ""
    bindings = list(
        session.execute(
            select(PersonAccountBinding).where(
                PersonAccountBinding.provider.in_((identity_graph.PROVIDER_TOOLHUB, identity_graph.PROVIDER_WIKIMEDIA)),
                PersonAccountBinding.external_id.in_((toolhub_id, global_id)),
            )
        ).scalars()
    )
    by_key = {(row.provider, row.external_id): row for row in bindings}
    toolhub = by_key.get((identity_graph.PROVIDER_TOOLHUB, toolhub_id))
    wikimedia = by_key.get((identity_graph.PROVIDER_WIKIMEDIA, global_id))
    if toolhub is None or wikimedia is None:
        return ""
    for binding in (toolhub, wikimedia):
        if (
            binding.status != identity_graph.STATUS_VERIFIED
            or binding.revoked_at is not None
            or binding.person_id is None
        ):
            return ""
    return global_id if toolhub.person_id == wikimedia.person_id else ""


def owner_edit_context(
    session: Session,
    user: User,
    canonical: CanonicalToolCache,
    *,
    identity_matches: IdentityMatcher,
) -> dict[str, Any]:
    """Verify the signed-in Toolhub/Wikimedia binding against the source-page owner."""
    if canonical.source != SOURCE_WIKI_USERSCRIPT:
        return {"supported": False, "canEdit": False, "reason": "not_wiki_userscript"}
    page = wikimedia_urls.user_space_javascript_page(canonical.source_url)
    if page is None:
        return {"supported": False, "canEdit": False, "reason": "invalid_source_page"}
    owner = wikimedia_urls.canonical_username(page.username)
    context: dict[str, Any] = {
        "supported": True,
        "canEdit": False,
        "reason": "wikimedia_account_unverified",
        "ownerProof": {
            "wiki": page.domain,
            "username": owner,
            "sourceUrl": canonical.source_url,
            "proofMethod": "verified_person_binding_and_centralauth_id",
        },
    }
    global_id = _verified_wikimedia_id(session, user)
    if not global_id:
        return context
    if not identity_matches(page.domain, owner, global_id):
        context["reason"] = "wiki_owner_mismatch"
        return context
    context["canEdit"] = True
    context["reason"] = "verified_owner"
    context["ownerProof"]["globalUserId"] = global_id
    return context


LOCALIZED_URL_FIELDS = frozenset({"url_alternates", "user_docs_url", "developer_docs_url"})
MAX_LOCALIZED_URLS = 25
LANGUAGE_TAG = re.compile(r"^[A-Za-z0-9]{1,8}(?:-[A-Za-z0-9]{1,8})*$")


def _localized_url_patch(field: str, raw: Any) -> tuple[list[dict[str, str]], list[dict[str, str]]]:  # noqa: ANN401
    """Validate one bounded Toolhub localized-URL list without flattening it."""
    if not isinstance(raw, list):
        return [], [{"field": field, "message": "value must be a list of localized URLs"}]
    if len(raw) > MAX_LOCALIZED_URLS:
        return [], [{"field": field, "message": f"no more than {MAX_LOCALIZED_URLS} links are allowed"}]

    clean: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or not {"url", "language"}.issuperset(item) or "url" not in item:
            errors.append({"field": field, "message": f"link {index + 1} must contain only url and optional language"})
            continue
        url = " ".join(str(item.get("url") or "").split())
        validation = catalog_projection.field_validation(field, {"url": url})
        if not validation.get("valid"):
            errors.append(
                {"field": field, "message": str(validation.get("reason") or f"link {index + 1} has an invalid URL")}
            )
            continue
        if len(url) > catalog_projection.MAX_URL_LENGTH:
            errors.append(
                {
                    "field": field,
                    "message": f"link {index + 1} URL exceeds {catalog_projection.MAX_URL_LENGTH} characters",
                }
            )
            continue
        language = " ".join(str(item.get("language") or "").split())
        if language and not LANGUAGE_TAG.fullmatch(language):
            errors.append({"field": field, "message": f"link {index + 1} has an invalid language tag"})
            continue
        key = (language.casefold(), url)
        if key in seen:
            continue
        seen.add(key)
        entry = {"url": url}
        if language:
            entry["language"] = language
        clean.append(entry)
    return clean, errors


def validate_owner_patch(value: Any) -> tuple[dict[str, Any], list[dict[str, str]]]:  # noqa: ANN401
    """Validate only the listing fields a user-script owner may curate."""
    if not isinstance(value, dict):
        return {}, [{"field": "patch", "message": "patch must be an object"}]

    rejected = [
        {"field": str(field), "message": "field is not editable in a wiki user-script listing"}
        for field in value
        if field not in OWNER_EDIT_FIELDS
    ]
    allowed = {field: raw for field, raw in value.items() if field in OWNER_EDIT_FIELDS}
    localized = {field: raw for field, raw in allowed.items() if field in LOCALIZED_URL_FIELDS}
    regular = {field: raw for field, raw in allowed.items() if field not in LOCALIZED_URL_FIELDS}

    patch, errors = catalog_projection.validate_curation_patch(regular) if regular else ({}, [])
    if "title" in patch and not patch["title"]:
        patch.pop("title")
        errors.append({"field": "title", "message": "title cannot be blank"})
    for field, raw in localized.items():
        clean, localized_errors = _localized_url_patch(field, raw)
        errors.extend(localized_errors)
        if not localized_errors:
            patch[field] = clean
    errors.extend(rejected)
    if not patch and not errors:
        errors.append({"field": "patch", "message": "patch must contain at least one supported field"})
    return patch, errors
