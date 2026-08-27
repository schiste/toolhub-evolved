# SPDX-License-Identifier: GPL-3.0-or-later
"""Catalog-quality statistics use explicit, stable denominators."""

import contextlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import catalog_statistics, db, job_catalog, people_index  # noqa: E402
from backend.models import (  # noqa: E402
    ApiCacheMeta,
    CanonicalToolCache,
    CatalogToolProjection,
    ToolhubAccountProjection,
    ToolinfoAuthorBinding,
    ToolinfoSource,
    ToolinfoSourceAttestation,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    UnresolvedAttributionEvidence,
    utcnow,
)
from backend.sync import (  # noqa: E402
    AUTHOR_CLAIM_VERIFIED,
    PERSON_REL_AUTHOR,
    PERSON_REL_MAINTAINER,
    SOURCE_OFFICIAL,
    SOURCE_WIKI_GADGET,
    SOURCE_WIKI_USERSCRIPT,
)


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()


def _tool(session, name, record, source=SOURCE_OFFICIAL):
    now = datetime.now(tz=UTC).replace(tzinfo=None)
    session.add(
        CanonicalToolCache(
            tool_name=name,
            record={"name": name, **record},
            source=source,
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


def _created_histogram(source=None):
    """The creation-year series, either combined or for one of the two lanes."""
    now = datetime(2026, 8, 25, 12, tzinfo=UTC)
    with db.session_scope() as session:
        _tool(session, "registered", {"created_date": "2019-03-04T11:00:00Z"})
        _tool(
            session,
            "gadget",
            {"created_date": "2007-03-11T12:00:00Z"},
            source=SOURCE_WIKI_GADGET,
        )
        _tool(
            session,
            "script",
            {"created_date": "2009-04-12T18:30:00Z"},
            source=SOURCE_WIKI_USERSCRIPT,
        )
        session.flush()
        payload = catalog_statistics.build_snapshot(session, now=now)
    document = payload if source is None else payload["lenses"][source]
    series = document["distributions"]["createdByYear"]
    return {bucket["key"]: bucket["count"] for bucket in series if bucket["count"]}


def test_the_creation_years_count_every_source_together_by_default():
    assert _created_histogram() == {"2007": 1, "2009": 1, "2019": 1}


def test_the_registered_lane_leaves_out_what_the_wikis_contributed():
    assert _created_histogram("catalog") == {"2019": 1}


def test_the_wiki_lane_holds_both_gadgets_and_user_scripts_and_nothing_else():
    assert _created_histogram("wiki") == {"2007": 1, "2009": 1}


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
    histogram = catalog_statistics._YearHistogram()
    for value in ("2024-01-01", "2025-06-01"):
        histogram.add(value)
    rows = histogram.rows()

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

    histogram = catalog_statistics._RecencyHistogram(now)
    for value in values:
        histogram.add(value)
    rows = histogram.rows()
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
        person = people_index.ensure_person(session, display_name="Ada", wikimedia_global_user_id="99", source="test")
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


def test_relationship_metrics_separate_tools_people_rows_changes_and_freshness():
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)
    naive_now = now.replace(tzinfo=None)
    with db.session_scope() as session:
        for name in ("alpha", "beta", "gamma"):
            _tool(session, name, {"title": name.title()})
        linked = people_index.ensure_person(
            session, display_name="Linked", wikimedia_global_user_id="101", source="test"
        )
        identity_only = people_index.ensure_person(
            session, display_name="Identity only", wikimedia_global_user_id="102", source="test"
        )
        session.add_all(
            [
                ToolPersonRelationship(
                    tool_name="alpha",
                    person_id=linked.id,
                    relationship_type=PERSON_REL_AUTHOR,
                    verification_status=AUTHOR_CLAIM_VERIFIED,
                    verified_at=naive_now - timedelta(hours=2),
                ),
                ToolPersonRelationship(
                    tool_name="beta",
                    person_id=linked.id,
                    relationship_type=PERSON_REL_MAINTAINER,
                    verification_status=AUTHOR_CLAIM_VERIFIED,
                    verified_at=naive_now - timedelta(days=2),
                ),
                ToolPersonRelationship(
                    tool_name="gamma",
                    person_id=linked.id,
                    relationship_type=PERSON_REL_MAINTAINER,
                    verification_status=AUTHOR_CLAIM_VERIFIED,
                    verified_at=naive_now - timedelta(hours=1),
                    expires_at=naive_now - timedelta(minutes=1),
                ),
                ToolRelationshipEvidence(
                    tool_name="alpha",
                    person_id=linked.id,
                    relationship_type=PERSON_REL_AUTHOR,
                    source="test",
                    verification_status=AUTHOR_CLAIM_VERIFIED,
                    expires_at=naive_now + timedelta(hours=48),
                ),
                ToolRelationshipEvidence(
                    tool_name="gamma",
                    person_id=linked.id,
                    relationship_type=PERSON_REL_MAINTAINER,
                    source="test",
                    verification_status=AUTHOR_CLAIM_VERIFIED,
                    expires_at=naive_now - timedelta(hours=1),
                ),
            ]
        )
        session.flush()
        payload = catalog_statistics.build_snapshot(session, now=now)

    metrics = payload["relationshipMetrics"]
    assert metrics["tools"] == {"verifiedAuthors": 1, "verifiedMaintainers": 1}
    assert metrics["people"] == {
        "withAnyCurrentRelationship": 1,
        "withAnyVerifiedRelationship": 1,
        "verifiedAuthors": 1,
        "verifiedMaintainers": 1,
        "identityOnly": 1,
    }
    assert metrics["rows"] == {"total": 3, "verified": 2, "stale": 1}
    assert metrics["newlyVerifiedTools"]["last24Hours"] == {"all": 1, "authors": 1, "maintainers": 0}
    assert metrics["newlyVerifiedTools"]["last7Days"] == {"all": 2, "authors": 1, "maintainers": 1}
    assert metrics["evidenceFreshness"] == {"active": 1, "expired": 1, "expiringWithin72Hours": 1, "withdrawn": 0}
    assert identity_only.id != linked.id


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


def _seed_every_branch(session, now):
    """Seed one dataset that reaches every quantity build_snapshot counts.

    ``test_the_snapshot_payload_matches_the_recorded_golden_document`` compares
    the whole payload against a file generated from this seed, so a change to
    how the snapshot is assembled has to show up as a reviewed diff in that
    file rather than as a silently different number on /statistics.
    """
    naive_now = now.replace(tzinfo=None)
    _tool(
        session,
        "complete",
        {
            "title": "Complete",
            "description": "Fully described",
            "url": "https://complete.example",
            "tool_type": "web app",
            "repository": "https://git.example/complete",
            "user_docs_url": "https://docs.example/complete",
            "author": [{"name": "Ada"}],
            "created_date": "2024-02-01T00:00:00Z",
            "modified_date": "2026-08-10T00:00:00Z",
        },
    )
    _tool(
        session,
        "sparse",
        {
            "title": "Sparse",
            "tool_type": "bot",
            "created_date": "2023-06-01",
            "modified_date": "2026-05-01",
        },
    )
    _tool(
        session,
        "deprecated",
        {
            "title": "Deprecated",
            "description": "Retired",
            "url": "https://deprecated.example",
            "deprecated": True,
            "author": [{"name": "Grace"}],
            "created_date": "2022-01-01",
            "modified_date": "2025-12-01",
        },
    )
    _tool(
        session,
        "experimental",
        {
            "title": "Experimental",
            "experimental": True,
            "tool_type": "web app",
            "created": "2021-03-03",
            "modified": "2021-03-03",
        },
    )
    _tool(session, "undated", {"title": "Undated", "created_date": "not-a-date"})
    # Sourced from a wiki so both lens documents are pinned with something in
    # them; source is what decides which lens a record is counted under, and
    # every other counter reads a record field and ignores it.
    _tool(
        session,
        "ancient",
        {
            "title": "Ancient",
            "tool_type": "",
            "created_date": "2015-05-05",
            "modified_date": "2015-05-05",
        },
        source=SOURCE_WIKI_USERSCRIPT,
    )

    stable = people_index.ensure_person(session, display_name="Ada", wikimedia_global_user_id="11", source="test")
    # A handle only counts as publishable when it came from a trusted public
    # source, which is what makes "grace" resolvable as a verified handle.
    handle = people_index.ensure_person(session, display_name="Grace", wiki_username="grace", source="toolhub_oauth")
    # Publishable, but attached to no tool: the identityOnly branch.
    people_index.ensure_person(session, display_name="Orphan", wikimedia_global_user_id="12", source="test")
    session.flush()

    session.add_all(
        [
            # Current verified author: the tool, the person and the row all count.
            ToolPersonRelationship(
                tool_name="complete",
                person_id=stable.id,
                relationship_type=PERSON_REL_AUTHOR,
                verification_status=AUTHOR_CLAIM_VERIFIED,
                verified_at=naive_now - timedelta(hours=2),
            ),
            # Verified inside the 7-day window but outside 24 hours.
            ToolPersonRelationship(
                tool_name="sparse",
                person_id=stable.id,
                relationship_type=PERSON_REL_MAINTAINER,
                verification_status=AUTHOR_CLAIM_VERIFIED,
                verified_at=naive_now - timedelta(days=3),
            ),
            # Verified but expired, which reads as stale rather than verified.
            ToolPersonRelationship(
                tool_name="deprecated",
                person_id=handle.id,
                relationship_type=PERSON_REL_AUTHOR,
                verification_status=AUTHOR_CLAIM_VERIFIED,
                verified_at=naive_now - timedelta(days=40),
                expires_at=naive_now - timedelta(days=1),
            ),
            ToolPersonRelationship(
                tool_name="experimental",
                person_id=handle.id,
                relationship_type=PERSON_REL_AUTHOR,
            ),
            # A row for a tool the catalog no longer carries is skipped.
            ToolPersonRelationship(
                tool_name="vanished",
                person_id=stable.id,
                relationship_type=PERSON_REL_MAINTAINER,
                verification_status=AUTHOR_CLAIM_VERIFIED,
            ),
        ]
    )
    session.add_all(
        [
            ToolRelationshipEvidence(tool_name="complete", person_id=stable.id, relationship_type=PERSON_REL_AUTHOR),
            ToolRelationshipEvidence(
                tool_name="sparse",
                person_id=stable.id,
                relationship_type=PERSON_REL_MAINTAINER,
                expires_at=naive_now - timedelta(hours=1),
            ),
            ToolRelationshipEvidence(
                tool_name="deprecated",
                person_id=handle.id,
                relationship_type=PERSON_REL_AUTHOR,
                expires_at=naive_now + timedelta(hours=12),
            ),
            ToolRelationshipEvidence(
                tool_name="experimental",
                person_id=handle.id,
                relationship_type=PERSON_REL_AUTHOR,
                withdrawn_at=naive_now - timedelta(days=2),
            ),
            # Evidence for a tool outside the catalog must not be counted.
            ToolRelationshipEvidence(tool_name="vanished", person_id=stable.id, relationship_type=PERSON_REL_AUTHOR),
        ]
    )

    _label(session, "Ada", tool_name="complete")
    _label(session, "Ambiguous", tool_name="sparse")
    _label(session, "Grace", tool_name="deprecated")
    _label(session, "Someone Unfindable", tool_name="experimental")
    _label(session, "lonelyhandle", tool_name="undated")
    _label(session, "Vanished Author", tool_name="vanished")
    expired = UnresolvedAttributionEvidence(
        tool_name="ancient",
        observed_label="Expired",
        normalized_label="expired",
        relationship_type=PERSON_REL_AUTHOR,
        source="test",
        expires_at=naive_now - timedelta(days=1),
    )
    session.add(expired)
    _account(session, "1", "Ada")
    _account(session, "2", "Ambiguous")
    _account(session, "3", "Ambiguous")

    source_valid = ToolinfoSource(url="https://feeds.example/valid.json", valid=True, item_count=12)
    source_broken = ToolinfoSource(url="https://feeds.example/broken.json", valid=False, item_count=0)
    source_unchecked = ToolinfoSource(url="https://feeds.example/unchecked.json", valid=True, item_count=3)
    session.add_all([source_valid, source_broken, source_unchecked])
    session.flush()
    session.add_all(
        [
            ToolinfoSourceAttestation(source_id=source_valid.id, status="verified", classification="official"),
            ToolinfoSourceAttestation(source_id=source_broken.id, status="unverified", classification="community"),
        ]
    )
    session.add_all(
        [
            ToolinfoAuthorBinding(
                source_id=source_valid.id, normalized_label="ada", person_id=stable.id, status="bound", method="handle"
            ),
            ToolinfoAuthorBinding(source_id=source_valid.id, normalized_label="grace", status="unresolved"),
            ToolinfoAuthorBinding(
                source_id=source_broken.id,
                normalized_label="withdrawn",
                status="bound",
                method="handle",
                withdrawn_at=naive_now - timedelta(days=1),
            ),
        ]
    )
    session.flush()


GOLDEN_SNAPSHOT = Path(__file__).with_name("fixtures") / "catalog_statistics_snapshot.json"


def test_the_snapshot_payload_matches_the_recorded_golden_document():
    """The whole payload is pinned, not a handful of keys.

    build_snapshot answers roughly forty separate questions about the catalog.
    Asserting a few of them leaves the rest free to drift during a refactor,
    which is exactly what happened to the memory profile of this function. The
    recorded document is the oracle: regenerate it deliberately when a number
    is meant to change, and never to make a test pass.
    """
    now = datetime(2026, 8, 25, 12, tzinfo=UTC)
    with db.session_scope() as session:
        _seed_every_branch(session, now)
        payload = catalog_statistics.build_snapshot(session, now=now)

    if os.environ.get("UPDATE_GOLDEN_SNAPSHOT") == "1":
        # Tab indentation because prettier owns JSON formatting in this repo,
        # so regeneration stays a diff of numbers rather than of whitespace.
        GOLDEN_SNAPSHOT.write_text(json.dumps(payload, indent="\t", sort_keys=True) + "\n")

    assert payload == json.loads(GOLDEN_SNAPSHOT.read_text())


def _every_lens():
    """The three documents built from the golden seed, keyed by lens name."""
    now = datetime(2026, 8, 25, 12, tzinfo=UTC)
    with db.session_scope() as session:
        _seed_every_branch(session, now)
        payload = catalog_statistics.build_snapshot(session, now=now)
    return {"all": payload, "catalog": payload["lenses"]["catalog"], "wiki": payload["lenses"]["wiki"]}


def test_the_two_lanes_partition_the_catalog_rather_than_overlapping_it():
    """Every tool is counted once in `all` and once in exactly one lane.

    A record's lane comes from its source column, so the two narrow documents
    have to add back up to the wide one. If they ever stop, a tool has either
    been dropped from both lanes or double-counted in one.
    """
    lenses = _every_lens()
    assert lenses["catalog"]["catalog"]["totalTools"] + lenses["wiki"]["catalog"]["totalTools"] == (
        lenses["all"]["catalog"]["totalTools"]
    )
    assert lenses["catalog"]["identities"]["unresolvedTools"] + lenses["wiki"]["identities"]["unresolvedTools"] == (
        lenses["all"]["identities"]["unresolvedTools"]
    )


def test_a_lens_recomputes_coverage_instead_of_reporting_the_whole_catalogs():
    """Percentages are the reason a lens cannot be a client-side filter.

    Sums narrow by addition; a coverage ratio does not. The registered lane
    describes four of its five tools where the wiki lane describes none of
    its one, and neither number can be recovered from the combined 33%.
    """
    lenses = _every_lens()
    assert lenses["all"]["catalog"]["coreMetadataComplete"] == {"count": 2, "missingCount": 4, "percent": 33}
    assert lenses["catalog"]["catalog"]["coreMetadataComplete"] == {"count": 2, "missingCount": 3, "percent": 40}
    assert lenses["wiki"]["catalog"]["coreMetadataComplete"] == {"count": 0, "missingCount": 1, "percent": 0}
    per_lens = {name: {row["key"]: row["percent"] for row in document["metadata"]} for name, document in lenses.items()}
    assert per_lens["all"]["description"] == 33
    assert per_lens["catalog"]["description"] == 40
    assert per_lens["wiki"]["description"] == 0


def test_a_lens_recounts_verified_relationships_against_its_own_tools():
    """Relationship evidence is looked up per lens, not sliced afterwards.

    The seeded verified author and maintainer both sit on registered tools,
    so the wiki lane has to report zero of each and count its publishable
    people as identity-only -- they hold no relationship to anything it shows.
    """
    lenses = _every_lens()
    assert lenses["catalog"]["catalog"]["verifiedAuthors"]["count"] == 1
    assert lenses["catalog"]["catalog"]["verifiedMaintainers"]["count"] == 1
    assert lenses["wiki"]["catalog"]["verifiedAuthors"] == {"count": 0, "missingCount": 1, "percent": 0}
    assert lenses["wiki"]["catalog"]["verifiedMaintainers"] == {"count": 0, "missingCount": 1, "percent": 0}
    assert lenses["wiki"]["relationshipMetrics"]["rows"] == {"stale": 0, "total": 0, "verified": 0}
    assert lenses["wiki"]["relationshipMetrics"]["people"]["identityOnly"] == (
        lenses["wiki"]["identities"]["publishablePeople"]
    )


def test_a_lens_narrows_the_unresolved_vocabulary_to_the_tools_it_shows():
    """The funnel follows the labels, and labels arrive attached to tools.

    Every seeded author token sits on a registered tool, so the wiki lane's
    funnel is empty rather than a copy of the combined one. `sourceBindings`
    is the documented exception: a binding names a feed, never a tool.
    """
    lenses = _every_lens()
    assert lenses["catalog"]["attribution"]["distinctLabels"] == 5
    assert lenses["wiki"]["attribution"]["distinctLabels"] == 0
    assert lenses["wiki"]["attribution"]["noLocalMatch"] == 0
    assert lenses["wiki"]["identities"]["unresolvedLabels"] == 0
    assert lenses["wiki"]["attribution"]["sourceBindings"] == lenses["all"]["attribution"]["sourceBindings"]


def test_a_label_on_a_tool_the_catalog_no_longer_holds_is_left_out():
    """An orphaned evidence row is backlog, not vocabulary.

    The seed carries a label for `vanished`, a tool no lens contains. It used
    to inflate the combined funnel because the label branch was the one place
    that ignored the catalog; both lanes agreeing to drop it is what makes
    their counts add up to the wide document's.
    """
    lenses = _every_lens()
    assert lenses["all"]["identities"]["unresolvedLabels"] == 5
    labels = lenses["catalog"]["attribution"]["distinctLabels"] + lenses["wiki"]["attribution"]["distinctLabels"]
    assert labels == lenses["all"]["attribution"]["distinctLabels"]


def test_the_definitions_read_the_same_under_every_lens():
    """Narrowing the catalog changes the numbers, never what they are called."""
    lenses = _every_lens()
    assert lenses["catalog"]["definitions"] == lenses["all"]["definitions"]
    assert lenses["wiki"]["definitions"] == lenses["all"]["definitions"]
    assert lenses["wiki"]["sources"] == lenses["all"]["sources"]


def test_a_request_serves_a_stale_snapshot_rather_than_rebuilding_it():
    """Past the freshness window is not a reason to make a visitor wait.

    Rebuilding inside the request is what got the web service OOM-killed, and
    with a 15-minute window and a 6-hour precompute it was happening to almost
    everybody. The stored copy is served instead; /statistics shows its
    `generatedAt`, so the staleness is on the page rather than hidden.
    """
    with db.session_scope() as session:
        _tool(session, "t", {"title": "T"})
    catalog_statistics.snapshot()
    with db.session_scope() as session:
        _tool(session, "second", {"title": "Second"})
        row = session.get(ApiCacheMeta, catalog_statistics.SNAPSHOT_KEY)
        row.updated_at = utcnow() - catalog_statistics.SNAPSHOT_MAX_AGE - timedelta(minutes=1)

    payload = catalog_statistics.snapshot()

    assert payload["catalog"]["totalTools"] == 1


def test_a_request_rebuilds_once_the_stored_snapshot_passes_the_stale_limit():
    """Serving stale forever would hide a refresh job that stopped running."""
    with db.session_scope() as session:
        _tool(session, "t", {"title": "T"})
    catalog_statistics.snapshot()
    with db.session_scope() as session:
        _tool(session, "second", {"title": "Second"})
        row = session.get(ApiCacheMeta, catalog_statistics.SNAPSHOT_KEY)
        row.updated_at = utcnow() - catalog_statistics.SNAPSHOT_STALE_LIMIT - timedelta(minutes=1)

    payload = catalog_statistics.snapshot()

    assert payload["catalog"]["totalTools"] == 2


def test_refresh_rebuilds_and_stores_the_snapshot():
    with db.session_scope() as session:
        _tool(session, "t", {"title": "T"})

    report = catalog_statistics.refresh()

    assert report["stored"] is True
    assert report["totalTools"] == 1
    with db.session_scope() as session:
        row = session.get(ApiCacheMeta, catalog_statistics.SNAPSHOT_KEY)
        assert json.loads(row.value)["generatedAt"] == report["generatedAt"]


def test_refresh_declines_instead_of_rebuilding_a_payload_it_cannot_store(monkeypatch):
    @contextlib.contextmanager
    def never_acquires(_name, *, timeout_seconds=0):  # noqa: ARG001
        yield False

    monkeypatch.setattr(catalog_statistics.db, "advisory_lock", never_acquires)
    with db.session_scope() as session:
        _tool(session, "t", {"title": "T"})

    report = catalog_statistics.refresh()

    assert report["stored"] is False
    with db.session_scope() as session:
        assert session.get(ApiCacheMeta, catalog_statistics.SNAPSHOT_KEY) is None


def test_the_refresh_job_is_scheduled_inside_the_freshness_window_it_promises():
    """The two numbers are a contract, and they used to be six hours apart.

    SNAPSHOT_MAX_AGE said fifteen minutes; the only job that precomputed the
    snapshot ran every six hours. Nothing connected them, so the endpoint
    quietly moved the rebuild onto the request path. Read the schedule from
    jobs.yaml, which is the same file Toolforge and /workers read.
    """
    jobs = {job.name: job for job in job_catalog.load()}
    refresh_job = jobs["statistics-refresh"]

    interval = timedelta(minutes=refresh_job.expected_interval_minutes)
    assert timedelta() < interval <= catalog_statistics.SNAPSHOT_MAX_AGE


def _described(payload):
    """How many tools the snapshot reports as carrying a description."""
    return next(row["count"] for row in payload["metadata"] if row["key"] == "description")


def test_completeness_is_measured_on_what_the_site_shows_not_on_what_a_source_said():
    """Inferred and locally corrected fields must move these counts.

    The scan read `CanonicalToolCache.record` alone, which is the upstream
    payload before any local layer applies. Descriptions written by the
    inference worker are published through the projection, so the described
    count sat at exactly the number of tools that arrived with one and could
    not move however many thousands the worker added -- the one number that
    reports whether the worker is worth running was blind to it.
    """
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)
    with db.session_scope() as session:
        _tool(session, "inferred", {"title": "Inferred"}, source=SOURCE_WIKI_USERSCRIPT)
        _tool(session, "bare", {"title": "Bare"}, source=SOURCE_WIKI_USERSCRIPT)
        session.add(
            CatalogToolProjection(
                tool_name="inferred",
                effective_record={"name": "inferred", "title": "Inferred", "description": "Written by the worker"},
            )
        )
        session.flush()
        payload = catalog_statistics.build_snapshot(session, now=now)

    assert payload["catalog"]["totalTools"] == 2
    assert _described(payload) == 1


def test_a_tool_with_no_projection_row_still_counts_from_its_canonical_record():
    """The join is outer: a tool the projection has not reached is not erased."""
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)
    with db.session_scope() as session:
        _tool(session, "unprojected", {"title": "Unprojected", "description": "From upstream"})
        session.flush()
        payload = catalog_statistics.build_snapshot(session, now=now)

    assert payload["catalog"]["totalTools"] == 1
    assert _described(payload) == 1
