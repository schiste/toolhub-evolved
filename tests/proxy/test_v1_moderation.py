# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend/v1_moderation.py: the /v1/moderation/* endpoints.

Self-contained: builds its own Flask app + in-memory SQLite database and signs
in test users the same way tests/proxy/test_backend.py does, without importing
from it.
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import authz, db, people_reconcile, security  # noqa: E402
from backend.models import (  # noqa: E402
    Person,
    PersonReconciliationConflict,
    PersonReconciliationMapping,
    PersonReconciliationRun,
    User,
)


@pytest.fixture
def app():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
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


def make_admin(client, username="Operator", wm_sub="operator"):
    admin_id = add_user(username=username, wm_sub=wm_sub, role=authz.ROLE_ADMIN)
    sign_in(client, admin_id)
    return admin_id


HEADERS = {"X-CSRF-Token": "tok"}


# ---------------------------------------------------------------------------
# people-candidates


def test_people_candidates_rejects_an_unsupported_decision_filter(client):
    make_admin(client)
    resp = client.get("/v1/moderation/people-candidates/?decision=bogus")
    assert resp.status_code == 400
    assert "decision must be" in resp.get_json()["error"]


def make_mapping(*, source_id, target_id, decision="candidate", confidence=80):
    with db.session_scope() as s:
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        mapping = PersonReconciliationMapping(
            run_id=run.id,
            source_person_id=source_id,
            target_person_id=target_id,
            source_key=f"source-{source_id}",
            target_key=f"target-{target_id}",
            decision=decision,
            reason="test",
            confidence=confidence,
        )
        s.add(mapping)
        s.flush()
        return mapping.id


def make_person(display_name, canonical_key):
    with db.session_scope() as s:
        person = Person(canonical_key=canonical_key, display_name=display_name, identity_quality="display_name")
        s.add(person)
        s.flush()
        return person.id


def test_people_candidate_update_requires_a_json_object_body(client):
    make_admin(client)
    resp = client.put("/v1/moderation/people-candidates/1/", data="not-json", headers=HEADERS)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "moderation body must be a JSON object"


def test_people_candidate_update_rejects_an_unsupported_decision(client):
    make_admin(client)
    resp = client.put(
        "/v1/moderation/people-candidates/1/",
        json={"decision": "candidate"},
        headers=HEADERS,
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "decision must be approved, rejected, or split"


def test_people_candidate_update_reports_a_missing_mapping(client):
    make_admin(client)
    resp = client.put(
        "/v1/moderation/people-candidates/999999/",
        json={"decision": "rejected"},
        headers=HEADERS,
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "people candidate not found"


def test_people_candidate_update_rejects_a_mapping_with_a_durable_decision_already(client):
    make_admin(client)
    source_id = make_person("Source Person", "candidate-key:source")
    target_id = make_person("Target Person", "candidate-key:target")
    mapping_id = make_mapping(source_id=source_id, target_id=target_id, decision="rejected")
    resp = client.put(
        f"/v1/moderation/people-candidates/{mapping_id}/",
        json={"decision": "approved"},
        headers=HEADERS,
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "people candidate already has a durable decision"


def test_people_candidate_update_reports_a_reconciliation_error_and_rolls_back(client):
    make_admin(client)
    # Same person on both sides is rejected by apply_mapping with
    # PersonReconciliationError("mapping source and target must differ").
    person_id = make_person("Solo Person", "candidate-key:solo")
    mapping_id = make_mapping(source_id=person_id, target_id=person_id, decision="candidate")
    resp = client.put(
        f"/v1/moderation/people-candidates/{mapping_id}/",
        json={"decision": "approved"},
        headers=HEADERS,
    )
    assert resp.status_code == 409
    assert "must differ" in resp.get_json()["error"]
    with db.session_scope() as s:
        # Rolled back: the decision write from the handler must not have stuck.
        row = s.get(PersonReconciliationMapping, mapping_id)
        assert row.decision == "candidate"


def test_people_candidate_update_rejected_decision_does_not_call_apply_mapping(client):
    make_admin(client)
    source_id = make_person("Reject Source", "candidate-key:reject-source")
    target_id = make_person("Reject Target", "candidate-key:reject-target")
    mapping_id = make_mapping(source_id=source_id, target_id=target_id, decision="candidate")
    resp = client.put(
        f"/v1/moderation/people-candidates/{mapping_id}/",
        json={"decision": "rejected", "reviewNotes": "not a match"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["affectedTools"] == 0
    assert body["candidate"]["decision"] == "rejected"
    assert body["candidate"]["reviewNotes"] == "not a match"


# ---------------------------------------------------------------------------
# people-conflicts


def test_people_conflicts_rejects_an_unsupported_status_filter(client):
    make_admin(client)
    resp = client.get("/v1/moderation/people-conflicts/?status=bogus")
    assert resp.status_code == 400
    assert "status must be" in resp.get_json()["error"]


def make_conflict(*, status="pending"):
    with db.session_scope() as s:
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        conflict = PersonReconciliationConflict(
            run_id=run.id,
            conflict_type="ambiguous_display_name",
            value="alex",
            status=status,
        )
        s.add(conflict)
        s.flush()
        return conflict.id


def test_people_conflict_update_requires_a_json_object_body(client):
    make_admin(client)
    conflict_id = make_conflict()
    resp = client.put(f"/v1/moderation/people-conflicts/{conflict_id}/", data="not-json", headers=HEADERS)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "moderation body must be a JSON object"


def test_people_conflict_update_rejects_an_unsupported_status(client):
    make_admin(client)
    conflict_id = make_conflict()
    resp = client.put(
        f"/v1/moderation/people-conflicts/{conflict_id}/",
        json={"status": "bogus"},
        headers=HEADERS,
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "status must be pending, resolved, or dismissed"


def test_people_conflict_update_reports_a_missing_conflict(client):
    make_admin(client)
    resp = client.put(
        "/v1/moderation/people-conflicts/999999/",
        json={"status": "resolved"},
        headers=HEADERS,
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "people conflict not found"


def test_people_conflict_update_resolves_and_records_the_reviewer(client):
    admin_id = make_admin(client)
    conflict_id = make_conflict()
    resp = client.put(
        f"/v1/moderation/people-conflicts/{conflict_id}/",
        json={"status": "resolved", "reviewNotes": "checked"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.get_json()["conflict"]
    assert body["status"] == "resolved"
    assert body["reviewedByUserId"] == admin_id
    assert body["reviewNotes"] == "checked"


def test_people_conflict_update_back_to_pending_clears_the_reviewer(client):
    make_admin(client)
    conflict_id = make_conflict(status="resolved")
    resp = client.put(
        f"/v1/moderation/people-conflicts/{conflict_id}/",
        json={"status": "pending"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.get_json()["conflict"]
    assert body["status"] == "pending"
    assert body["reviewedByUserId"] is None
    assert body["reviewedAt"] == ""


# ---------------------------------------------------------------------------
# sanity: PersonReconciliationError constant used above actually exists


def test_person_reconciliation_error_is_the_documented_exception_type():
    assert issubclass(people_reconcile.PersonReconciliationError, ValueError)
