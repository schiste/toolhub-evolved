# SPDX-License-Identifier: GPL-3.0-or-later
"""Deciding which wikis a census run covers, and when it has to stop.

The interesting cases are all about a thousand wikis and one run's worth of
time: that nothing starves, that a wiki which was never covered goes first, that
a wiki nobody edits drifts out of the way of one that is edited hourly, and that
a replica having a bad afternoon costs a wiki some turns rather than its place.

No replica and no wiki are reached. The budget runs on an injected clock rather
than on sleeping, so the deadline cases cost nothing.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, wiki_schedule as schedule  # noqa: E402
from backend.models import WikiLaneState, WikiProject, utcnow  # noqa: E402

LANE = schedule.USERSCRIPT_LANE
GADGETS = schedule.GADGET_LANE


@pytest.fixture(autouse=True)
def _database():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret", trusted_hosts=backend.LOCAL_TRUSTED_HOSTS + backend.DEFAULT_TRUSTED_HOSTS)
    with application.app_context():
        yield


def register(*wikis, section="s3", closed=False, seen=None):
    """Put wikis in the registry, as `wiki_registry.refresh` would have."""
    with db.session_scope() as session:
        for index, wiki in enumerate(wikis):
            session.add(
                WikiProject(
                    wiki=wiki,
                    dbname=wiki.split(".")[0],
                    section=section,
                    closed=closed,
                    first_seen_at=seen or utcnow() - timedelta(days=index + 1),
                    last_seen_at=utcnow(),
                )
            )


def state(wiki, lane=LANE):
    with db.session_scope() as session:
        row = session.query(WikiLaneState).filter_by(wiki=wiki, lane=lane).one()
        return {
            "next_due_at": row.next_due_at,
            "cadence": row.cadence_seconds,
            "failures": row.consecutive_failures,
            "runs": row.runs,
            "error": row.last_error,
            "success": row.last_success_at,
            "started": row.last_started_at,
        }


# --- the queue -------------------------------------------------------------


def test_a_wiki_never_covered_is_due_immediately():
    """This is what makes adding a wiki to the registry enough. No backfill step."""
    register("fr.wikipedia.org")
    assert [entry.wiki for entry in schedule.due(LANE)] == ["fr.wikipedia.org"]


def test_a_wiki_covered_a_moment_ago_is_not_due_again():
    register("fr.wikipedia.org")
    schedule.settle("fr.wikipedia.org", LANE, schedule.Outcome())
    assert schedule.due(LANE) == ()


def test_the_most_overdue_wiki_goes_first():
    register("a.example", "b.example", "c.example")
    now = utcnow()
    for wiki, minutes in (("a.example", 5), ("b.example", 90), ("c.example", 30)):
        schedule.settle(wiki, LANE, schedule.Outcome(), now=now - timedelta(days=400, minutes=minutes))
    assert [entry.wiki for entry in schedule.due(LANE)] == ["b.example", "c.example", "a.example"]


def test_a_wiki_a_run_had_no_time_for_is_more_overdue_next_time_not_forgotten():
    """Starvation is the failure mode a thousand-wiki queue has to rule out."""
    register("a.example", "b.example")
    covered = "a.example"
    schedule.settle(covered, LANE, schedule.Outcome())
    remaining = schedule.due(LANE)
    assert [entry.wiki for entry in remaining] == ["b.example"]
    # And it is still there on the next run, ahead of the wiki that was covered.
    assert [entry.wiki for entry in schedule.due(LANE)] == ["b.example"]


def test_the_two_lanes_queue_apart():
    """A gadget inventory is one request and a script sweep is thousands."""
    register("fr.wikipedia.org")
    schedule.settle("fr.wikipedia.org", GADGETS, schedule.Outcome())
    assert schedule.due(GADGETS) == ()
    assert [entry.wiki for entry in schedule.due(LANE)] == ["fr.wikipedia.org"]


def test_a_retired_wiki_is_never_offered():
    register("gone.example")
    with db.session_scope() as session:
        session.query(WikiProject).filter_by(wiki="gone.example").one().retired_at = utcnow()
    assert schedule.due(LANE) == ()


def test_the_selection_carries_what_it_takes_to_reach_the_wiki():
    """The queue is read once; a caller that had to look the address up again
    would be asking the registry a thousand more questions per run."""
    register("aa.wikipedia.org", section="s3", closed=True)
    (entry,) = schedule.due(LANE)
    assert (entry.dbname, entry.section, entry.closed) == ("aa", "s3", True)


def test_a_selection_is_reordered_so_one_section_is_covered_together():
    """869 wikis share s3; interleaving them would reopen its connection each time."""
    register("one.example", "four.example", section="s3")
    register("two.example", section="s1")
    register("three.example", section="s6")
    assert [entry.section for entry in schedule.due(LANE)] == ["s1", "s3", "s3", "s6"]


def test_the_selection_is_bounded_but_the_order_is_still_by_owed_ness():
    register(*[f"w{index:03d}.example" for index in range(10)])
    now = utcnow()
    for index in range(10):
        schedule.settle(f"w{index:03d}.example", LANE, schedule.Outcome(), now=now - timedelta(days=400 + index))
    # The three most overdue are the three oldest settles, whatever the limit
    # does to the rest.
    assert {entry.wiki for entry in schedule.due(LANE, limit=3)} == {
        "w009.example",
        "w008.example",
        "w007.example",
    }


def test_the_backlog_is_how_many_wikis_are_owed_a_turn():
    register(*[f"w{index}.example" for index in range(5)])
    assert schedule.backlog(LANE) == 5
    schedule.settle("w0.example", LANE, schedule.Outcome())
    assert schedule.backlog(LANE) == 4
    # Unbounded by the selection, which is the point: it says whether the
    # budget is keeping up, and a number capped at the slice size could not.
    assert schedule.backlog(LANE) >= len(schedule.due(LANE, limit=2))


# --- learning how often a wiki is worth asking -----------------------------


def test_a_wiki_that_keeps_changing_converges_on_the_fast_end():
    register("en.wikipedia.org")
    for _ in range(10):
        schedule.settle("en.wikipedia.org", LANE, schedule.Outcome(changed=True))
    assert state("en.wikipedia.org")["cadence"] == schedule.CADENCES[LANE].fastest


def test_a_quiet_wiki_drifts_out_of_the_way():
    register("quiet.example")
    for _ in range(20):
        schedule.settle("quiet.example", LANE, schedule.Outcome())
    assert state("quiet.example")["cadence"] == schedule.CADENCES[LANE].slowest


def test_a_closed_wiki_is_allowed_to_get_slower_than_an_open_one():
    """Its scripts cannot change, because nobody can edit them."""
    register("aa.wikipedia.org", closed=True)
    for _ in range(30):
        schedule.settle("aa.wikipedia.org", LANE, schedule.Outcome(closed=True))
    assert state("aa.wikipedia.org")["cadence"] == schedule.CADENCES[LANE].slowest_closed


def test_a_wiki_that_went_quiet_and_came_back_speeds_up_again():
    register("fr.wikipedia.org")
    for _ in range(6):
        schedule.settle("fr.wikipedia.org", LANE, schedule.Outcome())
    slow = state("fr.wikipedia.org")["cadence"]
    schedule.settle("fr.wikipedia.org", LANE, schedule.Outcome(changed=True))
    assert state("fr.wikipedia.org")["cadence"] == slow // 2


def test_the_next_turn_is_the_cadence_away():
    register("fr.wikipedia.org")
    now = utcnow()
    due_at = schedule.settle("fr.wikipedia.org", LANE, schedule.Outcome(changed=True), now=now)
    assert due_at == now + timedelta(seconds=state("fr.wikipedia.org")["cadence"])


# --- when a wiki cannot be covered ----------------------------------------


def test_a_failure_backs_off_and_keeps_the_reason():
    register("broken.example")
    now = utcnow()
    due_at = schedule.settle("broken.example", LANE, schedule.Outcome(error="MaxRetryError"), now=now)
    assert due_at == now + timedelta(seconds=schedule.BACKOFF_BASE)
    assert state("broken.example")["error"] == "MaxRetryError"
    assert state("broken.example")["success"] is None


def test_repeated_failures_back_off_further_each_time():
    register("broken.example")
    now = utcnow()
    delays = []
    for _ in range(4):
        delays.append(schedule.settle("broken.example", LANE, schedule.Outcome(error="boom"), now=now) - now)
    assert delays == [timedelta(seconds=schedule.BACKOFF_BASE * 2**index) for index in range(4)]


def test_backoff_is_capped_so_a_wiki_never_leaves_the_queue_for_good():
    register("broken.example")
    now = utcnow()
    for _ in range(30):
        due_at = schedule.settle("broken.example", LANE, schedule.Outcome(error="boom"), now=now)
    assert due_at == now + timedelta(seconds=schedule.BACKOFF_MAX)


def test_a_failure_does_not_change_how_often_the_wiki_is_worth_asking():
    """A replica having a bad afternoon is not a wiki changing its edit rate."""
    register("fr.wikipedia.org")
    schedule.settle("fr.wikipedia.org", LANE, schedule.Outcome(changed=True))
    cadence = state("fr.wikipedia.org")["cadence"]
    schedule.settle("fr.wikipedia.org", LANE, schedule.Outcome(error="boom"))
    assert state("fr.wikipedia.org")["cadence"] == cadence


def test_a_success_clears_the_failure_count():
    register("flaky.example")
    now = utcnow()
    schedule.settle("flaky.example", LANE, schedule.Outcome(error="boom"), now=now)
    schedule.settle("flaky.example", LANE, schedule.Outcome(error="boom"), now=now)
    schedule.settle("flaky.example", LANE, schedule.Outcome(), now=now)
    assert state("flaky.example")["failures"] == 0
    assert state("flaky.example")["error"] is None
    # And the next failure starts the backoff over rather than resuming it.
    assert schedule.settle("flaky.example", LANE, schedule.Outcome(error="boom"), now=now) - now == timedelta(
        seconds=schedule.BACKOFF_BASE
    )


def test_every_attempt_is_counted_whether_it_worked_or_not():
    register("fr.wikipedia.org")
    schedule.settle("fr.wikipedia.org", LANE, schedule.Outcome())
    schedule.settle("fr.wikipedia.org", LANE, schedule.Outcome(error="boom"))
    assert state("fr.wikipedia.org")["runs"] == 2


def test_starting_a_wiki_is_recorded_before_the_work_not_after():
    """A run killed mid-sweep leaves no success anywhere; so does a wiki it never
    reached. The start stamp is the only thing that tells the two apart."""
    register("en.wikipedia.org")
    schedule.start("en.wikipedia.org", LANE)
    assert state("en.wikipedia.org")["started"] is not None
    assert state("en.wikipedia.org")["success"] is None
    # And it did not consume the wiki's turn.
    assert [entry.wiki for entry in schedule.due(LANE)] == ["en.wikipedia.org"]


# --- the budget ------------------------------------------------------------


class Clock:
    """A monotonic clock the test advances by hand."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def tick(self, seconds):
        self.now += seconds


def test_a_run_has_time_until_its_allowance_is_spent():
    clock = Clock()
    budget = schedule.Budget(600, clock=clock)
    assert budget.remains()
    clock.tick(599)
    assert budget.remains()
    clock.tick(1)
    assert not budget.remains()


def test_the_budget_reports_what_is_left_and_never_goes_negative():
    clock = Clock()
    budget = schedule.Budget(600, clock=clock)
    clock.tick(150)
    assert (budget.spent(), budget.left()) == (150, 450)
    clock.tick(10_000)
    assert budget.left() == 0


def test_a_wiki_already_started_is_not_interrupted_by_the_deadline():
    """Checked before a wiki, not during one: a half-covered wiki is worse than
    a run that finished four minutes late."""
    clock = Clock()
    budget = schedule.Budget(60, clock=clock)
    covered = []
    for wiki in ("a", "b", "c"):
        if not budget.remains():
            break
        covered.append(wiki)
        clock.tick(45)
    assert covered == ["a", "b"]


def test_a_run_with_no_allowance_covers_nothing():
    assert not schedule.Budget(0).remains()
