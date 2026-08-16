# SPDX-License-Identifier: GPL-3.0-or-later
"""The Phabricator real-name sweep caches public reads and re-judges them."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import phabricator_realname_sync as sync  # noqa: E402
from backend import db, people_index  # noqa: E402
from backend.models import PhabricatorProfileProjection, ToolforgeAccountProjection, utcnow  # noqa: E402
from backend.phabricator_identity import PhabricatorProfile, PhabricatorProfileError  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()


class FakeProvider:
    """Answer profile lookups from a table, recording what was asked."""

    def __init__(self, answers, *, failing=()):
        self.answers = answers
        self.failing = set(failing)
        self.asked = []

    def lookup(self, username):
        self.asked.append(username)
        if username in self.failing:
            raise PhabricatorProfileError("phabricator is down")
        real_name = self.answers.get(username)
        return PhabricatorProfile(username=username, real_name=real_name) if real_name else None


def _account(session, uid_number, developer_username, *, global_name="", disabled=False):
    session.add(
        ToolforgeAccountProjection(
            uid_number=uid_number,
            uid=developer_username.casefold(),
            normalized_uid=developer_username.casefold(),
            developer_username=developer_username,
            normalized_developer_username=developer_username.casefold(),
            wikimedia_global_name=global_name,
            disabled=disabled,
        )
    )


def _person(session, uid_number, developer_username):
    return people_index.ensure_person(
        session,
        display_name=developer_username,
        toolforge_uid_number=uid_number,
        toolforge_username=developer_username,
        source="wikimedia_toolforge_bridge",
    )


def _real_names(session, person_id):
    return {
        row.value
        for row in session.execute(
            select(people_index.PersonIdentifier).where(
                people_index.PersonIdentifier.person_id == person_id,
                people_index.PersonIdentifier.namespace == people_index.NS_PHABRICATOR_REAL_NAME,
                people_index.PersonIdentifier.is_current.is_(True),
            )
        ).scalars()
    }


def _run(provider, **kwargs):
    return sync.run(provider=provider, sleep_fn=lambda _seconds: None, **kwargs)


def test_a_sweep_caches_the_pair_and_records_it_as_a_matching_key():
    with db.session_scope() as session:
        _account(session, "1001", "Gopavasanth")
        person_id = _person(session, "1001", "Gopavasanth").id

    provider = FakeProvider({"Gopavasanth": "Gopa Vasanth"})
    result = _run(provider)

    assert provider.asked == ["Gopavasanth"]
    assert result["recorded"] == 1
    with db.session_scope() as session:
        cached = session.get(PhabricatorProfileProjection, "gopavasanth")
        assert (cached.real_name, cached.missing) == ("Gopa Vasanth", False)
        assert _real_names(session, person_id) == {"Gopa Vasanth"}


def test_a_second_sweep_asks_nothing_and_reaches_the_same_verdict():
    with db.session_scope() as session:
        _account(session, "1001", "Gopavasanth")
        _person(session, "1001", "Gopavasanth")

    _run(FakeProvider({"Gopavasanth": "Gopa Vasanth"}))
    # The cursor wraps on the empty window, so the next sweep re-reads the same
    # account from the cache rather than from the network.
    _run(FakeProvider({}))
    repeat = FakeProvider({})
    result = _run(repeat)

    assert repeat.asked == []
    assert result["recorded"] == 1


def test_an_absent_profile_is_cached_so_it_is_not_re_asked():
    with db.session_scope() as session:
        _account(session, "1001", "Nosuchdev")
        _person(session, "1001", "Nosuchdev")

    _run(FakeProvider({}))
    _run(FakeProvider({}))
    repeat = FakeProvider({})
    _run(repeat)

    assert repeat.asked == []
    with db.session_scope() as session:
        assert session.get(PhabricatorProfileProjection, "nosuchdev").missing is True


def test_the_sul_name_is_asked_only_when_the_developer_name_has_no_profile():
    with db.session_scope() as session:
        _account(session, "1001", "Soda", global_name="SohomSUL")
        _account(session, "1002", "Novel", global_name="NovelHandle")
        _person(session, "1001", "Soda")
        _person(session, "1002", "Novel")

    provider = FakeProvider({"Soda": "Sohom Datta", "NovelHandle": "Novel Person"})
    _run(provider)

    # 1001's cn answered, so its SUL name was never requested. 1002's did not,
    # so the fallback ran on the same sweep.
    assert provider.asked == ["Soda", "Novel", "NovelHandle"]


def test_a_shared_real_name_is_recorded_for_nobody():
    with db.session_scope() as session:
        _account(session, "1001", "Adamone")
        _account(session, "1002", "Adamtwo")
        first = _person(session, "1001", "Adamone").id
        second = _person(session, "1002", "Adamtwo").id

    result = _run(FakeProvider({"Adamone": "Adam Smith", "Adamtwo": "Adam Smith"}))

    assert result["recorded"] == 0
    assert result["refused"] == 2
    with db.session_scope() as session:
        assert _real_names(session, first) == set()
        assert _real_names(session, second) == set()


def test_a_real_name_that_is_only_the_handle_again_is_not_recorded():
    with db.session_scope() as session:
        _account(session, "1001", "Volans")
        person_id = _person(session, "1001", "Volans").id

    result = _run(FakeProvider({"Volans": "volans"}))

    assert result["recorded"] == 0
    with db.session_scope() as session:
        assert _real_names(session, person_id) == set()


def test_a_real_name_that_is_already_another_persons_handle_is_refused():
    with db.session_scope() as session:
        _account(session, "1001", "Gopavasanth")
        _person(session, "1001", "Gopavasanth")
        # Somebody else already publishes under this exact string.
        people_index.ensure_person(
            session,
            display_name="Gopa Vasanth",
            wikimedia_global_user_id="99",
            wiki_username="Gopa Vasanth",
            source="toolhub_oauth",
        )

    result = _run(FakeProvider({"Gopavasanth": "Gopa Vasanth"}))

    assert result["recorded"] == 0


def test_a_departed_account_keeps_its_real_name():
    with db.session_scope() as session:
        _account(session, "1001", "Gopavasanth", disabled=True)
        person_id = _person(session, "1001", "Gopavasanth").id

    assert _run(FakeProvider({"Gopavasanth": "Gopa Vasanth"}))["recorded"] == 1
    with db.session_scope() as session:
        assert _real_names(session, person_id) == {"Gopa Vasanth"}


def test_a_renamed_account_retires_the_name_it_used_to_carry():
    with db.session_scope() as session:
        _account(session, "1001", "Volans")
        person_id = _person(session, "1001", "Volans").id

    _run(FakeProvider({"Volans": "Old Name"}))
    with db.session_scope() as session:
        session.get(PhabricatorProfileProjection, "volans").checked_at = utcnow() - sync.PROFILE_TTL - timedelta(days=1)
        # The cursor sits past this account, so wrap before the re-read.
        sync._set_cursor(session, "")

    result = _run(FakeProvider({"Volans": "New Name"}))

    assert result["retired"] == 1
    with db.session_scope() as session:
        assert _real_names(session, person_id) == {"New Name"}


def test_an_outage_stops_the_window_without_advancing_past_the_failure():
    with db.session_scope() as session:
        for index in range(3):
            _account(session, f"100{index}", f"Dev{index}")
            _person(session, f"100{index}", f"Dev{index}")

    provider = FakeProvider({"Dev0": "Zero Name"}, failing={"Dev1"})
    result = _run(provider)

    assert result["interrupted"] is True
    assert provider.asked == ["Dev0", "Dev1"]

    # The next sweep resumes at the account that failed, not past it.
    resumed = FakeProvider({"Dev1": "One Name", "Dev2": "Two Name"})
    _run(resumed)
    assert resumed.asked == ["Dev1", "Dev2"]


def test_an_outage_is_never_cached_as_a_missing_profile():
    with db.session_scope() as session:
        _account(session, "1001", "Dev1")
        _person(session, "1001", "Dev1")

    _run(FakeProvider({}, failing={"Dev1"}))

    with db.session_scope() as session:
        assert session.get(PhabricatorProfileProjection, "dev1") is None


def test_a_handle_shaped_like_prose_is_never_turned_into_a_profile_url():
    with db.session_scope() as session:
        _account(session, "1001", "Some Person")
        _person(session, "1001", "Some Person")

    provider = FakeProvider({})
    _run(provider)

    assert provider.asked == []
