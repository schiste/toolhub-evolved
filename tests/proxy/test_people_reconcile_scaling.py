# SPDX-License-Identifier: GPL-3.0-or-later
"""Reapplying durable mappings must not cost one query per existing mapping."""

import sys
from pathlib import Path

import pytest
from sqlalchemy import event

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, people_index, people_reconcile  # noqa: E402
from backend.models import (  # noqa: E402
    PersonReconciliationMapping,
    PersonReconciliationRun,
    ToolRelationshipEvidence,
)
from backend.sync import AUTHOR_CLAIM_VERIFIED, PERSON_REL_AUTHOR  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()


def _person(session, name, global_id):
    return people_index.ensure_person(session, display_name=name, wikimedia_global_user_id=global_id, source="test")


def _run(session):
    run = PersonReconciliationRun(mode="apply", status="running")
    session.add(run)
    session.flush()
    return run


def _unrelated_mappings(session, count, run=None):
    """Mappings whose source people hold no evidence on the tool under test."""
    run = run or _run(session)
    for index in range(count):
        source = _person(session, f"other-{index}", f"9{index:04d}")
        target = _person(session, f"target-{index}", f"8{index:04d}")
        session.add(
            PersonReconciliationMapping(
                run_id=run.id,
                source_person_id=source.id,
                target_person_id=target.id,
                decision=people_reconcile.MAPPING_AUTO_LINK,
                source_key=f"s{index}",
                target_key=f"t{index}",
            )
        )
    session.flush()


def _count_queries(session, tool_name):
    statements = []

    def record(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(db.engine(), "before_cursor_execute", record)
    try:
        people_reconcile.apply_durable_mappings_for_tool(session, tool_name)
    finally:
        event.remove(db.engine(), "before_cursor_execute", record)
    return len(statements)


def test_query_count_does_not_grow_with_unrelated_mappings():
    with db.session_scope() as session:
        author = _person(session, "Ada", "42")
        session.add(
            ToolRelationshipEvidence(
                tool_name="toolx",
                person_id=author.id,
                relationship_type=PERSON_REL_AUTHOR,
                source="test",
                verification_status=AUTHOR_CLAIM_VERIFIED,
            )
        )
        _unrelated_mappings(session, 5)
        session.flush()
        few = _count_queries(session, "toolx")

        _unrelated_mappings(session, 60)
        session.flush()
        many = _count_queries(session, "toolx")

    # Loading every applied mapping cost one evidence query each: ~2,100 per
    # tool in production, over 90% of the drain's per-tool time. The cost must
    # follow the mappings that can actually move evidence on this tool, of
    # which there are none here.
    assert many == few


def test_a_tool_with_no_evidence_does_no_mapping_work():
    with db.session_scope() as session:
        _unrelated_mappings(session, 10)
        session.flush()
        assert people_reconcile.apply_durable_mappings_for_tool(session, "untouched") == 0


def test_a_matching_mapping_still_moves_its_evidence():
    with db.session_scope() as session:
        source = _person(session, "Legacy label", "77")
        target = _person(session, "Stable person", "78")
        session.add(
            ToolRelationshipEvidence(
                tool_name="toolx",
                person_id=source.id,
                relationship_type=PERSON_REL_AUTHOR,
                source="test",
                verification_status=AUTHOR_CLAIM_VERIFIED,
            )
        )
        session.add(
            PersonReconciliationMapping(
                run_id=_run(session).id,
                source_person_id=source.id,
                target_person_id=target.id,
                decision=people_reconcile.MAPPING_AUTO_LINK,
                source_key="s",
                target_key="t",
            )
        )
        _unrelated_mappings(session, 20)
        session.flush()

        assert people_reconcile.apply_durable_mappings_for_tool(session, "toolx") == 1
        session.flush()
        moved = session.query(ToolRelationshipEvidence).filter_by(tool_name="toolx").one()
        assert moved.person_id == target.id
