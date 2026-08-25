"""Tests for the gadget census job entrypoint."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import gadget_census as job  # noqa: E402

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


def test_the_job_defaults_to_the_pilot_wikis(monkeypatch, capsys, wiki):
    monkeypatch.delenv("GADGET_WIKIS", raising=False)

    assert job.main() == 0

    assert wiki.asked == ["fr.wikipedia.org", "meta.wikimedia.org"]
    assert "gadget-catalogue: wiki=meta.wikimedia.org" in capsys.readouterr().out


def test_the_dating_pass_runs_between_the_read_and_the_catalogue(monkeypatch, capsys, wiki):
    """Order is the point: a date stamped after the catalogue was built ships one run late."""
    monkeypatch.setenv("GADGET_WIKIS", FRWIKI)
    monkeypatch.setattr(job.gadget_creation_dates, "backfill", lambda wikis: {wikis[0]: 3})

    assert job.main() == 0

    out = capsys.readouterr().out
    assert f"gadget-creation-dates: wiki={FRWIKI} replica=yes stamped=3" in out
    assert out.index("gadget-inventory:") < out.index("gadget-creation-dates:") < out.index("gadget-catalogue:")


def test_a_wiki_with_no_replica_to_read_is_reported_as_such_and_still_catalogued(monkeypatch, capsys, wiki):
    """Toolforge credentials are how this lane reads dates; without them the census still runs."""
    monkeypatch.setenv("GADGET_WIKIS", FRWIKI)
    monkeypatch.setattr(job.gadget_creation_dates, "backfill", lambda _wikis: {})

    assert job.main() == 0

    out = capsys.readouterr().out
    assert f"gadget-creation-dates: wiki={FRWIKI} replica=no stamped=0" in out
    assert "gadget-catalogue: wiki=fr.wikipedia.org declared=2 written=1" in out


def test_last_edit_dates_are_stamped_before_the_catalogue_too(monkeypatch, capsys, wiki):
    """The same reason the creation pass runs first: a date stamped late ships a run late."""
    monkeypatch.setenv("GADGET_WIKIS", FRWIKI)
    monkeypatch.setattr(job.wiki_edit_dates, "backfill_gadgets", lambda wikis: {wikis[0]: 4})

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
    monkeypatch.setattr(job.wiki_edit_dates, "backfill_gadgets", lambda wikis: asked.append(wikis) or {wikis[0]: 0})

    assert job.main() == 0
    assert job.main() == 0

    # Twice, on two runs that read the identical definition page both times.
    assert asked == [[FRWIKI], [FRWIKI]]
    assert capsys.readouterr().out.count(f"gadget-edit-dates: wiki={FRWIKI} replica=yes stamped=0") == 2


def test_a_wiki_with_no_replica_reports_no_last_edits_and_is_still_catalogued(monkeypatch, capsys, wiki):
    """Dates are a Toolforge-only enrichment; the census is not, and must not stop for them."""
    monkeypatch.setenv("GADGET_WIKIS", FRWIKI)
    monkeypatch.setattr(job.wiki_edit_dates, "backfill_gadgets", lambda _wikis: {})

    assert job.main() == 0

    out = capsys.readouterr().out
    assert f"gadget-edit-dates: wiki={FRWIKI} replica=no stamped=0" in out
    assert "gadget-catalogue: wiki=fr.wikipedia.org declared=2 written=1" in out
