"""Tests for the rebuildable same-origin icon cache."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
import requests
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import tool_assets as tool_assets_job  # noqa: E402
from backend import db, outbound, tool_assets  # noqa: E402
from backend.models import CatalogToolProjection, ToolAssetCache, utcnow  # noqa: E402


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    db.configure("sqlite://")
    db.init_schema()
    monkeypatch.setenv("TOOLHUB_ASSET_CACHE_DIR", str(tmp_path / "icons"))


def test_refresh_icon_records_bounded_asset_and_serves_it(monkeypatch):
    body = b"\x89PNG\r\n\x1a\nicon"
    with db.session_scope() as s:
        s.add(
            CatalogToolProjection(
                tool_name="alpha",
                effective_record={"name": "alpha", "icon": "https://alpha.example/icon.png"},
                provenance={
                    "icon": [
                        {
                            "value": "https://alpha.example/icon.png",
                            "source": "official_toolhub",
                            "effective": True,
                        }
                    ]
                },
            )
        )
    monkeypatch.setattr(
        outbound,
        "fetch_bounded_response",
        lambda *args, **kwargs: outbound.BoundedResponse(
            body=body,
            url="https://alpha.example/icon.png",
            content_type="image/png",
            etag='"abc"',
            last_modified=None,
        ),
    )

    result = tool_assets.refresh_tool("alpha")

    assert result["status"] == "ready"
    cached = tool_assets.cached_asset("alpha")
    assert cached[:2] == (body, "image/png")
    with db.session_scope() as s:
        row = s.get(ToolAssetCache, "alpha")
        assert row.size_bytes == len(body)
        assert Path(row.cached_path).parent == tool_assets.cache_dir()


def test_unsupported_content_type_is_recorded_without_a_file(monkeypatch):
    with db.session_scope() as s:
        s.add(
            CatalogToolProjection(
                tool_name="alpha",
                effective_record={"name": "alpha", "icon": "https://alpha.example/icon"},
                provenance={},
            )
        )
    monkeypatch.setattr(
        outbound,
        "fetch_bounded_response",
        lambda *args, **kwargs: outbound.BoundedResponse(
            body=b"not an image",
            url="https://alpha.example/icon",
            content_type="text/html",
            etag=None,
            last_modified=None,
        ),
    )

    result = tool_assets.refresh_tool("alpha")

    assert result["status"] == "error"
    assert tool_assets.cached_asset("alpha") is None
    assert not tool_assets.cache_dir().exists()


def test_job_keeps_per_tool_errors_as_data_quality_results(monkeypatch, capsys):
    monkeypatch.setattr(
        tool_assets,
        "refresh_candidates",
        lambda limit: {"candidates": 3, "processed": 3, "ready": 1, "errors": 2},
    )

    assert tool_assets_job.main() == 0
    assert '"errors": 2' in capsys.readouterr().out


def test_refresh_tool_skips_a_blank_name():
    assert tool_assets.refresh_tool("   ") == {"toolName": "", "status": "skipped"}


def test_refresh_tool_reports_a_missing_projection():
    assert tool_assets.refresh_tool("does-not-exist") == {
        "toolName": "does-not-exist",
        "status": "missing_projection",
    }


def test_refresh_tool_records_a_missing_icon_without_fetching(monkeypatch):
    with db.session_scope() as s:
        s.add(CatalogToolProjection(tool_name="alpha", effective_record={"name": "alpha"}, provenance={}))
    monkeypatch.setattr(
        outbound,
        "fetch_bounded_response",
        lambda *args, **kwargs: pytest.fail("no icon URL means no fetch should happen"),
    )

    result = tool_assets.refresh_tool("alpha")

    assert result == {"toolName": "alpha", "status": "missing"}
    with db.session_scope() as s:
        row = s.get(ToolAssetCache, "alpha")
        assert row.source_url == ""
        assert row.source_type == "official_toolhub"
        assert row.status == "missing"
        assert row.checked_at is not None
        assert row.next_attempt_at is None
        assert row.last_error is None


def test_identical_icon_content_is_deduplicated_on_disk(monkeypatch):
    body = b"\x89PNG\r\n\x1a\nsame-bytes"
    with db.session_scope() as s:
        s.add(
            CatalogToolProjection(
                tool_name="alpha", effective_record={"icon": "https://a.example/icon.png"}, provenance={}
            )
        )
        s.add(
            CatalogToolProjection(
                tool_name="beta", effective_record={"icon": "https://b.example/icon.png"}, provenance={}
            )
        )
    monkeypatch.setattr(
        outbound,
        "fetch_bounded_response",
        lambda *args, **kwargs: outbound.BoundedResponse(
            body=body, url="https://x.example/icon.png", content_type="image/png", etag=None, last_modified=None
        ),
    )

    first = tool_assets.refresh_tool("alpha")
    second = tool_assets.refresh_tool("beta")

    assert first["status"] == "ready"
    assert second["status"] == "ready"
    assert first["sha256"] == second["sha256"]
    # The second store finds the digest-named file already on disk and must
    # not rewrite it.
    assert len(list(tool_assets.cache_dir().glob("*.png"))) == 1


def test_cached_asset_ignores_rows_pointing_outside_the_cache_dir(tmp_path):
    outside = tmp_path / "elsewhere.png"
    outside.write_bytes(b"not in the cache dir")
    with db.session_scope() as s:
        s.add(
            ToolAssetCache(
                tool_name="alpha",
                status="ready",
                cached_path=str(outside),
                content_type="image/png",
                sha256="deadbeef",
            )
        )

    assert tool_assets.cached_asset("alpha") is None


def test_refresh_candidates_selects_eligible_rows_and_bounds_processing(monkeypatch):
    with db.session_scope() as s:
        s.add(CatalogToolProjection(tool_name="a_new", effective_record={"icon": "https://x.example/a.png"}))
        s.add(CatalogToolProjection(tool_name="b_pending", effective_record={"icon": "https://x.example/b.png"}))
        s.add(CatalogToolProjection(tool_name="c_error_ready", effective_record={"icon": "https://x.example/c.png"}))
        s.add(CatalogToolProjection(tool_name="d_error_wait", effective_record={"icon": "https://x.example/d.png"}))
        s.add(CatalogToolProjection(tool_name="e_ready_same", effective_record={"icon": "https://x.example/e.png"}))
        s.add(CatalogToolProjection(tool_name="f_changed", effective_record={"icon": "https://x.example/f-new.png"}))
        s.add(ToolAssetCache(tool_name="b_pending", source_url="https://x.example/b.png", status="pending"))
        s.add(
            ToolAssetCache(
                tool_name="c_error_ready", source_url="https://x.example/c.png", status="error", next_attempt_at=None
            )
        )
        s.add(
            ToolAssetCache(
                tool_name="d_error_wait",
                source_url="https://x.example/d.png",
                status="error",
                next_attempt_at=tool_assets.utcnow() + timedelta(hours=5),
            )
        )
        s.add(ToolAssetCache(tool_name="e_ready_same", source_url="https://x.example/e.png", status="ready"))
        s.add(ToolAssetCache(tool_name="f_changed", source_url="https://x.example/f-old.png", status="ready"))

    def fake_fetch(_session, url, *, policy, caller):  # noqa: ARG001
        if url.endswith("c.png"):
            raise requests.ConnectionError("down")
        return outbound.BoundedResponse(body=b"PNGDATA", url=url, content_type="image/png", etag=None, last_modified=None)

    monkeypatch.setattr(outbound, "fetch_bounded_response", fake_fetch)

    # Only a_new, b_pending, c_error_ready and f_changed qualify; the limit
    # of 2 must process just the first two in tool_name order.
    first = tool_assets.refresh_candidates(limit=2)
    assert first == {
        "candidates": 4,
        "fetches": 4,
        "processed": 2,
        "ready": 2,
        "errors": 0,
        "settled": 0,
        "settlements": 0,
    }

    # a_new and b_pending are now ready with matching source URLs, so a
    # second sweep only picks up the untouched error and changed rows.
    second = tool_assets.refresh_candidates(limit=10)
    assert second == {
        "candidates": 2,
        "fetches": 2,
        "processed": 2,
        "ready": 1,
        "errors": 1,
        "settled": 0,
        "settlements": 0,
    }
    with db.session_scope() as s:
        assert s.get(ToolAssetCache, "c_error_ready").status == "error"
        assert s.get(ToolAssetCache, "f_changed").status == "ready"
        assert s.get(ToolAssetCache, "d_error_wait").status == "error"
        assert s.get(ToolAssetCache, "e_ready_same").status == "ready"


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        (
            "https://commons.wikimedia.org/wiki/File:Adiutor_icon.svg",
            "https://commons.wikimedia.org/wiki/Special:FilePath/Adiutor_icon.svg",
        ),
        (
            "https://commons.wikimedia.org/wiki/File:Cdkdepict_wikidata.png",
            "https://commons.wikimedia.org/wiki/Special:FilePath/Cdkdepict_wikidata.png?width=512",
        ),
        (
            "https://commons.wikimedia.org/wiki/Image:Old_alias.png",
            "https://commons.wikimedia.org/wiki/Special:FilePath/Old_alias.png?width=512",
        ),
        (
            "https://commons.wikimedia.org/wiki/File:Caf%C3%A9.svg",
            "https://commons.wikimedia.org/wiki/Special:FilePath/Caf%C3%A9.svg",
        ),
        # Not a file page, and not on a wiki at all: both are left alone.
        ("https://commons.wikimedia.org/wiki/Commons:Welcome", "https://commons.wikimedia.org/wiki/Commons:Welcome"),
        ("https://alpha.example/icon.png", "https://alpha.example/icon.png"),
    ],
)
def test_a_commons_file_page_resolves_to_the_file_behind_it(declared, expected):
    """The schema asks for a description page; an <img> needs what it describes."""
    assert tool_assets._wiki_file_url(declared) == expected


def _projection(name, icon):
    with db.session_scope() as s:
        s.add(
            CatalogToolProjection(
                tool_name=name,
                effective_record={"name": name, "icon": icon},
                provenance={"icon": [{"value": icon, "source": "official_toolhub", "effective": True}]},
            )
        )


def test_a_commons_icon_is_fetched_from_the_file_rather_than_its_page(monkeypatch):
    _projection("alpha", "https://commons.wikimedia.org/wiki/File:Adiutor_icon.svg")
    asked = []

    def fetch(_session, url, **_kwargs):
        asked.append(url)
        return outbound.BoundedResponse(
            body=b"<svg/>", url=url, content_type="image/svg+xml", etag=None, last_modified=None
        )

    monkeypatch.setattr(outbound, "fetch_bounded_response", fetch)

    assert tool_assets.refresh_tool("alpha")["status"] == "ready"
    assert asked == ["https://commons.wikimedia.org/wiki/Special:FilePath/Adiutor_icon.svg"]
    with db.session_scope() as s:
        assert s.get(ToolAssetCache, "alpha").source_url == asked[0]


def test_a_vector_too_large_to_fetch_falls_back_to_a_scaled_copy(monkeypatch):
    _projection("alpha", "https://commons.wikimedia.org/wiki/File:Huge_drawing.svg")
    asked = []

    def fetch(_session, url, **_kwargs):
        asked.append(url)
        if "width=" not in url:
            message = f"{url}: response larger than 524288 bytes"
            raise ValueError(message)
        return outbound.BoundedResponse(
            body=b"\x89PNG\r\n\x1a\n", url=url, content_type="image/png", etag=None, last_modified=None
        )

    monkeypatch.setattr(outbound, "fetch_bounded_response", fetch)

    assert tool_assets.refresh_tool("alpha")["status"] == "ready"
    assert asked == [
        "https://commons.wikimedia.org/wiki/Special:FilePath/Huge_drawing.svg",
        "https://commons.wikimedia.org/wiki/Special:FilePath/Huge_drawing.svg?width=512",
    ]


def test_an_icon_that_is_not_on_a_wiki_is_not_retried_twice(monkeypatch):
    _projection("alpha", "https://alpha.example/icon.png")
    asked = []

    def fetch(_session, url, **_kwargs):
        asked.append(url)
        message = f"{url}: response larger than 524288 bytes"
        raise ValueError(message)

    monkeypatch.setattr(outbound, "fetch_bounded_response", fetch)

    assert tool_assets.refresh_tool("alpha")["status"] == "error"
    assert asked == ["https://alpha.example/icon.png"]


def _selects_from(statements, table, column):
    """Statements that read one column of one table, however SQLAlchemy quoted it."""
    return [
        text
        for text in statements
        if table in text.lower() and column in text.lower() and text.lstrip().upper().startswith("SELECT")
    ]


def test_the_candidate_scan_reads_only_the_columns_it_decides_from():
    """Two tables scanned whole, and the loop keeps nothing but tool names.

    It needs `effective_record` and `provenance` to resolve the declared icon,
    and four scalars off the cache to tell whether that icon is missing, stale
    or due a retry. Selecting the entities pulled the projection's other three
    JSON blobs and `search_text` plus every cache row's stored bytes metadata,
    which OOM-killed this job hourly once discovery opened up to every
    Wikimedia project.

    Asserted with nothing due, so the only reads are the scan itself: a real
    candidate is *supposed* to have its projection loaded by `refresh_tool`.
    """
    from sqlalchemy import event

    with db.session_scope() as s:
        s.add(
            CatalogToolProjection(
                tool_name="alpha",
                effective_record={"name": "alpha", "icon": "https://alpha.example/icon.png"},
            )
        )
        s.add(
            ToolAssetCache(
                tool_name="alpha",
                source_url="https://alpha.example/icon.png",
                status="ready",
            )
        )

    seen = []

    def record(_conn, _cursor, statement, *_rest):
        seen.append(statement)

    engine = db.engine()
    event.listen(engine, "before_cursor_execute", record)
    try:
        summary = tool_assets.refresh_candidates()
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert summary["candidates"] == 0, "fixture must leave nothing due, or refresh loads projections legitimately"
    for column in ("validation", "source_timestamps", "search_text"):
        offenders = _selects_from(seen, "catalog_tool_projection", column)
        assert not offenders, f"candidate scan read projection {column}: {offenders[:1]}"
    for column in ("cached_path", "sha256", "content_type", "last_error"):
        offenders = _selects_from(seen, "tool_asset_cache", column)
        assert not offenders, f"candidate scan read asset {column}: {offenders[:1]}"


def test_the_narrowed_candidate_scan_still_sees_every_reason_to_refresh(monkeypatch):
    """Narrowing must not quietly change who is judged due.

    Each branch keys off a different column, so a select that dropped one would
    still return rows -- just the wrong ones, silently. One tool per reason: no
    cache row at all, a changed source URL, a pending fetch, an error whose
    backoff has expired, and an error still deferred that must be skipped.
    """
    with db.session_scope() as s:
        for name in ("uncached", "moved", "pending", "retryable", "deferred"):
            s.add(
                CatalogToolProjection(
                    tool_name=name,
                    effective_record={"name": name, "icon": f"https://{name}.example/icon.png"},
                )
            )
        s.add(ToolAssetCache(tool_name="moved", source_url="https://old.example/icon.png", status="ready"))
        s.add(ToolAssetCache(tool_name="pending", source_url="https://pending.example/icon.png", status="pending"))
        s.add(
            ToolAssetCache(
                tool_name="retryable",
                source_url="https://retryable.example/icon.png",
                status="error",
                next_attempt_at=utcnow() - timedelta(hours=1),
            )
        )
        s.add(
            ToolAssetCache(
                tool_name="deferred",
                source_url="https://deferred.example/icon.png",
                status="error",
                next_attempt_at=utcnow() + timedelta(hours=1),
            )
        )

    # Counting is the assertion; stub the fetch so no candidate is dialled.
    monkeypatch.setattr(tool_assets, "refresh_tool", lambda name, **_kwargs: {"toolName": name, "status": "ready"})

    assert tool_assets.refresh_candidates(limit=1)["candidates"] == 4


def test_tools_that_declare_no_icon_are_settled_outside_the_fetch_limit(monkeypatch):
    """The wiki lane declares no icon, so it must not queue behind downloads.

    Both lanes that discover wiki tools leave `icon` empty, so every one of
    them was "due" forever and each took a slot from a limit sized for HTTP
    fetches -- a hundred an hour to write rows that need no request at all.
    """
    with db.session_scope() as s:
        for index in range(12):
            s.add(
                CatalogToolProjection(
                    tool_name=f"wiki_{index:02d}",
                    effective_record={"name": f"wiki_{index:02d}"},
                    provenance={"icon": []},
                )
            )
        s.add(CatalogToolProjection(tool_name="z_has_icon", effective_record={"icon": "https://x.example/z.png"}))

    fetched = []

    def record_fetch(_session, url, *, policy, caller):  # noqa: ARG001
        fetched.append(url)
        return outbound.BoundedResponse(body=b"PNGDATA", url=url, content_type="image/png", etag=None, last_modified=None)

    monkeypatch.setattr(outbound, "fetch_bounded_response", record_fetch)

    result = tool_assets.refresh_candidates(limit=1)
    assert result["settlements"] == 12
    assert result["settled"] == 12
    # One request for the one tool that declares an icon, and none for the
    # twelve that do not -- the limit bounds requests, not settlements.
    assert fetched == ["https://x.example/z.png"]
    assert result["fetches"] == 1

    with db.session_scope() as s:
        settled = s.execute(
            select(ToolAssetCache.tool_name).where(ToolAssetCache.status == "missing").order_by(ToolAssetCache.tool_name)
        )
        assert [row.tool_name for row in settled] == [f"wiki_{index:02d}" for index in range(12)]

    # And the settled rows are done: a second sweep finds nothing left to do
    # for them, rather than re-deciding the same verdict every hour.
    assert tool_assets.refresh_candidates(limit=1)["settlements"] == 0
