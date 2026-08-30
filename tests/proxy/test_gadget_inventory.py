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

    def __init__(self, definition=DEFINITION, *, fails=False, messages=None, messages_fail=False):
        self.definition = definition
        self.fails = fails
        # Gadget name -> the wikitext of its `MediaWiki:Gadget-<name>` message.
        # A name absent here is a gadget whose message nobody ever wrote, which
        # is what 15% of frwiki's declarations look like.
        self.messages = messages or {}
        self.messages_fail = messages_fail
        self.requests = []
        self.message_requests = []

    def request(self, domain, method, params):
        if params.get("meta") == "allmessages":
            self.message_requests.append(params["ammessages"].split("|"))
            if self.messages_fail:
                raise Boom
            return {
                "query": {
                    "allmessages": [
                        {"name": f"Gadget-{name}", "content": self.messages[name]}
                        if name in self.messages
                        else {"name": f"Gadget-{name}", "missing": True}
                        for name in (key.removeprefix("Gadget-") for key in params["ammessages"].split("|"))
                    ]
                }
            }
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
    wiki = FakeWiki(messages={"Popups": "Navigation popups."})
    summary = gadget_inventory.ingest(wiki.request, FRWIKI)

    # The economics of the lane: user scripts cost thousands of requests, and
    # the whole inventory of a wiki costs one whatever it declares. Descriptions
    # add one request per 50 gadgets on top, so frwiki's 445 gadgets cost ten
    # requests rather than the 445 a page-per-gadget read would.
    assert len(wiki.requests) == 1
    assert wiki.message_requests == [["Gadget-Popups", "Gadget-Purge", "Gadget-Internals"]]
    assert summary == {
        "wiki": FRWIKI,
        "read": True,
        "reason": "read",
        "declared": 3,
        "added": 3,
        "updated": 0,
        "folded": 0,
        "retired": 0,
        "described": 1,
    }


def test_a_gadget_is_described_in_the_wikis_own_words():
    # The description a gadget has is the one its community wrote for its own
    # preferences screen. Reading it is what keeps gadgets out of the language
    # model that describes user scripts, which have no such sentence anywhere.
    wiki = FakeWiki(messages={"Popups": "\'\'Popups\'\' : afficher une fenêtre au survol d\'un lien."})
    gadget_inventory.ingest(wiki.request, FRWIKI)

    assert stored()["Popups"].description == "Popups : afficher une fenêtre au survol d\'un lien."
    assert stored()["Purge"].description == ""


def test_descriptions_are_asked_for_fifty_at_a_time():
    definition = "== A ==\n" + "".join(f"* Gadget{n}[ResourceLoader]|G{n}.js\n" for n in range(120))
    wiki = FakeWiki(definition)
    gadget_inventory.ingest(wiki.request, FRWIKI)

    assert [len(batch) for batch in wiki.message_requests] == [50, 50, 20]


def test_a_wiki_that_would_not_say_keeps_the_descriptions_it_had():
    # The definition page answered and the messages did not, so the gadgets are
    # known and their descriptions are not. Treating that silence as a
    # retraction would blank a wiki's descriptions on one bad response, which is
    # the same mistake `_unread` exists to prevent for the inventory itself.
    gadget_inventory.ingest(FakeWiki(messages={"Popups": "Navigation popups."}).request, FRWIKI)
    summary = gadget_inventory.ingest(FakeWiki(messages_fail=True).request, FRWIKI)

    assert stored()["Popups"].description == "Navigation popups."
    assert summary["described"] == 0


def test_a_description_the_wiki_has_deleted_is_cleared():
    # The opposite case, and the reason the one above has to be a distinct
    # answer rather than an empty one: here the wiki did tell us, and what it
    # said is that the message is gone.
    gadget_inventory.ingest(FakeWiki(messages={"Popups": "Navigation popups."}).request, FRWIKI)
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)

    assert stored()["Popups"].description == ""


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
    assert summary["reason"] == "request-failed"
    assert summary["retired"] == 0
    assert len(stored()) == 3


def test_an_empty_definition_page_retires_nothing():
    gadget_inventory.ingest(FakeWiki().request, FRWIKI)
    summary = gadget_inventory.ingest(FakeWiki("   \n").request, FRWIKI)

    assert summary["read"] is False
    # Distinct from a wiki that refused us: this one answered, and the answer
    # had no definitions in it. Reading every page as empty is a bug that
    # looks identical to an outage until the run says which it saw.
    assert summary["reason"] == "no-definition"
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
