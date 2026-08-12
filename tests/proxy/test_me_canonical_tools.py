# SPDX-License-Identifier: GPL-3.0-or-later
"""The signed-in workbench reads the same canonical relationship graph as People."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, people_index  # noqa: E402
from backend.models import CanonicalToolCache, ToolPersonRelationship, User, utcnow  # noqa: E402
from backend.v1_me import _canonical_account_tools  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def test_account_tools_are_read_from_person_relationships_without_upstream_search(monkeypatch):
    with db.session_scope() as session:
        user = User(wm_sub="42", username="Alice", wikimedia_global_user_id="160")
        session.add(user)
        session.flush()
        person = people_index.link_user(session, user)
        session.add(
            CanonicalToolCache(
                tool_name="toolforge-example",
                record={"name": "toolforge-example", "title": "Example", "author": [{"name": "Someone"}]},
                fetched_at=utcnow(),
                expires_at=utcnow(),
                stale_until=utcnow(),
            )
        )
        session.add(
            ToolPersonRelationship(
                tool_name="toolforge-example",
                person_id=person.id,
                relationship_type="maintainer",
                verification_status="verified",
                confidence=100,
                evidence_count=1,
            )
        )
        user_id = user.id

    monkeypatch.setattr(
        "backend.toolhub.public_api_get",
        lambda *_args, **_kwargs: pytest.fail("canonical account read must not search upstream"),
    )
    with db.session_scope() as session:
        user = session.get(User, user_id)
    payload = _canonical_account_tools(user)

    assert payload["counts"] == {"verified": 1, "possible": 0}
    assert payload["verified"][0]["tool"]["name"] == "toolforge-example"
    assert payload["verified"][0]["relationships"][0]["requestedRelationship"] == "maintainer"
    assert payload["searchTerms"] == ["canonical-relationship-graph"]
