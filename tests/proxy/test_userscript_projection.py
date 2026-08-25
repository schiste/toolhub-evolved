"""Tests for projecting a stored census into a ranked directory."""

import sys
from pathlib import Path
from unittest import mock

import pytest
from flask import Flask
from sqlalchemy import event

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import (  # noqa: E402
    db,
    userscripts,
    userscript_directory as directory,
    userscript_projection as projection,
    userscript_sweep as sweep,
)
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


def page(title, *, rank=0, role="script", fingerprint="", wiki=FRWIKI, deleted=False, created="", touched="", body=""):
    """Store one census page, filling in what the projection reads."""
    with db.session_scope() as session:
        session.add(
            UserScriptPage(
                wiki=wiki,
                title=title,
                owner=directory.owner_of_user_page(title),
                basename=directory.basename_of(title),
                role=role,
                fingerprint=fingerprint,
                sketch=userscripts.sketch(body),
                discovery_rank=rank,
                created_at_wiki=created,
                touched_at_wiki=touched,
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
        "repaired": 0,
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
    # The loading pages are stored too, because an import only exists in the
    # first place because its source page was swept -- and the owner demand
    # counts is the one that sweep resolved.
    page("User:Aaa/tool.js")
    page("User:Bbb/common.js", role="shim")
    page("User:Bbb/vector.js", role="shim")
    loads("User:Bbb/common.js", "User:Aaa/tool.js")
    loads("User:Bbb/vector.js", "User:Aaa/tool.js")
    projection.project(FRWIKI)
    assert entries() == [("User:Aaa/tool.js", directory.TIER_ACTIVE, 1, 0, 1)]


def test_demand_counts_people_on_a_wiki_whose_namespace_no_alias_list_knows():
    # `Benutzer:` is not in `_NAMESPACE_ALIASES`, so these titles reach storage
    # with the wiki's own prefix intact. Reading the owner by position resolves
    # them to one person, so the script has one user, not two.
    page("Benutzer:Aaa/tool.js")
    page("Benutzer:Bbb/common.js", role="shim")
    page("Benutzer:Bbb/vector.js", role="shim")
    loads("Benutzer:Bbb/common.js", "Benutzer:Aaa/tool.js")
    loads("Benutzer:Bbb/vector.js", "Benutzer:Aaa/tool.js")
    projection.project(FRWIKI)
    assert entries() == [("Benutzer:Aaa/tool.js", directory.TIER_ACTIVE, 1, 0, 1)]


def test_the_crowded_name_fold_fires_on_a_namespace_no_alias_list_knows():
    # The fold this census exists for -- 472 `LiveRCparam.js` pages sharing no
    # content, one per person -- counts distinct *owners*. On a wiki whose
    # prefix no alias list covers, every row used to store an empty owner, so
    # the group looked like one person and the fold could never fire.
    for index, owner in enumerate(["Aaa", "Bbb", "Ccc", "Ddd", "Eee"]):
        page(f"Benutzer:{owner}/LiveRCparam.js", rank=index)
    projection.project(FRWIKI)
    assert entries() == [("Benutzer:Aaa/LiveRCparam.js", directory.TIER_ARCHIVE, 0, 4, 1)]


def test_a_crowded_name_below_the_owner_threshold_is_left_alone():
    # The same five pages owned by one person are one person's habit across
    # skin slots, not a convention shared across the wiki, and must not fold.
    for index in range(5):
        page(f"Benutzer:Aaa/skin{index}/LiveRCparam.js", rank=index)
    projection.project(FRWIKI)
    assert len(entries()) == 5


def test_a_page_loading_itself_is_not_demand_for_itself():
    page("User:Aaa/tool.js")
    loads("User:Aaa/tool.js", "User:Aaa/tool.js")
    projection.project(FRWIKI)
    assert entries() == [("User:Aaa/tool.js", directory.TIER_ARCHIVE, 0, 0, 1)]


def test_a_page_loading_another_page_of_its_own_owner_is_not_demand():
    # The case self-loading was only the narrowest instance of: one person
    # wiring up their own setup. Counting it makes every helper subpage on the
    # wiki look like it has a user, which is exactly what demand is meant to
    # distinguish.
    page("User:Aaa/helper.js")
    page("User:Aaa/common.js", role="shim")
    page("User:Aaa/vector.js", role="shim")
    loads("User:Aaa/common.js", "User:Aaa/helper.js")
    loads("User:Aaa/vector.js", "User:Aaa/helper.js")
    projection.project(FRWIKI)
    assert entries() == [("User:Aaa/helper.js", directory.TIER_ARCHIVE, 0, 0, 1)]


def test_somebody_else_loading_the_same_helper_still_counts():
    # The owner's own loads are dropped; the moment a second person loads it,
    # the script has the demand it is claiming.
    page("User:Aaa/helper.js")
    page("User:Aaa/common.js", role="shim")
    page("User:Bbb/common.js", role="shim")
    loads("User:Aaa/common.js", "User:Aaa/helper.js")
    loads("User:Bbb/common.js", "User:Aaa/helper.js")
    projection.project(FRWIKI)
    assert entries() == [("User:Aaa/helper.js", directory.TIER_ACTIVE, 1, 0, 1)]


def test_an_owner_loading_their_own_script_from_another_wiki_is_still_the_owner():
    # Usernames are global across Wikimedia wikis, so `User:Aaa` on enwiki is
    # the author of `User:Aaa/tool.js` on frwiki, and their own cross-wiki load
    # is not the argument for a global gadget it would otherwise look like.
    page("User:Aaa/tool.js")
    page("User:Aaa/common.js", role="shim", wiki=ENWIKI)
    loads("User:Aaa/common.js", "User:Aaa/tool.js", wiki=ENWIKI, target_wiki=FRWIKI)
    projection.project(FRWIKI)
    assert entries() == [("User:Aaa/tool.js", directory.TIER_ARCHIVE, 0, 0, 1)]


def test_pages_whose_owner_did_not_parse_do_not_cancel_against_each_other():
    # An empty owner is "not known", not "the same person". Treating two
    # unattributable pages as one owner would silently delete demand rather
    # than decline to count it.
    page("NoNamespace.js")
    page("AlsoNoNamespace.js", role="shim")
    loads("AlsoNoNamespace.js", "NoNamespace.js")
    projection.project(FRWIKI)
    assert entries() == [("NoNamespace.js", directory.TIER_ACTIVE, 1, 0, 1)]


def test_a_load_from_another_wiki_still_counts():
    # These edges are the argument for a global gadget, so they must not be
    # filtered out by selecting imports on the source's wiki.
    page("User:Aaa/tool.js")
    page("User:Zed/common.js", role="shim", wiki=ENWIKI)
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
    # `repaired` counts the loads that had no identity until this run gave them
    # one -- the reader fixing its own input rather than trusting a sweep ran.
    assert summary == {"wiki": FRWIKI, "candidates": 2, "repaired": 1, "originals": 1, "active": 1, "archive": 0}
    # The copy's demand belongs to the original, and the copy is still listed.
    assert entries() == [("User:Aaa/tool.js", directory.TIER_ACTIVE, 1, 1, 1)]
    assert members()["User:Bbb/tool.js"] == ("User:Aaa/tool.js", projection.RELATION_COPY)


def script(count, name="a"):
    """A body long enough that one changed line leaves a near copy of it."""
    return "\n".join(f"var {name}{at} = {at} * 3 + '{name}';" for at in range(count))


def test_a_near_copy_is_filed_as_a_fork_rather_than_a_copy():
    # Three strengths, and the entry has to say which one filed a page: identical
    # is a fact, most-of-the-same-body is an observation, a shared name is an
    # inference. Only the middle one survives somebody editing their own settings.
    body = script(200)
    theirs = body.replace("var a7 = 7 * 3 + 'a';", "var a7 = 42 * 3 + 'a';")
    page("User:Aaa/tool.js", rank=0, fingerprint="a", body=body)
    page("User:Bbb/other.js", rank=1, fingerprint="b", body=theirs)
    summary = projection.project(FRWIKI)
    assert summary["candidates"] == 2
    assert summary["originals"] == 1
    assert entries() == [("User:Aaa/tool.js", directory.TIER_ARCHIVE, 0, 1, 1)]
    assert members()["User:Bbb/other.js"] == ("User:Aaa/tool.js", projection.RELATION_FORK)


def test_a_page_with_no_stored_sketch_is_still_its_own_script():
    # What a directory run sees while the backfill is still walking the table.
    page("User:Aaa/tool.js", rank=0, fingerprint="a")
    page("User:Bbb/other.js", rank=1, fingerprint="b")
    assert projection.project(FRWIKI)["originals"] == 2


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
    # Where no creation date could be established -- every host without a replica
    # -- the page enumerated first is the earlier one, whatever its title sorts as.
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


def test_the_creation_date_the_wiki_reports_beats_the_order_we_found_it_in():
    """Enumeration order is a stand-in. Where a real date exists it is the answer."""
    page("User:Zed/tool.js", rank=0, fingerprint="same", created="20140101000000")
    page("User:Aaa/tool.js", rank=1, fingerprint="same", created="20090101000000")
    projection.project(FRWIKI)
    assert members()["User:Zed/tool.js"] == ("User:Aaa/tool.js", projection.RELATION_COPY)


def test_a_page_with_no_creation_date_cannot_outrank_one_that_has_it():
    """The two keys are compared as strings, so the fallback must sort behind.

    Without the leading digit that puts it there, a zero-padded rank would begin
    with a 0 and beat every real timestamp -- so a page discovered first on a
    host with no replica would claim to predate a page created in 2003.
    """
    page("User:Aaa/tool.js", rank=0, fingerprint="same")
    page("User:Bbb/tool.js", rank=1, fingerprint="same", created="20030101000000")
    projection.project(FRWIKI)
    assert members()["User:Aaa/tool.js"] == ("User:Bbb/tool.js", projection.RELATION_COPY)


def stamps():
    """The raw wiki creation stamp each frwiki entry carries, keyed by title."""
    with db.session_scope() as session:
        rows = session.query(UserScriptDirectoryEntry).filter(UserScriptDirectoryEntry.wiki == FRWIKI).all()
        return {row.title: row.created_at_wiki for row in rows}


def test_the_entry_carries_the_date_the_wiki_reported():
    page("User:Aaa/tool.js", rank=0, created="20090412183000")
    projection.project(FRWIKI)
    assert stamps() == {"User:Aaa/tool.js": "20090412183000"}


def test_an_undated_page_stores_nothing_rather_than_the_ordering_stand_in():
    """The sort key is a fiction for ordering. Publishing it would invent a creation date."""
    page("User:Aaa/tool.js", rank=7)
    projection.project(FRWIKI)
    stored = stamps()["User:Aaa/tool.js"]
    assert stored == ""
    assert stored != projection._sort_key(7)


def test_the_date_travels_from_the_original_not_from_the_copy_that_files_it():
    """A duplicate group publishes one entry: the original's, and so the original's date."""
    page("User:Zed/tool.js", rank=0, fingerprint="same", created="20140101000000")
    page("User:Aaa/tool.js", rank=1, fingerprint="same", created="20090101000000")
    projection.project(FRWIKI)
    assert stamps() == {"User:Aaa/tool.js": "20090101000000"}


def edit_stamps():
    """The raw wiki last-edit stamp each frwiki entry carries, keyed by title."""
    with db.session_scope() as session:
        rows = session.query(UserScriptDirectoryEntry).filter(UserScriptDirectoryEntry.wiki == FRWIKI).all()
        return {row.title: row.touched_at_wiki for row in rows}


def test_the_entry_carries_the_last_edit_the_wiki_reported():
    page("User:Aaa/tool.js", rank=0, touched="20251104071200")
    projection.project(FRWIKI)
    assert edit_stamps() == {"User:Aaa/tool.js": "20251104071200"}


def test_an_unedited_page_carries_no_stand_in_for_its_last_edit():
    """Nothing orders by this one, so there is no fiction to leak into it."""
    page("User:Aaa/tool.js", rank=7)
    projection.project(FRWIKI)
    assert edit_stamps() == {"User:Aaa/tool.js": ""}


def test_the_last_edit_is_the_originals_not_the_newest_across_the_group():
    """An entry stands for one script. Somebody editing a near-copy last night
    says nothing about whether the script itself moved.
    """
    page("User:Zed/tool.js", rank=0, fingerprint="same", created="20140101000000", touched="20260801000000")
    page("User:Aaa/tool.js", rank=1, fingerprint="same", created="20090101000000", touched="20180101000000")
    projection.project(FRWIKI)
    assert edit_stamps() == {"User:Aaa/tool.js": "20180101000000"}


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
        "repaired": 0,
        "originals": 0,
        "active": 0,
        "archive": 0,
    }
    assert entries() == []


def test_every_directory_row_carries_the_census_identity_of_the_page_it_is_about():
    page("User:Zed/tool.js", rank=0, fingerprint="same")
    page("User:Aaa/tool.js", rank=1, fingerprint="same")
    projection.project(FRWIKI)
    with db.session_scope() as session:
        ids = dict(session.query(UserScriptPage.title, UserScriptPage.id))
        entry = session.query(UserScriptDirectoryEntry).one()
        rows = {
            row.title: (row.script_id, row.origin_id) for row in session.query(UserScriptDirectoryMember).all()
        }
    assert entry.script_id == ids["User:Zed/tool.js"]
    # The member carries both ends of the edge: which page it is, and which
    # script it folded onto. Either alone leaves the relation half-stated.
    assert rows == {
        "User:Zed/tool.js": (ids["User:Zed/tool.js"], ids["User:Zed/tool.js"]),
        "User:Aaa/tool.js": (ids["User:Aaa/tool.js"], ids["User:Zed/tool.js"]),
    }


def test_a_rebuild_renumbers_the_rows_but_not_the_scripts():
    # The whole reason the identity is carried rather than read off the row: the
    # projection deletes and re-inserts, so a row id means only what it meant
    # during the run that wrote it. Here the first script is tombstoned, the
    # second one does not change at all, and its row id moves anyway.
    page("User:Aaa/first.js", rank=0)
    page("User:Bbb/second.js", rank=1)
    projection.project(FRWIKI)
    with db.session_scope() as session:
        before = {row.title: (row.id, row.script_id) for row in session.query(UserScriptDirectoryEntry).all()}
    with db.session_scope() as session:
        session.query(UserScriptPage).filter(UserScriptPage.title == "User:Aaa/first.js").one().deleted_at = utcnow()
    projection.project(FRWIKI)
    with db.session_scope() as session:
        after = session.query(UserScriptDirectoryEntry).one()
    row_id, script_id = before["User:Bbb/second.js"]
    assert after.id != row_id
    assert after.script_id == script_id


def test_a_deleted_page_leaves_no_identity_behind_to_point_at():
    # `page_ids` reads live pages only. A tombstoned page cannot be an original
    # and must not lend its id to anything the next projection writes.
    page("User:Aaa/tool.js", rank=0, deleted=True)
    projection.project(FRWIKI)
    with db.session_scope() as session:
        assert session.query(UserScriptDirectoryEntry).count() == 0


def demand_for(wiki=FRWIKI):
    """The demand map as the projection reads it, after the same repair pass."""
    with db.session_scope() as session:
        sweep.resolve_pending(session, wiki)
        return projection.demand(session, wiki)


def test_a_load_naming_a_page_nobody_holds_is_not_counted_at_all():
    # Under title matching this filed a key nobody could ever look up: the
    # collapse only ever asks about candidates, so demand for a title with no
    # census row sat in the map forever, unread. Counting by identity means the
    # key cannot be created in the first place.
    page("User:Aaa/tool.js")
    loads("User:Bbb/common.js", "User:Nobody/never-swept.js")
    assert demand_for() == {}


def test_a_load_that_names_no_wiki_means_the_one_it_was_written_on():
    # The stored shorthand for a same-wiki load. It resolves to a page like any
    # other, and forgetting that would silently drop every local edge.
    page("User:Aaa/tool.js")
    page("User:Bbb/common.js")
    loads("User:Bbb/common.js", "User:Aaa/tool.js", target_wiki="")
    assert demand_for() == {"User:Aaa/tool.js": {"Bbb"}}


def test_a_retired_page_stops_collecting_demand():
    page("User:Aaa/tool.js", deleted=True)
    loads("User:Bbb/common.js", "User:Aaa/tool.js")
    assert demand_for() == {}


def test_a_page_loading_itself_is_not_demand_for_itself():
    page("User:Aaa/tool.js")
    loads("User:Aaa/tool.js", "User:Aaa/tool.js")
    assert demand_for() == {}


def test_the_repair_pass_writes_nothing_once_the_edges_carry_an_identity():
    # The docstring's claim, pinned: repair is what makes the reader safe to run
    # in any order, and it has to be free on a corpus that is already healthy.
    page("User:Aaa/tool.js")
    loads("User:Bbb/common.js", "User:Aaa/tool.js")
    assert projection.project(FRWIKI)["repaired"] == 1
    assert projection.project(FRWIKI)["repaired"] == 0


def test_a_load_pointing_outside_the_census_never_becomes_repair_work():
    # The reason this is a join and not a scan for nulls: an unresolvable row
    # must not be rewritten, or counted, or looked at again next run.
    page("User:Aaa/tool.js")
    loads("User:Bbb/common.js", "User:Ccc/elsewhere.js")
    assert projection.project(FRWIKI)["repaired"] == 0
    assert projection.project(FRWIKI)["repaired"] == 0


def test_the_corpus_is_read_without_its_bodies():
    # What made this job unaffordable on enwiki. `Candidate` carries a
    # fingerprint and a sketch, both distilled from the body at census time, so
    # a projection that also drags the bodies along is paying tens of thousands
    # of script sources to read titles off them -- and paying it in a container
    # that kills without a traceback when it runs out. Asserted as the shape of
    # the query, because the memory is only ever observable as a dead pod.
    page("User:Aaa/tool.js", body="var a = 1;")
    statements = []
    listener = lambda conn, cursor, statement, *rest: statements.append(statement)  # noqa: E731, ARG005
    event.listen(db.engine(), "before_cursor_execute", listener)
    try:
        with db.session_scope() as session:
            found = projection.candidates(session, FRWIKI)
    finally:
        event.remove(db.engine(), "before_cursor_execute", listener)

    assert [candidate.title for candidate in found] == ["User:Aaa/tool.js"]
    assert not [statement for statement in statements if "user_script_pages.body" in statement]


def test_no_connection_is_held_while_the_corpus_is_folded():
    # The collapse is pure Python and, on a wiki this size, minutes of it. A
    # connection left open and silent through that is one the server closes --
    # which it did, and the run then died on the first query of the write with
    # the whole fold already spent. So the fold happens between transactions,
    # and this counts checkouts to say so.
    page("User:Aaa/tool.js")
    page("User:Bbb/tool.js")
    held = []

    def checkout(*_):
        held.append(1)

    def checkin(*_):
        held.pop()

    real_collapse = directory.collapse
    during = []

    def watched(*args, **kwargs):
        during.append(len(held))
        return real_collapse(*args, **kwargs)

    event.listen(db.engine(), "checkout", checkout)
    event.listen(db.engine(), "checkin", checkin)
    try:
        with mock.patch.object(directory, "collapse", watched):
            summary = projection.project(FRWIKI)
    finally:
        event.remove(db.engine(), "checkout", checkout)
        event.remove(db.engine(), "checkin", checkin)

    assert during == [0]
    # Released, and still a whole projection: the phases must not cost the result.
    assert summary["originals"] == 2
