# SPDX-License-Identifier: GPL-3.0-or-later
"""Author normalization keeps explicit handles and guessed labels distinct."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import toolinfo_authors  # noqa: E402


def _assertions(author):
    return toolinfo_authors.author_assertions({"name": "tool", "author": author})


def test_wiki_link_becomes_a_structured_handle():
    (assertion,) = _assertions("[[User:Emijrp]]")
    assert assertion.display_name == "Emijrp"
    assert assertion.wiki_username == "Emijrp"
    # Delimiter guessing was not involved, so the lower-trust flag stays off.
    assert assertion.legacy_delimited is False


def test_multiple_links_in_one_value_are_independent_authors():
    assertions = _assertions("[[User:Emijrp]] and [[User:The Photographer]]")
    assert [row.display_name for row in assertions] == ["Emijrp", "The Photographer"]
    assert all(row.wiki_username for row in assertions)
    assert assertions[0].position < assertions[1].position


def test_link_alias_and_subpage_are_not_identity():
    (piped,) = _assertions("[[User:Ada|Ada L.]]")
    assert piped.wiki_username == "Ada"
    (subpage,) = _assertions("[[User:Ada/sandbox]]")
    assert subpage.wiki_username == "Ada"


def test_underscores_normalize_to_the_canonical_title_form():
    (assertion,) = _assertions("[[User:The_Photographer]]")
    assert assertion.wiki_username == "The Photographer"


def test_repeated_link_to_one_account_is_a_single_assertion():
    assert len(_assertions("[[User:Ada]] and [[User:Ada]]")) == 1


def test_links_are_case_insensitive_and_tolerate_spacing():
    (assertion,) = _assertions("[[ user : Ada ]]")
    assert assertion.wiki_username == "Ada"


def test_structured_entry_with_wikitext_name_still_yields_the_handle():
    (assertion,) = _assertions([{"name": "[[User:Ada]]", "developer_username": "ada"}])
    assert assertion.wiki_username == "Ada"
    assert assertion.developer_username == "ada"


def test_declared_wiki_username_is_never_overridden_by_link_parsing():
    (assertion,) = _assertions([{"name": "[[User:Ada]]", "wiki_username": "Grace"}])
    assert assertion.wiki_username == "Grace"


def test_plain_labels_are_unaffected_and_stay_unstructured():
    (assertion,) = _assertions("Aaron Liu")
    assert assertion.display_name == "Aaron Liu"
    assert assertion.wiki_username == ""


def test_legacy_delimited_values_keep_their_lower_trust_flag():
    assertions = _assertions("Ada; Grace")
    assert [row.display_name for row in assertions] == ["Ada", "Grace"]
    assert all(row.legacy_delimited for row in assertions)


def test_a_linked_value_still_counts_as_a_listed_author():
    # Catalog statistics count listed authors from this function, so link
    # parsing must never empty a record that previously had an attribution.
    assert _assertions("[[User:Ada]]")
    assert toolinfo_authors.author_names({"author": "[[User:Ada]]"}) == ["Ada"]
