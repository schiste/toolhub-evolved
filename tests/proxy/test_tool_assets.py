"""Tests for the rebuildable same-origin icon cache."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

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
