"""Privacy tests for shared recent and audit activity."""
# cspell:words unfavorited Wikitools Onnnn

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import activity_privacy, catalog_read, db, people_index  # noqa: E402
from backend.models import ActivityRow, Favorite, User  # noqa: E402
from backend.v1_common import assemble_overlay  # noqa: E402, PLC2701 - integration coverage for the response assembler


def test_private_preference_activity_recognizes_backend_and_upstream_shapes() -> None:
    assert activity_privacy.is_private_preference_activity({"content_type": "favorite"})
    assert activity_privacy.is_private_preference_activity(
        {"action": "favorite-removed", "target": {"type": "favorite"}}
    )
    assert activity_privacy.is_private_preference_activity({"comment": "Added tool to favourites"})
    assert not activity_privacy.is_private_preference_activity(
        {"content_type": "tool", "comment": "Improved my favorite color option"}
    )


def test_is_private_preference_activity_rejects_non_dict_rows() -> None:
    assert not activity_privacy.is_private_preference_activity(["not", "a", "dict"])
    assert not activity_privacy.is_private_preference_activity(None)


def test_is_private_preference_activity_matches_exact_action_key() -> None:
    # "favorited" matches PRIVATE_ACTION_KEYS directly, without needing the
    # object-key or add/remove-word heuristics that other tests exercise.
    assert activity_privacy.is_private_preference_activity({"action": "favorited"})


def test_public_activity_rows_rejects_non_list_input() -> None:
    assert activity_privacy.public_activity_rows({"not": "a-list"}) == []
    assert activity_privacy.public_activity_rows(None) == []


def test_filtered_json_tolerates_invalid_and_non_object_payloads() -> None:
    assert activity_privacy.sanitize_overlay_payload(b"not json") == b"not json"
    assert activity_privacy.sanitize_overlay_payload(b"[]") == b"[]"


def test_filtered_json_skips_non_list_key_values() -> None:
    payload = json.dumps({"revisions": "not-a-list", "auditlogs": []}).encode()
    assert activity_privacy.sanitize_overlay_payload(payload) == payload


def test_public_activity_endpoint_sanitizer_filters_results() -> None:
    payload = json.dumps(
        {"results": [{"content_type": "favorite"}, {"content_type": "tool", "name": "public"}]}
    ).encode()

    assert json.loads(
        activity_privacy.sanitize_public_api_payload("https://toolhub.wikimedia.org/api/recent/", payload)
    ) == {"results": [{"content_type": "tool", "name": "public"}]}


def test_overlay_sanitizer_removes_private_rows_from_both_shared_feeds() -> None:
    private_revision = {"content_type": "favorite", "content_id": "secret"}
    private_audit = {"action": "unfavorited", "target": {"type": "favorite", "id": "secret"}}
    public_revision = {"content_type": "tool", "content_id": "public"}
    payload = json.dumps(
        {
            "favorites": ["secret"],
            "revisions": [private_revision, public_revision],
            "auditlogs": [private_audit],
        }
    ).encode()

    sanitized = json.loads(activity_privacy.sanitize_overlay_payload(payload))

    assert sanitized["favorites"] == ["secret"]
    assert sanitized["revisions"] == [public_revision]
    assert sanitized["auditlogs"] == []


def test_overlay_assembler_never_shares_another_users_favorite_activity() -> None:
    db.configure("sqlite://")
    db.init_schema()
    with db.session_scope() as session:
        viewer = User(wm_sub="viewer", username="Viewer")
        other = User(wm_sub="other", username="Other")
        session.add_all([viewer, other])
        session.flush()
        viewer_id = viewer.id
        session.add_all(
            [
                ActivityRow(
                    kind="revisions",
                    client_id="private-favorite",
                    user_id=other.id,
                    row={"content_type": "favorite", "content_id": "secret-tool"},
                ),
                ActivityRow(
                    kind="revisions",
                    client_id="public-tool",
                    user_id=other.id,
                    row={"content_type": "tool", "content_id": "public-tool"},
                ),
            ]
        )

    overlay = assemble_overlay(viewer_id)

    assert overlay["revisions"] == [{"content_type": "tool", "content_id": "public-tool"}]


def test_public_contribution_summary_excludes_favorites_and_local_fallback_events() -> None:
    db.configure("sqlite://")
    db.init_schema()
    with db.session_scope() as session:
        user = User(wm_sub="42", username="Ada")
        session.add(user)
        session.flush()
        person = people_index.link_user(session, user)
        session.add_all(
            [
                ActivityRow(
                    kind="revisions",
                    client_id="official-tool",
                    user_id=user.id,
                    object_type="tool",
                    official_status="official",
                    row={},
                ),
                ActivityRow(
                    kind="revisions",
                    client_id="private-favorite",
                    user_id=user.id,
                    object_type="favorite",
                    official_status="official",
                    row={},
                ),
                ActivityRow(
                    kind="revisions",
                    client_id="failed-tool",
                    user_id=user.id,
                    object_type="tool",
                    official_status="local_fallback",
                    row={},
                ),
            ]
        )
        session.flush()

        summary = people_index.refresh_activity_summaries(session, person_ids={person.id})[0]

        assert summary.contribution_count == 1


def _seed_lists(rows: list[dict]) -> None:
    """Persist one page of the published-list replica."""
    from backend import api_cache  # noqa: PLC0415 - keeps the module-scope import list stable

    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/lists/?page_size=50&page=1",
        api_cache.CacheableResponse(
            status=200, content_type="application/json", body=json.dumps({"results": rows}).encode()
        ),
        fresh_seconds=-10,
        stale_if_error_seconds=0,
    )


def _upstream_list_row(list_id: int, title: str) -> dict:
    """One `/api/recent/` revision exactly as upstream Toolhub spells it."""
    return {
        "content_type": "toollist",
        "content_id": list_id,
        "content_title": title,
        "comment": "Added tool to list",
        "user": {"id": 7, "username": "XAnOnnnn"},
    }


def test_upstream_list_activity_is_public_only_for_a_replicated_published_list() -> None:
    db.configure("sqlite://")
    db.init_schema()
    _seed_lists([{"id": 861, "title": "My Favorite Wikitools", "published": True, "tools": []}])

    # 861 is genuinely published despite the name; 1511 is not in the replica at all.
    assert not activity_privacy.is_private_activity(_upstream_list_row(861, "My Favorite Wikitools"))
    assert activity_privacy.is_private_activity(_upstream_list_row(1511, "L1"))


def test_unknown_list_fails_closed_when_the_replica_is_empty() -> None:
    db.configure("sqlite://")
    db.init_schema()

    # A cold or stale replica must hide list activity rather than leak it.
    assert activity_privacy.is_private_activity(_upstream_list_row(861, "My Favorite Wikitools"))


def test_published_list_ids_excludes_unpublished_and_favorites_lists() -> None:
    db.configure("sqlite://")
    db.init_schema()
    _seed_lists(
        [
            {"id": 861, "title": "Public", "published": True},
            {"id": 900, "title": "Private", "published": False},
            {"id": 901, "title": "Favorites", "published": True, "favorites": True},
        ]
    )

    assert catalog_read.published_list_ids() == frozenset({"861"})


def test_a_users_favorites_list_never_reaches_a_shared_feed() -> None:
    db.configure("sqlite://")
    db.init_schema()
    _seed_lists([{"id": 901, "title": "Favorites", "published": True, "favorites": True}])

    # Toolhub records a favorite as an ordinary toollist revision, so the only
    # thing keeping it private is that a favorites list is never allowlisted.
    assert activity_privacy.is_private_activity(_upstream_list_row(901, "Favorites"))


def test_evolved_list_rows_are_decided_by_official_status_not_the_replica() -> None:
    db.configure("sqlite://")
    db.init_schema()

    published = {"content_type": "list", "content_id": "w1", "_evolved": True, "officialStatus": "official"}
    fallback = {"content_type": "list", "content_id": "w2", "_evolved": True, "officialStatus": "local_fallback"}

    assert not activity_privacy.is_private_activity(published)
    assert activity_privacy.is_private_activity(fallback)


def test_auditlog_shaped_list_rows_are_filtered_on_target_id() -> None:
    db.configure("sqlite://")
    db.init_schema()
    _seed_lists([{"id": 861, "title": "Public", "published": True}])

    assert not activity_privacy.is_private_activity(
        {"action": "list-edited", "target": {"type": "toollist", "id": "861"}}
    )
    assert activity_privacy.is_private_activity({"action": "list-edited", "target": {"type": "toollist", "id": "1511"}})


def test_recent_collection_filters_private_lists_before_it_pages() -> None:
    db.configure("sqlite://")
    db.init_schema()
    _seed_lists([{"id": 861, "title": "Public", "published": True}])
    from backend import api_cache  # noqa: PLC0415 - keeps the module-scope import list stable

    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/recent/?page_size=50&page=1",
        api_cache.CacheableResponse(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "results": [
                        _upstream_list_row(1511, "L1"),
                        {"content_type": "tool", "content_id": "alpha", "comment": "updated"},
                        _upstream_list_row(861, "Public"),
                    ]
                }
            ).encode(),
        ),
        fresh_seconds=-10,
        stale_if_error_seconds=0,
    )

    payload = catalog_read.collection_payload("/api/recent/", {"page_size": "30"})

    # `count` must describe the visible rows, not the unfiltered replica.
    assert payload["count"] == 2
    assert [row["content_id"] for row in payload["results"]] == ["alpha", 861]


def test_overlay_assembler_returns_only_the_viewers_own_favorites() -> None:
    """Favorites are per account: the overlay never carries another user's."""
    db.configure("sqlite://")
    db.init_schema()
    with db.session_scope() as session:
        viewer = User(wm_sub="viewer", username="Viewer")
        other = User(wm_sub="other", username="Other")
        session.add_all([viewer, other])
        session.flush()
        viewer_id = viewer.id
        session.add_all(
            [
                Favorite(user_id=viewer.id, tool_name="viewer-tool", position=0),
                Favorite(user_id=other.id, tool_name="other-secret-tool", position=0),
            ]
        )

    overlay = assemble_overlay(viewer_id)

    assert overlay["favorites"] == ["viewer-tool"]


def test_recent_payload_reports_whether_list_activity_is_available() -> None:
    db.configure("sqlite://")
    db.init_schema()

    # Cold replica: the allowlist is empty, so all list activity is withheld.
    assert catalog_read.collection_payload("/api/recent/", {})["listActivityAvailable"] is False

    _seed_lists([{"id": 861, "title": "Public", "published": True}])

    assert catalog_read.collection_payload("/api/recent/", {})["listActivityAvailable"] is True
    # The flag describes the recent feed only; other collections never carry it.
    assert "listActivityAvailable" not in catalog_read.collection_payload("/api/lists/", {})


def test_the_allowlist_is_read_once_per_batch_not_once_per_row(monkeypatch) -> None:
    db.configure("sqlite://")
    db.init_schema()
    _seed_lists([{"id": 861, "title": "Public", "published": True}])
    reads = 0
    original = catalog_read.published_list_ids

    def counted() -> frozenset[str]:
        nonlocal reads
        reads += 1
        return original()

    monkeypatch.setattr(catalog_read, "published_list_ids", counted)

    rows = [_upstream_list_row(index, f"L{index}") for index in range(20)]
    assert len(activity_privacy.public_activity_rows(rows)) == 0
    assert reads == 1


def test_a_replica_that_raises_is_treated_as_an_empty_allowlist(monkeypatch) -> None:
    def explode() -> frozenset[str]:
        raise RuntimeError("replica is down")

    monkeypatch.setattr(catalog_read, "published_list_ids", explode)

    # Fails closed: a replica that cannot answer allowlists nothing, so every
    # list row stays out of the feed rather than a broken read opening it up.
    assert activity_privacy._published_list_ids() == frozenset()
    assert activity_privacy.is_private_list_activity({"content_type": "list", "content_id": "861"})


def test_is_private_list_activity_rejects_non_dict_rows() -> None:
    assert not activity_privacy.is_private_list_activity(None)
    assert not activity_privacy.is_private_list_activity(["not", "a", "dict"])


def test_a_list_row_naming_no_list_stays_private() -> None:
    # Nothing to check against the allowlist is not permission to show it.
    assert activity_privacy.is_private_list_activity({"content_type": "list"})
    assert activity_privacy.is_private_list_activity({"content_type": "list", "content_id": "   "})


def test_a_caller_supplied_allowlist_is_used_instead_of_the_replica(monkeypatch) -> None:
    def explode() -> frozenset[str]:
        raise AssertionError("the replica must not be read when the caller passes an allowlist")

    monkeypatch.setattr(catalog_read, "published_list_ids", explode)
    row = {"content_type": "list", "content_id": "861"}

    assert not activity_privacy.is_private_list_activity(row, published=frozenset({"861"}))
    assert activity_privacy.is_private_list_activity(row, published=frozenset({"900"}))
