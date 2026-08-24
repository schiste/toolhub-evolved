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


TOOLS_URL = "https://toolhub.wikimedia.org/api/tools/"


def _queued_names() -> list[str]:
    from backend.models import PersonReconciliationQueue  # noqa: PLC0415

    with db.session_scope() as session:
        return sorted(row.tool_name for row in session.query(PersonReconciliationQueue).all())


def _drain_queue() -> None:
    from backend.models import PersonReconciliationQueue  # noqa: PLC0415

    with db.session_scope() as session:
        session.query(PersonReconciliationQueue).delete()


def test_a_second_snapshot_of_unchanged_records_queues_nothing():
    # The condition a recovery snapshot creates: the whole catalog re-read and
    # found identical. Reconciliation reads `record` alone, so re-deriving from
    # an unchanged one cannot reach a different answer.
    records = [{"name": "alpha", "title": "Alpha"}, {"name": "beta", "title": "Beta"}]
    canonical_tools.upsert_records(records, source_url=TOOLS_URL)
    assert _queued_names() == ["alpha", "beta"]
    _drain_queue()

    assert canonical_tools.upsert_records(records, source_url=TOOLS_URL) == 2

    assert _queued_names() == []


def test_a_record_whose_content_moved_is_still_queued():
    canonical_tools.upsert_records([{"name": "alpha", "title": "Alpha"}], source_url=TOOLS_URL)
    _drain_queue()

    canonical_tools.upsert_records([{"name": "alpha", "title": "Alpha renamed"}], source_url=TOOLS_URL)

    assert _queued_names() == ["alpha"]


def test_only_the_moved_members_of_a_batch_are_queued():
    # The saving is per record, not per batch: one changed tool must not drag
    # its unchanged neighbours into the queue behind it.
    canonical_tools.upsert_records(
        [{"name": "alpha", "title": "Alpha"}, {"name": "beta", "title": "Beta"}],
        source_url=TOOLS_URL,
    )
    _drain_queue()

    canonical_tools.upsert_records(
        [{"name": "alpha", "title": "Alpha"}, {"name": "beta", "title": "Beta moved"}],
        source_url=TOOLS_URL,
    )

    assert _queued_names() == ["beta"]


def test_a_first_sighting_is_queued_even_with_nothing_to_compare():
    # A new row has no previous record, and "no previous record" must read as
    # changed rather than as equal-to-nothing.
    canonical_tools.upsert_records([{"name": "alpha"}], source_url=TOOLS_URL)

    assert _queued_names() == ["alpha"]


def test_a_listing_refresh_that_adds_nothing_to_a_detail_record_queues_nothing():
    # _merge_listing_record keeps richer detail fields, so a thin listing pass
    # over an already-hydrated tool is a no-op on `record` -- and must be a
    # no-op on the queue too, or every listing page requeues the catalog.
    canonical_tools.upsert_records(
        [{"name": "alpha", "title": "Alpha", "description": "Long detail text"}],
        source_url="https://toolhub.wikimedia.org/api/tools/alpha/",
        detail=True,
    )
    _drain_queue()

    canonical_tools.upsert_records(
        [{"name": "alpha", "title": "Alpha", "description": None}],
        source_url=TOOLS_URL,
    )

    assert _queued_names() == []


def test_skipping_the_queue_still_refreshes_the_freshness_columns():
    # The skip must be confined to the queue. The row itself is still written,
    # otherwise an unchanged record would never renew its cache lifetime.
    from backend.models import CanonicalToolCache  # noqa: PLC0415

    canonical_tools.upsert_records([{"name": "alpha", "title": "Alpha"}], source_url=TOOLS_URL)
    with db.session_scope() as session:
        first_fetched = session.get(CanonicalToolCache, "alpha").fetched_at
    _drain_queue()

    canonical_tools.upsert_records([{"name": "alpha", "title": "Alpha"}], source_url=TOOLS_URL, generation=12)

    assert _queued_names() == []
    with db.session_scope() as session:
        row = session.get(CanonicalToolCache, "alpha")
        assert row.generation == 12
        assert row.fetched_at >= first_fetched


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


def _cache_row(name, *, generation, source):
    from backend.models import CanonicalToolCache, utcnow  # noqa: PLC0415

    now = utcnow()
    return CanonicalToolCache(
        tool_name=name,
        record={"name": name},
        fetched_at=now,
        expires_at=now,
        stale_until=now,
        generation=generation,
        source=source,
    )


def test_a_synthesized_record_survives_a_snapshot_that_never_mentions_it():
    from backend.models import CanonicalToolCache  # noqa: PLC0415
    from backend.sync import SOURCE_OFFICIAL, SOURCE_WIKI_GADGET  # noqa: PLC0415

    with db.session_scope() as session:
        session.add(_cache_row("current", generation=2, source=SOURCE_OFFICIAL))
        session.add(_cache_row("stale", generation=1, source=SOURCE_OFFICIAL))
        # Synthesized rows carry no generation because no snapshot produced them.
        session.add(_cache_row("gadget", generation=0, source=SOURCE_WIKI_GADGET))
    with db.session_scope() as session:
        # Only the row an older snapshot left behind is retired. Toolhub not
        # listing a wiki's gadget is not Toolhub saying the gadget is gone.
        assert canonical_tools.prune_completed_generation(session, 2, 1) == ["stale"]
    with db.session_scope() as session:
        assert session.get(CanonicalToolCache, "gadget") is not None


def test_publishing_a_snapshot_leaves_synthesized_records_alone():
    from backend.models import CanonicalToolCache  # noqa: PLC0415
    from backend.sync import SOURCE_WIKI_GADGET  # noqa: PLC0415

    with db.session_scope() as session:
        session.add(_cache_row("gadget", generation=0, source=SOURCE_WIKI_GADGET))
    canonical_tools.stage_snapshot_records([{"name": "alpha"}], source_url="source", generation=7)
    with db.session_scope() as session:
        assert canonical_tools.publish_snapshot_stage(session, 7, 1) == []
    with db.session_scope() as session:
        # The live path. Without this boundary every catalog sync would silently
        # empty the catalogue of everything the wikis, rather than Toolhub, know.
        assert session.get(CanonicalToolCache, "gadget") is not None
        assert session.get(CanonicalToolCache, "alpha") is not None


def test_the_snapshot_size_check_counts_only_what_the_snapshot_produced():
    from backend.sync import SOURCE_OFFICIAL, SOURCE_WIKI_GADGET  # noqa: PLC0415

    with db.session_scope() as session:
        session.add(_cache_row("current", generation=2, source=SOURCE_OFFICIAL))
        session.add(_cache_row("gadget", generation=2, source=SOURCE_WIKI_GADGET))
    with db.session_scope() as session:
        # A synthesized row sharing the number must not read as an extra page,
        # or a complete snapshot would fail its own consistency check.
        assert canonical_tools.prune_completed_generation(session, 2, 1) == []


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


def _seed_lifecycle_rows():
    """One archived row and one active row, both matching the query "cite"."""
    from datetime import UTC, datetime

    from backend.models import CanonicalToolCache

    now = datetime.now(UTC).replace(tzinfo=None)
    with db.session_scope() as s:
        for name, lifecycle in (("cite-live", "active"), ("cite-archived", "archived")):
            s.add(
                CanonicalToolCache(
                    tool_name=name,
                    record={"name": name, "title": f"Cite {lifecycle}", "_lifecycle": lifecycle},
                    fetched_at=now,
                    expires_at=now,
                    stale_until=now,
                    generation=1,
                )
            )


def test_search_withholds_archived_tools_unless_asked():
    # This browse path is the offline fallback behind `cachedCanonicalTools`.
    # Before this filter existed it answered a failed catalog search with the
    # archived rows `/search/tools/` withholds, so an outage silently undid the
    # Status filter rather than degrading to the same population.
    _seed_lifecycle_rows()

    default_names = [row["toolName"] for row in canonical_tools.search("cite")]
    widened_names = [row["toolName"] for row in canonical_tools.search("cite", include_archived=True)]

    assert default_names == ["cite-live"]
    assert sorted(widened_names) == ["cite-archived", "cite-live"]


def test_search_by_name_still_returns_an_archived_row():
    # Naming a row is asking for it on purpose, which is the whole reason the
    # census keeps an archived row instead of dropping it.
    _seed_lifecycle_rows()

    assert list(canonical_tools.tools_by_name(["cite-archived"])) == ["cite-archived"]


def _upsert(name: str, **flags: bool) -> None:
    canonical_tools.upsert_records(
        [{"name": name, "title": name.title(), **flags}],
        source_url="https://toolhub.wikimedia.org/api/tools/?page=1",
    )


def test_the_status_flags_are_derived_from_the_record_rather_than_stored_twice():
    """One definition per derived column, and it lives on the validator."""
    from backend.models import CanonicalToolCache  # noqa: PLC0415

    _upsert("dep", deprecated=True)
    _upsert("plain")

    with db.session_scope() as session:
        assert session.get(CanonicalToolCache, "dep").deprecated is True
        assert session.get(CanonicalToolCache, "dep").experimental is False
        assert session.get(CanonicalToolCache, "plain").deprecated is False


def test_a_missing_flag_reads_false_rather_than_unknown():
    """Toolinfo omits the flags far more often than it sets them to false."""
    from backend.models import CanonicalToolCache  # noqa: PLC0415

    canonical_tools.upsert_records(
        [{"name": "bare", "title": "Bare"}], source_url="https://toolhub.wikimedia.org/api/tools/bare/"
    )

    with db.session_scope() as session:
        assert session.get(CanonicalToolCache, "bare").deprecated is False


def test_backfill_status_flags_fills_the_rows_that_predate_the_columns_and_stops():
    """NULL is the cursor, so the pass is idempotent without a completion marker.

    A marker written next to a partial batch can claim done while rows are
    still unfilled; a column that is its own cursor cannot.
    """
    from backend.models import CanonicalToolCache  # noqa: PLC0415

    _upsert("dep", deprecated=True)
    _upsert("exp", experimental=True)
    _upsert("plain")
    with db.session_scope() as session:
        for name in ("dep", "exp", "plain"):
            row = session.get(CanonicalToolCache, name)
            row.deprecated = None
            row.experimental = None

    # One row per batch, so the loop has to come back for the rest rather than
    # reporting the first batch as the whole catalogue.
    assert canonical_tools.backfill_status_flags(batch_size=1) == 3
    assert canonical_tools.backfill_status_flags() == 0

    with db.session_scope() as session:
        assert session.get(CanonicalToolCache, "dep").deprecated is True
        assert session.get(CanonicalToolCache, "exp").experimental is True
        assert session.get(CanonicalToolCache, "plain").deprecated is False


def test_backfill_status_flags_leaves_a_row_it_already_derived_alone():
    """A filled row is not re-derived, so a redeploy costs one empty query."""
    _upsert("dep", deprecated=True)

    assert canonical_tools.backfill_status_flags() == 0


def test_the_offline_fallback_answers_the_same_status_filter_as_the_live_search():
    """A degraded page must not quietly widen the set the reader asked for.

    This path runs when the catalog request failed, which is exactly when the
    reader cannot tell that anything did. Ignoring `status` here would answer a
    filtered search with unfiltered results under a caption about cached data.
    """
    from backend import catalog_facets  # noqa: PLC0415

    _upsert("dep", deprecated=True)
    _upsert("plain")

    everything = canonical_tools.search("")
    active_only = canonical_tools.search("", statuses=frozenset({catalog_facets.STATUS_ACTIVE}))

    assert sorted(row["toolName"] for row in everything) == ["dep", "plain"]
    assert [row["toolName"] for row in active_only] == ["plain"]


def test_the_offline_fallback_treats_an_absent_status_as_every_kind():
    """`None` is "the caller never asked", which must not read as "nothing"."""
    _upsert("dep", deprecated=True)

    assert len(canonical_tools.search("", statuses=None)) == 1
    assert canonical_tools.search("", statuses=frozenset()) == []


def test_backfill_status_flags_stops_at_a_refused_batch_instead_of_the_deploy():
    """It runs from `migrate.py`, after the host has already pulled.

    A refusal there aborts the deploy half-applied. Stopping costs nothing
    because the cursor is the data: the rows still NULL are picked up next
    deploy, and the read path already treats NULL as "not flagged".
    """

    @contextlib.contextmanager
    def _raise_session_scope():
        raise SQLAlchemyError("held by the sync job")
        yield  # pragma: no cover - unreachable, contextmanager requires a yield

    _upsert("dep", deprecated=True)
    with contextlib.ExitStack() as stack:
        stack.enter_context(pytest.MonkeyPatch.context()).setattr(
            canonical_tools.db, "session_scope", _raise_session_scope
        )
        assert canonical_tools.backfill_status_flags() == 0
