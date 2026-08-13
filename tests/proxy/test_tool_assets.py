"""Tests for the rebuildable same-origin icon cache."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import tool_assets as tool_assets_job  # noqa: E402
from backend import db, outbound, tool_assets  # noqa: E402
from backend.models import CatalogToolProjection, ToolAssetCache  # noqa: E402


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
    assert first == {"candidates": 4, "processed": 2, "ready": 2, "errors": 0}

    # a_new and b_pending are now ready with matching source URLs, so a
    # second sweep only picks up the untouched error and changed rows.
    second = tool_assets.refresh_candidates(limit=10)
    assert second == {"candidates": 2, "processed": 2, "ready": 1, "errors": 1}
    with db.session_scope() as s:
        assert s.get(ToolAssetCache, "c_error_ready").status == "error"
        assert s.get(ToolAssetCache, "f_changed").status == "ready"
        assert s.get(ToolAssetCache, "d_error_wait").status == "error"
        assert s.get(ToolAssetCache, "e_ready_same").status == "ready"
