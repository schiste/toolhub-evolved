"""Integration tests for the Evolved-local catalog projection."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import catalog_projection, catalog_validation, db, outbound  # noqa: E402
from backend.models import (  # noqa: E402
    CanonicalToolCache,
    CatalogCuration,
    CatalogFacetValue,
    CatalogToolProjection,
    ToolinfoDiscovery,
    ToolinfoSource,
    ToolinfoSourceItem,
    User,
    utcnow,
)
from backend.sync import REVIEW_APPROVED  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def _canonical(name, **fields):
    now = utcnow()
    return CanonicalToolCache(
        tool_name=name,
        record={"name": name, "title": "Official title", **fields},
        source_url=f"https://toolhub.wikimedia.org/api/tools/{name}/",
        fetched_at=now,
        expires_at=now,
        stale_until=now,
    )


def test_projection_preserves_invalid_official_evidence_and_merges_valid_sources():
    now = utcnow()
    with db.session_scope() as s:
        s.add(_canonical("alpha", url="javascript:alert(1)", technology_used=["Python"]))
        source = ToolinfoSource(url="https://alpha.example/toolinfo.json", valid=True, last_fetched_at=now)
        s.add(source)
        s.flush()
        s.add(
            ToolinfoSourceItem(
                tool_name="alpha",
                source_id=source.id,
                source_url=source.url,
                payload={"url": "https://alpha.example", "technology_used": ["Django"]},
                last_seen_at=now,
            )
        )

    summary = catalog_projection.refresh_tool_names(["alpha"])

    assert summary == {"requested": 1, "refreshed": 1, "changed": 1, "errors": 0}
    payload = catalog_projection.projection_payload("alpha")
    assert payload["record"]["url"] == "https://alpha.example"
    assert payload["record"]["technology_used"] == ["Python", "Django"]
    assert payload["provenance"]["url"][0]["valid"] is False
    assert payload["provenance"]["url"][0]["effective"] is False
    assert payload["validation"]["url"]["invalidEvidenceCount"] == 1
    with db.session_scope() as s:
        facets = {(row.field, row.value) for row in s.query(CatalogFacetValue).all()}
    assert facets >= {("technology", "python"), ("technology", "django")}


def test_approved_curation_is_only_source_that_replaces_valid_canonical_scalar():
    now = utcnow()
    with db.session_scope() as s:
        s.add(_canonical("alpha", url="https://official.example"))
        user = User(wm_sub="reviewer", username="Reviewer")
        s.add(user)
        s.flush()
        s.add(
            CatalogCuration(
                tool_name="alpha",
                created_by_user_id=user.id,
                reviewed_by_user_id=user.id,
                patch={"url": "https://corrected.example"},
                rationale="Official URL is obsolete.",
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    catalog_projection.refresh_tool_names(["alpha"])

    payload = catalog_projection.projection_payload("alpha")
    assert payload["record"]["url"] == "https://corrected.example"
    evidence = payload["provenance"]["url"]
    assert [item["source"] for item in evidence] == ["official_toolhub", "evolved_curation"]
    assert [item["effective"] for item in evidence] == [False, True]


def test_discovered_toolinfo_must_match_the_declared_tool_origin():
    with db.session_scope() as s:
        s.add(_canonical("alpha", technology_used=["Python"]))
        s.add(
            ToolinfoDiscovery(
                tool_name="alpha",
                tool_url="https://different.example",
                toolinfo_url="https://alpha.example/toolinfo.json",
                status="found",
                payload={"url": "https://different.example", "technology_used": ["Injected"]},
                checked_at=utcnow(),
            )
        )

    catalog_projection.refresh_tool_names(["alpha"])

    payload = catalog_projection.projection_payload("alpha")
    assert payload["record"]["technology_used"] == ["Python"]
    assert "self_hosted_toolinfo" not in payload["sourceTimestamps"]


def test_validate_curation_patch_bounds_fields_and_urls():
    patch, errors = catalog_projection.validate_curation_patch(
        {"name": "renamed", "url": "javascript:alert(1)", "keywords": ["one", "one", "two"]}
    )

    assert patch == {"keywords": ["one", "two"]}
    assert {item["field"] for item in errors} == {"name", "url"}


def test_candidate_repair_is_versioned_and_idempotent():
    with db.session_scope() as s:
        s.add(_canonical("alpha"))

    first = catalog_projection.refresh_candidates()
    second = catalog_projection.refresh_candidates()

    assert first["candidates"] == 1
    assert first["refreshed"] == 1
    assert second == {"candidates": 0, "requested": 0, "refreshed": 0, "changed": 0, "errors": 0}
    with db.session_scope() as s:
        assert s.get(CatalogToolProjection, "alpha").status == catalog_projection.STATUS_READY


def test_background_url_validation_survives_unchanged_projection_refresh(monkeypatch):
    with db.session_scope() as s:
        s.add(_canonical("alpha", url="https://alpha.example", repository="https://code.example/alpha"))
    catalog_projection.refresh_tool_names(["alpha"])
    monkeypatch.setattr(
        outbound,
        "probe_reachable",
        lambda _session, url, *, caller: outbound.ProbeResponse(url=url, status_code=200, content_type="text/html"),
    )

    summary = catalog_validation.refresh_candidates()
    catalog_projection.refresh_tool_names(["alpha"])

    assert summary == {"candidates": 2, "processed": 2, "reachable": 2, "errors": 0}
    payload = catalog_projection.projection_payload("alpha")
    assert payload["validation"]["url"]["reachable"] is True
    assert payload["validation"]["url"]["checkedValue"] == "https://alpha.example"
