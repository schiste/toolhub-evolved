# SPDX-License-Identifier: GPL-3.0-or-later
"""Run narrowly scoped tool and maintainer enrichment for one Toolhub user/tool."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, select

from backend import DEFAULT_DB_URL, db, maintainer_index, toolhub, toolinfo_discovery, toolinfo_sources
from backend.author_claims import (
    AuthorNameProvider,
    ToolforgeMaintainerProvider,
    author_names_from_toolhub_tool,
    claim_payload,
    dedupe_strings,
)
from backend.models import MaintainerActivityRollup, ToolAuthorClaim, ToolMaintainerEdge, User


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True, help="Existing Toolhub username to enrich, case-insensitive.")
    parser.add_argument("--tool-name", required=True, help="Exact official Toolhub tool name to enrich.")
    parser.add_argument(
        "--toolforge-name",
        required=True,
        help="Exact Toolforge service name used for maintainer proof.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser


def _configure_database() -> None:
    db.configure(os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL)
    db.init_schema()


def _existing_user(username: str) -> User:
    with db.session_scope() as s:
        user = s.execute(select(User).where(func.lower(User.username) == username.casefold())).scalar_one_or_none()
        if user is None:
            msg = f"Refusing to run scoped enrichment: user {username!r} does not exist."
            raise RuntimeError(msg)
        return User(
            id=user.id,
            wm_sub=user.wm_sub,
            username=user.username,
            role=user.role,
            registered_at=user.registered_at,
        )


def _official_tool(tool_name: str) -> dict[str, Any]:
    payload = toolhub.public_api_get(f"/api/tools/{quote(tool_name, safe='')}/")
    if not isinstance(payload, dict) or payload.get("name") != tool_name:
        msg = f"Refusing to run scoped enrichment: official tool {tool_name!r} was not found."
        raise RuntimeError(msg)
    return payload


def _candidate(tool: dict[str, Any], *, toolforge_name: str, username: str) -> dict[str, dict[str, Any]]:
    tool_name = str(tool.get("name") or "").strip()
    author_names = dedupe_strings(author_names_from_toolhub_tool(tool) or [username])
    provider = ToolforgeMaintainerProvider()
    return {
        tool_name: {
            "tool": tool,
            "matchedAuthorNames": author_names,
            "searchTerms": [f"toolforge:{toolforge_name}"],
            "evidenceUrl": provider.evidence_url(toolforge_name),
            "evidencePayload": {
                "toolforgeToolName": toolforge_name,
                "discoveryMethod": "scoped_operator_enrichment",
            },
        }
    }


def _record_scoped_claims(user: User, tool_name: str, entry: dict[str, Any]) -> list[dict[str, Any]]:
    author_provider = AuthorNameProvider()
    toolforge_provider = ToolforgeMaintainerProvider()
    author_names = entry["matchedAuthorNames"]
    with db.session_scope() as s:
        stored_user = s.get(User, user.id)
        if stored_user is None:
            msg = f"Refusing to run scoped enrichment: user id {user.id!r} disappeared."
            raise RuntimeError(msg)
        author_provider.record(
            s,
            stored_user,
            tool_name=tool_name,
            author_names=author_names,
            evidence_url=entry["evidenceUrl"],
            evidence_payload=entry["evidencePayload"],
        )
        toolforge_provider.verify(
            s,
            stored_user,
            tool_name=tool_name,
            author_names=author_names,
            toolhub_tool=entry["tool"],
        )
        rows = list(
            s.execute(
                select(ToolAuthorClaim).where(
                    ToolAuthorClaim.tool_name == tool_name,
                    ToolAuthorClaim.toolhub_username == stored_user.username,
                )
            ).scalars()
        )
        return [claim_payload(row) for row in rows]


def _public_maintainer_summary(tool_name: str, tool: dict[str, Any]) -> dict[str, Any]:
    with db.session_scope() as s:
        metadata_edges = maintainer_index.replace_toolhub_metadata_edges(s, tool_name, tool)
        claim_edges = maintainer_index.sync_author_claim_edges(s, tool_names=[tool_name])
        keys = [
            row[0]
            for row in s.execute(
                select(ToolMaintainerEdge.maintainer_key).where(ToolMaintainerEdge.tool_name == tool_name).distinct()
            ).all()
        ]
        rollups = maintainer_index.refresh_activity_rollups(s, maintainer_keys=keys)
        summary = maintainer_index.public_tool_summary(s, tool_name)
        stored_rollups = list(
            s.execute(select(MaintainerActivityRollup).where(MaintainerActivityRollup.maintainer_key.in_(keys or [""])))
            .scalars()
            .all()
        )
    return {
        "metadataEdgesRefreshed": len(metadata_edges),
        "claimEdgesRefreshed": len(claim_edges),
        "activityRollupsForToolKeys": len(rollups),
        "storedActivityRollupsForToolKeys": len(stored_rollups),
        "maintainerSummary": summary,
    }


def _scoped_claim_count(tool_name: str, username: str) -> int:
    with db.session_scope() as s:
        return s.scalar(
            select(func.count())
            .select_from(ToolAuthorClaim)
            .where(
                ToolAuthorClaim.tool_name == tool_name,
                func.lower(ToolAuthorClaim.toolhub_username) == username.casefold(),
            )
        )


def _run(username: str, tool_name: str, toolforge_name: str) -> dict[str, Any]:
    _configure_database()
    user = _existing_user(username)
    tool = _official_tool(tool_name)
    candidates = _candidate(tool, toolforge_name=toolforge_name, username=user.username)
    claims = _record_scoped_claims(user, tool_name, candidates[tool_name])
    discoveries_by_tool = toolinfo_discovery.ensure_pending_for_candidates(candidates)
    sources_by_tool = toolinfo_sources.sources_for_tools([tool_name])
    maintainer_payload = _public_maintainer_summary(tool_name, tool)
    verified_claims = [claim for claim in claims if claim.get("isVerified")]
    return {
        "scope": {"username": username, "toolName": tool_name, "toolforgeName": toolforge_name},
        "storedUsername": user.username,
        "toolTitle": tool.get("title") or tool.get("name"),
        "resolverCounts": {"verified": 1 if verified_claims else 0, "possible": 0 if verified_claims else 1},
        "toolinfoDiscovery": discoveries_by_tool.get(tool_name),
        "toolinfoSource": sources_by_tool.get(tool_name),
        "claimCountForScopedUserAndTool": _scoped_claim_count(tool_name, username),
        **maintainer_payload,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = _run(args.username, args.tool_name, args.toolforge_name)
    indent = 2 if args.pretty else None
    sys.stdout.write(json.dumps(payload, indent=indent, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
