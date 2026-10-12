# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure policy and validation tests for verified userscript owner edits."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import identity_graph, wiki_user_script_edits  # noqa: E402
from backend.sync import SOURCE_WIKI_USERSCRIPT  # noqa: E402


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return iter(self.rows)


class _Session:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.execute_calls = 0

    def execute(self, _statement):
        self.execute_calls += 1
        return _Result(self.rows)


def _binding(provider, external_id, *, status=None, revoked_at=None, person_id=1):
    return SimpleNamespace(
        provider=provider,
        external_id=external_id,
        status=status or identity_graph.STATUS_VERIFIED,
        revoked_at=revoked_at,
        person_id=person_id,
    )


def _valid_bindings(*, toolhub_person=1, wikimedia_person=1):
    return [
        _binding(identity_graph.PROVIDER_TOOLHUB, "toolhub-42", person_id=toolhub_person),
        _binding(identity_graph.PROVIDER_WIKIMEDIA, "global-9001", person_id=wikimedia_person),
    ]


def _user(*, global_id="global-9001", toolhub_id="toolhub-42"):
    return SimpleNamespace(wikimedia_global_user_id=global_id, wm_sub=toolhub_id)


def _canonical(*, source=SOURCE_WIKI_USERSCRIPT, source_url="https://en.wikipedia.org/wiki/User:Alice/tool.js"):
    return SimpleNamespace(source=source, source_url=source_url)


@pytest.mark.parametrize(
    ("global_id", "toolhub_id"),
    [("", "toolhub-42"), ("global-9001", "")],
)
def test_verified_wikimedia_id_requires_both_account_identifiers(global_id, toolhub_id):
    session = _Session()

    assert wiki_user_script_edits._verified_wikimedia_id(session, _user(global_id=global_id, toolhub_id=toolhub_id)) == ""
    assert session.execute_calls == 0


@pytest.mark.parametrize(
    ("present_provider", "present_id"),
    [
        (identity_graph.PROVIDER_WIKIMEDIA, "global-9001"),
        (identity_graph.PROVIDER_TOOLHUB, "toolhub-42"),
    ],
)
def test_verified_wikimedia_id_requires_both_account_bindings(present_provider, present_id):
    session = _Session([_binding(present_provider, present_id)])

    assert wiki_user_script_edits._verified_wikimedia_id(session, _user()) == ""


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("status", "pending"),
        ("revoked_at", object()),
        ("person_id", None),
    ],
)
def test_verified_wikimedia_id_rejects_unverified_revoked_or_unlinked_bindings(attribute, value):
    bindings = _valid_bindings()
    setattr(bindings[1], attribute, value)

    assert wiki_user_script_edits._verified_wikimedia_id(_Session(bindings), _user()) == ""


def test_verified_wikimedia_id_requires_bindings_to_resolve_to_one_person():
    session = _Session(_valid_bindings(toolhub_person=1, wikimedia_person=2))

    assert wiki_user_script_edits._verified_wikimedia_id(session, _user()) == ""


def test_verified_wikimedia_id_returns_the_shared_verified_identity():
    session = _Session(_valid_bindings())

    assert wiki_user_script_edits._verified_wikimedia_id(session, _user()) == "global-9001"


def test_owner_edit_context_rejects_non_userscript_sources_without_looking_up_identity():
    session = _Session()

    context = wiki_user_script_edits.owner_edit_context(
        session,
        _user(),
        _canonical(source="toolhub"),
        identity_matches=lambda *_args: pytest.fail("unsupported source must not query Wikimedia identity"),
    )

    assert context == {"supported": False, "canEdit": False, "reason": "not_wiki_userscript"}
    assert session.execute_calls == 0


def test_owner_edit_context_rejects_invalid_source_pages_without_looking_up_identity():
    session = _Session()

    context = wiki_user_script_edits.owner_edit_context(
        session,
        _user(),
        _canonical(source_url="https://example.org/not-a-userscript-page"),
        identity_matches=lambda *_args: pytest.fail("invalid source page must not query Wikimedia identity"),
    )

    assert context == {"supported": False, "canEdit": False, "reason": "invalid_source_page"}
    assert session.execute_calls == 0


def test_owner_edit_context_requires_verified_bindings_before_checking_centralauth():
    session = _Session()
    context = wiki_user_script_edits.owner_edit_context(
        session,
        _user(),
        _canonical(),
        identity_matches=lambda *_args: pytest.fail("unverified bindings must not trigger a wiki lookup"),
    )

    assert context["supported"] is True
    assert context["canEdit"] is False
    assert context["reason"] == "wikimedia_account_unverified"


def test_owner_edit_context_rejects_a_centralauth_owner_mismatch():
    session = _Session(_valid_bindings())
    calls = []
    context = wiki_user_script_edits.owner_edit_context(
        session,
        _user(),
        _canonical(),
        identity_matches=lambda domain, username, global_id: calls.append((domain, username, global_id) or False),
    )

    assert context["canEdit"] is False
    assert context["reason"] == "wiki_owner_mismatch"
    assert calls == [("en.wikipedia.org", "Alice", "global-9001")]


def test_owner_edit_context_allows_the_verified_centralauth_owner():
    session = _Session(_valid_bindings())
    context = wiki_user_script_edits.owner_edit_context(
        session,
        _user(),
        _canonical(),
        identity_matches=lambda domain, username, global_id: (domain, username, global_id)
        == ("en.wikipedia.org", "Alice", "global-9001"),
    )

    assert context["canEdit"] is True
    assert context["reason"] == "verified_owner"
    assert context["ownerProof"]["globalUserId"] == "global-9001"


def test_validate_owner_patch_requires_an_object_and_at_least_one_supported_field():
    assert wiki_user_script_edits.validate_owner_patch(None) == (
        {},
        [{"field": "patch", "message": "patch must be an object"}],
    )
    assert wiki_user_script_edits.validate_owner_patch({}) == (
        {},
        [{"field": "patch", "message": "patch must contain at least one supported field"}],
    )


def test_validate_owner_patch_rejects_a_blank_required_title():
    patch, errors = wiki_user_script_edits.validate_owner_patch({"title": "  "})

    assert patch == {}
    assert errors == [{"field": "title", "message": "title cannot be blank"}]


@pytest.mark.parametrize(
    ("localized_value", "message"),
    [
        ("https://docs.example/page", "value must be a list of localized URLs"),
        ([None], "link 1 must contain only url and optional language"),
        ([{"language": "en"}], "link 1 must contain only url and optional language"),
        ([{"url": "https://docs.example/page", "extra": "value"}], "link 1 must contain only url and optional language"),
        ([{"url": "javascript:alert(1)"}], "Use an absolute HTTP or HTTPS URL."),
        ([{"url": "https://docs.example/" + "x" * 2000}], "URL exceeds 2000 characters"),
        ([{"url": "https://docs.example/page", "language": "en--US"}], "invalid language tag"),
        ([{"url": ""}], "A localized URL must contain a URL."),
    ],
)
def test_validate_owner_patch_rejects_invalid_localized_url_values(localized_value, message):
    patch, errors = wiki_user_script_edits.validate_owner_patch({"user_docs_url": localized_value})

    assert patch == {}
    assert errors[0]["field"] == "user_docs_url"
    assert message in errors[0]["message"]


def test_validate_owner_patch_rejects_too_many_localized_urls():
    links = [{"url": f"https://docs.example/page-{index}"} for index in range(26)]

    patch, errors = wiki_user_script_edits.validate_owner_patch({"user_docs_url": links})

    assert patch == {}
    assert errors == [{"field": "user_docs_url", "message": "no more than 25 links are allowed"}]


def test_validate_owner_patch_deduplicates_localized_urls_case_insensitively():
    patch, errors = wiki_user_script_edits.validate_owner_patch(
        {
            "user_docs_url": [
                {"url": " https://docs.example/page ", "language": "en"},
                {"url": "https://docs.example/page", "language": "EN"},
            ]
        }
    )

    assert errors == []
    assert patch == {"user_docs_url": [{"url": "https://docs.example/page", "language": "en"}]}


def test_validate_owner_patch_preserves_a_localized_url_without_language():
    patch, errors = wiki_user_script_edits.validate_owner_patch(
        {"user_docs_url": [{"url": "https://docs.example/page"}]}
    )

    assert errors == []
    assert patch == {"user_docs_url": [{"url": "https://docs.example/page"}]}
