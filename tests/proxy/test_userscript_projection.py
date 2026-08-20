"""Tests for projecting a stored census into a ranked directory."""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, userscript_directory as directory, userscript_projection as projection  # noqa: E402
from backend.models import (  # noqa: E402
    UserScriptDirectoryEntry,
    UserScriptDirectoryMember,
    UserScriptImport,
    UserScriptPage,
    utcnow,
)

FRWIKI = "fr.wikipedia.org"
ENWIKI = "en.wikipedia.org"


@pytest.fixture(autouse=True)
def _database():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    with application.app_context():
        yield


def page(title, *, rank=0, role="script", fingerprint="", wiki=FRWIKI, deleted=False):
    """Store one census page, filling in what the projection reads."""
    with db.session_scope() as session:
        session.add(
            UserScriptPage(
                wiki=wiki,
                title=title,
                owner=directory.owner_of(title),
                basename=directory.basename_of(title),
                role=role,
                fingerprint=fingerprint,
                discovery_rank=rank,
                deleted_at=utcnow() if deleted else None,
            ),
        )


def loads(source, target, *, wiki=FRWIKI, target_wiki=""):
    """Store one observed load of `target` by `source`."""
    with db.session_scope() as session:
        session.add(
            UserScriptImport(
                wiki=wiki,
                source_title=source,
                verb="importScript",
                target_wiki=target_wiki,
                target_title=target,
            ),
        )


def entries(tier=None):
    """Directory entries for frwiki, in the order the tier is read."""
    with db.session_scope() as session:
        query = session.query(UserScriptDirectoryEntry).filter(UserScriptDirectoryEntry.wiki == FRWIKI)
        if tier is not None:
            query = query.filter(UserScriptDirectoryEntry.tier == tier)
        rows = query.order_by(UserScriptDirectoryEntry.tier, UserScriptDirectoryEntry.position).all()
        return [(row.title, row.tier, row.demand, row.instances, row.position) for row in rows]


def members():
    """Every membership row for frwiki, keyed by the page it files."""
    with db.session_scope() as session:
        rows = session.query(UserScriptDirectoryMember).filter(UserScriptDirectoryMember.wiki == FRWIKI).all()
        return {row.title: (row.origin_title, row.relation) for row in rows}


def test_a_lone_script_becomes_its_own_entry():
    page("User:Aaa/tool.js")
    assert projection.project(FRWIKI) == {
        "wiki": FRWIKI,
        "candidates": 1,
        "originals": 1,
        "active": 0,
        "archive": 1,
    }
    assert entries() == [("User:Aaa/tool.js", directory.TIER_ARCHIVE, 0, 0, 1)]
    assert members() == {"User:Aaa/tool.js": ("User:Aaa/tool.js", projection.RELATION_ORIGINAL)}


def test_only_script_pages_are_candidates():
    page("User:Aaa/tool.js", rank=0)
    page("User:Bbb/common.js", rank=1, role="empty")
    page("User:Ccc/vector.js", rank=2, role="shim")
    summary = projection.project(FRWIKI)
    assert summary["candidates"] == 1
    assert [title for title, *_ in entries()] == ["User:Aaa/tool.js"]


def test_a_deleted_page_leaves_the_directory():
    page("User:Aaa/tool.js", rank=0)
    page("User:Bbb/gone.js", rank=1, deleted=True)
    assert projection.project(FRWIKI)["candidates"] == 1
    assert "User:Bbb/gone.js" not in members()


def test_demand_is_counted_in_people_not_in_pages():
    # One person loading a script from two of their own slots is one user of it.
    page("User:Aaa/tool.js")
    loads("User:Bbb/common.js", "User:Aaa/tool.js")
    loads("User:Bbb/vector.js", "User:Aaa/tool.js")
    projection.project(FRWIKI)
    assert entries() == [("User:Aaa/tool.js", directory.TIER_ACTIVE, 1, 0, 1)]


def test_a_page_loading_itself_is_not_demand_for_itself():
    page("User:Aaa/tool.js")
    loads("User:Aaa/tool.js", "User:Aaa/tool.js")
    projection.project(FRWIKI)
    assert entries() == [("User:Aaa/tool.js", directory.TIER_ARCHIVE, 0, 0, 1)]


def test_a_load_from_another_wiki_still_counts():
    # These edges are the argument for a global gadget, so they must not be
    # filtered out by selecting imports on the source's wiki.
    page("User:Aaa/tool.js")
    loads("User:Zed/common.js", "User:Aaa/tool.js", wiki=ENWIKI, target_wiki=FRWIKI)
    projection.project(FRWIKI)
    assert entries() == [("User:Aaa/tool.js", directory.TIER_ACTIVE, 1, 0, 1)]


def test_a_load_pointing_at_another_wiki_does_not_count_here():
    page("User:Aaa/tool.js")
    loads("User:Bbb/common.js", "User:Aaa/tool.js", target_wiki=ENWIKI)
    projection.project(FRWIKI)
    assert entries() == [("User:Aaa/tool.js", directory.TIER_ARCHIVE, 0, 0, 1)]


def test_a_source_outside_user_space_counts_as_itself():
    page("User:Aaa/tool.js")
    loads("MediaWiki:Gadget-Foo.js", "User:Aaa/tool.js")
    projection.project(FRWIKI)
    assert entries() == [("User:Aaa/tool.js", directory.TIER_ACTIVE, 1, 0, 1)]


def test_an_identical_copy_is_filed_under_the_original_it_copies():
    page("User:Aaa/tool.js", rank=0, fingerprint="same")
    page("User:Bbb/tool.js", rank=1, fingerprint="same")
    loads("User:Ccc/common.js", "User:Bbb/tool.js")
    summary = projection.project(FRWIKI)
    assert summary == {"wiki": FRWIKI, "candidates": 2, "originals": 1, "active": 1, "archive": 0}
    # The copy's demand belongs to the original, and the copy is still listed.
    assert entries() == [("User:Aaa/tool.js", directory.TIER_ACTIVE, 1, 1, 1)]
    assert members()["User:Bbb/tool.js"] == ("User:Aaa/tool.js", projection.RELATION_COPY)


def test_a_crowded_filename_folds_as_a_variant_not_as_a_copy():
    # Byte-identical is a fact; a shared name is an inference. A reviewer reading
    # the directory has to be able to tell which one filed a page.
    for index, owner in enumerate(["Aaa", "Bbb", "Ccc", "Ddd", "Eee", "Fff"]):
        page(f"User:{owner}/common-config.js", rank=index, fingerprint=f"f{index}")
    projection.project(FRWIKI)
    filed = members()
    assert filed["User:Aaa/common-config.js"] == ("User:Aaa/common-config.js", projection.RELATION_ORIGINAL)
    assert filed["User:Fff/common-config.js"] == ("User:Aaa/common-config.js", projection.RELATION_VARIANT)


def test_entries_are_ranked_by_demand_within_each_tier():
    page("User:Aaa/quiet.js", rank=0)
    page("User:Bbb/popular.js", rank=1)
    page("User:Ccc/some.js", rank=2)
    for who in ["Ddd", "Eee", "Fff"]:
        loads(f"User:{who}/common.js", "User:Bbb/popular.js")
    loads("User:Ggg/common.js", "User:Ccc/some.js")
    projection.project(FRWIKI)
    assert entries(directory.TIER_ACTIVE) == [
        ("User:Bbb/popular.js", directory.TIER_ACTIVE, 3, 0, 1),
        ("User:Ccc/some.js", directory.TIER_ACTIVE, 1, 0, 2),
    ]
    assert entries(directory.TIER_ARCHIVE) == [("User:Aaa/quiet.js", directory.TIER_ARCHIVE, 0, 0, 1)]


def test_discovery_rank_decides_which_page_is_the_original():
    # The page enumerated first is the earlier one, whatever its title sorts as.
    page("User:Zed/tool.js", rank=0, fingerprint="same")
    page("User:Aaa/tool.js", rank=1, fingerprint="same")
    projection.project(FRWIKI)
    assert members()["User:Aaa/tool.js"] == ("User:Zed/tool.js", projection.RELATION_COPY)


def test_ranks_sort_numerically_rather_than_as_written():
    # Zero-padding is the point: "9" must come before "10", not after it.
    page("User:Aaa/tool.js", rank=9, fingerprint="same")
    page("User:Bbb/tool.js", rank=10, fingerprint="same")
    projection.project(FRWIKI)
    assert members()["User:Bbb/tool.js"] == ("User:Aaa/tool.js", projection.RELATION_COPY)


def test_a_negative_rank_does_not_escape_the_sort_key():
    assert projection._sort_key(-1) == projection._sort_key(0)


def test_another_wikis_directory_is_left_alone():
    page("User:Aaa/tool.js", rank=0)
    page("User:Zzz/other.js", rank=0, wiki=ENWIKI)
    projection.project(ENWIKI)
    projection.project(FRWIKI)
    with db.session_scope() as session:
        kept = session.query(UserScriptDirectoryEntry).filter(UserScriptDirectoryEntry.wiki == ENWIKI).all()
        assert [row.title for row in kept] == ["User:Zzz/other.js"]


def test_projecting_twice_leaves_one_directory_not_two():
    page("User:Aaa/tool.js")
    projection.project(FRWIKI)
    first = entries()
    projection.project(FRWIKI)
    assert entries() == first
    assert len(members()) == 1


def test_a_page_that_stops_being_an_original_loses_its_entry():
    # The rebuild exists for this: there is no row to update, because the entry
    # has become a member of somebody else's.
    page("User:Zed/tool.js", rank=0, fingerprint="same")
    projection.project(FRWIKI)
    assert [title for title, *_ in entries()] == ["User:Zed/tool.js"]
    page("User:Aaa/tool.js", rank=1, fingerprint="same")
    projection.project(FRWIKI)
    assert [title for title, *_ in entries()] == ["User:Zed/tool.js"]
    assert members()["User:Aaa/tool.js"] == ("User:Zed/tool.js", projection.RELATION_COPY)


def test_an_unswept_wiki_projects_an_empty_directory():
    assert projection.project(FRWIKI) == {
        "wiki": FRWIKI,
        "candidates": 0,
        "originals": 0,
        "active": 0,
        "archive": 0,
    }
    assert entries() == []
