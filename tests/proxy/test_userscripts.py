"""What a user-space JavaScript page is, and what it loads.

Every case here is a shape that actually occurs in a full pass over frwiki's
9,919 user-space JavaScript pages, and most of them are cases where the obvious
implementation gets the census wrong: a commented-out import counted as demand,
one script hashed as three because its copies carry different credit comments,
one page split in two because the API answered with a different spelling of the
user namespace than the database stored.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import userscripts  # noqa: E402

FRWIKI = "fr.wikipedia.org"


# --- comments -------------------------------------------------------------


def test_block_and_line_comments_are_blanked_not_deleted():
    body = "var a = 1; /* keep\nstructure */ var b = 2;\nvar c = 3; // trailing"
    stripped = userscripts.strip_comments(body)
    assert "keep" not in stripped
    assert "trailing" not in stripped
    assert stripped.count("\n") == body.count("\n")
    assert "var a = 1;" in stripped
    assert "var c = 3;" in stripped


def test_a_url_is_not_mistaken_for_a_line_comment():
    body = "mw.loader.load('https://en.wikipedia.org/w/index.php?title=X&action=raw');"
    assert "en.wikipedia.org" in userscripts.strip_comments(body)


def test_stripping_an_absent_body_is_not_an_error():
    assert userscripts.strip_comments("") == ""


# --- titles ---------------------------------------------------------------


def test_localized_user_namespaces_collapse_onto_one_spelling():
    # MediaWiki gender-normalizes the localized namespace on the way out, so the
    # same page is returned as Utilisatrice: after being stored as Utilisateur:.
    assert userscripts.canonical_title("Utilisateur:Evpok/LiveRCparam.js") == "User:Evpok/LiveRCparam.js"
    assert userscripts.canonical_title("Utilisatrice:Evpok/LiveRCparam.js") == "User:Evpok/LiveRCparam.js"
    assert userscripts.canonical_title("user : Evpok/LiveRCparam.js") == "User:Evpok/LiveRCparam.js"


def test_underscores_and_runs_of_whitespace_are_one_title():
    assert userscripts.canonical_title("User:Le_Galéanthrope/Monobook.js") == "User:Le Galéanthrope/Monobook.js"
    assert userscripts.canonical_title("  User:Foo   Bar/x.js  ") == "User:Foo Bar/x.js"


def test_the_page_name_is_capitalized_but_the_rest_is_left_alone():
    assert userscripts.canonical_title("User:orlodrim/portail-eval.js") == "User:Orlodrim/portail-eval.js"
    assert userscripts.canonical_title("MediaWiki:Gadget-verifHomon.js") == "MediaWiki:Gadget-verifHomon.js"


def test_titles_without_a_namespace_still_normalize():
    assert userscripts.canonical_title("common.js") == "Common.js"


def test_a_namespace_with_no_page_name_is_returned_untouched():
    assert userscripts.canonical_title("MediaWiki:") == "MediaWiki:"


def test_an_absent_title_is_empty_not_an_error():
    assert userscripts.canonical_title("") == ""
    assert userscripts.canonical_title("   ") == ""


# --- fingerprints ---------------------------------------------------------


def test_credit_comments_do_not_split_one_script_into_several():
    # Popups appears on frwiki as three byte-exact groups differing only here.
    a = "// [[:en:User:Lupin/popups.js]]\nimportScript('MediaWiki:Gadget-Popups.js');"
    b = "// Traduction de [[Utilisateur:Leag]]\nimportScript('MediaWiki:Gadget-Popups.js');"
    assert userscripts.fingerprint(a) == userscripts.fingerprint(b)


def test_the_namespace_alias_does_not_split_one_script():
    # portail-eval split into groups of 33 and 24 on frwiki for this reason
    # alone: one set of copies wrote User: and the other wrote Utilisateur:.
    a = "importScript('Utilisateur:Orlodrim/portail-eval.js');"
    b = "importScript('User:Orlodrim/portail-eval.js');"
    assert userscripts.fingerprint(a) == userscripts.fingerprint(b)


def test_surrounding_whitespace_does_not_split_one_script():
    a = "importScript('User:Orlodrim/portail-eval.js');"
    b = "\n   importScript('User:Orlodrim/portail-eval.js');\n\n"
    assert userscripts.fingerprint(a) == userscripts.fingerprint(b)


def test_a_script_wrapped_around_a_long_comment_keeps_its_line_count():
    # Blanking a multi-line comment to one space would join line 1 to line 5
    # and report a five-line script as a two-line stub.
    body = "var a = 1;\n/* a\nlong\nnote */\nvar b = 2;\nvar c = 3;"
    assert userscripts.classify(body) == userscripts.ROLE_SCRIPT


def test_different_load_mechanisms_stay_different_scripts():
    a = "importScript('MediaWiki:Gadget-Popups.js');"
    b = "mw.loader.load('//en.wikipedia.org/w/index.php?title=User:Lupin/popups.js');"
    assert userscripts.fingerprint(a) != userscripts.fingerprint(b)


def test_a_page_with_no_code_has_no_fingerprint():
    # 1,045 frwiki pages are empty; clustering them together would report the
    # largest script on the wiki as the absence of one.
    assert userscripts.fingerprint("") == ""
    assert userscripts.fingerprint("   \n\n  ") == ""
    assert userscripts.fingerprint("/* everything I wrote is a comment */") == ""


# --- roles ----------------------------------------------------------------


def test_an_empty_or_comments_only_page_is_empty():
    assert userscripts.classify("") == userscripts.ROLE_EMPTY
    assert userscripts.classify("// nothing here\n\n") == userscripts.ROLE_EMPTY


def test_a_short_page_with_no_load_is_a_stub():
    assert userscripts.classify("test") == userscripts.ROLE_STUB
    assert userscripts.classify("var tooltipRefHover = true;") == userscripts.ROLE_STUB


def test_a_page_whose_point_is_the_load_is_a_shim():
    assert userscripts.classify("importScript('User:EDUCA33E/LiveRC.js');") == userscripts.ROLE_SHIM
    assert userscripts.classify("obtenir('LiveRC');", wiki=FRWIKI) == userscripts.ROLE_SHIM


def test_configuration_around_a_load_is_still_a_shim():
    body = "var a = 1;\nvar b = 2;\nvar c = 3;\nimportScript('User:EDUCA33E/LiveRC.js');"
    assert userscripts.classify(body) == userscripts.ROLE_SHIM


def test_a_real_script_that_imports_a_library_is_not_a_shim():
    body = "importScript('User:Leag/lib.js');\n" + "\n".join(f"var v{n} = {n};" for n in range(6))
    assert userscripts.classify(body) == userscripts.ROLE_SCRIPT


def test_a_page_with_real_code_and_no_load_is_a_script():
    body = "function f() {\n  return 1;\n}\nf();"
    assert userscripts.classify(body) == userscripts.ROLE_SCRIPT


def test_a_local_verb_is_only_a_load_on_the_wiki_that_defines_it():
    # obtenir() is defined in frwiki's own MediaWiki:Common.js; elsewhere the
    # same line is an ordinary function call and the page is a stub.
    assert userscripts.classify("obtenir('LiveRC');") == userscripts.ROLE_STUB


# --- imports --------------------------------------------------------------


def test_a_commented_out_import_is_not_demand():
    # 796 of frwiki's 9,112 skin-slot import edges are commented out. Counting
    # them credits a script with users who deliberately switched it off.
    body = "// importScript('User:Stef48/revocation.js');"
    assert userscripts.script_imports(body) == ()


def test_an_ordinary_import_resolves_to_a_canonical_title():
    (found,) = userscripts.script_imports("importScript('Utilisateur:Arkanosis/xpatrol.js');")
    assert found.verb == "importScript"
    assert found.title == "User:Arkanosis/xpatrol.js"
    assert found.url == ""
    assert found.is_stylesheet is False


def test_the_frwiki_local_verb_resolves_to_its_gadget_page():
    (found,) = userscripts.script_imports('obtenir("RenommageCategorie");', wiki=FRWIKI)
    assert found.verb == "obtenir"
    assert found.argument == "RenommageCategorie"
    assert found.title == "MediaWiki:Gadget-RenommageCategorie.js"


def test_an_unknown_local_verb_yields_nothing_rather_than_a_guess():
    assert userscripts.script_imports('obtenir("RenommageCategorie");') == ()


def test_a_global_verb_is_unaffected_by_the_wikis_own_local_verb():
    (found,) = userscripts.script_imports("importScript('User:Foo/x.js');", wiki=FRWIKI)
    assert found.title == "User:Foo/x.js"


def test_a_url_load_names_the_wiki_and_the_page_it_points_at():
    # 1,160 of frwiki's 1,807 URL imports leave frwiki. Left opaque, the census
    # would report a wiki whose users depend on nothing outside it.
    body = "mw.loader.load('//meta.wikimedia.org/w/index.php?title=User:Hedonil/XTools.js&action=raw');"
    (found,) = userscripts.script_imports(body)
    assert found.wiki == "meta.wikimedia.org"
    assert found.title == "User:Hedonil/XTools.js"
    assert found.url.startswith("//meta.wikimedia.org")


def test_a_local_import_is_attributed_to_the_wiki_being_analyzed():
    (found,) = userscripts.script_imports("importScript('User:Foo/x.js');", wiki=FRWIKI)
    assert found.wiki == FRWIKI


def test_the_title_may_arrive_before_the_action_in_the_query():
    # Both orderings occur; parsing by position rather than by key loses one.
    body = "mw.loader.load('//commons.wikimedia.org/w/index.php?action=raw&title=MediaWiki:Gadget-Cat-a-lot.js');"
    (found,) = userscripts.script_imports(body)
    assert found.title == "MediaWiki:Gadget-Cat-a-lot.js"


def test_a_pretty_wiki_path_names_a_page_too():
    (found,) = userscripts.script_imports("importScriptURI('https://fr.wikipedia.org/wiki/User:Orlodrim/x.js');")
    assert (found.wiki, found.title) == ("fr.wikipedia.org", "User:Orlodrim/x.js")


def test_a_percent_encoded_title_is_decoded():
    # frwiki titles carry accents, and a raw-action URL percent-encodes them.
    # Only the first character of the whole title is capitalized, never a
    # subpage -- User:Delhovlyn/démineur.js is the real page.
    body = "mw.loader.load('//fr.wikipedia.org/w/index.php?title=User:Delhovlyn/d%C3%A9mineur.js&action=raw');"
    (found,) = userscripts.script_imports(body)
    assert found.title == "User:Delhovlyn/démineur.js"


def test_a_query_title_is_decoded_once_and_not_twice():
    # parse_qs already decodes; unquoting its output again would turn a title
    # that legitimately contains a percent escape into a different page.
    body = "mw.loader.load('//fr.wikipedia.org/w/index.php?title=User:Foo/a%2541b.js');"
    (found,) = userscripts.script_imports(body)
    assert found.title == "User:Foo/a%41b.js"


def test_a_path_title_is_decoded():
    # urlparse leaves the path encoded, so this branch does need to decode.
    (found,) = userscripts.script_imports("importScriptURI('//fr.wikipedia.org/wiki/User:Foo/d%C3%A9mo.js');")
    assert found.title == "User:Foo/démo.js"


def test_a_module_bundle_url_stays_opaque():
    # load.php names modules, not pages; there is no directory entry to point at.
    body = "mw.loader.load('//fr.wikipedia.org/w/load.php?modules=ext.gadget.LiveRC');"
    (found,) = userscripts.script_imports(body)
    assert found.title == ""
    assert found.url.endswith("LiveRC")


def test_a_plain_file_url_stays_opaque():
    body = "mw.loader.load('//bits.wikimedia.org/skins-1.5/common/edit.js');"
    (found,) = userscripts.script_imports(body)
    assert (found.wiki, found.title) == ("", "")


def test_a_url_with_no_host_names_nothing():
    assert userscripts.wiki_target("https:///w/index.php?title=X") == ("", "")


def test_the_same_page_reached_by_two_verbs_stays_two_edges():
    body = "importScript('User:Foo/x.js');\nmw.loader.load('//fr.wikipedia.org/wiki/User:Foo/x.js');"
    assert len(userscripts.script_imports(body, wiki=FRWIKI)) == 2


def test_a_stylesheet_load_is_marked_as_one():
    (found,) = userscripts.script_imports("importStylesheet('User:Foo/skin.css');")
    assert found.is_stylesheet is True
    assert found.title == "User:Foo/skin.css"


def test_a_jquery_load_is_recognized_at_the_start_of_a_statement():
    # A word-boundary anchor silently misses "$." after a space or semicolon,
    # which lost 24 real edges in the first pass over frwiki.
    body = "$.getScript('//en.wikipedia.org/w/index.php?title=MediaWiki:Gadget-refToolbarBase.js');"
    (found,) = userscripts.script_imports(body)
    assert found.verb == "$.getScript"


def test_a_verb_that_is_a_suffix_of_an_identifier_is_not_a_load():
    assert userscripts.script_imports("myImportScript('User:Foo/x.js');") == ()


def test_the_longer_verb_wins_over_its_own_prefix():
    (found,) = userscripts.script_imports("importScriptURI('https://example.org/x.js');")
    assert found.verb == "importScriptURI"


def test_an_empty_argument_resolves_to_nothing():
    assert userscripts.script_imports("importScript('   ');") == ()


def test_the_same_load_written_twice_counts_once():
    body = "importScript('User:Foo/x.js');\nimportScript('Utilisateur:Foo/x.js');"
    assert len(userscripts.script_imports(body)) == 1


def test_the_same_target_reached_by_two_verbs_stays_two_edges():
    body = "importScript('User:Foo/x.js');\nmw.loader.getScript('User:Foo/x.js');"
    assert len(userscripts.script_imports(body)) == 2


def test_imports_are_returned_in_source_order():
    body = "importScript('User:A/x.js');\nimportScript('User:B/y.js');"
    assert [found.title for found in userscripts.script_imports(body)] == ["User:A/x.js", "User:B/y.js"]


# --- one pass -------------------------------------------------------------


def test_analyze_answers_both_questions_at_once():
    page = userscripts.analyze("Utilisateur:Gribeco/vector.js", "obtenir('LiveRC');", wiki=FRWIKI)
    assert page.title == "User:Gribeco/vector.js"
    assert page.role == userscripts.ROLE_SHIM
    assert page.is_candidate is False
    assert page.fingerprint != ""
    assert [found.title for found in page.imports] == ["MediaWiki:Gadget-LiveRC.js"]


def test_only_a_script_is_a_directory_candidate():
    body = "function portailEval() {\n  return 1;\n}\nportailEval();"
    page = userscripts.analyze("User:Orlodrim/portail-eval.js", body, wiki=FRWIKI)
    assert page.role == userscripts.ROLE_SCRIPT
    assert page.is_candidate is True
