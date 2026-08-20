# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the source-host enrichment lane and the budget that bounds it.

The behaviour worth pinning here is what the lane does when it *cannot* finish:
the shared token has a reserve floor it will not spend below, a repository it
was never able to attempt must not be charged an attempt, and a count the host
declined to answer must not overwrite one it answered last week.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import repository_enrichment as lane  # noqa: E402
from backend import db, outbound  # noqa: E402
from backend.models import RepositoryAnalysisState, RepositoryHostMetadata  # noqa: E402

GITHUB_URL = "https://github.com/wikimedia/toolhub"
CODEBERG_URL = "https://codeberg.org/owner/repo"
PROJECT_BODY = b'{"archived": false, "stargazers_count": 12, "default_branch": "main"}'

# Sorts after GITHUB_URL, so in a two-candidate pass GitHub is reached first
# and its refusal is already on the books when the wiki page comes up.
WIKI_URL = "https://www.mediawiki.org/wiki/User:Ada/tool.js"
BARE_BODY = b'{"latest": {"id": 9, "timestamp": "2026-08-01T00:00:00Z"}}'

GITHUB = "github"
# Not a token provider, which is what makes it the useful foil for GitHub here.
WIKI = "mediawiki-wikimedia"


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()


@pytest.fixture(autouse=True)
def _no_token(monkeypatch):
    monkeypatch.delenv("TOOLHUB_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("TOOLHUB_ENRICHMENT_LIMIT", raising=False)


def _resp(status=200, headers=None, body=b"{}"):
    return outbound.ApiResponse(status_code=status, url="https://api.example/x", body=body, headers=headers or {})


class FakeApi:
    """Stands in for outbound.fetch_api, which has its own tests."""

    def __init__(self, by_url=None, default=None, raises=None):
        self.by_url = by_url or {}
        self.default = default if default is not None else _resp()
        self.raises = raises
        self.calls = []

    def __call__(self, _session, url, *, caller, token=None, etag=None):  # noqa: ANN001
        self.calls.append((url, token, etag))
        if self.raises is not None:
            raise self.raises
        for fragment, response in self.by_url.items():
            if fragment in url:
                return response
        return self.default


def _install(monkeypatch, api):
    monkeypatch.setattr(lane.outbound, "fetch_api", api)
    return api


def _state(url, tool_name="tool"):
    with db.session_scope() as s:
        s.add(RepositoryAnalysisState(tool_name=tool_name, repository_url=url))


def _row(url=GITHUB_URL):
    with db.session_scope() as s:
        return s.get(RepositoryHostMetadata, lane.url_hash(url))


# --- the budget --------------------------------------------------------------


def test_the_budget_is_unknown_until_a_host_reports_one():
    budget = lane.Budget()
    assert budget.remaining(GITHUB) is None
    assert budget.depleted(GITHUB) is False

    budget.observe(GITHUB, {"x-ratelimit-remaining": "4999"})

    assert (budget.spent, budget.remaining(GITHUB)) == (1, 4999)
    assert budget.depleted(GITHUB) is False


def test_a_host_that_reports_nothing_still_costs_a_request():
    budget = lane.Budget()
    budget.observe(GITHUB, {})
    budget.observe(GITHUB, {"x-ratelimit-remaining": "not-a-number"})
    assert (budget.spent, budget.remaining(GITHUB)) == (2, None)


def test_the_lane_stops_at_the_reserve_floor_it_will_not_spend_below():
    # The same token publishes user-submitted issue reports; a background
    # refresh must never be why one of those fails.
    budget = lane.Budget(reserve=1000)
    budget.observe(GITHUB, {"x-ratelimit-remaining": "1001"})
    assert budget.depleted(GITHUB) is False
    budget.observe(GITHUB, {"x-ratelimit-remaining": "1000"})
    assert budget.depleted(GITHUB) is True


def test_the_reserve_floor_is_not_held_back_from_hosts_we_send_no_token_to():
    # The floor protects a shared credential. Wikimedia issued none, so there
    # is no user-facing consumer of ours to starve and nothing to hold back.
    budget = lane.Budget(reserve=1000)
    budget.observe(WIKI, {"x-ratelimit-remaining": "10"})
    assert budget.depleted(WIKI) is False
    budget.observe(WIKI, {"x-ratelimit-remaining": "0"})
    assert budget.depleted(WIKI) is True


def test_a_host_saying_no_stops_that_host_and_no_other():
    budget = lane.Budget()
    budget.exhaust(GITHUB)
    assert budget.depleted(GITHUB) is True
    assert budget.depleted(WIKI) is False
    assert budget.remaining(WIKI) is None


def test_one_hosts_floor_leaves_the_others_spendable():
    # The behaviour this split exists for: GitHub near its floor used to stop
    # the Wikimedia pages too, which spend none of that quota.
    budget = lane.Budget(reserve=1000)
    budget.observe(GITHUB, {"x-ratelimit-remaining": "1000"})
    budget.observe(WIKI, {})
    assert budget.depleted(GITHUB) is True
    assert budget.depleted(WIKI) is False


@pytest.mark.parametrize(
    ("attempts", "hours"), [(0, 1), (1, 2), (3, 8), (5, 24), (50, 24)]
)
def test_backoff_grows_then_caps_at_a_day(attempts, hours):
    assert lane._backoff(attempts) == timedelta(hours=hours)


# --- request shaping ---------------------------------------------------------


def test_the_token_goes_to_github_and_nowhere_else(monkeypatch):
    monkeypatch.setenv("TOOLHUB_GITHUB_TOKEN", "  ghp-secret  ")
    api = _install(monkeypatch, FakeApi(default=_resp(body=PROJECT_BODY)))
    _state(GITHUB_URL, "a")
    _state(CODEBERG_URL, "b")

    lane.run()

    tokens = {url.split("/")[2]: token for url, token, _etag in api.calls}
    assert tokens["api.github.com"] == "ghp-secret"
    # Codeberg never issued this credential and must not be offered it.
    assert tokens["codeberg.org"] is None


def test_a_stored_etag_makes_the_next_poll_conditional(monkeypatch):
    api = _install(monkeypatch, FakeApi(default=_resp(headers={"etag": 'W/"v1"'}, body=PROJECT_BODY)))
    _state(GITHUB_URL)

    lane.run()
    assert _row().etag == 'W/"v1"'

    # Due again: clear the cooldown the first pass set.
    with db.session_scope() as s:
        s.get(RepositoryHostMetadata, lane.url_hash(GITHUB_URL)).next_attempt_at = None
    api.calls.clear()
    api.default = _resp(status=304)

    lane.run()

    assert api.calls[0][2] == 'W/"v1"'


def test_an_unchanged_repository_costs_one_request_not_three(monkeypatch):
    # A 304 is free on GitHub, and the counts move only when commits do.
    api = _install(monkeypatch, FakeApi(default=_resp(status=304)))
    _state(GITHUB_URL)

    summary = lane.run()

    assert len(api.calls) == 1
    assert summary["unchanged"] == 1
    assert _row().status == lane.STATUS_CURRENT


# --- counts ------------------------------------------------------------------


def test_counts_are_read_from_headers_for_the_hosts_that_publish_them(monkeypatch):
    _install(
        monkeypatch,
        FakeApi(
            by_url={
                "/contributors": _resp(headers={"link": '<https://x?page=417>; rel="last"'}, body=b"[{}]"),
                "/commits": _resp(headers={"link": '<https://x?page=9001>; rel="last"'}, body=b"[{}]"),
            },
            default=_resp(body=PROJECT_BODY),
        ),
    )
    _state(GITHUB_URL)

    lane.run()

    row = _row()
    assert (row.contributor_count, row.commit_count) == (417, 9001)
    assert row.star_count == 12


def test_a_host_that_publishes_no_counts_is_not_asked_for_them(monkeypatch):
    api = _install(monkeypatch, FakeApi(default=_resp(body=PROJECT_BODY)))
    _state(CODEBERG_URL)

    lane.run()

    # One request, not three: a call known to be unanswerable is budget spent
    # for nothing.
    assert len(api.calls) == 1
    row = _row(CODEBERG_URL)
    assert row.contributor_count is None
    assert row.commit_count is None


def test_a_count_the_host_declined_does_not_erase_the_one_it_gave_before(monkeypatch):
    _install(
        monkeypatch,
        FakeApi(
            by_url={"/contributors": _resp(headers={"link": '<https://x?page=42>; rel="last"'}, body=b"[{}]")},
            default=_resp(body=PROJECT_BODY),
        ),
    )
    _state(GITHUB_URL)
    lane.run()
    assert _row().contributor_count == 42

    with db.session_scope() as s:
        s.get(RepositoryHostMetadata, lane.url_hash(GITHUB_URL)).next_attempt_at = None
    # This time the counts endpoint errors. The budget running out mid-repository
    # is not evidence that a project lost its contributors.
    _install(
        monkeypatch,
        FakeApi(by_url={"/contributors": _resp(status=500)}, default=_resp(body=PROJECT_BODY)),
    )

    lane.run()

    assert _row().contributor_count == 42


# --- verdicts ----------------------------------------------------------------


def test_an_unsupported_host_is_settled_without_a_request(monkeypatch):
    api = _install(monkeypatch, FakeApi())
    _state("https://example.com/owner/repo")

    summary = lane.run()

    assert api.calls == []
    assert summary["unsupported"] == 1
    row = _row("https://example.com/owner/repo")
    assert row.status == lane.STATUS_UNSUPPORTED
    # Re-decided on the ordinary cadence: a project can move to a real forge.
    assert row.next_attempt_at is not None
    assert row.attempts == 0


@pytest.mark.parametrize("status", [404, 410])
def test_a_vanished_project_is_recorded_as_missing_not_failed(monkeypatch, status):
    _install(monkeypatch, FakeApi(default=_resp(status=status)))
    _state(GITHUB_URL)

    summary = lane.run()

    assert summary["missing"] == 1
    assert _row().status == lane.STATUS_MISSING
    assert _row().attempts == 0


def test_an_unexpected_status_backs_the_repository_off(monkeypatch):
    _install(monkeypatch, FakeApi(default=_resp(status=500)))
    _state(GITHUB_URL)

    summary = lane.run()

    assert summary["errors"] == 1
    row = _row()
    assert row.status == lane.STATUS_ERROR
    assert row.attempts == 1
    assert row.last_error is not None
    assert "500" in row.last_error


def test_a_transport_failure_backs_the_repository_off(monkeypatch):
    _install(monkeypatch, FakeApi(raises=lane.requests.ConnectionError("no route")))
    _state(GITHUB_URL)

    summary = lane.run()

    assert summary["errors"] == 1
    assert _row().attempts == 1
    assert "no route" in summary["sampleErrors"][0]


def test_a_guard_rejection_is_an_error_not_a_crash(monkeypatch):
    _install(monkeypatch, FakeApi(raises=ValueError("resolves to a non-public address")))
    _state(GITHUB_URL)

    assert lane.run()["errors"] == 1


def test_an_unreadable_payload_is_an_error_not_a_stored_blank(monkeypatch):
    _install(monkeypatch, FakeApi(default=_resp(body=b"<html>not json</html>")))
    _state(GITHUB_URL)

    summary = lane.run()

    assert summary["errors"] == 1
    row = _row()
    assert row.status == lane.STATUS_ERROR
    assert row.star_count is None


def test_the_stored_row_carries_the_host_identity(monkeypatch):
    _install(monkeypatch, FakeApi(default=_resp(body=PROJECT_BODY)))
    _state(GITHUB_URL)

    lane.run()

    row = _row()
    assert (row.provider, row.api, row.kind) == ("github", "github", "forge")
    assert row.project_path == "wikimedia/toolhub"
    assert row.archived is False
    assert row.fetched_at is not None


# --- stopping ----------------------------------------------------------------


def test_a_rate_limited_answer_stops_that_host_and_charges_nobody(monkeypatch):
    _install(monkeypatch, FakeApi(default=_resp(status=403, headers={"x-ratelimit-remaining": "0"})))
    _state(GITHUB_URL, "a")
    _state("https://github.com/other/repo", "b")

    summary = lane.run()

    assert summary["stoppedOnBudget"] is True
    # Not attempted is not failed: charging an attempt would back a repository
    # off for a shortage that had nothing to do with it.
    stopped_on = _row("https://github.com/other/repo")
    assert stopped_on.attempts == 0
    assert stopped_on.status == lane.STATUS_PENDING
    assert stopped_on.next_attempt_at is None
    # And the one the pass never reached is untouched entirely.
    assert _row() is None
    assert summary["errors"] == 0


def test_the_floor_only_bites_once_a_host_reports_a_budget(monkeypatch):
    # An unknown budget is not an exhausted one. Four of the five hosts never
    # report one at all, and refusing to fetch them because nobody said how
    # much was left would enrich nothing outside GitHub.
    api = _install(monkeypatch, FakeApi(default=_resp(body=PROJECT_BODY)))
    _state(CODEBERG_URL)

    summary = lane.run(reserve=10**9)

    assert len(api.calls) == 1
    assert summary["fetched"] == 1
    assert summary["rateLimitRemaining"] is None


def test_a_depleted_budget_skips_the_repository_rather_than_half_fetching_it(monkeypatch):
    responses = FakeApi(default=_resp(headers={"x-ratelimit-remaining": "1000"}, body=PROJECT_BODY))
    _install(monkeypatch, responses)
    _state(GITHUB_URL, "a")
    _state("https://github.com/other/repo", "b")

    summary = lane.run(reserve=1000)

    assert summary["stoppedOnBudget"] is True
    # Both are on the host that hit its floor, so only the first is considered.
    assert summary["considered"] == 1


def test_one_host_refusing_does_not_stop_a_host_that_did_not(monkeypatch):
    # The whole point of the per-host split. GitHub 403s on the first
    # candidate; the wiki page behind it spends none of GitHub's quota and
    # must still be enriched.
    api = _install(
        monkeypatch,
        FakeApi(
            by_url={
                "api.github.com": _resp(status=403, headers={"x-ratelimit-remaining": "0"}),
                "/history/counts/editors": _resp(body=b'{"count": 7, "limit": false}'),
                "/history/counts/edits": _resp(body=b'{"count": 42, "limit": false}'),
                "/bare": _resp(body=BARE_BODY),
            }
        ),
    )
    _state(GITHUB_URL, "a")
    _state(WIKI_URL, "b")

    summary = lane.run()

    assert summary["stoppedOnBudget"] is True
    assert summary["fetched"] == 1
    row = _row(WIKI_URL)
    assert (row.kind, row.provider, row.status) == ("wiki", "mediawiki-wikimedia", lane.STATUS_CURRENT)
    assert (row.contributor_count, row.commit_count) == (7, 42)
    # One refused GitHub call plus the wiki's three: the refusal cost the wiki
    # nothing, where a pooled budget would have skipped it outright.
    assert len(api.calls) == 4
    # And the token never left the host that issued it.
    assert {token for url, token, _etag in api.calls if "mediawiki.org" in url} == {None}


def test_a_hosts_own_floor_is_read_from_its_own_headers(monkeypatch):
    # Wikimedia reporting nothing must not inherit GitHub's number, or a busy
    # GitHub hour would silently gate a host that never reported a limit.
    _install(
        monkeypatch,
        FakeApi(
            by_url={
                "api.github.com": _resp(headers={"x-ratelimit-remaining": "1000"}, body=PROJECT_BODY),
                "/history/counts/editors": _resp(body=b'{"count": 2, "limit": false}'),
                "/history/counts/edits": _resp(body=b'{"count": 3, "limit": false}'),
                "/bare": _resp(body=BARE_BODY),
            }
        ),
    )
    _state(GITHUB_URL, "a")
    _state(WIKI_URL, "b")

    summary = lane.run(reserve=1000)

    # GitHub reported itself at the floor on its own first call, so its counts
    # went unread -- but the wiki page never inherited that number and answered
    # all three of its own requests.
    assert summary["fetched"] == 2
    assert summary["rateLimitRemaining"] == 1000
    github, wiki = _row(GITHUB_URL), _row(WIKI_URL)
    assert (github.contributor_count, github.commit_count) == (None, None)
    assert (wiki.contributor_count, wiki.commit_count) == (2, 3)
    # Nothing was skipped: hitting the floor part-way through a repository is
    # not the same as declining to start one.
    assert summary["stoppedOnBudget"] is False
    assert summary["considered"] == 2


# --- candidate selection -----------------------------------------------------


def test_several_tools_at_one_url_are_fetched_once(monkeypatch):
    api = _install(monkeypatch, FakeApi(default=_resp(body=PROJECT_BODY)))
    # A Wikimedia monorepo: one repository, several tools.
    for name in ("tool-a", "tool-b", "tool-c"):
        _state(GITHUB_URL, name)

    summary = lane.run()

    assert summary["considered"] == 1
    assert len({url for url, _t, _e in api.calls if url.endswith("/repos/wikimedia/toolhub")}) == 1


def test_tools_without_a_repository_url_are_not_candidates():
    _state("", "tool-a")
    assert lane.candidates() == []


def test_a_repository_inside_its_cooldown_is_skipped():
    _state(GITHUB_URL)
    with db.session_scope() as s:
        s.add(
            RepositoryHostMetadata(
                url_hash=lane.url_hash(GITHUB_URL),
                repository_url=GITHUB_URL,
                next_attempt_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=5),
            )
        )
    assert lane.candidates() == []


def test_never_fetched_repositories_go_first():
    _state("https://github.com/a/seen", "a")
    _state("https://github.com/b/fresh", "b")
    with db.session_scope() as s:
        s.add(
            RepositoryHostMetadata(
                url_hash=lane.url_hash("https://github.com/a/seen"),
                repository_url="https://github.com/a/seen",
                next_attempt_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
            )
        )
    assert lane.candidates()[0] == "https://github.com/b/fresh"


def test_the_longest_overdue_repository_comes_first():
    for name, hours in (("older", 10), ("newer", 1)):
        url = f"https://github.com/x/{name}"
        _state(url, name)
        with db.session_scope() as s:
            s.add(
                RepositoryHostMetadata(
                    url_hash=lane.url_hash(url),
                    repository_url=url,
                    next_attempt_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours),
                )
            )
    assert lane.candidates()[0] == "https://github.com/x/older"


def test_a_row_that_has_never_been_scheduled_sorts_first():
    assert lane._due_order(RepositoryHostMetadata(url_hash="x", repository_url="y")) == 0.0


def test_the_batch_is_capped():
    for index in range(5):
        _state(f"https://github.com/x/r{index}", f"tool-{index}")
    assert len(lane.candidates(limit=2)) == 2


# --- job entry point ---------------------------------------------------------


def test_main_runs_the_lane_and_prints_its_summary(monkeypatch, capsys):
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    monkeypatch.setattr(lane, "run", lambda limit: {"considered": 0, "limit": limit})

    assert lane.main() == 0
    assert "considered" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("raw", "expected"), [("50", 50), ("0", lane.DEFAULT_LIMIT), ("lots", lane.DEFAULT_LIMIT)]
)
def test_the_per_pass_cap_is_configurable_but_never_unbounded(monkeypatch, raw, expected):
    monkeypatch.setenv("TOOLHUB_ENRICHMENT_LIMIT", raw)
    assert lane._limit() == expected


def test_the_cap_falls_back_when_unset():
    assert lane._limit() == lane.DEFAULT_LIMIT
