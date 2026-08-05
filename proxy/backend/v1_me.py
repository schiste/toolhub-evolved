# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1/me/* endpoints, split out of backend/v1.py.

URL paths are unchanged; only the Flask endpoint names move under their
own blueprint. Helpers still shared with other families are reached as
`v1.<name>` so there is exactly one binding for each and patching or
reloading backend.v1 keeps working.
"""

from typing import Any
from urllib.parse import urlencode, urlparse

from flask import Blueprint, Flask, Response, current_app, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend import (
    authz,
    db,
    maintainer_index,
    people_index,
    tool_summaries,
    toolhub,
    toolinfo_discovery,
    toolinfo_sources,
    user_tool_cache,
    v1,
)
from backend.author_claims import (
    author_names_from_toolhub_tool,
    claim_is_verified,
    dedupe_strings,
    string_key,
)
from backend.models import (
    PersonProfile,
    ToolAuthorClaim,
    User,
    utcnow,
)
from backend.security import current_user_id, login_required, write_guard

v1_me_bp = Blueprint("v1_me", __name__)


def _string_key(value: Any) -> str:  # noqa: ANN401 - untrusted API JSON
    """Return a case-insensitive key for display/user/tool names."""
    return string_key(value)


def _dedupe_strings(values: list[Any]) -> list[str]:
    """Return non-empty strings in first-seen order, case-insensitively deduped."""
    return dedupe_strings(values)


def _toolhub_author_names(tool: dict) -> list[str]:
    """Return author display and identity names from one official Toolhub tool."""
    return author_names_from_toolhub_tool(tool)


def _toolhub_search_results(term: str) -> list[dict]:
    """Fetch candidate tools from official Toolhub search for one author term."""
    payload = toolhub.public_api_get(
        "/api/search/tools/",
        params={
            "author__term": term,
            "ordering": "-score",
            "page": 1,
            "page_size": v1.ME_TOOLS_SEARCH_PAGE_SIZE,
        },
    )
    results = payload.get("results") if isinstance(payload, dict) else []
    return [row for row in results if isinstance(row, dict)] if isinstance(results, list) else []


def _claims_by_tool(claims: list[dict]) -> dict[str, list[dict]]:
    """Group serialized author claims by Toolhub tool name."""
    out: dict[str, list[dict]] = {}
    for claim in claims:
        out.setdefault(_string_key(claim.get("toolName")), []).append(claim)
    return out


def _search_terms_for_user(username: str, claims: list[ToolAuthorClaim]) -> list[str]:
    """Return bounded Toolhub author-search terms for a signed-in user."""
    aliases = [
        row.author_name
        for row in claims
        if row.revoked_at is None
        and claim_is_verified(row.verification_status, row.verification_method, expires_at=row.expires_at)
    ]
    return _dedupe_strings([username, *aliases])[: v1.ME_TOOLS_MAX_SEARCH_TERMS]


def _add_candidate_tool(candidates: dict[str, dict], row: dict, term: str) -> None:
    """Merge one official Toolhub search result into the candidate map."""
    tool_name = v1._clean_name(row.get("name"))
    if tool_name is None:
        return
    author_names = _toolhub_author_names(row)
    matched = [name for name in author_names if _string_key(name) == _string_key(term)]
    if not matched:
        return
    entry = candidates.setdefault(
        tool_name,
        {
            "tool": row,
            "matchedAuthorNames": [],
            "claimAuthorNames": [],
            "searchTerms": [],
        },
    )
    entry["searchTerms"] = _dedupe_strings([*entry["searchTerms"], term])
    entry["matchedAuthorNames"] = _dedupe_strings([*entry["matchedAuthorNames"], *matched])
    entry["claimAuthorNames"] = _dedupe_strings([*entry["claimAuthorNames"], *matched])


def _add_toolforge_candidate(candidates: dict[str, dict], row: dict, toolforge_name: str, username: str) -> None:
    """Merge one exact Toolforge-derived Toolhub tool into the candidate map."""
    tool_name = v1._clean_name(row.get("name"))
    if tool_name is None:
        return
    entry = candidates.setdefault(
        tool_name,
        {
            "tool": row,
            "matchedAuthorNames": [],
            "claimAuthorNames": [],
            "searchTerms": [],
        },
    )
    entry["tool"] = row
    entry["searchTerms"] = _dedupe_strings([*entry["searchTerms"], f"toolforge:{toolforge_name}"])
    # Membership proves the signed-in account operates the tool. It does not
    # prove that the canonical Toolhub author name belongs to that account.
    entry["matchedAuthorNames"] = _dedupe_strings([*entry["matchedAuthorNames"], username])
    entry["claimAuthorNames"] = _dedupe_strings([*entry["claimAuthorNames"], username])
    entry["toolforgeMembershipName"] = toolforge_name
    entry["evidenceUrl"] = v1.TOOLFORGE_MAINTAINER_PROVIDER.evidence_url(toolforge_name)
    entry["evidencePayload"] = {
        **(entry.get("evidencePayload") if isinstance(entry.get("evidencePayload"), dict) else {}),
        "toolforgeToolName": toolforge_name,
        "discoveryMethod": "toolforge_ldap_membership",
    }


def _candidate_tools_for_terms(search_terms: list[str]) -> tuple[dict[str, dict], list[dict]]:
    """Search official Toolhub for all resolver terms, preserving partial successes."""
    candidates: dict[str, dict] = {}
    errors: list[dict] = []
    for term in search_terms:
        try:
            rows = _toolhub_search_results(term)
        except toolhub.ToolhubAPIError as exc:
            errors.append({"term": term, "status": exc.status_code, "details": exc.payload})
            continue
        except toolhub.requests.RequestException as exc:
            errors.append({"term": term, "status": 502, "details": {"message": str(exc)}})
            continue
        for row in rows:
            _add_candidate_tool(candidates, row, term)
    return candidates, errors


def _candidate_tools_for_toolforge_memberships(username: str) -> tuple[dict[str, dict], list[dict], list[str]]:
    """Fetch official Toolhub candidates from Toolforge tool-account memberships."""
    candidates: dict[str, dict] = {}
    errors: list[dict] = []
    toolforge_names = v1.TOOLFORGE_MEMBERSHIP_PROVIDER.tool_names(username)
    for toolforge_name in toolforge_names:
        official_name = f"toolforge-{toolforge_name}"
        try:
            row = v1._toolhub_tool_detail(official_name)
        except toolhub.ToolhubAPIError as exc:
            if exc.status_code != v1.HTTP_NOT_FOUND:
                errors.append({"term": official_name, "status": exc.status_code, "details": exc.payload})
            continue
        except toolhub.requests.RequestException as exc:
            errors.append({"term": official_name, "status": 502, "details": {"message": str(exc)}})
            continue
        if row is not None:
            _add_toolforge_candidate(candidates, row, toolforge_name, username)
    return candidates, errors, toolforge_names


def _resolver_item(
    tool_name: str,
    entry: dict,
    claims_by_tool: dict[str, list[dict]],
    discoveries_by_tool: dict[str, dict] | None = None,
    sources_by_tool: dict[str, dict] | None = None,
) -> dict:
    """Attach only this tool's provider claims to one candidate Toolhub tool."""
    claims = list(claims_by_tool.get(_string_key(tool_name), []))
    return {
        "tool": entry["tool"],
        "matchedAuthorNames": entry["matchedAuthorNames"],
        "searchTerms": entry["searchTerms"],
        "evidenceUrl": entry.get("evidenceUrl"),
        "claims": claims,
        "toolinfoDiscovery": (discoveries_by_tool or {}).get(tool_name, toolinfo_discovery.discovery_payload(None)),
        "toolinfoSource": (sources_by_tool or {}).get(tool_name),
    }


def _resolver_groups(
    candidates: dict[str, dict],
    claims_by_tool: dict[str, list[dict]],
    discoveries_by_tool: dict[str, dict] | None = None,
    sources_by_tool: dict[str, dict] | None = None,
) -> dict:
    """Split candidate tools into verified and possible groups."""
    groups: dict[str, list[dict]] = {"verified": [], "possible": []}
    for tool_name, entry in candidates.items():
        item = _resolver_item(tool_name, entry, claims_by_tool, discoveries_by_tool, sources_by_tool)
        key = "verified" if any(claim.get("isVerified") for claim in item["claims"]) else "possible"
        groups[key].append(item)
    return groups


def _author_search_evidence_url(search_term: str) -> str:
    """Return the official Toolhub search URL that produced an author-name match."""
    query = urlencode(
        {
            "author__term": search_term,
            "ordering": "-score",
            "page": 1,
            "page_size": v1.ME_TOOLS_SEARCH_PAGE_SIZE,
        }
    )
    return f"{toolhub.base_url()}/api/search/tools/?{query}"


def _record_candidate_provider_claims(user: User, candidates: dict[str, dict]) -> list[dict]:
    """Persist resolver-side provider evidence and return fresh claim payloads."""
    with db.session_scope() as s:
        for tool_name, entry in candidates.items():
            search_term = entry["searchTerms"][0] if entry["searchTerms"] else user.username
            v1.AUTHOR_NAME_PROVIDER.record(
                s,
                user,
                tool_name=tool_name,
                author_names=entry.get("claimAuthorNames", entry["matchedAuthorNames"]),
                evidence_url=entry.get("evidenceUrl") or _author_search_evidence_url(search_term),
                evidence_payload=entry.get("evidencePayload") or {"searchTerms": entry["searchTerms"]},
            )
            membership_name = entry.get("toolforgeMembershipName")
            if membership_name:
                v1.TOOLFORGE_MAINTAINER_PROVIDER.record_membership(
                    s,
                    user,
                    tool_name=tool_name,
                    toolforge_name=membership_name,
                )
            else:
                v1.TOOLFORGE_MAINTAINER_PROVIDER.verify(
                    s,
                    user,
                    tool_name=tool_name,
                    author_names=entry["matchedAuthorNames"],
                    toolhub_tool=entry["tool"],
                )
        rows = list(
            s.execute(
                select(ToolAuthorClaim).where(
                    v1._author_claim_owned_by(user),
                    ToolAuthorClaim.revoked_at.is_(None),
                )
            ).scalars()
        )
        payloads = [v1._claim_payload(row) for row in rows]
    # Refresh the derived maintainer/people index in its own transaction, and
    # never fail this read because of it. It rebuilds a tool's relationships by
    # deleting and re-inserting them, so two concurrent callers legitimately
    # race: one deletes rows the other has already loaded, and the loser's flush
    # raises StaleDataError. That was surfacing as a 500 here, which the client
    # retried, which produced more concurrent callers — a loop that saturated
    # the webservice. The index is supplementary to the payloads above and the
    # people-reconcile job rebuilds it regardless, so a skipped refresh costs
    # nothing a moment later.
    try:
        with db.session_scope() as s:
            maintainer_index.sync_author_claim_edges(s, user_ids=[user.id])
    except SQLAlchemyError as exc:
        current_app.logger.info("deferred maintainer index refresh for %s: %s", user.username, exc)
    return payloads


@v1_me_bp.route("/v1/me/claims/")
@login_required
def v1_me_claims() -> Response:
    """List relationship-claim workflow rows owned by the signed-in account."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - login_required guarantees this
    user = v1._require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    with db.session_scope() as s:
        rows = list(
            s.execute(
                select(ToolAuthorClaim)
                .where(v1._author_claim_owned_by(user))
                .order_by(ToolAuthorClaim.updated_at.desc(), ToolAuthorClaim.id.desc())
            ).scalars()
        )
        return jsonify({"claims": [v1._claim_payload(row) for row in rows]})


def _resolve_me_tools(user: User) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Perform one expensive resolver pass and return its private payload."""
    with db.session_scope() as s:
        stored_claims = list(
            s.execute(
                select(ToolAuthorClaim).where(
                    v1._author_claim_owned_by(user),
                    ToolAuthorClaim.revoked_at.is_(None),
                )
            ).scalars()
        )
    search_terms = _search_terms_for_user(user.username, stored_claims)
    candidates, errors = _candidate_tools_for_terms(search_terms)
    toolforge_candidates, toolforge_errors, toolforge_tool_names = _candidate_tools_for_toolforge_memberships(
        user.username
    )
    for tool_name, entry in toolforge_candidates.items():
        existing = candidates.get(tool_name)
        if existing is None:
            candidates[tool_name] = entry
            continue
        existing["tool"] = entry["tool"]
        existing["matchedAuthorNames"] = _dedupe_strings(
            [*existing["matchedAuthorNames"], *entry["matchedAuthorNames"]]
        )
        existing["claimAuthorNames"] = _dedupe_strings(
            [*existing.get("claimAuthorNames", []), *entry.get("claimAuthorNames", [])]
        )
        if entry.get("toolforgeMembershipName"):
            existing["toolforgeMembershipName"] = entry["toolforgeMembershipName"]
        existing["searchTerms"] = _dedupe_strings([*existing["searchTerms"], *entry["searchTerms"]])
        if entry.get("evidenceUrl"):
            existing["evidenceUrl"] = entry["evidenceUrl"]
        if isinstance(entry.get("evidencePayload"), dict):
            existing["evidencePayload"] = {
                **(existing.get("evidencePayload") if isinstance(existing.get("evidencePayload"), dict) else {}),
                **entry["evidencePayload"],
            }
    errors.extend(toolforge_errors)

    if errors and not candidates and len(errors) == len(search_terms):
        return None, errors

    claim_payloads = _record_candidate_provider_claims(user, candidates)
    claims_by_tool = _claims_by_tool(claim_payloads)
    discoveries_by_tool = toolinfo_discovery.ensure_pending_for_candidates(candidates)
    sources_by_tool = toolinfo_sources.sources_for_tools(list(candidates))
    groups = _resolver_groups(candidates, claims_by_tool, discoveries_by_tool, sources_by_tool)

    return (
        {
            "username": user.username,
            "searchTerms": search_terms,
            "toolforgeToolNames": toolforge_tool_names,
            "toolinfoDiscovery": discoveries_by_tool,
            "toolinfoSources": sources_by_tool,
            "counts": {"verified": len(groups["verified"]), "possible": len(groups["possible"])},
            "verified": groups["verified"],
            "possible": groups["possible"],
            "errors": errors,
        },
        errors,
    )


def _refresh_me_tools_cache(app: Flask, user_id: int) -> dict[str, Any] | None:
    """Load the user in the worker and refresh their private resolver row."""
    with app.app_context(), db.advisory_lock(f"user-tool-resolver:{user_id}") as acquired:
        if not acquired:
            return None
        with db.session_scope() as s:
            user = s.get(User, user_id)
        if user is None:
            message = "Toolhub user no longer exists"
            raise RuntimeError(message)
        payload, errors = _resolve_me_tools(user)
        if payload is None:
            message = f"official Toolhub unavailable: {errors}"
            raise RuntimeError(message)
        return payload


def _me_tools_summaries(payload: dict[str, Any]) -> dict[str, Any]:
    """Materialized summaries for the tools this payload is about to render.

    Composed per response rather than stored with the payload: summaries are
    public and change on their own schedule, so caching them inside a private
    per-user replica would both leak them into the wrong lifetime and let them
    go stale with it.

    Strictly read-only (`refresh_stale=False`). Queueing builds from here would
    let a private read kick off catalog-wide maintainer and people syncing —
    the same coupling that turned this endpoint into a retry storm before. A
    name with no materialized row is simply absent, and the client's own
    deferred refresh picks it up through the public summaries endpoint, which
    is where that work belongs.
    """
    names: list[str] = []
    for bucket in ("verified", "possible"):
        for item in payload.get(bucket) or []:
            if not isinstance(item, dict):
                continue
            tool = item.get("tool")
            name = tool.get("name") if isinstance(tool, dict) else None
            if isinstance(name, str) and name and name not in names:
                names.append(name)
            if len(names) >= v1._ME_TOOLS_SUMMARY_LIMIT:
                break
    if not names:
        return {}
    return tool_summaries.summaries_for(
        names, v1._build_local_tool_summary, refresh_stale=False, view=tool_summaries.VIEW_CARD
    ).results


def _private_resolver_response(payload: dict[str, Any], metadata: dict[str, str]) -> Response:
    # Carry the health summaries with the tools they belong to. Without this the
    # client can only ask for them after this response lands, so the cards paint
    # once without a score and again with one.
    response = jsonify({**payload, "cache": metadata, "summaries": _me_tools_summaries(payload)})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@v1_me_bp.route("/v1/me/tools/")
@login_required
def v1_me_tools() -> Response:
    """Read the private local replica, refreshing it only when stale or absent."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — login_required guarantees this
    user = v1._require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    cached = user_tool_cache.read(uid)
    if cached is not None:
        if cached.metadata["status"] == "stale":
            app = current_app._get_current_object()
            user_tool_cache.queue_refresh(uid, lambda user_id: _refresh_me_tools_cache(app, user_id))
            cached.metadata["refresh"] = "queued"
        return _private_resolver_response(cached.payload, cached.metadata)

    # Serialize cold fills per user. The second read matters when another
    # worker populated the row while this request was waiting for the lock.
    with db.advisory_lock(f"user-tool-resolver:{uid}", timeout_seconds=10) as acquired:
        if not acquired:
            resp = jsonify(
                {
                    "error": "resolver fill in progress",
                    "detail": "Your private Toolhub data is being refreshed. Retry shortly.",
                }
            )
            resp.status_code = 503
            resp.headers["Cache-Control"] = "private, no-store"
            resp.headers["Retry-After"] = "3"
            return resp

        cached = user_tool_cache.read(uid)
        if cached is not None:
            if cached.metadata["status"] == "stale":
                app = current_app._get_current_object()
                user_tool_cache.queue_refresh(uid, lambda user_id: _refresh_me_tools_cache(app, user_id))
                cached.metadata["refresh"] = "queued"
            return _private_resolver_response(cached.payload, cached.metadata)

        payload, errors = _resolve_me_tools(user)
        if payload is None:
            resp = jsonify({"error": "official Toolhub is unavailable", "username": user.username, "errors": errors})
            resp.status_code = 502
            return resp
        user_tool_cache.store(uid, payload)
        return _private_resolver_response(payload, {"status": "miss"})


def _profile_url(value: Any) -> str:  # noqa: ANN401 - JSON input
    clean = str(value or "").strip()[:2000]
    if not clean:
        return ""
    parsed = urlparse(clean)
    return clean if parsed.scheme == "https" and parsed.netloc else ""


@v1_me_bp.route("/v1/me/profile/")
@login_required
def v1_me_profile_get() -> Response:
    """Read Evolved-owned profile content for the signed-in person."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - login_required guarantees a session
    with db.session_scope() as s:
        user = s.get(User, uid)
        if user is None:
            return v1._deny(v1.HTTP_UNAUTHORIZED, "sign in required")
        person = people_index.link_user(s, user)
        return jsonify({"profile": v1._profile_payload(s.get(PersonProfile, person.id), person)})


@v1_me_bp.route("/v1/me/profile/", methods=["PUT"])
@write_guard
def v1_me_profile_put() -> Response:
    """Update Evolved-owned profile content for the signed-in person."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 - write_guard guarantees a session
    with db.session_scope() as s:
        user = s.get(User, uid)
        if user is None:
            return v1._deny(v1.HTTP_UNAUTHORIZED, "sign in required")
        person = people_index.link_user(s, user)
        profile = s.get(PersonProfile, person.id)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return v1._bad("JSON object required")
        if profile is None:
            profile = PersonProfile(person_id=person.id)
            s.add(profile)
        profile.bio = str(payload.get("bio") or "").strip()[:2000]
        profile.avatar_url = _profile_url(payload.get("avatarUrl"))
        profile.website_url = _profile_url(payload.get("websiteUrl"))
        profile.location = str(payload.get("location") or "").strip()[:255]
        links = payload.get("links") if isinstance(payload.get("links"), list) else []
        profile.links = [url for value in links[:10] if (url := _profile_url(value))]
        profile.visibility = "private" if payload.get("visibility") == "private" else "public"
        profile.updated_at = utcnow()
        s.flush()
        return jsonify({"profile": v1._profile_payload(profile, person)})
