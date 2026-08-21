# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading network endpoints out of source: which host, which path, which call."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import source_endpoints  # noqa: E402


def values(line):
    return [endpoint.value for endpoint in source_endpoints.endpoints(line)]


def only(line):
    found = source_endpoints.endpoints(line)
    assert len(found) == 1, found
    return found[0]


def test_a_plain_url_yields_its_host_and_path():
    endpoint = only('fetch("https://nominatim.openstreetmap.org/search")')
    assert (endpoint.host, endpoint.path, endpoint.action) == (
        "nominatim.openstreetmap.org",
        "/search",
        "",
    )


def test_the_action_parameter_is_kept_because_it_is_the_endpoint():
    # Two calls to the same path with wildly different trust profiles. A
    # path-only view would file the bot that rewrites articles next to the one
    # that counts them.
    read = only('url = "https://en.wikipedia.org/w/api.php?action=query&format=json"')
    write = only('url = "https://en.wikipedia.org/w/api.php?action=edit&format=json"')
    assert read.value == "en.wikipedia.org/w/api.php?action=query"
    assert write.value == "en.wikipedia.org/w/api.php?action=edit"


def test_every_allowlisted_parameter_becomes_its_own_endpoint():
    line = "https://en.wikipedia.org/w/api.php?action=query&list=recentchanges&prop=revisions"
    assert values(line) == [
        "en.wikipedia.org/w/api.php?action=query",
        "en.wikipedia.org/w/api.php?list=recentchanges",
        "en.wikipedia.org/w/api.php?prop=revisions",
    ]


def test_a_url_with_actions_does_not_also_report_the_bare_path():
    # The path is legible inside every action value, so emitting it separately
    # would spend a second finding on a fact already recorded.
    assert values("https://en.wikipedia.org/w/api.php?action=query") == ["en.wikipedia.org/w/api.php?action=query"]


def test_the_same_parameter_twice_is_recorded_once():
    line = "https://x.wikipedia.org/w/api.php?action=query&action=query"
    assert values(line) == ["x.wikipedia.org/w/api.php?action=query"]


def test_a_pipe_joined_mediawiki_value_survives_intact():
    endpoint = only("https://en.wikipedia.org/w/api.php?prop=revisions|info")
    assert endpoint.action == "prop=revisions|info"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        # Both spellings found in Twinkle: a wikitext link label and
        # Phabricator's own "task|task" shorthand. The pipe belongs to the
        # markup around the URL, and reading it as path invented an address.
        ("[https://momentjs.com/|moment.js]", "momentjs.com/"),
        # Phabricator's own "task|task" shorthand, on a host that survives the
        # reference filter so the pipe is what the assertion is about.
        ("https://api.acme-data.org/T247721|T247721", "api.acme-data.org/{}"),
    ],
)
def test_a_pipe_outside_the_query_string_ends_the_address(line, expected):
    assert values(line) == [expected]


@pytest.mark.parametrize(
    "query",
    [
        # The whole point: a secret in a query string must not reach a report.
        "api_key=sk-live-0123456789abcdef",
        "access_token=ya29.a0AfH6SMBexample",
        "password=hunter2",
        "token=abc123&action_taken=edit",
    ],
)
def test_query_values_outside_the_allowlist_are_never_stored(query):
    endpoint = only(f'requests.get("https://api.acme-data.org/v1/thing?{query}")')
    assert endpoint.action == ""
    assert endpoint.value == "api.acme-data.org/v1/thing"


def test_an_allowlisted_key_with_an_unverblike_value_is_dropped():
    # `action` is allowlisted, but a value that is not shaped like a verb is
    # not one, and guessing is how a secret would get through.
    endpoint = only("https://api.acme-data.org/v1?action=AAAA%2Fbb%2Bcc%3D%3D")
    assert endpoint.action == ""


def test_a_value_longer_than_an_action_ever_is_gets_dropped():
    long_value = "a" * (source_endpoints.MAX_ACTION_CHARS + 5)
    assert only(f"https://api.acme-data.org/v1?action={long_value}").action == ""


def test_credentials_in_the_authority_never_reach_the_host():
    endpoint = only("https://alice:hunter2@api.acme-data.org/v1/thing")
    assert endpoint.host == "api.acme-data.org"
    assert "hunter2" not in endpoint.value + endpoint.label


def test_a_port_is_not_part_of_the_host():
    assert only("https://api.acme-data.org:8443/v1").host == "api.acme-data.org"


def test_variable_path_segments_collapse_to_one_endpoint():
    # Otherwise a tool's API surface would be reported as its user base.
    first = only("https://api.acme-data.org/user/12345/edits")
    second = only("https://api.acme-data.org/user/67890/edits")
    assert first.value == second.value == "api.acme-data.org/user/{}/edits"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # A template hole the language left behind. The brace stops the match,
        # so what survives is the sigil, which is enough to know it is data.
        ("https://api.acme-data.org/user/${id}/edits", "/user/{}"),
        ("https://api.acme-data.org/user/%s/edits", "/user/{}/edits"),
        ("https://api.acme-data.org/page/deadbeefcafe1234", "/page/{}"),
        ("https://api.acme-data.org/page/*", "/page/{}"),
        # The identifier scheme this project sees more than any other.
        ("https://www.wikidata.org/entity/Q1985727", "/entity/{}"),
        ("https://www.wikidata.org/entity/Q2", "/entity/{}"),
        ("https://www.wikidata.org/w/rest.php/wikibase/v0/statements/P31", "/w/rest.php/wikibase/v0/statements/{}"),
    ],
)
def test_data_shaped_segments_are_templated(url, expected):
    assert only(url).path == expected


def test_an_api_version_is_a_route_not_an_identifier():
    # `v1` is one letter and digits, like `Q2`. Case is the whole difference,
    # which is why the identifier rule refuses to fold case.
    assert only("https://api.acme-data.org/v1/chat/completions").path == "/v1/chat/completions"


def test_a_short_hex_looking_segment_is_left_alone():
    # `feed` is hex and four characters; templating it would erase a route.
    assert only("https://api.acme-data.org/feed/latest").path == "/feed/latest"


def test_a_root_url_still_has_a_path():
    assert only("https://api.acme-data.org").path == "/"
    assert only("https://api.acme-data.org/").path == "/"


def test_a_trailing_slash_is_the_same_endpoint():
    assert values("https://api.acme-data.org/v1/ https://api.acme-data.org/v1") == ["api.acme-data.org/v1"]


def test_the_path_is_bounded_in_segments():
    deep = "/".join(f"s{index}" for index in range(source_endpoints.MAX_PATH_SEGMENTS * 3))
    assert only(f"https://api.acme-data.org/{deep}").path.count("/") == source_endpoints.MAX_PATH_SEGMENTS


def test_the_path_is_bounded_in_characters():
    long_segments = "/".join("route" * 12 for _ in range(source_endpoints.MAX_PATH_SEGMENTS))
    assert len(only(f"https://api.acme-data.org/{long_segments}").path) == source_endpoints.MAX_PATH_CHARS


def test_a_host_longer_than_a_hostname_ever_is_gets_refused():
    # Truncating instead would cut mid-label and invent a name resolving
    # nowhere, which reads in a report as a real service the tool contacts.
    host = "sub." + "z" * source_endpoints.MAX_HOST_CHARS + ".acme-data.org"
    assert source_endpoints.endpoints(f"https://{host}/v1") == ()


def test_a_line_full_of_urls_is_bounded():
    line = " ".join(f"https://api{index}.acme-data.org/v1" for index in range(source_endpoints.MAX_PER_LINE * 3))
    assert len(source_endpoints.endpoints(line)) == source_endpoints.MAX_PER_LINE


def test_the_cap_counts_actions_not_urls():
    # One minified line can carry a query API call per parameter, so the cap
    # has to bite on what is emitted rather than on what is matched.
    parameters = "&".join(f"list=l{index}" for index in range(source_endpoints.MAX_PER_LINE * 2))
    assert len(source_endpoints.endpoints(f"https://x.wikipedia.org/w/api.php?{parameters}")) == (
        source_endpoints.MAX_PER_LINE
    )


@pytest.mark.parametrize(
    "line",
    [
        # No URL at all.
        "const total = a + b;",
        "",
        # A scheme this lane does not speak.
        "ftp://files.acme-data.org/thing",
        "git+ssh://git@code.acme-data.org/repo.git",
        # A hostname with no dot is not a public service.
        "http://localhost:8000/api",
        "http://buildbox/api",
        "http://[::1]:8000/api",
    ],
)
def test_lines_that_name_no_endpoint(line):
    assert source_endpoints.endpoints(line) == ()


def test_a_none_line_is_no_line():
    assert source_endpoints.endpoints(None) == ()


@pytest.mark.parametrize(
    "host",
    [
        # Namespaces, licenses and badges: named in source, never connected to.
        "www.w3.org",
        "creativecommons.org",
        "img.shields.io",
        # Placeholders, in documentation and in half-finished config.
        "example.com",
        "api.example.org",
        "127.0.0.1",
        "0.0.0.0",
        "api.service.invalid",
        "wiki.local",
    ],
)
def test_hosts_that_are_never_really_an_endpoint(host):
    assert source_endpoints.endpoints(f'fetch("https://{host}/v1/thing")') == ()


@pytest.mark.parametrize(
    "host",
    [
        "en.wikipedia.org",
        "commons.wikimedia.org",
        "www.mediawiki.org",
        # Not a wiki, but Wikimedia's: the query service and Toolforge are as
        # first-party as a project is, and clean_wiki_domain sees neither.
        "query.wikidata.org",
        "mytool.toolforge.org",
        "example.wmflabs.org",
        "vm.wmcloud.org",
    ],
)
def test_wikimedia_hosts_are_recognized_as_first_party(host):
    assert only(f"https://{host}/v1/thing").family == source_endpoints.FAMILY_WIKIMEDIA


@pytest.mark.parametrize(
    "host",
    [
        "nominatim.openstreetmap.org",
        "api.github.com",
        "api.openai.com",
        # A lookalike is not the estate.
        "en.wikipedia.evil.net",
    ],
)
def test_everything_else_is_third_party(host):
    assert only(f"https://{host}/v1/thing").family == source_endpoints.FAMILY_EXTERNAL


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        # Prose, then code, then a trailing comma from the call around it.
        ("See https://api.acme-data.org/v1/thing.", "api.acme-data.org/v1/thing"),
        ('fetch("https://api.acme-data.org/v1/thing"),', "api.acme-data.org/v1/thing"),
        ("(https://api.acme-data.org/v1/thing)", "api.acme-data.org/v1/thing"),
        ("[docs](https://api.acme-data.org/v1/thing)", "api.acme-data.org/v1/thing"),
    ],
)
def test_punctuation_around_a_url_is_not_part_of_it(line, expected):
    assert values(line) == [expected]


def test_several_hosts_on_one_line_are_all_reported_in_order():
    line = 'proxy("https://api.b.acme-data.org/v1", "https://api.a.acme-data.org/v2")'
    assert values(line) == ["api.b.acme-data.org/v1", "api.a.acme-data.org/v2"]


def test_the_same_endpoint_twice_on_a_line_is_recorded_once():
    line = "https://api.acme-data.org/v1 https://api.acme-data.org/v1"
    assert values(line) == ["api.acme-data.org/v1"]


def test_the_host_case_does_not_split_one_endpoint_in_two():
    assert values("https://API.Example.NET/v1 https://api.acme-data.org/v1") == ["api.acme-data.org/v1"]


def test_the_label_reads_as_an_address_a_person_can_check():
    assert only("https://en.wikipedia.org/w/api.php?action=edit").label == "en.wikipedia.org /w/api.php (action=edit)"
    assert only("https://api.acme-data.org/v1/thing").label == "api.acme-data.org /v1/thing"


@pytest.mark.parametrize(
    "line",
    [
        # A wiki page is something a person reads. A tool that wants the
        # content asks /w/api.php for it, so keying on the article path alone
        # holds on every MediaWiki, inside the estate and out.
        "see https://en.wikipedia.org/wiki/Help:Contents",
        "https://www.mediawiki.org/wiki/API:Etiquette",
        "https://translatewiki.net/wiki/Translating:Toolhub",
        "https://en.wikipedia.org/wiki",
        # Repository furniture: the project page, an issue, a file browser, a
        # review, and the forge's own static hosting.
        "https://github.com/wikimedia-gadgets/twinkle",
        "https://github.com/select2/select2/issues/42",
        "https://github.com/select2/select2/blob/master/LICENSE.md",
        "https://gerrit.wikimedia.org/r/plugins/gitiles/mediawiki/core/x",
        "https://phabricator.wikimedia.org/T247721",
        "https://docs.github.com/en/github/finding-security-vulnerabilities",
        "https://wikimedia-gadgets.github.io/twinkle",
        # Reading material, announced by the host itself.
        "https://stackoverflow.com/a/1234/567",
        "https://docs.djangoproject.com/en/2.2",
        "https://lists.wikimedia.org/pipermail/mediawiki-api-announce/x.html",
        "https://blog.acme-data.org/why-we-moved",
        # An opaque redirect names no endpoint even in principle.
        "https://git.io/JvXDl",
    ],
)
def test_a_link_to_read_is_not_an_endpoint_to_call(line):
    assert source_endpoints.endpoints(line) == ()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # A release asset pulled with wget in a Dockerfile is a real download,
        # forge host or not. This one is measured from wikimedia/toolhub.
        (
            "https://github.com/jwilder/dockerize/releases/download/${V}/dockerize.tar.gz",
            "github.com/jwilder/dockerize/releases/download/{}",
        ),
        ("https://github.com/a/b/archive/refs/tags/v1.0.zip", "github.com/a/b/archive/refs/tags/v1.0.zip"),
        ("https://gitlab.com/a/b/raw/main/data.json", "gitlab.com/a/b/raw/main/data.json"),
    ],
)
def test_a_download_on_a_forge_is_still_a_download(url, expected):
    assert values(url) == [expected]


@pytest.mark.parametrize(
    "url",
    [
        # Neither host browses anything, so neither needs the carve-out above.
        "https://raw.githubusercontent.com/a/b/main/data.json",
        "https://api.github.com/repos/a/b",
    ],
)
def test_a_host_that_only_serves_content_is_not_the_forge(url):
    assert len(source_endpoints.endpoints(url)) == 1


def test_the_api_path_of_a_wiki_is_not_a_wiki_page():
    # /wiki/ is the article path and /w/ is the script path. Only the first is
    # reading material, and confusing them would empty the bucket entirely.
    assert values("https://en.wikipedia.org/w/api.php?action=edit") == ["en.wikipedia.org/w/api.php?action=edit"]
    assert values("https://en.wikipedia.org/w/rest.php/v1/page/Foo") == ["en.wikipedia.org/w/rest.php/v1/page/Foo"]


def test_a_wikilike_prefix_is_not_the_article_path():
    # `/wikidata/` and `/wikipedia/` start with the same five letters, so the
    # article rule has to stop at the segment boundary or it takes both.
    assert values("https://dumps.acme-data.org/wikipedia/commons/1/12/pages-meta") == [
        "dumps.acme-data.org/wikipedia/commons/{}/{}/pages-meta"
    ]


@pytest.mark.parametrize(
    "line",
    [
        # Measured in pywikibot/fixes.py: a regex literal whose `.*` contains a
        # dot, which used to be the only thing a hostname had to have.
        r"fixes = {'pattern': r'http://.*?object=tx\|'}",
        "re.compile(r'https://[a-z]+\\.example\\.org/')",
        # DNS labels do not carry underscores, and a bare label is not a host.
        "https://not_a_host.acme-data.org/v1",
        "https://-leading.acme-data.org/v1",
        "https://trailing-.acme-data.org/v1",
    ],
)
def test_something_shaped_like_a_pattern_is_not_a_hostname(line):
    assert source_endpoints.endpoints(line) == ()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # Archives and CORS proxies address their target inside the path.
        # urlsplit has already collapsed the target's `//` by the time this
        # sees it, so the remnant is a bare `http:` segment.
        ("https://web.archive.org/web/20200101/http://www.bbc.co.uk/news", "web.archive.org/web/{}/{}"),
        ("https://archive.md/2020/https://www.bbc.com", "archive.md/{}/{}"),
        ("https://cors-anywhere.herokuapp.com/https://petscan.wmflabs.org", "cors-anywhere.herokuapp.com/{}"),
    ],
)
def test_a_path_that_swallows_another_url_stops_there(url, expected):
    # Otherwise the report names the BBC as a service the tool reaches, when
    # the BBC was an example in a docstring and the archive is the endpoint.
    assert values(url) == [expected]


@pytest.mark.parametrize(
    "line",
    [
        # Declared at the top of every Android layout, resolved by nothing.
        'xmlns:android="http://schemas.android.com/apk/res/android"',
        "https://www.opengis.net/kml/2.2",
        "https://wikiba.se/ontology#",
        "https://dev.w3.org/html5/websockets",
        # Developer documentation, by any of the names it goes under.
        "https://developer.mozilla.org/en-US/docs/Web/API/EventSource/close",
        "https://doc.rust-lang.org/cargo/reference/manifest.html",
        "https://datatracker.ietf.org/doc/html/rfc7807",
        # A package's page on a registry; the dependencies bucket has the fact.
        "https://pypi.org/project/mwoauth",
        "https://www.npmjs.com/package/axios",
        # Store listings and the badge services that decorate a README.
        "https://play.google.com/store/apps/details?id=fr.free.nrw.commons",
        "https://f-droid.org/repository/browse",
        "https://app.codacy.com/project/badge/Grade/abc123",
        # A defunct issue tracker is still an issue tracker.
        "https://bugzilla.wikimedia.org/show_bug.cgi",
    ],
)
def test_more_things_named_in_source_that_nothing_calls(line):
    assert source_endpoints.endpoints(line) == ()


def test_a_documentation_subdomain_does_not_swallow_a_lookalike():
    # `docker.io` starts with `doc`. The rule needs the label to end there.
    assert only("https://docker.io/v2/library/python/manifests/3.12").host == "docker.io"


@pytest.mark.parametrize(
    "line",
    [
        # Measured on x-tools/xtools: interface icons served from the same host
        # as the media a tool uploads, fifteen of twenty-four findings.
        "https://upload.wikimedia.org/wikipedia/commons/e/e0/Mop.svg",
        "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a3/Admin_bot.png",
        "https://cdn.acme-data.org/assets/app.css",
        "https://cdn.acme-data.org/fonts/inter.woff2",
        "https://cdn.acme-data.org/favicon.ico",
    ],
)
def test_a_file_to_look_at_is_not_a_service_to_call(line):
    assert source_endpoints.endpoints(line) == ()


def test_a_media_path_that_is_not_an_asset_still_counts():
    # The rule keys on the extension, so the upload host itself stays reachable.
    assert only("https://upload.wikimedia.org/w/api.php").host == "upload.wikimedia.org"


@pytest.mark.parametrize(
    "url",
    [
        "https://symfony.com/doc/current/best_practices.html",
        "https://www.php.net/manual/en/function.strtotime.php",
        "https://graphviz.org/docs/outputs",
        "https://turbo.hotwired.dev/handbook/drive",
        "https://acme-data.org/tutorial/getting-started",
    ],
)
def test_a_manual_on_the_product_domain_is_still_a_manual(url):
    assert source_endpoints.endpoints(url) == ()


def test_a_path_named_for_a_document_type_is_not_a_manual():
    # `/document` starts with `doc`. The rule needs the segment to end there.
    assert only("https://api.acme-data.org/document/42").path == "/document/{}"


def test_a_balanced_bracket_belongs_to_the_address():
    # Measured in x-tools/xtools: a Commons file name disambiguated with
    # parentheses, ending the match at `Pliers_with_yellow_handles_` and filing
    # the first half of a file name as a route.
    line = (
        "interface-admin: https://upload.wikimedia.org/wikipedia/commons/thumb/"
        "7/7e/Pliers_(rotated).svg/20px-Pliers_(rotated).svg.png"
    )
    assert source_endpoints.endpoints(line) == ()


@pytest.mark.parametrize(
    "line",
    [
        "See (https://api.acme-data.org/v1) for details",
        "[the endpoint](https://api.acme-data.org/v1)",
        "call(https://api.acme-data.org/v1)",
    ],
)
def test_a_bracket_around_the_address_is_not_part_of_it(line):
    assert only(line).path == "/v1"


def test_an_address_the_parser_refuses_ends_only_itself():
    # `urlsplit` raises on an authority holding a character that NFKC turns into
    # a delimiter. The scan runs over every line of every repository the crawler
    # reaches, so the line has to survive the address it cannot read.
    line = "https://acme\uff03data.org/v1 and https://api.acme-data.org/v1"
    assert [item.value for item in source_endpoints.endpoints(line)] == ["api.acme-data.org/v1"]


def test_a_callback_placeholder_does_not_end_the_query():
    # JSONP spells its callback `callback=?`. Reading that as the end of the
    # address cost QuickStatements the `action=query` on a call it makes.
    line = "$.getJSON('https://api.acme-data.org/w/api.php?callback=?&action=query&titles=X')"
    assert values(line) == ["api.acme-data.org/w/api.php?action=query"]
