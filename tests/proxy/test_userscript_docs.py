# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding the page a user script's author documented it on.

No wiki is reached. What is tested is the reasoning either side of the request:
which pages are worth asking about, how a wiki's answer is read when it
redirects or respells a title, and -- the part that decides whether this can run
hourly at all -- that a page once asked about is not asked about again, while a
page the run never got to stays pending.

The payload in `EN_ANSWER` is what en.wikipedia.org actually returned for those
four titles, kept verbatim rather than composed here: a parser tested only on
answers written to suit it cannot disagree with the parser.
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, userscript_docs as docs, userscripts  # noqa: E402
from backend.models import UserScriptDirectoryEntry, UserScriptPage, utcnow  # noqa: E402

ENWIKI = "en.wikipedia.org"

# en.wikipedia.org, 2026-08-26, for the four titles in `EN_ASKED`. One base page
# exists outright, two are redirects to documentation that moved out of user
# space, and one does not exist at all.
EN_ASKED = (
    "User:Lupin/popups",
    "User:Ale jrb/Scripts/igloo",
    "User:Nosuchuseratall/nope",
    "User:Cacycle/wikEd",
)
EN_ANSWER = {
    "batchcomplete": True,
    "query": {
        "redirects": [
            {"from": "User:Ale jrb/Scripts/igloo", "to": "Wikipedia:Igloo"},
            {"from": "User:Lupin/popups", "to": "Wikipedia:Tools/Navigation popups"},
        ],
        "pages": [
            {"ns": 2, "title": "User:Nosuchuseratall/nope", "missing": True},
            {"pageid": 2678531, "ns": 4, "title": "Wikipedia:Tools/Navigation popups"},
            {"pageid": 10002961, "ns": 2, "title": "User:Cacycle/wikEd"},
            {"pageid": 25077558, "ns": 4, "title": "Wikipedia:Igloo"},
        ],
    },
}


@pytest.fixture(autouse=True)
def _database():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret", trusted_hosts=backend.LOCAL_TRUSTED_HOSTS + backend.DEFAULT_TRUSTED_HOSTS)
    with application.app_context():
        yield


# --- fake wiki -------------------------------------------------------------


class Wiki:
    """Answers an existence query from a set of titles it says it holds.

    `redirects` is what the wiki would report having followed, so a test can
    describe a rename the way the API describes one rather than by pre-resolving
    it. `fail_after` makes the wiki refuse from that request onwards, which is
    every way a wiki can stop answering: lag, a timeout, a 500.
    """

    def __init__(self, titles=(), *, redirects=None, normalized=None, fail_after=None):
        self.titles = set(titles)
        self.redirects = dict(redirects or {})
        self.normalized = dict(normalized or {})
        self.fail_after = fail_after
        self.asked = []

    def request(self, wiki, method, params):
        assert method == "GET"
        asked = tuple(params["titles"].split("|"))
        self.asked.append((wiki, asked))
        if self.fail_after is not None and len(self.asked) > self.fail_after:
            raise RuntimeError("maxlag")
        hops = {title: self.normalized[title] for title in asked if title in self.normalized}
        landed = {hops.get(title, title) for title in asked}
        followed = {title: self.redirects[title] for title in landed if title in self.redirects}
        # A redirect's source is not among the pages the API answers about: it
        # reports the target instead, which is the behaviour being relied on.
        reported = (landed - set(followed)) | set(followed.values())
        pages = [
            {"title": title, "pageid": 1, "ns": 2} if title in self.titles else {"title": title, "missing": True}
            for title in sorted(reported)
        ]
        query = {"pages": pages}
        if hops:
            query["normalized"] = [{"from": key, "to": value} for key, value in sorted(hops.items())]
        if followed:
            query["redirects"] = [{"from": key, "to": value} for key, value in sorted(followed.items())]
        return {"query": query}


# --- helpers ---------------------------------------------------------------


def store(*titles, wiki=ENWIKI, role=userscripts.ROLE_SCRIPT, deleted=None, published=True):
    """Seed pages, and by default the directory entries that make them askable.

    `published=False` seeds the page alone, which is what a per-user copy of
    somebody else's script looks like: the census holds it, the directory folds
    it onto the original, and nothing ever publishes an answer for it.
    """
    with db.session_scope() as session:
        for title in titles:
            session.add(UserScriptPage(wiki=wiki, title=title, role=role, deleted_at=deleted))
            if published:
                session.add(UserScriptDirectoryEntry(wiki=wiki, title=title, owner="", basename="", tier="active"))


def stored(wiki=ENWIKI):
    """Return each page's documentation title, and whether it has been asked about."""
    with db.session_scope() as session:
        rows = session.query(UserScriptPage).filter(UserScriptPage.wiki == wiki).all()
        return {row.title: (row.docs_title, row.docs_checked_at is not None) for row in rows}


# --- which page is worth asking about --------------------------------------


def test_a_script_page_bases_to_the_page_beside_it():
    assert docs.base_title("User:Lupin/popups.js") == "User:Lupin/popups"


def test_a_stylesheet_and_a_json_page_base_the_same_way():
    assert docs.base_title("User:Tom/vector.css") == "User:Tom/vector"
    assert docs.base_title("User:Tom/config.json") == "User:Tom/config"


def test_a_suffix_the_wiki_wrote_in_capitals_is_still_a_suffix():
    assert docs.base_title("User:Tom/Gadget.JS") == "User:Tom/Gadget"


def test_a_page_that_is_not_a_subpage_has_no_documentation_page():
    """`User:Someone.js` bases to an account page, which documents nothing."""
    assert docs.base_title("User:Someone.js") == ""


def test_a_title_with_no_code_suffix_has_no_documentation_page():
    assert docs.base_title("User:Tom/notes") == ""


# --- reading the wiki's answer ---------------------------------------------


def test_a_base_page_that_exists_is_the_documentation_page():
    found = docs.resolved(EN_ANSWER, EN_ASKED)
    assert found["User:Cacycle/wikEd"] == "User:Cacycle/wikEd"


def test_a_redirect_is_followed_to_where_the_documentation_moved():
    """The convention survives a rename, and the reader wants the target."""
    found = docs.resolved(EN_ANSWER, EN_ASKED)
    assert found["User:Lupin/popups"] == "Wikipedia:Tools/Navigation popups"
    assert found["User:Ale jrb/Scripts/igloo"] == "Wikipedia:Igloo"


def test_a_base_page_the_wiki_has_never_had_is_absent_rather_than_empty():
    assert "User:Nosuchuseratall/nope" not in docs.resolved(EN_ANSWER, EN_ASKED)


def test_a_title_the_wiki_respells_is_followed_to_the_spelling_it_answered_about():
    payload = {
        "query": {
            "normalized": [{"from": "User:Tom/my_script", "to": "User:Tom/my script"}],
            "pages": [{"title": "User:Tom/my script", "pageid": 7, "ns": 2}],
        }
    }
    assert docs.resolved(payload, ("User:Tom/my_script",)) == {"User:Tom/my_script": "User:Tom/my script"}


def test_a_redirect_pointing_at_a_page_nobody_created_is_not_documentation():
    payload = {
        "query": {
            "redirects": [{"from": "User:Tom/script", "to": "Wikipedia:Gone"}],
            "pages": [{"title": "Wikipedia:Gone", "missing": True}],
        }
    }
    assert docs.resolved(payload, ("User:Tom/script",)) == {}


def test_an_answer_that_is_not_a_query_at_all_finds_nothing():
    assert docs.resolved({"error": {"code": "maxlag"}}, ("User:Tom/script",)) == {}


def test_a_page_list_that_is_not_a_list_answers_about_nothing():
    """Without `formatversion=2` the API keys pages by pageid instead of listing them."""
    payload = {"query": {"pages": {"2678531": {"pageid": 2678531, "title": "User:Tom/helper"}}}}
    # Reading that shape as a list would mean iterating the pageid strings and
    # concluding every page asked about is missing. Answering about none of them
    # is the difference between "not found" and "found nothing".
    assert docs.resolved(payload, ("User:Tom/helper",)) == {}


def test_a_hop_the_wiki_reported_only_half_of_is_not_followed():
    # A hop needs both ends. One with only a `from` names no destination, and
    # treating the title as its own target would report the redirect source as
    # the documentation page.
    payload = {
        "query": {
            "redirects": [{"from": "User:Tom/helper"}, {"from": "User:Ann/tool", "to": "Help:Tool"}],
            "pages": [{"pageid": 1, "title": "Help:Tool"}, {"pageid": 2, "title": "User:Tom/helper"}],
        }
    }
    assert docs.resolved(payload, ("User:Tom/helper", "User:Ann/tool")) == {
        "User:Tom/helper": "User:Tom/helper",
        "User:Ann/tool": "Help:Tool",
    }


def test_a_redirect_chain_longer_than_the_hop_budget_lands_nowhere():
    # Wikis hold double and triple redirects, and a loop is a redirect a bot has
    # not fixed yet. Following forever would hang the run; stopping short and
    # publishing whichever title the budget ran out on would name a page the
    # reader was only passing through.
    chain = [f"User:Tom/hop{index}" for index in range(6)]
    payload = {
        "query": {
            "redirects": [{"from": source, "to": target} for source, target in zip(chain, chain[1:], strict=False)],
            "pages": [{"pageid": 1, "title": chain[-1]}],
        }
    }
    assert docs.resolved(payload, (chain[0],)) == {}


# --- asking one wiki -------------------------------------------------------


def test_a_page_with_documentation_beside_it_is_recorded():
    store("User:Tom/helper.js")
    wiki = Wiki({"User:Tom/helper"})
    counts = docs.resolve(wiki.request, ENWIKI)
    assert (counts["found"], counts["written"]) == (1, 1)
    assert stored() == {"User:Tom/helper.js": ("User:Tom/helper", True)}


def test_a_page_with_none_is_recorded_as_asked_and_answered():
    """Empty and never-asked must not look the same, or every run asks again."""
    store("User:Tom/helper.js")
    counts = docs.resolve(Wiki().request, ENWIKI)
    assert (counts["checked"], counts["found"]) == (1, 0)
    assert stored() == {"User:Tom/helper.js": ("", True)}


def test_a_second_run_asks_the_wiki_nothing():
    store("User:Tom/helper.js")
    docs.resolve(Wiki({"User:Tom/helper"}).request, ENWIKI)
    again = Wiki({"User:Tom/helper"})
    counts = docs.resolve(again.request, ENWIKI)
    assert again.asked == []
    assert counts["requests"] == 0


def test_a_page_that_bases_to_nothing_is_settled_without_a_request():
    store("User:Someone.js")
    wiki = Wiki()
    counts = docs.resolve(wiki.request, ENWIKI)
    assert wiki.asked == []
    assert counts["checked"] == 1
    assert stored() == {"User:Someone.js": ("", True)}


def test_only_script_pages_are_asked_about():
    """A shim is somebody's one-line loader and documents nothing of its own."""
    store("User:Tom/shim.js", role=userscripts.ROLE_SHIM)
    wiki = Wiki({"User:Tom/shim"})
    counts = docs.resolve(wiki.request, ENWIKI)
    assert wiki.asked == []
    assert counts["asked"] == 0


def test_a_deleted_page_is_not_asked_about():
    store("User:Tom/gone.js", deleted=utcnow())
    wiki = Wiki({"User:Tom/gone"})
    assert docs.resolve(wiki.request, ENWIKI)["asked"] == 0
    assert wiki.asked == []


def test_titles_are_asked_fifty_at_a_time():
    store(*(f"User:Tom/script{index}.js" for index in range(120)))
    wiki = Wiki()
    counts = docs.resolve(wiki.request, ENWIKI)
    assert [len(asked) for _wiki, asked in wiki.asked] == [50, 50, 20]
    assert counts["requests"] == 3


def test_two_pages_sharing_one_base_page_both_get_it():
    """`User:Tom/thing.js` and `User:Tom/thing.css` document in one place."""
    store("User:Tom/thing.js", "User:Tom/thing.css")
    wiki = Wiki({"User:Tom/thing"})
    docs.resolve(wiki.request, ENWIKI)
    assert stored() == {
        "User:Tom/thing.js": ("User:Tom/thing", True),
        "User:Tom/thing.css": ("User:Tom/thing", True),
    }
    assert len(wiki.asked) == 1


# --- stopping, and being able to resume ------------------------------------


def test_the_request_cap_leaves_the_rest_of_the_wiki_pending():
    store(*(f"User:Tom/script{index:03d}.js" for index in range(100)))
    wiki = Wiki()
    counts = docs.resolve(wiki.request, ENWIKI, limit=1)
    assert counts["requests"] == 1
    assert sum(1 for _title, (_docs, checked) in stored().items() if checked) == 50


def test_a_run_whose_budget_matches_the_backlog_stops_without_asking_for_more():
    # The other way the loop ends. Every other test either runs out of pages or
    # is cut short mid-batch; here the last chunk of the batch spends the last
    # request, so the budget is what stops it -- and it must stop rather than
    # ask `pending` for a batch it has no request left to send.
    store(*(f"User:Tom/script{index:03d}.js" for index in range(50)))
    wiki = Wiki()
    counts = docs.resolve(wiki.request, ENWIKI, limit=1)
    assert counts["requests"] == 1
    assert len(wiki.asked) == 1
    assert counts["checked"] == 50


def test_a_batch_with_nothing_to_stamp_writes_nothing():
    # `apply_docs` opens a session per batch, and a batch cut short before its
    # first request has no page to stamp. Asking the database for rows matching
    # an empty list is a query that can only return nothing.
    with db.session_scope() as session:
        assert docs.apply_docs(session, {}, (), utcnow()) == 0


def test_a_wiki_that_stops_answering_leaves_the_unasked_pages_pending():
    """A refusal must not be recorded as `this page has no documentation`."""
    store(*(f"User:Tom/script{index:03d}.js" for index in range(100)))
    wiki = Wiki({"User:Tom/script000"}, fail_after=1)
    counts = docs.resolve(wiki.request, ENWIKI)
    checked = {title for title, (_docs, seen) in stored().items() if seen}
    assert len(checked) == 50
    assert counts["found"] == 1


def test_a_wiki_that_stops_answering_is_asked_again_next_run():
    store(*(f"User:Tom/script{index:03d}.js" for index in range(100)))
    docs.resolve(Wiki(fail_after=1).request, ENWIKI)
    counts = docs.resolve(Wiki({"User:Tom/script099"}).request, ENWIKI)
    assert counts["asked"] == 50
    assert counts["found"] == 1


def test_another_wikis_pages_are_left_alone():
    store("User:Tom/helper.js")
    store("Utilisateur:Tom/helper.js", wiki="fr.wikipedia.org")
    docs.resolve(Wiki({"User:Tom/helper", "Utilisateur:Tom/helper"}).request, ENWIKI)
    assert stored("fr.wikipedia.org") == {"Utilisateur:Tom/helper.js": ("", False)}


def test_a_per_user_copy_is_never_asked_about():
    """The catalogue publishes the original, so only the original is worth a request.

    Most of a wiki's script pages are copies of somebody else's script sitting
    in a personal common.js, and `userscript_toolinfo` reads `docs_title` off
    the directory entry's title alone. An answer found for a copy is written and
    never read, and it costs the same fiftieth of a request as a real one.
    """
    store("User:Lupin/popups.js")
    store("User:Someone/popups.js", "User:Another/popups.js", published=False)
    wiki = Wiki({"User:Lupin/popups"})

    counts = docs.resolve(wiki.request, ENWIKI)

    assert counts["asked"] == 1
    assert counts["requests"] == 1
    assert wiki.asked == [(ENWIKI, ("User:Lupin/popups",))]
    assert stored()["User:Someone/popups.js"] == ("", False)


def test_a_copy_the_directory_later_publishes_is_asked_about_then():
    """Nothing is settled for a page that was never asked, so promotion is enough."""
    store("User:Someone/popups.js", published=False)
    wiki = Wiki({"User:Someone/popups"})
    assert docs.resolve(wiki.request, ENWIKI)["asked"] == 0

    with db.session_scope() as session:
        session.add(
            UserScriptDirectoryEntry(wiki=ENWIKI, title="User:Someone/popups.js", owner="", basename="", tier="active")
        )

    assert docs.resolve(wiki.request, ENWIKI)["found"] == 1
    assert stored()["User:Someone/popups.js"] == ("User:Someone/popups", True)
