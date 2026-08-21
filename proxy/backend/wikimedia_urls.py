# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict parsing for public Wikimedia wiki and user-space URLs."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

# Two shapes of Wikimedia project. The first alternative covers the ones that
# exist once per language and are addressed by subdomain (en.wikipedia.org,
# commons.wikimedia.org). The second covers the ones that exist exactly once:
# they are pinned to their own host with an optional www rather than folded
# into the subdomain alternative, because they have no per-language siblings
# and accepting *.mediawiki.org would widen the trusted set for nothing.
WIKIMEDIA_HOST_RE = re.compile(
    r"^(?:[a-z0-9-]+\.)*(?:wikipedia|wikimedia|wiktionary|wikibooks|wikinews|wikiquote|wikiversity|"
    r"wikivoyage|wikisource)\.org$|^(?:www\.)?(?:wikidata|mediawiki|wikifunctions)\.org$"
    r"|^species\.wikimedia\.org$"
)


@dataclass(frozen=True)
class WikimediaUserPage:
    """One user-owned page on a validated public Wikimedia wiki."""

    domain: str
    username: str
    title: str


def without_format_marks(text: str) -> str:
    """Drop invisible formatting marks so Python agrees with storage about sameness.

    A stray left-to-right mark is invisible in the editor that produced it and
    ignorable to the database collation, so two spellings that differ only by
    one are a single row to MySQL while staying two distinct strings to Python.
    Every unique key built out of a wiki title assumes those two notions of
    equality agree -- and the tests, which run on SQLite, compare bytes and so
    never catch a place where they do not.

    A Meta `global.js` is the page that proved they diverge: it loads
    `User:Hoo man/tagger.js` twice, once with a trailing U+200E left over from
    a copied link, and the census offered both spellings to one INSERT.

    Dropping them is also the answer demand wants. A script reached through an
    invisible character is the same script, and counting it separately would
    split its demand across a mark nobody can see.
    """
    # No ASCII character is in category Cf, and almost every title is ASCII.
    if text.isascii():
        return text
    return "".join(character for character in text if unicodedata.category(character) != "Cf")


def clean_wiki_domain(value: str) -> str:
    """Return a supported public Wikimedia domain or reject it.

    "Supported" means Wikimedia-operated, which is what makes a `User:` page
    there an identity assertion: the account is the same global SUL account it
    would be on any other project. Everything downstream leans on that --
    attestations, user reconciliation, digest delivery and source scanning all
    gate on this one pattern.
    """
    domain = value.strip().casefold().rstrip(".")
    if not domain or not WIKIMEDIA_HOST_RE.fullmatch(domain):
        message = "destination must be a public Wikimedia wiki domain"
        raise ValueError(message)
    return domain


def canonical_username(value: str) -> str:
    """Return one MediaWiki spelling of a username, preserving case.

    Underscores and spaces are interchangeable in MediaWiki titles, and a name
    copied out of a URL carries underscores while the API always answers with
    spaces. Case is left alone: MediaWiki capitalizes only the first letter, so
    `Foo Bar` and `Foo bar` are two different accounts and folding them
    together would be unsound wherever this is used as an identity assertion.
    """
    clean = " ".join(unquote(str(value or "")).replace("_", " ").split())
    prefix, separator, remainder = clean.partition(":")
    if separator and prefix.casefold() == "user":
        clean = remainder.strip()
    return clean


def normalized_username(value: str) -> str:
    """Normalize MediaWiki spelling without treating a display name as identity."""
    return canonical_username(value).casefold()


def _user_title(value: str) -> tuple[str, str] | None:
    title = " ".join(unquote(value or "").split())
    prefix, separator, remainder = title.partition(":")
    if not separator or prefix.casefold() != "user":
        return None
    username = remainder.split("/", 1)[0].strip()
    return (username, title) if username else None


def user_space_page(url: str) -> WikimediaUserPage | None:
    """Parse a canonical ``User:`` page only on a real Wikimedia project."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme.casefold() not in {"http", "https"} or parsed.username or parsed.password:
        return None
    try:
        domain = clean_wiki_domain(parsed.hostname or "")
        port = parsed.port
    except (ValueError, TypeError):
        return None
    expected_port = 443 if parsed.scheme.casefold() == "https" else 80
    if port not in {None, expected_port}:
        return None

    candidates: list[str] = []
    path = unquote(parsed.path)
    if "/wiki/" in path:
        candidates.append(path.split("/wiki/", 1)[1])
    candidates.extend(parse_qs(parsed.query).get("title", []))
    for candidate in candidates:
        if parsed_title := _user_title(candidate):
            username, title = parsed_title
            return WikimediaUserPage(domain=domain, username=username, title=title)
    return None


def user_space_javascript_page(url: str) -> WikimediaUserPage | None:
    """Return a validated user-space page only when the title is JavaScript."""
    page = user_space_page(url)
    return page if page is not None and page.title.casefold().endswith(".js") else None
