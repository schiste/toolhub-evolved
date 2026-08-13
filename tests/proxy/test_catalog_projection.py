"""Integration tests for the Evolved-local catalog projection."""

import contextlib
import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import catalog_projection, catalog_validation, db, outbound  # noqa: E402
from backend.models import (  # noqa: E402
    CanonicalToolCache,
    CatalogCuration,
    CatalogFacetValue,
    CatalogToolProjection,
    RepositoryAnalysisState,
    SourceAnalysisReport,
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


def test_localized_title_dict_prefers_en_or_mul_then_falls_back_to_any_value():
    with db.session_scope() as s:
        s.add(_canonical("alpha", title={"mul": "Universal Title"}))
        s.add(_canonical("beta", title={"xx": "", "yy": "Yet another title"}))

    catalog_projection.refresh_tool_names(["alpha", "beta"])

    with db.session_scope() as s:
        alpha_search_text = s.get(CatalogToolProjection, "alpha").search_text
        beta_search_text = s.get(CatalogToolProjection, "beta").search_text
    assert "universal title" in alpha_search_text
    assert "yet another title" in beta_search_text


def test_url_validation_flags_empty_and_credentialed_urls():
    empty_patch, empty_errors = catalog_projection.validate_curation_patch({"url": ""})
    assert empty_patch == {"url": ""}
    assert empty_errors == []

    creds_patch, creds_errors = catalog_projection.validate_curation_patch(
        {"url": "https://user:pass@host.example/"}
    )
    assert creds_patch == {}
    assert creds_errors == [{"field": "url", "message": "Credentials are not allowed in public URLs."}]


def test_validate_curation_patch_rejects_non_dict_non_list_and_empty_input():
    patch, errors = catalog_projection.validate_curation_patch("not-a-dict")
    assert patch == {}
    assert errors == [{"field": "patch", "message": "patch must be an object"}]

    list_patch, list_errors = catalog_projection.validate_curation_patch({"keywords": "not-a-list"})
    assert list_patch == {}
    assert list_errors == [{"field": "keywords", "message": "value must be a list"}]

    empty_patch, empty_errors = catalog_projection.validate_curation_patch({})
    assert empty_patch == {}
    assert empty_errors == [{"field": "patch", "message": "patch must contain at least one supported field"}]


def test_validate_curation_patch_accepts_scalar_non_url_fields():
    patch, errors = catalog_projection.validate_curation_patch({"title": "  New   Title  "})
    assert patch == {"title": "New Title"}
    assert errors == []


def test_same_origin_toolinfo_requires_both_urls():
    assert catalog_projection._same_origin_toolinfo("", "https://alpha.example/toolinfo.json") is False  # noqa: SLF001
    assert catalog_projection._same_origin_toolinfo("https://alpha.example", "") is False  # noqa: SLF001


def test_latest_reports_skips_rows_with_blank_tool_name():
    now = utcnow()
    with db.session_scope() as s:
        user = User(wm_sub="reviewer", username="Reviewer")
        s.add(user)
        s.flush()
        s.add(
            SourceAnalysisReport(
                user_id=user.id,
                tool_name="",
                report={"suggestions": {"toolinfoPatch": {"title": "Blank name"}}},
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )
        s.add(
            SourceAnalysisReport(
                user_id=user.id,
                tool_name="alpha",
                report={"suggestions": {"toolinfoPatch": {"title": "Alpha report"}}},
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    with db.session_scope() as s:
        reports = catalog_projection._latest_reports(s, ["", "alpha"])  # noqa: SLF001

    assert set(reports) == {"alpha"}


def test_sources_by_tool_skips_non_dict_evidence_payloads():
    now = utcnow()
    with db.session_scope() as s:
        user = User(wm_sub="reviewer", username="Reviewer")
        s.add(user)
        s.flush()
        # A canonical row whose record is present but not a dict (defensive malformed data).
        s.add(
            CanonicalToolCache(
                tool_name="alpha",
                record="",
                source_url="https://toolhub.wikimedia.org/api/tools/alpha/",
                fetched_at=now,
                expires_at=now,
                stale_until=now,
            )
        )

        source = ToolinfoSource(url="https://alpha.example/toolinfo.json", valid=True, last_fetched_at=now)
        s.add(source)
        s.flush()
        s.add(
            ToolinfoSourceItem(
                tool_name="alpha",
                source_id=source.id,
                source_url=source.url,
                payload=None,
                last_seen_at=now,
            )
        )
        s.add(
            CatalogCuration(
                tool_name="alpha",
                created_by_user_id=user.id,
                reviewed_by_user_id=user.id,
                patch=["not", "a", "dict"],
                rationale="Malformed curation payload.",
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    with db.session_scope() as s:
        sources = catalog_projection._sources_by_tool(s, ["alpha"])  # noqa: SLF001

    assert sources.get("alpha", []) == []


def test_discovery_without_a_checked_at_timestamp_is_not_recorded_as_observed():
    with db.session_scope() as s:
        s.add(_canonical("alpha"))
        s.add(
            ToolinfoDiscovery(
                tool_name="alpha",
                tool_url="https://alpha.example",
                toolinfo_url="https://alpha.example/toolinfo.json",
                status="found",
                payload={"technology_used": ["Rust"]},
                checked_at=None,
            )
        )

    catalog_projection.refresh_tool_names(["alpha"])

    payload = catalog_projection.projection_payload("alpha")
    assert payload["record"]["technology_used"] == ["Rust"]
    assert "self_hosted_toolinfo" not in payload["sourceTimestamps"]


def test_invalid_curation_url_without_other_evidence_leaves_field_unset():
    now = utcnow()
    with db.session_scope() as s:
        s.add(_canonical("alpha"))
        user = User(wm_sub="reviewer", username="Reviewer")
        s.add(user)
        s.flush()
        s.add(
            CatalogCuration(
                tool_name="alpha",
                created_by_user_id=user.id,
                reviewed_by_user_id=user.id,
                patch={"url": "javascript:alert(1)"},
                rationale="Bad correction.",
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    catalog_projection.refresh_tool_names(["alpha"])

    payload = catalog_projection.projection_payload("alpha")
    assert "url" not in payload["record"]
    assert payload["validation"]["url"]["state"] == "missing"
    evidence = payload["provenance"]["url"]
    assert [item["source"] for item in evidence] == ["evolved_curation"]
    assert evidence[0]["valid"] is False


def test_mark_failures_records_error_and_backoff_then_swallows_session_errors(monkeypatch):
    catalog_projection._mark_failures(["alpha"], ValueError("boom"))  # noqa: SLF001

    with db.session_scope() as s:
        row = s.get(CatalogToolProjection, "alpha")
        assert row.status == catalog_projection.STATUS_ERROR
        assert row.attempts == 1
        assert row.last_error == "boom"
        assert row.next_attempt_at is not None
        assert row.next_attempt_at > utcnow()

    catalog_projection._mark_failures(["alpha"], ValueError("boom again"))  # noqa: SLF001
    with db.session_scope() as s:
        assert s.get(CatalogToolProjection, "alpha").attempts == 2

    @contextlib.contextmanager
    def _raise_session_scope():
        raise SQLAlchemyError("session boom")
        yield  # pragma: no cover - unreachable, contextmanager requires a yield

    monkeypatch.setattr(catalog_projection.db, "session_scope", _raise_session_scope)

    catalog_projection._mark_failures(["alpha"], ValueError("swallowed"))  # noqa: SLF001 - must not raise


def test_refresh_batch_marks_failures_when_assembly_raises(monkeypatch):
    with db.session_scope() as s:
        s.add(_canonical("alpha"))

    def _boom(_s, _names):
        msg = "boom"
        raise ValueError(msg)

    monkeypatch.setattr(catalog_projection, "_sources_by_tool", _boom)

    summary = catalog_projection.refresh_tool_names(["alpha"])

    assert summary == {"requested": 1, "refreshed": 0, "changed": 0, "errors": 1}
    with db.session_scope() as s:
        row = s.get(CatalogToolProjection, "alpha")
        assert row.status == catalog_projection.STATUS_ERROR
        assert "boom" in row.last_error


def test_refresh_batch_with_no_names_returns_zero_summary():
    assert catalog_projection._refresh_batch([]) == {  # noqa: SLF001
        "requested": 0,
        "refreshed": 0,
        "changed": 0,
        "errors": 0,
    }


def test_refresh_candidates_skips_tools_pending_backoff():
    with db.session_scope() as s:
        s.add(_canonical("alpha"))

    catalog_projection._mark_failures(["alpha"], ValueError("boom"))  # noqa: SLF001

    result = catalog_projection.refresh_candidates()

    assert result["candidates"] == 0
    assert result["refreshed"] == 0


def test_projection_payload_returns_none_for_a_blank_name():
    assert catalog_projection.projection_payload("") is None
    assert catalog_projection.projection_payload("   ") is None


def test_localized_text_falls_back_to_the_whole_value_when_every_candidate_is_blank():
    value = {"fr": "   "}
    assert catalog_projection._localized_text(value) == catalog_projection._clean_text(value)


def test_replace_facets_skips_a_value_whose_label_cleans_to_empty(monkeypatch):
    real_clean = catalog_projection._clean_text
    calls = {"n": 0}

    def flaky_clean(value):
        if value == "trigger":
            calls["n"] += 1
            return "kept" if calls["n"] == 1 else ""
        return real_clean(value)

    monkeypatch.setattr(catalog_projection, "_clean_text", flaky_clean)

    class RecordingSession:
        def __init__(self):
            self.added = []

        def execute(self, statement):
            return None

        def add(self, row):
            self.added.append(row)

    s = RecordingSession()
    catalog_projection._replace_facets(s, "gap-tool", {"keywords": ["trigger"]}, {}, utcnow())
    # The value passed _values' cleanliness filter but its label cleaned to
    # empty on the second pass, so no facet row may be recorded for it.
    assert calls["n"] == 2
    assert s.added == []
