# SPDX-License-Identifier: GPL-3.0-or-later
"""Registry lookups walk unresolved labels and record identity, never a claim."""

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, people_index, people_reconcile  # noqa: E402
from backend.models import (  # noqa: E402
    ApiCacheMeta,
    PersonIdentifier,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    UnresolvedAttributionEvidence,
)
from backend.public_identity import WikimediaIdentity  # noqa: E402
from backend.sync import AUTHOR_CLAIM_VERIFIED, PERSON_REL_AUTHOR  # noqa: E402


class FakeRegistry:
    """Resolve only the usernames it was told about, recording every lookup."""

    def __init__(self, accounts):
        self.accounts = accounts
        self.asked = []

    def lookup_username(self, username):
        self.asked.append(username)
        global_id = self.accounts.get(username)
        return WikimediaIdentity(global_user_id=global_id, username=username) if global_id else None


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()


def _label(session, label, tool="toolx"):
    """An attribution observed in catalog text, with no person behind it."""
    session.add(
        UnresolvedAttributionEvidence(
            tool_name=tool,
            observed_label=label,
            normalized_label=label.casefold(),
            relationship_type=PERSON_REL_AUTHOR,
            source="toolhub_author_metadata",
        )
    )
    session.flush()


def _discover(session, registry, **kwargs):
    return people_reconcile.discover_registry_candidates(session, provider=registry, sleep=lambda _s: None, **kwargs)


def _identifier(session, value):
    return (
        session.execute(
            select(PersonIdentifier).where(
                PersonIdentifier.namespace == people_index.NS_WIKIMEDIA_GLOBAL_USER_ID,
                PersonIdentifier.value == value,
            )
        )
        .scalars()
        .first()
    )


def test_a_confirmed_account_becomes_a_person_keyed_on_its_global_id():
    with db.session_scope() as session:
        _label(session, "0xdeadbeef")
        result = _discover(session, FakeRegistry({"0xdeadbeef": "9999"}))

        assert (result["checked"], result["resolved"], result["peopleCreated"]) == (1, 1, 1)
        assert _identifier(session, "9999") is not None


def test_the_new_person_makes_the_label_locally_resolvable():
    with db.session_scope() as session:
        _label(session, "0xdeadbeef")
        _discover(session, FakeRegistry({"0xdeadbeef": "9999"}))
        session.flush()
        handles = {
            row.normalized_value
            for row in session.execute(
                select(PersonIdentifier).where(PersonIdentifier.namespace == people_index.NS_WIKI_USERNAME)
            ).scalars()
        }

    # This is the whole mechanism: the handle index now carries the label, so
    # the ordinary corroborated-handle rule can resolve it once evidence ties
    # that person to a tool. The lookup itself links nothing.
    assert "0xdeadbeef" in handles


def test_a_created_person_publishes_no_relationship_and_is_not_listed():
    with db.session_scope() as session:
        _label(session, "0xdeadbeef")
        _discover(session, FakeRegistry({"0xdeadbeef": "9999"}))
        session.flush()
        listed = people_index.search_people_directory(session, people_index.PeopleDirectoryQuery(query="0xdeadbeef"))

        assert session.query(ToolRelationshipEvidence).count() == 0
        assert session.query(ToolPersonRelationship).count() == 0
    # Publishable by stable identity, but with no relationship it is not
    # listed, so a mistaken lookup never becomes a visible claim about anyone.
    assert listed["count"] == 0


def test_name_shaped_labels_are_never_looked_up():
    with db.session_scope() as session:
        _label(session, "Aaron Liu")
        registry = FakeRegistry({"aaron liu": "9999"})

        result = _discover(session, registry)

        assert registry.asked == []
        assert result["checked"] == 0


def test_a_label_already_matching_a_publishable_handle_is_not_looked_up():
    with db.session_scope() as session:
        people_index.ensure_person(
            session,
            display_name="Ada",
            wikimedia_global_user_id="42",
            wiki_username="0xdeadbeef",
            source="toolhub_oauth",
        )
        _label(session, "0xdeadbeef")
        registry = FakeRegistry({"0xdeadbeef": "9999"})

        result = _discover(session, registry)

    # It is resolvable locally, so spending a request on it would be waste.
    assert registry.asked == []
    assert result["checked"] == 0


def test_an_account_the_registry_does_not_know_creates_nothing():
    with db.session_scope() as session:
        _label(session, "0xdeadbeef")
        result = _discover(session, FakeRegistry({}))

        assert (result["resolved"], result["peopleCreated"]) == (0, 0)


def test_an_account_already_in_the_graph_is_not_duplicated():
    with db.session_scope() as session:
        people_index.ensure_person(session, display_name="Ada", wikimedia_global_user_id="9999", source="toolhub_oauth")
        _label(session, "0xdeadbeef")

        result = _discover(session, FakeRegistry({"0xdeadbeef": "9999"}))

        assert result["resolved"] == 1
        assert result["peopleCreated"] == 0


def test_each_run_is_bounded_and_the_cursor_advances_to_new_labels():
    with db.session_scope() as session:
        for index in range(6):
            _label(session, f"handle{index}", tool=f"tool{index}")
        registry = FakeRegistry({})

        first = _discover(session, registry, label_limit=2)
        asked_first = list(registry.asked)
        session.flush()
        second = _discover(session, registry, label_limit=2)
        asked_second = registry.asked[len(asked_first) :]

        assert first["checked"] == 2
        assert second["checked"] == 2
        # The cursor moved on, so a label the registry does not know is retried
        # at most once per full sweep instead of on every single run.
        assert set(asked_first).isdisjoint(asked_second)
        assert session.get(ApiCacheMeta, people_reconcile.REGISTRY_CURSOR_KEY) is not None


def test_a_withdrawn_label_is_not_looked_up():
    with db.session_scope() as session:
        _label(session, "0xdeadbeef")
        row = session.query(UnresolvedAttributionEvidence).one()
        row.withdrawn_at = people_reconcile.utcnow()
        session.flush()
        registry = FakeRegistry({"0xdeadbeef": "9999"})

        assert _discover(session, registry)["checked"] == 0
        assert registry.asked == []


def test_corroboration_still_governs_publication():
    """The lookup records identity; the existing rule decides the relationship."""
    with db.session_scope() as session:
        _label(session, "0xdeadbeef")
        _discover(session, FakeRegistry({"0xdeadbeef": "9999"}))
        session.flush()
        identifier = _identifier(session, "9999")
        # Independent verified evidence on the tool is what the corroborated
        # handle rule requires before the label resolves to this person.
        session.add(
            ToolRelationshipEvidence(
                tool_name="toolx",
                person_id=identifier.person_id,
                relationship_type=PERSON_REL_AUTHOR,
                source="toolforge_toolsadmin",
                verification_status=AUTHOR_CLAIM_VERIFIED,
            )
        )
        session.flush()
        resolved = people_index.corroborated_handle_person(
            session, tool_name="toolx", display_name="0xdeadbeef", source="toolhub_author_metadata"
        )

        assert resolved is not None
        assert resolved.id == identifier.person_id


def test_retry_after_is_honoured_within_bounds():
    from backend import public_identity

    # Wikimedia's own signal decides the wait, not a delay we guessed.
    assert public_identity.retry_delay_seconds("5") == 5.0
    assert public_identity.retry_delay_seconds("0") == 0.0
    # Clamped so a hostile or mistaken header cannot stall a job for hours.
    assert public_identity.retry_delay_seconds("99999") == public_identity.MAX_RETRY_DELAY_SECONDS
    # Absent or unparseable falls back to a short, safe pause.
    for header in (None, "", "soon", "Wed, 21 Oct 2026 07:28:00 GMT"):
        assert public_identity.retry_delay_seconds(header) == public_identity.DEFAULT_RETRY_DELAY_SECONDS


def test_a_rate_limited_response_is_retried_then_given_up_on():
    from backend import public_identity

    calls = []

    def fetcher(_username):
        calls.append(1)
        return 429, None

    provider = public_identity.WikimediaIdentityProvider(username_fetcher=fetcher)
    # A rate-limited lookup resolves nothing rather than inventing an identity.
    assert provider.lookup_username("0xdeadbeef") is None
    assert len(calls) == 1


def test_lookups_after_the_first_are_spaced_apart():
    with db.session_scope() as session:
        for index in range(3):
            _label(session, f"handle{index}", tool=f"tool{index}")
        sleeps = []

        people_reconcile.discover_registry_candidates(
            session, provider=FakeRegistry({}), sleep=sleeps.append, label_limit=3
        )

    # The first request goes straight out; every later one waits, so a batch
    # never becomes a burst against the registry.
    assert sleeps == [people_reconcile.REGISTRY_MIN_INTERVAL_SECONDS] * 2


def test_a_person_that_cannot_be_created_is_counted_as_resolved_only(monkeypatch):
    with db.session_scope() as session:
        _label(session, "0xdeadbeef")
        monkeypatch.setattr(people_index, "ensure_person", lambda *_a, **_k: None)

        result = _discover(session, FakeRegistry({"0xdeadbeef": "777"}))

        # The registry answered, but nothing was recorded, so the label stays
        # unresolved rather than being counted as progress.
        assert (result["resolved"], result["peopleCreated"]) == (1, 0)


class _Response:
    def __init__(self, status_code, payload=None, retry_after=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = {"Retry-After": retry_after} if retry_after else {}

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_the_real_fetcher_waits_and_retries_when_rate_limited(monkeypatch):
    from backend import public_identity

    ok = {"query": {"globaluserinfo": {"id": "500", "name": "Ada"}}}
    responses = [_Response(429, retry_after="0"), _Response(200, ok)]
    waits = []
    monkeypatch.setattr(public_identity.requests, "get", lambda *_a, **_k: responses.pop(0))
    monkeypatch.setattr(public_identity.time, "sleep", waits.append)

    status, payload = public_identity.WikimediaIdentityProvider._fetch_username("Ada")

    # It waited exactly as long as the service asked, then succeeded.
    assert (status, payload) == (200, ok)
    assert waits == [0.0]


def test_the_real_fetcher_gives_up_after_the_retry_budget(monkeypatch):
    from backend import public_identity

    monkeypatch.setattr(public_identity.requests, "get", lambda *_a, **_k: _Response(503, retry_after="0"))
    monkeypatch.setattr(public_identity.time, "sleep", lambda _s: None)

    status, payload = public_identity.WikimediaIdentityProvider._fetch_username("Ada")

    # A persistently unavailable registry yields nothing rather than looping.
    assert status == 503
    assert payload is None


def test_a_non_json_body_is_treated_as_no_answer(monkeypatch):
    from backend import public_identity

    monkeypatch.setattr(public_identity.requests, "get", lambda *_a, **_k: _Response(200))

    assert public_identity.WikimediaIdentityProvider._fetch_username("Ada") == (200, None)
