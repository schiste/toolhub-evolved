# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only live LiftWing digest preflight tests."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import digest_liftwing_preflight as preflight  # noqa: E402
from backend import digests  # noqa: E402


def facts(count=2):
    return [
        {
            "name": f"tool-{index}",
            "title": f"Tool {index}",
            "description": f"Tool {index} supports a documented workflow.",
            "toolhub_url": f"https://toolhub.wikimedia.org/tools/tool-{index}",
            "authors": [],
            "maintainers": [],
        }
        for index in range(count)
    ]


def editorial(source):
    return {
        "introduction": "These tools support distinct, documented Wikimedia workflows.",
        "highlights": [
            {"tool_name": fact["name"], "blurb": fact["description"]} for fact in source
        ],
    }


def test_fetch_edition_facts_is_bounded_and_validated():
    class Response:
        content = b"{}"

        def raise_for_status(self):
            return None

        def json(self):
            return {"tools": [{"facts": fact} for fact in facts()]}

    class Session:
        def get(self, url, timeout):
            assert url.endswith("/v1/digests/daily/2026-08-13/")
            assert timeout == preflight.SOURCE_TIMEOUT_SECONDS
            return Response()

    period = digests.period_from_key("daily", "2026-08-13")
    assert len(preflight.fetch_edition_facts(period, session=Session())) == 2
    with pytest.raises(ValueError, match="HTTPS origin"):
        preflight.clean_public_base("http://example.test/path")


def test_preflight_runs_model_validation_and_rendering_without_writes(monkeypatch):
    source = facts()
    monkeypatch.setattr(preflight, "fetch_edition_facts", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(
        digests,
        "generate_editorial",
        lambda supplied, _cadence: (editorial(supplied), "llm-qwen36-27b", False, {}),
    )

    result = preflight.run([digests.period_from_key("daily", "2026-08-13")])

    assert result["safe"] is True
    assert result["databaseWrites"] is False
    edition = result["editions"][0]
    assert edition["toolCount"] == 2
    assert edition["selectedToolCount"] == 2
    assert edition["renderedBytes"]["html"] > 0


def test_preflight_exposes_generation_failure(monkeypatch):
    monkeypatch.setattr(preflight, "fetch_edition_facts", lambda *_args, **_kwargs: facts())
    monkeypatch.setattr(
        digests,
        "generate_editorial",
        lambda *_args: (
            editorial(facts()),
            "llm-qwen36-27b",
            True,
            {"_toolhub_generation_error": "invalid evidence"},
        ),
    )

    with pytest.raises(RuntimeError, match="invalid evidence"):
        preflight.run([digests.period_from_key("daily", "2026-08-13")])
