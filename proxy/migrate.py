# SPDX-License-Identifier: GPL-3.0-or-later
"""One-off data migrations, run once per deploy before the webservice restarts.

Schema setup (`backend.db.init_schema`) runs inside every worker process at
startup and is deliberately DDL-only. Anything proportional to table size has
to live here instead: run from a worker, a row-level migration executes once
per process on every restart, with several workers doing it at once, against
tables live requests need — which is exactly how a deploy turns into an outage.

Every migration below is idempotent and batched into short transactions, so
re-running this is cheap and safe, and a partial run simply resumes.

    tools/deploy.sh runs this automatically. Manually:
        webservice python3.13 shell -- \
          ~/www/python/venv/bin/python ~/repo/proxy/migrate.py
"""

import os
import sys
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import func, inspect, or_, select, text

from backend import (
    DEFAULT_DB_URL,
    api_cache,
    canonical_tools,
    catalog_projection,
    db,
    identity_graph,
    maintainer_index,
    people_index,
)
from backend.author_claims import claim_relationship_for_method
from backend.models import (
    Person,
    PersonIdentifier,
    ToolAuthorClaim,
    ToolAuthorKey,
    ToolhubAccountProjection,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    UnresolvedAttributionEvidence,
    User,
    utcnow,
)
from backend.sync import (
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    PERSON_REL_AUTHOR,
    PERSON_REL_CATALOG_ACTOR,
    PERSON_REL_MAINTAINER,
    PERSON_REL_RECORD_OWNER,
)


@dataclass(frozen=True)
class MigrationResult:
    """Rows touched by one named migration."""

    name: str
    rows: int

    def log_line(self) -> str:
        """Return the operator-facing summary for one migration."""
        return f"  {self.name}: {self.rows} rows" if self.rows else f"  {self.name}: up to date"


def run_once() -> list[MigrationResult]:
    """Apply every pending data migration and report what each one touched."""
    return [
        MigrationResult("api_cache index columns", api_cache.backfill_index_columns()),
        MigrationResult("canonical search_text", canonical_tools.backfill_search_text()),
        MigrationResult(
            "catalog projections",
            catalog_projection.refresh_candidates(limit=catalog_projection.MAX_REFRESH_TOOLS)["refreshed"],
        ),
        MigrationResult("resolver identity cleanup", _clean_resolver_identity_claims()),
        MigrationResult("people immutable ids and account links", _backfill_people_identity()),
        MigrationResult("external account bindings", _backfill_account_bindings()),
        MigrationResult("unified relationship evidence", _backfill_relationship_evidence()),
        MigrationResult("display-only attribution evidence", _migrate_display_attributions()),
        MigrationResult("retired legacy people projections", _retire_legacy_people_tables()),
    ]


def _backfill_account_bindings() -> int:
    """Hydrate local users and materialize every safely provable account binding."""
    with db.session_scope() as s:
        result = identity_graph.synchronize(s)
        return int(result["toolhubBindings"]) + int(result["verified"]) + int(result["usersHydrated"])


def _clean_resolver_identity_claims() -> int:
    """Remove legacy claims that confused canonical authors with account users.

    The old resolver stored Toolforge proofs and display-name candidates under
    the canonical author name. That polluted the account's future search terms
    and expanded one false association into every tool by that author. Strong
    signed-toolinfo and official-write claims are intentionally left alone.
    """
    with db.session_scope() as s:
        rows = list(
            s.execute(
                select(ToolAuthorClaim).where(
                    or_(
                        ToolAuthorClaim.verification_method == AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                        ToolAuthorClaim.verification_method == AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
                    ),
                    func.lower(ToolAuthorClaim.author_name) != func.lower(ToolAuthorClaim.toolhub_username),
                )
            ).scalars()
        )
        affected_pairs = {(row.tool_name, row.toolhub_username) for row in rows}
        affected_tools = {tool_name for tool_name, _username in affected_pairs}
        for row in rows:
            s.delete(row)
        if not rows:
            return 0
        legacy_edge_count = 0
        if "tool_maintainer_edges" in inspect(db.engine()).get_table_names():
            statement = text(
                "DELETE FROM tool_maintainer_edges "
                "WHERE tool_name = :tool_name AND lower(toolhub_username) = :username "
                "AND source = :source AND method IN (:toolforge_method, :display_method)"
            )
            for tool_name, username in affected_pairs:
                legacy_edge_count += int(
                    s.execute(
                        statement,
                        {
                            "tool_name": tool_name,
                            "username": username.casefold(),
                            "source": maintainer_index.SOURCE_AUTHOR_CLAIM,
                            "toolforge_method": AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                            "display_method": AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
                        },
                    ).rowcount
                    or 0
                )
        maintainer_index.sync_author_claim_edges(s, tool_names=sorted(affected_tools))
        cache_count = 0
        if "user_tool_resolver_cache" in inspect(db.engine()).get_table_names():
            cache_count = int(s.execute(text("DELETE FROM user_tool_resolver_cache")).rowcount or 0)
        return len(rows) + legacy_edge_count + int(cache_count or 0)


def _backfill_people_identity() -> int:
    """Assign opaque ids, classify identifiers, and link OAuth accounts."""
    touched = 0
    now = utcnow()
    with db.session_scope() as s:
        for person in s.execute(select(Person).order_by(Person.id)).scalars():
            if not person.public_id:
                person.public_id = str(uuid4())
                touched += 1
        for identifier in s.execute(select(PersonIdentifier).order_by(PersonIdentifier.id)).scalars():
            namespace_map = {
                "toolhub": people_index.NS_TOOLHUB_USERNAME,
                "wiki": people_index.NS_WIKI_USERNAME,
            }
            namespace = namespace_map.get(identifier.namespace, identifier.namespace)
            kind = (
                people_index.IDENTIFIER_STABLE
                if namespace
                in {
                    people_index.NS_TOOLHUB_USER_ID,
                    people_index.NS_WIKIMEDIA_GLOBAL_USER_ID,
                    people_index.NS_TOOLFORGE_UID_NUMBER,
                }
                else people_index.IDENTIFIER_HANDLE
            )
            if (
                identifier.namespace != namespace
                or identifier.identifier_kind != kind
                or identifier.last_seen_at is None
            ):
                identifier.namespace = namespace
                identifier.identifier_kind = kind
                identifier.source = identifier.source or "legacy_people_projection"
                identifier.is_current = True
                identifier.last_seen_at = identifier.last_seen_at or identifier.created_at or now
                identifier.updated_at = now
                touched += 1
        users = list(s.execute(select(User).order_by(User.id)).scalars())
        for user in users:
            old_person_id = user.person_id
            people_index.link_user(s, user)
            touched += int(old_person_id != user.person_id)
        for account in s.execute(
            select(ToolhubAccountProjection).order_by(ToolhubAccountProjection.toolhub_user_id)
        ).scalars():
            existing = s.execute(
                select(PersonIdentifier.id).where(
                    PersonIdentifier.namespace == people_index.NS_TOOLHUB_USER_ID,
                    PersonIdentifier.normalized_value == account.toolhub_user_id.casefold(),
                    PersonIdentifier.is_current.is_(True),
                )
            ).scalar_one_or_none()
            person = people_index.ensure_official_account_person(
                s,
                toolhub_user_id=account.toolhub_user_id,
                username=account.username,
                wikimedia_global_user_id=account.wikimedia_global_user_id or "",
                checked_at=account.last_seen_at,
            )
            touched += int(existing is None and person is not None)
        touched += _backfill_account_owned_records(s, users)
    inspector = inspect(db.engine())

    def has_unique_column(table: str, column: str) -> bool:
        indexes = inspector.get_indexes(table)
        constraints = inspector.get_unique_constraints(table)
        return any(index.get("unique") and index.get("column_names") == [column] for index in indexes) or any(
            constraint.get("column_names") == [column] for constraint in constraints
        )

    with db.engine().begin() as connection:
        if not has_unique_column("people", "public_id"):
            connection.exec_driver_sql("CREATE UNIQUE INDEX ux_people_public_id ON people (public_id)")
        if not has_unique_column("users", "person_id"):
            connection.exec_driver_sql("CREATE UNIQUE INDEX ux_users_person_id ON users (person_id)")
    return touched


def _backfill_account_owned_records(s, users: list[User]) -> int:  # noqa: ANN001 - SQLAlchemy session
    """Move legacy claim/key ownership from mutable handles to account ids."""
    touched = 0
    users_by_id = {user.id: user for user in users}
    users_by_handle = {user.username.casefold(): user for user in users}
    for model in (ToolAuthorClaim, ToolAuthorKey):
        for row in s.execute(select(model).order_by(model.id)).scalars():
            owner = (
                users_by_id.get(row.user_id)
                if row.user_id is not None
                else users_by_handle.get(row.toolhub_username.casefold())
            )
            if owner is not None and (row.user_id != owner.id or row.toolhub_username != owner.username):
                row.user_id = owner.id
                row.toolhub_username = owner.username
                touched += 1
            if model is ToolAuthorClaim:
                changed = False
                expected_relationship = claim_relationship_for_method(row.verification_method)
                if row.requested_relationship != expected_relationship:
                    row.requested_relationship = expected_relationship
                    changed = True
                if row.created_at is None:
                    row.created_at = row.checked_at or utcnow()
                    changed = True
                if row.updated_at is None:
                    row.updated_at = row.checked_at or row.created_at
                    changed = True
                touched += int(changed)
    return touched


def _legacy_role(source: str, method: str) -> str:
    if source == maintainer_index.SOURCE_TOOLHUB_AUTHOR:
        return PERSON_REL_AUTHOR
    if source == maintainer_index.SOURCE_TOOLHUB_ACTOR:
        return PERSON_REL_CATALOG_ACTOR
    if method == "toolhub_write_access":
        return PERSON_REL_RECORD_OWNER
    if method == AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME:
        return PERSON_REL_AUTHOR
    return PERSON_REL_MAINTAINER


def _migrate_display_attributions() -> int:
    """Move legacy display-only person edges into non-identity attribution rows."""
    touched = 0
    now = utcnow()
    with db.session_scope() as s:
        identified_people = select(PersonIdentifier.person_id).where(PersonIdentifier.is_current.is_(True))
        evidence = list(
            s.execute(
                select(ToolRelationshipEvidence)
                .join(Person, Person.id == ToolRelationshipEvidence.person_id)
                .where(
                    ~Person.id.in_(identified_people),
                    Person.display_name != "",
                )
            ).scalars()
        )
        affected_person_ids = {row.person_id for row in evidence}
        people = {
            row.id: row for row in s.execute(select(Person).where(Person.id.in_(affected_person_ids or {-1}))).scalars()
        }
        for row in evidence:
            person = people[row.person_id]
            unresolved = s.execute(
                select(UnresolvedAttributionEvidence).where(
                    UnresolvedAttributionEvidence.tool_name == row.tool_name,
                    UnresolvedAttributionEvidence.normalized_label == person.display_name.casefold(),
                    UnresolvedAttributionEvidence.relationship_type == row.relationship_type,
                    UnresolvedAttributionEvidence.source == row.source,
                    UnresolvedAttributionEvidence.method == row.method,
                    UnresolvedAttributionEvidence.evidence_key == row.evidence_key,
                )
            ).scalar_one_or_none()
            if unresolved is None:
                unresolved = UnresolvedAttributionEvidence(
                    tool_name=row.tool_name,
                    normalized_label=person.display_name.casefold(),
                    relationship_type=row.relationship_type,
                    source=row.source,
                    method=row.method,
                    evidence_key=row.evidence_key,
                    first_seen_at=row.first_seen_at,
                    created_at=row.created_at,
                )
                s.add(unresolved)
            unresolved.observed_label = row.observed_name or person.display_name
            unresolved.verification_status = row.verification_status
            unresolved.confidence = row.confidence
            unresolved.toolhub_canonical = row.toolhub_canonical
            unresolved.evidence_url = row.evidence_url
            unresolved.evidence_payload = row.evidence_payload
            unresolved.checked_at = row.checked_at
            unresolved.expires_at = row.expires_at
            unresolved.withdrawn_at = row.withdrawn_at
            unresolved.last_error = row.last_error
            unresolved.updated_at = now
            s.delete(row)
            touched += 1
        if affected_person_ids:
            relationships = list(
                s.execute(
                    select(ToolPersonRelationship).where(ToolPersonRelationship.person_id.in_(affected_person_ids))
                ).scalars()
            )
            for relationship in relationships:
                s.delete(relationship)
                touched += 1
    return touched


def _backfill_relationship_evidence() -> int:
    """Backfill evidence from canonical Toolhub cache, claims, and old edges."""
    if "tool_maintainer_edges" not in inspect(db.engine()).get_table_names():
        return 0
    touched = 0
    with db.session_scope() as s:
        legacy = s.execute(text("SELECT * FROM tool_maintainer_edges ORDER BY tool_name, id")).mappings().all()
        grouped: dict[tuple[str, str], list[dict]] = {}
        for row in legacy:
            source = str(row.get("source") or "legacy_maintainer_edge")
            method = str(row.get("method") or "")
            grouped.setdefault((str(row["tool_name"]), source), []).append(
                {
                    "display_name": row.get("maintainer_display_name") or row.get("author_name") or "",
                    "toolhub_username": row.get("toolhub_username") or "",
                    "wiki_username": row.get("wiki_username") or "",
                    "relationship_type": _legacy_role(source, method),
                    "method": method,
                    "evidence_key": str(row.get("id") or ""),
                    "verification_status": row.get("verification_status") or "unverified",
                    "confidence": row.get("confidence") or 0,
                    "toolhub_canonical": source.startswith("toolhub_"),
                    "evidence_url": row.get("evidence_url"),
                    "evidence_payload": row.get("evidence_payload"),
                    "first_seen_at": row.get("first_seen_at"),
                    "checked_at": row.get("checked_at"),
                    "expires_at": row.get("expires_at"),
                    "last_error": row.get("last_error"),
                }
            )
        for (tool_name, source), observations in grouped.items():
            touched += len(people_index.replace_source_evidence(s, tool_name, source, observations))

        # Legacy rows are only a fallback. Rebuild authoritative local sources
        # afterward so stale legacy snapshots cannot replace current canonical
        # metadata or current claim state when they share a source name.
        canonical_rows = s.execute(text("SELECT tool_name, record FROM canonical_tool_cache")).mappings().all()
        for row in canonical_rows:
            record = row["record"]
            if isinstance(record, str):
                import json  # noqa: PLC0415 - only needed by the one-off migration

                record = json.loads(record)
            if isinstance(record, dict):
                touched += len(maintainer_index.replace_toolhub_metadata_edges(s, row["tool_name"], record))
        claim_tools = [row[0] for row in s.execute(select(ToolAuthorClaim.tool_name).distinct()).all()]
        touched += len(maintainer_index.sync_author_claim_edges(s, tool_names=claim_tools))
    return touched


def _retire_legacy_people_tables() -> int:
    """Drop obsolete projections after their evidence has been migrated."""
    legacy_tables = ("tool_person_relationships", "maintainer_activity_rollups", "tool_maintainer_edges")
    existing = set(inspect(db.engine()).get_table_names())
    retired = 0
    with db.engine().begin() as connection:
        for table in legacy_tables:
            if table in existing:
                connection.exec_driver_sql(f"DROP TABLE {table}")
                retired += 1
    return retired


def main(argv: list[str] | None = None) -> int:
    """Jobs/deploy entrypoint: prepare the schema, then migrate row data.

    `--require-configured-db` refuses to run against the local SQLite default.
    Toolforge only injects the tool's environment into webservice and job pods,
    not into a `become` shell, so a deploy step that simply reads TOOLHUB_DB_URL
    silently migrates a stale repo-local database and reports success. This
    makes that failure loud instead.
    """
    args = sys.argv[1:] if argv is None else argv
    configured = os.environ.get("TOOLHUB_DB_URL")
    if "--require-configured-db" in args and not configured:
        sys.stderr.write(
            "migrate: TOOLHUB_DB_URL is unset, so this would migrate the local SQLite default\n"
            "         instead of the configured database. Run it where the tool environment\n"
            "         exists (webservice/job pod), not from a plain `become` shell.\n"
        )
        return 1
    db.configure(configured or DEFAULT_DB_URL)
    db.init_schema()
    sys.stdout.write(f"migrate: dialect={db.engine().dialect.name} configured_db_url={'yes' if configured else 'no'}\n")
    for result in run_once():
        sys.stdout.write(f"{result.log_line()}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - deploy entrypoint, exercised via main() in tests
    raise SystemExit(main())
