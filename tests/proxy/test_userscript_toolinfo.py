"""Tests for turning a wiki's user-script directory into catalogue records."""

import sys
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, userscript_toolinfo  # noqa: E402
from backend.models import CanonicalToolCache, UserScriptDirectoryEntry, UserScriptPage, utcnow  # noqa: E402
from backend.sync import (  # noqa: E402
    LIFECYCLE_ACTIVE,
    LIFECYCLE_ARCHIVED,
    SOURCE_OFFICIAL,
    SOURCE_WIKI_USERSCRIPT,
    SYNC_EVOLVED_REAL,
)
from backend.userscript_directory import TIER_ACTIVE, TIER_ARCHIVE  # noqa: E402

FRWIKI = "fr.wikipedia.org"


@pytest.fixture(autouse=True)
def _database():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    with application.app_context():
        yield


def a_script(
    owner="Lupin",
    basename="popups.js",
    tier=TIER_ACTIVE,
    model="javascript",
    wiki=FRWIKI,
    demand=3,
    created="",
):
    """Store one directory entry and the page it was projected from."""
    title = f"User:{owner}/{basename}"
    with db.session_scope() as session:
        session.add(UserScriptPage(wiki=wiki, title=title, owner=owner, basename=basename, content_model=model))
        session.add(
            UserScriptDirectoryEntry(
                wiki=wiki,
                title=title,
                owner=owner,
                basename=basename,
                tier=tier,
                demand=demand,
                position=1,
                created_at_wiki=created,
            )
        )
    return title


def catalogued():
    with db.session_scope() as session:
        return {row.tool_name: row.record for row in session.execute(select(CanonicalToolCache)).scalars()}


def lifecycles():
    with db.session_scope() as session:
        return {row.tool_name: row.lifecycle for row in session.execute(select(CanonicalToolCache)).scalars()}


# --- what becomes a tool ---


def test_a_user_script_becomes_a_tool_the_catalogue_can_show():
    a_script()
    summary = userscript_toolinfo.synchronize(FRWIKI)

    assert summary["originals"] == 1
    assert summary["written"] == 1
    # The point of the lane: a name now exists in the table every card, facet,
    # search hit and author edge is reached through.
    assert sorted(catalogued()) == ["userscript-fr.wikipedia.org-lupin-popups.js"]


def test_the_record_transcribes_the_page_and_infers_nothing():
    a_script()
    userscript_toolinfo.synchronize(FRWIKI)

    record = catalogued()["userscript-fr.wikipedia.org-lupin-popups.js"]
    assert record["title"] == "popups.js"
    assert record["url"] == "https://fr.wikipedia.org/wiki/User:Lupin/popups.js"
    assert record["repository"] == "https://fr.wikipedia.org/wiki/User:Lupin/popups.js?action=raw"
    assert record["tool_type"] == "user script"
    assert record["for_wikis"] == [FRWIKI]
    assert record["technology_used"] == ["JavaScript"]
    # The owner is a fact about the title, not a guess about who wrote the code.
    assert record["author"] == [{"name": "Lupin", "wiki_username": "Lupin"}]
    # The one field that is not a transcription, and it carries the underscore
    # that says so.
    assert record["_lifecycle"] == LIFECYCLE_ACTIVE
    # No description. Nothing here has read any prose about this script.
    assert "description" not in record
    # And no creation date: no replica has dated this page.
    assert "created_date" not in record


def test_a_dated_script_publishes_its_pages_first_revision_as_a_creation_date():
    a_script(created="20090412183000")
    userscript_toolinfo.synchronize(FRWIKI)

    assert catalogued()["userscript-fr.wikipedia.org-lupin-popups.js"]["created_date"] == "2009-04-12T18:30:00Z"


def test_a_script_whose_stored_stamp_is_unreadable_publishes_no_date():
    """The directory's ordering stand-in is not a MediaWiki timestamp, and must never print as one."""
    a_script(created="00000000-0000000009919")
    userscript_toolinfo.synchronize(FRWIKI)

    assert "created_date" not in catalogued()["userscript-fr.wikipedia.org-lupin-popups.js"]


def test_the_row_is_marked_as_ours_so_a_catalog_snapshot_leaves_it_alone():
    a_script()
    userscript_toolinfo.synchronize(FRWIKI)

    with db.session_scope() as session:
        row = session.get(CanonicalToolCache, "userscript-fr.wikipedia.org-lupin-popups.js")
        assert row.source == SOURCE_WIKI_USERSCRIPT
        assert row.sync_status == SYNC_EVOLVED_REAL
        assert row.source_url == "https://fr.wikipedia.org/wiki/User:Lupin/popups.js"


# --- lifecycle ---


def test_an_archived_script_is_catalogued_and_said_to_be_archived():
    a_script(owner="Someone", basename="old.js", tier=TIER_ARCHIVE, demand=0)
    summary = userscript_toolinfo.synchronize(FRWIKI)

    # Catalogued, not omitted: a script nobody loads still exists.
    assert summary["written"] == 1
    assert lifecycles() == {"userscript-fr.wikipedia.org-someone-old.js": LIFECYCLE_ARCHIVED}


def test_a_loaded_script_is_marked_active():
    a_script()
    userscript_toolinfo.synchronize(FRWIKI)

    assert lifecycles() == {"userscript-fr.wikipedia.org-lupin-popups.js": LIFECYCLE_ACTIVE}


def test_the_lifecycle_column_is_derived_from_the_record_and_cannot_drift_from_it():
    a_script(tier=TIER_ARCHIVE, demand=0)
    userscript_toolinfo.synchronize(FRWIKI)

    with db.session_scope() as session:
        row = session.get(CanonicalToolCache, "userscript-fr.wikipedia.org-lupin-popups.js")
        assert row.lifecycle == row.record["_lifecycle"] == LIFECYCLE_ARCHIVED
        # A card reads card_record, not record, so the flag has to survive that
        # projection or an archived script would look healthy in every list.
        assert row.card_record["_lifecycle"] == LIFECYCLE_ARCHIVED


def test_a_record_that_never_mentions_a_lifecycle_leaves_the_column_empty():
    # Which is everything Toolhub hands us: nothing has measured those.
    with db.session_scope() as session:
        session.add(
            CanonicalToolCache(
                tool_name="stewardbots",
                record={"name": "stewardbots", "title": "Steward bots"},
                expires_at=utcnow(),
                stale_until=utcnow(),
            )
        )
    assert lifecycles() == {"stewardbots": ""}


def test_the_record_never_claims_the_author_deprecated_anything():
    a_script(tier=TIER_ARCHIVE, demand=0)
    userscript_toolinfo.synchronize(FRWIKI)

    # "Nobody loads it" is this codebase's observation. "Deprecated" would be
    # the author's own claim, and no author made one.
    assert "deprecated" not in catalogued()["userscript-fr.wikipedia.org-lupin-popups.js"]


def test_a_script_that_gains_an_audience_is_rewritten_not_left_stale():
    a_script(tier=TIER_ARCHIVE, demand=0)
    userscript_toolinfo.synchronize(FRWIKI)
    with db.session_scope() as session:
        entry = session.execute(select(UserScriptDirectoryEntry)).scalars().one()
        entry.tier = TIER_ACTIVE
    summary = userscript_toolinfo.synchronize(FRWIKI)

    # The lifecycle lives in the record, so the tier moving is a record change
    # and the unchanged shortcut cannot swallow it.
    assert summary["written"] == 1
    assert summary["unchanged"] == 0
    assert lifecycles() == {"userscript-fr.wikipedia.org-lupin-popups.js": LIFECYCLE_ACTIVE}


# --- what does not become a tool ---


def test_a_stylesheet_is_not_a_tool_however_much_code_it_holds():
    a_script(owner="Penquista", basename="monobook.css", model="css")
    summary = userscript_toolinfo.synchronize(FRWIKI)

    assert summary["stylesheet"] == 1
    assert summary["written"] == 0
    assert catalogued() == {}


def test_the_wiki_decides_what_is_a_stylesheet_not_the_suffix():
    # frwiki serves this page as javascript despite the name, so it is a script.
    a_script(owner="Penquista", basename="monobook.css", model="javascript")
    summary = userscript_toolinfo.synchronize(FRWIKI)

    assert summary["stylesheet"] == 0
    assert summary["written"] == 1


def test_templatestyles_counts_as_a_stylesheet_too():
    a_script(basename="styles.css", model="sanitized-css")
    assert userscript_toolinfo.synchronize(FRWIKI)["stylesheet"] == 1


def test_a_page_whose_name_slugs_to_nothing_gets_no_entry():
    a_script(owner="Пользователь", basename="скрипт")
    summary = userscript_toolinfo.synchronize(FRWIKI)

    assert summary["unnamed"] == 1
    assert catalogued() == {}


def test_two_titles_that_slug_to_one_name_keep_the_first_and_count_the_loss():
    # Two genuinely distinct MediaWiki titles: the wiki capitalizes only the
    # first letter after the namespace, so a subpage's case is significant.
    a_script(owner="Lupin", basename="popups.js")
    a_script(owner="Lupin", basename="Popups.js")
    summary = userscript_toolinfo.synchronize(FRWIKI)

    assert summary["duplicate"] == 1
    assert summary["written"] == 1


def test_a_name_another_source_owns_is_never_overwritten():
    a_script()
    with db.session_scope() as session:
        session.add(
            CanonicalToolCache(
                tool_name="userscript-fr.wikipedia.org-lupin-popups.js",
                record={"name": "userscript-fr.wikipedia.org-lupin-popups.js", "title": "Somebody's real tool"},
                source=SOURCE_OFFICIAL,
                expires_at=utcnow(),
                stale_until=utcnow(),
            )
        )
    summary = userscript_toolinfo.synchronize(FRWIKI)

    assert summary["conflicted"] == 1
    assert catalogued()["userscript-fr.wikipedia.org-lupin-popups.js"]["title"] == "Somebody's real tool"


# --- keeping in step ---


def test_running_twice_over_an_unchanged_directory_writes_nothing_the_second_time():
    a_script()
    userscript_toolinfo.synchronize(FRWIKI)
    summary = userscript_toolinfo.synchronize(FRWIKI)

    assert summary["written"] == 0
    assert summary["unchanged"] == 1


def test_a_script_that_stops_being_an_original_is_retired():
    a_script()
    userscript_toolinfo.synchronize(FRWIKI)
    with db.session_scope() as session:
        session.query(UserScriptDirectoryEntry).delete()
    summary = userscript_toolinfo.synchronize(FRWIKI)

    assert summary["retired"] == 1
    assert catalogued() == {}


def test_one_wiki_never_retires_another_wikis_scripts():
    a_script()
    a_script(wiki="meta.wikimedia.org", owner="Krinkle", basename="global.js")
    userscript_toolinfo.synchronize(FRWIKI)
    userscript_toolinfo.synchronize("meta.wikimedia.org")
    summary = userscript_toolinfo.synchronize(FRWIKI)

    assert summary["retired"] == 0
    assert sorted(catalogued()) == [
        "userscript-fr.wikipedia.org-lupin-popups.js",
        "userscript-meta.wikimedia.org-krinkle-global.js",
    ]


# --- names ---


@pytest.mark.parametrize(
    ("owner", "basename", "expected"),
    [
        ("Lupin", "popups.js", "userscript-fr.wikipedia.org-lupin-popups.js"),
        ("Dr Brains", "Cat-a-lot.js", "userscript-fr.wikipedia.org-dr-brains-cat-a-lot.js"),
        ("", "popups.js", ""),
        ("Lupin", "", ""),
    ],
)
def test_tool_name_is_built_from_wiki_owner_and_filename(owner, basename, expected):
    assert userscript_toolinfo.tool_name(FRWIKI, owner, basename) == expected
