# SPDX-License-Identifier: GPL-3.0-or-later
"""Background reachability validation of effective catalog URLs."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import catalog_validation, db, outbound, run_budget  # noqa: E402
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
    assert candidates == {"https://code.example/alpha": [("alpha", "repository", "https://code.example/alpha")]}


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
    assert {(field, value) for fields in candidates.values() for _tool, field, value in fields} == {
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



def _work(summary):
    """The summary without its timing, which is a real clock and not an assertion."""
    return {key: value for key, value in summary.items() if key not in {"spentSeconds", "budgeted"}}

def test_record_ignores_a_projection_deleted_after_the_probe_started():
    with db.session_scope() as s:
        s.add(CatalogToolProjection(tool_name="alpha", effective_record={"url": "https://alpha.example"}))
    with db.session_scope() as s:
        s.delete(s.get(CatalogToolProjection, "alpha"))

    # Must not raise even though the row is gone.
    catalog_validation._record([("alpha", "url", "https://alpha.example")], {"reachable": True})

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

    catalog_validation._record([("alpha", "url", "https://alpha.example")], {"reachable": True})

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

    assert _work(summary) == {"candidates": 2, "processed": 2, "recorded": 2, "reachable": 1, "errors": 1}
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

    assert _work(summary) == {"candidates": 2, "processed": 1, "recorded": 1, "reachable": 1, "errors": 0}


def _selects_from(statements, table, column):
    """Statements that read one column of one table, however SQLAlchemy quoted it."""
    return [
        text
        for text in statements
        if table in text.lower() and column in text.lower() and text.lstrip().upper().startswith("SELECT")
    ]


def test_the_candidate_scan_never_reads_the_projection_columns_it_does_not_use():
    """The scan reads two JSON blobs per row, and must not drag the other three along.

    `_candidate_rows` needs `effective_record` to find URLs and `validation` to
    tell which are still fresh. A projection row also carries `provenance`,
    `source_timestamps` and `search_text`, averaging ~10KB together in
    production. Selecting the entity loaded all of it across 82,911 candidate
    URLs, which OOM-killed this job on every hourly tick for a day.

    Checking the emitted SQL rather than memory keeps this honest on SQLite,
    where the rows are far too small to OOM anything.
    """
    from sqlalchemy import event

    with db.session_scope() as s:
        s.add(CatalogToolProjection(tool_name="alpha", effective_record={"url": "https://alpha.example"}))

    seen = []

    def record(_conn, _cursor, statement, *_rest):
        seen.append(statement)

    engine = db.engine()
    event.listen(engine, "before_cursor_execute", record)
    try:
        total, _candidates = catalog_validation._candidate_rows(10)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert total == 1
    for column in ("provenance", "source_timestamps", "search_text"):
        offenders = _selects_from(seen, "catalog_tool_projection", column)
        assert not offenders, f"candidate scan read {column}: {offenders[:1]}"


def test_a_wiki_tools_page_and_its_raw_view_cost_one_request_between_them():
    """The wiki lane publishes one page under two fields; it is probed once.

    `userscript_toolinfo` builds `url` from the page and `repository` from the
    same page with `?action=raw`. Probing both spent two requests per tool to
    learn one fact, across 48,670 wiki tools, every seven days. Both fields
    still get their own recorded verdict -- the saving is in the requests, not
    in what is stored.
    """
    page = "https://en.wikipedia.org/wiki/User:Anomie/linkclassifier.js"
    with db.session_scope() as s:
        s.add(
            CatalogToolProjection(
                tool_name="userscript-en.wikipedia.org-anomie-linkclassifier.js",
                effective_record={"url": page, "repository": f"{page}?action=raw"},
            )
        )

    total, candidates = catalog_validation._candidate_rows(10)

    assert total == 1
    assert list(candidates) == [page]
    assert {field for _tool, field, _value in candidates[page]} == {"url", "repository"}


def test_a_query_string_that_is_not_action_raw_is_probed_on_its_own():
    """Only `action=raw` is folded. Any other query may select another resource."""
    base = "https://example.test/tool"
    with db.session_scope() as s:
        s.add(
            CatalogToolProjection(
                tool_name="alpha",
                effective_record={"url": base, "repository": f"{base}?branch=main"},
            )
        )

    total, candidates = catalog_validation._candidate_rows(10)

    assert total == 2
    assert sorted(candidates) == [base, f"{base}?branch=main"]


def test_the_limit_bounds_requests_rather_than_recorded_fields():
    """Two tools, one page each under two fields: one target fits, both its fields land.

    The limit is what keeps the run inside its hour, and what costs an hour is
    requests. Bounding recorded rows instead would have let a run make one
    request and call it two units of work.
    """
    first = "https://en.wikipedia.org/wiki/User:A/one.js"
    second = "https://en.wikipedia.org/wiki/User:B/two.js"
    with db.session_scope() as s:
        for name, page in (("alpha", first), ("beta", second)):
            s.add(
                CatalogToolProjection(
                    tool_name=name,
                    effective_record={"url": page, "repository": f"{page}?action=raw"},
                )
            )

    total, candidates = catalog_validation._candidate_rows(1)

    assert total == 2
    assert len(candidates) == 1
    assert len(next(iter(candidates.values()))) == 2


def test_a_run_stops_when_its_budget_is_spent_not_when_the_count_runs_out(monkeypatch):
    """The deadline is what bounds a scheduled run; the count is only the safety cap.

    Two targets are due and the limit allows both. The clock expires after the
    first, so the second must be left for the next run -- untouched, not
    recorded as unreachable.
    """
    with db.session_scope() as s:
        s.add(CatalogToolProjection(tool_name="alpha", effective_record={"url": "https://alpha.example"}))
        s.add(CatalogToolProjection(tool_name="beta", effective_record={"url": "https://beta.example"}))

    probed = []

    def fake_probe(_session, url, *, caller):  # noqa: ARG001
        probed.append(url)
        return outbound.ProbeResponse(url=url, status_code=200, content_type="text/html")

    monkeypatch.setattr(outbound, "probe_reachable", fake_probe)
    ticks = iter([0.0, 0.0, 5.0, 5.0, 5.0])
    budget = run_budget.Budget(1, clock=lambda: next(ticks))

    summary = catalog_validation.refresh_candidates(limit=100, budget=budget)

    assert probed == ["https://alpha.example"]
    assert summary["processed"] == 1
    assert summary["candidates"] == 2
    with db.session_scope() as s:
        assert s.get(CatalogToolProjection, "beta").validation in (None, {})


def test_one_probe_writes_every_field_that_named_its_target_in_one_transaction(monkeypatch):
    """A wiki tool publishes the same page twice, and that is one write, not two.

    Counting transactions rather than trusting the shape: `_record` is called
    once per target, and the two fields folded onto it come back as `recorded`
    2 against `processed` 1.
    """
    with db.session_scope() as s:
        s.add(
            CatalogToolProjection(
                tool_name="script",
                effective_record={
                    "url": "https://en.wikipedia.org/wiki/User:X/y.js",
                    "repository": "https://en.wikipedia.org/wiki/User:X/y.js?action=raw",
                },
            )
        )

    monkeypatch.setattr(
        outbound,
        "probe_reachable",
        lambda _session, url, *, caller: outbound.ProbeResponse(url=url, status_code=200, content_type="text/html"),  # noqa: ARG005
    )

    summary = catalog_validation.refresh_candidates()

    assert _work(summary) == {"candidates": 1, "processed": 1, "recorded": 2, "reachable": 1, "errors": 0}
