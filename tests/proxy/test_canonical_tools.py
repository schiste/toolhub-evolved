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


def test_toolforge_runtime_host_is_only_a_candidate_project_hint():
    record = {"url": "https://toolhub-evolved.toolforge.org/tools/create"}

    assert canonical_tools.verified_toolforge_project_names("bd808-toolhub-evolved-test") == []
    assert canonical_tools.candidate_toolforge_project_names("bd808-toolhub-evolved-test", record) == [
        "toolhub-evolved"
    ]
    assert canonical_tools.toolforge_project_names("bd808-toolhub-evolved-test", record) == ["toolhub-evolved"]


def test_explicit_toolforge_name_is_verified_while_runtime_and_admin_urls_are_candidates():
    record = {
        "url": "https://toolsadmin.wikimedia.org/tools/id/toolsadmin-project/toolinfo/1.2/toolinfo.json",
        "api_url": "https://runtime-project.toolforge.org/api",
    }

    assert canonical_tools.verified_toolforge_project_names("toolforge-name-project") == [
        "name-project",
    ]
    assert canonical_tools.candidate_toolforge_project_names("toolforge-name-project", record) == [
        "toolsadmin-project",
        "runtime-project",
    ]


def test_toolforge_project_names_ignores_non_toolforge_hosts_and_missing_record():
    assert canonical_tools.toolforge_project_names("plain-tool", None) == []
    assert (
        canonical_tools.toolforge_project_names(
            "plain-tool", {"url": "https://example.org/", "api_url": "https://example.org/api/"}
        )
        == []
    )


def test_a_runtime_host_restores_the_hyphen_the_canonical_name_collapsed():
    # Upstream names collapse hyphen runs, so the punycode project `xn--9s9h`
    # arrives as `toolforge-xn-9s9h` and the name alone can never name it back.
    # The record's own host still carries the lost hyphen, and it collapses to
    # exactly the name-derived project, so it is admissible as the project the
    # record provably runs in rather than a hint about where it might run.
    record = {"url": "https://xn--9s9h.toolforge.org/"}

    assert canonical_tools.verified_toolforge_project_names("toolforge-xn-9s9h", record) == [
        "xn-9s9h",
        "xn--9s9h",
    ]
    # And it stops being a mere candidate, which is what makes the LDAP project
    # mapping verified rather than unverified.
    assert canonical_tools.candidate_toolforge_project_names("toolforge-xn-9s9h", record) == []


def test_a_runtime_host_that_disagrees_with_the_name_stays_a_candidate():
    # The reason a host is normally inadmissible: this record links to another
    # project's deployment. Collapsing hyphens does not make the two agree, so
    # the exception must not fire and the host stays unverified.
    record = {"url": "https://xn--other.toolforge.org/"}

    assert canonical_tools.verified_toolforge_project_names("toolforge-xn-9s9h", record) == ["xn-9s9h"]
    assert canonical_tools.candidate_toolforge_project_names("toolforge-xn-9s9h", record) == ["xn--other"]


def test_the_hyphen_exception_needs_a_record_and_a_toolforge_name():
    # Callers with no record in hand lose only the exception, never the name.
    assert canonical_tools.verified_toolforge_project_names("toolforge-xn-9s9h") == ["xn-9s9h"]
    # A record that is not named for a Toolforge project verifies nothing, so
    # the exception cannot be a back door into the strict path.
    assert canonical_tools.verified_toolforge_project_names("xn-9s9h", {"url": "https://xn--9s9h.toolforge.org/"}) == []


def test_names_by_toolforge_project_indexes_the_restored_hyphen():
    canonical_tools.upsert_records(
        [{"name": "toolforge-xn-9s9h", "title": "Punycode", "url": "https://xn--9s9h.toolforge.org/"}],
        source_url="https://toolhub.wikimedia.org/api/tools/toolforge-xn-9s9h/",
    )

    with db.session_scope() as session:
        index = canonical_tools.names_by_toolforge_project(session)

    # LDAP keys membership on the real project name, so the index has to reach
    # it under that spelling; the collapsed name stays indexed alongside.
    assert index["xn--9s9h"] == ("toolforge-xn-9s9h",)
    assert index["xn-9s9h"] == ("toolforge-xn-9s9h",)


def test_runtime_host_project_names_reads_every_host_form_toolforge_has_used():
    # One project, four eras of URL. A record written in any of them still names
    # its tool, so all four have to resolve; reading only the current form would
    # treat a decade-old URL as naming no project at all.
    assert canonical_tools.runtime_host_project_names({"url": "https://depicts.toolforge.org/x"}) == ["depicts"]
    assert canonical_tools.runtime_host_project_names({"url": "https://tools.wmflabs.org/depicts/run"}) == ["depicts"]
    assert canonical_tools.runtime_host_project_names({"url": "https://xtools.wmflabs.org/"}) == ["xtools"]
    assert canonical_tools.runtime_host_project_names({"url": "https://depicts.wmcloud.org/"}) == ["depicts"]


def test_runtime_host_project_names_never_reads_tools_as_a_project():
    # `tools.wmflabs.org` ends with `.wmflabs.org`, so suffix order decides this:
    # the path hosts are matched first, or every legacy URL would name a project
    # called "tools" and pool unrelated tools together.
    assert canonical_tools.runtime_host_project_names({"url": "https://tools.wmflabs.org/"}) == []
    assert canonical_tools.runtime_host_project_names({"url": "https://tools-static.wmflabs.org/qq/lib.js"}) == ["qq"]


def test_runtime_host_project_names_spans_both_url_fields_and_dedupes():
    record = {"url": "https://proj.toolforge.org/", "api_url": "https://tools.wmflabs.org/proj/api"}

    assert canonical_tools.runtime_host_project_names(record) == ["proj"]


def test_runtime_host_project_names_is_empty_off_toolforge_and_without_a_record():
    assert canonical_tools.runtime_host_project_names(None) == []
    assert canonical_tools.runtime_host_project_names({}) == []
    assert canonical_tools.runtime_host_project_names({"url": "https://www.wikidata.org/wiki/User:X/script.js"}) == []
    # toolsadmin is a registry, not a runtime host: it serves nobody's tool.
    assert (
        canonical_tools.runtime_host_project_names(
            {"url": "https://toolsadmin.wikimedia.org/tools/id/proj/toolinfo/1.0/toolinfo.json"}
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


def test_ingest_payload_ignores_unrelated_paths_and_persists_valid_tools():
    assert canonical_tools.ingest_payload("https://toolhub.wikimedia.org/api/schema/", b'{"name":"alpha"}') == 0
    assert canonical_tools.ingest_payload("https://toolhub.wikimedia.org/api/tools/", b'{"results":[]}') == 0
    assert (
        canonical_tools.ingest_payload(
            "https://toolhub.wikimedia.org/api/tools/alpha/",
            b'{"name":"alpha","title":"Alpha"}',
        )
        == 1
    )
    assert canonical_tools.compact_record({"name": "alpha", "description": "A"})["name"] == "alpha"


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


def test_upsert_records_can_stage_a_generation_without_queueing_reconciliation():
    from backend.models import CanonicalToolCache  # noqa: PLC0415

    assert (
        canonical_tools.upsert_records(
            [{"name": "alpha"}],
            source_url="https://toolhub.wikimedia.org/api/tools/",
            generation=9,
            enqueue_reconciliation=False,
        )
        == 1
    )
    with db.session_scope() as session:
        assert session.get(CanonicalToolCache, "alpha").generation == 9


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


def test_prune_completed_generation_deletes_retired_rows():
    from backend.models import CanonicalToolCache, utcnow  # noqa: PLC0415

    now = utcnow()
    with db.session_scope() as session:
        for name, generation in (("current", 2), ("retired", 1)):
            session.add(
                CanonicalToolCache(
                    tool_name=name,
                    record={"name": name},
                    fetched_at=now,
                    expires_at=now,
                    stale_until=now,
                    generation=generation,
                )
            )
    with db.session_scope() as session:
        assert canonical_tools.prune_completed_generation(session, 2, 1) == ["retired"]
    with db.session_scope() as session:
        assert session.get(CanonicalToolCache, "retired") is None


def test_snapshot_staging_validates_counts_and_publishes_new_rows():
    from backend.models import CanonicalToolCache  # noqa: PLC0415

    assert canonical_tools.stage_snapshot_records([{"name": ""}, "wrong"], source_url="source", generation=4) == 0
    assert (
        canonical_tools.stage_snapshot_records(
            [{"name": "alpha"}, {"name": "alpha", "title": "duplicate"}],
            source_url="https://toolhub.wikimedia.org/api/tools/",
            generation=4,
        )
        == 1
    )
    with db.session_scope() as session, pytest.raises(ValueError, match="staged 1 distinct rows, expected 2"):
        canonical_tools.publish_snapshot_stage(session, 4, 2)
    with db.session_scope() as session:
        assert canonical_tools.publish_snapshot_stage(session, 4, 1) == []
    with db.session_scope() as session:
        assert session.get(CanonicalToolCache, "alpha").generation == 4


def test_snapshot_publish_preserves_existing_detail_only_fields_and_source():
    from backend.models import CanonicalToolCache, utcnow  # noqa: PLC0415

    now = utcnow()
    detail_url = "https://toolhub.wikimedia.org/api/tools/alpha/"
    with db.session_scope() as session:
        session.add(
            CanonicalToolCache(
                tool_name="alpha",
                record={"name": "alpha", "detail_only": "keep"},
                source_url=detail_url,
                fetched_at=now,
                expires_at=now,
                stale_until=now,
                generation=3,
            )
        )
    canonical_tools.stage_snapshot_records(
        [{"name": "alpha", "title": "Listing title"}],
        source_url="https://toolhub.wikimedia.org/api/tools/",
        generation=4,
    )

    with db.session_scope() as session:
        assert canonical_tools.publish_snapshot_stage(session, 4, 1) == []
    with db.session_scope() as session:
        row = session.get(CanonicalToolCache, "alpha")
        assert row.record["detail_only"] == "keep"
        assert row.record["title"] == "Listing title"
        assert row.source_url == detail_url


def test_read_projection_backfill_marks_an_empty_catalog_complete():
    from backend.models import ApiCacheMeta  # noqa: PLC0415

    assert canonical_tools.backfill_read_projection() == 0
    with db.session_scope() as session:
        assert session.get(ApiCacheMeta, canonical_tools.READ_PROJECTION_META_KEY).value == "complete"


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


def test_a_bare_toolforge_prefix_restores_nothing_from_the_runtime_host():
    # `toolforge-` alone leaves the name-derived project empty, so there is
    # nothing for the runtime host to be checked against. The hyphen-restoring
    # exception is a confirmation of the name, never a lookup, so with no name
    # to confirm the host's own project must not become an answer on its own.
    record = {"url": "https://xn--9s9h.toolforge.org/"}

    assert canonical_tools.verified_toolforge_project_names("toolforge-", record) == []
