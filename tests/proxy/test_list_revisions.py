"""Naming the tools a list revision changed, and folding a day into one row."""

import json
import re
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import api_cache, catalog_read, db, list_revisions  # noqa: E402
from backend.models import ListRevisionChange  # noqa: E402


def _row(revision_id: int, *, list_id: int = 861, user: int = 7, stamp: str, parent: int | None = None) -> dict:
    """One `/api/recent/` list revision exactly as upstream Toolhub spells it."""
    return {
        "content_type": "toollist",
        "content_id": list_id,
        "content_title": "Public",
        "comment": "Added tool to list",
        "id": revision_id,
        "parent_id": parent,
        "timestamp": stamp,
        "user": {"id": user, "username": "Editor"},
    }


def _fresh_db() -> None:
    db.configure("sqlite://")
    db.init_schema()


def _store(revision_id: int, added: list[str], removed: list[str]) -> None:
    with db.session_scope() as session:
        session.merge(ListRevisionChange(revision_id=revision_id, list_id=861, added=added, removed=removed))


# --- grouping -----------------------------------------------------------


def test_a_days_revisions_by_one_editor_collapse_onto_the_newest_timestamp() -> None:
    grouped = list_revisions.group_list_activity(
        [
            _row(3, stamp="2026-08-20T18:00:00Z"),
            _row(2, stamp="2026-08-20T09:00:00Z"),
            _row(1, stamp="2026-08-20T08:00:00Z"),
        ]
    )

    assert len(grouped) == 1
    # Rows arrive newest first, so the group keeps the most recent revision's row.
    assert grouped[0]["timestamp"] == "2026-08-20T18:00:00Z"
    assert grouped[0]["revisionIds"] == [3, 2, 1]


def test_two_editors_of_one_list_stay_two_rows() -> None:
    grouped = list_revisions.group_list_activity(
        [
            _row(2, user=7, stamp="2026-08-20T18:00:00Z"),
            _row(1, user=8, stamp="2026-08-20T09:00:00Z"),
        ]
    )

    # The table has a "Last updated by" column: merging these would put one
    # editor's name on the other's work.
    assert len(grouped) == 2


def test_edits_minutes_apart_across_utc_midnight_stay_two_rows() -> None:
    grouped = list_revisions.group_list_activity(
        [
            _row(2, stamp="2026-08-21T00:02:00Z"),
            _row(1, stamp="2026-08-20T23:58:00Z"),
        ]
    )

    assert len(grouped) == 2


def test_offset_timestamps_are_grouped_by_their_utc_day_not_their_local_one() -> None:
    grouped = list_revisions.group_list_activity(
        [
            _row(2, stamp="2026-08-21T01:00:00+02:00"),
            _row(1, stamp="2026-08-20T23:30:00Z"),
        ]
    )

    # 01:00+02:00 is 23:00 UTC on the 20th, the same UTC day as the other row.
    assert len(grouped) == 1


def test_an_unreadable_timestamp_groups_with_nothing_but_itself() -> None:
    grouped = list_revisions.group_list_activity(
        [_row(2, stamp="not-a-date"), _row(1, stamp="2026-08-20T09:00:00Z")]
    )

    # Merging two days into one row states something false about history; an
    # extra row only repeats a true one.
    assert len(grouped) == 2


def test_tool_rows_pass_through_grouping_untouched() -> None:
    tool = {"content_type": "tool", "content_id": "alpha", "comment": "updated"}

    assert list_revisions.group_list_activity([tool, tool]) == [tool, tool]


def test_evolved_rows_are_never_collapsed_into_one_another() -> None:
    evolved = {
        "content_type": "list",
        "content_id": "w1",
        "_evolved": True,
        "comment": "Evolved: list-created",
        "user": {"username": "Editor"},
        "timestamp": "2026-08-20T09:00:00Z",
    }

    # Two Evolved writes on one day are two distinct events, and collapsing them
    # would drop one from the feed entirely.
    assert list_revisions.group_list_activity([evolved, evolved]) == [evolved, evolved]


def test_group_list_activity_rejects_non_list_input() -> None:
    assert list_revisions.group_list_activity({"not": "a-list"}) == []


# --- naming -------------------------------------------------------------


def test_a_grouped_row_names_every_tool_the_day_added() -> None:
    _fresh_db()
    _store(1, ["alpha"], [])
    _store(2, ["beta"], [])

    named = list_revisions.attach_tool_changes(
        list_revisions.group_list_activity([_row(2, stamp="2026-08-20T10:00:00Z"), _row(1, stamp="2026-08-20T09:00:00Z")])
    )

    # Oldest first: the day's story reads in the order it happened, not the
    # order the feed listed it.
    assert named[0]["toolsAdded"] == ["alpha", "beta"]
    assert named[0]["toolsRemoved"] == []
    assert "revisionIds" not in named[0]


def test_a_tool_added_and_removed_the_same_day_is_reported_in_neither_column() -> None:
    _fresh_db()
    _store(1, ["alpha"], [])
    _store(2, [], ["alpha"])

    named = list_revisions.attach_tool_changes(
        list_revisions.group_list_activity([_row(2, stamp="2026-08-20T10:00:00Z"), _row(1, stamp="2026-08-20T09:00:00Z")])
    )

    # The day left the list exactly as it found it.
    assert named[0]["toolsAdded"] == []
    assert named[0]["toolsRemoved"] == []


def test_a_tool_removed_and_put_back_the_same_day_is_reported_in_neither_column() -> None:
    _fresh_db()
    _store(1, [], ["alpha"])
    _store(2, ["alpha"], [])

    named = list_revisions.attach_tool_changes(
        list_revisions.group_list_activity(
            [_row(2, stamp="2026-08-20T10:00:00Z"), _row(1, stamp="2026-08-20T09:00:00Z")]
        )
    )

    assert named[0]["toolsAdded"] == []
    assert named[0]["toolsRemoved"] == []


def test_a_removal_of_a_tool_added_on_an_earlier_day_is_named_as_a_removal() -> None:
    _fresh_db()
    _store(2, [], ["alpha"])

    named = list_revisions.attach_tool_changes(
        list_revisions.group_list_activity([_row(2, stamp="2026-08-20T10:00:00Z")])
    )

    assert named[0]["toolsRemoved"] == ["alpha"]


def test_unresolved_revisions_leave_the_row_with_its_generic_comment() -> None:
    _fresh_db()

    named = list_revisions.attach_tool_changes(
        list_revisions.group_list_activity([_row(9, stamp="2026-08-20T10:00:00Z")])
    )

    assert named[0]["toolsAdded"] == []
    assert named[0]["comment"] == "Added tool to list"


def test_attach_tool_changes_rejects_non_list_input() -> None:
    assert list_revisions.attach_tool_changes(None) == []


# --- resolving ----------------------------------------------------------


class _Upstream:
    """A stand-in for Toolhub's revision-diff endpoint."""

    def __init__(self, diffs: dict[tuple[int, int], object]) -> None:
        self.diffs = diffs
        self.paths: list[str] = []

    def get(self, path: str, *, read_cache: bool = True) -> object:  # noqa: ARG002 - matches public_api_get
        self.paths.append(path)
        match = re.fullmatch(r"/api/lists/\d+/revisions/(\d+)/diff/(\d+)/", path)
        assert match is not None, path
        diff = self.diffs.get((int(match.group(1)), int(match.group(2))))
        if diff is None:
            raise RuntimeError("no such diff")
        return diff


def _install(monkeypatch, upstream: _Upstream) -> None:
    monkeypatch.setattr(list_revisions.toolhub, "public_api_get", upstream.get)


def test_an_addition_is_named_from_the_forward_diff_alone(monkeypatch) -> None:
    _fresh_db()
    upstream = _Upstream({(5, 6): {"operations": [{"op": "add", "path": "/tools/12", "value": "toolforge-xwiki"}]}})
    _install(monkeypatch, upstream)

    assert list_revisions.resolve_revision(861, 6, 5) == ""
    # The ordinary case costs exactly one upstream request.
    assert len(upstream.paths) == 1
    with db.session_scope() as session:
        assert session.get(ListRevisionChange, 6).added == ["toolforge-xwiki"]


def test_a_removal_is_named_from_the_reverse_diff(monkeypatch) -> None:
    _fresh_db()
    upstream = _Upstream(
        {
            # Upstream sends a bare index when a tool goes away...
            (5, 6): {"operations": [{"op": "remove", "path": "/tools/12"}]},
            # ...but the same change read backwards carries the name.
            (6, 5): {"operations": [{"op": "add", "path": "/tools/12", "value": "toolforge-xwiki"}]},
        }
    )
    _install(monkeypatch, upstream)

    assert list_revisions.resolve_revision(861, 6, 5) == ""
    with db.session_scope() as session:
        stored = session.get(ListRevisionChange, 6)
        assert stored.removed == ["toolforge-xwiki"]
        assert stored.added == []


def test_a_revision_that_touched_no_tool_is_still_recorded(monkeypatch) -> None:
    _fresh_db()
    upstream = _Upstream({(5, 6): {"operations": [{"op": "replace", "path": "/title", "value": "New title"}]}})
    _install(monkeypatch, upstream)

    assert list_revisions.resolve_revision(861, 6, 5) == list_revisions.REASON_NO_TOOL_CHANGE
    # Absence must mean "not looked at yet", never "looked at and found
    # nothing", or the job re-fetches this diff on every run forever.
    with db.session_scope() as session:
        assert session.get(ListRevisionChange, 6) is not None


def test_an_unreadable_diff_is_recorded_with_its_error(monkeypatch) -> None:
    _fresh_db()
    _install(monkeypatch, _Upstream({}))

    assert list_revisions.resolve_revision(861, 6, 5) == list_revisions.REASON_UNREADABLE
    with db.session_scope() as session:
        assert "no such diff" in session.get(ListRevisionChange, 6).last_error


def test_a_lists_first_revision_is_recorded_without_any_request(monkeypatch) -> None:
    _fresh_db()
    upstream = _Upstream({})
    _install(monkeypatch, upstream)

    assert list_revisions.resolve_revision(861, 6, None) == list_revisions.REASON_NO_PARENT
    assert upstream.paths == []


# --- ingest -------------------------------------------------------------


def test_ingest_skips_revisions_it_has_already_resolved(monkeypatch) -> None:
    _fresh_db()
    _store(1, ["alpha"], [])
    upstream = _Upstream({(1, 2): {"operations": [{"op": "add", "path": "/tools/-", "value": "beta"}]}})
    _install(monkeypatch, upstream)

    counts = list_revisions.ingest(
        [_row(1, stamp="2026-08-20T09:00:00Z"), _row(2, stamp="2026-08-20T10:00:00Z", parent=1)],
        pause=lambda _seconds: None,
    )

    assert counts == {"pending": 1, "named": 1, "uneventful": 0, "unreadable": 0}


def test_ingest_resolves_the_newest_revisions_first(monkeypatch) -> None:
    _fresh_db()
    _install(monkeypatch, _Upstream({}))

    list_revisions.ingest(
        [_row(1, stamp="2026-08-20T09:00:00Z"), _row(2, stamp="2026-08-20T10:00:00Z", parent=1)],
        limit=1,
        pause=lambda _seconds: None,
    )

    # A backlog too large for one run still leaves the rows a reader is most
    # likely looking at resolved.
    with db.session_scope() as session:
        assert session.get(ListRevisionChange, 2) is not None
        assert session.get(ListRevisionChange, 1) is None


# --- the payload a reader receives --------------------------------------


def test_recent_payload_groups_and_names_before_it_pages() -> None:
    _fresh_db()
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/lists/?page_size=50&page=1",
        api_cache.CacheableResponse(
            status=200,
            content_type="application/json",
            body=json.dumps({"results": [{"id": 861, "title": "Public", "published": True}]}).encode(),
        ),
        fresh_seconds=-10,
        stale_if_error_seconds=0,
    )
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/recent/?page_size=50&page=1",
        api_cache.CacheableResponse(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "results": [
                        _row(3, stamp="2026-08-20T18:00:00Z"),
                        _row(2, stamp="2026-08-20T09:00:00Z"),
                        _row(1, stamp="2026-08-19T09:00:00Z"),
                    ]
                }
            ).encode(),
        ),
        fresh_seconds=-10,
        stale_if_error_seconds=0,
    )
    _store(1, ["gamma"], [])
    _store(2, ["alpha"], [])
    _store(3, ["beta"], [])

    payload = catalog_read.collection_payload("/api/recent/", {"page_size": "30"})

    # Two UTC days, so two rows -- and `count` describes those, not the three
    # revisions behind them.
    assert payload["count"] == 2
    assert payload["results"][0]["toolsAdded"] == ["alpha", "beta"]
    assert payload["results"][1]["toolsAdded"] == ["gamma"]


# --- edges the ordinary feed does not reach -----------------------------


def test_a_timestamp_without_an_offset_is_read_as_utc_not_as_local_time() -> None:
    naive = {**_row(2, stamp="2026-08-20T09:00:00Z"), "timestamp": "2026-08-20T09:00:00"}
    grouped = list_revisions.group_list_activity([naive, _row(1, stamp="2026-08-20T08:00:00Z")])

    # Reading a bare stamp in the machine's zone would move it across midnight
    # for half the planet, and split one day's edits into two rows there only.
    assert len(grouped) == 1


def test_an_editor_upstream_spells_as_a_bare_name_still_keys_the_group() -> None:
    named = {**_row(2, stamp="2026-08-20T10:00:00Z"), "user": "Editor"}
    other = {**_row(1, stamp="2026-08-20T09:00:00Z"), "user": "Someone else"}
    grouped = list_revisions.group_list_activity([named, {**named, "id": 1}, other])

    # Two rows, not one: the bare string is still an identity, so it separates
    # editors exactly as the object form does.
    assert len(grouped) == 2
    assert grouped[0]["revisionIds"] == [2, 1]


def test_a_revision_with_no_usable_id_joins_its_day_without_polluting_the_lookup() -> None:
    grouped = list_revisions.group_list_activity(
        [_row(2, stamp="2026-08-20T10:00:00Z"), {**_row(1, stamp="2026-08-20T09:00:00Z"), "id": None}]
    )

    # The row is still part of the day, but only ids that could be looked up
    # are collected -- a None in this list would become a failed query later.
    assert len(grouped) == 1
    assert grouped[0]["revisionIds"] == [2]


def test_a_database_the_reader_cannot_reach_costs_tool_names_not_the_page(monkeypatch) -> None:
    _fresh_db()

    def unreachable():
        raise SQLAlchemyError("replica down")

    monkeypatch.setattr(list_revisions.db, "session_scope", unreachable)
    named = list_revisions.attach_tool_changes(
        list_revisions.group_list_activity([_row(2, stamp="2026-08-20T10:00:00Z")])
    )

    # The generic upstream comment is still rendered underneath, so the row
    # says less rather than nothing.
    assert named[0]["toolsAdded"] == []
    assert named[0]["comment"] == "Added tool to list"


def test_a_patch_that_names_no_tool_is_recorded_as_having_changed_none(monkeypatch) -> None:
    _fresh_db()
    upstream = _Upstream({(5, 6): {"operations": [{"op": "add", "path": "/tools/-", "value": {"name": "   "}}]}})
    _install(monkeypatch, upstream)

    # A blank name is not a tool. Storing it would put an empty chip in the feed.
    assert list_revisions.resolve_revision(861, 6, 5) == list_revisions.REASON_NO_TOOL_CHANGE
    with db.session_scope() as session:
        assert session.get(ListRevisionChange, 6).added == []


def test_a_write_that_fails_still_reports_what_the_diff_said(monkeypatch) -> None:
    _fresh_db()
    upstream = _Upstream({(5, 6): {"operations": [{"op": "add", "path": "/tools/-", "value": "beta"}]}})
    _install(monkeypatch, upstream)

    def unreachable():
        raise SQLAlchemyError("write blocked")

    monkeypatch.setattr(list_revisions.db, "session_scope", unreachable)

    # The caller's tally stays true to the diff it read; the row is simply not
    # persisted, and the next run resolves it again.
    assert list_revisions.resolve_revision(861, 6, 5) == ""


def test_pending_revisions_ignores_rows_that_are_not_upstream_list_revisions() -> None:
    _fresh_db()
    tool = {"content_type": "tool", "content_id": "alpha", "id": 9, "parent_id": None}

    assert list_revisions.pending_revisions([tool]) == []


def test_pending_revisions_ignores_a_list_row_whose_ids_are_not_numbers() -> None:
    _fresh_db()
    unnumbered = {**_row(2, stamp="2026-08-20T10:00:00Z"), "content_id": "861"}

    # `content_id` is the list to diff against. A string there is not a list
    # anyone can request, and asking anyway would spend a request to learn so.
    assert list_revisions.pending_revisions([unnumbered]) == []


def test_pending_revisions_asks_nothing_of_the_database_when_the_feed_has_no_lists() -> None:
    _fresh_db()

    assert list_revisions.pending_revisions([]) == []


def test_ingest_pauses_between_upstream_requests_but_not_before_the_first(monkeypatch) -> None:
    _fresh_db()
    _install(monkeypatch, _Upstream({}))
    pauses: list[float] = []

    list_revisions.ingest(
        [_row(1, stamp="2026-08-20T09:00:00Z", parent=0), _row(2, stamp="2026-08-20T10:00:00Z", parent=1)],
        pause=pauses.append,
    )

    # Two revisions, one pause: upstream is volunteer-run, and the first
    # request has nothing to be polite about.
    assert pauses == [list_revisions.REQUEST_PAUSE_SECONDS]


def test_ingest_counts_a_revision_that_changed_no_tool_apart_from_one_that_named_some(monkeypatch) -> None:
    _fresh_db()
    upstream = _Upstream(
        {
            (0, 1): {"operations": [{"op": "add", "path": "/tools/-", "value": "alpha"}]},
            (1, 2): {"operations": [{"op": "replace", "path": "/title", "value": "New title"}]},
        }
    )
    _install(monkeypatch, upstream)

    counts = list_revisions.ingest(
        [_row(1, stamp="2026-08-20T09:00:00Z", parent=0), _row(2, stamp="2026-08-20T10:00:00Z", parent=1)],
        pause=lambda _seconds: None,
    )

    # "Resolved and found nothing" is its own outcome: it is not a failure, and
    # it must not be counted as a rename either.
    assert counts == {"pending": 2, "named": 1, "uneventful": 1, "unreadable": 0}
