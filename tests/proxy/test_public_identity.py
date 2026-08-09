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


def toolforge_row(*, uid="magnus", sul="Magnus Manske", uid_number="3067", tools=("mix-n-match",)):
    return {
        "uid": [uid],
        "uidNumber": [uid_number],
        "sul": [sul],
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


def test_toolforge_lookup_requires_one_exact_sul_binding():
    assert public_identity.ToolforgeIdentityProvider(lookup=lambda _name: []).lookup_sul("Magnus Manske") is None
    assert (
        public_identity.ToolforgeIdentityProvider(lookup=lambda _name: [toolforge_row(sul="Someone Else")]).lookup_sul(
            "Magnus Manske"
        )
        is None
    )
    assert (
        public_identity.ToolforgeIdentityProvider(
            lookup=lambda _name: [toolforge_row(), toolforge_row(uid="magnus-two", uid_number="9999")]
        ).lookup_sul("Magnus Manske")
        is None
    )


def test_toolforge_lookup_queries_sul_and_reads_stable_identity_fields(monkeypatch):
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

    identity = public_identity.ToolforgeIdentityProvider().lookup_sul("Magnus Manske")

    assert identity is not None
    assert calls["server"] == (public_identity.TOOLFORGE_LDAP_URI, True, 5)
    assert calls["search"] == (
        public_identity.TOOLFORGE_LDAP_BASE_DN,
        "(sul=escaped:Magnus Manske)",
        ["uid", "uidNumber", "sul", "memberOf"],
        2,
    )
    assert calls["unbind"] is True
