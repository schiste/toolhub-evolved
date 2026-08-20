# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for resolving source URLs to host APIs and normalizing their answers.

Everything here is pure: no network, no fixtures, no database. That is the
point of source_hosts existing as its own module -- the part of provider
enrichment most likely to be wrong is the part that knows what each host calls
each field, and it should be possible to be wrong about that loudly and cheaply.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import source_hosts  # noqa: E402


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


def test_only_github_and_gitlab_advertise_the_extra_counts():
    def caps(url):
        ref = source_hosts.project_ref(url)
        assert ref is not None
        return source_hosts.capabilities(ref)

    assert caps("https://github.com/o/r") == source_hosts.HostCapabilities(
        contributor_count=True, commit_count=True
    )
    assert caps("https://gitlab.com/o/r") == source_hosts.HostCapabilities(
        contributor_count=True, commit_count=True
    )
    for url in ("https://codeberg.org/o/r", "https://bitbucket.org/o/r", "https://gerrit.wikimedia.org/g/o/r"):
        assert caps(url) == source_hosts.HostCapabilities()


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
        pushed_at="2026-08-01T00:00:00Z",
        created_at="2020-01-01T00:00:00Z",
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
    assert facts.pushed_at == "2026-07-01T00:00:00Z"
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
    assert facts.created_at == "2019-01-01T00:00:00Z"
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
    assert source_hosts.metadata_from_payload(_ref("https://github.com/o/r"), ["nope"]) == (
        source_hosts.HostMetadata()
    )


@pytest.mark.parametrize("disclaimer", ["NOASSERTION", "none", "Other", "unknown"])
def test_a_disclaimed_license_is_unknown_not_stored(disclaimer):
    facts = source_hosts.metadata_from_payload(
        _ref("https://github.com/o/r"), {"license": {"spdx_id": disclaimer}}
    )
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
    facts = source_hosts.metadata_from_payload(
        _ref("https://github.com/o/r"), {"description": "d" * 5000}
    )
    assert facts.description is not None
    assert len(facts.description) == source_hosts.MAX_TEXT_CHARS


# --- response decoding -------------------------------------------------------


def test_gerrit_xssi_prefix_is_stripped_before_parsing():
    payload = source_hosts.decode_payload(
        _ref("https://gerrit.wikimedia.org/g/labs/tools/x"), b")]}'\n{\"state\": \"READ_ONLY\"}"
    )
    assert payload == {"state": "READ_ONLY"}


def test_other_hosts_are_parsed_as_plain_json():
    assert source_hosts.decode_payload(_ref("https://github.com/o/r"), b'{"archived": false}') == {
        "archived": False
    }


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
