# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure extraction of the network endpoints a tool's source addresses.

API_RULES next door answers "which API family is this", from client library
names and endpoint spellings. It cannot answer "and which host, and which
call", because a family is not an address: `mw.Api` says MediaWiki without
saying which wiki, and nothing in that table sees a service Wikimedia does not
run at all. This does the complementary job -- it reads literal URLs and
reports the host, the path, and for the query APIs the parameter that decides
what the call actually does.

Four rules govern what is kept, all of them about not storing things:

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
* Nothing but endpoints. Source names far more addresses than it calls: wiki
  pages, repository browse URLs, the blog post behind a workaround, the manual
  for a setting, the icons an interface is decorated with. Measured across nine
  real repositories those were a quarter of every hit, and on two of them they
  filled the cap and pushed the tool's actual API surface out of the report.
  They are dropped rather than filed alongside it.

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
# The pipe and the question mark end a path. A pipe there is almost always a
# link label from the surrounding markup -- `[https://momentjs.com/|moment.js]`
# and Phabricator's `T247721|T247721` both parsed as part of the address until
# it was narrowed.
_PATH_CHAR = r"[^\s\"'`<>()\[\]{}\\^|?]"

# Inside the query both are ordinary and dropping them is expensive. MediaWiki
# joins multi-valued parameters with a pipe (`prop=revisions|info`), which is
# exactly what this exists to read, and JSONP spells its callback `callback=?`
# -- ending the address there costs every parameter after it, which on
# QuickStatements meant losing the `action=query` from a call it makes.
_QUERY_CHAR = r"[^\s\"'`<>()\[\]{}\\^]"


def _bracketed(char: str) -> str:
    """Return a pattern for one balanced pair of parentheses.

    A parenthesis is punctuation around an address far more often than it is
    part of one, so on its own it ends the match. A balanced pair is how the
    Commons file namespace spells a disambiguated title, and without the
    carve-out `Pliers_with_yellow_handles_(rotated).svg` ends at the bracket and
    the report gains a route named for the first half of a file name.
    """
    return rf"\({char}*\)"


URL_RE = re.compile(
    rf"https?://(?:{_bracketed(_PATH_CHAR)}|{_PATH_CHAR})*"
    rf"(?:\?(?:{_bracketed(_QUERY_CHAR)}|{_QUERY_CHAR})*)?",
    re.IGNORECASE,
)

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
        # Every Android layout file opens by declaring these, and nothing
        # anywhere resolves them. In apps-android-commons the first one was
        # the single highest-confidence endpoint in the whole report.
        "schemas.android.com",
        "schemas.microsoft.com",
        "www.opengis.net",
        "opengis.net",
        "wikiba.se",
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
        "app.codacy.com",
        "uploader.codecov.io",
        # Avatar services. A picture of a contributor is not something the tool
        # calls, and a README that thanks its contributors names one per person.
        "avatars.githubusercontent.com",
        "secure.gravatar.com",
        "www.gravatar.com",
    }
)

# What a hostname can be made of. Requiring real labels is what keeps a regex
# literal out of the report: `r"http://.*?object=tx"` in pywikibot/fixes.py was
# read as the host `.*`, which passed every check below because it contains a
# dot. Underscores are refused along with everything else DNS does not allow.
HOSTNAME_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(?:\.(?!-)[a-z0-9-]{1,63}(?<!-))+$", re.IGNORECASE)

# Authorities that stand in for a real one. A tool that genuinely talks to
# 127.0.0.1 is talking to itself, which is not an external service either.
# Hostnames with no dot at all -- `localhost`, a bare container name, the `::1`
# that urlsplit hands back unbracketed -- are refused before this is consulted.
PLACEHOLDER_RE = re.compile(
    r"^(?:127\.0\.0\.1|0\.0\.0\.0|(?:.+\.)?example\.(?:com|org|net))$"
    r"|\.(?:invalid|test|local|localdomain|internal|localhost)$",
    re.IGNORECASE,
)

# A forge is a website first and a file server second. Nearly every repository
# names its own project page, its issue tracker, and half a dozen neighbors it
# borrowed code from, none of which anything connects to. The paths that are
# genuine fetches are few and well known, so those are carved back out below.
FORGE_HOST_RE = re.compile(
    r"^(?:www\.|help\.|docs\.|gist\.)?(?:github\.com|gitlab\.com|bitbucket\.org"
    r"|sourceforge\.net|codeberg\.org)$"
    r"|^(?:gerrit|phabricator|gitlab|diffusion)\.wikimedia\.org$"
    # The forge's own static hosting. A project page there is the README with
    # a stylesheet on it, and the product serves nothing else.
    r"|\.(?:github|gitlab)\.io$",
    re.IGNORECASE,
)

# The exception: a release asset or a raw blob is a real download, reached with
# wget in a Dockerfile as often as not. Hosts that serve only raw content --
# raw.githubusercontent.com and its kind -- never match FORGE_HOST_RE at all and
# so never need rescuing here.
FORGE_FETCH_RE = re.compile(r"^/(?:.+/)?(?:releases/download|archive|raw)/", re.IGNORECASE)

# Hosts that exist to be read rather than called. The leading subdomains say so
# outright, and the rest are the question-and-answer and mailing-list sites that
# turn up in a comment above the line that needed explaining.
#
# The known cost is `docs.` on a host that also serves data -- a published
# spreadsheet under docs.google.com is a real fetch and will be dropped. That
# has not appeared yet, and inventing an exemption for it now would be guessing.
REFERENCE_HOST_RE = re.compile(
    r"^(?:docs?|blog|help|wiki|lists|discourse|groups|developer|bugzilla)\."
    r"|(?:^|\.)(?:stackoverflow\.com|stackexchange\.com|serverfault\.com"
    r"|superuser\.com|askubuntu\.com|openhub\.net|fsf\.org|readthedocs\.io"
    r"|readthedocs\.org|medium\.com|blogspot\.com|w3\.org|datatracker\.ietf\.org"
    r"|rfc-editor\.org"
    # A package's own page on a registry. What the tool actually depends on is
    # already the dependencies bucket's answer; this is the human-readable
    # version of it, linked from a comment saying where to get the thing.
    r"|pypi\.org|npmjs\.com|packagist\.org|crates\.io|rubygems\.org"
    # An app store listing, and the vendor pages that go with one.
    r"|play\.google\.com|apps\.apple\.com|f-droid\.org|policies\.google\.com"
    r"|support\.google\.com)$",
    re.IGNORECASE,
)

# A shortened link cannot be reported as an endpoint even in principle: the
# address names a redirect service, and the service it actually reaches is not
# in the source at all. Resolving one would mean a network call, which this
# module does not make.
SHORTENER_RE = re.compile(
    r"^(?:git\.io|bit\.ly|goo\.gl|t\.co|tinyurl\.com|ow\.ly|is\.gd|buff\.ly|w\.wiki)$",
    re.IGNORECASE,
)

# What is left of `https://` after urlsplit has normalized the double slash
# away, sitting as a path segment of its own.
EMBEDDED_SCHEME_RE = re.compile(r"^https?:$", re.IGNORECASE)

# A file served to be looked at, not a service answering a request. Keyed on the
# extension because the host does not say: upload.wikimedia.org serves the
# thumbnails an interface decorates itself with from the same name as the media
# a tool uploads. On x-tools/xtools these icons were fifteen of twenty-four
# findings and the whole top of the report by confidence.
STATIC_ASSET_RE = re.compile(
    r"\.(?:png|jpe?g|gif|svg|webp|ico|bmp|tiff?|css|woff2?|ttf|eot|otf)$",
    re.IGNORECASE,
)

# A documentation tree, on a host whose name gives no hint of one. Vendors put
# their manuals on the product domain -- symfony.com/doc, www.php.net/manual,
# graphviz.org/docs -- and a comment citing the page that explains a setting is
# the single most common URL in source after the license header.
DOC_PATH_RE = re.compile(r"^/(?:docs?|manual|handbook|tutorials?)(?:/|$)", re.IGNORECASE)

# MediaWiki's article path. `/wiki/Help:Contents` is a page a human reads, and a
# tool that genuinely wants that content asks /w/api.php for it instead -- which
# is why this can key on the path alone and stay true on every wiki, including
# the ones outside the estate.
WIKI_PAGE_RE = re.compile(r"^/wiki(?:/|$)", re.IGNORECASE)


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

# A path segment carrying data rather than naming a route. Case-sensitive on
# purpose: the last alternative is the identifier scheme this project sees most
# -- Wikibase entities and properties, Phabricator tasks -- and matching it
# case-insensitively would swallow `v1` and `v2`, which are routes.
VARIABLE_SEGMENT_RE = re.compile(
    r"[$%*+~]"  # a template hole the language left behind: ${id}, %s, :*
    r"|^\d+$"  # a bare number
    r"|^[0-9a-fA-F]{8,}$"  # a hash, a revision, a long hex id
    r"|^[A-Z]\d+$"  # Q42, P31, T247721
)


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
    if len(host) > MAX_HOST_CHARS or not HOSTNAME_RE.match(host):
        return ""
    if host in NEVER_AN_ENDPOINT or PLACEHOLDER_RE.search(host):
        return ""
    return host


def _is_reference(host: str, path: str) -> bool:
    """Report whether this address names something to read rather than to call.

    Source links to documentation far more often than it calls services, so
    without this the bucket fills with wiki pages, repository browse URLs and
    the blog post that explained a workaround. Those are worth knowing, but
    they answer a different question than the one this bucket is named for.

    Takes the path as the source wrote it rather than the templated one, so that
    a filename the templating would have replaced is still read as a filename.
    """
    if REFERENCE_HOST_RE.search(host) or SHORTENER_RE.match(host):
        return True
    if WIKI_PAGE_RE.match(path) or DOC_PATH_RE.match(path) or STATIC_ASSET_RE.search(path):
        return True
    return bool(FORGE_HOST_RE.search(host)) and not FORGE_FETCH_RE.match(path)


def _segment(value: str) -> str:
    """Return one path segment, or `{}` when it holds data rather than a route."""
    return "{}" if VARIABLE_SEGMENT_RE.search(value) else value


def _path(raw: str) -> str:
    """Return the request path, templated, bounded, and always rooted at /.

    A path that swallows another URL stops there. Archives and CORS proxies
    address their target that way, and `web.archive.org/web/{}/http:/bbc.co.uk`
    reports the BBC as something the tool reaches -- when the real endpoint is
    the archive, and the BBC was an example in a docstring.
    """
    segments = [segment for segment in raw.split("/") if segment][:MAX_PATH_SEGMENTS]
    for index, segment in enumerate(segments):
        if EMBEDDED_SCHEME_RE.match(segment):
            segments = [*segments[:index], "{}"]
            break
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
        try:
            parsed = urlsplit(match.group(0).rstrip(TRAILING_PUNCTUATION))
        except ValueError:
            # Source is not a list of addresses, it is text that sometimes
            # contains one, and urlsplit refuses some of what that produces --
            # an authority holding a character that normalizes to a delimiter,
            # say. This runs over every line of every repository the crawler
            # reaches, so one address it cannot read must cost that address and
            # nothing else.
            continue
        host = _host(parsed)
        if not host:
            continue
        if _is_reference(host, parsed.path):
            continue
        path = _path(parsed.path)
        group = family(host)
        for action in _actions(parsed.query) or ("",):
            endpoint = Endpoint(host=host, path=path, action=action, family=group)
            if endpoint not in found:
                found.append(endpoint)
        if len(found) >= MAX_PER_LINE:
            break
    return tuple(found[:MAX_PER_LINE])
