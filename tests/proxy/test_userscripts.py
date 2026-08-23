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


def test_a_wiki_s_own_namespace_name_folds_once_it_has_been_read():
    # The built-ins cover the two wikis censused first and nothing else, so
    # dewiki's own name has to be handed in. Without it the title is stored as
    # a string no page answers to, and every load edge pointing at it resolves
    # to nothing.
    assert userscripts.canonical_title("Benutzer:PerfektesChaos/js/lint.js") == "Benutzer:PerfektesChaos/js/lint.js"
    folded = userscripts.canonical_title("Benutzer:PerfektesChaos/js/lint.js", spellings=("Benutzer", "Benutzerin"))
    assert folded == "User:PerfektesChaos/js/lint.js"


def test_a_wiki_s_names_widen_the_fold_and_never_narrow_it():
    # A wiki that names only its own spellings must still fold the built-ins,
    # so that learning a namespace name can never un-fold a title already
    # stored under the old rule.
    assert userscripts.canonical_title("User:Foo/x.js", spellings=("Benutzer",)) == "User:Foo/x.js"
    assert userscripts.canonical_title("Utilisateur:Foo/x.js", spellings=("Benutzer",)) == "User:Foo/x.js"


def test_a_namespace_name_is_matched_as_text_and_not_as_a_pattern():
    # These arrive from a remote wiki's siteinfo. A name carrying regex
    # punctuation must match itself and nothing else -- and must not blow up
    # the census that asked for it.
    assert userscripts.canonical_title("A.C:Foo/x.js", spellings=("A.C",)) == "User:Foo/x.js"
    assert userscripts.canonical_title("AXC:Foo/x.js", spellings=("A.C",)) == "AXC:Foo/x.js"


def test_a_cross_wiki_load_is_folded_by_the_target_s_names_not_the_loader_s():
    # `Benutzer:` means namespace 2 on dewiki and means nothing at all on
    # frwiki, so the spellings that decide this fold are the host's.
    def prefixes(wiki):
        return userscripts.WikiPrefixes(namespaces=("Benutzer",) if wiki == "de.wikipedia.org" else ())

    body = "mw.loader.load('//de.wikipedia.org/w/index.php?title=Benutzer:PerfektesChaos/js.js&action=raw&ctype=text/javascript');"
    (found,) = userscripts.script_imports(body, wiki=FRWIKI, prefixes=prefixes)
    assert (found.wiki, found.title) == ("de.wikipedia.org", "User:PerfektesChaos/js.js")


def _interwiki(**hosts):
    """A prefixes lookup where every wiki knows the same map and dewiki's names."""

    def prefixes(wiki):
        return userscripts.WikiPrefixes(
            namespaces=("Benutzer",) if wiki == "de.wikipedia.org" else (),
            interwiki=hosts,
        )

    return prefixes


def test_a_load_naming_an_interwiki_prefix_lands_on_the_wiki_it_names():
    # `importScript('en:User:Lupin/popups.js')` used to be stored as a page
    # titled `en:User:Lupin/popups.js` on the loading wiki. No such page exists
    # anywhere, so the edge resolved to nothing on both ends.
    body = "importScript('en:User:Lupin/popups.js');"
    (found,) = userscripts.script_imports(body, wiki=FRWIKI, prefixes=_interwiki(en="en.wikipedia.org"))
    assert (found.wiki, found.title) == ("en.wikipedia.org", "User:Lupin/popups.js")


def test_the_title_left_after_the_peel_is_folded_by_the_target_s_names():
    # Two decisions, and the second has to happen after the first: `Benutzer:`
    # only means namespace 2 once the prefix has said which wiki we are on.
    body = "importScript('de:Benutzer:PerfektesChaos/js.js');"
    (found,) = userscripts.script_imports(body, wiki=FRWIKI, prefixes=_interwiki(de="de.wikipedia.org"))
    assert (found.wiki, found.title) == ("de.wikipedia.org", "User:PerfektesChaos/js.js")


def test_a_nested_prefix_is_followed_to_the_wiki_at_the_end_of_it():
    # `:w:en:` appears in the corpus: a leading colon, then a prefix that lands
    # back on the same family, then the language.
    body = "importScript(':W:en:User:Lupin/popups.js');"
    prefixes = _interwiki(w="www.wikipedia.org", en="en.wikipedia.org")
    (found,) = userscripts.script_imports(body, wiki=FRWIKI, prefixes=prefixes)
    assert (found.wiki, found.title) == ("en.wikipedia.org", "User:Lupin/popups.js")


def test_a_prefix_the_wiki_does_not_know_stays_part_of_the_title():
    # `Wikipedia:` is a namespace, not an interwiki, and the interwiki map it
    # is filtered out of is what makes this true. Peeling it would move
    # thousands of project-namespace pages to a wiki they were never on.
    body = "importScript('Wikipedia:Foo/bar.js');"
    (found,) = userscripts.script_imports(body, wiki=FRWIKI, prefixes=_interwiki(en="en.wikipedia.org"))
    assert (found.wiki, found.title) == (FRWIKI, "Wikipedia:Foo/bar.js")


def test_a_prefix_with_nothing_after_it_names_no_page():
    body = "importScript('en:');"
    assert userscripts.script_imports(body, wiki=FRWIKI, prefixes=_interwiki(en="en.wikipedia.org")) == ()


def test_a_prefix_chain_that_never_ends_is_bounded():
    # A wiki whose map points a prefix back at itself is a loop the corpus can
    # hand us for free; the bound is what makes the peel terminate on data.
    body = "importScript('" + "x:" * 40 + "User:Foo/bar.js');"
    (found,) = userscripts.script_imports(body, wiki=FRWIKI, prefixes=_interwiki(x=FRWIKI))
    assert found.wiki == FRWIKI
    assert found.title.startswith("x:")


def test_a_fingerprint_does_not_move_when_a_wiki_s_names_are_learned():
    # Fingerprints are stored and compared against each other. Widening the
    # rule that produces them would rewrite every hash already written and make
    # each page look like a fork of itself until the whole corpus was reswept.
    def prefixes(_wiki):
        return userscripts.WikiPrefixes(namespaces=("Benutzer",))

    body = "// [[Benutzer:PerfektesChaos]]\nimportScript('Benutzer:X/y.js');"
    plain = userscripts.analyze("Benutzer:X/y.js", body, wiki="de.wikipedia.org")
    aware = userscripts.analyze("Benutzer:X/y.js", body, wiki="de.wikipedia.org", prefixes=prefixes)
    assert aware.title == "User:X/y.js"
    assert aware.fingerprint == plain.fingerprint


def test_underscores_and_runs_of_whitespace_are_one_title():
    assert userscripts.canonical_title("User:Le_Galéanthrope/Monobook.js") == "User:Le Galéanthrope/Monobook.js"
    assert userscripts.canonical_title("  User:Foo   Bar/x.js  ") == "User:Foo Bar/x.js"


def test_an_invisible_formatting_mark_is_not_a_second_spelling():
    # MySQL's collation ignores these, so a title that only differs by one is
    # already the same row -- Python has to agree or the unique key rejects it.
    assert userscripts.canonical_title("User:Hoo man/tagger.js\u200e") == "User:Hoo man/tagger.js"
    assert userscripts.canonical_title("User:Foo/\ufeffx.js") == "User:Foo/x.js"


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


def test_a_load_repeated_with_an_invisible_mark_counts_once():
    # A Meta global.js does exactly this: the same load pasted twice, once with
    # a left-to-right mark carried over from a copied link.
    body = (
        "mw.loader.load('//meta.wikimedia.org/w/index.php?title=User:Hoo_man/tagger.js\u200e"
        "&action=raw&ctype=text/javascript');\n"
        "mw.loader.load('//meta.wikimedia.org/w/index.php?title=User:Hoo_man/tagger.js"
        "&action=raw&ctype=text/javascript');"
    )
    found = userscripts.script_imports(body, wiki="meta.wikimedia.org")
    assert len(found) == 1
    assert found[0].title == "User:Hoo man/tagger.js"
    assert "\u200e" not in found[0].url


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


def test_a_relative_index_php_url_names_a_page_on_the_wiki_that_wrote_it():
    # 47 of frwiki's distinct load targets were stored as the whole query
    # string, because a URL with no host was not recognized as a URL at all.
    body = "importScript('/w/index.php?title=MediaWiki:Common.js/edit.js&action=raw&ctype=text/javascript');"
    (found,) = userscripts.script_imports(body, wiki=FRWIKI)
    assert (found.wiki, found.title) == (FRWIKI, "MediaWiki:Common.js/edit.js")


def test_a_relative_pretty_path_names_a_page_too():
    (found,) = userscripts.script_imports("importScript('/wiki/User:Foo/bar.js');", wiki=FRWIKI)
    assert (found.wiki, found.title) == (FRWIKI, "User:Foo/bar.js")


def test_a_target_written_as_a_wikilink_is_still_a_title():
    (found,) = userscripts.script_imports("importScript('[[Utilisateur:Dr Brains/VerifEval.js]]');", wiki=FRWIKI)
    assert found.title == "User:Dr Brains/VerifEval.js"


def test_a_percent_encoded_target_names_the_page_it_decodes_to():
    # Copied out of a URL. The page exists; the spelling is what did not.
    body = "importScript('User:%C3%9Ejarkur/Highlight recently added text.js');"
    (found,) = userscripts.script_imports(body, wiki=FRWIKI)
    assert found.title == "User:Þjarkur/Highlight recently added text.js"


def test_a_title_with_a_bare_percent_is_left_alone():
    # `unquote` only consumes a valid escape, and a real title may hold a `%`.
    (found,) = userscripts.script_imports("importScript('User:Foo/100% sure.js');", wiki=FRWIKI)
    assert found.title == "User:Foo/100% sure.js"


def test_an_absolute_cross_wiki_url_is_unaffected_by_the_relative_case():
    body = "importScript('https://en.wikipedia.org/w/index.php?title=User:Lupin/popups.js&action=raw');"
    (found,) = userscripts.script_imports(body, wiki=FRWIKI)
    assert (found.wiki, found.title) == ("en.wikipedia.org", "User:Lupin/popups.js")


def test_a_url_that_names_no_page_stays_an_opaque_url():
    body = "mw.loader.load('https://tools.wmflabs.org/somewhere/bundle.js');"
    (found,) = userscripts.script_imports(body, wiki=FRWIKI)
    assert (found.wiki, found.title) == ("", "")
    assert found.url.endswith("bundle.js")


def test_a_relative_url_that_names_no_page_is_not_an_edge():
    # A query string with an empty `title=` is a leftover, not a target. Stored
    # as a title it becomes demand for a page nobody can ever create.
    assert userscripts.script_imports("importScript('/w/index.php?title=');", wiki=FRWIKI) == ()


def test_a_relative_path_that_is_not_a_wiki_path_is_not_an_edge():
    assert userscripts.script_imports("importScript('/static/js/thing.js');", wiki=FRWIKI) == ()


def test_an_argument_with_a_scheme_this_census_cannot_read_is_not_a_title():
    # Really in the corpus, on a page whose author was working locally. It is a
    # URL, so it is not a page title; it is not HTTP, so there is nothing here
    # to fetch or point at either.
    body = "importScript('ftp://localhost/copyvio version-finale.js?');"
    assert userscripts.script_imports(body, wiki=FRWIKI) == ()


def test_mw_loader_load_of_a_gadget_names_a_module_not_a_page():
    # 450 of the census's 676 module loads say `ext.gadget.*`: a user script
    # asking for a gadget by name. Stored as a title it was demand for
    # `Ext.gadget.HotCat`, a page nobody will ever create.
    (found,) = userscripts.script_imports("mw.loader.load('ext.gadget.HotCat');", wiki=FRWIKI)
    assert (found.module, found.title, found.url) == ("ext.gadget.HotCat", "", "")
    assert found.wiki == FRWIKI


def test_a_module_load_is_not_capitalized_the_way_a_title_would_be():
    (found,) = userscripts.script_imports("mw.loader.load('mediawiki.util');", wiki=FRWIKI)
    assert found.module == "mediawiki.util"


def test_a_page_loading_two_modules_keeps_both():
    body = "mw.loader.load('ext.gadget.A');\nmw.loader.load('ext.gadget.B');"
    assert [found.module for found in userscripts.script_imports(body, wiki=FRWIKI)] == [
        "ext.gadget.A",
        "ext.gadget.B",
    ]


def test_a_module_load_written_twice_still_counts_once():
    body = "mw.loader.load('ext.gadget.A');\nmw.loader.load('ext.gadget.A');"
    assert len(userscripts.script_imports(body, wiki=FRWIKI)) == 1


def test_only_mw_loader_load_takes_a_module():
    # Every other verb is handed a page title or a URL, so a dotted name given
    # to one of them is still a title -- an odd one, but not a module.
    (found,) = userscripts.script_imports("importScript('ext.gadget.HotCat');", wiki=FRWIKI)
    assert found.module == ""
    assert found.title == "Ext.gadget.HotCat"


def test_a_relative_url_given_to_mw_loader_load_is_still_a_url():
    # MediaWiki's own test accepts a single leading slash, so this is not the
    # module branch: it is the page the URL names.
    body = "mw.loader.load('/w/index.php?title=User:Foo/bar.js&action=raw');"
    (found,) = userscripts.script_imports(body, wiki=FRWIKI)
    assert (found.title, found.module) == ("User:Foo/bar.js", "")
