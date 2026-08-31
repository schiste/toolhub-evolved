# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure parsing for tool source hosted on a wiki rather than in a repository.

Wikimedia user scripts and gadgets are source code that never enters a forge:
a gadget is a set of `MediaWiki:Gadget-*` pages *registered* in
`MediaWiki:Gadgets-definition`, and a user script is a `User:` subpage with a
code content model. They have revisions rather than commits, editors rather
than contributors, and no branches at all, so the forge vocabulary in
source_hosts only half fits -- which is why `kind` exists.

The two differ in what settles them, and `kind` is careful about it. A user
script is settled by its namespace: `User:Someone/foo.js` is one, and no
registry exists that could disagree. A gadget is not. The Gadgets extension
serves a gadget because a line in the definition page names its files, sets
its options and puts it in Preferences; the `MediaWiki:Gadget-` title is the
convention those files follow, not the thing that makes them a gadget. A page
whose definition line was removed when the gadget was retired keeps the title
and stops being a gadget. So a URL alone yields KIND_GADGET_PAGE, and only
`registered_gadget` -- given the definition text -- can return KIND_GADGET.

Nothing here performs I/O. The two page sets a caller needs are each derived
from one document it must fetch itself: a gadget's peers come out of
`MediaWiki:Gadgets-definition`, a user script's out of an allpages listing.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, replace
from urllib.parse import parse_qs, unquote, urlparse

from backend.wikimedia_urls import clean_wiki_domain, without_format_marks

KIND_USER_SCRIPT = "user-script"
#: A page listed in MediaWiki:Gadgets-definition. Only registered_gadget returns
#: this, because only the definition page proves it.
KIND_GADGET = "gadget"
#: A `MediaWiki:Gadget-*` page whose registration has not been established --
#: either not looked up, or looked up and absent. Deliberately one kind for both:
#: a caller that has not checked knows exactly as much as one that checked and
#: found nothing, which is that this is a page in the gadget namespace.
KIND_GADGET_PAGE = "gadget-page"
#: Every kind that names a page under GADGET_PREFIX, registered or not.
GADGET_KINDS = frozenset({KIND_GADGET, KIND_GADGET_PAGE})

NAMESPACE_USER = "User"
NAMESPACE_MEDIAWIKI = "MediaWiki"
# Canonical spellings, keyed by the case-folded prefix a URL might carry.
NAMESPACES = {NAMESPACE_USER.casefold(): NAMESPACE_USER, NAMESPACE_MEDIAWIKI.casefold(): NAMESPACE_MEDIAWIKI}
# MediaWiki's built-in namespace numbers, which list=allpages takes instead of
# a name. Fixed by the software, not per-wiki configuration.
NAMESPACE_IDS = {NAMESPACE_USER: 2, NAMESPACE_MEDIAWIKI: 8}

GADGET_PREFIX = f"{NAMESPACE_MEDIAWIKI}:Gadget-"
#: How a gadget's description message is named: the same spelling as
#: `GADGET_PREFIX` without the namespace, because a message is asked for by key
#: and a key carrying one names nothing.
GADGET_MESSAGE_PREFIX = "Gadget-"
GADGET_DEFINITION_TITLE = f"{NAMESPACE_MEDIAWIKI}:Gadgets-definition"

# MediaWiki only assigns a code content model to pages with these extensions,
# so a title without one is prose about a tool rather than the tool.
SOURCE_SUFFIXES = (".js", ".css", ".json")

MAX_TITLE_CHARS = 255
# Both page sets are bounded so that one malformed definition line or one
# enormous user-space tree cannot turn a single tool into an unbounded scan.
MAX_PAGES = 50

DEFINITION_LINE_RE = re.compile(r"^\*\s*(?P<body>.+)$")
# Sections are declared by a heading of any depth, which is what MediaWiki's own
# reader accepts -- frwiki nests `=== Pages ===` under `== Apparence ==` and both
# start a section there, so treating only `==` as one would file half the wiki's
# gadgets under the wrong heading.
DEFINITION_SECTION_RE = re.compile(r"^=+\s*(?P<section>[^=]+?)\s*=+$")
# Editors leave notes next to a file name (`AjoutRapide.js <!-- see T432122 -->`).
# The comment is not part of the title, and leaving it attached makes the entry
# stop ending in `.js`, so the file silently drops out of the gadget's page set.
DEFINITION_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass(frozen=True)
class GadgetEntry:
    """One gadget exactly as its wiki's definition page declares it.

    Options are kept as parsed pairs rather than a dict so the entry stays
    hashable and ordered the way the wiki wrote them. A bare option like
    `default` or `hidden` is a key with no values, which is why every lookup
    returns a tuple and `has` is a separate question from `values`.

    This is a transcription, not a judgement: `hidden` is recorded, not acted
    on. Whether a hidden gadget is a tool worth cataloguing is a decision for
    the caller that builds catalogue records, and one this parser must not make
    on its behalf.
    """

    name: str
    section: str
    options: tuple[tuple[str, tuple[str, ...]], ...]
    pages: tuple[str, ...]

    def values(self, key: str) -> tuple[str, ...]:
        """Return the values given for one option, or () if it is absent or bare."""
        for option, values in self.options:
            if option == key:
                return values
        return ()

    def has(self, key: str) -> bool:
        """Report whether an option was declared at all, with or without values."""
        return any(option == key for option, _values in self.options)


@dataclass(frozen=True)
class WikiSource:
    """One wiki page that holds a tool's source, and which kind of tool it is.

    `kind` reports only what its source of truth has established. A gadget page
    arrives as KIND_GADGET_PAGE and becomes KIND_GADGET when, and only when,
    `registered_gadget` finds it in the definition text.
    """

    domain: str
    title: str
    kind: str

    @property
    def filename(self) -> str:
        """Return the gadget file name this page provides, or "" for a user script.

        `MediaWiki:Gadget-Twinkle.js` provides `Twinkle.js`, which is the
        spelling `MediaWiki:Gadgets-definition` lists it under. Answered for an
        unregistered page too: the name is what a lookup in that page needs, so
        withholding it until the lookup succeeds would be circular.
        """
        return self.title.removeprefix(GADGET_PREFIX) if self.kind in GADGET_KINDS else ""

    @property
    def stem(self) -> str:
        """Return the title without its source suffix, for finding peer subpages."""
        return _stem(self.title)

    @property
    def namespace(self) -> str:
        """Return the canonical namespace name this page is stored under."""
        return self.title.partition(":")[0]

    @property
    def namespace_id(self) -> int:
        """Return the namespace number list=allpages needs to search this page."""
        return NAMESPACE_IDS[self.namespace]

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

    Invisible formatting marks go too, after decoding rather than before: a
    toolinfo URL can carry one percent-encoded, and it is only a character to
    drop once unquote has turned it back into one. A marked title reaches the
    same page as the clean one, so leaving the mark in would enrich that page
    twice under two keys that no reader can tell apart.
    """
    clean = " ".join(without_format_marks(unquote(str(value or ""))).replace("_", " ").split())
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

    Strict about `kind` for the same reason. A gadget-namespace title resolves
    to KIND_GADGET_PAGE however conventional it looks, because registration is
    the predicate and it lives in another page.
    """
    resolved = _url_title(url)
    if resolved is None:
        return None
    domain, title = resolved
    if not _is_source_title(title):
        return None
    if title.startswith(GADGET_PREFIX):
        # Not KIND_GADGET: a URL cannot show a definition line, and this module
        # performs no I/O to go and read one. See registered_gadget.
        return WikiSource(domain=domain, title=title, kind=KIND_GADGET_PAGE)
    if title.startswith(f"{NAMESPACE_USER}:") and "/" in title:
        # A subpage, not User:Someone -- the account page itself is never source.
        return WikiSource(domain=domain, title=title, kind=KIND_USER_SCRIPT)
    return None


def page_url(domain: str, title: str) -> str:
    """Return the canonical https URL of one wiki page."""
    return f"https://{domain}/wiki/{title.replace(' ', '_')}"


#: The Terms of Use every Wikimedia wiki publishes under, and the one document
#: that says anything at all about the licence of a script or gadget page.
TERMS_OF_USE_URL = "https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use"
#: The day the current Terms took effect and moved new contributions from
#: CC BY-SA 3.0 to 4.0. Everything published before it was licensed under 3.0
#: and was never relicensed, so this date -- not today's Terms -- decides which
#: version a given page carries.
TERMS_4_0_EFFECTIVE = "2023-06-07"
LICENSE_CC_BY_SA_3 = "CC-BY-SA-3.0"
LICENSE_CC_BY_SA_4 = "CC-BY-SA-4.0"


def content_license(created_at: str) -> str:
    """Return the SPDX licence a wiki page carries by the Terms of Use, or "".

    This is the one field on a script or gadget that no page states and every
    page nonetheless has. Section 7 of the Terms binds text contributed to any
    Wikimedia project under CC BY-SA, and carves out nothing for JavaScript or
    CSS: the words never appear. Nor does the project supply a different rule --
    `Wikipedia:User scripts` says a great deal about trusting a script and
    nothing about copying one. So the site-wide term is the whole of the answer,
    and reading it off is a transcription of a declaration the author made by
    publishing, not a guess about a page nobody licensed.

    The version is what makes it a computation rather than a constant, and the
    reason `created_at` is required. The current Terms took effect on 7 June
    2023; everything published before them was licensed under CC BY-SA 3.0, and
    a later Terms of Use cannot relicense a contribution already made. A page
    first written in 2009 is 3.0 today. In a 120-page sample of enwiki user
    scripts, 102 were created before that date, so calling the corpus 4.0
    because the Terms now say 4.0 would misstate roughly six pages in seven.

    Creation, not last edit, settles it: an edit in 2024 adds 4.0 material to a
    page whose earlier revisions stay 3.0, and the licence anybody reusing the
    whole page must honour is the older one. The result is deliberately the stricter
    of the two claims the page supports.

    Only the date is compared, so a bare `2023-06-07` and a full instant agree,
    and anything too short to be a date -- including the "" an undated page
    already carries -- is treated as undated.

    An undated page yields "", the same answer `created_date` itself gives.
    Which version applies is a question about when, so a page the Wiki Replicas
    have never dated publishes no licence rather than the more common guess.
    Dual licensing under the GFDL is omitted for the same reason a single SPDX
    identifier can only say one thing: the Terms let anybody reusing it satisfy
    either, and CC BY-SA is the one they reach for.
    """
    day = created_at.strip()[: len(TERMS_4_0_EFFECTIVE)]
    if len(day) != len(TERMS_4_0_EFFECTIVE) or not day[:4].isdigit():
        return ""
    return LICENSE_CC_BY_SA_4 if day >= TERMS_4_0_EFFECTIVE else LICENSE_CC_BY_SA_3


def _definition_options(text: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Split the inside of a definition's bracket into its options.

    Options are pipe-separated, and each is either bare (`hidden`) or carries a
    comma-separated list (`dependencies=a,b`). An option with an empty value
    list is kept as a bare one so `rights=` and `rights` cannot be told apart
    by accident downstream.
    """
    parsed: list[tuple[str, tuple[str, ...]]] = []
    for part in text.split("|"):
        option, _equals, listed = part.strip().partition("=")
        if not (key := option.strip()):
            continue
        values = tuple(value for item in listed.split(",") if (value := item.strip()))
        parsed.append((key, values))
    return tuple(parsed)


def _definition_page(name: str) -> str:
    """Return one definition-listed file name in the spelling a page title carries.

    A definition line writes each file exactly as its author typed it, and
    `MediaWiki:Gadget-C_helper.js` and `MediaWiki:Gadget-C helper.js` are one
    page -- fr.wikipedia registers C helper with underscores, Commons registers
    everything with spaces, and both are correct. So the raw text cannot be
    compared against a `filename` that arrived through canonical_title.

    Routed through canonical_title rather than repeating the rule, so the
    spelling a definition is matched by and the spelling a URL resolves to
    cannot drift apart. Returns "" for a name that leaves no title behind,
    which the caller's source-title test then drops.

    Stripped here rather than by the caller: the padding around `| File.js |`
    would otherwise land after the prefix, inside the part canonical_title
    treats as the page name, where it survives as a leading space.
    """
    return canonical_title(f"{GADGET_PREFIX}{name.strip()}").removeprefix(GADGET_PREFIX)


def _definition_entry(line: str) -> GadgetEntry | None:
    """Split one Gadgets-definition line into its gadget name, options and files.

    The documented shape is `* name[options]|File.js|File.css`, and the options
    themselves contain pipes (`dependencies=a,b|rights=c`), so the file list
    can only be found after the closing bracket -- splitting the whole line on
    `|` would read `rights=c` as a page.

    The section is the caller's to supply because it is not on this line: it
    comes from the last heading above it, which only something reading the
    whole page can know.
    """
    match = DEFINITION_LINE_RE.match(line.strip())
    if match is None:
        return None
    body = DEFINITION_COMMENT_RE.sub("", match.group("body"))
    name, bracket, tail = body.partition("[")
    options: tuple[tuple[str, tuple[str, ...]], ...] = ()
    if bracket:
        declared, closed, tail = tail.partition("]")
        if not closed:
            return None
        options = _definition_options(declared)
    else:
        name, _, tail = body.partition("|")
    listed = (_definition_page(part) for part in tail.split("|"))
    files = tuple(name for name in listed if _is_source_title(name))
    if not (name.strip() and files):
        return None
    return GadgetEntry(name=name.strip(), section="", options=options, pages=files[:MAX_PAGES])


def gadget_entries(definition: str) -> tuple[GadgetEntry, ...]:
    """Return every gadget one wiki's definition page declares, in page order.

    The inventory counterpart of `gadget_pages`: that answers "what else is in
    this gadget", this answers "what gadgets are there". Both read the same
    line the same way, which is the point of them living together -- two
    readers that disagreed about a gadget's file set would put one gadget in
    the catalogue under two different page sets.

    A repeated name keeps its first declaration. MediaWiki resolves a duplicate
    that way too, and a catalogue that took the last one would disagree with
    the wiki about which code a reader actually gets.
    """
    found: list[GadgetEntry] = []
    seen: set[str] = set()
    section = ""
    for line in definition.splitlines():
        if (heading := DEFINITION_SECTION_RE.match(line.strip())) is not None:
            section = heading.group("section")
            continue
        entry = _definition_entry(line)
        if entry is None or entry.name in seen:
            continue
        seen.add(entry.name)
        found.append(GadgetEntry(name=entry.name, section=section, options=entry.options, pages=entry.pages))
    return tuple(found)


@dataclass(frozen=True)
class GadgetDeclaration:
    """One gadget's definition line, kept with where on the page it was found.

    The line number and the text travel with the entry because a caller that
    reports on the declaration has to cite it, and `MediaWiki:Gadgets-definition`
    is a page a maintainer can open at that line. An entry alone would force
    every such caller to search the page again for the line it came from.
    """

    entry: GadgetEntry
    line_number: int
    line: str


def gadget_declaration(definition: str, filename: str) -> GadgetDeclaration | None:
    """Return the definition line that registers `filename`, or None if none does.

    One pass answers both questions callers ask of this page -- which files the
    gadget consists of, and what the wiki declared about it -- so neither has to
    read the page a second time.
    """
    for number, line in enumerate(definition.splitlines(), start=1):
        entry = _definition_entry(line)
        if entry is not None and filename in entry.pages:
            return GadgetDeclaration(entry=entry, line_number=number, line=line)
    return None


def gadget_pages(definition: str, filename: str) -> tuple[str, ...]:
    """Return every page of the gadget that `filename` belongs to.

    A gadget is defined as a set, so any one of its files identifies all of
    them. Returns () when the definition does not list this file: an
    unregistered `MediaWiki:Gadget-*` page is a leftover or a work in progress,
    and inventing a set for it would be a guess.
    """
    declaration = gadget_declaration(definition, filename)
    return gadget_titles(declaration.entry) if declaration else ()


def gadget_titles(entry: GadgetEntry) -> tuple[str, ...]:
    """Return the full page titles of one gadget's files."""
    return tuple(f"{GADGET_PREFIX}{name}" for name in entry.pages)


def registered_gadget(source: WikiSource, definition: str) -> tuple[WikiSource, tuple[str, ...]]:
    """Settle whether a gadget page is registered, and return the pages to read.

    Answers both questions from one document because they have one answer. The
    definition line is what makes these files a gadget *and* what says which
    files it consists of; finding it settles the kind and the page set together,
    and not finding it settles neither.

    An unregistered page still holds source worth reading, so it comes back as
    its own single-page set -- read it, report on it, but do not call it a
    gadget. Passing anything but a gadget-namespace source is a caller error and
    returns it unchanged, since only such a page can appear in a definition.
    """
    if source.kind not in GADGET_KINDS:
        return source, (source.title,)
    pages = gadget_pages(definition, source.filename)
    if not pages:
        return replace(source, kind=KIND_GADGET_PAGE), (source.title,)
    return replace(source, kind=KIND_GADGET), pages


def listed_title(source: WikiSource, listed: str) -> str:
    """Return one canonical spelling of a title a wiki listed for `source`.

    `canonical_title` on its own is not enough for a title that came back from
    the Action API, because the API answers in the wiki's own language. The
    page this service holds as `User:PDD/unsigned.js` is returned by
    de.wikisource as `Benutzer:PDD/unsigned.js` and by fr.wikipedia as
    `Utilisateur:PDD/unsigned.js`. `canonical_title` leaves those prefixes
    alone, which is right when it is asked about a title from nowhere in
    particular -- it cannot tell a namespace it has never heard of from a page
    whose name simply contains a colon.

    Here it can. The listing that produced this title was restricted to
    `source.namespace_id`, a number, so every title in it is in that namespace
    whatever the wiki calls it locally. Swapping the label is a rename between
    two spellings of one namespace rather than a guess, and it is what lets a
    localized title be compared with the canonical one this service stores.

    Left alone when the labels already agree, so the English wikis -- where
    this was the only behaviour for as long as the comparison was string
    equality -- keep going through exactly the path they did before.
    """
    clean = canonical_title(listed)
    namespace, separator, page = clean.partition(":")
    if not separator or namespace == source.namespace:
        return clean
    return canonical_title(f"{source.namespace}:{page}")


def subpage_titles(source: WikiSource, listed: list[str]) -> tuple[str, ...]:
    """Return the pages of `listed` that belong to this user script.

    An allpages prefix search is broader than the script: querying
    `Foo/twinkle` also returns `Foo/twinkleblock.js`, a different tool by the
    same author. Only an exact suffix swap (`.js` -> `.css`) or a real subpage
    (`Foo/twinkle/core.js`) is part of this one.

    Answered in canonical spellings, including for the localized titles a
    non-English wiki lists: see `listed_title`. A caller holding the wiki's own
    spellings has to put them through `listed_title` too before looking them up
    in this result, which is the whole reason that step is a named function
    rather than something this one does inline.
    """
    stem = source.stem
    kept = [
        title
        for title in (listed_title(source, value) for value in listed)
        if _is_source_title(title) and (_stem(title) == stem or title.startswith(f"{stem}/"))
    ]
    ordered = [source.title, *sorted(set(kept) - {source.title})]
    return tuple(ordered[:MAX_PAGES])


# A description message is wikitext written for Special:Gadgets, not for a
# catalogue. Ordered deliberately: links resolve before tags are stripped, so
# the `<nowiki>[</nowiki>` a wiki uses to print a literal bracket around a link
# is still recognizable as a tag when its turn comes, rather than having become
# a stray `[[` that reads as the start of another link.
# `<small>` in a description message is the wikis' shared idiom for reference
# chrome rather than emphasis -- on frwiki every one of them wraps a bracketed
# "documentation" or "illustration" link. Its label survives link resolution and
# its target does not, so keeping the span leaves a catalogue description ending
# in "[documentation] [illustration]": words that pointed somewhere on a wiki and
# point nowhere here. The span goes, not just its tags.
_SMALL_SPAN_RE = re.compile(r"<small\b[^>]*>.*?</small\s*>", re.IGNORECASE | re.DOTALL)
_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
_WIKI_LINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]|]+)\]\]")
_EXTERNAL_LINK_RE = re.compile(r"\[(?:https?:|//)\S+(?:[ \t]+([^\]]*))?\]")
_HTML_TAG_RE = re.compile(r"<[^>]*>")
_QUOTES_RE = re.compile(r"'{2,5}")
# Removing a span leaves the space that separated it from the sentence sitting
# in front of the full stop. Only `.` and `,` are closed up: French spaces its
# `:`, `;`, `?`, `!` and `»` on purpose, and these messages are mostly not in
# English -- tidying those would be this catalogue correcting a wiki's own
# typography rather than reading it.
_ORPHAN_PUNCTUATION_RE = re.compile(r"\s+([.,])")


def plain_text(wikitext: str) -> str:
    """Reduce a wikitext interface message to prose a catalogue can publish.

    What survives is the sentence a reader of the gadget's preferences screen
    sees; what does not is the markup that got it there. A link keeps its label
    and loses its target, because the target is a page on one wiki and the
    label is the words the author chose. An unlabelled external link leaves
    nothing at all -- a bare URL in a description field is not a description.

    A `<small>` span goes entirely, contents included, for the reason given
    where the pattern is defined.

    Templates are dropped rather than expanded. The API is asked to expand them
    before they arrive, so anything still bracketed here is one the wiki itself
    could not resolve, and a template's name is not prose.

    Reduction only. Nothing here decides whether the result is worth
    publishing: an empty return means the message was markup all the way down,
    and it is the caller that reads that as no description.
    """
    text = str(wikitext or "")
    text = _SMALL_SPAN_RE.sub("", text)
    text = _TEMPLATE_RE.sub("", text)
    text = _WIKI_LINK_RE.sub(r"\1", text)
    text = _EXTERNAL_LINK_RE.sub(lambda match: match.group(1) or "", text)
    text = _HTML_TAG_RE.sub("", text)
    text = _QUOTES_RE.sub("", text)
    return _ORPHAN_PUNCTUATION_RE.sub(r"\1", " ".join(html.unescape(text).split()))
