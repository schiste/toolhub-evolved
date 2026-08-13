# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused unit tests for the canonical Toolhub tool cache helpers.

`canonical_tools` is otherwise exercised end-to-end from test_backend.py (via
the Flask app fixture) and test_me_canonical_tools.py (via the signed-in
workbench). This file targets branches those integration paths never hit:
malformed input, empty/duplicate names, and swallowed SQLAlchemy errors.
"""

import contextlib
import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import canonical_tools, db  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def test_toolforge_project_names_dedupes_across_prefix_url_and_toolsadmin_path():
    # The tool-name prefix, the .toolforge.org host, and a toolsadmin.wikimedia.org
    # "/tools/id/<name>/" path all resolve to the same project here: the second
    # and third hits must be dropped as duplicates (candidate loop, line 72),
    # and the toolsadmin path walk must skip a non-matching prefix segment
    # before it finds the "tools", "id" pair (line 64).
    record = {
        "url": "https://myproj.toolforge.org/tool",
        "api_url": "https://toolsadmin.wikimedia.org/extra/tools/id/myproj/",
    }

    assert canonical_tools.toolforge_project_names("toolforge-myproj", record) == ["myproj"]


def test_toolforge_project_names_ignores_non_toolforge_hosts_and_missing_record():
    assert canonical_tools.toolforge_project_names("plain-tool", None) == []
    assert (
        canonical_tools.toolforge_project_names(
            "plain-tool", {"url": "https://example.org/", "api_url": "https://example.org/api/"}
        )
        == []
    )


def test_iter_tool_records_walks_a_top_level_list():
    payload = [{"name": "a", "title": "A"}, {"name": "b", "url": "https://b.example"}]

    records = canonical_tools._iter_tool_records(payload)  # noqa: SLF001 - branch coverage for the walk itself

    assert [r["name"] for r in records] == ["a", "b"]


def test_iter_tool_records_discards_scalar_entries_that_are_neither_dict_nor_list():
    # A popped stack entry that is neither a tool record, a dict (to search for
    # nested listing keys), nor a list (to flatten) must be silently dropped
    # rather than raising or being treated as a record.
    assert canonical_tools._iter_tool_records("just a string") == []  # noqa: SLF001


def test_ingest_payload_returns_zero_for_undecodable_or_invalid_json_bodies():
    url = "https://toolhub.wikimedia.org/api/tools/"

    assert canonical_tools.ingest_payload(url, b"{not valid json") == 0
    assert canonical_tools.ingest_payload(url, b"\xff\xfe\x00\x01") == 0


def test_upsert_records_skips_blank_and_duplicate_names():
    count = canonical_tools.upsert_records(
        [
            {"name": "dup", "title": "First"},
            {"name": "dup", "title": "Second"},
            {"name": ""},
            {"title": "no name at all"},
        ],
        source_url="https://toolhub.wikimedia.org/api/tools/",
    )

    assert count == 1
    cached = canonical_tools.tools_by_name(["dup"])["dup"]
    assert cached["record"]["title"] == "First"


def test_upsert_records_returns_zero_when_every_record_is_unusable():
    assert canonical_tools.upsert_records([], source_url="https://toolhub.wikimedia.org/api/tools/") == 0
    assert (
        canonical_tools.upsert_records(
            [{"name": ""}, {"title": "still no name"}], source_url="https://toolhub.wikimedia.org/api/tools/"
        )
        == 0
    )


def test_upsert_records_swallows_sqlalchemy_errors(monkeypatch):
    @contextlib.contextmanager
    def _raise_session_scope():
        raise SQLAlchemyError("boom")
        yield  # pragma: no cover - unreachable, contextmanager requires a yield

    monkeypatch.setattr(canonical_tools.db, "session_scope", _raise_session_scope)

    result = canonical_tools.upsert_records(
        [{"name": "alpha", "title": "Alpha"}], source_url="https://toolhub.wikimedia.org/api/tools/alpha/"
    )

    assert result == 0


def test_prune_completed_generation_raises_on_mismatched_snapshot_size():
    from backend.models import CanonicalToolCache, utcnow  # noqa: PLC0415 - keep import local to this test

    now = utcnow()
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="alpha",
                record={"name": "alpha", "title": "Alpha"},
                fetched_at=now,
                expires_at=now,
                stale_until=now,
                generation=1,
            )
        )
        s.add(
            CanonicalToolCache(
                tool_name="beta",
                record={"name": "beta", "title": "Beta"},
                fetched_at=now,
                expires_at=now,
                stale_until=now,
                generation=1,
            )
        )

    with db.session_scope() as s, pytest.raises(ValueError, match=r"saw 2 distinct rows, expected 3"):
        canonical_tools.prune_completed_generation(s, generation=1, expected_count=3)


def test_prune_completed_generation_skips_delete_when_nothing_is_retired():
    from backend.models import CanonicalToolCache, utcnow  # noqa: PLC0415

    now = utcnow()
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="alpha",
                record={"name": "alpha", "title": "Alpha"},
                fetched_at=now,
                expires_at=now,
                stale_until=now,
                generation=1,
            )
        )

    with db.session_scope() as s:
        retired = canonical_tools.prune_completed_generation(s, generation=1, expected_count=1)

    assert retired == []
    with db.session_scope() as s:
        assert s.get(CanonicalToolCache, "alpha") is not None


def test_backfill_search_text_swallows_sqlalchemy_errors(monkeypatch):
    @contextlib.contextmanager
    def _raise_session_scope():
        raise SQLAlchemyError("boom")
        yield  # pragma: no cover - unreachable, contextmanager requires a yield

    monkeypatch.setattr(canonical_tools.db, "session_scope", _raise_session_scope)

    assert canonical_tools.backfill_search_text() == 0


def test_tools_by_name_returns_empty_for_blank_or_empty_input():
    assert canonical_tools.tools_by_name([]) == {}
    assert canonical_tools.tools_by_name(["", "   "]) == {}


def test_tools_by_name_dedupes_repeated_names():
    canonical_tools.upsert_records(
        [{"name": "dup", "title": "Dup"}], source_url="https://toolhub.wikimedia.org/api/tools/dup/"
    )

    result = canonical_tools.tools_by_name(["dup", "dup", "missing"])

    assert set(result) == {"dup"}
