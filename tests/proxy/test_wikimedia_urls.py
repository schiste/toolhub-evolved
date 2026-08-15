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
