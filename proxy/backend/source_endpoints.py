# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure extraction of the network endpoints a tool's source addresses.

API_RULES next door answers "which API family is this", from client library
names and endpoint spellings. It cannot answer "and which host, and which
call", because a family is not an address: `mw.Api` says MediaWiki without
saying which wiki, and nothing in that table sees a service Wikimedia does not
run at all. This does the complementary job -- it reads literal URLs and
reports the host, the path, and for the query APIs the parameter that decides
what the call actually does.

Three rules govern what is kept, all of them about not storing things:

* No credentials, ever. Userinfo is dropped before the host is read, and query
  values survive only for an allowlist of parameters whose values are verbs
  (`action=edit`), never secrets. Every other key is discarded along with its
  value, unexamined -- an `?api_key=` in source is a finding for the warning
  scanner, not a fact for this one.
* No invented precision. A path segment that is a variable, an id, or a
  template hole becomes `{}`. `/user/12345/edits` and `/user/67890/edits` are
  one endpoint, and pretending otherwise would report a tool's user base as its
  API surface.
* No unbounded growth. One minified line can carry hundreds of URLs, so the
  count per line and the length of a path are capped, and an over-long
  authority is refused outright rather than cut to a prefix naming nothing.

Nothing here performs I/O or scores anything. How much to trust a hit is the
caller's decision, made from the file it came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from backend.wikimedia_urls import clean_wiki_domain

FAMILY_WIKIMEDIA = "wikimedia"
FAMILY_EXTERNAL = "external"

MAX_PER_LINE = 8
MAX_PATH_SEGMENTS = 6
MAX_PATH_CHARS = 120
MAX_HOST_CHARS = 120
MAX_ACTION_CHARS = 40

# Bounded on both ends: a scheme this project would actually speak, and a stop
# at the first character that cannot appear unescaped in a URL sitting inside
# source code. Excluding the braces means an interpolated URL such as
# `https://api.example.org/user/${id}/edits` is cut short at the hole rather
# than swallowing the template syntax -- the host and the first segments are
# still recovered, which is the part worth having.
#
# The pipe is allowed through despite being an operator in most of these
# languages, because MediaWiki joins multi-valued parameters with it and
# `prop=revisions|info` is exactly the kind of thing this exists to read. A
# real pipe operator is separated by whitespace, which ends the match anyway.
URL_RE = re.compile(r"https?://[^\s\"'`<>()\[\]{}\\^]+", re.IGNORECASE)

# Trailing punctuation belongs to the prose or the code around the URL, not to
# the URL: `see https://example.org/api.` and `fetch("https://x.org/api"),`.
TRAILING_PUNCTUATION = ".,;:!?'\"`)]}>"

# Wikimedia runs plenty that is not a wiki, and clean_wiki_domain deliberately
# knows only the content projects -- widening it would widen the set of hosts
# trusted for identity assertions. These are the surrounding hosts, which for
# the narrower question of first party versus third party count as inside.
WIKIMEDIA_OPS_RE = re.compile(
    r"(?:^|\.)(?:toolforge\.org|wmflabs\.org|wmcloud\.org|wikimedia\.cloud"
    r"|wikidata\.org|mediawiki\.org|wikifunctions\.org)$",
    re.IGNORECASE,
)

# Hosts that appear in source without anything ever connecting to them. Left in
# they would be the majority of findings, and every one of them false.
NEVER_AN_ENDPOINT = frozenset(
    {
        # Namespaces and schema identifiers. An xmlns is a name, not an address.
        "www.w3.org",
        "w3.org",
        "schema.org",
        "json-schema.org",
        "purl.org",
        "xmlns.com",
        "ns.adobe.com",
        # License and legal boilerplate, in a header on nearly every file.
        "www.gnu.org",
        "gnu.org",
        "opensource.org",
        "spdx.org",
        "creativecommons.org",
        "www.apache.org",
        # README furniture: badges and the services backing them.
        "img.shields.io",
        "shields.io",
        "badgen.net",
        "badge.fury.io",
        "travis-ci.org",
        "travis-ci.com",
        "codecov.io",
        "coveralls.io",
    }
)

# Authorities that stand in for a real one. A tool that genuinely talks to
# 127.0.0.1 is talking to itself, which is not an external service either.
# Hostnames with no dot at all -- `localhost`, a bare container name, the `::1`
# that urlsplit hands back unbracketed -- are refused before this is consulted.
PLACEHOLDER_RE = re.compile(
    r"^(?:127\.0\.0\.1|0\.0\.0\.0|(?:.+\.)?example\.(?:com|org|net))$"
    r"|\.(?:invalid|test|local|localdomain|internal|localhost)$",
    re.IGNORECASE,
)

# The query parameters worth keeping, because their values say what a request
# does rather than what it is about. MediaWiki's action API is the reason this
# exists at all: action=query and action=edit are the same path and utterly
# different trust profiles, so a path-only view would file a bot that rewrites
# articles alongside one that counts them.
ACTION_KEYS = frozenset({"action", "list", "prop", "generator", "meta"})

# Deliberately narrow: a lowercase word, or several joined by MediaWiki's pipe
# (`prop=revisions|info`). A value that is not shaped like a verb is not one,
# and is dropped rather than guessed at.
ACTION_VALUE_RE = re.compile(rf"^[a-z][a-z0-9|_-]{{0,{MAX_ACTION_CHARS}}}$", re.IGNORECASE)

# A path segment carrying data rather than naming a route: a template hole the
# language left behind (`$`, `%s`, `*`), a bare number, or a long hex blob.
VARIABLE_SEGMENT_RE = re.compile(r"[$%*+~]|^\d+$|^[0-9a-f]{8,}$", re.IGNORECASE)


@dataclass(frozen=True)
class Endpoint:
    """One address a tool's source names, at the precision worth storing."""

    host: str
    path: str
    action: str
    family: str

    @property
    def value(self) -> str:
        """Return the stable identity of this endpoint, for deduplication."""
        return f"{self.host}{self.path}" + (f"?{self.action}" if self.action else "")

    @property
    def label(self) -> str:
        """Return the spelling shown to a reader of the report."""
        return f"{self.host} {self.path}" + (f" ({self.action})" if self.action else "")


def family(host: str) -> str:
    """Report whether `host` is inside the Wikimedia estate or outside it."""
    try:
        clean_wiki_domain(host)
    except ValueError:
        return FAMILY_WIKIMEDIA if WIKIMEDIA_OPS_RE.search(host) else FAMILY_EXTERNAL
    return FAMILY_WIKIMEDIA


def _host(parsed: object) -> str:
    """Return the lowercased hostname, or "" for anything not worth recording.

    Reads `hostname` rather than `netloc` on purpose: that property has already
    dropped any `user:password@` prefix and the port, so a credential pasted
    into a URL cannot reach the returned string even by accident.

    An over-long authority is refused rather than truncated. Cutting a hostname
    at a fixed width lands mid-label and invents a name that resolves nowhere,
    which is worse than not reporting it.
    """
    host = str(getattr(parsed, "hostname", "") or "").lower()
    if "." not in host or len(host) > MAX_HOST_CHARS:
        return ""
    if host in NEVER_AN_ENDPOINT or PLACEHOLDER_RE.search(host):
        return ""
    return host


def _segment(value: str) -> str:
    """Return one path segment, or `{}` when it holds data rather than a route."""
    return "{}" if VARIABLE_SEGMENT_RE.search(value) else value


def _path(raw: str) -> str:
    """Return the request path, templated, bounded, and always rooted at /."""
    segments = [segment for segment in raw.split("/") if segment][:MAX_PATH_SEGMENTS]
    return f"/{'/'.join(_segment(segment) for segment in segments)}"[:MAX_PATH_CHARS]


def _actions(query: str) -> tuple[str, ...]:
    """Return the allowlisted `key=value` pairs of a query string, in order.

    Only these keys, and only values shaped like the verbs they are meant to
    be. Everything else is dropped -- which is what keeps a token in a query
    string from reaching a stored finding, since the rejection happens on the
    key before the value is looked at.
    """
    found: list[str] = []
    for key, value in parse_qsl(query, keep_blank_values=False):
        if key.strip().lower() not in ACTION_KEYS:
            continue
        clean = value.strip().lower()
        pair = f"{key.strip().lower()}={clean}"
        if ACTION_VALUE_RE.match(clean) and pair not in found:
            found.append(pair)
    return tuple(found)


def endpoints(line: str) -> tuple[Endpoint, ...]:
    """Return every endpoint one line of source addresses, in order of first sight.

    A URL with no recognized action yields one endpoint for its path. A URL
    carrying them yields one per action *instead* of the bare path: the path is
    still readable inside each value, so emitting both would spend the caller's
    finding budget twice on the same fact.
    """
    found: list[Endpoint] = []
    for match in URL_RE.finditer(str(line or "")):
        parsed = urlsplit(match.group(0).rstrip(TRAILING_PUNCTUATION))
        host = _host(parsed)
        if not host:
            continue
        path, group = _path(parsed.path), family(host)
        for action in _actions(parsed.query) or ("",):
            endpoint = Endpoint(host=host, path=path, action=action, family=group)
            if endpoint not in found:
                found.append(endpoint)
        if len(found) >= MAX_PER_LINE:
            break
    return tuple(found[:MAX_PER_LINE])
