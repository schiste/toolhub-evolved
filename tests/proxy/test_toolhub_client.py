# SPDX-License-Identifier: GPL-3.0-or-later
"""Small direct-unit coverage for backend.toolhub helpers not exercised elsewhere."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import toolhub  # noqa: E402


def test_wikimedia_global_user_id_skips_blank_uid_and_falls_through_to_empty():
    # The matching identity is found (provider "wikimedia"), but its uid is
    # blank, so the loop must continue past it rather than returning early,
    # and finish with the trailing "" when nothing else matches either.
    profile = {
        "social_auth": [
            {"provider": "wikimedia", "uid": "   "},
            {"provider": "other", "uid": "999"},
        ]
    }
    assert toolhub.wikimedia_global_user_id(profile) == ""
