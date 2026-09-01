# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend/v1_user.py: /v1/user/* endpoints.

Self-contained: builds its own Flask app + in-memory SQLite database and signs
in test users the same way tests/proxy/test_backend.py does, without importing
from it. Targets the branches of v1_user_delete_evolved_data that only fire
when the caller has a linked person: an owned profile row and evidence-backed
tool relationships to recompute after the delete.
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import authz, db, maintainer_index, security, sync  # noqa: E402
from backend.models import (  # noqa: E402
    Person,
    PersonProfile,
    ToolRelationshipEvidence,
    User,
)


@pytest.fixture
def app():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret", trusted_hosts=backend.LOCAL_TRUSTED_HOSTS + backend.DEFAULT_TRUSTED_HOSTS)
    application.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    security.clear_rate_limits()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def add_user(username="Ada", wm_sub="42", role=authz.ROLE_USER):
    with db.session_scope() as s:
        user = User(wm_sub=wm_sub, username=username, role=role)
        s.add(user)
        s.flush()
        return user.id


def sign_in(client, uid, csrf="tok"):
    with db.session_scope() as s:
        user = s.get(User, uid)
        epoch = user.session_epoch or 0 if user is not None else 0
    with client.session_transaction() as sess:
        sess["uid"] = uid
        sess["csrf"] = csrf
        sess["epoch"] = epoch


def link_person(uid, *, tool_name="alpha-tool", with_profile=True):
    """Give a user a linked Person, a profile row, and evidence-backed tool relationships.

    This exercises the branches of v1_user_delete_evolved_data that only run
    when user.person_id is set: the profile-count/delete block and the
    affected-tools relationship-recompute loop.
    """
    with db.session_scope() as s:
        person = Person(canonical_key=f"test:{uid}", display_name="Ada Lovelace")
        s.add(person)
        s.flush()
        user = s.get(User, uid)
        user.person_id = person.id
        if with_profile:
            s.add(PersonProfile(person_id=person.id, bio="hello"))
        s.add(
            ToolRelationshipEvidence(
                tool_name=tool_name,
                person_id=person.id,
                relationship_type=sync.PERSON_REL_MAINTAINER,
                source=maintainer_index.SOURCE_AUTHOR_CLAIM,
                method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
            )
        )
        return person.id


def delete_evolved_data(client):
    return client.delete("/v1/user/evolved-data/", headers={"X-CSRF-Token": "tok"})


def test_delete_evolved_data_without_linked_person(client):
    """person_id is None: neither the profile block nor the resolve loop fires."""
    uid = add_user()
    sign_in(client, uid)
    resp = delete_evolved_data(client)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["deleted"]["profile"] == 0


def test_delete_evolved_data_with_linked_person_and_profile(client):
    """person_id set, with a profile row and evidence for one tool.

    Covers: the profile count+delete block, the per-tool relationship-resolve
    loop body, and the trailing refresh_activity_summaries call.
    """
    uid = add_user()
    sign_in(client, uid)
    person_id = link_person(uid, tool_name="alpha-tool", with_profile=True)
    resp = delete_evolved_data(client)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["deleted"]["profile"] == 1
    assert body["deleted"]["relationshipEvidence"] == 1
    with db.session_scope() as s:
        assert s.get(PersonProfile, person_id) is None


def test_delete_evolved_data_with_linked_person_no_profile(client):
    """person_id set but no profile row: profile_count stays 0, delete is a no-op."""
    uid = add_user()
    sign_in(client, uid)
    link_person(uid, tool_name="beta-tool", with_profile=False)
    resp = delete_evolved_data(client)
    assert resp.status_code == 200
    assert resp.get_json()["deleted"]["profile"] == 0
