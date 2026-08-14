# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for authoritative Wikimedia and Toolforge identity resolution."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import public_identity  # noqa: E402


def wikimedia_provider(global_id="160", username="Magnus Manske"):
    return public_identity.WikimediaIdentityProvider(
        fetcher=lambda _global_id: (
            200,
            {
                "query": {
                    "globaluserinfo": {
                        "id": int(global_id),
                        "name": username,
                        "registration": "2008-03-25T09:03:23Z",
                    }
                }
            },
        )
    )


def toolforge_row(
    *,
    uid="magnus",
    developer_username="Magnus",
    global_id="160",
    global_name="Magnus Manske",
    uid_number="3067",
    tools=("mix-n-match",),
):
    return {
        "uid": [uid],
        "uidNumber": [uid_number],
        "cn": [developer_username],
        "wikimediaGlobalAccountId": [global_id],
        "wikimediaGlobalAccountName": [global_name],
        "memberOf": [f"cn=tools.{tool},ou=servicegroups,dc=wikimedia,dc=org" for tool in tools],
    }


def test_resolver_joins_global_identity_to_sul_bound_toolforge_account():
    resolver = public_identity.PublicIdentityResolver(
        wikimedia=wikimedia_provider(),
        toolforge=public_identity.ToolforgeIdentityProvider(lookup=lambda _username: [toolforge_row()]),
    )

    resolved = resolver.resolve("160")

    assert resolved is not None
    assert resolved.wikimedia.global_user_id == "160"
    assert resolved.wikimedia.username == "Magnus Manske"
    assert resolved.toolforge is not None
    assert resolved.toolforge.uid == "magnus"
    assert resolved.toolforge.uid_number == "3067"
    assert resolved.toolforge.developer_username == "Magnus"
    assert resolved.toolforge.tool_names == ("mix-n-match",)


def test_wikimedia_lookup_rejects_missing_mismatched_and_failed_rows():
    payloads = [
        (503, {}),
        (200, []),
        (200, {"query": {"globaluserinfo": {"missing": True}}}),
        (200, {"query": {"globaluserinfo": {"id": 999, "name": "Magnus Manske"}}}),
    ]
    for status, payload in payloads:
        provider = public_identity.WikimediaIdentityProvider(fetcher=lambda _global_id, value=(status, payload): value)
        assert provider.lookup("160") is None
    assert public_identity.WikimediaIdentityProvider(fetcher=lambda _id: (200, {})).lookup("") is None


def test_toolforge_lookup_requires_one_exact_global_id_binding():
    assert public_identity.ToolforgeIdentityProvider(lookup=lambda _id: []).lookup_global("160") is None
    assert (
        public_identity.ToolforgeIdentityProvider(lookup=lambda _id: [toolforge_row(global_id="999")]).lookup_global(
            "160"
        )
        is None
    )
    assert (
        public_identity.ToolforgeIdentityProvider(
            lookup=lambda _id: [toolforge_row(), toolforge_row(uid="magnus-two", uid_number="9999")]
        ).lookup_global("160")
        is None
    )


def test_toolforge_lookup_uses_canonical_name_when_ldap_link_name_is_stale():
    identity = public_identity.ToolforgeIdentityProvider(
        lookup=lambda _id: [toolforge_row(global_name="Old Magnus Name")]
    ).lookup_global("160", canonical_username="Magnus Manske")

    assert identity is not None
    assert identity.sul_username == "Magnus Manske"


def test_toolforge_lookup_queries_global_id_and_reads_stable_identity_fields(monkeypatch):
    calls = {}

    class FakeServer:
        def __init__(self, uri, *, use_ssl, connect_timeout):
            calls["server"] = (uri, use_ssl, connect_timeout)

    class FakeEntry:
        entry_attributes_as_dict = toolforge_row()

    class FakeConnection:
        def __init__(self, server, *, receive_timeout, auto_bind):
            calls["connection"] = (server, receive_timeout, auto_bind)
            self.entries = []

        def search(self, base_dn, ldap_filter, *, attributes, size_limit):
            calls["search"] = (base_dn, ldap_filter, attributes, size_limit)
            self.entries = [FakeEntry()]

        def unbind(self):
            calls["unbind"] = True

    monkeypatch.setattr(public_identity, "Server", FakeServer)
    monkeypatch.setattr(public_identity, "Connection", FakeConnection)
    monkeypatch.setattr(public_identity, "escape_filter_chars", lambda value: f"escaped:{value}")

    identity = public_identity.ToolforgeIdentityProvider().lookup_global(
        "160",
        canonical_username="Magnus Manske",
    )

    assert identity is not None
    assert calls["server"] == (public_identity.TOOLFORGE_LDAP_URI, True, 5)
    assert calls["search"] == (
        public_identity.TOOLFORGE_LDAP_BASE_DN,
        "(&(objectClass=posixAccount)(wikimediaGlobalAccountId=escaped:160))",
        ["uid", "uidNumber", "cn", "wikimediaGlobalAccountId", "wikimediaGlobalAccountName", "memberOf"],
        2,
    )
    assert calls["unbind"] is True


def test_tool_names_from_member_dns_dedupes_case_insensitively_and_skips_non_matching():
    names = public_identity.tool_names_from_member_dns(
        [
            "cn=tools.mix-n-match,ou=servicegroups,dc=wikimedia,dc=org",
            "cn=tools.Mix-N-Match,ou=servicegroups,dc=wikimedia,dc=org",  # duplicate, different case
            "cn=some-other-group,ou=groups,dc=wikimedia,dc=org",  # does not match at all
        ]
    )

    assert names == ("mix-n-match",)


def test_toolforge_lookup_global_accepts_scalar_ldap_attributes():
    row = {
        "uid": "magnus",
        "uidNumber": "3067",
        "cn": "Magnus",
        "wikimediaGlobalAccountId": "160",
        "wikimediaGlobalAccountName": "Magnus Manske",
    }

    identity = public_identity.ToolforgeIdentityProvider(lookup=lambda _id: [row]).lookup_global("160")

    assert identity is not None
    assert identity.uid == "magnus"
    assert identity.uid_number == "3067"
    assert identity.developer_username == "Magnus"
    assert identity.tool_names == ()


def test_wikimedia_lookup_returns_none_when_fetcher_raises():
    def raising_fetcher(_global_id):
        raise OSError("network down")

    assert public_identity.WikimediaIdentityProvider(fetcher=raising_fetcher).lookup("160") is None


def test_wikimedia_lookup_rejects_a_row_that_is_not_a_dict():
    provider = public_identity.WikimediaIdentityProvider(fetcher=lambda _global_id: (200, {"query": {}}))
    assert provider.lookup("160") is None


def test_wikimedia_lookup_username_rejects_empty_missing_and_incomplete_rows():
    assert public_identity.WikimediaIdentityProvider(username_fetcher=lambda _u: (200, {})).lookup_username("") is None

    payloads = [
        (503, {}),
        (200, []),
        (200, {"query": {"globaluserinfo": {"missing": True}}}),
        (200, {"query": {}}),
        (200, {"query": {"globaluserinfo": {"name": "Magnus Manske"}}}),  # no id
        (200, {"query": {"globaluserinfo": {"id": 160}}}),  # no name
    ]
    for status, payload in payloads:
        provider = public_identity.WikimediaIdentityProvider(
            username_fetcher=lambda _u, value=(status, payload): value
        )
        assert provider.lookup_username("Magnus Manske") is None


def test_wikimedia_lookup_username_returns_none_when_fetcher_raises():
    def raising_fetcher(_username):
        raise ValueError("boom")

    assert public_identity.WikimediaIdentityProvider(username_fetcher=raising_fetcher).lookup_username("Magnus") is None


def test_wikimedia_lookup_username_resolves_current_global_identity():
    provider = public_identity.WikimediaIdentityProvider(
        username_fetcher=lambda _u: (
            200,
            {
                "query": {
                    "globaluserinfo": {
                        "id": 160,
                        "name": "Magnus Manske",
                        "registration": "2008-03-25T09:03:23Z",
                    }
                }
            },
        )
    )

    identity = provider.lookup_username("Magnus Manske")

    assert identity is not None
    assert identity.global_user_id == "160"
    assert identity.username == "Magnus Manske"


class _FakeCentralAuthResponse:
    def __init__(self, status_code, payload=None, *, raise_on_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_on_json = raise_on_json

    def json(self):
        if self._raise_on_json:
            raise ValueError("not json")
        return self._payload


def test_default_fetch_username_calls_centralauth_api_with_guiuser(monkeypatch):
    calls = {}

    def fake_get(url, params, headers, timeout):
        calls["args"] = (url, params, headers, timeout)
        return _FakeCentralAuthResponse(
            200,
            {
                "query": {
                    "globaluserinfo": {
                        "id": 160,
                        "name": "Magnus Manske",
                        "registration": "2008-03-25T09:03:23Z",
                    }
                }
            },
        )

    monkeypatch.setattr(public_identity.requests, "get", fake_get)

    identity = public_identity.WikimediaIdentityProvider().lookup_username("Magnus Manske")

    assert identity is not None
    assert identity.global_user_id == "160"
    url, params, headers, timeout = calls["args"]
    assert url == public_identity.CENTRALAUTH_API_URL
    assert params["guiuser"] == "Magnus Manske"
    assert params["meta"] == "globaluserinfo"
    assert headers["User-Agent"] == public_identity.toolhub.USER_AGENT
    assert timeout == public_identity.toolhub.REQUEST_TIMEOUT


def test_default_fetch_username_treats_unparsable_json_as_no_payload(monkeypatch):
    monkeypatch.setattr(
        public_identity.requests,
        "get",
        lambda url, params, headers, timeout: _FakeCentralAuthResponse(200, raise_on_json=True),
    )

    assert public_identity.WikimediaIdentityProvider().lookup_username("Magnus Manske") is None


def test_default_fetch_calls_centralauth_api_with_guiid(monkeypatch):
    calls = {}

    def fake_get(url, params, headers, timeout):
        calls["args"] = (url, params, headers, timeout)
        return _FakeCentralAuthResponse(
            200,
            {
                "query": {
                    "globaluserinfo": {
                        "id": 160,
                        "name": "Magnus Manske",
                        "registration": "2008-03-25T09:03:23Z",
                    }
                }
            },
        )

    monkeypatch.setattr(public_identity.requests, "get", fake_get)

    identity = public_identity.WikimediaIdentityProvider().lookup("160")

    assert identity is not None
    assert identity.username == "Magnus Manske"
    url, params, headers, timeout = calls["args"]
    assert url == public_identity.CENTRALAUTH_API_URL
    assert params["guiid"] == "160"
    assert headers["Accept"] == "application/json"
    assert timeout == public_identity.toolhub.REQUEST_TIMEOUT


def test_default_fetch_treats_unparsable_json_as_no_payload(monkeypatch):
    monkeypatch.setattr(
        public_identity.requests,
        "get",
        lambda url, params, headers, timeout: _FakeCentralAuthResponse(200, raise_on_json=True),
    )

    assert public_identity.WikimediaIdentityProvider().lookup("160") is None


def test_toolforge_lookup_global_short_circuits_on_empty_id():
    calls = []

    def lookup(global_id):
        calls.append(global_id)
        return []

    assert public_identity.ToolforgeIdentityProvider(lookup=lookup).lookup_global("") is None
    assert calls == []


def test_toolforge_lookup_global_returns_none_when_lookup_raises():
    def raising_lookup(_global_id):
        raise OSError("ldap down")

    assert public_identity.ToolforgeIdentityProvider(lookup=raising_lookup).lookup_global("160") is None


def test_probe_schema_returns_false_when_probe_raises():
    def raising_probe():
        raise TimeoutError("ldap timeout")

    assert public_identity.ToolforgeIdentityProvider(schema_probe=raising_probe).probe_schema() is False


def test_ldap_search_returns_empty_when_ldap3_is_unavailable(monkeypatch):
    monkeypatch.setattr(public_identity, "Connection", None)

    assert public_identity.ToolforgeIdentityProvider().lookup_global("160") is None


def test_resolver_returns_none_when_wikimedia_lookup_fails():
    resolver = public_identity.PublicIdentityResolver(
        wikimedia=public_identity.WikimediaIdentityProvider(fetcher=lambda _global_id: (404, {})),
    )

    assert resolver.resolve("160") is None


def test_toolforge_schema_probe_uses_the_real_bridge_attributes(monkeypatch):
    calls = {}

    class FakeServer:
        def __init__(self, *_args, **_kwargs):
            pass

    class FakeEntry:
        entry_attributes_as_dict = toolforge_row()

    class FakeConnection:
        def __init__(self, *_args, **_kwargs):
            self.entries = []

        def search(self, base_dn, ldap_filter, *, attributes, size_limit):
            calls["search"] = (base_dn, ldap_filter, attributes, size_limit)
            self.entries = [FakeEntry()]

        def unbind(self):
            pass

    monkeypatch.setattr(public_identity, "Server", FakeServer)
    monkeypatch.setattr(public_identity, "Connection", FakeConnection)

    assert public_identity.ToolforgeIdentityProvider().probe_schema() is True
    assert calls["search"][1] == "(&(objectClass=posixAccount)(wikimediaGlobalAccountId=*))"
    assert "wikimediaGlobalAccountId" in calls["search"][2]
