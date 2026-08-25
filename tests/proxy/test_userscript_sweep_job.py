"""Tests for the user-script census job entrypoint.

The passes it runs and the order it runs them in are the contract here -- the
work each one does has its own tests. What this file pins down is that every
run performs every pass, on every configured wiki, whether or not the wiki had
anything new to say.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import userscript_sweep as job  # noqa: E402
from backend import db, wiki_schedule  # noqa: E402
from backend.models import WikiLaneState, utcnow  # noqa: E402

FRWIKI = "fr.wikipedia.org"

WATCH = {
    "wiki": FRWIKI,
    "mode": "watch",
    "asked": 0,
    "fetched": 0,
    "written": 0,
    "skipped": 0,
    "unreadable": 0,
    "oversized": 0,
    "collisions": 0,
    "lagged": False,
    "cursor": "20260824000000",
    "windows": 1,
    "behind": False,
}


@pytest.fixture
def passes(monkeypatch):
    """Stand in for every pass, so the job under test is only the sequence of them."""
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    monkeypatch.setenv("USERSCRIPT_WIKIS", FRWIKI)
    monkeypatch.setattr(job, "WikimediaClient", lambda: SimpleNamespace(request=lambda *_a, **_k: {}))
    monkeypatch.setattr(job.userscript_sweep, "run", lambda *_args, **_kwargs: dict(WATCH))
    monkeypatch.setattr(job.userscript_creation_dates, "backfill", lambda wikis, **_kwargs: {wikis[0]: 0})
    monkeypatch.setattr(
        job.userscript_projection,
        "project",
        lambda wiki: {"wiki": wiki, "candidates": 0, "originals": 0, "active": 0, "archive": 0},
    )
    monkeypatch.setattr(
        job.userscript_toolinfo,
        "synchronize",
        lambda wiki: {
            "wiki": wiki,
            "originals": 0,
            "written": 0,
            "unchanged": 0,
            "stylesheet": 0,
            "unnamed": 0,
            "duplicate": 0,
            "conflicted": 0,
            "retired": 0,
        },
    )


def test_last_edits_are_stamped_before_the_directory_is_projected(monkeypatch, capsys, passes):
    """The projection copies the date onto its entries, so it has to be stamped first.

    A directory rebuilt before the pages it reads were dated publishes last
    run's dates, and the wrong ones are worse than none: the whole point of the
    field is telling a reader whether a script is still looked after.
    """
    monkeypatch.setattr(job.wiki_edit_dates, "backfill_scripts", lambda wikis, **_kwargs: {wikis[0]: 7})

    assert job.main() == 0

    out = capsys.readouterr().out
    assert f"userscript-edit-dates: wiki={FRWIKI} replica=yes stamped=7" in out
    assert out.index("userscript-creation-dates:") < out.index("userscript-edit-dates:")
    assert out.index("userscript-edit-dates:") < out.index("userscript-directory:")


def test_every_run_asks_for_last_edits_however_little_the_watch_found(monkeypatch, capsys, passes):
    """This is what makes the dates checked rather than backfilled once.

    A watch fetches only pages that moved, and a sweep skips pages whose latest
    revision it already holds -- so the pages either mode can date are the ones
    already dated. Asking the replica about the whole corpus every run is the
    only thing that reaches a page ingested before the field existed.
    """
    asked = []
    monkeypatch.setattr(job.wiki_edit_dates, "backfill_scripts", lambda wikis, **_kwargs: asked.append(wikis) or {wikis[0]: 0})

    assert job.main() == 0
    assert job.main() == 0

    # Two runs, both of which wrote nothing and fetched nothing.
    assert asked == [[FRWIKI], [FRWIKI]]
    assert capsys.readouterr().out.count(f"userscript-edit-dates: wiki={FRWIKI} replica=yes stamped=0") == 2


def test_every_configured_wiki_is_dated_not_only_the_first(monkeypatch, capsys, passes):
    monkeypatch.setenv("USERSCRIPT_WIKIS", f"{FRWIKI},meta.wikimedia.org")
    asked = []
    monkeypatch.setattr(job.wiki_edit_dates, "backfill_scripts", lambda wikis, **_kwargs: asked.append(wikis[0]) or {wikis[0]: 1})

    assert job.main() == 0

    assert asked == [FRWIKI, "meta.wikimedia.org"]
    assert "userscript-edit-dates: wiki=meta.wikimedia.org replica=yes stamped=1" in capsys.readouterr().out


def test_a_wiki_with_no_replica_reports_no_last_edits_and_is_still_projected(monkeypatch, capsys, passes):
    """Dates are a Toolforge-only enrichment; the census is not, and must not stop for them."""
    monkeypatch.setattr(job.wiki_edit_dates, "backfill_scripts", lambda _wikis, **_kwargs: {})

    assert job.main() == 0

    out = capsys.readouterr().out
    assert f"userscript-edit-dates: wiki={FRWIKI} replica=no stamped=0" in out
    assert f"userscript-directory: wiki={FRWIKI}" in out
    assert f"userscript-catalogue: wiki={FRWIKI}" in out


# --- a thousand corpora, one hour ------------------------------------------


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


def watching(wiki):
    return {**WATCH, "wiki": wiki}


@pytest.fixture
def covered(monkeypatch, passes):
    """Record which wikis a run actually got through, in order."""
    seen = []
    monkeypatch.setattr(job.userscript_sweep, "run", lambda _request, wiki, **_kwargs: watching(wiki))
    monkeypatch.setattr(job.wiki_edit_dates, "backfill_scripts", lambda wikis, **_kwargs: {wikis[0]: 0})
    project = job.userscript_projection.project
    monkeypatch.setattr(job.userscript_projection, "project", lambda wiki: seen.append(wiki) or project(wiki))
    monkeypatch.delenv("USERSCRIPT_WIKIS", raising=False)
    return seen


def test_the_queue_decides_which_wikis_a_run_covers_when_nobody_named_any(monkeypatch, capsys, covered):
    """The hourly run used to cover a hand-maintained list of three. Now it covers what is owed."""
    monkeypatch.setattr(job.wiki_schedule, "due", lambda _lane, **_kwargs: queued("es.wikipedia.org", "de.wikipedia.org"))

    assert job.main() == 0

    assert covered == ["es.wikipedia.org", "de.wikipedia.org"]
    assert "userscript-census: queued=2 covered=2 failed=0" in capsys.readouterr().out


def test_an_operator_naming_wikis_still_outranks_the_queue(monkeypatch, capsys, covered):
    """`USERSCRIPT_WIKIS=... USERSCRIPT_SWEEP=1` is how one big wiki is swept on demand."""
    monkeypatch.setenv("USERSCRIPT_WIKIS", "en.wikipedia.org")
    monkeypatch.setattr(job.wiki_schedule, "due", lambda _lane, **_kwargs: queued("es.wikipedia.org"))

    assert job.main() == 0

    assert covered == ["en.wikipedia.org"]
    assert "userscript-census: queued=1 covered=1 failed=0" in capsys.readouterr().out


def test_a_deployment_with_no_registry_yet_still_covers_the_wikis_it_always_did(monkeypatch, capsys, covered):
    """An empty queue on an empty registry means "nobody has said which wikis exist" -- not "all done"."""
    monkeypatch.setattr(job.wiki_schedule, "due", lambda _lane, **_kwargs: ())
    monkeypatch.setattr(job.wiki_registry, "projects", lambda **_kwargs: ())

    assert job.main() == 0

    assert covered == ["fr.wikipedia.org", "meta.wikimedia.org", "en.wikipedia.org"]
    assert "userscript-census: queued=3 covered=3 failed=0" in capsys.readouterr().out


def test_a_registry_that_owes_nobody_a_turn_covers_nobody(monkeypatch, capsys, covered):
    """The healthy steady state, and the one case that must not fall back."""
    monkeypatch.setattr(job.wiki_schedule, "due", lambda _lane, **_kwargs: ())
    monkeypatch.setattr(job.wiki_registry, "projects", lambda **_kwargs: ("fr.wikipedia.org",))

    assert job.main() == 0

    assert covered == []
    assert "userscript-census: queued=0 covered=0 failed=0" in capsys.readouterr().out


def test_a_run_out_of_time_stops_between_wikis_and_leaves_the_rest_queued(monkeypatch, capsys, covered):
    """A sweep is never interrupted mid-corpus; what a spent budget costs is the wikis not started."""
    monkeypatch.setenv("USERSCRIPT_BUDGET_SECONDS", "10")
    monkeypatch.setattr(job.wiki_schedule, "due", lambda _lane, **_kwargs: queued("es.wikipedia.org", "de.wikipedia.org"))
    real = job.wiki_schedule.Budget
    ticks = iter(range(1000))
    monkeypatch.setattr(job.wiki_schedule, "Budget", lambda seconds: real(seconds, clock=lambda: next(ticks) * 6))

    assert job.main() == 0

    assert covered == ["es.wikipedia.org"]
    assert "userscript-census: queued=2 covered=1 failed=0" in capsys.readouterr().out
    assert lane_state("de.wikipedia.org") is None


def test_one_wikis_failure_costs_that_wiki_its_turn_and_not_the_run(monkeypatch, capsys, covered):
    """The 2026-08-23 lesson: one Meta page raised, and because enwiki was third, enwiki starved.

    Ordering decided which corpus stopped converging, which is not a thing
    ordering should decide. Now the exception belongs to the wiki that raised
    it: recorded, backed off, and left behind.
    """
    monkeypatch.setattr(job.wiki_schedule, "due", lambda _lane, **_kwargs: queued("meta.wikimedia.org", "en.wikipedia.org"))

    def one_bad_wiki(_request, wiki, **_kwargs):
        if wiki == "meta.wikimedia.org":
            message = "two spellings of one load target"
            raise RuntimeError(message)
        return watching(wiki)

    monkeypatch.setattr(job.userscript_sweep, "run", one_bad_wiki)

    assert job.main() == 0

    out = capsys.readouterr().out
    assert covered == ["en.wikipedia.org"]
    assert "userscript-census: wiki=meta.wikimedia.org failed error=RuntimeError" in out
    assert "userscript-census: queued=2 covered=1 failed=1" in out
    assert lane_state("meta.wikimedia.org") == {"failures": 1, "error": "RuntimeError", "runs": 1}


def test_a_run_fails_only_when_every_wiki_it_attempted_failed(monkeypatch, covered):
    """No credentials, no network, a broken deployment -- the shapes still worth escalating."""
    monkeypatch.setattr(job.wiki_schedule, "due", lambda _lane, **_kwargs: queued("es.wikipedia.org", "de.wikipedia.org"))

    def every_wiki_bad(_request, _wiki, **_kwargs):
        message = "no network"
        raise RuntimeError(message)

    monkeypatch.setattr(job.userscript_sweep, "run", every_wiki_bad)

    with pytest.raises(job.CensusIncompleteError, match="every wiki attempted"):
        job.main()
