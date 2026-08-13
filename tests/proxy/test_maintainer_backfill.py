"""Tests for catalog-wide Toolsadmin maintainer enrichment."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, maintainer_index, toolinfo_authors  # noqa: E402
from backend.author_claims import (  # noqa: E402
    ToolforgeMaintainerProvider,
    ToolsadminMaintainer,
    parse_toolsadmin_maintainer_entries,
)
from backend.models import (  # noqa: E402
    MaintainerBackfillState,
    PersonIdentifier,
    ToolAuthorClaim,
    ToolRelationshipEvidence,
    utcnow,
)
from backend.sync import AUTHOR_CLAIM_TOOLFORGE_MAINTAINER, AUTHOR_CLAIM_VERIFIED  # noqa: E402
import maintainer_backfill  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def test_toolsadmin_parser_prefers_profile_handles():
    html = """
    <table><caption>Maintainers</caption><tbody>
      <tr><td><a href="/profile/renamed-user/">Display Name</a></td></tr>
      <tr><td><a href="/users/SecondUser/">Second display</a></td></tr>
    </tbody></table>
    """

    entries = parse_toolsadmin_maintainer_entries(html)
    assert [(entry.display_name, entry.username) for entry in entries] == [
        ("Display Name", "renamed-user"),
        ("Second display", "SecondUser"),
    ]


def test_toolforge_provider_matches_profile_handle_when_display_name_changed():
    provider = ToolforgeMaintainerProvider(
        fetcher=lambda _name: (
            200,
            '<table><caption>Maintainers</caption><tr><td><a href="/profile/ada/">Ada Lovelace</a></td></tr></table>',
        )
    )
    from backend.models import User

    user = User(id=1, wm_sub="ada-sub", username="ada")
    with db.session_scope() as s:
        rows = provider.verify(
            s,
            user,
            tool_name="toolforge-ada-tool",
            author_names=["Ada Lovelace"],
            toolhub_tool={},
        )

    assert rows[0].verification_status == "verified"


def test_backfill_materializes_stable_public_edges_and_checkpoints(monkeypatch):
    monkeypatch.setattr(
        maintainer_backfill,
        "_candidates",
        lambda: [("toolforge-alpha", {"name": "toolforge-alpha"}, ["alpha"])],
    )
    provider = ToolforgeMaintainerProvider(
        fetcher=lambda _name: (
            200,
            '<table><caption>Maintainers</caption><tr><td><a href="/profile/ada/">Ada</a></td></tr></table>',
        )
    )

    summary = maintainer_backfill.run(limit=1, provider=provider, sleep_fn=lambda _seconds: None)

    assert summary == {"tools": 1, "maintainers": 1, "failed": 0, "requests": 1, "cycleComplete": True, "remaining": 0}
    with db.session_scope() as s:
        edge = s.query(ToolRelationshipEvidence).one()
        identifier = s.query(PersonIdentifier).filter_by(person_id=edge.person_id).one()
        assert identifier.namespace == "toolforge_username"
        assert identifier.normalized_value == "ada"
        assert edge.source == maintainer_index.SOURCE_TOOLFORGE_TOOLSADMIN
        state = s.get(MaintainerBackfillState, maintainer_backfill.STATE_KEY)
        assert state is not None
        assert state.cycles_completed == 1
        assert state.next_tool_name is None


def test_best_claim_rows_keeps_the_first_when_a_later_row_ranks_no_higher():
    older = utcnow()
    newer = older + timedelta(hours=1)
    higher = ToolAuthorClaim(
        tool_name="ranked-tool",
        author_name="Ada",
        toolhub_username="ada",
        user_id=1,
        verification_method=AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
        verification_status=AUTHOR_CLAIM_VERIFIED,
        checked_at=newer,
    )
    lower = ToolAuthorClaim(
        tool_name="ranked-tool",
        author_name="Ada",
        toolhub_username="ada",
        user_id=1,
        verification_method=AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
        verification_status=AUTHOR_CLAIM_VERIFIED,
        checked_at=older,
    )

    best = maintainer_index._best_claim_rows([higher, lower])

    assert best == [higher]


def test_replace_toolforge_maintainer_edges_skips_blank_display_names():
    db.configure("sqlite://")
    db.init_schema()
    with db.session_scope() as s:
        rows = maintainer_index.replace_toolforge_maintainer_edges(
            s,
            "blank-maintainer-tool",
            [("blank-tool", [ToolsadminMaintainer(display_name="", username="blank")], "https://example/blank")],
            checked_at=utcnow(),
        )
    assert rows == []


def test_toolhub_observations_skips_assertions_without_a_display_name(monkeypatch):
    monkeypatch.setattr(
        maintainer_index.toolinfo_authors,
        "author_assertions",
        lambda _tool: [toolinfo_authors.AuthorAssertion(display_name="")],
    )
    assert maintainer_index._toolhub_observations({"author": ["irrelevant"]}) == []


def test_toolhub_observations_skips_actors_with_no_username_or_id():
    observations = maintainer_index._toolhub_observations(
        {"created_by": {}, "modified_by": {"username": "Ada", "id": 7}}
    )
    assert [obs["evidence_key"] for obs in observations] == ["modified_by"]


def test_activity_payload_delegates_to_people_index():
    from backend import people_index

    assert maintainer_index.activity_payload(None) == people_index.activity_payload(None)


def test_summary_status_covers_probable_and_candidate_outcomes():
    from types import SimpleNamespace

    probable = [SimpleNamespace(confidence=70, verification_status="unverified")]
    assert maintainer_index._summary_status(probable) == "probable"

    candidate = [SimpleNamespace(confidence=10, verification_status="unverified")]
    assert maintainer_index._summary_status(candidate) == "candidate"


def test_failed_backfill_preserves_existing_evidence(monkeypatch):
    monkeypatch.setattr(
        maintainer_backfill,
        "_candidates",
        lambda: [("toolforge-alpha", {"name": "toolforge-alpha"}, ["alpha"])],
    )
    with db.session_scope() as s:
        maintainer_index.replace_toolforge_maintainer_edges(
            s,
            "toolforge-alpha",
            [("alpha", [], "https://toolsadmin.example/tools/id/alpha")],
            checked_at=utcnow(),
        )
        # A populated edge is added separately to make the preservation assertion explicit.
        maintainer_index.replace_toolforge_maintainer_edges(
            s,
            "toolforge-alpha",
            [("alpha", parse_toolsadmin_maintainer_entries('<a href="/profile/ada/">Ada</a>'), "https://example")],
            checked_at=utcnow(),
        )
    provider = ToolforgeMaintainerProvider(fetcher=lambda _name: (503, "busy"))

    summary = maintainer_backfill.run(limit=1, provider=provider, sleep_fn=lambda _seconds: None)

    assert summary["failed"] == 1
    with db.session_scope() as s:
        assert s.query(ToolRelationshipEvidence).count() == 1
