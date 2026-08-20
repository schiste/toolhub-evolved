# SPDX-License-Identifier: GPL-3.0-or-later
"""Parsing wiki-hosted tool source: which pages are source, and which belong together."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import wiki_sources  # noqa: E402

SCRIPT = "https://en.wikipedia.org/wiki/User:Example/twinkle.js"
GADGET = "https://en.wikipedia.org/wiki/MediaWiki:Gadget-Twinkle.js"

# The documented Gadgets-definition shape, including the two things that break
# a naive parser: a section heading, and options that contain their own pipes.
DEFINITION = """
== Browsing ==
* Twinkle[ResourceLoader|dependencies=mediawiki.util,jquery.ui|rights=autoconfirmed]|Twinkle.js|Twinkle.css|morebits.js|morebits.css
* HotCat[ResourceLoader]|HotCat.js
* plain|Plain.js
"""


def test_a_user_subpage_with_a_code_suffix_is_a_user_script():
    source = wiki_sources.wiki_source(SCRIPT)
    assert source.domain == "en.wikipedia.org"
    assert source.title == "User:Example/twinkle.js"
    assert source.kind == wiki_sources.KIND_USER_SCRIPT


def test_a_gadget_page_is_a_gadget_and_knows_its_definition_filename():
    source = wiki_sources.wiki_source(GADGET)
    assert source.kind == wiki_sources.KIND_GADGET
    # This is the spelling Gadgets-definition lists, without the page prefix.
    assert source.filename == "Twinkle.js"


def test_a_user_script_has_no_gadget_filename():
    assert wiki_sources.wiki_source(SCRIPT).filename == ""


@pytest.mark.parametrize(
    "url",
    [
        # Prose about a tool is not the tool: no code content model, no suffix.
        "https://en.wikipedia.org/wiki/User:Example/twinkle",
        "https://en.wikipedia.org/wiki/User:Example/Documentation",
        # The account page itself is never source, suffix or not.
        "https://en.wikipedia.org/wiki/User:Example.js",
        # Mainspace and other namespaces are articles, not source.
        "https://en.wikipedia.org/wiki/Twinkle.js",
        "https://en.wikipedia.org/wiki/Template:Example.js",
        # Not a Wikimedia wiki.
        "https://example.org/wiki/User:Example/twinkle.js",
        "https://en.wikipedia.evil.example/wiki/User:Example/twinkle.js",
        # http, credentials and odd ports are all refused before the title.
        "http://en.wikipedia.org/wiki/User:Example/twinkle.js",
        "https://user:secret@en.wikipedia.org/wiki/User:Example/twinkle.js",
        "https://en.wikipedia.org:8443/wiki/User:Example/twinkle.js",
        # A wiki host with no page at all.
        "https://en.wikipedia.org/wiki/",
        "https://en.wikipedia.org/",
        "https://en.wikipedia.org/w/index.php?oldid=123",
    ],
)
def test_urls_that_are_not_wiki_hosted_source(url):
    assert wiki_sources.wiki_source(url) is None


def test_the_index_php_spelling_is_the_same_page():
    # toolinfo carries both forms, and they must not enrich as two projects.
    query = wiki_sources.wiki_source("https://en.wikipedia.org/w/index.php?title=User:Example/twinkle.js")
    assert query.title == wiki_sources.wiki_source(SCRIPT).title


def test_underscores_percent_encoding_and_first_letter_case_collapse_to_one_title():
    spellings = [
        "https://en.wikipedia.org/wiki/MediaWiki:Gadget-Twinkle.js",
        "https://en.wikipedia.org/wiki/MediaWiki:gadget-Twinkle.js",
        "https://en.wikipedia.org/wiki/mediawiki:Gadget-Twinkle.js",
        "https://en.wikipedia.org/wiki/MediaWiki%3AGadget-Twinkle.js",
        "https://en.wikipedia.org/wiki/MediaWiki:Gadget-Twinkle.js",
    ]
    assert len({wiki_sources.wiki_source(url).title for url in spellings}) == 1


def test_case_below_the_first_letter_is_not_folded():
    # MediaWiki capitalizes only the first character, so these are two pages
    # and folding them together would merge two tools.
    assert wiki_sources.canonical_title("User:Example/Twinkle.js") != wiki_sources.canonical_title(
        "User:Example/twinkle.js"
    )


def test_a_gadget_pulls_in_every_page_the_definition_lists():
    pages = wiki_sources.gadget_pages(DEFINITION, "Twinkle.js")
    assert pages == (
        "MediaWiki:Gadget-Twinkle.js",
        "MediaWiki:Gadget-Twinkle.css",
        "MediaWiki:Gadget-morebits.js",
        "MediaWiki:Gadget-morebits.css",
    )


def test_any_one_file_of_a_gadget_finds_the_whole_set():
    # A tool may name the helper rather than the entry point.
    assert wiki_sources.gadget_pages(DEFINITION, "morebits.css") == wiki_sources.gadget_pages(DEFINITION, "Twinkle.js")


def test_option_pipes_are_never_read_as_pages():
    # dependencies=a,b|rights=c contains pipes; splitting the line on | would
    # file "rights=autoconfirmed" as a gadget page.
    assert all(
        "rights" not in page and "dependencies" not in page
        for page in wiki_sources.gadget_pages(DEFINITION, "Twinkle.js")
    )


def test_a_gadget_entry_without_options_still_parses():
    assert wiki_sources.gadget_pages(DEFINITION, "Plain.js") == ("MediaWiki:Gadget-Plain.js",)


def test_an_unregistered_gadget_page_gets_no_invented_set():
    # A leftover MediaWiki:Gadget-* page is not a gadget. Returning () lets the
    # caller fall back to the single page rather than guess at peers.
    assert wiki_sources.gadget_pages(DEFINITION, "Nonexistent.js") == ()


@pytest.mark.parametrize(
    "line",
    [
        "== Browsing ==",
        "",
        "not a list item|Foo.js",
        "* Unclosed[ResourceLoader|Foo.js",
        "* NoFiles[ResourceLoader]",
        "* |Foo.js",
    ],
)
def test_definition_lines_that_yield_nothing(line):
    assert wiki_sources.gadget_pages(line, "Foo.js") == ()


def test_a_definition_entry_ignores_non_source_files():
    # Some wikis list a documentation page alongside the code.
    assert wiki_sources.gadget_pages("* X[RL]|X.js|Docs", "X.js") == ("MediaWiki:Gadget-X.js",)


def test_a_user_script_collects_its_suffix_swaps_and_real_subpages():
    source = wiki_sources.wiki_source(SCRIPT)
    listed = [
        "User:Example/twinkle.js",
        "User:Example/twinkle.css",
        "User:Example/twinkle/core.js",
        "User:Example/twinkle.json",
    ]
    assert wiki_sources.subpage_titles(source, listed) == (
        "User:Example/twinkle.js",
        "User:Example/twinkle.css",
        "User:Example/twinkle.json",
        "User:Example/twinkle/core.js",
    )


def test_a_prefix_neighbour_is_not_part_of_the_script():
    # apprefix=Example/twinkle also returns twinkleblock.js, which is a
    # different tool by the same author. Scanning it here would attribute one
    # author's second tool to their first.
    source = wiki_sources.wiki_source(SCRIPT)
    listed = ["User:Example/twinkle.js", "User:Example/twinkleblock.js", "User:Example/twinkle-old.js"]
    assert wiki_sources.subpage_titles(source, listed) == ("User:Example/twinkle.js",)


def test_the_named_page_comes_first_even_when_the_listing_omits_it():
    # The listing is a prefix search and can lag; the page we were pointed at
    # is source whether or not the index has caught up.
    source = wiki_sources.wiki_source(SCRIPT)
    assert wiki_sources.subpage_titles(source, ["User:Example/twinkle.css"])[0] == "User:Example/twinkle.js"


def test_non_source_pages_in_the_listing_are_dropped():
    source = wiki_sources.wiki_source(SCRIPT)
    listed = ["User:Example/twinkle.js", "User:Example/twinkle", "User:Example/twinkle/notes"]
    assert wiki_sources.subpage_titles(source, listed) == ("User:Example/twinkle.js",)


def test_the_page_set_is_bounded():
    source = wiki_sources.wiki_source(SCRIPT)
    listed = [f"User:Example/twinkle/part{index}.js" for index in range(wiki_sources.MAX_PAGES * 2)]
    assert len(wiki_sources.subpage_titles(source, listed)) == wiki_sources.MAX_PAGES


def test_a_gadget_set_is_bounded():
    files = "|".join(f"Part{index}.js" for index in range(wiki_sources.MAX_PAGES * 2))
    assert len(wiki_sources.gadget_pages(f"* Big[RL]|{files}", "Part0.js")) == wiki_sources.MAX_PAGES


def test_the_allpages_query_is_namespace_relative():
    source = wiki_sources.wiki_source(SCRIPT)
    # apprefix is matched inside apnamespace, so the prefix must not repeat it.
    assert source.prefix == "Example/twinkle"
    assert source.namespace_id == 2
    assert wiki_sources.wiki_source(GADGET).namespace_id == 8


def test_a_canonical_page_url_round_trips():
    source = wiki_sources.wiki_source(SCRIPT)
    url = wiki_sources.page_url(source.domain, source.title)
    assert url == "https://en.wikipedia.org/wiki/User:Example/twinkle.js"
    assert wiki_sources.wiki_source(url) == source


def test_a_title_with_spaces_becomes_underscores_in_a_url():
    assert wiki_sources.page_url("en.wikipedia.org", "User:A B/c.js") == "https://en.wikipedia.org/wiki/User:A_B/c.js"


def test_a_title_longer_than_mediawiki_allows_is_truncated_not_rejected():
    long_title = "User:Example/" + "a" * 400 + ".js"
    assert len(wiki_sources.canonical_title(long_title)) == wiki_sources.MAX_TITLE_CHARS


def test_a_title_with_no_namespace_is_returned_unchanged():
    assert wiki_sources.canonical_title("Some_page.js") == "Some page.js"


def test_an_empty_title_is_no_title():
    assert wiki_sources.canonical_title("User:") == ""
    assert wiki_sources.canonical_title("") == ""


def test_source_on_a_single_site_project_is_reachable():
    # mediawiki.org is where a great many importable scripts and gadgets live.
    # While it was outside the host pattern every one of them scanned as a tool
    # with no source at all.
    script = wiki_sources.wiki_source("https://www.mediawiki.org/wiki/User:Ada/tool.js")
    assert script is not None
    assert (script.domain, script.kind) == ("www.mediawiki.org", wiki_sources.KIND_USER_SCRIPT)

    gadget = wiki_sources.wiki_source("https://www.mediawiki.org/wiki/MediaWiki:Gadget-Foo.js")
    assert gadget is not None
    assert gadget.kind == wiki_sources.KIND_GADGET
