# SPDX-License-Identifier: GPL-3.0-or-later
"""Catalog-quality statistics use explicit, stable denominators."""

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
    CanonicalToolCache,
    ToolPersonRelationship,
    ToolinfoSource,
    UnresolvedAttributionEvidence,
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
