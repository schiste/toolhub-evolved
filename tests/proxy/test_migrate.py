# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the one-off data migration entrypoint (proxy/migrate.py).

These cover the two properties that make it safe to run from a deploy: it is
idempotent, and it refuses to silently migrate the wrong database.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import Text
from sqlalchemy.dialects import mysql
from sqlalchemy.dialects.mysql import MEDIUMTEXT, mariadb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import migrate  # noqa: E402
from backend import api_cache, canonical_tools, db, maintainer_index  # noqa: E402
from backend.models import (  # noqa: E402
    ApiCache,
    DigestEdition,
    DigestSubscription,
    Person,
    ToolAuthorClaim,
    ToolAuthorKey,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    UnresolvedAttributionEvidence,
    User,
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
    assert first["digest render MEDIUMTEXT"] == 0
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
        # Stamped now, not backdated: delivery gates on confirmed_at <= published_at,
        # so a backdated stamp would make an already-published edition eligible.
        assert rows["daily"].confirmed_at > published_at
        # An explicitly stopped subscription stays stopped across deployments.
        assert rows["weekly"].active is False


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


def test_digest_render_migration_is_mysql_idempotent(monkeypatch):
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
            return ["digest_editions"]

        def get_columns(self, _table):
            column_type = MEDIUMTEXT() if self.widened else Text()
            return [
                {"name": name, "type": column_type} for name in ("rendered_html", "rendered_wikitext", "rendered_text")
            ]

    engine = Engine()
    monkeypatch.setattr(migrate.db, "engine", lambda: engine)
    monkeypatch.setattr(migrate, "inspect", lambda _engine: Inspector())
    assert migrate._widen_digest_render_columns() == 3  # noqa: SLF001 - exact DDL regression
    assert statements == [
        "ALTER TABLE digest_editions MODIFY COLUMN rendered_html MEDIUMTEXT NOT NULL",
        "ALTER TABLE digest_editions MODIFY COLUMN rendered_text MEDIUMTEXT NOT NULL",
        "ALTER TABLE digest_editions MODIFY COLUMN rendered_wikitext MEDIUMTEXT NOT NULL",
    ]

    monkeypatch.setattr(migrate, "inspect", lambda _engine: Inspector(widened=True))
    assert migrate._widen_digest_render_columns() == 0  # noqa: SLF001 - idempotency regression


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
