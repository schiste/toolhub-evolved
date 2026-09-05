# SPDX-License-Identifier: GPL-3.0-or-later
"""Counting how many records a projected field actually reaches.

The tool exists because two changes shipped correct and unreachable, so what is
tested here is the part that would have caught them: that reach is reported per
lane rather than averaged, and that `empty` counts the records a change could
still fill. An average over all three kinds is what hid `audiences` sitting at
3.6% on Toolhub tools and 0% on both wiki lanes.
"""

import importlib.util
import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db  # noqa: E402
from backend.models import CatalogToolProjection  # noqa: E402

spec = importlib.util.spec_from_file_location("field_reach", ROOT / "tools" / "field_reach.py")
field_reach = importlib.util.module_from_spec(spec)
spec.loader.exec_module(field_reach)


@pytest.fixture(autouse=True)
def _database():
    application = Flask(__name__)
    backend.register(
        application,
        db_url="sqlite://",
        secret_key="test-secret",
        trusted_hosts=backend.LOCAL_TRUSTED_HOSTS + backend.DEFAULT_TRUSTED_HOSTS,
    )
    with application.app_context():
        yield


def _projection(name, record, provenance=None):
    with db.session_scope() as session:
        session.add(
            CatalogToolProjection(
                tool_name=name,
                effective_record=record,
                provenance=provenance or {},
                validation={},
                source_timestamps={},
            )
        )


def test_a_records_kind_is_read_from_its_catalogue_name():
    assert field_reach.kind_of("userscript-en.wikipedia.org-a-b.js") == "user script"
    assert field_reach.kind_of("gadget-fr.wikipedia.org-hotcat") == "gadget"
    assert field_reach.kind_of("hay-directory") == "toolhub tool"


def test_reach_is_reported_per_lane_rather_than_averaged():
    """The average is what hides the gap worth seeing.

    `audiences` stood at 3.6% across Toolhub tools and 0% across both wiki
    lanes; one number for all three would have read as 0.4% and said nothing
    about where the 51,266 empty records were.
    """
    _projection("hay-directory", {"audiences": ["editor"]})
    _projection("gadget-fr.wikipedia.org-hotcat", {"audiences": []})
    _projection("userscript-en.wikipedia.org-a-b.js", {})
    report = field_reach.survey(("audiences",))["audiences"]
    assert report["filled"] == {"toolhub tool": 1}
    assert report["empty"] == {"toolhub tool": 0, "gadget": 1, "user script": 1}


def test_the_empty_column_is_the_population_a_change_could_reach():
    """The number to read before shipping something that fills a field."""
    for index in range(3):
        _projection(f"gadget-fr.wikipedia.org-g{index}", {"keywords": ["a"]})
    _projection("gadget-fr.wikipedia.org-bare", {})
    report = field_reach.survey(("keywords",))["keywords"]
    assert report["empty"]["gadget"] == 1
    assert report["filled"]["gadget"] == 3


def test_a_field_is_credited_to_whichever_source_won_it():
    """`by source` says who is answering, which is the check after shipping."""
    _projection(
        "gadget-fr.wikipedia.org-hotcat",
        {"keywords": ["categories"]},
        {"keywords": [{"value": "categories", "source": "llm_inference", "effective": True}]},
    )
    _projection(
        "hay-directory",
        {"keywords": ["directory"]},
        {"keywords": [{"value": "directory", "source": "official_toolhub", "effective": True}]},
    )
    assert field_reach.survey(("keywords",))["keywords"]["by source"] == {
        "llm_inference": 1,
        "official_toolhub": 1,
    }


def test_a_value_with_no_provenance_is_counted_rather_than_dropped():
    """Filled and unattributed is a real state, and silently omitting it would
    make the source breakdown disagree with the filled count."""
    _projection("hay-directory", {"keywords": ["directory"]})
    report = field_reach.survey(("keywords",))["keywords"]
    assert report["by source"] == {"unrecorded": 1}
    assert sum(report["by source"].values()) == sum(report["filled"].values())


def test_asking_for_a_field_the_projection_does_not_carry_is_refused(capsys):
    """A typo must not read as a field nobody has filled."""
    assert field_reach.main(["--field", "audienses"]) == 2
    assert "not projected fields" in capsys.readouterr().err


def test_running_without_a_database_says_so_rather_than_reporting_zero(monkeypatch, capsys):
    """Zero reach and no catalogue are different answers, and one is alarming."""
    monkeypatch.delenv("TOOLHUB_DB_URL", raising=False)
    assert field_reach.main([]) == 2
    assert "TOOLHUB_DB_URL" in capsys.readouterr().err


def test_the_widest_gap_is_reported_first():
    """The field with most left to fill is the one the reader came for."""
    _projection("hay-directory", {"keywords": ["a"], "audiences": ["editor"]})
    _projection("gadget-fr.wikipedia.org-g", {"keywords": ["a"]})
    rendered = field_reach.render(field_reach.survey(("keywords", "audiences")))
    assert rendered.index("audiences") < rendered.index("keywords")
