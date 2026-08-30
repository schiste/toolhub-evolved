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
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, inspect, or_, select, text
from sqlalchemy.dialects.mysql import LONGTEXT, MEDIUMTEXT
from sqlalchemy.exc import OperationalError

from backend import (
    DEFAULT_DB_URL,
    api_cache,
    canonical_tools,
    catalog_facets,
    catalog_projection,
    db,
    digests,
    identity_graph,
    maintainer_index,
    people_index,
    source_attestations,
    userscript_sweep,
    userscripts,
    wiki_prefixes,
)
from backend.author_claims import claim_relationship_for_method
from backend.models import (
    ApiCacheMeta,
    CanonicalToolCache,
    CatalogFacetValue,
    DigestDelivery,
    DigestEdition,
    DigestSubscription,
    Person,
    PersonIdentifier,
    ToolAuthorClaim,
    ToolAuthorKey,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    UnresolvedAttributionEvidence,
    User,
    UserScriptDirectoryEntry,
    UserScriptImport,
    UserScriptPage,
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

# How many rows one backfill pass holds open at a time. Small enough that a
# deploy never waits on a single statement over a table with hundreds of
# thousands of rows, large enough that the walk is not dominated by round trips.
BACKFILL_CHUNK = 1000

# The unique key on `user_script_imports`, and the columns it now covers. Named
# here rather than read off the model because the migration has to name it in
# DDL, and a mismatch between the two would be a silent no-op every deploy.
WIDENED_IMPORT_KEY = "ux_user_script_imports_edge"
WIDENED_IMPORT_KEY_COLUMNS = (
    "wiki",
    "source_title",
    "verb",
    "target_wiki",
    "target_title",
    "target_url",
    "target_module",
)

# MariaDB's two ways of saying "another writer holds this row": 1205 is having
# waited out innodb_lock_wait_timeout, 1213 is having been picked as a deadlock
# victim. Both mean come back later. Every other OperationalError -- a dropped
# connection, a missing table -- means something a deploy should not survive.
LOCK_CONTENTION_ERRNOS = frozenset({1205, 1213})

# Identifier namespaces as they were first spelled, and the names they were
# given once the vocabulary distinguished a username from an account id.
IDENTIFIER_NAMESPACE_RENAMES = {
    "toolhub": people_index.NS_TOOLHUB_USERNAME,
    "wiki": people_index.NS_WIKI_USERNAME,
}


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
    return list(migrations())


def migrations() -> Iterator[MigrationResult]:
    """Yield each migration's result as that migration finishes.

    Separate from `run_once` so that a caller which prints can print as it goes:
    a migration that raises used to discard the record of every migration that
    had already run and committed, leaving a failed deploy with one line of
    output and no way to tell how far it got. `run_once` keeps the eager
    contract its name promises -- a generator nobody iterates runs nothing.
    """
    yield MigrationResult("text columns widened to MEDIUMTEXT", _widen_text_columns())
    yield MigrationResult("digest email subscriptions activated", _confirm_legacy_email_subscriptions())
    yield MigrationResult("out-of-scope digest editions retired", _retire_out_of_scope_digest_editions())
    yield MigrationResult("api_cache index columns", api_cache.backfill_index_columns())
    yield MigrationResult("catalog read indexes", _ensure_catalog_read_indexes())
    yield MigrationResult("canonical search_text", canonical_tools.backfill_search_text())
    yield MigrationResult("canonical card and sort projection", canonical_tools.backfill_read_projection())
    yield MigrationResult("canonical status flags", canonical_tools.backfill_status_flags())
    yield MigrationResult(
        "catalog projections",
        catalog_projection.refresh_candidates(limit=catalog_projection.MAX_REFRESH_TOOLS)["refreshed"],
    )
    yield MigrationResult("catalog facet aggregate", catalog_facets.rebuild_global_payload(force=True))
    yield MigrationResult("resolver identity cleanup", _clean_resolver_identity_claims())
    yield MigrationResult("legacy Toolforge proof retirement", _retire_legacy_toolforge_proofs())
    yield MigrationResult("source attestation rules marker", _initialize_source_attestation_rules())
    yield MigrationResult("Toolforge relationship input marker", _initialize_toolforge_relationship_marker())
    yield MigrationResult("relationship verification timestamps", _backfill_relationship_verified_at())
    yield MigrationResult("people immutable ids, slugs and account links", _backfill_people_identity())
    yield MigrationResult("unified relationship evidence", _backfill_relationship_evidence())
    yield MigrationResult("display-only attribution evidence", _migrate_display_attributions())
    yield MigrationResult("retired legacy people projections", _retire_legacy_people_tables())
    yield MigrationResult("user-script load key widened for modules", _widen_userscript_import_key())
    yield MigrationResult("user-script loads resolved to pages", _backfill_userscript_import_targets())
    yield MigrationResult("user-script body sketches", _backfill_userscript_sketches())
    yield MigrationResult("user-script analyses restated", _restate_swallowed_userscript_analyses())


def _ensure_catalog_read_indexes() -> int:
    """Create covering indexes and retire the single-column predecessors.

    Retirement is conditional on the replacement being present, not on the
    calendar: a run that fails to create the covering index must leave the
    narrow one it supersedes in place, or the failure turns a slow read into a
    whole-table scan.
    """
    engine = db.engine()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    targets = (
        (CanonicalToolCache.__table__, "ix_canonical_tool_cache_modified_at_sort"),
        (CatalogFacetValue.__table__, "ix_catalog_facet_values_field_value_tool"),
        (UserScriptImport.__table__, "ix_user_script_imports_target_page"),
        (UserScriptDirectoryEntry.__table__, "ix_user_script_directory_demand"),
        (UserScriptPage.__table__, "ix_user_script_pages_wiki_deleted"),
    )
    created = 0
    for table, name in targets:
        if table.name not in existing_tables:
            continue
        existing = {item["name"] for item in inspector.get_indexes(table.name)}
        if name in existing:
            continue
        index = next(candidate for candidate in table.indexes if candidate.name == name)
        index.create(bind=engine)
        created += 1
    # Each entry reads "once `covering` exists, these are dead weight on writes".
    # `ix_user_script_pages_wiki` is a strict prefix of the index that replaces
    # it, so dropping it costs no read and spares a half-million-row table one
    # index to maintain on every census write.
    superseded = (
        (
            CatalogFacetValue.__tablename__,
            "ix_catalog_facet_values_field_value_tool",
            {
                "ix_catalog_facet_values_tool_name",
                "ix_catalog_facet_values_field",
                "ix_catalog_facet_values_value",
            },
        ),
        (
            UserScriptPage.__tablename__,
            "ix_user_script_pages_wiki_deleted",
            {"ix_user_script_pages_wiki"},
        ),
    )
    for table_name, covering, obsolete in superseded:
        if table_name not in existing_tables:
            continue
        present = {item["name"] for item in inspect(engine).get_indexes(table_name)}
        if covering not in present:
            continue
        with engine.begin() as connection:
            for name in sorted(obsolete & present):
                if engine.dialect.name in {"mysql", "mariadb"}:
                    connection.exec_driver_sql(f"DROP INDEX {name} ON {table_name}")
                else:
                    connection.exec_driver_sql(f"DROP INDEX {name}")
                created += 1
    return created


def _widen_userscript_import_key() -> int:
    """Add `target_module` to the unique key on `user_script_imports`.

    A load that names a ResourceLoader module rather than a page leaves
    `target_wiki`, `target_title`, and `target_url` all blank, so under the old
    six-column key every module a page loads is the same row. `mw.loader.load`
    is usually called several times in a row, and the writer drops the loser of
    a duplicate rather than raising -- so without this, a page asking for three
    gadgets would be recorded as asking for one, silently.

    The old key is a prefix of the new one, so no existing row can become a
    duplicate and the create cannot fail on data. The drop is by name because
    the original constraint was declared unnamed and MariaDB named it after its
    first column; a fresh database already creates the named form, and there
    the search below finds nothing and this does nothing.
    """
    engine = db.engine()
    inspector = inspect(engine)
    table = UserScriptImport.__tablename__
    if table not in set(inspector.get_table_names()):
        return 0
    unique = {item["name"] for item in inspector.get_indexes(table) if item.get("unique")}
    if WIDENED_IMPORT_KEY in unique or not unique:
        return 0
    columns = ", ".join(f"`{name}`" for name in WIDENED_IMPORT_KEY_COLUMNS)
    with engine.begin() as connection:
        for name in sorted(unique):
            if engine.dialect.name in {"mysql", "mariadb"}:
                connection.exec_driver_sql(f"DROP INDEX `{name}` ON {table}")
            else:
                connection.exec_driver_sql(f"DROP INDEX {name}")
        # No USING HASH: this key is far past InnoDB's 3072-byte prefix limit,
        # and MariaDB converts a unique key that long to a hash index by itself
        # -- which is what the existing one already is.
        connection.exec_driver_sql(f"CREATE UNIQUE INDEX {WIDENED_IMPORT_KEY} ON {table} ({columns})")
    return 1


def _backfill_userscript_import_targets() -> int:
    """Point the loads stored before `target_page_id` existed at the pages they name.

    The sweep resolves what each run writes, in both directions, which closes
    every edge a live corpus creates. It cannot close the ones that were already
    there: a wiki whose sweep finished long ago rewrites almost nothing, so its
    loads would sit unresolved until the pages around them happened to change.

    A full scan of the null rows is the wrong shape for the sweep -- a load
    naming a wiki outside the census is null forever and would be re-read on
    every run -- but it is exactly the right shape once. This walks by id so the
    work is chunked rather than one statement over the whole table, and rows it
    cannot resolve are simply left alone, which is what makes it safe to run
    again on the next deploy.
    """
    engine = db.engine()
    if UserScriptImport.__tablename__ not in set(inspect(engine).get_table_names()):
        return 0
    resolved = 0
    after = 0
    while True:
        with db.session_scope() as session:
            rows = (
                session.query(UserScriptImport)
                .filter(UserScriptImport.target_page_id.is_(None), UserScriptImport.id > after)
                .order_by(UserScriptImport.id)
                .limit(BACKFILL_CHUNK)
                .all()
            )
            if not rows:
                return resolved
            after = rows[-1].id
            pages = userscript_sweep.page_ids(
                session,
                ((row.target_wiki, row.target_title) for row in rows if row.target_title),
            )
            for row in rows:
                page_id = pages.get((row.target_wiki, row.target_title))
                if page_id is not None:
                    row.target_page_id = page_id
                    resolved += 1


def _backfill_userscript_sketches() -> int:
    """Sample the bodies stored before sketches existed, so forks fold on the first run.

    Every one of these bodies is already in the database, so the alternative is
    not "wait a moment" -- it is re-reading a whole corpus from the wikis to
    learn something the rows already contain. Sketching only the pages the
    directory can use keeps it to the script-role rows rather than all 155,000.

    A page whose body was truncated at `MAX_STORED_BODY` on the way in gets a
    sketch of the part that was kept, which is what the next sweep will replace
    with the full one. The two differ only for pages over half a megabyte, and a
    sample of the first half megabyte of a script still resembles a fork of it.

    Chunked by id and restartable: rows already sketched are skipped by the
    filter, so a deploy interrupted halfway resumes rather than starting over.
    """
    engine = db.engine()
    if UserScriptPage.__tablename__ not in set(inspect(engine).get_table_names()):
        return 0
    written = 0
    after = 0
    while True:
        with db.session_scope() as session:
            rows = (
                session.query(UserScriptPage)
                .filter(
                    UserScriptPage.sketch == "",
                    UserScriptPage.role == userscripts.ROLE_SCRIPT,
                    UserScriptPage.id > after,
                )
                .order_by(UserScriptPage.id)
                .limit(BACKFILL_CHUNK)
                .all()
            )
            if not rows:
                return written
            after = rows[-1].id
            for row in rows:
                sketch = userscripts.sketch(row.body or "")
                if sketch:
                    row.sketch = sketch
                    written += 1


#: Bodies are read whole here, and a user-script body runs to `MAX_STORED_BODY`
#: (512 KiB). A thousand of those at once is half a gigabyte of strings held to
#: re-run a regex over them, in a migration that runs inline during a deploy; a
#: quarter of the usual chunk keeps the peak where the rest of the deploy can
#: live beside it. Nothing here is faster in bigger slices -- the walk is one
#: pass over the table either way.
RESTATE_CHUNK = BACKFILL_CHUNK // 4


def _restate_swallowed_userscript_analyses() -> int:
    """Re-analyse the stored bodies that a comment-stripping bug read as blank.

    Block comments were stripped before line comments, so a `/*` that was already
    inside a `//` line opened one anyway. A Tampermonkey header reading
    `// @match https://commons.wikimedia.org/*` -- a URL wildcard, not an opener
    -- blanked everything between it and the file's next `*/`, and the script
    behind it was stored as an empty page. `backend.userscripts` no longer reads
    it that way; this is what carries the correction to the pages already read,
    which the sweep never will because their revisions have not moved.

    Restricted to the rows that could have been truncated: a page already filed
    as a script was not, and a body with no `/*` in it has nothing to open a
    comment. The predicate is deliberately wider than the symptom -- a swallow
    that leaves one or two lines behind reads as a stub, and one that leaves a
    load behind reads as a shim -- so all three of the non-script roles are
    offered rather than just the empty one.

    Chunked by id and restartable: a row is examined by its position, not by
    whether it still needs work, so the walk ends whether or not any given row
    changed, and an interrupted deploy resumes from where the ids left off. Rows
    whose verdict does not move are left entirely alone, so running it again on
    the next deploy writes nothing.
    """
    engine = db.engine()
    if UserScriptPage.__tablename__ not in set(inspect(engine).get_table_names()):
        return 0
    restated = 0
    after = 0
    while True:
        with db.session_scope() as session:
            rows = (
                session.query(UserScriptPage)
                .filter(
                    UserScriptPage.role != userscripts.ROLE_SCRIPT,
                    UserScriptPage.deleted_at.is_(None),
                    UserScriptPage.body.contains("/*"),
                    UserScriptPage.id > after,
                )
                .order_by(UserScriptPage.id)
                .limit(RESTATE_CHUNK)
                .all()
            )
            if not rows:
                return restated
            after = rows[-1].id
            # Read, not refreshed: a load edge names its target wiki and reading
            # that target's title needs the target's own namespace names, but
            # this walk asks no wiki anything and must not start.
            prefixes = wiki_prefixes.resolver(session)
            restated += sum(1 for row in rows if userscript_sweep.restate_analysis(session, row, prefixes))


#: Columns declared `LARGE_TEXT` in models.py that shipped as plain TEXT, and so
#: exist in production with a 65,535-byte ceiling the model no longer respects.
#: Two entries from two separate incidents: a digest body and, after precomputed
#: snapshots moved into `api_cache_meta`, a ~300 KiB user-script roster written
#: into a column sized for a cursor. Both failed the same way -- error 1406 on
#: the write, in production only, because SQLite ignores declared widths and no
#: test against the test database can reach this.
WIDENED_TEXT_COLUMNS = (
    ("digest_editions", ("rendered_html", "rendered_text", "rendered_wikitext")),
    ("api_cache_meta", ("value",)),
)


def _widen_text_columns() -> int:
    """Carry existing MariaDB columns past TEXT's 64 KiB ceiling to MEDIUMTEXT.

    Nullability is read back from the column rather than assumed, because
    `MODIFY COLUMN` restates the whole definition: naming the wrong one here
    would silently rewrite a nullable column as NOT NULL, or drop a NOT NULL
    that something else depends on, while appearing to do only a widening.
    """
    engine = db.engine()
    if engine.dialect.name not in {"mysql", "mariadb"}:
        return 0
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    widened = 0
    for table, columns in WIDENED_TEXT_COLUMNS:
        if table not in tables:
            continue
        current = {column["name"]: column for column in inspector.get_columns(table)}
        pending = [
            name
            for name in columns
            if name in current and not isinstance(current[name]["type"], (MEDIUMTEXT, LONGTEXT))
        ]
        if not pending:
            continue
        with engine.begin() as connection:
            for name in pending:
                null = "NULL" if current[name].get("nullable") else "NOT NULL"
                connection.exec_driver_sql(f"ALTER TABLE {table} MODIFY COLUMN {name} MEDIUMTEXT {null}")
        widened += len(pending)
    return widened


def _initialize_source_attestation_rules() -> int:
    """Mark the already-audited projection for the first incremental release."""
    with db.session_scope() as s:
        row = s.get(ApiCacheMeta, source_attestations.RULES_META_KEY)
        if row is not None:
            return 0
        s.add(ApiCacheMeta(key=source_attestations.RULES_META_KEY, value=source_attestations.RULES_VERSION))
        return 1


def _initialize_toolforge_relationship_marker() -> int:
    """Avoid reprojecting unchanged LDAP memberships after this upgrade."""
    with db.session_scope() as s:
        return identity_graph.seed_relationship_fingerprint(s)


def _confirm_legacy_email_subscriptions() -> int:
    """Activate email subscriptions that were stranded awaiting a second opt-in.

    Email subscriptions no longer require a confirmation click, so rows created
    under the old flow would otherwise stay inactive forever: nothing sends the
    confirmation link any more. They were created by an authenticated request
    from the account they deliver to, which is the same consent every new
    subscription now records.

    Rows that were explicitly stopped are left alone. Those have confirmed_at
    set and active cleared, so they are not matched here; only never-confirmed
    rows are promoted, which keeps the migration idempotent and keeps an
    unsubscribe from being undone by a later deployment.

    confirmed_at is stamped now rather than copied from the row's creation
    time because delivery queues on `confirmed_at <= edition.period_end`. A
    backdated stamp would make an already-closed period eligible, and no
    subscription is supposed to receive an edition covering a period that ended
    before it existed. The stored last_error is cleared with it: it describes a
    confirmation email that is no longer part of the flow.
    """
    with db.session_scope() as s:
        rows = list(s.execute(select(DigestSubscription).where(DigestSubscription.confirmed_at.is_(None))).scalars())
        now = utcnow()
        for row in rows:
            row.confirmed_at = now
            row.active = True
            row.last_error = None
            row.updated_at = now
        return len(rows)


def _retire_out_of_scope_digest_editions() -> int:
    """Retire generated editions whose period closed before the backfill horizon.

    Generation used to have no horizon, so it worked forward from the catalog's
    first 2021 event and accumulated hundreds of validated editions that
    publication never reached. Those periods are now outside the horizon and will
    never be regenerated, but publish_pending() would still pick them up on the
    first pass that gets that far and post years of stale editions to Meta.

    Only `validated` rows are matched, so this is idempotent and cannot touch a
    published edition, a website-only example, or a genuine publication failure
    inside the horizon. Rows carrying any external publication state or delivery
    row are left alone and reported by the audit instead: something already
    happened off-site for them, so silently retiring them would hide it.
    """
    horizon = utcnow() - timedelta(days=digests.backfill_days())

    def absent(column: Any) -> Any:  # noqa: ANN401 - SQLAlchemy column expression
        # These columns default to "" rather than NULL, so emptiness is the marker.
        return or_(column.is_(None), column == "")

    with db.session_scope() as s:
        rows = list(
            s.execute(
                select(DigestEdition).where(
                    DigestEdition.status == "validated",
                    DigestEdition.period_end < horizon,
                    absent(DigestEdition.meta_page_title),
                    absent(DigestEdition.meta_page_url),
                    absent(DigestEdition.meta_revision_id),
                )
            ).scalars()
        )
        delivered = set(
            s.execute(
                select(DigestDelivery.edition_id).where(DigestDelivery.edition_id.in_([row.id for row in rows] or [-1]))
            ).scalars()
        )
        retired = [row for row in rows if row.id not in delivered]
        for row in retired:
            row.status = digests.OUT_OF_SCOPE_STATUS
            row.updated_at = utcnow()
        return len(retired)


def _backfill_relationship_verified_at() -> int:
    """Seed historical milestones without making deployment look like new verification."""
    with db.session_scope() as s:
        rows = list(
            s.execute(
                select(ToolPersonRelationship).where(
                    ToolPersonRelationship.verification_status == "verified",
                    ToolPersonRelationship.verified_at.is_(None),
                )
            ).scalars()
        )
        for row in rows:
            row.verified_at = row.created_at
        return len(rows)


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


def _retire_legacy_toolforge_proofs() -> int:
    """Withdraw HTML-label proofs that predate exact LDAP reconciliation."""
    now = utcnow()
    touched = 0
    affected_tools: set[str] = set()
    with db.session_scope() as s:
        claims = list(
            s.execute(
                select(ToolAuthorClaim).where(
                    ToolAuthorClaim.verification_method == AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                    ToolAuthorClaim.revoked_at.is_(None),
                    ToolAuthorClaim.verification_status.in_(("verified", "stale")),
                )
            ).scalars()
        )
        for claim in claims:
            if maintainer_index.toolforge_claim_has_ldap_proof(claim):
                continue
            claim.verification_status = "unverified"
            claim.expires_at = None
            claim.last_error = "Legacy Toolsadmin label was not exact LDAP membership proof"
            claim.updated_at = now
            affected_tools.add(claim.tool_name)
            touched += 1

        toolsadmin_rows = list(
            s.execute(
                select(ToolRelationshipEvidence).where(
                    ToolRelationshipEvidence.source == maintainer_index.SOURCE_TOOLFORGE_TOOLSADMIN,
                    ToolRelationshipEvidence.withdrawn_at.is_(None),
                )
            ).scalars()
        )
        for row in toolsadmin_rows:
            payload = row.evidence_payload if isinstance(row.evidence_payload, dict) else {}
            exact_membership = bool(
                row.method == AUTHOR_CLAIM_TOOLFORGE_MAINTAINER
                and payload.get("membershipValidatedBy") == "toolforge_ldap"
                and payload.get("toolforgeUidNumber")
            )
            if exact_membership:
                continue
            row.withdrawn_at = now
            row.updated_at = now
            affected_tools.add(row.tool_name)
            touched += 1

        if affected_tools:
            maintainer_index.sync_author_claim_edges(s, tool_names=sorted(affected_tools))
            for tool_name in sorted(affected_tools):
                people_index.resolve_tool_relationships(s, tool_name)
    return touched


def _is_lock_contention(error: OperationalError) -> bool:
    """Report whether the database refused because another writer held the row."""
    args = getattr(getattr(error, "orig", None), "args", ())
    return bool(args) and args[0] in LOCK_CONTENTION_ERRNOS


def _restate_identifiers(rows: Iterable[PersonIdentifier], now: datetime) -> int:
    """Move one chunk of identifier rows onto the current namespace and kind."""
    touched = 0
    for identifier in rows:
        namespace = IDENTIFIER_NAMESPACE_RENAMES.get(identifier.namespace, identifier.namespace)
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
        if identifier.namespace != namespace or identifier.identifier_kind != kind or identifier.last_seen_at is None:
            identifier.namespace = namespace
            identifier.identifier_kind = kind
            identifier.source = identifier.source or "legacy_people_projection"
            identifier.is_current = True
            identifier.last_seen_at = identifier.last_seen_at or identifier.created_at or now
            identifier.updated_at = now
            touched += 1
    return touched


def _normalize_identifier_vocabulary() -> tuple[int, int]:
    """Restate legacy identifier rows, chunk by chunk. Returns (changed, deferred).

    `person_identifiers` is written every minute by the reconcile queue and for
    minutes at a time by `people-identity-reconcile`, so a pass over it will meet
    rows another writer is holding. As one transaction over the whole table this
    could not converge: waiting out `innodb_lock_wait_timeout` on a single row
    rolled back every row already restated, so the same work was still pending on
    the next deploy, and the deploy itself died here -- before `jobs load` and
    before the release was recorded, leaving the host pulled but not deployed.

    A chunk that cannot be locked is one some hourly job is writing right now.
    Leaving it for the next deploy is the whole point; grinding through a retry
    would be arguing with the writer that is winning.
    """
    changed = 0
    deferred = 0
    after = 0
    now = utcnow()
    while True:
        with db.session_scope() as s:
            ids = list(
                s.execute(
                    select(PersonIdentifier.id)
                    .where(PersonIdentifier.id > after)
                    .order_by(PersonIdentifier.id)
                    .limit(BACKFILL_CHUNK)
                ).scalars()
            )
        if not ids:
            return (changed, deferred)
        # The window is fixed, and the cursor advanced past it, before anything
        # can raise. A chunk this deploy cannot have is then skipped rather than
        # retried forever, which is what deferring inside the read would do.
        window, after = (after, ids[-1]), ids[-1]
        restated = 0
        try:
            with db.session_scope() as s:
                rows = s.execute(
                    select(PersonIdentifier).where(
                        PersonIdentifier.id > window[0],
                        PersonIdentifier.id <= window[1],
                    )
                ).scalars()
                restated = _restate_identifiers(rows, now)
        except OperationalError as error:
            if not _is_lock_contention(error):
                raise
            deferred += len(ids)
            continue
        # Counted only once the commit has survived: session_scope flushes on
        # exit, so the refusal usually arrives after the rows were restated in
        # memory, and those rows did not change.
        changed += restated


def _link_accounts_to_people() -> tuple[int, int]:
    """Point each OAuth account at its person, chunk by chunk. Returns (linked, deferred).

    This pass writes `person_identifiers` too: `link_user` refreshes every
    identifier it resolves, so it meets the same minute-by-minute writers that
    `_normalize_identifier_vocabulary` was taught to defer to. It was refused in
    a place nothing was catching, though. `ensure_person` upserts one namespace
    after another, and the SELECT opening each upsert flushes the rows the
    previous one dirtied -- so the refusal surfaces out of a read, several
    frames from the assignment that earned it, and the traceback says
    "Query-invoked autoflush" rather than naming an UPDATE. It is still errno
    1205, and one held row still aborted the whole deploy after `git pull` had
    already fast-forwarded the host.

    Chunking is what makes deferring cheap: a chunk another writer holds is
    dropped, and the accounts before and after it still link on this deploy.
    """
    linked = 0
    deferred = 0
    after = 0
    while True:
        with db.session_scope() as s:
            ids = list(
                s.execute(select(User.id).where(User.id > after).order_by(User.id).limit(BACKFILL_CHUNK)).scalars()
            )
        if not ids:
            return (linked, deferred)
        # Window fixed and cursor advanced before anything can raise, so a chunk
        # this deploy cannot have is skipped rather than retried forever.
        window, after = (after, ids[-1]), ids[-1]
        relinked = 0
        try:
            with db.session_scope() as s:
                current_ids = {
                    (row.namespace, row.normalized_value): row.person_id
                    for row in s.execute(
                        select(PersonIdentifier).where(PersonIdentifier.is_current.is_(True))
                    ).scalars()
                }
                users = s.execute(
                    select(User).where(User.id > window[0], User.id <= window[1]).order_by(User.id)
                ).scalars()
                for user in users:
                    toolhub_owner = current_ids.get((people_index.NS_TOOLHUB_USER_ID, user.wm_sub.casefold()))
                    wikimedia_owner = current_ids.get(
                        (people_index.NS_WIKIMEDIA_GLOBAL_USER_ID, (user.wikimedia_global_user_id or "").casefold())
                    )
                    if (
                        toolhub_owner is not None
                        and user.person_id == toolhub_owner
                        and (not user.wikimedia_global_user_id or user.person_id == wikimedia_owner)
                    ):
                        # Already pointed at the right person by both stable
                        # identifiers. Skipping is not only cheaper: linking
                        # would restamp identifier rows that need no change,
                        # which is exactly the contention this defers around.
                        #
                        # `toolhub_owner is not None` is what makes the test a
                        # match rather than an absence. An account with no
                        # identifier row has no owner to compare against, and
                        # its `person_id` is NULL for the same reason -- so
                        # without this the two NULLs agreed and the row the
                        # backfill exists to repair was the one row it always
                        # skipped.
                        continue
                    old_person_id = user.person_id
                    people_index.link_user(s, user)
                    relinked += int(old_person_id != user.person_id)
        except OperationalError as error:
            if not _is_lock_contention(error):
                raise
            deferred += len(ids)
            continue
        # Counted only once the commit has survived, for the same reason the
        # identifier pass counts late: the refusal usually arrives after the
        # session has already moved the rows in memory.
        linked += relinked


def _backfill_people_identity() -> int:
    """Assign opaque IDs and slugs, classify identifiers, and link accounts."""
    touched = 0
    with db.session_scope() as s:
        for person in s.execute(select(Person).order_by(Person.id)).scalars():
            if not person.public_id:
                person.public_id = str(uuid4())
                touched += 1
        s.flush()
        touched += _backfill_person_slugs(s)
    restated, identifiers_deferred = _normalize_identifier_vocabulary()
    touched += restated
    linked, links_deferred = _link_accounts_to_people()
    touched += linked
    restated_records, records_deferred = _relink_account_owned_records()
    touched += restated_records
    for deferred, subject in (
        (identifiers_deferred, "identifier rows"),
        (links_deferred, "account links"),
        (records_deferred, "claim and key owner rows"),
    ):
        if deferred:
            # Loud, because the alternative reading of a quiet deploy is that
            # there was nothing to do. Convergence is left to the next one.
            sys.stderr.write(
                f"migrate: left {deferred} {subject} to the next deploy; another writer held them\n",
            )
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
    _ensure_person_slug_index()
    return touched


def _backfill_person_slugs(s) -> int:  # noqa: ANN001 - SQLAlchemy session
    """Fill canonical slugs once without rewriting already-published URLs."""
    used = {
        str(slug).casefold()
        for (slug,) in s.execute(select(Person.public_slug).where(Person.public_slug.is_not(None))).all()
        if str(slug or "").strip()
    }
    touched = 0
    for person in s.execute(select(Person).where(Person.public_slug.is_(None)).order_by(Person.id)).scalars():
        candidate = next(
            (
                value
                for value in people_index.person_slug_candidates(person.display_name, person.public_id)
                if value.casefold() not in used
            ),
            None,
        )
        if candidate is None:
            message = f"could not allocate unique public slug for person {person.public_id}"
            raise RuntimeError(message)
        person.public_slug = candidate
        used.add(candidate.casefold())
        touched += 1
    return touched


def _ensure_person_slug_index() -> None:
    """Add the production uniqueness guard after the row backfill completes."""
    inspector = inspect(db.engine())
    indexes = inspector.get_indexes("people")
    constraints = inspector.get_unique_constraints("people")
    unique = any(index.get("unique") and index.get("column_names") == ["public_slug"] for index in indexes) or any(
        constraint.get("column_names") == ["public_slug"] for constraint in constraints
    )
    if not unique:
        with db.engine().begin() as connection:
            connection.exec_driver_sql("CREATE UNIQUE INDEX ux_people_public_slug ON people (public_slug)")


def _restate_account_owned_record(row, owners_by_id: dict, owners_by_handle: dict) -> int:  # noqa: ANN001 - ORM row
    """Point one claim or key row at its account, and fill a claim's derived columns."""
    owner = (
        owners_by_id.get(row.user_id)
        if row.user_id is not None
        else owners_by_handle.get(row.toolhub_username.casefold())
    )
    touched = 0
    if owner is not None and (row.user_id, row.toolhub_username) != owner:
        row.user_id, row.toolhub_username = owner
        touched += 1
    if isinstance(row, ToolAuthorClaim):
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


def _relink_account_owned_records() -> tuple[int, int]:
    """Move legacy claim/key ownership onto account ids, chunk by chunk. Returns (touched, deferred).

    The last pass in this migration still holding every row it touches in one
    transaction. It writes `tool_author_claims.user_id` and `toolhub_username`,
    and `maintainer-backfill` writes those same two columns every hour at :13
    from `sync_author_claim_edges`, so a deploy that lands in that minute meets
    a held row and errno 1205 aborts the whole migration -- after `git pull`
    has already fast-forwarded the host, which is the failure mode the two
    passes above were chunked to stop.

    Accounts are read once into plain tuples rather than carried as ORM
    instances: the rows are rewritten one chunk per session, and a `User`
    loaded in an earlier session would be detached by the time a later chunk
    read it. Only the id and username are ever used.
    """
    with db.session_scope() as s:
        accounts = [(user.id, user.username) for user in s.execute(select(User).order_by(User.id)).scalars()]
    owners_by_id = {user_id: (user_id, username) for user_id, username in accounts}
    owners_by_handle = {username.casefold(): (user_id, username) for user_id, username in accounts}

    touched = 0
    deferred = 0
    for model in (ToolAuthorClaim, ToolAuthorKey):
        after = 0
        while True:
            with db.session_scope() as s:
                ids = list(
                    s.execute(
                        select(model.id).where(model.id > after).order_by(model.id).limit(BACKFILL_CHUNK)
                    ).scalars()
                )
            if not ids:
                break
            # Window fixed and cursor advanced before anything can raise, so a
            # chunk this deploy cannot have is skipped rather than retried
            # forever -- the rule `_link_accounts_to_people` follows.
            window, after = (after, ids[-1]), ids[-1]
            restated = 0
            try:
                with db.session_scope() as s:
                    rows = s.execute(
                        select(model).where(model.id > window[0], model.id <= window[1]).order_by(model.id)
                    ).scalars()
                    for row in rows:
                        restated += _restate_account_owned_record(row, owners_by_id, owners_by_handle)
            except OperationalError as error:
                if not _is_lock_contention(error):
                    raise
                deferred += len(ids)
                continue
            # Counted only once the commit has survived: the refusal usually
            # arrives after the session has already moved the rows in memory.
            touched += restated
    return (touched, deferred)


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
    for result in migrations():
        sys.stdout.write(f"{result.log_line()}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - deploy entrypoint, exercised via main() in tests
    raise SystemExit(main())
