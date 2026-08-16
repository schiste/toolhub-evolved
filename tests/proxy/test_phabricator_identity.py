# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for public Phabricator profile reads."""

import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import phabricator_identity  # noqa: E402

HEADER = '<span class="phui-header-header">{value}</span>'


def _page(username, real_name):
    return f'<div class="phui-header-col2">{HEADER.format(value=f"{username} ({real_name})")}</div>'


def _provider(status, body):
    return phabricator_identity.PhabricatorProfileProvider(fetcher=lambda _username: (status, body))


def test_parses_username_and_real_name_from_profile_header():
    profile = phabricator_identity.parse_profile(_page("Gopavasanth", "Gopa Vasanth"))
    assert profile == phabricator_identity.PhabricatorProfile(username="Gopavasanth", real_name="Gopa Vasanth")


def test_parses_real_name_carrying_its_own_parentheses():
    profile = phabricator_identity.parse_profile(_page("Ladsgroup", "Amir Sarabadani (WMDE)"))
    assert profile is not None
    assert profile.real_name == "Amir Sarabadani (WMDE)"


def test_collapses_markup_and_entities_inside_the_header():
    profile = phabricator_identity.parse_profile(HEADER.format(value="Volans (Riccardo\n  <b>Coccioli</b>&nbsp;)"))
    assert profile is not None
    assert profile.real_name == "Riccardo Coccioli"


@pytest.mark.parametrize(
    "html",
    [
        "",
        "<div>no header at all</div>",
        # An account that left its real name unset renders the handle alone.
        HEADER.format(value="Volans"),
        # A header whose handle is not a Phabricator username is not a pair.
        HEADER.format(value="Some Person (Other Name)"),
    ],
)
def test_returns_none_when_the_page_carries_no_usable_pair(html):
    assert phabricator_identity.parse_profile(html) is None


def test_lookup_returns_the_pair_for_a_known_handle():
    provider = _provider(200, _page("Soda", "Sohom Datta"))
    assert provider.lookup("Soda") == phabricator_identity.PhabricatorProfile(username="Soda", real_name="Sohom Datta")


def test_lookup_accepts_the_case_phabricator_canonicalizes():
    provider = _provider(200, _page("Ladsgroup", "Amir Sarabadani"))
    assert provider.lookup("ladsgroup") is not None


def test_lookup_refuses_a_profile_that_redirected_to_another_account():
    provider = _provider(200, _page("SomebodyElse", "Someone Else"))
    assert provider.lookup("Soda") is None


def test_lookup_returns_none_for_an_unknown_handle():
    assert _provider(404, "").lookup("nobody") is None


def test_lookup_refuses_a_label_that_is_not_a_username():
    calls = []

    def fetcher(username):
        calls.append(username)
        return 200, ""

    provider = phabricator_identity.PhabricatorProfileProvider(fetcher=fetcher)
    assert provider.lookup("Amir Sarabadani") is None
    assert calls == []


def test_lookup_raises_rather_than_reporting_an_absent_real_name_on_an_outage():
    provider = _provider(503, "")
    with pytest.raises(phabricator_identity.PhabricatorProfileError):
        provider.lookup("Soda")

    def failing(_username):
        raise requests.ConnectionError("boom")

    with pytest.raises(phabricator_identity.PhabricatorProfileError):
        phabricator_identity.PhabricatorProfileProvider(fetcher=failing).lookup("Soda")


def test_evidence_url_escapes_the_handle():
    provider = phabricator_identity.PhabricatorProfileProvider()
    assert provider.evidence_url("Soda") == "https://phabricator.wikimedia.org/p/Soda/"
