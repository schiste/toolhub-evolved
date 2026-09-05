# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the one-off data migration entrypoint (proxy/migrate.py).

These cover the two properties that make it safe to run from a deploy: it is
idempotent, and it refuses to silently migrate the wrong database.
"""

import sys
from datetime import timedelta
from unittest import mock
from pathlib import Path

import pytest
from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, inspect, select
from sqlalchemy.dialects import mysql
from sqlalchemy.dialects.mysql import MEDIUMTEXT, mariadb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import migrate  # noqa: E402
from backend import api_cache, canonical_tools, db, digests, maintainer_index, userscripts  # noqa: E402
from backend.models import (  # noqa: E402
    ApiCache,
    ApiCacheMeta,
    Base,
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
    UserScriptImport,
    UserScriptPage,
    utcnow,
)
from backend import sync  # noqa: E402


@pytest.fixture
def configured_db(tmp_path):
    db.configure(f"sqlite:///{tmp_path / 'migrate.sqlite3'}")
    db.init_schema()
    return None


def test_migrate_backfills_both_caches_and_is_idempotent(configured_db, capsys):
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/tools/legacy/",
        api_cache.CacheableResponse(200, "application/json", b"{}"),
    )
    canonical_tools.upsert_records(
        [{"name": "legacy-tool", "title": "Legacy", "description": "cached earlier"}],
        source_url="https://toolhub.wikimedia.org/api/search/tools/",
    )
    # Simulate rows written before either column existed.
    with db.session_scope() as s:
        s.query(ApiCache).update({ApiCache.path: "", ApiCache.collection: "", ApiCache.detail_key: ""})
        s.execute(db.text("UPDATE canonical_tool_cache SET search_text = ''"))
        s.execute(db.text("UPDATE canonical_tool_cache SET card_record = NULL, modified_at_sort = NULL"))

    # Asserted per migration rather than as a whole set, so adding a migration
    # extends this rather than breaking it.
    first = {result.name: result.rows for result in migrate.run_once()}
    assert first["text columns widened to MEDIUMTEXT"] == 0
    assert first["api_cache index columns"] == 1
    assert first["canonical search_text"] == 1
    # search_text repair reassigns the same record and therefore fills every
    # derived read column in one pass.
    assert first["canonical card and sort projection"] == 0

    # Running again is a no-op, so a deploy can re-run it without thinking.
    second = {result.name: result.rows for result in migrate.run_once()}
    assert second["api_cache index columns"] == 0
    assert second["canonical search_text"] == 0
    assert second["canonical card and sort projection"] == 0
    assert [r for r in canonical_tools.search("cached earlier")][0]["toolName"] == "legacy-tool"


def test_catalog_read_projection_backfill_repairs_rows_with_current_search_text(configured_db):
    canonical_tools.upsert_records(
        [{"name": "projected", "title": "Projected", "modified_date": "2026-08-15T12:00:00Z"}],
        source_url="https://toolhub.wikimedia.org/api/search/tools/",
    )
    with db.session_scope() as session:
        session.execute(
            db.text(
                "UPDATE canonical_tool_cache SET card_record = NULL, modified_at_sort = NULL "
                "WHERE tool_name = 'projected'"
            )
        )

    assert canonical_tools.backfill_read_projection() == 1
    with db.session_scope() as session:
        row = (
            session.execute(
                db.text("SELECT card_record, modified_at_sort FROM canonical_tool_cache WHERE tool_name = 'projected'")
            )
            .mappings()
            .one()
        )
    assert row["card_record"] is not None
    assert row["modified_at_sort"] is not None
    assert canonical_tools.backfill_read_projection() == 0


def test_catalog_index_migration_retires_redundant_single_column_indexes(configured_db):
    with db.engine().begin() as connection:
        connection.exec_driver_sql("CREATE INDEX ix_catalog_facet_values_tool_name ON catalog_facet_values (tool_name)")
        connection.exec_driver_sql("CREATE INDEX ix_catalog_facet_values_field ON catalog_facet_values (field)")
        connection.exec_driver_sql("CREATE INDEX ix_catalog_facet_values_value ON catalog_facet_values (value)")

    assert migrate._ensure_catalog_read_indexes() == 3
    names = {item["name"] for item in db.inspect(db.engine()).get_indexes("catalog_facet_values")}
    assert "ix_catalog_facet_values_field_value_tool" in names
    assert not names & {
        "ix_catalog_facet_values_tool_name",
        "ix_catalog_facet_values_field",
        "ix_catalog_facet_values_value",
    }
    assert migrate._ensure_catalog_read_indexes() == 0


def test_the_cross_wiki_directory_index_reaches_a_table_that_predates_it(configured_db):
    # `create_all` skips a table that already exists, indexes included, so an
    # index added to a shipped model only ever reaches production through this
    # step. The directory table has been in production for weeks; dropping the
    # index here is what a production database looks like before the migration.
    with db.engine().begin() as connection:
        connection.exec_driver_sql("DROP INDEX ix_user_script_directory_demand")

    assert migrate._ensure_catalog_read_indexes() == 1
    names = {item["name"] for item in db.inspect(db.engine()).get_indexes("user_script_directory")}
    assert "ix_user_script_directory_demand" in names
    assert migrate._ensure_catalog_read_indexes() == 0


def test_the_script_page_count_index_reaches_a_table_that_predates_it(configured_db):
    """Counting a wiki's live pages must not have to open the rows.

    `deleted_at` sat in no index, so MariaDB evaluated `WHERE deleted_at IS
    NULL` by fetching all 478,189 rows of a 1.8 GB table -- 25 seconds, to
    exclude the ten rows that are deleted. That count runs once per wiki in the
    roster build and once more on every per-wiki read.
    """
    with db.engine().begin() as connection:
        connection.exec_driver_sql("DROP INDEX ix_user_script_pages_wiki_deleted")
        connection.exec_driver_sql("CREATE INDEX ix_user_script_pages_wiki ON user_script_pages (wiki)")

    # One created, one retired.
    assert migrate._ensure_catalog_read_indexes() == 2
    names = {item["name"] for item in db.inspect(db.engine()).get_indexes("user_script_pages")}
    assert "ix_user_script_pages_wiki_deleted" in names
    # A strict prefix of the index that replaced it: keeping both would cost the
    # census a second index to maintain on every write and buy no read.
    assert "ix_user_script_pages_wiki" not in names
    assert migrate._ensure_catalog_read_indexes() == 0


def test_a_covering_index_that_did_not_land_leaves_its_predecessor_in_place(configured_db):
    """Retirement is conditional on the replacement existing, not on the attempt.

    Dropping the narrow index on a run where the covering one did not appear
    would turn a slow per-wiki count into an unindexed table scan -- a worse
    database than the one the migration started with, produced by the step
    meant to improve it.
    """
    with db.engine().begin() as connection:
        connection.exec_driver_sql("DROP INDEX ix_user_script_pages_wiki_deleted")
        connection.exec_driver_sql("CREATE INDEX ix_user_script_pages_wiki ON user_script_pages (wiki)")

    with mock.patch.object(Index, "create", lambda *_args, **_kwargs: None):
        migrate._ensure_catalog_read_indexes()

    names = {item["name"] for item in db.inspect(db.engine()).get_indexes("user_script_pages")}
    assert "ix_user_script_pages_wiki_deleted" not in names
    assert "ix_user_script_pages_wiki" in names


# What one column of each type costs in a MariaDB key, under the utf8mb4
# charset production uses -- four bytes per character, not one.
_KEY_BYTES = {
    String: lambda column: (column.type.length or 0) * 4,
    Integer: lambda _column: 4,
    DateTime: lambda _column: 5,
    Boolean: lambda _column: 1,
}
# MariaDB's limit for an InnoDB key under the DYNAMIC row format.
_MAX_KEY_BYTES = 3072
# Indexes that are over the limit and already deployed, so failing on them here
# would describe nothing anyone can act on. Both are single-column: MariaDB cut
# the first down to a 768-character prefix rather than refusing it, and the
# second predates the ALTER that widened its column, which MariaDB does not
# recheck. Neither escape is available to a new multi-column index -- that one
# is refused outright, which is how this test came to exist.
_GRANDFATHERED = {
    "ix_toolhub_account_projection_groups_search",
    "ix_toolinfo_sources_url",
}


def _key_bytes(column):
    for kind, cost in _KEY_BYTES.items():
        if isinstance(column.type, kind):
            return cost(column)
    # A type nobody has indexed before: fail rather than wave it through, since
    # the whole point of this test is that it is the only place the limit is checked.
    raise AssertionError(f"no key size known for {column.table.name}.{column.name} ({column.type!r})")


def test_no_index_declares_a_key_longer_than_mariadb_accepts():
    """SQLite has no key-length limit, so no other test in this suite can catch this.

    `create_all` and `_ensure_catalog_read_indexes` both run against MariaDB in
    production and against SQLite here. An index that is fine locally and 3136
    bytes on Toolforge fails at deploy time, inside migrate, which aborts the
    deploy and leaves the old code serving -- which is exactly what
    ix_user_script_directory_demand did when it still carried (wiki, title).

    Only `Index` declarations are checked, not unique constraints. Production
    holds several of those that are over the limit today -- ux_user_script_imports_edge
    is 15284 bytes -- because they were created while their columns were narrower
    and MariaDB does not recheck a key when a later ALTER widens a column. They
    survive because they already exist, so asserting on them here would fail on
    the deployed schema rather than describe it.
    """
    oversized = []
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            size = sum(_key_bytes(column) for column in index.columns)
            if size > _MAX_KEY_BYTES and index.name not in _GRANDFATHERED:
                oversized.append(f"{index.name}: {size} bytes")
    assert oversized == []


def test_digest_render_columns_compile_to_mysql_mediumtext(configured_db):
    for name in ("rendered_html", "rendered_wikitext", "rendered_text"):
        column = DigestEdition.__table__.columns[name]
        assert column.type.compile(dialect=mysql.dialect()) == "MEDIUMTEXT"
        assert column.type.compile(dialect=mariadb.MariaDBDialect()) == "MEDIUMTEXT"
        assert column.type.compile(dialect=db.engine().dialect) == "TEXT"


def test_migrate_activates_stranded_email_subscriptions_without_reviving_stopped_ones(configured_db):
    """Nothing sends confirmation links any more, so unconfirmed rows must not stay stuck."""
    published_at = utcnow() - timedelta(days=2)
    with db.session_scope() as s:
        user = User(wm_sub="42", username="Subscriber", wikimedia_global_user_id="9")
        s.add(user)
        s.flush()
        s.add_all(
            [
                DigestSubscription(
                    user_id=user.id,
                    channel="email",
                    cadence="daily",
                    wiki_domain="meta.wikimedia.org",
                    wiki_username="Subscriber",
                    last_error="the confirmation email could not be sent",
                ),
                DigestSubscription(
                    user_id=user.id,
                    channel="email",
                    cadence="weekly",
                    wiki_domain="meta.wikimedia.org",
                    wiki_username="Subscriber",
                    confirmed_at=published_at,
                    active=False,
                ),
            ]
        )

    first = {result.name: result.rows for result in migrate.run_once()}
    second = {result.name: result.rows for result in migrate.run_once()}

    assert first["digest email subscriptions activated"] == 1
    assert second["digest email subscriptions activated"] == 0
    with db.session_scope() as s:
        rows = {row.cadence: row for row in s.query(DigestSubscription).all()}
        assert rows["daily"].active is True
        assert rows["daily"].last_error is None
        # Stamped now, not backdated: delivery gates on confirmed_at <= period_end,
        # so a backdated stamp would make an already-closed period eligible.
        assert rows["daily"].confirmed_at > published_at
        # An explicitly stopped subscription stays stopped across deployments.
        assert rows["weekly"].active is False


def _edition(key: str, period_end, status: str, **extra) -> DigestEdition:
    return DigestEdition(
        cadence="daily",
        edition_key=key,
        period_start=period_end - timedelta(days=1),
        period_end=period_end,
        status=status,
        title=f"Toolhub Daily — {key}",
        **extra,
    )


def test_migrate_retires_only_unpublishable_out_of_scope_editions(configured_db):
    """Generation once had no horizon, so validated editions from years ago must not reach Meta."""
    now = utcnow()
    with db.session_scope() as s:
        s.add_all(
            [
                _edition("2021-11-08", now - timedelta(days=1700), "validated"),
                _edition("2026-08-14", now - timedelta(days=2), "validated"),
                _edition("2022-03-01", now - timedelta(days=1500), "published", meta_revision_id="7"),
                _edition("2022-03-02", now - timedelta(days=1499), digests.WEBSITE_ONLY_STATUS),
                # Already has an off-site page: retiring it silently would hide that.
                _edition("2022-03-03", now - timedelta(days=1498), "validated", meta_page_title="Toolhub/X"),
            ]
        )

    first = {result.name: result.rows for result in migrate.run_once()}
    second = {result.name: result.rows for result in migrate.run_once()}

    assert first["out-of-scope digest editions retired"] == 1
    assert second["out-of-scope digest editions retired"] == 0
    with db.session_scope() as s:
        rows = {row.edition_key: row.status for row in s.query(DigestEdition).all()}
        assert rows["2021-11-08"] == digests.OUT_OF_SCOPE_STATUS
        # Inside the horizon, so still a real publication candidate.
        assert rows["2026-08-14"] == "validated"
        assert rows["2022-03-01"] == "published"
        assert rows["2022-03-02"] == digests.WEBSITE_ONLY_STATUS
        assert rows["2022-03-03"] == "validated"


def test_retired_editions_are_never_republished_or_shown(configured_db):
    """A retired edition must stay out of publish_pending and out of the website."""
    with db.session_scope() as s:
        s.add(_edition("2021-11-09", utcnow() - timedelta(days=1699), "validated"))
    migrate.run_once()

    with db.session_scope() as s:
        pending = s.execute(
            select(DigestEdition.id).where(DigestEdition.status.in_(("validated", "publication_failed")))
        ).scalars()
        assert list(pending) == []
        assert digests.OUT_OF_SCOPE_STATUS not in digests.WEBSITE_VISIBLE_STATUSES


def test_migrate_seeds_historical_relationship_verification_time(configured_db):
    with db.session_scope() as s:
        person = Person(canonical_key="stable:1", display_name="Ada", identity_quality="stable")
        s.add(person)
        s.flush()
        relationship = ToolPersonRelationship(
            tool_name="historical",
            person_id=person.id,
            relationship_type="maintainer",
            verification_status="verified",
        )
        s.add(relationship)
        s.flush()
        created_at = relationship.created_at

    first = {result.name: result.rows for result in migrate.run_once()}
    second = {result.name: result.rows for result in migrate.run_once()}

    assert first["relationship verification timestamps"] == 1
    assert second["relationship verification timestamps"] == 0
    with db.session_scope() as s:
        assert s.query(ToolPersonRelationship).one().verified_at == created_at


def test_migrate_backfills_stable_person_slugs_idempotently(configured_db):
    with db.session_scope() as s:
        s.add_all(
            [
                Person(
                    canonical_key="stable:slug",
                    public_id="31e9abd5-fb61-42d8-96e4-ccbe3bb54ced",
                    public_slug=None,
                    display_name="Christophe",
                    identity_quality="stable",
                ),
                Person(
                    canonical_key="stable:slug-collision",
                    public_id="11111111-1111-1111-1111-11113bb54ced",
                    public_slug=None,
                    display_name="Christophe",
                    identity_quality="stable",
                ),
            ]
        )

    assert migrate._backfill_people_identity() == 2
    assert migrate._backfill_people_identity() == 0
    with db.session_scope() as s:
        slugs = {
            person.canonical_key: person.public_slug for person in s.query(Person).order_by(Person.canonical_key).all()
        }
        assert slugs == {
            "stable:slug": "christophe-4ced",
            "stable:slug-collision": "christophe-b54ced",
        }


def test_a_snapshot_column_is_declared_past_the_text_ceiling():
    """The only place MariaDB's 64 KiB limit can be caught before production.

    The test database is SQLite, which ignores declared widths entirely: a
    value that MariaDB rejects with error 1406 is stored without complaint by
    every other test in this suite. So no behavioural test can reach this, and
    the compiled DDL is what has to be asserted instead.

    `api_cache_meta.value` is named because it is the one that got this wrong:
    a column sized for a cursor, holding a ~300 KiB precomputed roster.
    """
    ddl = ApiCacheMeta.__table__.c.value.type.compile(mysql.dialect())
    assert ddl == "MEDIUMTEXT"


def test_the_widening_list_names_only_columns_the_models_still_declare_wide():
    """A column drops off this list by being narrowed, which must not pass quietly.

    The list is deliberately not every wide column -- one born MEDIUMTEXT never
    needed carrying across -- so this is a subset check, not equality.
    """
    wide = {
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.type.compile(mysql.dialect()) in {"MEDIUMTEXT", "LONGTEXT"}
    }
    listed = {(table, column) for table, columns in migrate.WIDENED_TEXT_COLUMNS for column in columns}
    assert listed <= wide


def test_widening_reaches_every_shipped_text_column_once(monkeypatch):
    """Both tables get MODIFY-ed, and a second run does nothing.

    Asserting the exact DDL rather than a count, because `MODIFY COLUMN`
    restates a column's whole definition: a run that widened the type and
    dropped a NOT NULL would satisfy any count-based assertion while quietly
    changing what the column accepts.
    """
    statements = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def exec_driver_sql(self, statement):
            statements.append(statement)

    class Engine:
        dialect = type("Dialect", (), {"name": "mysql"})()

        def begin(self):
            return Connection()

    class Inspector:
        def __init__(self, widened=False):
            self.widened = widened

        def get_table_names(self):
            return ["digest_editions", "api_cache_meta", "unrelated"]

        def get_columns(self, table):
            column_type = MEDIUMTEXT() if self.widened else Text()
            names = ("value",) if table == "api_cache_meta" else ("rendered_html", "rendered_wikitext", "rendered_text")
            return [{"name": name, "type": column_type, "nullable": False} for name in names]

    engine = Engine()
    monkeypatch.setattr(migrate.db, "engine", lambda: engine)
    monkeypatch.setattr(migrate, "inspect", lambda _engine: Inspector())
    assert migrate._widen_text_columns() == 4  # noqa: SLF001 - exact DDL regression
    assert statements == [
        "ALTER TABLE digest_editions MODIFY COLUMN rendered_html MEDIUMTEXT NOT NULL",
        "ALTER TABLE digest_editions MODIFY COLUMN rendered_text MEDIUMTEXT NOT NULL",
        "ALTER TABLE digest_editions MODIFY COLUMN rendered_wikitext MEDIUMTEXT NOT NULL",
        "ALTER TABLE api_cache_meta MODIFY COLUMN value MEDIUMTEXT NOT NULL",
    ]

    monkeypatch.setattr(migrate, "inspect", lambda _engine: Inspector(widened=True))
    assert migrate._widen_text_columns() == 0  # noqa: SLF001 - idempotency regression


def test_widening_preserves_a_nullable_column(monkeypatch):
    """A nullable column stays nullable across the widening.

    The DDL has to restate nullability, and every column this migration
    currently touches is NOT NULL -- so nothing else in the suite would notice
    if the clause were hardcoded rather than read back from the column.
    """
    statements = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def exec_driver_sql(self, statement):
            statements.append(statement)

    class Engine:
        dialect = type("Dialect", (), {"name": "mysql"})()

        def begin(self):
            return Connection()

    class Inspector:
        def get_table_names(self):
            return ["api_cache_meta"]

        def get_columns(self, _table):
            return [{"name": "value", "type": Text(), "nullable": True}]

    monkeypatch.setattr(migrate.db, "engine", lambda: Engine())
    monkeypatch.setattr(migrate, "inspect", lambda _engine: Inspector())
    assert migrate._widen_text_columns() == 1  # noqa: SLF001 - exact DDL regression
    assert statements == ["ALTER TABLE api_cache_meta MODIFY COLUMN value MEDIUMTEXT NULL"]


def test_schema_setup_does_no_row_level_work(configured_db):
    """init_schema() runs in every worker at startup, so it must stay DDL-only.

    A backfill here executes once per process on every restart, with several
    workers doing it at once against a table live requests need. That is what
    took the site down; the work belongs in migrate.py, which runs once before
    the restart.
    """
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/tools/legacy/",
        api_cache.CacheableResponse(200, "application/json", b"{}"),
    )
    canonical_tools.upsert_records(
        [{"name": "legacy-tool", "title": "Legacy", "description": "cached earlier"}],
        source_url="https://toolhub.wikimedia.org/api/search/tools/",
    )
    with db.session_scope() as s:
        s.query(ApiCache).update({ApiCache.path: "", ApiCache.collection: "", ApiCache.detail_key: ""})
        s.execute(db.text("UPDATE canonical_tool_cache SET search_text = ''"))

    db.init_schema()

    # Untouched by schema setup — and still present, never dropped.
    with db.session_scope() as s:
        assert s.query(ApiCache).count() == 1
        assert s.query(ApiCache).one().path == ""
        assert s.execute(db.text("SELECT search_text FROM canonical_tool_cache")).scalar() == ""
    # Only the explicit migration does the row work.
    migrated = {result.name: result.rows for result in migrate.run_once()}
    assert migrated["api_cache index columns"] == 1
    assert migrated["canonical search_text"] == 1


def test_migrate_cleans_legacy_resolver_identity_claims_and_caches(configured_db):
    now = utcnow()
    with db.session_scope() as s:
        user = User(wm_sub="schiste", username="Schiste")
        s.add(user)
        s.flush()
        s.execute(
            db.text(
                "CREATE TABLE user_tool_resolver_cache "
                "(user_id INTEGER PRIMARY KEY, payload TEXT, computed_at DATETIME, "
                "expires_at DATETIME, stale_until DATETIME, last_error TEXT)"
            )
        )
        s.execute(
            db.text(
                "INSERT INTO user_tool_resolver_cache "
                "(user_id, payload, computed_at, expires_at, stale_until) "
                "VALUES (:user_id, '{}', :computed_at, :expires_at, :stale_until)"
            ),
            {
                "user_id": user.id,
                "computed_at": now,
                "expires_at": now + timedelta(minutes=5),
                "stale_until": now + timedelta(days=1),
            },
        )
        s.add_all(
            [
                ToolAuthorClaim(
                    tool_name="wrong-tool",
                    author_name="Effeietsanders",
                    toolhub_username="Schiste",
                    verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                    verification_method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                ),
                ToolAuthorClaim(
                    tool_name="wrong-tool-2",
                    author_name="Effeietsanders",
                    toolhub_username="Schiste",
                    verification_status=sync.AUTHOR_CLAIM_UNVERIFIED,
                    verification_method=sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
                ),
                ToolAuthorClaim(
                    tool_name="signed-tool",
                    author_name="Maintainer Alias",
                    toolhub_username="Schiste",
                    verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                    verification_method=sync.AUTHOR_CLAIM_SIGNED_TOOLINFO,
                    requested_relationship=sync.PERSON_REL_CATALOG_ACTOR,
                ),
                ToolAuthorKey(toolhub_username="Schiste", key_id="legacy-key", public_key="pk"),
            ]
        )

    first = {result.name: result.rows for result in migrate.run_once()}
    assert first["resolver identity cleanup"] == 3
    with db.session_scope() as s:
        assert (
            s.query(ToolAuthorClaim).filter(ToolAuthorClaim.tool_name.in_(["wrong-tool", "wrong-tool-2"])).count() == 0
        )
        signed_claim = s.query(ToolAuthorClaim).filter(ToolAuthorClaim.tool_name == "signed-tool").one()
        migrated_user = s.query(User).one()
        assert signed_claim.user_id == migrated_user.id
        assert signed_claim.requested_relationship == sync.PERSON_REL_MAINTAINER
        assert s.query(ToolAuthorKey).one().user_id == migrated_user.id
        assert s.execute(db.text("SELECT count(*) FROM user_tool_resolver_cache")).scalar() == 0

    second = {result.name: result.rows for result in migrate.run_once()}
    assert second["resolver identity cleanup"] == 0


def test_migrate_retires_only_toolforge_proofs_without_exact_ldap_evidence(configured_db):
    with db.session_scope() as s:
        user = User(wm_sub="42", username="Alice")
        s.add(user)
        s.flush()
        person = maintainer_index.people_index.link_user(s, user)
        s.add_all(
            [
                ToolAuthorClaim(
                    tool_name="legacy-tool",
                    author_name="Alice",
                    toolhub_username="Alice",
                    user_id=user.id,
                    verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                    verification_method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                    evidence_payload={"maintainers": [{"displayName": "Alice"}]},
                ),
                ToolAuthorClaim(
                    tool_name="ldap-tool",
                    author_name="Alice",
                    toolhub_username="Alice",
                    user_id=user.id,
                    verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                    verification_method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                    evidence_payload={
                        "discoveryMethod": "toolforge_ldap_membership",
                        "toolforgeUidNumber": "9001",
                        "toolforgeToolName": "alice-tool",
                    },
                ),
                ToolRelationshipEvidence(
                    tool_name="legacy-tool",
                    person_id=person.id,
                    relationship_type=sync.PERSON_REL_MAINTAINER,
                    source=maintainer_index.SOURCE_TOOLFORGE_TOOLSADMIN,
                    method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                    evidence_key="alice",
                    verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                    confidence=95,
                    evidence_payload={"maintainers": [{"displayName": "Alice"}]},
                ),
            ]
        )

    assert migrate._retire_legacy_toolforge_proofs() == 2  # noqa: SLF001 - exact migration regression
    assert migrate._retire_legacy_toolforge_proofs() == 0  # noqa: SLF001 - idempotency regression

    with db.session_scope() as s:
        legacy_claim = s.query(ToolAuthorClaim).filter_by(tool_name="legacy-tool").one()
        ldap_claim = s.query(ToolAuthorClaim).filter_by(tool_name="ldap-tool").one()
        html_evidence = (
            s.query(ToolRelationshipEvidence).filter_by(source=maintainer_index.SOURCE_TOOLFORGE_TOOLSADMIN).one()
        )
        assert legacy_claim.verification_status == sync.AUTHOR_CLAIM_UNVERIFIED
        assert ldap_claim.verification_status == sync.AUTHOR_CLAIM_VERIFIED
        assert html_evidence.withdrawn_at is not None
        relationship = s.query(ToolPersonRelationship).filter_by(tool_name="legacy-tool").one()
        assert relationship.verification_status == sync.AUTHOR_CLAIM_UNVERIFIED


def test_relationship_backfill_prefers_current_canonical_metadata_over_legacy_snapshot(configured_db):
    canonical_tools.upsert_records(
        [{"name": "identity-tool", "author": [{"name": "Current Author"}]}],
        source_url="https://toolhub.wikimedia.org/api/search/tools/",
    )
    with db.engine().begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE tool_maintainer_edges ("
            "id INTEGER PRIMARY KEY, tool_name VARCHAR(255), source VARCHAR(64), method VARCHAR(64), "
            "maintainer_display_name VARCHAR(255), toolhub_username VARCHAR(255))"
        )
        connection.exec_driver_sql(
            "INSERT INTO tool_maintainer_edges "
            "(id, tool_name, source, method, maintainer_display_name, toolhub_username) "
            "VALUES (1, 'identity-tool', 'toolhub_author_metadata', "
            "'toolhub_author_metadata', 'Stale Author', '')"
        )

    migrate._backfill_relationship_evidence()  # noqa: SLF001 - migration-order regression coverage

    with db.session_scope() as s:
        active = s.query(UnresolvedAttributionEvidence).filter_by(
            tool_name="identity-tool",
            source="toolhub_author_metadata",
            withdrawn_at=None,
        )
        assert [row.observed_label for row in active] == ["Current Author"]


def test_relationship_backfill_skips_canonical_rebuild_after_legacy_table_is_retired(configured_db, monkeypatch):
    canonical_tools.upsert_records(
        [{"name": "current-tool", "author": [{"name": "Current Author"}]}],
        source_url="https://toolhub.wikimedia.org/api/search/tools/",
    )

    def unexpected_rebuild(*_args, **_kwargs):
        pytest.fail("canonical evidence must not be rebuilt after legacy edge retirement")

    monkeypatch.setattr(maintainer_index, "replace_toolhub_metadata_edges", unexpected_rebuild)

    assert migrate._backfill_relationship_evidence() == 0  # noqa: SLF001 - completion-marker regression


def test_migrate_refuses_to_run_against_the_unconfigured_default(monkeypatch, capsys):
    """The guard for the mistake that matters: migrating a stale local database.

    Toolforge injects the tool environment into webservice and job pods only, so
    a deploy step run from a plain `become` shell sees no TOOLHUB_DB_URL, falls
    back to the repo-local SQLite file, and reports success having touched
    nothing real.
    """
    monkeypatch.delenv("TOOLHUB_DB_URL", raising=False)
    assert migrate.main(["--require-configured-db"]) == 1
    assert "TOOLHUB_DB_URL is unset" in capsys.readouterr().err


def test_migrate_runs_against_a_configured_database(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TOOLHUB_DB_URL", f"sqlite:///{tmp_path / 'configured.sqlite3'}")
    assert migrate.main(["--require-configured-db"]) == 0
    out = capsys.readouterr().out
    assert "configured_db_url=yes" in out
    assert "api_cache index columns" in out


def test_migrate_resolves_user_script_loads_stored_before_the_column_existed(configured_db):
    # The sweep only ever resolves what a run writes. A wiki whose sweep finished
    # before `target_page_id` existed rewrites almost nothing, so without this
    # one-off pass its whole dependency graph would stay unresolved indefinitely.
    with db.session_scope() as session:
        session.add(
            UserScriptPage(
                wiki="fr.wikipedia.org",
                title="User:B/two.js",
                role="script",
                content_model="javascript",
            ),
        )
        session.add_all(
            UserScriptImport(
                wiki="fr.wikipedia.org",
                source_title="User:A/one.js",
                verb="importScript",
                target_wiki="fr.wikipedia.org",
                target_title=title,
                target_url="",
            )
            for title in ("User:B/two.js", "User:B/gone.js")
        )

    assert migrate._backfill_userscript_import_targets() == 1
    # And again: a resolved row is not re-counted, and an unresolvable one is
    # left null rather than pointed at something convenient.
    assert migrate._backfill_userscript_import_targets() == 0

    with db.session_scope() as session:
        page_id = session.query(UserScriptPage.id).scalar()
        rows = dict(session.query(UserScriptImport.target_title, UserScriptImport.target_page_id))
    assert rows == {"User:B/two.js": page_id, "User:B/gone.js": None}


def test_migrate_sketches_the_bodies_stored_before_sketches_existed(configured_db):
    # The bodies are already here. Waiting for the next sweep would mean re-reading
    # a whole corpus from the wikis to learn something the rows already contain,
    # and until it finished the fork fold would see nothing to fold.
    body = "\n".join(f"var a{at} = {at} * 3;" for at in range(200))
    with db.session_scope() as session:
        session.add_all(
            [
                UserScriptPage(wiki="fr.wikipedia.org", title="User:A/one.js", role="script", body=body),
                # A shim is not a directory candidate, so sampling it would be
                # work nothing reads.
                UserScriptPage(wiki="fr.wikipedia.org", title="User:B/vector.js", role="shim", body=body),
            ],
        )

    assert migrate._backfill_userscript_sketches() == 1
    # And again: a sketched row is skipped by the filter, so a deploy interrupted
    # halfway resumes rather than starting over.
    assert migrate._backfill_userscript_sketches() == 0

    with db.session_scope() as session:
        stored = dict(session.query(UserScriptPage.title, UserScriptPage.sketch))
    assert stored == {"User:A/one.js": userscripts.sketch(body), "User:B/vector.js": ""}


SWALLOWED = (
    "// ==UserScript==\n"
    # A URL wildcard, not a block-comment opener. Stripping block comments first
    # read it as one and blanked the rest of the file.
    "// @match       https://commons.wikimedia.org/*\n"
    "// ==/UserScript==\n"
    + "".join(f"var line{at} = {at};\n" for at in range(40))
    + "mw.loader.load('//fr.wikipedia.org/w/index.php?title=User:C/lib.js&action=raw&ctype=text/javascript');\n"
    + "/* a closing note */\n"
)


def test_migrate_restates_the_analyses_a_comment_bug_read_as_blank(configured_db):
    # The revision has not moved and never will -- these are abandoned scripts --
    # so the sweep will not revisit them and the correction has no other route in.
    ordinary = "\n".join(f"var b{at} = {at};" for at in range(40))
    with db.session_scope() as session:
        session.add_all(
            [
                UserScriptPage(wiki="fr.wikipedia.org", title="User:A/swallowed.js", role="empty", body=SWALLOWED),
                # Genuinely empty, and it stays that way: the migration offers
                # rows to the analyzer, it does not assume they were wrong.
                UserScriptPage(wiki="fr.wikipedia.org", title="User:B/blank.js", role="empty", body="/* all of it */"),
                # Already a script, so nothing here could have been truncated.
                UserScriptPage(wiki="fr.wikipedia.org", title="User:C/lib.js", role="script", body=ordinary),
            ],
        )

    assert migrate._restate_swallowed_userscript_analyses() == 1
    # And again: a row whose verdict does not move is written zero times, so a
    # second deploy is free rather than merely harmless.
    assert migrate._restate_swallowed_userscript_analyses() == 0

    with db.session_scope() as session:
        roles = dict(session.query(UserScriptPage.title, UserScriptPage.role))
        loads = [row.target_title for row in session.query(UserScriptImport).all()]
    assert roles == {
        "User:A/swallowed.js": userscripts.ROLE_SCRIPT,
        "User:B/blank.js": userscripts.ROLE_EMPTY,
        "User:C/lib.js": userscripts.ROLE_SCRIPT,
    }
    # The loads were parsed out of the same blanked body and were missing in the
    # same way, so the demand this page places on other scripts was never counted.
    assert loads == ["User:C/lib.js"]


def test_migrate_leaves_a_deleted_page_out_of_the_restatement(configured_db):
    # A tombstoned page is not a directory candidate whatever it says, and
    # rewriting one would spend the walk on rows nothing reads.
    with db.session_scope() as session:
        session.add(
            UserScriptPage(
                wiki="fr.wikipedia.org",
                title="User:A/gone.js",
                role="empty",
                body=SWALLOWED,
                deleted_at=utcnow(),
            ),
        )

    assert migrate._restate_swallowed_userscript_analyses() == 0

    with db.session_scope() as session:
        assert session.query(UserScriptPage.role).scalar() == "empty"


def test_the_import_key_is_widened_once_and_then_left_alone(configured_db):
    # A fresh database declares the widened key with the table, so there is no
    # separate unique index and nothing for this to do. What production has is
    # the older spelling: a constraint declared unnamed, which MariaDB created
    # as a standalone index named after its first column.
    assert migrate._widen_userscript_import_key() == 0

    engine = db.engine()
    table = UserScriptImport.__tablename__
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE UNIQUE INDEX wiki ON {table} "
            "(wiki, source_title, verb, target_wiki, target_title, target_url)",
        )

    assert migrate._widen_userscript_import_key() == 1
    # And again: the key it just created is the one it looks for, so a second
    # deploy is a no-op rather than a drop-and-rebuild of a live index.
    assert migrate._widen_userscript_import_key() == 0

    unique = {item["name"]: item["column_names"] for item in inspect(engine).get_indexes(table) if item["unique"]}
    assert list(unique) == [migrate.WIDENED_IMPORT_KEY]
    assert tuple(unique[migrate.WIDENED_IMPORT_KEY]) == migrate.WIDENED_IMPORT_KEY_COLUMNS


def held_by_another_writer(errno=1205):
    """The exception SQLAlchemy raises when MariaDB refuses to wait any longer.

    Built rather than provoked because the suite runs on SQLite, which has no
    row locks to contend for. What is under test is the decision the migration
    makes about the refusal, not the database's ability to produce one.
    """
    return migrate.OperationalError(
        "UPDATE person_identifiers SET last_seen_at=?, updated_at=? WHERE person_identifiers.id = ?",
        {},
        RuntimeError(errno, "Lock wait timeout exceeded; try restarting transaction"),
    )


def legacy_identifiers(count):
    """`count` identifier rows spelled the way the pre-vocabulary code wrote them."""
    with db.session_scope() as s:
        person = Person(canonical_key="person-under-migration", display_name="Person")
        s.add(person)
        s.flush()
        s.add_all(
            PersonIdentifier(
                person_id=person.id,
                namespace="toolhub",
                value=f"user{index}",
                normalized_value=f"user{index}",
            )
            for index in range(count)
        )


def test_a_chunk_another_writer_holds_is_left_for_the_next_deploy(configured_db, monkeypatch, capsys):
    # The regression: as one transaction over the whole table, a single held row
    # rolled back every row restated before it, so the pass could never converge
    # and the deploy died before it loaded jobs or recorded the release.
    legacy_identifiers(6)
    monkeypatch.setattr(migrate, "BACKFILL_CHUNK", 2)
    restate = migrate._restate_identifiers
    seen = []

    def refuse_the_second_chunk(rows, now):
        rows = list(rows)
        seen.append(len(rows))
        restated = restate(rows, now)
        if len(seen) == 2:
            raise held_by_another_writer()
        return restated

    monkeypatch.setattr(migrate, "_restate_identifiers", refuse_the_second_chunk)
    changed, deferred = migrate._normalize_identifier_vocabulary()

    # Every chunk was visited, so one held chunk does not stop the walk...
    assert seen == [2, 2, 2]
    # ...and the two rows it could not have are reported as left behind rather
    # than counted among the ones it changed.
    assert (changed, deferred) == (4, 2)
    with db.session_scope() as s:
        namespaces = [
            row for row in s.execute(select(PersonIdentifier.namespace).order_by(PersonIdentifier.id)).scalars()
        ]
    assert namespaces.count("toolhub") == 2


def test_the_deferred_rows_are_restated_by_the_next_run(configured_db, monkeypatch):
    # Convergence is the point of deferring rather than failing: what one deploy
    # could not lock, the next one takes.
    legacy_identifiers(6)
    monkeypatch.setattr(migrate, "BACKFILL_CHUNK", 2)
    restate = migrate._restate_identifiers
    calls = []

    def refuse_once(rows, now):
        calls.append(1)
        restated = restate(list(rows), now)
        if len(calls) == 2:
            raise held_by_another_writer()
        return restated

    monkeypatch.setattr(migrate, "_restate_identifiers", refuse_once)
    migrate._normalize_identifier_vocabulary()
    monkeypatch.setattr(migrate, "_restate_identifiers", restate)

    assert migrate._normalize_identifier_vocabulary() == (2, 0)
    assert migrate._normalize_identifier_vocabulary() == (0, 0)


def test_a_database_error_that_is_not_contention_still_fails_the_deploy(configured_db, monkeypatch):
    # The narrow escape hatch must stay narrow: a dropped connection is not a
    # row someone else is holding, and a deploy should not survive one.
    legacy_identifiers(2)
    monkeypatch.setattr(
        migrate,
        "_restate_identifiers",
        lambda rows, now: (_ for _ in ()).throw(held_by_another_writer(errno=2013)),
    )
    with pytest.raises(migrate.OperationalError):
        migrate._normalize_identifier_vocabulary()


def test_the_operator_is_told_what_was_left_behind(configured_db, monkeypatch, capsys):
    legacy_identifiers(2)
    monkeypatch.setattr(
        migrate,
        "_restate_identifiers",
        lambda rows, now: (_ for _ in ()).throw(held_by_another_writer()),
    )
    migrate._backfill_people_identity()
    assert "left 2 identifier rows to the next deploy" in capsys.readouterr().err


def unlinked_accounts(count):
    """`count` OAuth accounts whose people exist but which do not point at them yet.

    The identifier row is here so the accounts are the ordinary shape: a person
    already known under their Toolhub id, with the account not yet pointing at
    it. An account with no identifier row at all links too -- see
    `test_an_account_with_nothing_to_compare_against_is_linked_rather_than_skipped`.
    """
    with db.session_scope() as s:
        for index in range(count):
            person = Person(canonical_key=f"account-{index}", display_name=f"Account{index}")
            s.add(person)
            s.flush()
            s.add(User(wm_sub=str(index), username=f"Account{index}"))
            s.add(
                PersonIdentifier(
                    person_id=person.id,
                    namespace=migrate.people_index.NS_TOOLHUB_USER_ID,
                    value=str(index),
                    normalized_value=str(index),
                    identifier_kind=migrate.people_index.IDENTIFIER_STABLE,
                    is_current=True,
                )
            )


def test_a_held_account_chunk_leaves_the_rest_of_the_accounts_linked(configured_db, monkeypatch, capsys):
    # The second regression, and the one the identifier fix did not cover:
    # linking rewrites identifier rows too, so it meets the same writers -- but
    # the refusal arrives out of `ensure_person`'s next SELECT via autoflush,
    # where nothing was catching it, and killed the deploy outright.
    unlinked_accounts(6)
    monkeypatch.setattr(migrate, "BACKFILL_CHUNK", 2)
    link = migrate.people_index.link_user
    seen = []

    def refuse_the_second_chunk(s, user):
        seen.append(user.wm_sub)
        if len(seen) == 3:
            raise held_by_another_writer()
        return link(s, user)

    monkeypatch.setattr(migrate.people_index, "link_user", refuse_the_second_chunk)
    linked, deferred = migrate._link_accounts_to_people()

    # The walk reached every account despite the refusal in the middle of it...
    assert seen == ["0", "1", "2", "4", "5"]
    # ...and the chunk it could not have is reported as left behind rather than
    # counted among the accounts it linked.
    assert (linked, deferred) == (4, 2)
    with db.session_scope() as s:
        linked_subs = sorted(
            s.execute(select(User.wm_sub).where(User.person_id.is_not(None))).scalars(),
        )
    # Accounts 2 and 3 shared the held chunk, so neither landed; the next deploy
    # takes them.
    assert linked_subs == ["0", "1", "4", "5"]


def test_an_account_already_pointed_at_its_person_is_not_restamped(configured_db, monkeypatch):
    # Restamping an identifier that needs no change is what generates the write
    # traffic this whole pass has to defer around, so the skip is load-bearing
    # rather than an optimization.
    unlinked_accounts(2)
    assert migrate._link_accounts_to_people() == (2, 0)

    monkeypatch.setattr(
        migrate.people_index,
        "link_user",
        lambda s, user: pytest.fail(f"relinked {user.wm_sub}, which was already linked"),
    )
    assert migrate._link_accounts_to_people() == (0, 0)


def test_an_account_error_that_is_not_contention_still_fails_the_deploy(configured_db, monkeypatch):
    unlinked_accounts(2)
    monkeypatch.setattr(
        migrate.people_index,
        "link_user",
        lambda s, user: (_ for _ in ()).throw(held_by_another_writer(errno=2013)),
    )
    with pytest.raises(migrate.OperationalError):
        migrate._link_accounts_to_people()


def test_the_operator_is_told_which_accounts_were_left_behind(configured_db, monkeypatch, capsys):
    unlinked_accounts(2)
    monkeypatch.setattr(
        migrate.people_index,
        "link_user",
        lambda s, user: (_ for _ in ()).throw(held_by_another_writer()),
    )
    migrate._backfill_people_identity()
    assert "left 2 account links to the next deploy" in capsys.readouterr().err


def unowned_claims(count):
    """`count` author claims naming an account by handle without pointing at its id.

    The shape `maintainer-backfill` also rewrites: it fills `user_id` and
    `toolhub_username` from the handle every hour at :13, which is what the
    migration can find held.
    """
    with db.session_scope() as s:
        for index in range(count):
            s.add(User(wm_sub=f"claimant-{index}", username=f"Claimant{index}"))
        s.flush()
        for index in range(count):
            s.add(
                ToolAuthorClaim(
                    tool_name=f"tool-{index}",
                    author_name=f"Claimant{index}",
                    toolhub_username=f"Claimant{index}",
                    user_id=None,
                )
            )


def owned_claim_handles():
    """The handles of the claims that now point at an account id."""
    with db.session_scope() as s:
        return sorted(
            s.execute(select(ToolAuthorClaim.toolhub_username).where(ToolAuthorClaim.user_id.is_not(None))).scalars()
        )


def test_a_held_claim_chunk_leaves_the_rest_of_the_owner_rows_relinked(configured_db, monkeypatch):
    # The last pass still holding every row it touched in one transaction. It
    # writes the two columns `maintainer-backfill` writes, so a deploy landing
    # in that job's minute met a held row and aborted the whole migration --
    # after `git pull` had already fast-forwarded the host.
    unowned_claims(6)
    monkeypatch.setattr(migrate, "BACKFILL_CHUNK", 2)
    restate = migrate._restate_account_owned_record
    seen = []

    def refuse_the_second_chunk(row, owners_by_id, owners_by_handle):
        seen.append(row.toolhub_username)
        if len(seen) == 3:
            raise held_by_another_writer()
        return restate(row, owners_by_id, owners_by_handle)

    monkeypatch.setattr(migrate, "_restate_account_owned_record", refuse_the_second_chunk)
    touched, deferred = migrate._relink_account_owned_records()

    # The walk reached every claim despite the refusal in the middle of it...
    assert seen == ["Claimant0", "Claimant1", "Claimant2", "Claimant4", "Claimant5"]
    # ...and the chunk it could not have is reported as left behind.
    assert deferred == 2
    assert touched > 0
    # Claims 2 and 3 shared the held chunk, so neither landed; the next deploy
    # takes them.
    assert owned_claim_handles() == ["Claimant0", "Claimant1", "Claimant4", "Claimant5"]


def test_an_owner_row_already_pointed_at_its_account_is_not_rewritten(configured_db):
    unowned_claims(2)
    assert migrate._relink_account_owned_records()[1] == 0
    assert owned_claim_handles() == ["Claimant0", "Claimant1"]
    # Second pass over settled rows writes nothing, so a re-run cannot generate
    # the contention this pass has to defer around.
    assert migrate._relink_account_owned_records() == (0, 0)


def test_an_owner_row_error_that_is_not_contention_still_fails_the_deploy(configured_db, monkeypatch):
    unowned_claims(2)
    monkeypatch.setattr(
        migrate,
        "_restate_account_owned_record",
        lambda row, by_id, by_handle: (_ for _ in ()).throw(held_by_another_writer(errno=2013)),
    )
    with pytest.raises(migrate.OperationalError):
        migrate._relink_account_owned_records()


def test_the_operator_is_told_which_owner_rows_were_left_behind(configured_db, monkeypatch, capsys):
    unowned_claims(2)
    monkeypatch.setattr(
        migrate,
        "_restate_account_owned_record",
        lambda row, by_id, by_handle: (_ for _ in ()).throw(held_by_another_writer()),
    )
    migrate._backfill_people_identity()
    assert "left 2 claim and key owner rows to the next deploy" in capsys.readouterr().err


def test_a_deadlock_victim_is_treated_as_contention_and_a_bare_error_is_not():
    assert migrate._is_lock_contention(held_by_another_writer(errno=1213))
    assert not migrate._is_lock_contention(migrate.OperationalError("SELECT 1", {}, RuntimeError()))


def test_run_once_reports_the_migrations_that_finished_before_one_failed(configured_db, monkeypatch):
    # A list built every migration before printing any, so a failure late in the
    # sequence threw away the record of everything that had already committed.
    monkeypatch.setattr(
        migrate,
        "_backfill_userscript_import_targets",
        lambda: (_ for _ in ()).throw(RuntimeError("migration 19 fails")),
    )
    reported = []
    with pytest.raises(RuntimeError):
        for result in migrate.migrations():
            reported.append(result.name)
    assert "text columns widened to MEDIUMTEXT" in reported
    assert "user-script loads resolved to pages" not in reported


def test_an_account_with_nothing_to_compare_against_is_linked_rather_than_skipped(configured_db):
    """The skip is a match on the owner, not an absence of one.

    An account with no identifier row has no owner to compare against, and its
    `person_id` is NULL for the same reason. Comparing the two without first
    asking whether an owner exists made the two NULLs agree, and the pass read
    "already linked" over the one row it exists to repair -- the only row it
    could never fix. Unreachable through login, which sets `person_id`, so
    nothing but this test says so.
    """
    with db.session_scope() as s:
        s.add(User(wm_sub="991", username="Stranded"))

    linked, deferred = migrate._link_accounts_to_people()

    assert (linked, deferred) == (1, 0)
    with db.session_scope() as s:
        user = s.execute(select(User).where(User.wm_sub == "991")).scalars().one()
        assert user.person_id is not None
        owners = s.execute(
            select(PersonIdentifier).where(PersonIdentifier.person_id == user.person_id)
        ).scalars()
        assert migrate.people_index.NS_TOOLHUB_USER_ID in {row.namespace for row in owners}


def test_the_projection_step_asks_for_a_slice_not_the_whole_catalogue(monkeypatch):
    """A deploy that re-projects everything is a deploy that gets OOM-killed.

    Asserted against the limit actually passed, because the defect was a
    constant swapped at one call site: migrate read `MAX_REFRESH_TOOLS`, which
    is the hourly job's budget, and inherited a sweep it has no room for.
    """
    asked = []

    def _record(limit):
        asked.append(limit)
        return {"refreshed": 0}

    monkeypatch.setattr(migrate.catalog_projection, "refresh_candidates", _record)
    list(migrate.migrations())

    assert asked == [migrate.catalog_projection.MIGRATION_REFRESH_TOOLS]
    assert asked[0] < migrate.catalog_projection.MAX_REFRESH_TOOLS
