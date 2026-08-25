"""Tests for the gadget census job entrypoint."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import gadget_census as job  # noqa: E402
from backend import db, wiki_schedule  # noqa: E402
from backend.models import WikiLaneState, utcnow  # noqa: E402

FRWIKI = "fr.wikipedia.org"

DEFINITION = """
== Appearance ==
* Popups[ResourceLoader]|Popups.js
* Internals[ResourceLoader|hidden]|Internals.js
"""


class FakeWiki:
    """An Action API answering every wiki with the same definition page."""

    def __init__(self):
        self.asked = []

    def request(self, domain, _method, params):
        self.asked.append(domain)
        revision = {"slots": {"main": {"content": DEFINITION}}}
        if "ids" in str(params.get("rvprop", "")).split("|"):
            # Answer with what was asked for and nothing more, so a query that
            # stops asking for the id fails here instead of in production.
            revision["revid"] = 1
        return {"query": {"pages": [{"title": "MediaWiki:Gadgets-definition", "revisions": [revision]}]}}


@pytest.fixture
def wiki(monkeypatch):
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    fake = FakeWiki()
    monkeypatch.setattr(job, "WikimediaClient", lambda: fake)
    return fake


def test_the_job_reads_each_configured_wiki_once_and_catalogues_it(monkeypatch, capsys, wiki):
    monkeypatch.setenv("GADGET_WIKIS", "fr.wikipedia.org, en.wikipedia.org ,")

    assert job.main() == 0

    # One request per wiki is the economics of this lane: the definition page
    # is the whole inventory.
    assert wiki.asked == ["fr.wikipedia.org", "en.wikipedia.org"]
    out = capsys.readouterr().out
    assert "gadget-inventory: wiki=fr.wikipedia.org read=yes reason=read declared=2" in out
    assert "gadget-catalogue: wiki=fr.wikipedia.org declared=2 written=1" in out
    assert "hidden=1" in out


def test_a_deployment_with_no_registry_yet_still_covers_the_wikis_it_always_did(monkeypatch, capsys, wiki):
    """The first run after a deployment happens before the weekly registry job.

    An empty queue on an empty registry is "nobody has told this job which wikis
    exist yet", not "every wiki is up to date", and the two want opposite
    reactions. Falling back to the wikis this lane covered for its whole life
    means a deployment never has a census-shaped gap in it.
    """
    monkeypatch.delenv("GADGET_WIKIS", raising=False)

    assert job.main() == 0

    assert wiki.asked == ["fr.wikipedia.org", "meta.wikimedia.org", "en.wikipedia.org"]
    assert "gadget-catalogue: wiki=meta.wikimedia.org" in capsys.readouterr().out


def test_the_dating_pass_runs_between_the_read_and_the_catalogue(monkeypatch, capsys, wiki):
    """Order is the point: a date stamped after the catalogue was built ships one run late."""
    monkeypatch.setenv("GADGET_WIKIS", FRWIKI)
    monkeypatch.setattr(job.gadget_creation_dates, "backfill", lambda wikis, **_kwargs: {wikis[0]: 3})

    assert job.main() == 0

    out = capsys.readouterr().out
    assert f"gadget-creation-dates: wiki={FRWIKI} replica=yes stamped=3" in out
    assert out.index("gadget-inventory:") < out.index("gadget-creation-dates:") < out.index("gadget-catalogue:")


def test_a_wiki_with_no_replica_to_read_is_reported_as_such_and_still_catalogued(monkeypatch, capsys, wiki):
    """Toolforge credentials are how this lane reads dates; without them the census still runs."""
    monkeypatch.setenv("GADGET_WIKIS", FRWIKI)
    monkeypatch.setattr(job.gadget_creation_dates, "backfill", lambda _wikis, **_kwargs: {})

    assert job.main() == 0

    out = capsys.readouterr().out
    assert f"gadget-creation-dates: wiki={FRWIKI} replica=no stamped=0" in out
    assert "gadget-catalogue: wiki=fr.wikipedia.org declared=2 written=1" in out


def test_last_edit_dates_are_stamped_before_the_catalogue_too(monkeypatch, capsys, wiki):
    """The same reason the creation pass runs first: a date stamped late ships a run late."""
    monkeypatch.setenv("GADGET_WIKIS", FRWIKI)
    monkeypatch.setattr(job.wiki_edit_dates, "backfill_gadgets", lambda wikis, **_kwargs: {wikis[0]: 4})

    assert job.main() == 0

    out = capsys.readouterr().out
    assert f"gadget-edit-dates: wiki={FRWIKI} replica=yes stamped=4" in out
    assert out.index("gadget-creation-dates:") < out.index("gadget-edit-dates:") < out.index("gadget-catalogue:")


def test_every_run_asks_for_last_edits_even_when_the_definitions_did_not_move(monkeypatch, capsys, wiki):
    """A gadget's code changes without its declaration changing, so this pass is never skipped.

    The inventory can honestly report a wiki as unchanged on the very run one of
    its gadgets was rewritten -- `MediaWiki:Gadgets-definition` says which pages
    a gadget is made of, not what is in them. Dating only what the inventory
    touched would leave those gadgets showing the date of whichever edit last
    happened to alter a declaration.
    """
    monkeypatch.setenv("GADGET_WIKIS", FRWIKI)
    asked = []
    monkeypatch.setattr(job.wiki_edit_dates, "backfill_gadgets", lambda wikis, **_kwargs: asked.append(wikis) or {wikis[0]: 0})

    assert job.main() == 0
    assert job.main() == 0

    # Twice, on two runs that read the identical definition page both times.
    assert asked == [[FRWIKI], [FRWIKI]]
    assert capsys.readouterr().out.count(f"gadget-edit-dates: wiki={FRWIKI} replica=yes stamped=0") == 2


def test_a_wiki_with_no_replica_reports_no_last_edits_and_is_still_catalogued(monkeypatch, capsys, wiki):
    """Dates are a Toolforge-only enrichment; the census is not, and must not stop for them."""
    monkeypatch.setenv("GADGET_WIKIS", FRWIKI)
    monkeypatch.setattr(job.wiki_edit_dates, "backfill_gadgets", lambda _wikis, **_kwargs: {})

    assert job.main() == 0

    out = capsys.readouterr().out
    assert f"gadget-edit-dates: wiki={FRWIKI} replica=no stamped=0" in out
    assert "gadget-catalogue: wiki=fr.wikipedia.org declared=2 written=1" in out


# --- a thousand wikis, one run ---------------------------------------------

INVENTORY = {"read": True, "reason": "read", "declared": 0, "added": 0, "updated": 0, "folded": 0, "retired": 0}


def queued(*wikis, closed=False):
    """The queue the scheduler would hand a run, without a registry to build it from."""
    now = utcnow()
    return tuple(
        wiki_schedule.Due(wiki=wiki, dbname=wiki.split(".")[0], section="s3", closed=closed, due_at=now)
        for wiki in wikis
    )


def lane_state(wiki):
    with db.session_scope() as session:
        row = session.query(WikiLaneState).filter_by(wiki=wiki, lane=job.LANE).one_or_none()
        return None if row is None else {"failures": row.consecutive_failures, "error": row.last_error, "runs": row.runs}


def budget_spent_after(one_wiki_worth):
    """A Budget whose clock advances by one wiki's worth every time it is asked."""
    real = wiki_schedule.Budget
    ticks = iter(range(1000))
    return lambda seconds: real(seconds, clock=lambda: next(ticks) * one_wiki_worth)


def test_the_queue_decides_which_wikis_a_run_covers_when_nobody_named_any(monkeypatch, capsys, wiki):
    """The whole point of the change: the wikis come from the schedule, not from an env var.

    Three wikis were a list somebody maintained by hand. A thousand cannot be,
    so the run asks which wikis are owed a turn and covers those, and the only
    thing left in the environment is the budget.
    """
    monkeypatch.delenv("GADGET_WIKIS", raising=False)
    monkeypatch.setattr(job.wiki_schedule, "due", lambda _lane, **_kwargs: queued("es.wikipedia.org", "de.wikipedia.org"))

    assert job.main() == 0

    assert wiki.asked == ["es.wikipedia.org", "de.wikipedia.org"]
    assert "gadget-census: queued=2 covered=2 failed=0" in capsys.readouterr().out
    assert lane_state("de.wikipedia.org")["runs"] == 1


def test_a_run_out_of_time_stops_between_wikis_and_leaves_the_rest_queued(monkeypatch, capsys, wiki):
    """A budget is what makes a thousand wikis a schedule rather than a timeout.

    It is checked before a wiki rather than during one, so what a spent budget
    costs is the wikis not started -- and they are only more overdue next run,
    which is exactly how the queue decides who goes first.
    """
    monkeypatch.delenv("GADGET_WIKIS", raising=False)
    monkeypatch.setenv("GADGET_BUDGET_SECONDS", "10")
    monkeypatch.setattr(job.wiki_schedule, "due", lambda _lane, **_kwargs: queued("es.wikipedia.org", "de.wikipedia.org"))
    monkeypatch.setattr(job.wiki_schedule, "Budget", budget_spent_after(6))

    assert job.main() == 0

    assert wiki.asked == ["es.wikipedia.org"]
    assert "gadget-census: queued=2 covered=1 failed=0" in capsys.readouterr().out
    # The wiki the run never reached was never started, so nothing about it moved.
    assert lane_state("de.wikipedia.org") is None


def test_one_wikis_failure_costs_that_wiki_its_turn_and_not_the_run(monkeypatch, capsys, wiki):
    """With three wikis an unreachable one meant something was wrong. With a thousand it does not.

    The job guard disables a job after three consecutive failures, so a run that
    failed for one wiki's bad afternoon would starve the other nine hundred and
    ninety-nine within three ticks. The failure is recorded on the wiki, which
    backs it off and leaves its place in the rotation.
    """
    monkeypatch.delenv("GADGET_WIKIS", raising=False)
    monkeypatch.setattr(job.wiki_schedule, "due", lambda _lane, **_kwargs: queued("es.wikipedia.org", "de.wikipedia.org"))

    def one_bad_wiki(_request, asked):
        if asked == "es.wikipedia.org":
            message = "replica went away"
            raise RuntimeError(message)
        return {"wiki": asked, **INVENTORY}

    monkeypatch.setattr(job.gadget_inventory, "ingest", one_bad_wiki)

    assert job.main() == 0

    out = capsys.readouterr().out
    assert "gadget-census: wiki=es.wikipedia.org failed error=RuntimeError: replica went away" in out
    assert "gadget-census: queued=2 covered=1 failed=1" in out
    assert lane_state("es.wikipedia.org") == {"failures": 1, "error": "RuntimeError", "runs": 1}
    assert lane_state("de.wikipedia.org")["failures"] == 0


def test_a_run_fails_only_when_every_wiki_it_attempted_failed(monkeypatch, wiki):
    """No credentials, no network, a broken deployment -- the shapes worth escalating."""
    monkeypatch.delenv("GADGET_WIKIS", raising=False)
    monkeypatch.setattr(job.wiki_schedule, "due", lambda _lane, **_kwargs: queued("es.wikipedia.org", "de.wikipedia.org"))

    def every_wiki_bad(_request, _asked):
        message = "no replica credentials"
        raise RuntimeError(message)

    monkeypatch.setattr(job.gadget_inventory, "ingest", every_wiki_bad)

    with pytest.raises(RuntimeError, match="every wiki attempted"):
        job.main()
