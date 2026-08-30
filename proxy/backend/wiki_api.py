# SPDX-License-Identifier: GPL-3.0-or-later
"""Ask a MediaWiki for the source of a gadget or user script, and read the answer.

Pure: this builds query URLs and parses response payloads, and performs no I/O.

Two things push this onto the Action API rather than the REST one source_hosts
uses. Only the Action API can *discover* a page set -- generator=allpages for a
user script, the Gadgets-definition page for a gadget -- and only it can return
the content of many pages in a single request. That second property is the
whole point: a user script and all its subpages cost one request, a gadget and
all its files cost two, and a scan pass over the catalogue therefore costs a
number of requests in the low hundreds rather than one per page.

Content and revision ids arrive together on purpose. The head of a wiki page
set can only be known once its members are known, so there is no cheap
equivalent of `git ls-remote` to check first; fetching everything and comparing
afterwards is both simpler and, at one or two requests, cheaper than resolving
the set twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from urllib.parse import urlencode, urlparse

from backend import wiki_sources

ACTION_API_PATH = "/w/api.php"

# Sent on every query. maxlag lets the wiki shed us first when its replicas
# fall behind, which is the documented way for a background reader to be a good
# citizen -- it answers with an error rather than serving a slow request, and
# that error is a reason to come back later, not a failure of the tool.
MAXLAG_SECONDS = 5
BASE_PARAMS = {
    "action": "query",
    "format": "json",
    "formatversion": "2",
    "maxlag": str(MAXLAG_SECONDS),
}

# Revision content lives in a slot; asking for it without naming the slot
# returns a deprecation warning and no text.
REVISION_PARAMS = {"prop": "revisions", "rvprop": "ids|timestamp|content", "rvslots": "main"}

# What a definition page is asked for. The id is not wanted and is not read;
# it is requested because a revision without one is dropped by the parser.
DEFINITION_REVISION_PARAMS = {"prop": "revisions", "rvprop": "ids|content", "rvslots": "main"}

MAX_CONTENT_CHARS = 2 * 1024 * 1024


@dataclass(frozen=True)
class Revision:
    """The latest revision of one wiki page: what it says and when it said it."""

    title: str
    revision_id: int
    edited_at: str
    content: str


def _api_url(domain: str, params: dict[str, str]) -> str:
    return f"https://{domain}{ACTION_API_PATH}?{urlencode({**BASE_PARAMS, **params})}"


def definition_url(domain: str) -> str:
    """Return the query for a wiki's gadget definitions.

    Asks for the revision id even though no caller wants it, because
    `_revision` discards any revision that arrives without one. Keeping the
    definition page out of tool heads is `definition_text`'s job -- it returns
    wikitext and nothing else, so there is no id here for a head to pick up.
    """
    return _api_url(
        domain,
        {**DEFINITION_REVISION_PARAMS, "titles": wiki_sources.GADGET_DEFINITION_TITLE},
    )


# Everything a title's leading `X:` can mean on one wiki, in one request.
# `namespaces` carries the localized name and the canonical one; `namespacealiases`
# carries the rest, including spellings kept for backwards compatibility after a
# rename. Both are needed: neither is a superset of the other. `interwikimap`
# carries the prefixes that name a *different* wiki, which is the other thing a
# title can start with and the reason all three are read together.
SITEINFO_PARAMS = {"meta": "siteinfo", "siprop": "namespaces|namespacealiases|interwikimap"}

USER_NAMESPACE_ID = 2

# An interwiki URL is a template with the title substituted in. Only the host is
# kept, so the placeholder is never expanded -- the census addresses a page by
# wiki and title, not by following somebody's link.
INTERWIKI_PLACEHOLDER = "$1"

# A bound on one wiki's interwiki map, which is large by nature -- enwiki lists
# 781 prefixes. High enough that no real map is truncated, low enough that a
# malformed answer cannot fill the column.
MAX_INTERWIKI_PREFIXES = 4000


def siteinfo_url(domain: str) -> str:
    """Return the query for a wiki's namespace names, aliases, and interwiki map."""
    return _api_url(domain, SITEINFO_PARAMS)


def pages_url(domain: str, titles: tuple[str, ...]) -> str:
    """Return the query for the current revision of each named page."""
    return _api_url(domain, {**REVISION_PARAMS, "titles": "|".join(titles[: wiki_sources.MAX_PAGES])})


def subpages_url(domain: str, namespace_id: int, prefix: str) -> str:
    """Return the query that finds a user script's pages and reads them at once.

    A generator is what collapses discovery and fetching into one request: the
    prefix search feeds its results straight into the revision fetch, so the
    listing never has to come back here to be turned into a second query.
    """
    return _api_url(
        domain,
        {
            **REVISION_PARAMS,
            "generator": "allpages",
            "gapnamespace": str(namespace_id),
            "gapprefix": prefix,
            "gaplimit": str(wiki_sources.MAX_PAGES),
        },
    )


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def api_error(payload: object) -> str:
    """Return the error code the wiki answered with, or "" if it answered normally.

    An Action API error arrives as HTTP 200 with an error object in the body,
    so a caller that only checks the status reads a failure as an empty result
    -- which for this lane would mean recording a tool as having no source.
    """
    return str(_object(_object(payload).get("error")).get("code") or "")[:64]


def _pages(payload: object) -> list[dict[str, Any]]:
    raw = _object(_object(payload).get("query")).get("pages")
    return [page for page in raw if isinstance(page, dict)] if isinstance(raw, list) else []


def _revision(page: dict[str, Any]) -> Revision | None:
    revisions = page.get("revisions")
    title = str(page.get("title") or "")
    if not title or not isinstance(revisions, list) or not revisions:
        # A title the wiki has no page for comes back with missing: true and no
        # revisions. That is an answer, not an error: a gadget definition can
        # name a file nobody ever created.
        return None
    latest = _object(revisions[0])
    revision_id = latest.get("revid")
    content = _object(_object(latest.get("slots")).get("main")).get("content")
    if not isinstance(revision_id, int) or isinstance(revision_id, bool) or not isinstance(content, str):
        return None
    return Revision(
        title=title,
        revision_id=revision_id,
        edited_at=str(latest.get("timestamp") or "")[:64],
        content=content[:MAX_CONTENT_CHARS],
    )


def revisions(payload: object) -> tuple[Revision, ...]:
    """Return the latest revision of every page the query actually found.

    Ordered by title so that the head derived from these is stable: the API
    returns pages in whatever order its indexes produce, and a set that hashed
    differently on each poll would rescan the tool forever.
    """
    found = [revision for page in _pages(payload) if (revision := _revision(page)) is not None]
    return tuple(sorted(found, key=lambda revision: revision.title))


def definition_text(payload: object) -> str:
    """Return the wikitext of the single page a definition query asked for."""
    found = revisions(payload)
    return found[0].content if found else ""


def messages(payload: object) -> dict[str, str]:
    """Return the interface messages a query answered with, keyed by name.

    A message the wiki never wrote comes back flagged `missing` and carrying no
    content, and is dropped here rather than kept as an empty string: "the wiki
    says nothing about this gadget" and "the wiki says this gadget does nothing"
    are different facts, and only the first is true.
    """
    query = _object(_object(payload).get("query"))
    found: dict[str, str] = {}
    for item in query.get("allmessages") or []:
        entry = _object(item)
        name = str(entry.get("name") or "")
        content = entry.get("content")
        # `missing` is `true` under formatversion 2 and `""` under 1, so its
        # presence is the test rather than its truth.
        if not name or entry.get("missing") is not None or not isinstance(content, str):
            continue
        if content.strip():
            found[name] = content
    return found


def head(found: tuple[Revision, ...]) -> str:
    """Return one identifier for the state of a whole page set.

    The equivalent of a commit sha, and it has to cover the set rather than the
    entry page: a gadget whose main file is untouched but whose helper was
    rewritten has changed, and a head that only tracked the page we were
    pointed at would never rescan it.
    """
    fingerprint = "\n".join(f"{revision.title}@{revision.revision_id}" for revision in found)
    return sha256(fingerprint.encode("utf-8")).hexdigest()


def last_edited_at(found: tuple[Revision, ...]) -> str:
    """Return the most recent edit timestamp across the set, or "" if none is known."""
    return max((revision.edited_at for revision in found if revision.edited_at), default="")


def user_namespace_spellings(payload: object) -> tuple[str, ...]:
    """Return every name a siteinfo payload says namespace 2 answers to.

    The canonical name comes first and the rest follow in the order the wiki
    listed them, because the first spelling is the one worth showing a reader
    when the census has to name the namespace itself.

    A payload missing the namespace entirely returns nothing rather than
    guessing `User`. The caller already has a built-in fallback; inventing a
    spelling here would make an unreadable wiki indistinguishable from one that
    genuinely answers to nothing else.
    """
    query = _object(_object(payload).get("query"))
    namespace = _object(_object(query.get("namespaces")).get(str(USER_NAMESPACE_ID)))
    listed = [namespace.get("canonical"), namespace.get("name")]
    aliases = query.get("namespacealiases")
    if isinstance(aliases, list):
        listed += [_object(alias).get("alias") for alias in aliases if _object(alias).get("id") == USER_NAMESPACE_ID]
    found: list[str] = []
    for spelling in listed:
        text = str(spelling or "").strip()
        # Compared casefolded because that is how the fold matches them, and a
        # wiki that lists `User` as both canonical name and alias is one name.
        if text and text.casefold() not in {seen.casefold() for seen in found}:
            found.append(text)
    return tuple(found)


def _namespace_names(query: dict[str, Any]) -> set[str]:
    """Every name and alias this wiki uses for any namespace, casefolded."""
    found: set[str] = set()
    namespaces = _object(query.get("namespaces"))
    for entry in namespaces.values():
        listed = _object(entry)
        for key in ("canonical", "name"):
            if str(listed.get(key) or "").strip():
                found.add(str(listed[key]).strip().casefold())
    aliases = query.get("namespacealiases")
    if isinstance(aliases, list):
        for alias in aliases:
            spelling = str(_object(alias).get("alias") or "").strip()
            if spelling:
                found.add(spelling.casefold())
    return found


def interwiki_hosts(payload: object) -> dict[str, str]:
    """Return the wiki each interwiki prefix names, keyed by the casefolded prefix.

    Prefixes that are also namespace names on this wiki are dropped, because
    MediaWiki resolves a namespace before an interwiki and so must this. The
    collision is not hypothetical: `wikipedia:` on enwiki is both the Wikipedia
    namespace and an interwiki prefix pointing back at enwiki, and 3,736 census
    edges start with it. Reading those as interwiki would move every one of them
    to a title with the namespace stripped off -- and would look like progress,
    because their target wiki would stop being blank.

    Filtering here rather than at parse time is deliberate: this is the one
    place that holds the namespace list and the interwiki map at the same time,
    so what gets stored is already safe to use without them.
    """
    query = _object(_object(payload).get("query"))
    entries = query.get("interwikimap")
    if not isinstance(entries, list):
        return {}
    reserved = _namespace_names(query)
    hosts: dict[str, str] = {}
    for entry in entries[:MAX_INTERWIKI_PREFIXES]:
        listed = _object(entry)
        prefix = str(listed.get("prefix") or "").strip().casefold()
        host = urlparse(str(listed.get("url") or "").replace(INTERWIKI_PLACEHOLDER, "")).netloc.lower()
        if prefix and host and prefix not in reserved:
            hosts[prefix] = host
    return hosts
