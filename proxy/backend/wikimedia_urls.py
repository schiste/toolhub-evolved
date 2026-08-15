# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict parsing for public Wikimedia wiki and user-space URLs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

WIKIMEDIA_HOST_RE = re.compile(
    r"^(?:[a-z0-9-]+\.)*(?:wikipedia|wikimedia|wiktionary|wikibooks|wikinews|wikiquote|wikiversity|"
    r"wikivoyage|wikisource)\.org$|^(?:www\.)?wikidata\.org$|^species\.wikimedia\.org$"
)


@dataclass(frozen=True)
class WikimediaUserPage:
    """One user-owned page on a validated public Wikimedia wiki."""

    domain: str
    username: str
    title: str


def clean_wiki_domain(value: str) -> str:
    """Return a supported public Wikimedia domain or reject it."""
    domain = value.strip().casefold().rstrip(".")
    if not domain or not WIKIMEDIA_HOST_RE.fullmatch(domain):
        message = "destination must be a public Wikimedia wiki domain"
        raise ValueError(message)
    return domain


def normalized_username(value: str) -> str:
    """Normalize MediaWiki spelling without treating a display name as identity."""
    clean = " ".join(unquote(str(value or "")).replace("_", " ").split())
    prefix, separator, remainder = clean.partition(":")
    if separator and prefix.casefold() == "user":
        clean = remainder.strip()
    return clean.casefold()


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
