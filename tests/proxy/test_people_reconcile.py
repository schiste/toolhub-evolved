# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for deterministic people and evidence reconciliation."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, people_reconcile  # noqa: E402
from backend.models import (  # noqa: E402
    CanonicalToolCache,
    Person,
    PersonIdentifier,
    PersonReconciliationConflict,
    PersonReconciliationQueue,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    User,
    utcnow,
)


def _configure() -> None:
    db.configure("sqlite://")
    db.init_schema()


def test_apply_links_account_by_immutable_toolhub_id_and_is_idempotent():
    _configure()
    with db.session_scope() as s:
        user = User(wm_sub="42", username="Alice")
        s.add(user)
        s.add(
            CanonicalToolCache(
                tool_name="alias-tool",
                record={
                    "name": "alias-tool",
                    "author": [{"name": "Alice", "developer_username": "Alice", "wiki_username": "AliceWiki"}],
                    "created_by": {"id": 42, "username": "Alice"},
                },
                expires_at=utcnow(),
                stale_until=utcnow(),
            )
        )
        s.flush()

        dry_summary = people_reconcile.run(s, mode=people_reconcile.MODE_DRY_RUN)
        assert dry_summary["toolsRebuilt"] == 0
        assert s.query(ToolRelationshipEvidence).count() == 0

        apply_summary = people_reconcile.run(s, mode=people_reconcile.MODE_APPLY)
        assert apply_summary["toolsRebuilt"] == 1
        assert s.query(Person).count() == 1
        assert s.query(ToolPersonRelationship).count() == 2
        person = s.query(Person).one()
        public_id = person.public_id
        assert user.person_id == person.id
        assert {row.namespace for row in s.query(PersonIdentifier)} == {
            "toolhub_user_id",
            "toolhub_username",
            "wiki_username",
        }

        rerun_summary = people_reconcile.run(s, mode=people_reconcile.MODE_APPLY)
        assert rerun_summary["toolsRebuilt"] == 1
        assert s.query(Person).one().public_id == public_id
        assert s.query(ToolPersonRelationship).count() == 2


def test_display_names_remain_non_merging_conflicts():
    _configure()
    with db.session_scope() as s:
        s.add_all(
            [
                Person(canonical_key="display:bob-one", display_name="Bob", identity_quality="display_name"),
                Person(canonical_key="display:bob-two", display_name="Bob", identity_quality="display_name"),
            ]
        )
        s.flush()

        summary = people_reconcile.run(s, mode=people_reconcile.MODE_APPLY)

        assert summary["conflicts"] == 1
        assert s.query(Person).count() == 2
        assert s.query(PersonReconciliationConflict).count() == 1


def test_incremental_queue_deduplicates_and_rebuilds_one_changed_tool():
    _configure()
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="queued-tool",
                record={
                    "name": "queued-tool",
                    "author": [{"name": "Queue User", "developer_username": "queue-user"}],
                },
                expires_at=utcnow(),
                stale_until=utcnow(),
            )
        )

    assert people_reconcile.enqueue_tool_names(["queued-tool", "queued-tool"], reason="canonical_fetch") == 1
    summary = people_reconcile.process_queue(limit=1)

    assert summary == {"claimed": 1, "processed": 1, "failed": 0}
    with db.session_scope() as s:
        assert s.get(PersonReconciliationQueue, "queued-tool") is None
        assert s.query(ToolPersonRelationship).filter_by(tool_name="queued-tool").count() == 1

    assert people_reconcile.process_queue(limit=1) == {"claimed": 0, "processed": 0, "failed": 0}
