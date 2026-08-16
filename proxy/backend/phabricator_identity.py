# SPDX-License-Identifier: GPL-3.0-or-later
"""Read public Phabricator profiles to recover the real name behind a handle.

Toolsadmin writes a maintainer's Phabricator *real name* into the toolinfo
``author`` field, while its own maintainer table renders the LDAP ``cn``. The
two were seeded from each other once and have drifted since, so a catalog
author reads ``Gopa Vasanth`` while every handle this project holds for the
same person reads ``Gopavasanth``. Neither value is a wiki username, and no
structured field carries the link, which is why those labels never resolve.

Phabricator publishes the missing edge anonymously: ``/p/<username>/`` renders
``Username (Real Name)`` in its profile header. Only that direction is public
-- the people directory and the Conduit API both require a session -- and this
module deliberately uses only that direction. A real name is never a search
key here; it is only ever read back from a handle this project already holds,
so a common name cannot pull in a stranger who happens to share it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import quote

import requests

from backend import toolhub

PHABRICATOR_BASE_URL = "https://phabricator.wikimedia.org"
PHABRICATOR_TIMEOUT = 10
HTTP_OK = 200
HTTP_NOT_FOUND = 404
MAX_USERNAME = 255
MAX_REAL_NAME = 255
# Phabricator usernames are ASCII word characters, dots and hyphens. Rejecting
# everything else keeps a catalog label from being pasted into a profile URL.
USERNAME_PATTERN = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")
# The profile header is the only element that carries both halves of the pair.
_HEADER_PATTERN = re.compile(r'phui-header-header"[^>]*>(.*?)</span>', re.DOTALL)
_TAG_PATTERN = re.compile(r"<[^>]+>")
_HEADER_PAIR_PATTERN = re.compile(r"\A(?P<username>[^()]+?)\s*\((?P<real_name>.+)\)\Z", re.DOTALL)


class PhabricatorProfileError(RuntimeError):
    """Raised when a profile read cannot be trusted."""


@dataclass(frozen=True)
class PhabricatorProfile:
    """One public Phabricator identity pair."""

    username: str
    real_name: str


def is_probable_username(value: str) -> bool:
    """Return True when a value is safe to request as a profile handle."""
    return bool(USERNAME_PATTERN.match(str(value or "").strip()))


def _text(fragment: str) -> str:
    return " ".join(unescape(_TAG_PATTERN.sub(" ", fragment)).split())


def parse_profile(html: str) -> PhabricatorProfile | None:
    """Return the username/real-name pair a profile header declares.

    A profile whose header carries the username alone means the account left
    its real name unset, which is not a failure and not a usable pair, so it
    returns ``None`` exactly like an unparseable page. Callers cannot act on
    the difference and treating them alike keeps one absent-value path.
    """
    match = _HEADER_PATTERN.search(str(html or ""))
    if match is None:
        return None
    header = _text(match.group(1))
    pair = _HEADER_PAIR_PATTERN.match(header)
    if pair is None:
        return None
    username = pair.group("username").strip()[:MAX_USERNAME]
    real_name = " ".join(pair.group("real_name").split())[:MAX_REAL_NAME]
    if not username or not real_name or not is_probable_username(username):
        return None
    return PhabricatorProfile(username=username, real_name=real_name)


class PhabricatorProfileProvider:
    """Fetch one public profile at a time from the bounded candidate set."""

    def __init__(self, *, base_url: str = PHABRICATOR_BASE_URL, fetcher: object | None = None) -> None:
        """Store the public Phabricator base URL and optional test fetcher."""
        self.base_url = base_url.rstrip("/")
        self.fetcher = fetcher or self._fetch

    def evidence_url(self, username: str) -> str:
        """Return the public profile URL recorded as evidence."""
        return f"{self.base_url}/p/{quote(str(username or '').strip(), safe='')}/"

    def lookup(self, username: str) -> PhabricatorProfile | None:
        """Return the profile pair for one handle, or None when unknown.

        A missing profile and a profile without a real name are both ordinary
        outcomes for a handle guessed from LDAP, so only a transport failure
        or an unexpected status raises. That keeps a Phabricator outage from
        being recorded as "this person has no real name".
        """
        handle = str(username or "").strip()
        if not is_probable_username(handle):
            return None
        try:
            status, body = self.fetcher(handle)
        except requests.RequestException as error:
            raise PhabricatorProfileError(str(error)) from error
        if status == HTTP_NOT_FOUND:
            return None
        if status != HTTP_OK:
            message = f"Phabricator profile read returned HTTP {status}"
            raise PhabricatorProfileError(message)
        profile = parse_profile(body)
        # Phabricator canonicalizes handle case in the header, so a candidate
        # that lands on a different account is a redirect, not a match.
        if profile is None or profile.username.casefold() != handle.casefold():
            return None
        return profile

    def _fetch(self, username: str) -> tuple[int, str]:
        response = requests.get(
            self.evidence_url(username),
            headers={"User-Agent": toolhub.USER_AGENT, "Accept": "text/html"},
            timeout=PHABRICATOR_TIMEOUT,
        )
        return response.status_code, response.text
