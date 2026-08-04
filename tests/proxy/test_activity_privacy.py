"""Privacy tests for shared recent and audit activity."""
# cspell:words unfavorited

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import activity_privacy, db, people_index  # noqa: E402
from backend.models import ActivityRow, User  # noqa: E402
from backend.v1 import _assemble_overlay  # noqa: E402, PLC2701 - integration coverage for the response assembler


def test_private_preference_activity_recognizes_backend_and_upstream_shapes() -> None:
    assert activity_privacy.is_private_preference_activity({"content_type": "favorite"})
    assert activity_privacy.is_private_preference_activity(
        {"action": "favorite-removed", "target": {"type": "favorite"}}
    )
    assert activity_privacy.is_private_preference_activity({"comment": "Added tool to favourites"})
    assert not activity_privacy.is_private_preference_activity(
        {"content_type": "tool", "comment": "Improved my favorite color option"}
    )


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

    overlay = _assemble_overlay(viewer_id)

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
