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
        ("https://phabricator.wikimedia.org/T247721|T247721", "phabricator.wikimedia.org/{}"),
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
