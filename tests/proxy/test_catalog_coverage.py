# SPDX-License-Identifier: GPL-3.0-or-later
"""Field coverage attributes every filled value to exactly one source bucket."""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import catalog_coverage, db  # noqa: E402
from backend.catalog_projection import (  # noqa: E402
    PROJECTED_FIELDS,
    SOURCE_CANONICAL,
    SOURCE_CONFIDENCE,
    SOURCE_CURATION,
    SOURCE_INFERENCE,
    SOURCE_REPOSITORY,
    STATUS_READY,
)
from backend.models import CatalogToolProjection  # noqa: E402

NOW = datetime(2026, 8, 31, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()


def _entry(source, value="v", *, effective=False):
    return {
        "value": value,
        "source": source,
        "sourceUrl": "",
        "observedAt": "2026-08-30T00:00:00Z",
        "confidence": SOURCE_CONFIDENCE[source],
        "effective": effective,
        "valid": True,
        "state": "accepted",
    }


def _projection(session, name, provenance, status=STATUS_READY):
    session.add(
        CatalogToolProjection(
            tool_name=name,
            effective_record={"name": name},
            provenance=provenance,
            status=status,
        )
    )


def test_every_projection_source_maps_to_a_bucket():
    """An unmapped source would be counted as filled while belonging nowhere."""
    assert set(catalog_coverage.BUCKET_BY_SOURCE) == set(SOURCE_CONFIDENCE)
    assert set(catalog_coverage.BUCKET_BY_SOURCE.values()) <= set(catalog_coverage.BUCKETS)


def test_buckets_sum_to_the_filled_total():
    with db.session_scope() as session:
        _projection(session, "a", {"title": [_entry(SOURCE_CANONICAL, effective=True)]})
        _projection(session, "b", {"title": [_entry(SOURCE_CURATION, effective=True)]})
        _projection(session, "c", {"description": [_entry(SOURCE_REPOSITORY, effective=True)]})
    with db.session_scope() as session:
        payload = catalog_coverage.build_snapshot(session, now=NOW)

    assert payload["tools"] == 3
    title = next(item for item in payload["fields"] if item["field"] == "title")
    assert title["filled"] == 2
    assert sum(title["primary"].values()) == title["filled"]
    assert title["primary"]["toolinfo"] == 1
    assert title["primary"]["human"] == 1
    assert title["missing"] == 1

    description = next(item for item in payload["fields"] if item["field"] == "description")
    assert description["primary"]["code"] == 1

    assert payload["overall"]["filled"] == sum(item["filled"] for item in payload["fields"])
    assert payload["overall"]["slots"] == 3 * len(PROJECTED_FIELDS)


def test_inference_that_lost_a_field_is_reported_as_shadowed_not_filled():
    """The LLM is fill-only, so a field it offered but did not win is not its own."""
    with db.session_scope() as session:
        _projection(
            session,
            "a",
            {
                "description": [
                    _entry(SOURCE_CANONICAL, "declared", effective=True),
                    _entry(SOURCE_INFERENCE, "guessed"),
                ]
            },
        )
    with db.session_scope() as session:
        payload = catalog_coverage.build_snapshot(session, now=NOW)

    description = next(item for item in payload["fields"] if item["field"] == "description")
    assert description["filled"] == 1
    assert description["primary"]["toolinfo"] == 1
    assert description["primary"]["ai"] == 0
    assert description["shadowed"]["ai"] == 1


def test_a_list_field_merged_from_two_sources_counts_once():
    """Attributing a merged list to every contributor would overshoot the total."""
    with db.session_scope() as session:
        _projection(
            session,
            "a",
            {
                "keywords": [
                    _entry(SOURCE_CANONICAL, "alpha", effective=True),
                    _entry(SOURCE_REPOSITORY, "beta", effective=True),
                ]
            },
        )
    with db.session_scope() as session:
        payload = catalog_coverage.build_snapshot(session, now=NOW)

    keywords = next(item for item in payload["fields"] if item["field"] == "keywords")
    assert keywords["filled"] == 1
    assert sum(keywords["primary"].values()) == 1
    # Highest confidence wins the attribution; the other is still reported.
    assert keywords["primary"]["toolinfo"] == 1
    assert keywords["contributing"]["code"] == 1
    assert keywords["contributing"]["toolinfo"] == 1


def test_unready_projections_are_excluded_from_the_denominator():
    """A pending row has no provenance yet and would read as a catalog-wide hole."""
    with db.session_scope() as session:
        _projection(session, "ready", {"title": [_entry(SOURCE_CANONICAL, effective=True)]})
        _projection(session, "pending", {}, status="pending")
    with db.session_scope() as session:
        payload = catalog_coverage.build_snapshot(session, now=NOW)

    assert payload["tools"] == 1
    assert payload["pendingTools"] == 1
    title = next(item for item in payload["fields"] if item["field"] == "title")
    assert title["percent"] == 100.0


def test_coverage_endpoint_is_publicly_cacheable_and_serves_the_stored_snapshot():
    """The page reads one cached document; a request never pays for the pass twice."""
    app = Flask(__name__)
    backend.register(app, db_url="sqlite://", secret_key="test-secret")
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    with db.session_scope() as session:
        _projection(session, "one", {"title": [_entry(SOURCE_CURATION, effective=True)]})

    response = app.test_client().get("/v1/coverage/")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["tools"] == 1
    assert payload["overall"]["primary"]["human"] == 1
    assert response.headers["Cache-Control"].startswith("public, max-age=300")
    etag = response.headers["ETag"]
    assert app.test_client().get("/v1/coverage/", headers={"If-None-Match": etag}).status_code == 304
