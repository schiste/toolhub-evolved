# SPDX-License-Identifier: GPL-3.0-or-later
"""Small edge contracts that do not warrant another integration fixture."""

import sys
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
import backend.v1 as v1_api  # noqa: E402
from backend import db, tool_summaries  # noqa: E402


def test_card_people_discards_invalid_people_and_relationships():
    assert tool_summaries._card_people(  # noqa: SLF001 - direct compact-projection contract
        [
            "wrong",
            {"id": "person", "relationships": ["wrong", {"type": "observer"}]},
        ]
    ) == []


def test_recent_feed_turns_local_replica_failures_into_a_gateway_error(monkeypatch):
    db.configure("sqlite://")
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test")
    application.config["TESTING"] = True

    def fail(*_args, **_kwargs):
        raise RuntimeError("replica unavailable")

    monkeypatch.setattr(v1_api, "_feed_payload", fail)
    response = application.test_client().get("/feeds/recent.xml")

    assert response.status_code == 502
    assert b"replica unavailable" in response.data
