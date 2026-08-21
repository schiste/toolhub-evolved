"""Tests for reading a wiki's declared gadgets into the inventory."""

import sys
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, gadget_inventory  # noqa: E402
from backend.models import WikiGadget  # noqa: E402

FRWIKI = "fr.wikipedia.org"

DEFINITION = """
== Appearance ==
* Popups[ResourceLoader|dependencies=mediawiki.util]|Popups.js
* Purge[ResourceLoader|rights=purge|default]|Purge.js|Purge.css
* Internals[ResourceLoader|hidden]|Internals.js
"""


@pytest.fixture(autouse=True)
def _database():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    with application.app_context():
        yield


class Boom(RuntimeError):
    """A transport failure, as the client would raise it."""


class FakeWiki:
    """An Action API that answers with one definition page, or fails."""

    def __init__(self, definition=DEFINITION, *, fails=False):
        self.definition = definition
        self.fails = fails
        self.requests = []

    def request(self, domain, method, params):
        self.requests.append((domain, method, params))
        if self.fails:
            raise Boom
        revision = {"slots": {"main": {"content": self.definition}}}
        if "ids" in str(params.get("rvprop", "")).split("|"):
            # A wiki returns what was asked for and nothing more. A fake that
            # volunteers a revision id nobody requested is how a query that
            # read every real definition page as empty passed its tests.
            revision["revid"] = 1
        return {"query": {"pages": [{"title": "MediaWiki:Gadgets-definition", "revisions": [revision]}]}}


def stored(wiki=FRWIKI):
    with db.session_scope() as session:
        return {row.name: row for row in gadget_inventory.live(session, wiki)}


def test_one_request_reads_a_whole_wiki_of_gadgets():
    wiki = FakeWiki()
    summary = gadget_inventory.ingest(wiki.request, FRWIKI)

    # The economics of the lane: user scripts cost thousands of requests, the
    # gadget inventory costs one.
    assert len(wiki.requests) == 1
    assert summary == {"wiki": FRWIKI, "read": True, "declared": 3, "added": 3, "updated": 0, "folded": 0, "retired": 0}


def test_a_gadget_keeps_the_facts_the_definition_gave_it():
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    purge = stored()["Purge"]

    assert purge.section == "Appearance"
    assert purge.pages == ["Purge.js", "Purge.css"]
    assert purge.options == {"ResourceLoader": [], "rights": ["purge"], "default": []}
    assert purge.rights == ["purge"]
    assert purge.default_enabled is True
    assert purge.hidden is False


def test_hidden_is_recorded_not_filtered():
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    # The inventory transcribes. Whether a hidden gadget is a tool is a
    # question for the catalogue, and it cannot ask one that was thrown away.
    assert stored()["Internals"].hidden is True


def test_a_second_read_updates_rather_than_duplicates():
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    summary = gadget_inventory.ingest(FakeWiki().request, FRWIKI)

    assert summary["added"] == 0
    assert summary["updated"] == 3
    with db.session_scope() as session:
        assert len(list(session.execute(select(WikiGadget)).scalars())) == 3


def test_a_gadget_the_wiki_stopped_declaring_is_retired_not_deleted():
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    summary = gadget_inventory.ingest(FakeWiki("* Popups[ResourceLoader]|Popups.js").request, FRWIKI)

    assert summary["retired"] == 2
    assert sorted(stored()) == ["Popups"]
    with db.session_scope() as session:
        # The row survives so a catalogue entry built from it can be retired
        # deliberately rather than losing the reason it existed.
        rows = list(session.execute(select(WikiGadget).where(WikiGadget.deleted_at.is_not(None))).scalars())
        assert sorted(row.name for row in rows) == ["Internals", "Purge"]


def test_a_returning_gadget_stops_being_retired():
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    gadget_inventory.ingest(FakeWiki("* Popups[ResourceLoader]|Popups.js").request, FRWIKI)
    summary = gadget_inventory.ingest(FakeWiki().request, FRWIKI)

    assert summary["retired"] == 0
    assert sorted(stored()) == ["Internals", "Popups", "Purge"]


def test_an_unreadable_wiki_retires_nothing():
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    summary = gadget_inventory.ingest(FakeWiki(fails=True).request, FRWIKI)

    # Silence is not a statement that the gadgets are gone. Treating it as one
    # would empty the inventory on the first bad response.
    assert summary["read"] is False
    assert summary["retired"] == 0
    assert len(stored()) == 3


def test_an_empty_definition_page_retires_nothing():
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    summary = gadget_inventory.ingest(FakeWiki("   \n").request, FRWIKI)

    assert summary["read"] is False
    assert len(stored()) == 3


def test_two_names_storage_cannot_tell_apart_become_one_row():
    # MySQL folds case and ignores invisible marks; SQLite does neither, so a
    # test on SQLite can only prove this by asking the same question the index
    # asks. Getting it wrong is how the first Meta census died.
    definition = "* Popups[RL]|Popups.js\n* popups[RL]|Other.js\n* Popups‎[RL]|Third.js"
    summary = gadget_inventory.ingest(FakeWiki(definition).request, FRWIKI)

    assert summary["declared"] == 3
    assert summary["added"] == 1
    assert summary["folded"] == 2
    # MediaWiki serves the first declaration, so the first is what we describe.
    assert stored()["Popups"].pages == ["Popups.js"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Popups", "popups"),
        ("popups", "popups"),
        ("Popups‎", "popups"),
        ("  Popups  ", "popups"),
        ("", ""),
    ],
)
def test_the_storage_key_answers_the_question_the_index_asks(name, expected):
    assert gadget_inventory.storage_key(name) == expected


def test_a_wiki_with_no_gadgets_at_all_reads_clean():
    summary = gadget_inventory.ingest(FakeWiki("== Empty ==\n").request, FRWIKI)

    assert summary["read"] is True
    assert summary["declared"] == 0
    assert stored() == {}


def test_the_inventory_is_bounded(monkeypatch):
    monkeypatch.setattr(gadget_inventory, "MAX_GADGETS", 2)
    definition = "\n".join(f"* G{index}[RL]|G{index}.js" for index in range(5))
    summary = gadget_inventory.ingest(FakeWiki(definition).request, FRWIKI)

    assert summary["declared"] == 5
    assert summary["added"] == 2
