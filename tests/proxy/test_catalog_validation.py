# SPDX-License-Identifier: GPL-3.0-or-later
"""Background reachability validation of effective catalog URLs."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import catalog_validation, db, outbound  # noqa: E402
from backend.models import CatalogToolProjection  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def test_parsed_accepts_naive_aware_and_z_suffixed_timestamps_and_rejects_garbage():
    assert catalog_validation._parsed("") is None
    assert catalog_validation._parsed("not-a-real-date") is None
    assert catalog_validation._parsed("2024-01-02T00:00:00") == datetime(2024, 1, 2)
    assert catalog_validation._parsed("2024-01-02T00:00:00Z") == datetime(2024, 1, 2)
    assert catalog_validation._parsed("2024-01-02T02:00:00+02:00") == datetime(2024, 1, 2)


def test_a_recently_checked_url_is_not_a_candidate_but_an_unchecked_field_is():
    now = datetime.now(tz=UTC)
    with db.session_scope() as s:
        s.add(
            CatalogToolProjection(
                tool_name="alpha",
                effective_record={
                    "url": "https://alpha.example",
                    "repository": "https://code.example/alpha",
                },
                validation={
                    "url": {
                        "checkedValue": "https://alpha.example",
                        "checkedAt": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
                    }
                },
            )
        )

    total, candidates = catalog_validation._candidate_rows(10)

    assert total == 1
    assert candidates == [("alpha", "repository", "https://code.example/alpha")]


def test_a_stale_check_and_a_changed_value_are_both_candidates():
    now = datetime.now(tz=UTC)
    stale_at = now - catalog_validation.FRESH_FOR - timedelta(days=1)
    with db.session_scope() as s:
        s.add(
            CatalogToolProjection(
                tool_name="alpha",
                effective_record={
                    "url": "https://alpha.example",
                    "repository": "https://code.example/alpha",
                },
                validation={
                    # Checked, but past FRESH_FOR: still a candidate.
                    "url": {
                        "checkedValue": "https://alpha.example",
                        "checkedAt": stale_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
                    },
                    # Checked recently, but the value moved since: also a candidate.
                    "repository": {
                        "checkedValue": "https://old.example/alpha",
                        "checkedAt": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
                    },
                },
            )
        )

    total, candidates = catalog_validation._candidate_rows(10)

    assert total == 2
    assert {(field, value) for _tool, field, value in candidates} == {
        ("repository", "https://code.example/alpha"),
        ("url", "https://alpha.example"),
    }


def test_candidate_rows_are_bounded_by_the_limit():
    with db.session_scope() as s:
        s.add(CatalogToolProjection(tool_name="alpha", effective_record={"url": "https://alpha.example"}))
        s.add(CatalogToolProjection(tool_name="beta", effective_record={"url": "https://beta.example"}))

    total, candidates = catalog_validation._candidate_rows(1)

    assert total == 2
    assert len(candidates) == 1


def test_record_ignores_a_projection_deleted_after_the_probe_started():
    with db.session_scope() as s:
        s.add(CatalogToolProjection(tool_name="alpha", effective_record={"url": "https://alpha.example"}))
    with db.session_scope() as s:
        s.delete(s.get(CatalogToolProjection, "alpha"))

    # Must not raise even though the row is gone.
    catalog_validation._record("alpha", "url", "https://alpha.example", {"reachable": True})

    with db.session_scope() as s:
        assert s.get(CatalogToolProjection, "alpha") is None


def test_record_ignores_a_field_value_that_moved_on_before_the_probe_returned():
    with db.session_scope() as s:
        s.add(
            CatalogToolProjection(tool_name="alpha", effective_record={"url": "https://alpha.example"}, validation={})
        )
    with db.session_scope() as s:
        row = s.get(CatalogToolProjection, "alpha")
        row.effective_record = {"url": "https://alpha.example/moved"}

    catalog_validation._record("alpha", "url", "https://alpha.example", {"reachable": True})

    with db.session_scope() as s:
        assert s.get(CatalogToolProjection, "alpha").validation == {}


def test_refresh_candidates_records_both_reachable_and_failed_probes(monkeypatch):
    with db.session_scope() as s:
        s.add(
            CatalogToolProjection(
                tool_name="alpha",
                effective_record={
                    "url": "https://alpha.example",
                    "repository": "https://code.example/alpha",
                },
            )
        )

    def fake_probe(_session, url, *, caller):  # noqa: ARG001
        if url.startswith("https://code.example"):
            raise requests.ConnectionError("boom")
        return outbound.ProbeResponse(url=url, status_code=200, content_type="text/html")

    monkeypatch.setattr(outbound, "probe_reachable", fake_probe)

    summary = catalog_validation.refresh_candidates()

    assert summary == {"candidates": 2, "processed": 2, "reachable": 1, "errors": 1}
    with db.session_scope() as s:
        row = s.get(CatalogToolProjection, "alpha")
        assert row.validation["url"]["reachable"] is True
        assert row.validation["url"]["statusCode"] == 200
        assert row.validation["repository"]["reachable"] is False
        assert "boom" in row.validation["repository"]["lastError"]


def test_refresh_candidates_bounds_processing_by_limit(monkeypatch):
    with db.session_scope() as s:
        s.add(CatalogToolProjection(tool_name="alpha", effective_record={"url": "https://alpha.example"}))
        s.add(CatalogToolProjection(tool_name="beta", effective_record={"url": "https://beta.example"}))

    monkeypatch.setattr(
        outbound,
        "probe_reachable",
        lambda _session, url, *, caller: outbound.ProbeResponse(url=url, status_code=200, content_type="text/html"),  # noqa: ARG005
    )

    summary = catalog_validation.refresh_candidates(limit=1)

    assert summary == {"candidates": 2, "processed": 1, "reachable": 1, "errors": 0}
