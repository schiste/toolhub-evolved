# SPDX-License-Identifier: GPL-3.0-or-later
"""Coverage-focused tests for backend/v1_tools.py: the /v1/tools/* endpoints.

Self-contained: builds its own Flask app + in-memory SQLite database and signs
in test users the same way tests/proxy/test_backend.py does, without importing
from it. Toolhub network calls are always monkeypatched away.
"""

import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
import backend.v1 as v1_api  # noqa: E402
import backend.v1_tools as v1_tools_api  # noqa: E402
from backend import authz, db, security, sync  # noqa: E402
from backend.public_identity import (  # noqa: E402
    PublicIdentityResolver,
    ToolforgeIdentityProvider,
    WikimediaIdentityProvider,
)
from backend.models import User, utcnow  # noqa: E402


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


def add_user(username="Ada", wm_sub="42", role=authz.ROLE_USER, wikimedia_global_user_id=None):
    with db.session_scope() as s:
        user = User(wm_sub=wm_sub, username=username, role=role, wikimedia_global_user_id=wikimedia_global_user_id)
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


def identity_resolver(username, *tools, global_id="160", toolforge_uid=None):
    return PublicIdentityResolver(
        wikimedia=WikimediaIdentityProvider(
            fetcher=lambda _id: (200, {"query": {"globaluserinfo": {"id": global_id, "name": username}}})
        ),
        toolforge=ToolforgeIdentityProvider(
            lookup=lambda _name: [
                {
                    "uid": [toolforge_uid or username.casefold()],
                    "uidNumber": ["3067"],
                    "wikimediaGlobalAccountId": [global_id],
                    "wikimediaGlobalAccountName": [username],
                    "memberOf": [f"cn=tools.{tool},ou=servicegroups,dc=wikimedia,dc=org" for tool in tools],
                }
            ]
        ),
    )


def ghost_user():
    """A require_policy_or_abort stand-in whose id has no matching row.

    v1_tools.py routes re-fetch the User row inside their own session after
    require_policy_or_abort already returned one, to guard the (normally
    unreachable) account-deleted-mid-request race. Injecting a fake user with
    an id that was never inserted reproduces that "stored_user is None" branch
    deterministically instead of racing real deletion against two sessions.
    """
    return SimpleNamespace(id=999999999, username="ghost")


class FakeProvider:
    """Stand-in for SIGNED_TOOLINFO_PROVIDER / TOOLFORGE_MAINTAINER_PROVIDER."""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.calls = []

    def verify(self, s, user, **kwargs):
        self.calls.append(kwargs)
        return self.rows


def post_claim(client, name, body):
    return client.post(f"/v1/tools/{name}/claims/", json=body, headers={"X-CSRF-Token": "tok"})


# ---------------------------------------------------------------------------
# v1_tool_viewer_context


def test_viewer_context_stored_user_missing(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    monkeypatch.setattr(v1_tools_api.common, "require_policy_or_abort", lambda *a, **k: ghost_user())
    resp = client.get("/v1/tools/some-tool/viewer-context/")
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "sign in required"}


# ---------------------------------------------------------------------------
# v1_tool_claim_options


def test_claim_options_tool_lookup_error(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    monkeypatch.setattr(
        v1_tools_api.common, "claim_tool_or_error", lambda name: (None, v1_tools_api.common.bad("nope"))
    )
    resp = client.get("/v1/tools/missing-tool/claim-options/")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "nope"


def test_claim_options_stored_user_missing(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    tool = {"name": "ghost-tool", "title": "Ghost Tool"}
    monkeypatch.setattr(v1_tools_api.common, "claim_tool_or_error", lambda name: (tool, None))
    monkeypatch.setattr(v1_tools_api.common, "require_policy_or_abort", lambda *a, **k: ghost_user())
    resp = client.get("/v1/tools/ghost-tool/claim-options/")
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "sign in required"}


# ---------------------------------------------------------------------------
# v1_tool_claim_create


def test_claim_create_bad_body(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.post("/v1/tools/some-tool/claims/", data="not json", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "body must be a JSON object"


def test_claim_create_unknown_method(client):
    uid = add_user()
    sign_in(client, uid)
    resp = post_claim(client, "some-tool", {"method": "not-a-real-method"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "unknown claim verification method"


def test_claim_create_toolhub_write_access_is_automatic(client):
    uid = add_user()
    sign_in(client, uid)
    resp = post_claim(client, "some-tool", {"method": sync.AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS})
    assert resp.status_code == 409
    assert "recorded automatically" in resp.get_json()["error"]


def test_claim_create_tool_lookup_error(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    monkeypatch.setattr(
        v1_tools_api.common, "claim_tool_or_error", lambda name: (None, v1_tools_api.common.bad("nope"))
    )
    resp = post_claim(client, "missing-tool", {"method": sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "nope"


def test_claim_create_stored_user_missing(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    tool = {"name": "ghost-tool", "author": [{"name": "Ada"}]}
    monkeypatch.setattr(v1_tools_api.common, "claim_tool_or_error", lambda name: (tool, None))
    monkeypatch.setattr(v1_tools_api.common, "require_policy_or_abort", lambda *a, **k: ghost_user())
    resp = post_claim(client, "ghost-tool", {"method": sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME})
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "sign in required"}


def test_claim_create_author_display_name_rejects_unlisted_name(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    tool = {"name": "ada-tool", "author": [{"name": "Ada Lovelace"}]}
    monkeypatch.setattr(v1_tools_api.common, "claim_tool_or_error", lambda name: (tool, None))
    resp = post_claim(client, "ada-tool", {"method": sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME, "authorName": "Not Ada"})
    assert resp.status_code == 400
    assert "authorName must be one of" in resp.get_json()["error"]


def test_claim_create_toolforge_maintainer_no_toolforge_signal(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    tool = {"name": "plain-tool", "url": "https://example.org/plain-tool"}
    monkeypatch.setattr(v1_tools_api.common, "claim_tool_or_error", lambda name: (tool, None))
    resp = post_claim(client, "plain-tool", {"method": sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER})
    assert resp.status_code == 409
    assert "does not identify a Toolforge tool" in resp.get_json()["error"]


def test_claim_create_toolforge_maintainer_membership_not_verified(client, monkeypatch):
    uid = add_user(wikimedia_global_user_id="160")
    sign_in(client, uid)
    tool = {"name": "toolforge-mytool"}
    monkeypatch.setattr(v1_tools_api.common, "claim_tool_or_error", lambda name: (tool, None))
    # This account is a Toolforge member of "othertool", not "mytool" -> no match.
    monkeypatch.setattr(v1_api, "PUBLIC_IDENTITY_RESOLVER", identity_resolver("Ada", "othertool", global_id="160"))
    resp = post_claim(client, "toolforge-mytool", {"method": sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER})
    assert resp.status_code == 409
    assert "Toolforge membership could not be verified" in resp.get_json()["error"]


def test_claim_create_toolinfo_url_control_invalid_url(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    tool = {"name": "ctrl-tool"}
    monkeypatch.setattr(v1_tools_api.common, "claim_tool_or_error", lambda name: (tool, None))
    resp = post_claim(
        client,
        "ctrl-tool",
        {"method": sync.AUTHOR_CLAIM_TOOLINFO_URL_CONTROL, "toolinfoUrl": "not a url"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["validationErrors"][0]["field"] == "toolinfoUrl"


def test_claim_create_toolinfo_url_control_success(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    tool = {"name": "ctrl-tool"}
    monkeypatch.setattr(v1_tools_api.common, "claim_tool_or_error", lambda name: (tool, None))
    monkeypatch.setattr(v1_tools_api.common, "fetch_matching_item", lambda url, name: {"name": name})
    resp = post_claim(
        client,
        "ctrl-tool",
        {"method": sync.AUTHOR_CLAIM_TOOLINFO_URL_CONTROL, "toolinfoUrl": "https://example.org/toolinfo.json"},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["ok"] is True
    assert body["claims"][0]["verificationMethod"] == sync.AUTHOR_CLAIM_TOOLINFO_URL_CONTROL
    assert body["challenge"]["toolName"] == "ctrl-tool"


def test_claim_create_signed_toolinfo_invalid_url(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    tool = {"name": "signed-tool"}
    monkeypatch.setattr(v1_tools_api.common, "claim_tool_or_error", lambda name: (tool, None))
    resp = post_claim(client, "signed-tool", {"method": sync.AUTHOR_CLAIM_SIGNED_TOOLINFO, "toolinfoUrl": "ftp://bad"})
    assert resp.status_code == 400
    assert resp.get_json()["validationErrors"][0]["field"] == "toolinfoUrl"


def test_claim_create_signed_toolinfo_fetch_failure(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    tool = {"name": "signed-tool"}
    monkeypatch.setattr(v1_tools_api.common, "claim_tool_or_error", lambda name: (tool, None))

    def boom(url, name):
        message = "fetch exploded"
        raise ValueError(message)

    monkeypatch.setattr(v1_tools_api, "fetch_matching_item", boom)
    resp = post_claim(
        client,
        "signed-tool",
        {"method": sync.AUTHOR_CLAIM_SIGNED_TOOLINFO, "toolinfoUrl": "https://example.org/toolinfo.json"},
    )
    assert resp.status_code == 400
    assert "Could not read signed toolinfo" in resp.get_json()["error"]


def test_claim_create_signed_toolinfo_no_rows(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    tool = {"name": "signed-tool"}
    monkeypatch.setattr(v1_tools_api.common, "claim_tool_or_error", lambda name: (tool, None))
    monkeypatch.setattr(v1_tools_api, "fetch_matching_item", lambda url, name: {"name": name})
    fake = FakeProvider(rows=[])
    monkeypatch.setattr(v1_api, "SIGNED_TOOLINFO_PROVIDER", fake)
    resp = post_claim(
        client,
        "signed-tool",
        {"method": sync.AUTHOR_CLAIM_SIGNED_TOOLINFO, "toolinfoUrl": "https://example.org/toolinfo.json"},
    )
    assert resp.status_code == 400
    assert "no supported signature metadata" in resp.get_json()["error"]
    assert fake.calls[0]["evidence_url"] == "https://example.org/toolinfo.json"


def test_claim_create_falls_through_every_known_method_branch(client, monkeypatch):
    """A CLAIM_METHODS entry matching none of the if/elif branches leaves rows empty.

    In production CLAIM_METHODS only ever holds the five methods the if/elif
    chain already lists (with TOOLHUB_WRITE_ACCESS handled earlier by its own
    early return), so the chain's final elif is always taken once reached and
    its "condition false" arc is structurally dead. Widening CLAIM_METHODS
    here is the only way to exercise that arc directly, without touching
    proxy/backend/v1_tools.py itself.
    """
    uid = add_user()
    sign_in(client, uid)
    monkeypatch.setattr(v1_api, "CLAIM_METHODS", v1_api.CLAIM_METHODS | {"totally-unknown-method"})
    tool = {"name": "fallthrough-tool"}
    monkeypatch.setattr(v1_tools_api.common, "claim_tool_or_error", lambda name: (tool, None))
    resp = post_claim(client, "fallthrough-tool", {"method": "totally-unknown-method"})
    assert resp.status_code == 201
    assert resp.get_json()["claims"] == []


def test_claim_create_signed_toolinfo_success(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    tool = {"name": "signed-tool"}
    monkeypatch.setattr(v1_tools_api.common, "claim_tool_or_error", lambda name: (tool, None))
    monkeypatch.setattr(v1_tools_api, "fetch_matching_item", lambda url, name: {"name": name})
    with db.session_scope() as s:
        from backend.models import ToolAuthorClaim

        row = ToolAuthorClaim(
            tool_name="signed-tool",
            author_name="Ada",
            toolhub_username="Ada",
            user_id=uid,
            verification_status=sync.AUTHOR_CLAIM_VERIFIED,
            verification_method=sync.AUTHOR_CLAIM_SIGNED_TOOLINFO,
            requested_relationship=sync.PERSON_REL_AUTHOR,
        )
        s.add(row)
        s.flush()
        row_id = row.id
        fake = FakeProvider(rows=[row])
    monkeypatch.setattr(v1_api, "SIGNED_TOOLINFO_PROVIDER", fake)
    resp = post_claim(
        client,
        "signed-tool",
        {"method": sync.AUTHOR_CLAIM_SIGNED_TOOLINFO, "toolinfoUrl": "https://example.org/toolinfo.json"},
    )
    assert resp.status_code == 201
    assert resp.get_json()["claims"][0]["id"] == row_id


# ---------------------------------------------------------------------------
# v1_tool_summaries


def test_tool_summaries_no_names_returns_empty(client):
    resp = client.get("/v1/tools/summaries/")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {
        "count": 0,
        "results": {},
        "cacheMeta": {},
        "source": sync.SOURCE_LOCAL,
        "syncStatus": sync.SYNC_EVOLVED_REAL,
    }


def test_tool_summaries_unknown_view_is_rejected(client):
    resp = client.get("/v1/tools/summaries/?name=alpha&view=bogus")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "unknown summary view"
