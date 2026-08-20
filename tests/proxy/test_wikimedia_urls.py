# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for strict Wikimedia user-space URL parsing."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import wikimedia_urls  # noqa: E402


@pytest.mark.parametrize(
    ("url", "domain", "username"),
    [
        ("https://en.wikipedia.org/wiki/User:Enterprisey/tool.js", "en.wikipedia.org", "Enterprisey"),
        ("https://commons.wikimedia.org/wiki/User:Ada_Lovelace/file.js", "commons.wikimedia.org", "Ada_Lovelace"),
        ("https://www.wikidata.org/w/index.php?title=User%3AAda%2Ftool.js", "www.wikidata.org", "Ada"),
        ("http://meta.wikimedia.org:80/wiki/User:Example", "meta.wikimedia.org", "Example"),
    ],
)
def test_user_space_page_accepts_public_wikimedia_user_pages(url, domain, username):
    page = wikimedia_urls.user_space_page(url)

    assert page is not None
    assert (page.domain, page.username) == (domain, username)


@pytest.mark.parametrize(
    "url",
    [
        "https://en.wikipedia.org.example/wiki/User:Enterprisey/tool.js",
        "https://example.org/wiki/User:Enterprisey/tool.js",
        "https://en.wikipedia.org:444/wiki/User:Enterprisey/tool.js",
        "https://user@example.org/wiki/User:Enterprisey/tool.js",
        "javascript:https://en.wikipedia.org/wiki/User:Enterprisey/tool.js",
        "https://en.wikipedia.org/wiki/User_talk:Enterprisey/tool.js",
        "https://en.wikipedia.org/wiki/Wikipedia:User_scripts",
    ],
)
def test_user_space_page_rejects_untrusted_or_non_user_urls(url):
    assert wikimedia_urls.user_space_page(url) is None


def test_path_title_is_authoritative_when_a_query_also_contains_a_title():
    page = wikimedia_urls.user_space_page(
        "https://en.wikipedia.org/wiki/User:Path_Owner/tool.js?title=User:Query_Owner/tool.js"
    )

    assert page is not None
    assert page.username == "Path_Owner"


def test_normalized_username_handles_mediawiki_spelling_only():
    assert wikimedia_urls.normalized_username("User:Ada_Lovelace") == "ada lovelace"


def test_canonical_username_folds_spelling_but_not_case():
    # Underscores and spaces are interchangeable; a name copied from a URL has
    # underscores while the Action API always answers with spaces.
    assert wikimedia_urls.canonical_username("NellieBly_Bot") == "NellieBly Bot"
    assert wikimedia_urls.canonical_username("  User:Ada__Lovelace  ") == "Ada Lovelace"
    # Case is identity: MediaWiki capitalizes only the first letter, so these
    # are two different accounts and must not compare equal.
    assert wikimedia_urls.canonical_username("Foo Bar") != wikimedia_urls.canonical_username("Foo bar")


@pytest.mark.parametrize(
    ("url", "is_javascript"),
    [
        ("https://en.wikipedia.org/wiki/User:Enterprisey/tool.js", True),
        ("https://en.wikipedia.org/w/index.php?title=User%3AEnterprisey%2Ftool.JS&action=raw", True),
        ("https://en.wikipedia.org/wiki/User:Enterprisey/tool.css", False),
        ("https://example.org/wiki/User:Enterprisey/tool.js", False),
    ],
)
def test_user_space_javascript_page_requires_a_trusted_js_title(url, is_javascript):
    assert (wikimedia_urls.user_space_javascript_page(url) is not None) is is_javascript


# --- Wikimedia projects that exist exactly once ------------------------------


@pytest.mark.parametrize(
    ("url", "domain"),
    [
        # mediawiki.org hosts a large share of the user scripts and gadgets
        # that other wikis import, and was refused until now.
        ("https://www.mediawiki.org/wiki/User:Ada/tool.js", "www.mediawiki.org"),
        ("https://mediawiki.org/wiki/User:Ada/tool.js", "mediawiki.org"),
        ("https://www.wikifunctions.org/wiki/User:Ada/tool.js", "www.wikifunctions.org"),
        ("https://wikifunctions.org/wiki/User:Ada/tool.js", "wikifunctions.org"),
    ],
)
def test_single_site_projects_are_public_wikimedia_wikis(url, domain):
    page = wikimedia_urls.user_space_page(url)

    assert page is not None
    assert page.domain == domain


@pytest.mark.parametrize(
    "domain",
    [
        # Neither project has per-language siblings, so a subdomain is not a
        # sibling wiki -- it is someone else's host if it resolves at all.
        "de.mediawiki.org",
        "evil.wikifunctions.org",
        # The suffix trick the subdomain alternative has to survive too.
        "mediawiki.org.attacker.example",
        "wikifunctions.org.attacker.example",
        "notmediawiki.org",
    ],
)
def test_a_lookalike_of_a_single_site_project_is_not_one(domain):
    with pytest.raises(ValueError, match="public Wikimedia wiki domain"):
        wikimedia_urls.clean_wiki_domain(domain)
