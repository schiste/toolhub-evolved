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
    monkeypatch.setattr(job.userscript_creation_dates, "backfill", lambda wikis: {wikis[0]: 0})
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
    monkeypatch.setattr(job.wiki_edit_dates, "backfill_scripts", lambda wikis: {wikis[0]: 7})

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
    monkeypatch.setattr(job.wiki_edit_dates, "backfill_scripts", lambda wikis: asked.append(wikis) or {wikis[0]: 0})

    assert job.main() == 0
    assert job.main() == 0

    # Two runs, both of which wrote nothing and fetched nothing.
    assert asked == [[FRWIKI], [FRWIKI]]
    assert capsys.readouterr().out.count(f"userscript-edit-dates: wiki={FRWIKI} replica=yes stamped=0") == 2


def test_every_configured_wiki_is_dated_not_only_the_first(monkeypatch, capsys, passes):
    monkeypatch.setenv("USERSCRIPT_WIKIS", f"{FRWIKI},meta.wikimedia.org")
    asked = []
    monkeypatch.setattr(job.wiki_edit_dates, "backfill_scripts", lambda wikis: asked.append(wikis[0]) or {wikis[0]: 1})

    assert job.main() == 0

    assert asked == [FRWIKI, "meta.wikimedia.org"]
    assert "userscript-edit-dates: wiki=meta.wikimedia.org replica=yes stamped=1" in capsys.readouterr().out


def test_a_wiki_with_no_replica_reports_no_last_edits_and_is_still_projected(monkeypatch, capsys, passes):
    """Dates are a Toolforge-only enrichment; the census is not, and must not stop for them."""
    monkeypatch.setattr(job.wiki_edit_dates, "backfill_scripts", lambda _wikis: {})

    assert job.main() == 0

    out = capsys.readouterr().out
    assert f"userscript-edit-dates: wiki={FRWIKI} replica=no stamped=0" in out
    assert f"userscript-directory: wiki={FRWIKI}" in out
    assert f"userscript-catalogue: wiki={FRWIKI}" in out
