"""Tests for catalog-wide Toolsadmin maintainer enrichment."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, maintainer_index  # noqa: E402
from backend.author_claims import (  # noqa: E402
    ToolforgeMaintainerProvider,
    parse_toolsadmin_maintainer_entries,
)
from backend.models import MaintainerBackfillState, PersonIdentifier, ToolRelationshipEvidence, utcnow  # noqa: E402
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
        assert identifier.namespace == "wiki_username"
        assert identifier.normalized_value == "ada"
        assert edge.source == maintainer_index.SOURCE_TOOLFORGE_TOOLSADMIN
        state = s.get(MaintainerBackfillState, maintainer_backfill.STATE_KEY)
        assert state is not None
        assert state.cycles_completed == 1
        assert state.next_tool_name is None


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
