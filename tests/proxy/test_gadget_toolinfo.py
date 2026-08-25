"""Tests for turning a wiki's declared gadgets into catalogue records."""

import sys
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import catalog_projection, db, gadget_inventory, gadget_toolinfo  # noqa: E402
from backend.models import CanonicalToolCache, CatalogFacetValue, CatalogToolProjection, WikiGadget, utcnow  # noqa: E402
from backend.sync import SOURCE_OFFICIAL, SOURCE_WIKI_GADGET, SYNC_EVOLVED_REAL  # noqa: E402

FRWIKI = "fr.wikipedia.org"

DEFINITION = """
== Appearance ==
* Popups[ResourceLoader|dependencies=mediawiki.util]|Popups.js|Popups.css
* Purge[ResourceLoader|rights=purge]|Purge.js
* Internals[ResourceLoader|hidden]|Internals.js
"""


@pytest.fixture(autouse=True)
def _database():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    with application.app_context():
        yield


class FakeWiki:
    """An Action API answering with one gadget definition page."""

    def __init__(self, definition=DEFINITION):
        self.definition = definition

    def request(self, _domain, _method, _params):
        return {
            "query": {
                "pages": [
                    {
                        "title": "MediaWiki:Gadgets-definition",
                        "revisions": [{"revid": 1, "slots": {"main": {"content": self.definition}}}],
                    }
                ]
            }
        }


def catalogued():
    with db.session_scope() as session:
        return {row.tool_name: row.record for row in session.execute(select(CanonicalToolCache)).scalars()}


def a_gadget(**overrides):
    """Build an inventory row directly, for records no definition page can express."""
    fields = {"wiki": FRWIKI, "name": "Popups", "name_key": "popups", "pages": ["Popups.js"], "hidden": False}
    return WikiGadget(**{**fields, **overrides})


def test_a_gadget_becomes_a_tool_the_catalogue_can_show():
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    summary = gadget_toolinfo.synchronize(FRWIKI)

    assert summary["declared"] == 3
    assert summary["written"] == 2
    # The whole point of the lane: a name now exists in the table every card,
    # facet, search hit and author edge is reached through.
    assert sorted(catalogued()) == ["gadget-fr.wikipedia.org-popups", "gadget-fr.wikipedia.org-purge"]


def test_the_record_transcribes_the_declaration_and_invents_nothing():
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    gadget_toolinfo.synchronize(FRWIKI)
    record = catalogued()["gadget-fr.wikipedia.org-popups"]

    assert record == {
        "name": "gadget-fr.wikipedia.org-popups",
        "title": "Popups",
        "url": "https://fr.wikipedia.org/wiki/Special:Gadgets#gadget-Popups",
        "tool_type": "gadget",
        "for_wikis": [FRWIKI],
        "repository": "https://fr.wikipedia.org/wiki/MediaWiki:Gadget-Popups.js",
        "technology_used": ["JavaScript", "CSS"],
    }
    # And in particular no creation date: this run reached no replica, and the
    # definition page says nothing about when the gadget was written.
    assert "created_date" not in record
    # An empty description is a gap somebody can fill. A guessed one is this
    # codebase putting words in a maintainer's mouth.
    assert "description" not in record


def test_a_record_is_marked_as_ours_so_a_catalog_sync_leaves_it_alone():
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    gadget_toolinfo.synchronize(FRWIKI)

    with db.session_scope() as session:
        row = session.get(CanonicalToolCache, "gadget-fr.wikipedia.org-popups")
        assert row.source == SOURCE_WIKI_GADGET
        assert row.sync_status == SYNC_EVOLVED_REAL
        # Derived by the model from the record, which is what makes the tool
        # findable rather than merely present.
        assert "popups" in row.search_text


def test_a_hidden_gadget_gets_no_entry():
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    summary = gadget_toolinfo.synchronize(FRWIKI)

    # Machinery another gadget loads, not something a reader can choose. The
    # inventory records it; deciding it is not a tool happens here.
    assert summary["hidden"] == 1
    assert "gadget-fr.wikipedia.org-internals" not in catalogued()


def test_running_twice_rewrites_nothing():
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    gadget_toolinfo.synchronize(FRWIKI)
    summary = gadget_toolinfo.synchronize(FRWIKI)

    assert summary["written"] == 0
    assert summary["unchanged"] == 2


def test_a_changed_declaration_rewrites_the_record():
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    gadget_toolinfo.synchronize(FRWIKI)
    gadget_inventory.ingest(FakeWiki(DEFINITION.replace("|Popups.css", "")).request, FRWIKI)
    summary = gadget_toolinfo.synchronize(FRWIKI)

    assert summary["written"] == 1
    assert catalogued()["gadget-fr.wikipedia.org-popups"]["technology_used"] == ["JavaScript"]


def test_a_gadget_the_wiki_stopped_declaring_loses_its_entry():
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    gadget_toolinfo.synchronize(FRWIKI)
    gadget_inventory.ingest(FakeWiki("* Popups[RL]|Popups.js").request, FRWIKI)
    summary = gadget_toolinfo.synchronize(FRWIKI)

    # The only thing that ever asserted this tool exists has stopped saying so.
    assert summary["retired"] == 1
    assert sorted(catalogued()) == ["gadget-fr.wikipedia.org-popups"]


def test_a_name_another_record_already_owns_is_never_overwritten():
    now = utcnow()
    with db.session_scope() as session:
        session.add(
            CanonicalToolCache(
                tool_name="gadget-fr.wikipedia.org-popups",
                record={"name": "gadget-fr.wikipedia.org-popups", "title": "Somebody else's tool"},
                fetched_at=now,
                expires_at=now,
                stale_until=now,
                source=SOURCE_OFFICIAL,
            )
        )
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    summary = gadget_toolinfo.synchronize(FRWIKI)

    assert summary["conflicted"] == 1
    # Overwriting a real catalogue record to resolve a name collision is not a
    # trade this lane is allowed to make.
    assert catalogued()["gadget-fr.wikipedia.org-popups"]["title"] == "Somebody else's tool"


def test_two_gadget_names_that_slug_alike_yield_one_entry():
    gadget_inventory.ingest(FakeWiki("* My Gadget[RL]|A.js\n* My-Gadget[RL]|B.js").request, FRWIKI)
    summary = gadget_toolinfo.synchronize(FRWIKI)

    assert summary["duplicate"] == 1
    assert catalogued()["gadget-fr.wikipedia.org-my-gadget"]["title"] == "My Gadget"


def test_a_gadget_with_no_latin_name_is_left_out_rather_than_named_after_its_wiki():
    with db.session_scope() as session:
        session.add(a_gadget(name="Всплывающие", name_key="всплывающие"))
    summary = gadget_toolinfo.synchronize(FRWIKI)

    # Naming it after the wiki alone would collide with every other such gadget.
    assert summary["unnamed"] == 1
    assert catalogued() == {}


@pytest.mark.parametrize(
    ("wiki", "name", "expected"),
    [
        (FRWIKI, "Popups", "gadget-fr.wikipedia.org-popups"),
        (FRWIKI, "popups‎", "gadget-fr.wikipedia.org-popups"),
        (FRWIKI, "My Gadget!", "gadget-fr.wikipedia.org-my-gadget"),
        ("", "Popups", ""),
        (FRWIKI, "  ", ""),
    ],
)
def test_the_catalogue_name_is_built_from_one_lowercase_alphabet(wiki, name, expected):
    # Storage folds case and ignores invisible marks; spellings it calls equal
    # must not arrive in the catalogue looking different.
    assert gadget_toolinfo.tool_name(wiki, name) == expected


def test_a_declaration_with_nothing_to_transcribe_still_produces_a_record():
    # No definition page can say this, but a row written by an older version of
    # the inventory could, and the record builder must not fall over on one.
    record = gadget_toolinfo.toolinfo_record(a_gadget(pages=[]))

    assert "repository" not in record
    assert "technology_used" not in record


def test_a_dated_gadget_publishes_its_first_revision_as_a_creation_date():
    record = gadget_toolinfo.toolinfo_record(a_gadget(created_at_wiki="20070311120000"))

    assert record["created_date"] == "2007-03-11T12:00:00Z"


def test_an_undated_gadget_publishes_no_creation_date_at_all():
    """No replica has answered for it; a `first_seen_at` in 2026 is not the answer."""
    assert "created_date" not in gadget_toolinfo.toolinfo_record(a_gadget())


def test_a_gadget_whose_stored_stamp_is_unreadable_publishes_no_date():
    assert "created_date" not in gadget_toolinfo.toolinfo_record(a_gadget(created_at_wiki="whenever"))


def test_a_gadget_shouting_its_suffix_is_still_javascript():
    # The definition parser accepts the suffix casefolded, so this side must too
    # or the file is stored and its language silently lost.
    assert gadget_toolinfo.toolinfo_record(a_gadget(pages=["Popups.JS"]))["technology_used"] == ["JavaScript"]


def test_a_wiki_with_no_gadgets_changes_nothing():
    summary = gadget_toolinfo.synchronize(FRWIKI)

    assert summary == {"wiki": FRWIKI, **dict.fromkeys(gadget_toolinfo.COUNT_FIELDS, 0)}
    assert catalogued() == {}


def _projected(name):
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    gadget_toolinfo.synchronize(FRWIKI)
    catalog_projection.refresh_candidates()
    with db.session_scope() as session:
        row = session.get(CatalogToolProjection, name)
        facets = {
            (facet.field, facet.value): facet.confidence_basis_points
            for facet in session.execute(select(CatalogFacetValue).where(CatalogFacetValue.tool_name == name)).scalars()
        }
        return row.effective_record, row.provenance, facets


def test_a_gadget_reaches_the_catalogue_projection_like_any_other_tool():
    effective, _provenance, facets = _projected("gadget-fr.wikipedia.org-popups")

    # The whole ask: a gadget is elevated to exactly the level of a tool. Same
    # projection row, same facet rows, reached by the same refresh pass.
    assert effective["title"] == "Popups"
    assert effective["tool_type"] == "gadget"
    assert effective["for_wikis"] == [FRWIKI]
    assert ("tool_type", "gadget") in facets
    assert ("wiki", FRWIKI) in facets


def test_the_projection_says_a_wiki_declared_this_not_toolhub():
    _effective, provenance, facets = _projected("gadget-fr.wikipedia.org-popups")

    # Toolhub has never heard of this tool. Reporting the record as
    # official_toolhub would put a claim in its mouth on every card and every
    # evidence panel.
    assert {entry["source"] for entry in provenance["title"]} == {catalog_projection.SOURCE_GADGET}
    assert (
        facets[("tool_type", "gadget")] == catalog_projection.SOURCE_CONFIDENCE[catalog_projection.SOURCE_GADGET] * 100
    )
