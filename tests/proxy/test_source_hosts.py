# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for resolving source URLs to host APIs and normalizing their answers.

Everything here is pure: no network, no fixtures, no database. That is the
point of source_hosts existing as its own module -- the part of provider
enrichment most likely to be wrong is the part that knows what each host calls
each field, and it should be possible to be wrong about that loudly and cheaply.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import source_hosts  # noqa: E402

WIKI_GADGET = "https://en.wikipedia.org/wiki/MediaWiki:Gadget-Twinkle.js"
WIKI_SCRIPT = "https://en.wikipedia.org/wiki/User:Example/twinkle.js"


# --- URL to project identity -------------------------------------------------


@pytest.mark.parametrize(
    ("url", "provider", "api", "path", "api_base"),
    [
        (
            "https://github.com/wikimedia/toolhub",
            source_hosts.PROVIDER_GITHUB,
            source_hosts.API_GITHUB,
            "wikimedia/toolhub",
            "https://api.github.com",
        ),
        (
            "https://github.com/wikimedia/toolhub.git",
            source_hosts.PROVIDER_GITHUB,
            source_hosts.API_GITHUB,
            "wikimedia/toolhub",
            "https://api.github.com",
        ),
        (
            "https://GitHub.com/wikimedia/toolhub/tree/main/docs",
            source_hosts.PROVIDER_GITHUB,
            source_hosts.API_GITHUB,
            "wikimedia/toolhub",
            "https://api.github.com",
        ),
        (
            "https://gitlab.com/group/project",
            source_hosts.PROVIDER_GITLAB,
            source_hosts.API_GITLAB,
            "group/project",
            "https://gitlab.com/api/v4",
        ),
        (
            "https://gitlab.wikimedia.org/repos/ci-tools/deep/nest/-/tree/main",
            source_hosts.PROVIDER_GITLAB_WIKIMEDIA,
            source_hosts.API_GITLAB,
            "repos/ci-tools/deep/nest",
            "https://gitlab.wikimedia.org/api/v4",
        ),
        (
            "https://codeberg.org/owner/repo.git",
            source_hosts.PROVIDER_CODEBERG,
            source_hosts.API_FORGEJO,
            "owner/repo",
            "https://codeberg.org/api/v1",
        ),
        (
            "https://bitbucket.org/team/repo/src/main/",
            source_hosts.PROVIDER_BITBUCKET,
            source_hosts.API_BITBUCKET,
            "team/repo",
            "https://api.bitbucket.org/2.0",
        ),
        (
            "https://gerrit.wikimedia.org/r/plugins/gitiles/labs/tools/foo/",
            source_hosts.PROVIDER_GERRIT_WIKIMEDIA,
            source_hosts.API_GERRIT,
            "labs/tools/foo",
            "https://gerrit.wikimedia.org/r",
        ),
        (
            "https://gerrit.wikimedia.org/r/admin/repos/labs/tools/bar",
            source_hosts.PROVIDER_GERRIT_WIKIMEDIA,
            source_hosts.API_GERRIT,
            "labs/tools/bar",
            "https://gerrit.wikimedia.org/r",
        ),
        (
            "https://gerrit.wikimedia.org/plugins/gitiles/mediawiki/core",
            source_hosts.PROVIDER_GERRIT_WIKIMEDIA,
            source_hosts.API_GERRIT,
            "mediawiki/core",
            "https://gerrit.wikimedia.org/r",
        ),
        (
            "https://gerrit.wikimedia.org/g/mediawiki/core",
            source_hosts.PROVIDER_GERRIT_WIKIMEDIA,
            source_hosts.API_GERRIT,
            "mediawiki/core",
            "https://gerrit.wikimedia.org/r",
        ),
        (
            "https://gerrit.wikimedia.org/r/mediawiki/extensions/Foo.git",
            source_hosts.PROVIDER_GERRIT_WIKIMEDIA,
            source_hosts.API_GERRIT,
            "mediawiki/extensions/Foo",
            "https://gerrit.wikimedia.org/r",
        ),
    ],
)
def test_project_ref_resolves_every_supported_host(url, provider, api, path, api_base):
    ref = source_hosts.project_ref(url)
    assert ref is not None
    assert (ref.provider, ref.api, ref.path, ref.api_base) == (provider, api, path, api_base)
    assert ref.kind == source_hosts.KIND_FORGE


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/owner/repo",
        # repository_scan clones from these, but they are gist/raw/www rather
        # than API instances: enriching from them would aim an authenticated
        # request at a service that never issued the credential.
        "https://gist.github.com/owner/abc123",
        "https://pages.gitlab.com/owner/repo",
        "https://github.com/wikimedia",
        "https://github.com/",
        "https://gitlab.com/lonely",
        "https://gitlab.com/lonely/-/tree/main",
        "https://gerrit.wikimedia.org/",
        "https://gerrit.wikimedia.org/settings",
        "not-a-url",
    ],
)
def test_project_ref_declines_urls_it_cannot_address(url):
    assert source_hosts.project_ref(url) is None


def test_encoded_path_is_a_single_url_segment():
    ref = source_hosts.project_ref("https://gitlab.wikimedia.org/repos/ci-tools/nest")
    assert ref is not None
    assert ref.encoded_path == "repos%2Fci-tools%2Fnest"


# --- capabilities ------------------------------------------------------------


def test_only_github_gitlab_and_mediawiki_advertise_the_extra_counts():
    def caps(url):
        ref = source_hosts.project_ref(url)
        assert ref is not None
        return source_hosts.capabilities(ref)

    both = source_hosts.HostCapabilities(contributor_count=True, commit_count=True)
    for url in ("https://github.com/o/r", "https://gitlab.com/o/r", WIKI_GADGET):
        assert caps(url) == both, url
    for url in ("https://codeberg.org/o/r", "https://bitbucket.org/o/r", "https://gerrit.wikimedia.org/g/o/r"):
        assert caps(url) == source_hosts.HostCapabilities(), url


# --- API URLs ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/o/r", "https://api.github.com/repos/o/r"),
        ("https://gitlab.com/g/p", "https://gitlab.com/api/v4/projects/g%2Fp?license=true"),
        ("https://codeberg.org/o/r", "https://codeberg.org/api/v1/repos/o/r"),
        ("https://bitbucket.org/o/r", "https://api.bitbucket.org/2.0/repositories/o/r"),
        ("https://gerrit.wikimedia.org/g/labs/tools/x", "https://gerrit.wikimedia.org/r/projects/labs%2Ftools%2Fx"),
    ],
)
def test_project_url_per_api(url, expected):
    ref = source_hosts.project_ref(url)
    assert ref is not None
    assert source_hosts.project_url(ref) == expected


@pytest.mark.parametrize(
    ("url", "contributors", "commits"),
    [
        (
            "https://github.com/o/r",
            "https://api.github.com/repos/o/r/contributors?per_page=1&anon=1",
            "https://api.github.com/repos/o/r/commits?per_page=1",
        ),
        (
            "https://gitlab.com/g/p",
            "https://gitlab.com/api/v4/projects/g%2Fp/repository/contributors?per_page=1",
            "https://gitlab.com/api/v4/projects/g%2Fp/repository/commits?per_page=1",
        ),
    ],
)
def test_count_urls_request_a_single_item(url, contributors, commits):
    ref = source_hosts.project_ref(url)
    assert ref is not None
    assert source_hosts.contributor_count_url(ref) == contributors
    assert source_hosts.commit_count_url(ref) == commits


# --- payload normalization ---------------------------------------------------


def _ref(url):
    ref = source_hosts.project_ref(url)
    assert ref is not None
    return ref


def test_github_payload_is_normalized():
    facts = source_hosts.metadata_from_payload(
        _ref("https://github.com/o/r"),
        {
            "archived": True,
            "default_branch": "main",
            "description": "  A tool  ",
            "homepage": "https://tool.example",
            "license": {"spdx_id": "gpl-3.0-or-later"},
            "topics": ["wikimedia", "python"],
            "stargazers_count": 12,
            "forks_count": 3,
            "open_issues_count": 4,
            "pushed_at": "2026-08-01T00:00:00Z",
            "created_at": "2020-01-01T00:00:00Z",
        },
    )
    assert facts == source_hosts.HostMetadata(
        archived=True,
        default_branch="main",
        description="A tool",
        homepage="https://tool.example",
        license_id="GPL-3.0-OR-LATER",
        topics=("wikimedia", "python"),
        star_count=12,
        fork_count=3,
        open_issues_count=4,
        pushed_at=datetime(2026, 8, 1, tzinfo=UTC),
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
    )


def test_gitlab_payload_is_normalized_and_has_no_homepage():
    facts = source_hosts.metadata_from_payload(
        _ref("https://gitlab.com/g/p"),
        {
            "archived": False,
            "default_branch": "master",
            "description": "A tool",
            "license": {"key": "mit"},
            "topics": ["ci"],
            "star_count": 7,
            "forks_count": 1,
            "open_issues_count": 0,
            "last_activity_at": "2026-07-01T00:00:00Z",
            "created_at": "2021-01-01T00:00:00Z",
        },
    )
    assert facts.archived is False
    assert facts.license_id == "MIT"
    assert facts.star_count == 7
    assert facts.open_issues_count == 0
    assert facts.pushed_at == datetime(2026, 7, 1, tzinfo=UTC)
    assert facts.homepage is None


def test_forgejo_payload_is_normalized_and_reports_no_license():
    facts = source_hosts.metadata_from_payload(
        _ref("https://codeberg.org/o/r"),
        {
            "archived": False,
            "default_branch": "main",
            "description": "A tool",
            "website": "https://tool.example",
            "topics": ["gadget"],
            "stars_count": 2,
            "forks_count": 0,
            "open_issues_count": 5,
            "updated_at": "2026-06-01T00:00:00Z",
            "created_at": "2022-01-01T00:00:00Z",
        },
    )
    assert facts.homepage == "https://tool.example"
    assert facts.star_count == 2
    assert facts.license_id is None


def test_bitbucket_payload_reads_its_nested_default_branch():
    facts = source_hosts.metadata_from_payload(
        _ref("https://bitbucket.org/o/r"),
        {
            "mainbranch": {"name": "develop"},
            "description": "A tool",
            "website": "https://tool.example",
            "updated_on": "2026-05-01T00:00:00Z",
            "created_on": "2019-01-01T00:00:00Z",
        },
    )
    assert facts.default_branch == "develop"
    assert facts.created_at == datetime(2019, 1, 1, tzinfo=UTC)
    # Absent on this host, and absent is not zero.
    assert facts.star_count is None
    assert facts.archived is None


@pytest.mark.parametrize(
    ("state", "archived"),
    [("ACTIVE", False), ("READ_ONLY", True), ("HIDDEN", True), (None, None)],
)
def test_gerrit_state_maps_to_archived(state, archived):
    facts = source_hosts.metadata_from_payload(
        _ref("https://gerrit.wikimedia.org/g/labs/tools/x"),
        {"state": state, "description": "A tool"},
    )
    assert facts.archived is archived
    assert facts.description == "A tool"


def test_a_non_object_payload_normalizes_to_all_unknown():
    assert source_hosts.metadata_from_payload(_ref("https://github.com/o/r"), ["nope"]) == (source_hosts.HostMetadata())


@pytest.mark.parametrize("disclaimer", ["NOASSERTION", "none", "Other", "unknown"])
def test_a_disclaimed_license_is_unknown_not_stored(disclaimer):
    facts = source_hosts.metadata_from_payload(_ref("https://github.com/o/r"), {"license": {"spdx_id": disclaimer}})
    assert facts.license_id is None


def test_a_missing_license_object_is_unknown():
    facts = source_hosts.metadata_from_payload(_ref("https://github.com/o/r"), {"license": None})
    assert facts.license_id is None


def test_junk_field_types_are_dropped_rather_than_stored():
    facts = source_hosts.metadata_from_payload(
        _ref("https://github.com/o/r"),
        {
            "archived": "yes",
            "description": 42,
            "homepage": "   ",
            "topics": "wikimedia",
            "stargazers_count": True,
            "forks_count": -1,
            "open_issues_count": "many",
        },
    )
    assert facts == source_hosts.HostMetadata()


def test_topics_are_bounded_in_count_and_length():
    facts = source_hosts.metadata_from_payload(
        _ref("https://github.com/o/r"),
        {"topics": [f"topic-{index}" for index in range(50)] + [7, None, "x" * 200]},
    )
    assert len(facts.topics) == source_hosts.MAX_TOPICS
    assert facts.topics[0] == "topic-0"


def test_long_text_is_truncated_not_rejected():
    facts = source_hosts.metadata_from_payload(_ref("https://github.com/o/r"), {"description": "d" * 5000})
    assert facts.description is not None
    assert len(facts.description) == source_hosts.MAX_TEXT_CHARS


# --- response decoding -------------------------------------------------------


def test_gerrit_xssi_prefix_is_stripped_before_parsing():
    payload = source_hosts.decode_payload(
        _ref("https://gerrit.wikimedia.org/g/labs/tools/x"), b')]}\'\n{"state": "READ_ONLY"}'
    )
    assert payload == {"state": "READ_ONLY"}


def test_other_hosts_are_parsed_as_plain_json():
    assert source_hosts.decode_payload(_ref("https://github.com/o/r"), b'{"archived": false}') == {"archived": False}


# --- counts from headers -----------------------------------------------------


def test_gitlab_count_comes_from_x_total():
    ref = _ref("https://gitlab.com/g/p")
    assert source_hosts.count_from_response(ref, {"x-total": " 417 "}, []) == 417


def test_gitlab_never_falls_back_to_the_body_that_carries_emails():
    ref = _ref("https://gitlab.com/g/p")
    body = [{"name": "A", "email": "a@example.org"}]
    assert source_hosts.count_from_response(ref, {}, body) is None
    assert source_hosts.count_from_response(ref, {"X-Total": "not-a-number"}, body) is None


def test_github_count_comes_from_the_last_page_link():
    ref = _ref("https://github.com/o/r")
    link = (
        '<https://api.github.com/repos/o/r/contributors?per_page=1&page=2>; rel="next", '
        '<https://api.github.com/repos/o/r/contributors?per_page=1&page=417>; rel="last"'
    )
    assert source_hosts.count_from_response(ref, {"Link": link}, [{"login": "a"}]) == 417


@pytest.mark.parametrize(
    ("headers", "payload", "expected"),
    [
        # A single-page result carries no Link at all.
        ({}, [{"login": "a"}], 1),
        ({}, [], 0),
        # Present but naming no last page: nothing to read but the page itself.
        ({"Link": '<https://api.github.com/repos/o/r>; rel="last"'}, [{"login": "a"}], 1),
        ({"Link": '<https://api.github.com/repos/o/r?page=2>; rel="next"'}, [{"login": "a"}], 1),
        # Not a page of items at all -- an error object, say.
        ({}, {"message": "Not Found"}, None),
    ],
)
def test_github_falls_back_to_measuring_the_page(headers, payload, expected):
    ref = _ref("https://github.com/o/r")
    assert source_hosts.count_from_response(ref, headers, payload) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The five spellings the five hosts actually emit.
        ("2026-08-01T12:30:00Z", datetime(2026, 8, 1, 12, 30, tzinfo=UTC)),
        ("2026-08-01T12:30:00.000Z", datetime(2026, 8, 1, 12, 30, tzinfo=UTC)),
        ("2026-08-01T12:30:00.000000+00:00", datetime(2026, 8, 1, 12, 30, tzinfo=UTC)),
        ("2026-08-01T14:30:00+02:00", datetime(2026, 8, 1, 12, 30, tzinfo=UTC)),
        # No offset at all: every one of these APIs documents UTC.
        ("2026-08-01T12:30:00", datetime(2026, 8, 1, 12, 30, tzinfo=UTC)),
    ],
)
def test_every_host_timestamp_spelling_normalizes_to_utc(raw, expected):
    facts = source_hosts.metadata_from_payload(_ref("https://github.com/o/r"), {"pushed_at": raw})
    assert facts.pushed_at == expected


@pytest.mark.parametrize("raw", ["never", "", None, 17, "2026-13-45T99:99:99Z"])
def test_an_unreadable_timestamp_is_unknown_not_the_epoch(raw):
    # Falling back to a real instant would make recency scoring confidently
    # wrong rather than honestly silent.
    facts = source_hosts.metadata_from_payload(_ref("https://github.com/o/r"), {"pushed_at": raw})
    assert facts.pushed_at is None


# --- MediaWiki, the host that is not a forge ---------------------------------


@pytest.mark.parametrize(
    ("url", "path", "api_base"),
    [
        (WIKI_GADGET, "MediaWiki:Gadget-Twinkle.js", "https://en.wikipedia.org/w/rest.php/v1"),
        (WIKI_SCRIPT, "User:Example/twinkle.js", "https://en.wikipedia.org/w/rest.php/v1"),
        # Any Wikimedia wiki, not a fixed host list: the API is identical and
        # only the origin moves, which is the whole reason wikis are matched by
        # URL shape rather than by PROVIDERS_BY_HOST.
        (
            "https://commons.wikimedia.org/wiki/MediaWiki:Gadget-Foo.js",
            "MediaWiki:Gadget-Foo.js",
            "https://commons.wikimedia.org/w/rest.php/v1",
        ),
    ],
)
def test_a_wiki_page_resolves_to_a_wiki_kind_ref(url, path, api_base):
    ref = source_hosts.project_ref(url)
    assert ref is not None
    assert (ref.provider, ref.api, ref.path, ref.api_base) == (
        source_hosts.PROVIDER_MEDIAWIKI_WIKIMEDIA,
        source_hosts.API_MEDIAWIKI,
        path,
        api_base,
    )
    # The distinction the enrichment lane reads before assuming a clone exists.
    assert ref.kind == source_hosts.KIND_WIKI


@pytest.mark.parametrize(
    "url",
    [
        # An article about a tool is not the tool.
        "https://en.wikipedia.org/wiki/Twinkle",
        "https://en.wikipedia.org/wiki/User:Example/documentation",
        # A wiki we do not recognise gets no API base guessed for it.
        "https://wiki.example.org/wiki/MediaWiki:Gadget-Foo.js",
    ],
)
def test_wiki_urls_that_hold_no_code_are_declined(url):
    assert source_hosts.project_ref(url) is None


def test_a_page_title_is_encoded_whole_including_its_slashes():
    ref = source_hosts.project_ref(WIKI_SCRIPT)
    assert ref is not None
    # REST v1 takes the title as one path segment. A bare "/" here would
    # address /page/User:Example/twinkle.js/bare, which is a different route.
    assert ref.encoded_path == "User%3AExample%2Ftwinkle.js"


def test_wiki_api_urls_ask_for_the_bare_page_and_the_two_counts():
    ref = source_hosts.project_ref(WIKI_GADGET)
    assert ref is not None
    base = "https://en.wikipedia.org/w/rest.php/v1/page/MediaWiki%3AGadget-Twinkle.js"
    assert source_hosts.project_url(ref) == f"{base}/bare"
    assert source_hosts.contributor_count_url(ref) == f"{base}/history/counts/editors"
    assert source_hosts.commit_count_url(ref) == f"{base}/history/counts/edits"


def test_a_bare_page_reports_its_last_edit_and_nothing_it_cannot_know():
    meta = source_hosts.metadata_from_payload(
        _ref(WIKI_GADGET),
        {
            "id": 12345,
            "key": "MediaWiki:Gadget-Twinkle.js",
            "content_model": "javascript",
            "latest": {"id": 987, "timestamp": "2024-03-01T12:00:00Z"},
            "license": {"title": "Creative Commons Attribution-ShareAlike 4.0"},
        },
    )
    assert meta.pushed_at == datetime(2024, 3, 1, 12, 0, tzinfo=UTC)
    # A page has no branch and no forge counters; None says "not published
    # here" rather than zero, which is what stops scoring penalizing it.
    assert (meta.default_branch, meta.star_count, meta.fork_count, meta.open_issues_count) == (None, None, None, None)


def test_a_wiki_page_is_never_archived():
    # MediaWiki: pages are protected as routine site policy, so a protection
    # flag would read as abandonment on every gadget on every wiki. Leaving
    # archived unknown keeps wiki tools scored on activity alone.
    assert source_hosts.metadata_from_payload(_ref(WIKI_GADGET), {"protected": True}).archived is None


def test_the_wiki_text_license_is_not_stored_as_the_source_license():
    # CC BY-SA covers the page, not the JavaScript on it. Recording it would
    # answer the licence question confidently and wrongly.
    meta = source_hosts.metadata_from_payload(_ref(WIKI_GADGET), {"license": {"title": "CC BY-SA 4.0", "url": "..."}})
    assert meta.license_id is None


def test_a_page_that_has_never_been_edited_reports_no_timestamp():
    assert source_hosts.metadata_from_payload(_ref(WIKI_GADGET), {"latest": None}).pushed_at is None


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"count": 137, "limit": False}, 137),
        # limit=true means the wiki stopped counting at its cap, so this is a
        # floor. Every threshold it feeds asks "at least how many".
        ({"count": 10000, "limit": True}, 10000),
        ({"count": 0, "limit": False}, 0),
        ({"count": "many"}, None),
        ({}, None),
        ("not an object", None),
    ],
)
def test_the_wiki_count_is_read_from_the_body(payload, expected):
    assert source_hosts.count_from_response(_ref(WIKI_GADGET), {}, payload) == expected


def test_the_wiki_count_ignores_a_header_that_is_not_its_own():
    # X-Total belongs to GitLab. A proxy or CDN that adds one must not be able
    # to overwrite the number the endpoint actually answered with.
    assert source_hosts.count_from_response(_ref(WIKI_GADGET), {"X-Total": "9"}, {"count": 3}) == 3
