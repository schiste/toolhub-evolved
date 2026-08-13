# SPDX-License-Identifier: GPL-3.0-or-later
"""Normalize Toolhub/toolinfo author values into independent assertions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

LEGACY_AUTHOR_SEPARATOR = re.compile(r"\s*[,;]\s*")
MIN_MULTI_AUTHOR_PARTS = 2


@dataclass(frozen=True)
class AuthorAssertion:
    """One author edge extracted from a possibly multi-author field."""

    display_name: str
    developer_username: str = ""
    wiki_username: str = ""
    raw_value: str = ""
    position: int = 0
    legacy_delimited: bool = False

    @property
    def normalized_label(self) -> str:
        """Return the source-local comparison key for this assertion."""
        return self.display_name.casefold()


def _clean(value: Any, limit: int = 255) -> str:  # noqa: ANN401 - external JSON
    return " ".join(str(value or "").split()).strip()[:limit]


def _legacy_string_assertions(value: str, position: int) -> list[AuthorAssertion]:
    """Split legacy delimiter syntax while retaining its lower-trust origin.

    Toolinfo 1.2 models multiple authors as an array. Older feeds sometimes
    placed several authors in one scalar. Those tokens are useful independent
    assertions, but the parser flag prevents delimiter syntax from becoming
    identity proof by itself.
    """
    raw = _clean(value)
    parts = [_clean(part) for part in LEGACY_AUTHOR_SEPARATOR.split(raw)]
    parts = [part for part in parts if part]
    # A two-token ``Surname, Given`` value is indistinguishable from two
    # one-word handles. Keep it intact unless a semicolon or multi-word token
    # makes the legacy multi-author intent observable. Publishers can remove
    # all ambiguity by using the schema's author array.
    looks_multi_author = ";" in raw or len(parts) > MIN_MULTI_AUTHOR_PARTS or any(" " in part for part in parts)
    if len(parts) < MIN_MULTI_AUTHOR_PARTS or not looks_multi_author:
        return [AuthorAssertion(display_name=raw, raw_value=raw, position=position)] if raw else []
    return [
        AuthorAssertion(
            display_name=part,
            raw_value=raw,
            position=position + offset,
            legacy_delimited=True,
        )
        for offset, part in enumerate(parts)
    ]


def author_assertions(payload: dict[str, Any]) -> list[AuthorAssertion]:
    """Return every author as a separate, deterministically ordered assertion."""
    raw_authors = payload.get("author")
    authors = raw_authors if isinstance(raw_authors, list) else [raw_authors]
    assertions: list[AuthorAssertion] = []
    for author_index, author in enumerate(authors):
        position = author_index * 100
        if isinstance(author, dict):
            developer = _clean(author.get("developer_username"))
            wiki = _clean(author.get("wiki_username"))
            display = _clean(author.get("name") or developer or wiki)
            if display:
                assertions.append(
                    AuthorAssertion(
                        display_name=display,
                        developer_username=developer,
                        wiki_username=wiki,
                        raw_value=display,
                        position=position,
                    )
                )
        elif isinstance(author, str | int | float):
            assertions.extend(_legacy_string_assertions(str(author), position))
    seen: set[tuple[str, str, str]] = set()
    deduped: list[AuthorAssertion] = []
    for assertion in assertions:
        key = (
            assertion.normalized_label,
            assertion.developer_username.casefold(),
            assertion.wiki_username.casefold(),
        )
        if assertion.display_name and key not in seen:
            seen.add(key)
            deduped.append(assertion)
    return deduped


def author_names(payload: dict[str, Any]) -> list[str]:
    """Return all independent display/identity labels in first-seen order."""
    values: list[str] = []
    for assertion in author_assertions(payload):
        values.extend(
            value
            for value in (assertion.display_name, assertion.wiki_username, assertion.developer_username)
            if value
        )
    return list(dict.fromkeys(values))
