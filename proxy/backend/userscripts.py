# SPDX-License-Identifier: GPL-3.0-or-later
"""What one user-space JavaScript page is, and what it loads.

A wiki's user space is full of `.js` pages, and only a minority of them are
tools. The rest are one-line settings files, empty pages left by a rolled-back
edit, and — overwhelmingly — two-line *shims* that do nothing but load somebody
else's script. A census that counts pages therefore measures the wrong thing:
in a full pass over frwiki's 9,919 user-space JavaScript pages, the single
largest group of identical pages was 1,045 empty ones, and the most-copied
non-empty page was 43 bytes of `importScript` pointing at a gadget.

So this module answers two questions about a page body, and nothing else:

    classify()       what kind of page is this
    script_imports() what does it ask the wiki to load

Both run on the body with comments removed, which is not a detail. Popups
appears on frwiki as three separate byte-exact groups that differ only in their
credit comments and their load mechanism; hashing the raw text reports one
script as three. `fingerprint()` exists to stop that.

Everything here is a pure function of a string. Fetching pages, deciding which
of them belong in a directory, and collapsing copies onto their original are
separate concerns and separate modules.

Two boundaries worth stating plainly, because both were learned the expensive
way:

**Content model, never the file suffix.** `Penquista/monobook.css` on frwiki
contains JavaScript. Callers must select pages by `page_content_model`, and
this module assumes they did — it will happily analyze whatever it is handed.

**Loader verbs are per wiki.** frwiki defines its own import verb, `obtenir`,
in `MediaWiki:Common.js`, and 101 pages use it. It resolves to a gadget page by
a naming convention that exists only on that wiki. Nothing here guesses: a
local verb is declared in LOCAL_LOADERS for a specific wiki or it is not
recognized at all.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import Final
from urllib.parse import ParseResult, parse_qs, unquote, urlparse

from backend.wikimedia_urls import without_format_marks

# Names one wiki answers to for its user namespace, looked up by wiki. A
# callable rather than a mapping because the set of wikis a corpus refers to is
# discovered while reading it -- a load can name any wiki that exists.
Spellings = Callable[[str], tuple[str, ...]]

# What a page is. A directory holds ROLE_SCRIPT pages and nothing else, but the
# other three are not noise to be dropped -- a shim is the cleanest statement of
# demand in the whole corpus, and it is only readable as one if it is named.
ROLE_EMPTY: Final = "empty"
ROLE_STUB: Final = "stub"
ROLE_SHIM: Final = "shim"
ROLE_SCRIPT: Final = "script"

# A page that loads something and does almost nothing else is a shim: its point
# is the load. "Almost" is three lines, which covers the common shapes seen in
# the wild -- a guard condition, a configuration assignment, a trailing call --
# without letting a real script that happens to import a library be mistaken
# for a vote.
SHIM_MAX_OTHER_LINES: Final = 3

# Two lines or fewer with no load in them cannot be a tool. In practice this is
# a stray value, an abandoned experiment, or the word "test".
STUB_MAX_LINES: Final = 2

# Cap on a quoted loader argument. Real page titles are far shorter; the bound
# stops a pathological body from producing enormous match groups.
MAX_ARGUMENT_CHARS: Final = 300

# Verbs available on every wiki. `importScriptURI` must precede `importScript`
# in this order: the pattern alternates in sequence, so the shorter name would
# otherwise match first and leave "URI" behind.
GLOBAL_LOADER_VERBS: Final = (
    "importScriptURI",
    "importScript",
    "importStylesheet",
    "mw.loader.getScript",
    "mw.loader.load",
    "$.getScript",
)

# The one verb whose target is a stylesheet rather than a script. Kept
# distinguishable because a `.css` page is never a directory entry on its own,
# only an attachment to a script that demonstrably loads it.
STYLESHEET_VERBS: Final = frozenset({"importStylesheet"})


@dataclass(frozen=True)
class LocalLoader:
    """A load verb that exists on one wiki, and the title it resolves to.

    `title_template` is formatted with a single `name` field holding the verb's
    quoted argument. frwiki's `obtenir("RenommageCategorie")` resolves to
    `MediaWiki:Gadget-RenommageCategorie.js` by the convention its own
    `MediaWiki:Common.js` implements.
    """

    verb: str
    title_template: str


# Keyed by wiki domain. Adding a wiki means reading its `MediaWiki:Common.js`
# and writing down what you found -- these cannot be inferred.
LOCAL_LOADERS: Final[dict[str, tuple[LocalLoader, ...]]] = {
    "fr.wikipedia.org": (LocalLoader(verb="obtenir", title_template="MediaWiki:Gadget-{name}.js"),),
}


@dataclass(frozen=True)
class ScriptImport:
    """One load this page asks the wiki to perform.

    Exactly one of `title` and `url` carries the destination, or neither when
    the argument resolved to nothing usable. `verb` is preserved so a caller can
    tell a stylesheet load from a script load without re-parsing.
    """

    verb: str
    argument: str
    wiki: str = ""
    title: str = ""
    url: str = ""

    @property
    def is_stylesheet(self) -> bool:
        """Whether this load pulls in CSS rather than executable code."""
        return self.verb in STYLESHEET_VERBS


@dataclass(frozen=True)
class ScriptPage:
    """One analyzed page: what it is, what it loads, and how it hashes."""

    title: str
    role: str
    fingerprint: str
    imports: tuple[ScriptImport, ...]

    @property
    def is_candidate(self) -> bool:
        """Whether this page could be a directory entry at all.

        A necessary condition, not a sufficient one. Deciding that a candidate
        is an *original* rather than somebody's copy needs the whole corpus and
        happens elsewhere.
        """
        return self.role == ROLE_SCRIPT


# Comment stripping is deliberately lexical rather than a real JavaScript
# parse. The lookbehind keeps `https://` and a protocol-relative `//host/path`
# out of the line-comment rule; a `//` inside a string literal that is not
# preceded by a quote or colon is still treated as a comment, which is the
# known cost of not writing a tokenizer.
_BLOCK_COMMENT: Final = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT: Final = re.compile(r"(?<![:'\"])//[^\n]*")
_WHITESPACE: Final = re.compile(r"\s+")

# MediaWiki serves the user namespace under a localized name, and the API
# gender-normalizes it on the way back out: a title written `Utilisateur:Evpok`
# is returned as `Utilisatrice:Evpok`. Keying anything on the returned spelling
# splits one page into two.
_NAMESPACE_ALIASES: Final = ("User", "Utilisateur", "Utilisatrice")
_ALIAS_ANYWHERE: Final = re.compile(rf"\b(?:{'|'.join(_NAMESPACE_ALIASES)})\s*:", re.IGNORECASE)


@cache
def _alias_prefix(spellings: tuple[str, ...]) -> re.Pattern[str]:
    """Match a user-namespace prefix written in any of these spellings.

    The built-ins are always included, so a wiki whose own names could not be
    read still folds the two spellings that were folded before this was
    wiki-aware -- widening this must never be able to narrow it.

    Every spelling is escaped. The built-ins are literals and did not need it,
    but these arrive from a remote wiki's siteinfo, and a namespace name is
    free text as far as this code is concerned.
    """
    known = (*_NAMESPACE_ALIASES, *spellings)
    alternatives = "|".join(re.escape(spelling) for spelling in known)
    return re.compile(rf"^(?:{alternatives})\s*:\s*", re.IGNORECASE)


def no_spellings(_wiki: str) -> tuple[str, ...]:
    """Name no extra namespace spelling for any wiki.

    The default everywhere a resolver is optional, which keeps every caller
    that has no database -- tests, and the pure analysis of a single body --
    working on the built-ins alone.
    """
    return ()


_URL_ARGUMENT: Final = re.compile(r"^(?:https?:)?//", re.IGNORECASE)

_PERCENT_ESCAPE: Final = re.compile(r"%[0-9A-Fa-f]{2}")


_WIKI_PATH: Final = re.compile(r"^/wiki/(?P<title>.+)$")


def page_named_by(parsed: ParseResult, spellings: tuple[str, ...] = ()) -> str | None:
    """Return the title a parsed MediaWiki URL names, or None when it names none.

    Split out from `wiki_target` because the same two spellings turn up without
    a host at all: a script on frwiki asking for `/w/index.php?title=...` means
    a page on frwiki, and reading that as an opaque string files 47 of frwiki's
    load edges under a title no page will ever have.
    """
    query = parse_qs(parsed.query).get("title")
    if query:
        return canonical_title(query[0], spellings=spellings)  # parse_qs has already decoded it
    path = _WIKI_PATH.match(parsed.path)
    if path:
        return canonical_title(unquote(path.group("title")), spellings=spellings)
    return None


def wiki_target(url: str, spellings: Spellings = no_spellings) -> tuple[str, str]:
    """Split a URL into the wiki and page it names, or ("", "") if it names neither.

    Both MediaWiki spellings appear in the corpus: the raw-action query form
    that user scripts use to fetch code (1,658 of frwiki's 1,807 URL imports)
    and the pretty `/wiki/Title` path (17). Everything else -- a `load.php`
    module bundle, a CDN file, a Toolserver path -- stays an opaque URL,
    because it does not name a page a directory can hold an entry for.

    Resolving these is what makes cross-wiki reuse visible at all, and that is
    most of what is here: 1,160 of those 1,807 imports point off frwiki, 536 of
    them at en.wikipedia. A census that reads only local titles sees a wiki
    with no dependencies.

    The host is reported as read, never as trusted. It arrives from a page
    anyone can edit, so a caller that turns it into a request must still put
    that request through `backend.outbound`.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not host:
        return ("", "")
    # The host's own spellings, not the loading wiki's: this title belongs to
    # whatever wiki the URL names.
    title = page_named_by(parsed, spellings(host))
    return (host, title) if title is not None else ("", "")


@cache
def _verbs(wiki: str) -> tuple[str, ...]:
    """Every load verb recognized on `wiki`, longest-first within each family."""
    local = tuple(loader.verb for loader in LOCAL_LOADERS.get(wiki, ()))
    return GLOBAL_LOADER_VERBS + local


@cache
def _call_pattern(wiki: str) -> re.Pattern[str]:
    """Match a load *call*, whatever its argument looks like.

    Used for classification, where `importScript(someVariable)` still means the
    page's purpose is loading something.
    """
    alternatives = "|".join(re.escape(verb) for verb in _verbs(wiki))
    return re.compile(rf"(?<![A-Za-z0-9_$])(?P<verb>{alternatives})\s*\(")


@cache
def _edge_pattern(wiki: str) -> re.Pattern[str]:
    """Match a load call whose argument is a quoted literal we can resolve."""
    alternatives = "|".join(re.escape(verb) for verb in _verbs(wiki))
    return re.compile(
        rf"(?<![A-Za-z0-9_$])(?P<verb>{alternatives})\s*\(\s*"
        rf"(?P<quote>['\"])(?P<argument>[^'\"]{{0,{MAX_ARGUMENT_CHARS}}})(?P=quote)"
    )


def _blank_block(match: re.Match[str]) -> str:
    """Replace one block comment with whitespace of the same line count.

    Collapsing a multi-line comment to a single space would join the code
    before it to the code after it, and classification counts lines: a
    twelve-line script wrapped around one long comment would read as a stub.
    """
    newlines = match.group().count("\n")
    return "\n" * newlines if newlines else " "


def strip_comments(body: str) -> str:
    """Return `body` with block and line comments blanked out.

    Comments are replaced by whitespace rather than removed, so that both line
    structure and token separation survive for everything downstream.
    """
    return _LINE_COMMENT.sub(" ", _BLOCK_COMMENT.sub(_blank_block, body or ""))


def canonical_title(title: str, *, spellings: tuple[str, ...] = ()) -> str:
    """Return one spelling of a wiki page title.

    Underscores become spaces, runs of whitespace collapse, a localized user
    namespace becomes `User`, and the first character of the page name is
    capitalized because `$wgCapitalLinks` is true on every Wikipedia. (It is
    not true on every Wiktionary; a wiki where it is false would need this
    made conditional before its titles could be keyed on.)

    `spellings` are the extra names one wiki answers to for its user namespace,
    read from that wiki's siteinfo. They must be the names of the wiki the
    *title* belongs to, which for a cross-wiki load is the target's, not the
    loading page's -- `Benutzer:` means namespace 2 on dewiki and means nothing
    at all on frwiki.
    """
    clean = " ".join(without_format_marks(str(title or "")).replace("_", " ").split())
    if not clean:
        return ""
    stem = _alias_prefix(tuple(spellings)).sub("", clean)
    if stem != clean:
        clean = f"User:{stem}"
    namespace, separator, name = clean.partition(":")
    if separator and name:
        return f"{namespace}:{name[0].upper()}{name[1:]}"
    return f"{clean[0].upper()}{clean[1:]}"


def fingerprint(body: str) -> str:
    """Return a content hash that ignores comments, spacing, and namespace alias.

    Two pages with the same fingerprint are the same script as far as this
    census is concerned. The three normalizations are not cosmetic: each one
    corresponds to a group that a raw byte hash splits and should not.

    An empty or comments-only body has no fingerprint to give, and returns "" so
    callers cannot accidentally cluster every blank page together.
    """
    stripped = _ALIAS_ANYWHERE.sub("User:", strip_comments(body))
    flat = _WHITESPACE.sub(" ", stripped).strip()
    if not flat:
        return ""
    return hashlib.sha256(flat.encode("utf-8", "replace")).hexdigest()


def _code_lines(body: str) -> list[str]:
    """Return the non-blank lines of `body` with comments already removed."""
    return [line for line in (raw.strip() for raw in strip_comments(body).splitlines()) if line]


def classify(body: str, *, wiki: str = "") -> str:
    """Return which of the four roles this page body plays.

    The order of the tests matters. A page that loads something is a shim even
    when it is short, because "short" is not what makes it a vote rather than a
    tool; and a page that loads something *and* has real code of its own is a
    script that happens to use a library, which is why the shim test measures
    the lines that are not loads.
    """
    lines = _code_lines(body)
    if not lines:
        return ROLE_EMPTY
    call = _call_pattern(wiki)
    loads = sum(1 for line in lines if call.search(line))
    if loads and len(lines) - loads <= SHIM_MAX_OTHER_LINES:
        return ROLE_SHIM
    if len(lines) <= STUB_MAX_LINES:
        return ROLE_STUB
    return ROLE_SCRIPT


def _local_template(verb: str, wiki: str) -> str:
    """Return the title template for a wiki-local verb, or "" for a global one."""
    for loader in LOCAL_LOADERS.get(wiki, ()):
        if loader.verb == verb:
            return loader.title_template
    return ""


def _unwrapped(raw: str) -> str:
    """Drop the `[[...]]` a few authors write their load targets inside."""
    stripped = raw.strip()
    if stripped.startswith("[[") and stripped.endswith("]]"):
        return stripped[2:-2].strip()
    return stripped


def _decoded(raw: str) -> str:
    """Percent-decode a title, leaving anything that is not an escape alone.

    Scripts copy their targets out of URLs, so a handful arrive still encoded --
    `User:%C3%9Ejarkur/...` names a page that exists, spelled a way the census
    never stores. `unquote` passes a bare `%` through untouched, so a page whose
    real title contains one is not damaged.
    """
    return unquote(raw) if _PERCENT_ESCAPE.search(raw) else raw


def _resolve(verb: str, argument: str, wiki: str, spellings: Spellings) -> tuple[str, str, str]:
    """Turn one quoted loader argument into (wiki, title, url); "" where unusable."""
    # Cleaned before anything reads it, so the URL this returns and the title
    # derived from it are both already in storage's spelling.
    raw = _unwrapped(without_format_marks(argument))
    if not raw:
        return ("", "", "")
    template = _local_template(verb, wiki)
    if template:
        return (wiki, canonical_title(template.format(name=raw), spellings=spellings(wiki)), "")
    if _URL_ARGUMENT.match(raw):
        host, title = wiki_target(raw, spellings)
        return (host, title, raw)
    # A MediaWiki URL with no host names a page on the wiki that wrote it.
    if raw.startswith("/"):
        title = page_named_by(urlparse(raw), spellings(wiki))
        if title:
            return (wiki, title, "")
    return (wiki, canonical_title(_decoded(raw), spellings=spellings(wiki)), "")


def script_imports(body: str, *, wiki: str = "", spellings: Spellings = no_spellings) -> tuple[ScriptImport, ...]:
    """Return every resolvable load in `body`, in source order, without repeats.

    Repeats are dropped because this is used to count *demand*, and a page that
    imports the same script twice wants it once. Deduplication is on the whole
    resolved import, so the same target reached by two different verbs stays two
    edges -- that difference is real and occasionally load-bearing.
    """
    found: list[ScriptImport] = []
    seen: set[tuple[str, str, str, str]] = set()
    for match in _edge_pattern(wiki).finditer(strip_comments(body)):
        verb = match.group("verb")
        argument = match.group("argument")
        target, title, url = _resolve(verb, argument, wiki, spellings)
        if not title and not url:
            continue
        key = (verb, target, title, url)
        if key in seen:
            continue
        seen.add(key)
        found.append(ScriptImport(verb=verb, argument=argument, wiki=target, title=title, url=url))
    return tuple(found)


def analyze(title: str, body: str, *, wiki: str = "", spellings: Spellings = no_spellings) -> ScriptPage:
    """Analyze one page in a single pass over its body.

    `fingerprint` is deliberately not given the wiki's spellings. Fingerprints
    are stored and compared against each other, so widening the rule that
    produces them would change every hash already written and make a page look
    like a fork of itself until the whole wiki had been swept again. Folding
    them is worth doing with fork detection, where the comparison is being
    reworked anyway, and not as a side effect of learning a namespace name.
    """
    return ScriptPage(
        title=canonical_title(title, spellings=spellings(wiki)),
        role=classify(body, wiki=wiki),
        fingerprint=fingerprint(body),
        imports=script_imports(body, wiki=wiki, spellings=spellings),
    )
