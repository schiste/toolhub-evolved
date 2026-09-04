# SPDX-License-Identifier: GPL-3.0-or-later
"""Telling a tool apart from a page that merely lives in a tool's namespace.

The cases below are the real page names behind the four kinds, taken from the
3,942 pages the inference lane declined on 2026-09-04, with the counts that
made each rule worth having. What is tested is the direction of every doubt:
a page is called a tool unless something says otherwise, because the cost of a
wrong "component" is a maintainer whose checklist disappeared.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import tool_shape  # noqa: E402


def test_a_page_nobody_asked_about_is_a_tool():
    """No evidence is not evidence of absence, and the default has to be safe."""
    assert tool_shape.classify("User:Anomie/linkclassifier.js") == tool_shape.SHAPE_STANDALONE


def test_a_page_the_model_described_is_a_tool():
    """`declined=False` covers both "not asked" and "asked, and answered"."""
    assert tool_shape.classify("User:Anomie/linkclassifier.js", declined=False) == tool_shape.SHAPE_STANDALONE


def test_settings_pages_need_no_model_verdict():
    """571 declined pages are these, and the name settles it on every wiki.

    Checked without `declined` on purpose: a settings page is a settings page
    whether or not the lane has reached it yet.
    """
    for title in (
        "User:Someone/twinkleoptions.js",
        "User:Someone/huggle.yaml.js",
        "User:Someone/EditCounterOptIn.js",
        "User:Nadzik/JWB-settings.json",
    ):
        assert tool_shape.classify(title) == tool_shape.SHAPE_SETTINGS, title


def test_spelling_differences_in_a_filename_do_not_matter():
    """The same page is `EditCounterOptIn.js` on one wiki and lower case on the next."""
    assert tool_shape.classify("User:A/editcounteroptin.js") == tool_shape.SHAPE_SETTINGS
    assert tool_shape.classify("User:A/EDITCOUNTEROPTIN.JS") == tool_shape.SHAPE_SETTINGS


def test_a_vendored_library_needs_no_model_verdict():
    """`morebits.js` was declined on 103 of 103 pages: it is Twinkle's, copied."""
    for title in (
        "User:AhmadSherif/morebits.js",
        "User:Xinbenlv/ethers-5.7.2.umd.js",
        "User:Vlsergey/app.bundle.js",
        "User:Salvatore Ingala/lib/qx.js",
    ):
        assert tool_shape.classify(title) == tool_shape.SHAPE_LIBRARY, title


def test_a_skin_file_is_configuration_only_once_the_model_has_declined_it():
    """15% of `monobook.js` pages held a real script, so the name cannot decide.

    This is the rule that stops the largest single family -- 2,535 pages -- from
    being reclassified wholesale on the strength of its filename.
    """
    assert tool_shape.classify("User:DerHexer/monobook.js") == tool_shape.SHAPE_STANDALONE
    assert tool_shape.classify("User:DerHexer/monobook.js", declined=True) == tool_shape.SHAPE_SKIN


def test_an_unremarkable_page_the_model_declined_is_a_component():
    """The 2,388-page long tail: helper modules, data tables and stubs.

    `Lupo/ui.js` says of itself "Used by the upload form rewrite", which is the
    shape of the whole bucket -- a real file that is part of a tool rather than
    being one.
    """
    assert tool_shape.classify("User:Lupo/ui.js", declined=True) == tool_shape.SHAPE_COMPONENT


def test_settings_beat_a_model_verdict_that_would_say_component():
    """Ordered most specific first: the narrowest true statement is the useful one."""
    assert tool_shape.classify("User:A/twinkleoptions.js", declined=True) == tool_shape.SHAPE_SETTINGS


def test_an_empty_title_is_not_a_component():
    """Defensive: a missing title is missing evidence, not evidence of a component."""
    assert tool_shape.classify("") == tool_shape.SHAPE_STANDALONE
    assert tool_shape.classify("", declined=True) == tool_shape.SHAPE_COMPONENT
