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
from urllib.parse import urlencode

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


# What a wiki calls namespace 2, and everything else it answers to for it.
# `namespaces` carries the localized name and the canonical one; `namespacealiases`
# carries the rest, including spellings kept for backwards compatibility after a
# rename. Both are needed: neither is a superset of the other.
SITEINFO_PARAMS = {"meta": "siteinfo", "siprop": "namespaces|namespacealiases"}

USER_NAMESPACE_ID = 2


def siteinfo_url(domain: str) -> str:
    """Return the query for a wiki's namespace names and aliases."""
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
