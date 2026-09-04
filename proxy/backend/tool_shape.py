# SPDX-License-Identifier: GPL-3.0-or-later
"""Tell a tool apart from a page that merely lives in a tool's namespace.

The catalogue admits every `User:*/*.js` page the census finds, which is the
right rule for discovery and the wrong one for presentation. Measured across
3,942 pages the inference lane declined to describe on 2026-09-04, the median
body was 1,210 characters and 947 were over 5,000 -- so these are not stubs the
model could not read. They are pages that are not tools: a person's skin file,
a copy of somebody else's library, the saved settings of a tool that lives
elsewhere, a helper module of a script in the next page along.

That mattered because the tool page grades every record against the same nine
toolinfo fields. `User:Someone/vector.js` was being shown as a tool with a
"Listing completeness 2/9" meter and seven things its author ought to fix, when
there is nothing to fix: it is a personal configuration file and was never a
listing. A checklist addressed to nobody is worse than no checklist, because a
reader cannot tell it apart from one addressed to a real maintainer who has
neglected their record.

Deterministic first, and the model only where nothing else can decide. The
naming conventions below are MediaWiki's own and hold across every wiki --
`vector.js` is a skin file on all of them -- so they need no guess. Only the
long tail falls through to `declined`, which is this module's one use of the
inference lane's judgement, and it is used as a signal that a page could not be
described rather than as a description of it.

Nothing here changes what is catalogued, searchable or synchronized. It changes
what the tool page claims about a record, which is why it lives beside the
projection rather than in the census: a rule about presentation should not be
able to drop a page out of the catalogue by accident.
"""

from __future__ import annotations

import re

# What the page is, when it is not a tool. Ordered from most specific to least,
# because a page can satisfy more than one and the reader is better served by
# the narrowest true statement: `twinkleoptions.js` is a settings page before it
# is an unclassifiable one.
SHAPE_STANDALONE = ""
SHAPE_SKIN = "skin-config"
SHAPE_SETTINGS = "tool-settings"
SHAPE_LIBRARY = "vendored-library"
SHAPE_COMPONENT = "component"

# MediaWiki loads exactly these per-skin, plus `common.js` for every skin, from
# a user's own space. They are configuration: the usual content is a handful of
# `importScript` lines choosing which tools to switch on. 684 of the declined
# pages are these, and 380 of those are `monobook.js` alone.
#
# `monobook.js` is nonetheless the one entry here that is not decisive on its
# own -- 15% of them held a real script, against 100% for `morebits.js` -- so a
# skin file is only called configuration when the model also declined it. See
# `classify`.
SKIN_FILES = frozenset(
    {
        "common.js",
        "standard.js",
        "nostalgia.js",
        "cologneblue.js",
        "monobook.js",
        "myskin.js",
        "chick.js",
        "simple.js",
        "modern.js",
        "vector.js",
        "vector-2022.js",
        "timeless.js",
        "minerva.js",
        "global.js",
    }
)

# Pages that hold one tool's saved options for one person. The tool is real and
# is catalogued from its own page; this is the reader's copy of its settings,
# and it describes no behaviour of its own. `EditCounterOptIn.js` is not
# settings but belongs with them: its existence is the whole message, and its
# contents are conventionally a joke.
SETTINGS_FILES = frozenset(
    {
        "twinkleoptions.js",
        "huggle.yaml.js",
        "huggle3.css.js",
        "livercparam.js",
        "editcounteroptin.js",
        "jwb-settings.json",
        "massblock.js.json",
    }
)

# A copy of a library that belongs to somebody else, or a build artefact of one.
# `morebits.js` was declined on 103 of 103 pages: it is Twinkle's own library,
# copied wholesale, and what it does is a property of Twinkle rather than of the
# page it was pasted onto.
VENDORED_RE = re.compile(
    r"(?:^|/)(?:morebits|jquery[.-]|qx)\b|\.(?:umd|min|bundle)\.js$|/(?:lib|vendor|dist)/",
    re.IGNORECASE,
)


_NOT_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def _key(value: str) -> str:
    """Return the page's filename in a spelling the fixed lists can match.

    Punctuation is dropped rather than trusted. The same file is written
    `EditCounterOptIn.js` on one wiki and `editcounteroptin.js` on the next, and
    a set membership test against the raw leaf would miss half of them for a
    difference that means nothing.
    """
    return _NOT_ALPHANUMERIC.sub("", (value or "").rsplit("/", 1)[-1].casefold())


SETTINGS_KEYS = frozenset(_key(name) for name in SETTINGS_FILES)
SKIN_KEYS = frozenset(_key(name) for name in SKIN_FILES)


def classify(title: str, *, declined: bool = False) -> str:
    """Say what a user-space page is, or `SHAPE_STANDALONE` if it is a tool.

    `declined` is whether the inference lane read this page's source and
    reported that it could not say what it does. It is required for the two
    judgments no naming rule can make -- whether a skin file holds a real
    script, and whether an otherwise unremarkable page is a helper module --
    and is ignored everywhere a name already settles the matter.

    A page nobody has asked the model about yet is `declined=False`, so it stays
    standalone until there is evidence otherwise. That is the safe direction:
    the cost of missing a component is a checklist nobody needed, and the cost
    of guessing wrong the other way is hiding a real maintainer's checklist.
    """
    key = _key(title)
    if key in SETTINGS_KEYS:
        return SHAPE_SETTINGS
    if VENDORED_RE.search(title or ""):
        return SHAPE_LIBRARY
    # Both remaining kinds need the model's reading, for opposite reasons: a
    # skin file often does hold a real tool, and a component is not recognizable
    # by name at all.
    if not declined:
        return SHAPE_STANDALONE
    if key in SKIN_KEYS:
        return SHAPE_SKIN
    return SHAPE_COMPONENT
