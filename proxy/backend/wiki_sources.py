# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure parsing for tool source hosted on a wiki rather than in a repository.

Wikimedia user scripts and gadgets are source code that never enters a forge:
a gadget *is* a set of `MediaWiki:Gadget-*` pages, and a user script is a
`User:` subpage with a code content model. They have revisions rather than
commits, editors rather than contributors, and no branches at all, so the
forge vocabulary in source_hosts only half fits -- which is why `kind` exists.

Nothing here performs I/O. The two page sets a caller needs are each derived
from one document it must fetch itself: a gadget's peers come out of
`MediaWiki:Gadgets-definition`, a user script's out of an allpages listing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from backend.wikimedia_urls import clean_wiki_domain

KIND_USER_SCRIPT = "user-script"
KIND_GADGET = "gadget"

NAMESPACE_USER = "User"
NAMESPACE_MEDIAWIKI = "MediaWiki"
# Canonical spellings, keyed by the case-folded prefix a URL might carry.
NAMESPACES = {NAMESPACE_USER.casefold(): NAMESPACE_USER, NAMESPACE_MEDIAWIKI.casefold(): NAMESPACE_MEDIAWIKI}
# MediaWiki's built-in namespace numbers, which list=allpages takes instead of
# a name. Fixed by the software, not per-wiki configuration.
NAMESPACE_IDS = {NAMESPACE_USER: 2, NAMESPACE_MEDIAWIKI: 8}

GADGET_PREFIX = f"{NAMESPACE_MEDIAWIKI}:Gadget-"
GADGET_DEFINITION_TITLE = f"{NAMESPACE_MEDIAWIKI}:Gadgets-definition"

# MediaWiki only assigns a code content model to pages with these extensions,
# so a title without one is prose about a tool rather than the tool.
SOURCE_SUFFIXES = (".js", ".css", ".json")

MAX_TITLE_CHARS = 255
# Both page sets are bounded so that one malformed definition line or one
# enormous user-space tree cannot turn a single tool into an unbounded scan.
MAX_PAGES = 50

DEFINITION_LINE_RE = re.compile(r"^\*\s*(?P<body>.+)$")


@dataclass(frozen=True)
class WikiSource:
    """One wiki page that holds a tool's source, and which kind of tool it is."""

    domain: str
    title: str
    kind: str

    @property
    def filename(self) -> str:
        """Return the gadget file name this page provides, or "" for a user script.

        `MediaWiki:Gadget-Twinkle.js` provides `Twinkle.js`, which is the
        spelling `MediaWiki:Gadgets-definition` lists it under.
        """
        return self.title.removeprefix(GADGET_PREFIX) if self.kind == KIND_GADGET else ""

    @property
    def stem(self) -> str:
        """Return the title without its source suffix, for finding peer subpages."""
        return _stem(self.title)

    @property
    def namespace_id(self) -> int:
        """Return the namespace number list=allpages needs to search this page."""
        return NAMESPACE_IDS[self.title.partition(":")[0]]

    @property
    def prefix(self) -> str:
        """Return the allpages prefix for this script's peers.

        Namespace-relative on purpose: apprefix is matched inside apnamespace,
        so leaving `User:` on the front would search for a page whose name
        literally begins with it.
        """
        return self.stem.partition(":")[2]


def _stem(title: str) -> str:
    """Return the title without its code suffix, or unchanged if it has none."""
    for suffix in SOURCE_SUFFIXES:
        if title.casefold().endswith(suffix):
            return title[: -len(suffix)]
    return title


def _is_source_title(title: str) -> bool:
    """Report whether MediaWiki gives this title a code content model.

    Derived from _stem rather than repeating the suffix test, so the two can
    never disagree about where a title ends.
    """
    return _stem(title) != title


def canonical_title(value: str) -> str:
    """Return one MediaWiki spelling of a page title, or "" if there is no title.

    Underscores and spaces are interchangeable and a title copied out of a URL
    carries underscores, so both spellings must collapse to one -- otherwise
    the same gadget enriches twice under two different keys. MediaWiki
    capitalizes the first character after the namespace and leaves the rest
    alone, so this does the same: `Gadget-twinkle.js` and `Gadget-Twinkle.js`
    are one page, `morebits.js` and `Morebits.js` are two.
    """
    clean = " ".join(unquote(str(value or "")).replace("_", " ").split())
    prefix, separator, remainder = clean.partition(":")
    namespace = NAMESPACES.get(prefix.casefold()) if separator else None
    if namespace is None:
        return clean[:MAX_TITLE_CHARS]
    page = remainder.strip()
    return f"{namespace}:{page[:1].upper()}{page[1:]}"[:MAX_TITLE_CHARS] if page else ""


def _url_title(url: str) -> tuple[str, str] | None:
    """Return (domain, raw title) for a public Wikimedia page URL."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme.casefold() != "https" or parsed.username or parsed.password:
        return None
    try:
        domain = clean_wiki_domain(parsed.hostname or "")
    except (ValueError, TypeError):
        return None
    if parsed.port not in {None, 443}:
        return None
    path = unquote(parsed.path)
    candidates = [path.split("/wiki/", 1)[1]] if "/wiki/" in path else []
    # index.php?title=X is the same page as /wiki/X, and toolinfo carries both.
    candidates.extend(parse_qs(parsed.query).get("title", []))
    for candidate in candidates:
        if title := canonical_title(candidate):
            return domain, title
    return None


def wiki_source(url: str) -> WikiSource | None:
    """Resolve one URL to a wiki-hosted source page, or None if it is not one.

    Deliberately strict about the suffix. A `User:` page with no extension is
    documentation, a project page, or a talk archive -- scanning it as source
    would file prose as code and score a tool on it.
    """
    resolved = _url_title(url)
    if resolved is None:
        return None
    domain, title = resolved
    if not _is_source_title(title):
        return None
    if title.startswith(GADGET_PREFIX):
        return WikiSource(domain=domain, title=title, kind=KIND_GADGET)
    if title.startswith(f"{NAMESPACE_USER}:") and "/" in title:
        # A subpage, not User:Someone -- the account page itself is never source.
        return WikiSource(domain=domain, title=title, kind=KIND_USER_SCRIPT)
    return None


def page_url(domain: str, title: str) -> str:
    """Return the canonical https URL of one wiki page."""
    return f"https://{domain}/wiki/{title.replace(' ', '_')}"


def _definition_entry(line: str) -> tuple[str, tuple[str, ...]] | None:
    """Split one Gadgets-definition line into its gadget name and page files.

    The documented shape is `* name[options]|File.js|File.css`, and the options
    themselves contain pipes (`dependencies=a,b|rights=c`), so the file list
    can only be found after the closing bracket -- splitting the whole line on
    `|` would read `rights=c` as a page.
    """
    match = DEFINITION_LINE_RE.match(line.strip())
    if match is None:
        return None
    body = match.group("body")
    name, bracket, tail = body.partition("[")
    if bracket:
        _options, closed, tail = tail.partition("]")
        if not closed:
            return None
    else:
        name, _, tail = body.partition("|")
    files = tuple(part.strip() for part in tail.split("|") if _is_source_title(part.strip()))
    return (name.strip(), files) if name.strip() and files else None


def gadget_pages(definition: str, filename: str) -> tuple[str, ...]:
    """Return every page of the gadget that `filename` belongs to.

    A gadget is defined as a set, so any one of its files identifies all of
    them. Returns () when the definition does not list this file: an
    unregistered `MediaWiki:Gadget-*` page is a leftover or a work in progress,
    and inventing a set for it would be a guess.
    """
    for line in definition.splitlines():
        entry = _definition_entry(line)
        if entry is not None and filename in entry[1]:
            return tuple(f"{GADGET_PREFIX}{name}" for name in entry[1])[:MAX_PAGES]
    return ()


def subpage_titles(source: WikiSource, listed: list[str]) -> tuple[str, ...]:
    """Return the pages of `listed` that belong to this user script.

    An allpages prefix search is broader than the script: querying
    `Foo/twinkle` also returns `Foo/twinkleblock.js`, a different tool by the
    same author. Only an exact suffix swap (`.js` -> `.css`) or a real subpage
    (`Foo/twinkle/core.js`) is part of this one.
    """
    stem = source.stem
    kept = [
        title
        for title in (canonical_title(value) for value in listed)
        if _is_source_title(title) and (_stem(title) == stem or title.startswith(f"{stem}/"))
    ]
    ordered = [source.title, *sorted(set(kept) - {source.title})]
    return tuple(ordered[:MAX_PAGES])
