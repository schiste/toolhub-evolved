# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for deterministic historical people reconciliation."""

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
    PersonReconciliationMapping,
    ToolMaintainerEdge,
    ToolPersonRelationship,
    utcnow,
)


def _configure() -> None:
    db.configure("sqlite://")
    db.init_schema()


def test_dry_run_is_audited_and_apply_reunifies_cooccurring_stable_aliases():
    _configure()
    with db.session_scope() as s:
        s.add_all(
            [
                Person(canonical_key="toolhub:alice", display_name="Alice", identity_quality="stable"),
                Person(canonical_key="wiki:alicewiki", display_name="Alice", identity_quality="stable"),
                ToolMaintainerEdge(
                    tool_name="alias-tool",
                    maintainer_key="toolhub:alice",
                    maintainer_display_name="Alice",
                    toolhub_username="Alice",
                    wiki_username="AliceWiki",
                    source="toolhub_author_metadata",
                    method="toolhub_author_metadata",
                    confidence=45,
                ),
            ]
        )
        s.flush()

        dry_summary = people_reconcile.run(s, mode=people_reconcile.MODE_DRY_RUN)
        assert dry_summary["mergeCandidates"] == 1
        assert s.query(Person).count() == 2
        assert s.query(PersonReconciliationMapping).count() == 2

        apply_summary = people_reconcile.run(s, mode=people_reconcile.MODE_APPLY)
        assert apply_summary["mergedPeople"] == 1
        assert s.query(Person).count() == 1
        assert s.query(PersonIdentifier).count() == 2
        assert s.query(ToolPersonRelationship).count() == 1
        person = s.query(Person).one()
        assert person.canonical_key == "toolhub:alice"

        rerun_summary = people_reconcile.run(s, mode=people_reconcile.MODE_APPLY)
        assert rerun_summary["mergedPeople"] == 0
        assert s.query(Person).count() == 1
        assert s.query(ToolPersonRelationship).count() == 1


def test_cache_author_identifiers_are_materialized_and_display_names_do_not_merge():
    _configure()
    with db.session_scope() as s:
        s.add_all(
            [
                Person(canonical_key="toolhub:bob", display_name="Bob", identity_quality="stable"),
                Person(canonical_key="wiki:bobwiki", display_name="Bob", identity_quality="stable"),
                Person(canonical_key="display:bob-one", display_name="Bob", identity_quality="display_name"),
                Person(canonical_key="display:bob-two", display_name="Bob", identity_quality="display_name"),
                CanonicalToolCache(
                    tool_name="cached-alias-tool",
                    record={
                        "name": "cached-alias-tool",
                        "author": [{"name": "Bob", "developer_username": "Bob", "wiki_username": "BobWiki"}],
                    },
                    expires_at=utcnow(),
                    stale_until=utcnow(),
                ),
            ]
        )
        s.flush()

        summary = people_reconcile.run(s, mode=people_reconcile.MODE_APPLY)

        assert summary["canonicalCacheTools"] == 1
        assert s.query(Person).count() == 3
        assert s.query(PersonReconciliationConflict).count() == 1
        assert s.query(ToolPersonRelationship).count() == 1
        assert s.query(Person).filter(Person.canonical_key == "toolhub:bob").one()
