"""Which pages are distinct scripts, and which are somebody's instance of one.

The cases are drawn from the frwiki corpus, where the two collapses this module
performs are worth very different amounts. Hashing recovers 436 copies of one
LiveRC shim -- real, but shallow. The filename rule recovers 472 `LiveRCparam.js`
pages that share no two bytes of content, because they are one tool's settings
file filled in 472 times. Nothing but the name connects them, which is why the
guard that stops the name rule from eating real scripts gets the most tests here.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import userscript_directory as directory  # noqa: E402

Candidate = directory.Candidate


def page(owner, name, *, created="20100101000000", fingerprint=""):
    """Build a candidate the way the fetch layer will: title first, parts derived."""
    title = f"User:{owner}/{name}" if name else f"User:{owner}"
    return Candidate(
        title=title,
        owner=owner,
        basename=directory.basename_of(title),
        created=created,
        fingerprint=fingerprint or title,
    )


def crowd(name, owners, *, start=2010):
    """A filename shared by enough owners to trip CROWDED_OWNERS, oldest first."""
    return [page(owner, name, created=f"{start + index}0101000000") for index, owner in enumerate(owners)]


def titles(origins):
    return [origin.original.title for origin in origins]


# --- reading a title apart -------------------------------------------------


def test_the_owner_is_the_segment_below_the_namespace():
    assert directory.owner_of("User:EDUCA33E/LiveRC.js") == "EDUCA33E"


def test_a_page_with_no_subpage_still_has_an_owner():
    assert directory.owner_of("User:Orlodrim") == "Orlodrim"


def test_a_page_outside_user_space_has_no_owner():
    # MediaWiki:Gadget-Popups.js is a target of imports, never a candidate.
    assert directory.owner_of("MediaWiki:Gadget-Popups.js") == ""


def test_a_title_with_no_namespace_has_no_owner():
    assert directory.owner_of("Popups.js") == ""


def test_the_basename_is_everything_below_the_owner():
    assert directory.basename_of("User:Evpok/LiveRCparam.js") == "LiveRCparam.js"


def test_a_deeper_subpage_keeps_its_whole_path_as_the_basename():
    # 288 frwiki pages sit two levels down; monobooks.js/messagerie.js is one
    # person's library, not a filename shared with anybody.
    assert directory.basename_of("User:TheWize/monobooks.js/messagerie.js") == "monobooks.js/messagerie.js"


def test_a_page_with_no_subpage_has_no_basename():
    assert directory.basename_of("User:Orlodrim") == ""


def test_a_title_with_no_namespace_has_no_basename():
    assert directory.basename_of("Popups.js") == ""


# --- ordering --------------------------------------------------------------


def test_the_earliest_page_ranks_first():
    early = page("EDUCA33E", "LiveRC.js", created="20070101000000")
    late = page("Litlok", "LiveRC.js", created="20200101000000")
    assert early.rank < late.rank


def test_pages_created_in_the_same_second_are_ordered_by_title():
    # Bot-created and import-created pages share timestamps; without the
    # tiebreak the directory would name a different original between runs.
    first = page("Aaa", "common.js", created="20170601000000")
    second = page("Bbb", "common.js", created="20170601000000")
    assert first.rank < second.rank


# --- folding exact copies --------------------------------------------------


def test_identical_pages_fold_onto_the_earliest_one():
    pages = [
        page("Litlok", "vector.js", created="20150101000000", fingerprint="shim"),
        page("EDUCA33E", "vector.js", created="20070101000000", fingerprint="shim"),
        page("Zebulon84", "vector.js", created="20180101000000", fingerprint="shim"),
    ]
    origins = directory.collapse(pages, {})
    assert titles(origins) == ["User:EDUCA33E/vector.js"]
    assert origins[0].instances == 2


def test_folded_copies_are_themselves_ordered():
    pages = [
        page("Zebulon84", "vector.js", created="20180101000000", fingerprint="shim"),
        page("Litlok", "vector.js", created="20150101000000", fingerprint="shim"),
        page("EDUCA33E", "vector.js", created="20070101000000", fingerprint="shim"),
    ]
    copies = directory.collapse(pages, {})[0].copies
    assert [copy.owner for copy in copies] == ["Litlok", "Zebulon84"]


def test_pages_with_no_fingerprint_never_merge():
    # 1,045 frwiki pages are empty and 416 more hold nothing but comments. They
    # are the largest identical group on the wiki, and an empty hash matching
    # itself would make them a single wildly popular script.
    blanks = [
        Candidate(
            title=f"User:User{index}/tool{index}.js",
            owner=f"User{index}",
            basename=f"tool{index}.js",
            created="20100101000000",
            fingerprint="",
        )
        for index in range(6)
    ]
    assert len(directory.collapse(blanks, {})) == 6


def test_blank_pages_under_one_crowded_name_still_fold_by_name():
    # The name rule reaches what the hash cannot: six people whose common.js is
    # empty are six empty slots, not six scripts. This is why the fetch layer
    # can offer the whole corpus without pre-filtering it.
    blanks = [
        Candidate(
            title=f"User:User{index}/common.js",
            owner=f"User{index}",
            basename="common.js",
            created=f"{2010 + index}0101000000",
            fingerprint="",
        )
        for index in range(6)
    ]
    assert titles(directory.collapse(blanks, {})) == ["User:User0/common.js"]


def test_different_content_stays_separate():
    pages = [
        page("Orlodrim", "portail-eval.js", fingerprint="a"),
        page("Lgd", "refErrors.js", fingerprint="b"),
    ]
    assert len(directory.collapse(pages, {})) == 2


# --- folding crowded filenames ---------------------------------------------


def test_a_filename_shared_by_many_owners_folds_onto_the_first():
    # LiveRCparam.js: 472 owners, no two files alike, all of them settings for
    # one tool. Only the name connects them.
    pages = crowd("LiveRCparam.js", ["EDUCA33E", "Evpok", "Litlok", "Zebulon84", "Jules", "Od1n"])
    origins = directory.collapse(pages, {})
    assert titles(origins) == ["User:EDUCA33E/LiveRCparam.js"]
    assert origins[0].instances == 5


def test_a_filename_shared_by_a_few_owners_is_left_alone():
    pages = crowd("verifHomon.js", ["Orlodrim", "Lgd", "Leag"])
    assert len(directory.collapse(pages, {})) == 3


def test_one_persons_repeated_filename_is_not_a_crowd():
    # Four skin slots plus two libraries under one name is one person's habit.
    pages = [
        Candidate(
            title=f"User:Od1n/sub{index}/tools.js",
            owner="Od1n",
            basename="tools.js",
            created=f"{2010 + index}0101000000",
            fingerprint=f"body{index}",
        )
        for index in range(6)
    ]
    assert len(directory.collapse(pages, {})) == 6


def test_pages_without_a_basename_are_never_folded_together():
    pages = [page(f"User{index}", "", created=f"{2010 + index}0101000000") for index in range(6)]
    assert len(directory.collapse(pages, {})) == 6


def test_a_page_other_people_load_keeps_its_identity_under_a_crowded_name():
    # This is the guard that makes CROWDED_OWNERS = 5 safe. Without it a real
    # script would disappear into somebody else's settings file.
    pages = crowd("common.js", ["Aaa", "Bbb", "Ccc", "Ddd", "Eee", "Orlodrim"])
    demand = {"User:Orlodrim/common.js": {"User:X", "User:Y", "User:Z"}}
    origins = directory.collapse(pages, demand)
    assert "User:Orlodrim/common.js" in titles(origins)


def test_a_page_barely_loaded_still_folds():
    pages = crowd("common.js", ["Aaa", "Bbb", "Ccc", "Ddd", "Eee", "Orlodrim"])
    demand = {"User:Orlodrim/common.js": {"User:X"}}
    assert titles(directory.collapse(pages, demand)) == ["User:Aaa/common.js"]


def test_demand_for_a_copy_protects_the_page_that_absorbed_it():
    # Exact copies fold first, so by the time the name rule runs, a group's
    # demand is spread across pages the group no longer lists separately.
    pages = crowd("common.js", ["Aaa", "Bbb", "Ccc", "Ddd", "Eee"])
    pages += [
        page("Orlodrim", "common.js", created="20200101000000", fingerprint="tool"),
        page("Litlok", "common.js", created="20210101000000", fingerprint="tool"),
    ]
    demand = {"User:Litlok/common.js": {"User:X", "User:Y", "User:Z"}}
    assert "User:Orlodrim/common.js" in titles(directory.collapse(pages, demand))


def test_the_first_page_under_a_crowded_name_is_kept_even_with_no_demand():
    pages = crowd("LiveRCparam.js", ["EDUCA33E", "Bbb", "Ccc", "Ddd", "Eee"])
    assert titles(directory.collapse(pages, {})) == ["User:EDUCA33E/LiveRCparam.js"]


def test_two_crowded_names_do_not_interfere():
    pages = crowd("LiveRCparam.js", ["EDUCA33E", "Bbb", "Ccc", "Ddd", "Eee"])
    pages += crowd("AdvancedContribs.js", ["Maloq", "Fff", "Ggg", "Hhh", "Iii"], start=2012)
    assert sorted(titles(directory.collapse(pages, {}))) == [
        "User:EDUCA33E/LiveRCparam.js",
        "User:Maloq/AdvancedContribs.js",
    ]


def test_the_directory_is_returned_oldest_first():
    pages = [
        page("Litlok", "b.js", created="20200101000000"),
        page("EDUCA33E", "a.js", created="20070101000000"),
    ]
    assert titles(directory.collapse(pages, {})) == ["User:EDUCA33E/a.js", "User:Litlok/b.js"]


# --- ranking ---------------------------------------------------------------


def test_scripts_are_ranked_by_how_many_distinct_sources_load_them():
    pages = [page("Lupin", "popups.js"), page("Orlodrim", "portail-eval.js")]
    demand = {
        "User:Lupin/popups.js": {f"User:U{index}" for index in range(4)},
        "User:Orlodrim/portail-eval.js": {"User:A", "User:B"},
    }
    ranked = directory.rank_by_demand(directory.collapse(pages, demand), demand)
    assert [(origin.original.owner, score) for origin, score in ranked] == [("Lupin", 4), ("Orlodrim", 2)]


def test_demand_for_an_instance_counts_for_the_script_it_belongs_to():
    # Somebody who copied xpatrol and is loaded by four people is evidence
    # about xpatrol, not about a second tool.
    pages = [
        page("Orlodrim", "xpatrol.js", created="20100101000000", fingerprint="x"),
        page("Litlok", "xpatrol.js", created="20200101000000", fingerprint="x"),
    ]
    demand = {"User:Litlok/xpatrol.js": {"User:A", "User:B"}, "User:Orlodrim/xpatrol.js": {"User:A", "User:C"}}
    ranked = directory.rank_by_demand(directory.collapse(pages, demand), demand)
    assert ranked[0][1] == 3  # A counted once, not twice


def test_a_script_nobody_loads_scores_zero():
    # 655 of frwiki's 1,233 originals are in this state. They are still scripts.
    origins = directory.collapse([page("Orlodrim", "private.js")], {})
    assert directory.rank_by_demand(origins, {})[0][1] == 0


def test_scripts_with_equal_demand_are_ordered_oldest_first():
    pages = [
        page("Litlok", "b.js", created="20200101000000"),
        page("EDUCA33E", "a.js", created="20070101000000"),
    ]
    ranked = directory.rank_by_demand(directory.collapse(pages, {}), {})
    assert [origin.original.owner for origin, _ in ranked] == ["EDUCA33E", "Litlok"]


def test_an_origin_lists_the_original_first_among_its_pages():
    pages = [
        page("Litlok", "vector.js", created="20200101000000", fingerprint="shim"),
        page("EDUCA33E", "vector.js", created="20070101000000", fingerprint="shim"),
    ]
    origin = directory.collapse(pages, {})[0]
    assert origin.pages[0] is origin.original
    assert len(origin.pages) == 2


def test_a_script_nobody_loads_is_archived_rather_than_dropped():
    origin = directory.collapse([page("Orlodrim", "private.js")], {})[0]
    assert directory.tier_of(origin, {}) == directory.TIER_ARCHIVE


def test_one_importer_is_enough_to_leave_the_archive():
    # The boundary is deliberately one, not three: INDEPENDENT_DEMAND decides
    # what survives a crowded filename, which is a different question.
    demand = {"User:Orlodrim/portail-eval.js": {"Litlok"}}
    origin = directory.collapse([page("Orlodrim", "portail-eval.js")], demand)[0]
    assert directory.tier_of(origin, demand) == directory.TIER_ACTIVE


def test_demand_on_a_copy_keeps_the_original_out_of_the_archive():
    # Nobody loads EDUCA33E's page; they load Litlok's byte-identical copy of it.
    pages = [
        page("EDUCA33E", "LiveRC.js", created="20070101000000", fingerprint="shim"),
        page("Litlok", "LiveRC.js", created="20200101000000", fingerprint="shim"),
    ]
    demand = {"User:Litlok/LiveRC.js": {"Gz260"}}
    origin = directory.collapse(pages, demand)[0]
    assert origin.original.owner == "EDUCA33E"
    assert directory.tier_of(origin, demand) == directory.TIER_ACTIVE


def test_both_tiers_come_back_ordered_the_way_each_is_read():
    pages = [
        page("Orlodrim", "portail-eval.js", created="20100101000000"),
        page("Arkanosis", "xpatrol.js", created="20110101000000"),
        page("DCLXVI", "livepreview.js", created="20050101000000"),
        page("Emc2", "strings-it.js", created="20060101000000"),
    ]
    demand = {
        "User:Orlodrim/portail-eval.js": {"a", "b"},
        "User:Arkanosis/xpatrol.js": {"c"},
    }
    tiers = directory.by_tier(directory.collapse(pages, demand), demand)
    assert [o.original.owner for o in tiers[directory.TIER_ACTIVE]] == ["Orlodrim", "Arkanosis"]
    assert [o.original.owner for o in tiers[directory.TIER_ARCHIVE]] == ["DCLXVI", "Emc2"]


def test_an_empty_corpus_still_reports_both_tiers():
    assert directory.by_tier([], {}) == {directory.TIER_ACTIVE: [], directory.TIER_ARCHIVE: []}
