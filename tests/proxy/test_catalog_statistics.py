# SPDX-License-Identifier: GPL-3.0-or-later
"""Catalog-quality statistics use explicit, stable denominators."""

import contextlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import catalog_statistics, db, people_index  # noqa: E402
from backend.models import (  # noqa: E402
    ApiCacheMeta,
    CanonicalToolCache,
    ToolhubAccountProjection,
    ToolinfoAuthorBinding,
    ToolinfoSource,
    ToolPersonRelationship,
    UnresolvedAttributionEvidence,
    utcnow,
)
from backend.sync import AUTHOR_CLAIM_VERIFIED, PERSON_REL_AUTHOR, PERSON_REL_MAINTAINER  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()


def _tool(session, name, record):
    now = datetime.now(tz=UTC).replace(tzinfo=None)
    session.add(
        CanonicalToolCache(
            tool_name=name,
            record={"name": name, **record},
            source_url=f"https://toolhub.example/{name}",
            expires_at=now + timedelta(days=1),
            stale_until=now + timedelta(days=2),
        )
    )


def test_snapshot_keeps_missing_data_and_relationship_quality_visible():
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)
    with db.session_scope() as session:
        _tool(
            session,
            "complete",
            {
                "title": "Complete",
                "description": "Documented",
                "url": "https://complete.example",
                "tool_type": "web app",
                "author": [{"name": "Ada"}],
                "created_date": "2024-01-02T00:00:00Z",
                "modified_date": "2026-08-01T00:00:00Z",
            },
        )
        _tool(session, "unresolved", {"deprecated": True, "author": "Display only"})
        _tool(session, "empty", {})
        person = people_index.ensure_person(
            session,
            display_name="Ada",
            wikimedia_global_user_id="42",
            source="test",
        )
        session.add_all(
            [
                ToolPersonRelationship(
                    tool_name="complete",
                    person_id=person.id,
                    relationship_type=PERSON_REL_AUTHOR,
                    verification_status=AUTHOR_CLAIM_VERIFIED,
                ),
                ToolPersonRelationship(
                    tool_name="complete",
                    person_id=person.id,
                    relationship_type=PERSON_REL_MAINTAINER,
                    verification_status=AUTHOR_CLAIM_VERIFIED,
                ),
                UnresolvedAttributionEvidence(
                    tool_name="unresolved",
                    observed_label="Display only",
                    normalized_label="display only",
                    relationship_type=PERSON_REL_AUTHOR,
                    source="test",
                ),
                ToolinfoSource(
                    url="https://complete.example/toolinfo.json",
                    valid=True,
                    status="valid",
                    item_count=2,
                ),
            ]
        )
        session.flush()
        payload = catalog_statistics.build_snapshot(session, now=now)

    assert payload["catalog"] == {
        "totalTools": 3,
        "activeTools": 2,
        "deprecatedTools": 1,
        "experimentalTools": 0,
        "listedAuthors": {"count": 2, "missingCount": 1, "percent": 67},
        "verifiedAuthors": {"count": 1, "missingCount": 2, "percent": 33},
        "verifiedMaintainers": {"count": 1, "missingCount": 2, "percent": 33},
        "unresolvedAuthorTools": 1,
        "coreMetadataComplete": {"count": 1, "missingCount": 2, "percent": 33},
    }
    assert payload["identities"]["publishablePeople"] == 1
    assert payload["identities"]["unresolvedLabels"] == 1
    assert payload["distributions"]["createdByYear"] == [
        {"key": "2024", "label": "2024", "count": 1},
        {"key": "unknown", "label": "Date unavailable", "count": 2},
    ]
    assert payload["distributions"]["modifiedRecency"][0]["count"] == 1
    assert payload["distributions"]["modifiedRecency"][-1]["count"] == 2


def test_statistics_endpoint_is_publicly_cacheable_and_supports_etag():
    app = Flask(__name__)
    backend.register(app, db_url="sqlite://", secret_key="test-secret")
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    with db.session_scope() as session:
        _tool(session, "one", {"title": "One"})

    response = app.test_client().get("/v1/statistics/")
    assert response.status_code == 200
    assert response.get_json()["catalog"]["totalTools"] == 1
    assert response.headers["Cache-Control"].startswith("public, max-age=300")
    etag = response.headers["ETag"]
    assert app.test_client().get("/v1/statistics/", headers={"If-None-Match": etag}).status_code == 304


def _label(session, label, tool_name="t"):
    session.add(
        UnresolvedAttributionEvidence(
            tool_name=tool_name,
            observed_label=label,
            normalized_label=label.casefold(),
            relationship_type=PERSON_REL_AUTHOR,
            source="test",
        )
    )


def _account(session, toolhub_user_id, username):
    session.add(
        ToolhubAccountProjection(
            toolhub_user_id=toolhub_user_id,
            username=username,
            normalized_username=username.casefold(),
        )
    )


def test_attribution_funnel_partitions_labels_by_the_rule_that_could_reach_them():
    with db.session_scope() as session:
        _tool(session, "t", {"title": "T"})
        _label(session, "Ada")
        _account(session, "1", "Ada")
        _label(session, "Grace")
        _account(session, "2", "Grace")
        _account(session, "3", "grace")
        _label(session, "Hopper")
        people_index.ensure_person(
            session,
            display_name="Hopper",
            wikimedia_global_user_id="7",
            wiki_username="Hopper",
            source="test",
        )
        _label(session, "Nobody At All")
        session.flush()
        funnel = catalog_statistics.build_snapshot(session)["attribution"]

    assert funnel["distinctLabels"] == 4
    assert funnel["exactToolhubAccount"] == 1
    assert funnel["ambiguousToolhubAccount"] == 1
    assert funnel["verifiedHandleOnly"] == 1
    assert funnel["noLocalMatch"] == 1
    # The four buckets are a partition, so the total can never double-count or
    # quietly drop a label as new rules are added.
    assert (
        funnel["exactToolhubAccount"]
        + funnel["ambiguousToolhubAccount"]
        + funnel["verifiedHandleOnly"]
        + funnel["noLocalMatch"]
        == funnel["distinctLabels"]
    )


def test_a_handle_on_an_unpublishable_person_does_not_count_as_reachable():
    with db.session_scope() as session:
        _tool(session, "t", {"title": "T"})
        _label(session, "Ghost")
        # A display-name-only person is not publishable, so its handle must not
        # make the label look resolvable.
        people_index.ensure_person(session, display_name="Ghost", source="test")
        session.flush()
        funnel = catalog_statistics.build_snapshot(session)["attribution"]

    assert funnel["noLocalMatch"] == 1
    assert funnel["verifiedHandleOnly"] == 0


def test_source_binding_outcomes_are_reported_and_withdrawn_rows_are_excluded():
    with db.session_scope() as session:
        _tool(session, "t", {"title": "T"})
        source = ToolinfoSource(url="https://example.test/toolinfo.json", valid=True, status="valid", item_count=1)
        session.add(source)
        session.flush()
        session.add_all(
            [
                ToolinfoAuthorBinding(
                    source_id=source.id,
                    normalized_label="ada",
                    status="resolved",
                    method="toolinfo_structured_author_handle",
                ),
                ToolinfoAuthorBinding(
                    source_id=source.id,
                    normalized_label="grace",
                    status="unresolved",
                    method="display_only",
                ),
                ToolinfoAuthorBinding(
                    source_id=source.id,
                    normalized_label="gone",
                    status="resolved",
                    method="toolinfo_structured_author_handle",
                    withdrawn_at=datetime(2026, 1, 1),
                ),
            ]
        )
        session.flush()
        funnel = catalog_statistics.build_snapshot(session)["attribution"]

    assert funnel["sourceBindings"] == {"resolved": 1, "unresolved": 1}
    assert funnel["sourceBindingMethods"] == {"display_only": 1, "toolinfo_structured_author_handle": 1}


def test_the_ceiling_is_split_by_whether_a_registry_could_resolve_the_label():
    with db.session_scope() as session:
        _tool(session, "t", {"title": "T"})
        # Neither matches anything locally, so both land in noLocalMatch; only
        # the first could ever be looked up in a public registry.
        _label(session, "0xDeadbeef")
        _label(session, "Aaron Liu")
        session.flush()
        funnel = catalog_statistics.build_snapshot(session)["attribution"]

    assert funnel["noLocalMatch"] == 2
    assert funnel["noLocalMatchHandleShaped"] == 1
    assert funnel["noLocalMatchNameShaped"] == 1
    # The split is a partition of the ceiling, not a third bucket beside it.
    assert funnel["noLocalMatchHandleShaped"] + funnel["noLocalMatchNameShaped"] == funnel["noLocalMatch"]


def test_parse_date_rejects_garbage_and_normalizes_timezones():
    assert catalog_statistics._parse_date("") is None
    assert catalog_statistics._parse_date("not-a-real-date") is None
    naive = catalog_statistics._parse_date("2024-05-01T00:00:00")
    assert naive == datetime(2024, 5, 1, tzinfo=UTC)
    aware = catalog_statistics._parse_date("2024-05-01T00:00:00+02:00")
    assert aware == datetime(2024, 4, 30, 22, 0, tzinfo=UTC)


def test_year_histogram_omits_the_unknown_bucket_when_every_date_parses():
    rows = catalog_statistics._year_histogram(["2024-01-01", "2025-06-01"])

    assert rows == [
        {"key": "2024", "label": "2024", "count": 1},
        {"key": "2025", "label": "2025", "count": 1},
    ]
    assert all(row["key"] != "unknown" for row in rows)


def test_recency_histogram_walks_every_bucket_including_older_and_unknown():
    now = datetime(2026, 8, 13, tzinfo=UTC)
    values = [
        (now - timedelta(days=5)).isoformat(),  # last30Days
        (now - timedelta(days=45)).isoformat(),  # falls through last30Days into days31To90
        (now - timedelta(days=1200)).isoformat(),  # older than every named bucket
        "garbage",  # unknown
    ]

    rows = catalog_statistics._recency_histogram(values, now)
    by_key = {row["key"]: row["count"] for row in rows}

    assert by_key["last30Days"] == 1
    assert by_key["days31To90"] == 1
    assert by_key["older"] == 1
    assert by_key["unknown"] == 1


def test_an_unpublishable_handle_does_not_resolve_the_label_it_matches():
    with db.session_scope() as session:
        _tool(session, "t", {"title": "T"})
        _label(session, "Casper")
        # A wiki-username handle from an untrusted source is real evidence
        # but not publishable, so it must not count as a local match either.
        people_index.ensure_person(session, display_name="Casper", wiki_username="Casper", source="test")
        session.flush()
        funnel = catalog_statistics.build_snapshot(session)["attribution"]

    assert funnel["verifiedHandleOnly"] == 0
    assert funnel["noLocalMatch"] == 1


def test_relationships_skip_orphaned_rows_and_report_expired_verified_claims_as_stale():
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)
    with db.session_scope() as session:
        _tool(session, "known", {"title": "Known"})
        person = people_index.ensure_person(
            session, display_name="Ada", wikimedia_global_user_id="99", source="test"
        )
        session.add_all(
            [
                # A verified claim whose expiry has passed must be reported as
                # stale, not counted as currently verified.
                ToolPersonRelationship(
                    tool_name="known",
                    person_id=person.id,
                    relationship_type=PERSON_REL_AUTHOR,
                    verification_status=AUTHOR_CLAIM_VERIFIED,
                    expires_at=now.replace(tzinfo=None) - timedelta(days=1),
                ),
                # A relationship for a tool no longer in the canonical cache
                # must be skipped entirely rather than skewing the counts.
                ToolPersonRelationship(
                    tool_name="orphaned",
                    person_id=person.id,
                    relationship_type=PERSON_REL_MAINTAINER,
                    verification_status=AUTHOR_CLAIM_VERIFIED,
                ),
            ]
        )
        session.flush()
        payload = catalog_statistics.build_snapshot(session, now=now)

    assert payload["relationships"]["authors"] == {"stale": 1}
    assert payload["relationships"]["maintainers"] == {}
    assert payload["catalog"]["verifiedAuthors"] == {"count": 0, "missingCount": 1, "percent": 0}


def test_snapshot_rebuilds_when_the_cached_payload_is_corrupt_json():
    with db.session_scope() as session:
        _tool(session, "t", {"title": "T"})
        session.add(ApiCacheMeta(key=catalog_statistics.SNAPSHOT_KEY, value="{not valid json", updated_at=utcnow()))

    payload = catalog_statistics.snapshot()

    assert payload["catalog"]["totalTools"] == 1
    with db.session_scope() as session:
        row = session.get(ApiCacheMeta, catalog_statistics.SNAPSHOT_KEY)
        assert json.loads(row.value) == payload


def test_snapshot_returns_a_fresh_payload_without_writing_cache_when_the_lock_is_not_acquired(monkeypatch):
    @contextlib.contextmanager
    def never_acquires(_name, *, timeout_seconds=0):  # noqa: ARG001
        yield False

    monkeypatch.setattr(catalog_statistics.db, "advisory_lock", never_acquires)
    with db.session_scope() as session:
        _tool(session, "t", {"title": "T"})

    payload = catalog_statistics.snapshot()

    assert payload["catalog"]["totalTools"] == 1
    with db.session_scope() as session:
        assert session.get(ApiCacheMeta, catalog_statistics.SNAPSHOT_KEY) is None


def test_snapshot_force_rebuild_updates_the_existing_cache_row_in_place():
    with db.session_scope() as session:
        _tool(session, "t", {"title": "T"})
    first = catalog_statistics.snapshot()

    with db.session_scope() as session:
        _tool(session, "second", {"title": "Second"})
    second = catalog_statistics.snapshot(force=True)

    assert first["catalog"]["totalTools"] == 1
    assert second["catalog"]["totalTools"] == 2
    with db.session_scope() as session:
        row = session.get(ApiCacheMeta, catalog_statistics.SNAPSHOT_KEY)
        assert json.loads(row.value) == second
