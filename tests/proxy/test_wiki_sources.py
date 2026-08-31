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

# One line as fr.wikipedia actually writes it, underscores and padding included.
UNDERSCORED = "* C_helper [ResourceLoader|dependencies=mediawiki.util] | C_helper.js | C_helper_util.js\n"


def test_a_user_subpage_with_a_code_suffix_is_a_user_script():
    source = wiki_sources.wiki_source(SCRIPT)
    assert source.domain == "en.wikipedia.org"
    assert source.title == "User:Example/twinkle.js"
    assert source.kind == wiki_sources.KIND_USER_SCRIPT


def test_a_gadget_url_resolves_to_a_page_rather_than_to_a_gadget():
    # A URL shows a title, and a title is a naming convention. What makes these
    # files a gadget is a line in a page this module has not read.
    source = wiki_sources.wiki_source(GADGET)
    assert source.kind == wiki_sources.KIND_GADGET_PAGE
    # This is the spelling Gadgets-definition lists, without the page prefix.
    assert source.filename == "Twinkle.js"


def test_the_definition_is_what_turns_a_gadget_page_into_a_gadget():
    page = wiki_sources.wiki_source(GADGET)
    gadget, pages = wiki_sources.registered_gadget(page, DEFINITION)
    assert gadget.kind == wiki_sources.KIND_GADGET
    assert pages == wiki_sources.gadget_pages(DEFINITION, "Twinkle.js")
    # Same page, same title, same everything else -- one fact was added.
    assert (gadget.domain, gadget.title) == (page.domain, page.title)


def test_a_gadget_page_the_definition_does_not_list_stays_a_page():
    # A gadget retired by deleting its definition line keeps its title. So does
    # one whose line has not been written yet. Neither is a gadget, and both
    # still hold source, so the page comes back as its own single-page set.
    page = wiki_sources.wiki_source("https://en.wikipedia.org/wiki/MediaWiki:Gadget-Retired.js")
    leftover, pages = wiki_sources.registered_gadget(page, DEFINITION)
    assert leftover.kind == wiki_sources.KIND_GADGET_PAGE
    assert pages == ("MediaWiki:Gadget-Retired.js",)


def test_an_empty_definition_registers_nothing():
    # A wiki whose definition page is missing, blank, or failed to parse must
    # not thereby promote every gadget-namespace page it hosts.
    page = wiki_sources.wiki_source(GADGET)
    unresolved, pages = wiki_sources.registered_gadget(page, "")
    assert unresolved.kind == wiki_sources.KIND_GADGET_PAGE
    assert pages == (page.title,)


def test_a_user_script_is_not_put_through_the_gadget_registry():
    # Registration is a gadget concept. A user script needs none, and passing
    # one here must not rename it or invent peers for it.
    script = wiki_sources.wiki_source(SCRIPT)
    unchanged, pages = wiki_sources.registered_gadget(script, DEFINITION)
    assert unchanged == script
    assert pages == (script.title,)


def test_a_definition_that_writes_underscores_still_registers_the_gadget():
    # Copied from fr.wikipedia, which registers this gadget with underscores
    # where Commons uses spaces. Both are the same title to MediaWiki, so both
    # have to be the same title here -- matching the raw text against a name
    # that arrived through canonical_title found no line and retired a gadget
    # that is live in everyone's Preferences.
    page = wiki_sources.wiki_source("https://fr.wikipedia.org/wiki/MediaWiki:Gadget-C_helper.js")
    gadget, pages = wiki_sources.registered_gadget(page, UNDERSCORED)
    assert gadget.kind == wiki_sources.KIND_GADGET
    assert pages == (
        "MediaWiki:Gadget-C helper.js",
        "MediaWiki:Gadget-C helper util.js",
    )


def test_both_spellings_of_one_title_reach_one_registration():
    # The two URLs name one page, so nothing downstream may be able to tell
    # which spelling a tool record happened to carry.
    underscored = wiki_sources.wiki_source("https://fr.wikipedia.org/wiki/MediaWiki:Gadget-C_helper.js")
    spaced = wiki_sources.wiki_source("https://fr.wikipedia.org/wiki/MediaWiki:Gadget-C%20helper.js")
    assert wiki_sources.registered_gadget(underscored, UNDERSCORED) == wiki_sources.registered_gadget(
        spaced, UNDERSCORED
    )


def test_an_underscored_definition_does_not_register_a_page_it_omits():
    # The normalization must widen how a name is spelled, not what counts as a
    # match: a page absent from an underscored definition is still absent.
    page = wiki_sources.wiki_source("https://fr.wikipedia.org/wiki/MediaWiki:Gadget-C_helper_absent.js")
    leftover, _ = wiki_sources.registered_gadget(page, UNDERSCORED)
    assert leftover.kind == wiki_sources.KIND_GADGET_PAGE


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


def test_a_prefix_neighbor_is_not_part_of_the_script():
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
    assert gadget.kind == wiki_sources.KIND_GADGET_PAGE


@pytest.mark.parametrize(
    "marked",
    [
        # Literal, as a body or a catalogue field would carry it.
        "https://en.wikipedia.org/wiki/User:Example/twinkle.js‎",
        # Percent-encoded, as a URL copied out of a browser bar carries it.
        "https://en.wikipedia.org/wiki/User:Example/twinkle.js%E2%80%8E",
    ],
)
def test_an_invisible_mark_resolves_to_the_same_source_page(marked):
    clean = wiki_sources.wiki_source(SCRIPT)
    found = wiki_sources.wiki_source(marked)

    assert clean is not None
    assert found is not None
    # Same page, so the same enrichment key: a mark nobody can see must not
    # split one gadget into two repositories.
    assert (found.domain, found.title) == (clean.domain, clean.title)
    assert wiki_sources.page_url(found.domain, found.title) == wiki_sources.page_url(clean.domain, clean.title)


# An inventory has to survive the definition pages wikis actually write, which
# is why this fixture is uglier than DEFINITION: a nested heading, a note left
# beside a file name, a duplicate declaration, and a bare option.
INVENTORY = """
== Appearance ==
* Popups[ResourceLoader]|Popups.js
=== Tabs ===
* Purge[ResourceLoader|dependencies=mediawiki.util|rights=purge|default]|Purge.js|Purge.css
* AjoutRapide[ResourceLoader]|AjoutRapide.js <!-- see T432122 before disabling -->
* Internals[ResourceLoader|hidden]|Internals.js
* Popups[ResourceLoader]|SomethingElse.js
* not a gadget line
"""


def test_the_inventory_lists_every_declared_gadget_in_page_order():
    found = wiki_sources.gadget_entries(INVENTORY)
    assert [entry.name for entry in found] == ["Popups", "Purge", "AjoutRapide", "Internals"]


def test_a_gadget_belongs_to_the_last_heading_above_it_at_any_depth():
    sections = {entry.name: entry.section for entry in wiki_sources.gadget_entries(INVENTORY)}
    # `=== Tabs ===` opens a section just as `== Appearance ==` does, which is
    # how MediaWiki itself reads the page.
    assert sections == {"Popups": "Appearance", "Purge": "Tabs", "AjoutRapide": "Tabs", "Internals": "Tabs"}


def test_a_note_beside_a_file_name_does_not_lose_the_file():
    entry = next(item for item in wiki_sources.gadget_entries(INVENTORY) if item.name == "AjoutRapide")
    # With the comment attached the entry stops ending in `.js`, and the gadget
    # would silently arrive with no pages at all rather than failing loudly.
    assert entry.pages == ("AjoutRapide.js",)


def test_a_repeated_gadget_keeps_its_first_declaration():
    entry = next(item for item in wiki_sources.gadget_entries(INVENTORY) if item.name == "Popups")
    # MediaWiki serves the first one, so a catalogue built on the last would
    # describe code no reader is running.
    assert entry.pages == ("Popups.js",)
    assert sum(1 for item in wiki_sources.gadget_entries(INVENTORY) if item.name == "Popups") == 1


def test_options_keep_their_values_and_bare_flags_stay_distinguishable():
    entry = next(item for item in wiki_sources.gadget_entries(INVENTORY) if item.name == "Purge")
    assert entry.values("dependencies") == ("mediawiki.util",)
    assert entry.values("rights") == ("purge",)
    # `default` is declared with no values, which is not the same as absent.
    assert entry.has("default") is True
    assert entry.values("default") == ()
    assert entry.has("hidden") is False
    assert entry.values("nothing-declared") == ()


def test_the_inventory_records_hidden_without_acting_on_it():
    entry = next(item for item in wiki_sources.gadget_entries(INVENTORY) if item.name == "Internals")
    # Whether a hidden gadget belongs in a catalogue is the caller's call; the
    # parser transcribes the page and nothing more.
    assert entry.has("hidden") is True


def test_an_entry_with_an_unclosed_bracket_is_not_a_gadget():
    assert wiki_sources.gadget_entries("* Broken[ResourceLoader|Broken.js") == ()


def test_an_entry_with_no_source_files_is_not_a_gadget():
    assert wiki_sources.gadget_entries("* Docs[ResourceLoader]|ReadMe") == ()
    assert wiki_sources.gadget_entries("* [ResourceLoader]|Orphan.js") == ()


def test_an_empty_option_between_pipes_is_skipped():
    entry = wiki_sources.gadget_entries("* X[ResourceLoader||hidden]|X.js")[0]
    assert [option for option, _values in entry.options] == ["ResourceLoader", "hidden"]


def test_the_inventory_and_the_page_lookup_agree_about_one_gadget():
    entry = next(item for item in wiki_sources.gadget_entries(DEFINITION) if item.name == "Twinkle")
    # The whole reason both readers live in this module: one gadget must not
    # have two different page sets depending on who asked.
    assert wiki_sources.gadget_titles(entry) == wiki_sources.gadget_pages(DEFINITION, "Twinkle.js")


def test_an_inventory_gadget_set_is_bounded():
    files = "|".join(f"Part{index}.js" for index in range(wiki_sources.MAX_PAGES + 10))
    entry = wiki_sources.gadget_entries(f"* Big[RL]|{files}")[0]
    assert len(entry.pages) == wiki_sources.MAX_PAGES


def test_a_localized_subpage_and_suffix_swap_are_collected_too():
    source = wiki_sources.wiki_source(SCRIPT)
    listed = ["Benutzer:Example/twinkle.js", "Benutzer:Example/twinkle.css", "Benutzer:Example/twinkle/core.js"]
    assert wiki_sources.subpage_titles(source, listed) == (
        "User:Example/twinkle.js",
        "User:Example/twinkle.css",
        "User:Example/twinkle/core.js",
    )


def test_a_page_name_holding_a_colon_keeps_it():
    # The rewrite replaces the namespace label, not the first colon in the
    # title: `a:b.js` is a page name, and losing half of it would send the
    # scanner after a page that does not exist.
    source = wiki_sources.wiki_source("https://de.wikipedia.org/wiki/User:Example/a:b.js")
    assert wiki_sources.listed_title(source, "Benutzer:Example/a:b.js") == "User:Example/a:b.js"


def test_a_canonical_listing_is_left_exactly_as_it_was():
    # The English wikis were the only ones this path ever worked on, so they
    # are the ones a change here must not move.
    source = wiki_sources.wiki_source(SCRIPT)
    assert wiki_sources.listed_title(source, "User:Example/twinkle.js") == "User:Example/twinkle.js"


# Verbatim from fr.wikipedia.org on 2026-08-30, through the same `allmessages`
# query `gadget_inventory.message_params` builds. Kept as the wiki wrote them
# rather than composed here: a reducer tested only on markup invented to suit it
# cannot disagree with the reducer, and every idiom that matters below --
# nbsp before a colon, a `<span lang>` inside italics, a bracketed reference
# link inside `<small>` -- is one no fixture of mine would have thought to use.
DELUXE_HISTORY = (
    "''DeluxeHistory'' : afficher les historiques en couleur en fonction du statut de contributeur "
    "<small><nowiki>[</nowiki>[[Aide:Historiques en couleur|documentation]]<nowiki>]</nowiki></small> "
    "<small><nowiki>[</nowiki>[[:Image:Histocouleur.jpg|illustration]]<nowiki>]</nowiki></small>."
)
POPUPS = (
    "''Popups'' : afficher une fenêtre ''<span class=\"lang-en\" lang=\"en\">popup</span>'' "
    "(« surgissante »), quand la souris passe sur un lien, proposant de nombreuses fonctionnalités "
    "<small><nowiki>[</nowiki>[[Utilisateur:Leag/Navigation popups|documentation]]<nowiki>]</nowiki></small>."
)


def test_a_real_description_message_reduces_to_the_sentence_it_says():
    assert wiki_sources.plain_text(DELUXE_HISTORY) == (
        "DeluxeHistory : afficher les historiques en couleur en fonction du statut de contributeur."
    )


def test_reduction_keeps_the_words_an_author_chose_and_drops_the_markup_around_them():
    # The `<span lang="en">` around "popup" is markup; the word is the author's.
    # French spacing inside the quotation marks is the author's too, and closing
    # it up would be this catalogue rewriting a wiki's typography.
    assert wiki_sources.plain_text(POPUPS) == (
        "Popups : afficher une fenêtre popup (« surgissante »), quand la souris passe sur un lien, "
        "proposant de nombreuses fonctionnalités."
    )


def test_a_link_keeps_its_label_and_loses_its_target():
    # The target is a page on one wiki and the label is the words the author
    # chose, so only one of the two means anything in a catalogue record.
    assert wiki_sources.plain_text("See [[Help:Editing|the guide]] and [[HotCat]].") == "See the guide and HotCat."


def test_an_external_link_with_no_label_leaves_nothing():
    # A bare URL is not a description, and the alternative to dropping it is
    # publishing an address where a sentence should be.
    assert wiki_sources.plain_text("Read [https://example.org/doc the manual], [https://example.org].") == (
        "Read the manual,."
    )


def test_a_template_the_wiki_could_not_resolve_is_not_published_as_prose():
    # The API expands templates before they arrive, so anything still bracketed
    # here is one the wiki itself failed on, and its name is not a description.
    assert wiki_sources.plain_text("{{int:gadget-foo}} adds a button &amp; a menu") == "adds a button & a menu"


def test_a_message_that_was_markup_all_the_way_down_reduces_to_nothing():
    # Not an error and not a description: the caller reads an empty result as a
    # gadget the wiki declares without saying anything about.
    assert wiki_sources.plain_text("<small><nowiki>[</nowiki>[[Aide:X|doc]]<nowiki>]</nowiki></small>") == ""


def test_a_page_written_under_the_current_terms_carries_the_four_licence():
    assert wiki_sources.content_license("2024-01-01T00:00:00Z") == "CC-BY-SA-4.0"


def test_a_page_older_than_the_current_terms_still_carries_the_three_licence():
    # The Terms changed in 2023 and could not reach back: a script published in
    # 2004 was licensed under 3.0 and nothing has relicensed it since. This is
    # the common case, not the exception -- of 120 enwiki user scripts sampled,
    # 102 predate the change.
    assert wiki_sources.content_license("2004-04-29T08:08:22Z") == "CC-BY-SA-3.0"


@pytest.mark.parametrize(
    "stamp,expected",
    [
        ("2023-06-06T23:59:59Z", "CC-BY-SA-3.0"),
        ("2023-06-07T00:00:00Z", "CC-BY-SA-4.0"),
    ],
)
def test_the_boundary_falls_on_the_day_the_terms_took_effect(stamp, expected):
    # A whole corpus turns on this instant, so it is pinned rather than left to
    # whichever comparison the implementation happens to use.
    assert wiki_sources.content_license(stamp) == expected


def test_a_bare_date_and_a_full_instant_agree():
    # Callers pass `wiki_replica.iso_timestamp` output, but the answer depends
    # only on the day and must not change with the precision it arrives in.
    assert wiki_sources.content_license("2023-06-07") == wiki_sources.content_license("2023-06-07T12:00:00Z")


@pytest.mark.parametrize("stamp", ["", "   ", "whenever", "2023"])
def test_an_undated_page_carries_no_licence_rather_than_the_likelier_guess(stamp):
    # Which version applies is a question about when. With no date there is no
    # answer, and 3.0 -- right about six pages in seven -- is still a guess.
    assert wiki_sources.content_license(stamp) == ""
