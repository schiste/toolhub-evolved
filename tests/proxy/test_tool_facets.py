# SPDX-License-Identifier: GPL-3.0-or-later
"""Facet extraction, storage, and query behavior for tool signal facets."""

import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db  # noqa: E402
from backend.models import ToolSignalFacet, utcnow  # noqa: E402


@pytest.fixture(autouse=True)
def database() -> None:
    db.configure("sqlite://")
    db.init_schema()


def test_tool_signal_facet_roundtrip_and_uniqueness() -> None:
    with db.session_scope() as s:
        s.add(
            ToolSignalFacet(
                tool_name="sfedits",
                facet_type="dependency",
                value="pypi:pywikibot",
                confidence=0.9,
                source_report_id=1,
                updated_at=utcnow(),
            )
        )
    with db.session_scope() as s:
        row = s.query(ToolSignalFacet).one()
        assert row.tool_name == "sfedits"  # noqa: S101
        assert row.value == "pypi:pywikibot"  # noqa: S101
    with pytest.raises(IntegrityError), db.session_scope() as s:
        s.add(
            ToolSignalFacet(
                tool_name="sfedits",
                facet_type="dependency",
                value="pypi:pywikibot",
            )
        )
