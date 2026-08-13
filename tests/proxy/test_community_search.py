# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend/community_search.py.

Self-contained: configures its own in-memory SQLite database directly through
backend.db (no Flask app is needed, since community_search's public surface
is plain functions over a Session), following the pattern already used by
tests/proxy/test_people_reconcile.py.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import community_search, db, sync  # noqa: E402
from backend.models import (  # noqa: E402
    CanonicalToolCache,
    Person,
    PersonProfile,
    ToolPersonRelationship,
    utcnow,
)


def _configure() -> None:
    db.configure("sqlite://")
    db.init_schema()


def make_person(s, display_name, *, canonical_key=None):
    person = Person(
        canonical_key=canonical_key or f"display:{display_name.casefold()}",
        display_name=display_name,
        identity_quality="display_name",
    )
    s.add(person)
    s.flush()
    s.add(PersonProfile(person_id=person.id, visibility="public"))
    s.flush()
    return person


def make_tool(s, tool_name, **record_overrides):
    now = utcnow()
    record = {"name": tool_name, "title": tool_name.title(), **record_overrides}
    row = CanonicalToolCache(
        tool_name=tool_name,
        record=record,
        expires_at=now,
        stale_until=now,
    )
    s.add(row)
    s.flush()
    return row


# ---------------------------------------------------------------------------
# _text_values / _normalized_values: multilingual (dict) and list-shaped JSON


def test_text_values_recurses_into_nested_dicts_and_lists():
    assert set(community_search._text_values({"en": "Hello", "fr": "Bonjour"})) == {"Hello", "Bonjour"}
    assert community_search._text_values(["alpha", "beta"]) == ["alpha", "beta"]
    assert set(community_search._text_values({"tags": ["one", "two"]})) == {"one", "two"}
    assert community_search._text_values(42) == []


# ---------------------------------------------------------------------------
# _tool_match: author entries that are plain strings and non-dict/non-string


def test_tool_match_handles_string_authors_and_skips_unknown_author_shapes():
    record = {"author": ["Ada Lovelace", 42]}
    match = community_search._tool_match(record, "some-tool", "Ada Lovelace")
    assert match is not None
    rank, explanation = match
    assert explanation["field"] == "author"
    assert explanation["value"] == "Ada Lovelace"


def test_tool_match_returns_none_when_nothing_matches():
    record = {"title": "Something else", "author": [42, None]}
    assert community_search._tool_match(record, "some-tool", "unrelated query") is None


# ---------------------------------------------------------------------------
# _result_values: unresolved-attribution and generic tool ("else") shapes


def test_result_values_covers_unresolved_attribution_and_tool_kinds():
    assert community_search._result_values(
        {"kind": "unresolved_attribution", "attribution": {"label": "Some Label"}}
    ) == ["some label"]
    assert community_search._result_values({"kind": "tool", "tool": {"name": "Alpha", "title": "Alpha Tool"}}) == [
        "alpha",
        "alpha tool",
    ]
    assert community_search._result_values({"kind": "tool"}) == []


# ---------------------------------------------------------------------------
# _fold_same_label_evidence: standalone branch (0 or >1 exact-label matches)


def test_fold_same_label_evidence_keeps_ambiguous_and_unmatched_labels_standalone():
    _configure()
    with db.session_scope() as s:
        person = make_person(s, "Magnus Manske")
        item = community_search._person_item(
            {"id": person.public_id, "displayName": "Magnus Manske", "identifiers": []}, {"identity"}, []
        )
        exact_people, standalone, folded = community_search._fold_same_label_evidence(
            [item], [{"label": "Nobody Matching"}], "magnus manske"
        )
        assert folded == 0
        assert standalone == [{"label": "Nobody Matching"}]
        assert len(exact_people) == 1

        person_two = make_person(s, "Magnus Manske", canonical_key="display:magnus-manske-2")
        item_two = community_search._person_item(
            {"id": person_two.public_id, "displayName": "Magnus Manske", "identifiers": []}, {"identity"}, []
        )
        exact_people, standalone, folded = community_search._fold_same_label_evidence(
            [item, item_two], [{"label": "Magnus Manske"}], "magnus manske"
        )
        assert folded == 0
        assert standalone == [{"label": "Magnus Manske"}]
        assert len(exact_people) == 2


# ---------------------------------------------------------------------------
# search_community: empty query returns the plain directory-only shape


def test_search_community_empty_query_returns_directory_only_shape():
    _configure()
    with db.session_scope() as s:
        make_person(s, "Ada Lovelace")
        payload = community_search.search_community(s, community_search.CommunitySearchQuery(query=""))
        assert payload["primaryResults"] == payload["results"]
        assert payload["relatedTools"] == {"count": 0, "results": [], "truncated": False}
        assert payload["unresolvedEvidence"] == {"count": 0, "results": [], "truncated": False}
        assert payload["otherMatches"] == {"count": 0, "results": [], "truncated": False}
        assert payload["counts"] == {"people": 1, "accounts": 0, "tools": 0, "unresolvedAttributions": 0}
        assert payload["totalCount"] == 1
        assert payload["accountSync"]["status"] == "unavailable"
        assert payload["results"][0]["matchBasis"] == ["directory"]


# ---------------------------------------------------------------------------
# search_community: a tool that is both an exact person's related tool AND a
# direct text match must merge into one item carrying both match explanations


def test_search_community_merges_relationship_and_text_matches_for_the_same_tool():
    _configure()
    with db.session_scope() as s:
        person = make_person(s, "Magnus")
        make_tool(s, "magnus-tool")
        s.add(
            ToolPersonRelationship(
                tool_name="magnus-tool",
                person_id=person.id,
                relationship_type=sync.PERSON_REL_AUTHOR,
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                confidence=90,
                evidence_count=1,
                toolhub_canonical=True,
            )
        )
        s.flush()

        payload = community_search.search_community(s, community_search.CommunitySearchQuery(query="Magnus"))
        related = payload["relatedTools"]["results"]
        assert len(related) == 1
        related_item = related[0]
        assert related_item["tool"]["name"] == "magnus-tool"
        # relationship match plus the merged direct name-text match
        assert related_item["matchBasis"] == ["relationship", "name"]
        assert related_item["match"]["reason"] == "person_relationship"
        assert related_item["textMatch"]["reason"] == "name_prefix"


# ---------------------------------------------------------------------------
# search_community: ordering="name" sorts primary results by display value


def test_search_community_orders_by_name_when_requested():
    _configure()
    with db.session_scope() as s:
        make_person(s, "Zeta Person")
        make_person(s, "Alpha Person", canonical_key="display:alpha-person")

        payload = community_search.search_community(
            s, community_search.CommunitySearchQuery(query="Person", ordering="name")
        )
        names = [item["person"]["displayName"] for item in payload["primaryResults"]]
        assert names == sorted(names)
        assert names == ["Alpha Person", "Zeta Person"]


# ---------------------------------------------------------------------------
# search_community: a related person outside the linked-account id set gets no
# "account" match basis


def test_search_community_skips_account_basis_for_a_person_outside_linked_ids(monkeypatch):
    _configure()
    with db.session_scope() as s:
        outsider = {"id": "unlinked-person-id", "displayName": "Distinct Name", "identifiers": []}
        real_search = community_search.people_index.search_people_directory

        def fake_search(session, directory_query):
            if directory_query.public_ids:
                return {"results": [outsider], "count": 1}
            return real_search(session, directory_query)

        monkeypatch.setattr(community_search.people_index, "search_people_directory", fake_search)
        monkeypatch.setattr(
            community_search.account_directory,
            "search_accounts",
            lambda session, account_query: {"results": [{"personId": "linked-only-id"}], "count": 1, "sync": {}},
        )

        payload = community_search.search_community(
            s, community_search.CommunitySearchQuery(query="Distinct", contributor=True)
        )

        outsider_items = [
            item
            for item in payload["primaryResults"]
            if item.get("kind") == "person" and item["person"]["id"] == "unlinked-person-id"
        ]
        for item in outsider_items:
            assert "account" not in item["matchBasis"]
        assert isinstance(payload["counts"]["people"], int)
