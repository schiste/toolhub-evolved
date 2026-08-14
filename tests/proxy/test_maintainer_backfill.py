"""Tests for catalog-wide Toolsadmin maintainer enrichment."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, identity_graph, maintainer_index, people_index, toolinfo_authors  # noqa: E402
from backend.author_claims import (  # noqa: E402
    ToolforgeMaintainerProvider,
    ToolsadminMaintainer,
    parse_toolsadmin_maintainer_entries,
)
from backend.models import (  # noqa: E402
    MaintainerBackfillState,
    PersonIdentifier,
    ToolAuthorClaim,
    ToolforgeAccountProjection,
    ToolforgeMembershipProjection,
    ToolRelationshipEvidence,
    UnresolvedAttributionEvidence,
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


def test_toolforge_provider_uses_sul_bound_ldap_membership_not_html():
    provider = ToolforgeMaintainerProvider(fetcher=lambda _name: pytest.fail("must not fetch HTML"))
    from backend.models import User

    user = User(id=1, wm_sub="ada-sub", username="Ada", wikimedia_global_user_id="160")
    with db.session_scope() as s:
        s.add(
            ToolforgeAccountProjection(
                uid_number="9001",
                uid="ada-shell",
                normalized_uid="ada-shell",
                developer_username="AdaDeveloper",
                normalized_developer_username="adadeveloper",
                wikimedia_global_user_id="160",
            )
        )
        s.add(ToolforgeMembershipProjection(uid_number="9001", tool_name="ada-tool"))
        s.flush()
        rows = provider.verify(
            s,
            user,
            tool_name="toolforge-ada-tool",
            author_names=["Ada Lovelace"],
            toolhub_tool={},
        )

    assert rows[0].verification_status == "verified"
    assert rows[0].evidence_payload["toolforgeUidNumber"] == "9001"
    assert rows[0].evidence_payload["toolforgeDeveloperUsername"] == "AdaDeveloper"


def test_backfill_keeps_unresolved_html_labels_out_of_identity_graph(monkeypatch):
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

    assert summary == {
        "tools": 1,
        "maintainers": 0,
        "failed": 0,
        "requests": 1,
        "durableToolsSkipped": 0,
        "cycleComplete": True,
        "remaining": 0,
    }
    with db.session_scope() as s:
        assert s.query(ToolRelationshipEvidence).count() == 0
        unresolved = s.query(UnresolvedAttributionEvidence).one()
        assert unresolved.normalized_label == "ada"
        assert unresolved.verification_status == "unverified"
        state = s.get(MaintainerBackfillState, maintainer_backfill.STATE_KEY)
        assert state is not None
        assert state.cycles_completed == 1
        assert state.next_tool_name is None


def test_toolsadmin_label_verifies_only_with_bound_ldap_membership():
    with db.session_scope() as s:
        person = people_index.ensure_person(
            s,
            display_name="Ada Lovelace",
            wikimedia_global_user_id="160",
            source="test",
        )
        account = ToolforgeAccountProjection(
            uid_number="9001",
            uid="ada-shell",
            normalized_uid="ada-shell",
            developer_username="AdaDeveloper",
            normalized_developer_username="adadeveloper",
            wikimedia_global_user_id="160",
        )
        s.add(account)
        s.add(ToolforgeMembershipProjection(uid_number="9001", tool_name="alpha"))
        s.flush()
        identity_graph.bind_toolforge_account(
            s,
            account=account,
            person=person,
            proof_method=identity_graph.PROOF_TOOLFORGE_SUL,
            confidence=100,
            evidence={"wikimediaGlobalUserId": "160"},
        )
        rows = maintainer_index.replace_toolforge_maintainer_edges(
            s,
            "toolforge-alpha",
            [
                (
                    "alpha",
                    [ToolsadminMaintainer(display_name="Ada", username="AdaDeveloper")],
                    "https://toolsadmin.wikimedia.org/tools/id/alpha",
                )
            ],
            checked_at=utcnow(),
        )

    assert len(rows) == 1
    assert rows[0].verification_status == "verified"
    assert rows[0].confidence == 100
    assert rows[0].evidence_payload["membershipValidatedBy"] == "toolforge_ldap"


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
        # A populated unresolved label is added separately to make preservation explicit.
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
        assert s.query(ToolRelationshipEvidence).count() == 0
        assert s.query(UnresolvedAttributionEvidence).count() == 1


def test_backfill_skips_tools_covered_by_authoritative_ldap_projection(monkeypatch):
    monkeypatch.setattr(
        maintainer_backfill,
        "_candidates",
        lambda: [
            ("ldap-covered", {"name": "ldap-covered"}, ["covered"]),
            ("fallback-only", {"name": "fallback-only"}, ["fallback"]),
        ],
    )
    with db.session_scope() as s:
        person = maintainer_index.people_index.ensure_person(
            s,
            display_name="LDAP maintainer",
            toolforge_uid_number="100",
            source="test",
        )
        s.add(
            ToolRelationshipEvidence(
                tool_name="ldap-covered",
                person_id=person.id,
                relationship_type="maintainer",
                source=maintainer_index.SOURCE_TOOLFORGE_LDAP,
                method="toolforge_ldap_membership",
                verification_status="verified",
            )
        )
    requested = []
    provider = ToolforgeMaintainerProvider(
        fetcher=lambda name: requested.append(name) or (200, '<a href="/profile/fallback-user/">Fallback user</a>')
    )

    summary = maintainer_backfill.run(limit=10, provider=provider, sleep_fn=lambda _seconds: None)

    assert requested == ["fallback"]
    assert summary["durableToolsSkipped"] == 1
    assert summary["tools"] == 1


def test_backfill_remaining_uses_the_persisted_cursor_position(monkeypatch):
    monkeypatch.setattr(
        maintainer_backfill,
        "_candidates",
        lambda: [(name, {"name": name}, [name]) for name in ("alpha", "beta", "gamma", "omega")],
    )
    with db.session_scope() as s:
        s.add(MaintainerBackfillState(key=maintainer_backfill.STATE_KEY, next_tool_name="beta"))
    provider = ToolforgeMaintainerProvider(fetcher=lambda _name: (404, ""))

    summary = maintainer_backfill.run(limit=1, provider=provider, sleep_fn=lambda _seconds: None)

    assert summary["tools"] == 1
    assert summary["remaining"] == 1
