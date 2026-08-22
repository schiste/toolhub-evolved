# SPDX-License-Identifier: GPL-3.0-or-later
"""Digest event, UTC period, and immutable edition tests."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from flask import Flask
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
import backend.v1_digests as v1_digests_api  # noqa: E402
import digest_audit  # noqa: E402
import digest_deliver  # noqa: E402
import digest_publish  # noqa: E402
import digest_regenerate  # noqa: E402
from backend import db, digest_delivery, digests, wikimedia_delivery  # noqa: E402
from backend.models import (  # noqa: E402
    DigestDelivery,
    CanonicalToolCache,
    DigestEdition,
    DigestEditionTool,
    DigestGenerationAttempt,
    DigestOperationalState,
    DigestSubscription,
    Person,
    PersonProfile,
    ToolhubAccountProjection,
    ToolActivityEvent,
    ToolPersonRelationship,
    User,
    utcnow,
)
from backend.wikimedia_delivery import WikimediaClient, WikiEditResult, WikimediaAPIError, clean_wiki_domain  # noqa: E402


@pytest.fixture(autouse=True)
def _database():
    db.configure("sqlite://")
    db.init_schema()


def creation(ident: int, name: str, timestamp: str, *, parent_id: int | None = None) -> dict:
    return {
        "id": ident,
        "timestamp": timestamp,
        "content_type": "tool",
        "content_id": name,
        "parent_id": parent_id,
    }


def test_capture_recent_rows_keeps_only_valid_tool_creations_and_is_idempotent():
    rows = [
        creation(1, "new-tool", "2026-08-12T23:59:59Z"),
        creation(2, "updated-tool", "2026-08-12T10:00:00Z", parent_id=1),
        {"id": 3, "timestamp": "2026-08-12T10:00:00Z", "content_type": "list", "content_id": "4"},
        creation(4, "bad-time", "not-a-date"),
    ]

    assert digests.capture_recent_rows(rows, captured_at=datetime(2026, 8, 13, 0, 2)) == 1
    assert digests.capture_recent_rows(rows, captured_at=datetime(2026, 8, 13, 0, 3)) == 0
    with db.session_scope() as session:
        event = session.execute(select(ToolActivityEvent)).scalar_one()
        assert event.tool_name == "new-tool"
        assert event.event_at == datetime(2026, 8, 12, 23, 59, 59)
        assert event.captured_at == datetime(2026, 8, 13, 0, 2)


def test_due_periods_are_closed_utc_days_weeks_and_months_without_empty_periods():
    digests.capture_recent_rows([creation(1, "sunday-tool", "2026-08-09T23:59:59Z")])

    periods = digests.due_periods(now=datetime(2026, 8, 10, 6))

    assert [(period.cadence, period.key) for period in periods] == [
        ("daily", "2026-08-09"),
        ("weekly", "2026-W32"),
    ]
    assert all(period.end <= datetime(2026, 8, 10) for period in periods)


def test_due_periods_stop_at_the_backfill_horizon():
    digests.capture_recent_rows(
        [
            creation(1, "ancient-tool", "2021-10-10T12:00:00Z"),
            creation(2, "recent-tool", "2026-08-09T12:00:00Z"),
        ]
    )

    periods = digests.due_periods(now=datetime(2026, 8, 10, 6))

    keys = {(period.cadence, period.key) for period in periods}
    assert ("daily", "2026-08-09") in keys
    # Five years of closed periods must never re-enter the queue ahead of today's.
    assert not any(period.end < datetime(2026, 5, 12) for period in periods)
    assert ("daily", "2021-10-10") not in keys


def test_backfill_horizon_is_configurable_and_rejects_nonsense(monkeypatch):
    digests.capture_recent_rows([creation(1, "old-tool", "2026-06-01T12:00:00Z")])

    monkeypatch.setenv("DIGEST_BACKFILL_DAYS", "5")
    assert digests.due_periods(now=datetime(2026, 8, 10, 6)) == []

    monkeypatch.setenv("DIGEST_BACKFILL_DAYS", "120")
    assert ("daily", "2026-06-01") in {
        (period.cadence, period.key) for period in digests.due_periods(now=datetime(2026, 8, 10, 6))
    }

    monkeypatch.setenv("DIGEST_BACKFILL_DAYS", "0")
    with pytest.raises(ValueError, match="DIGEST_BACKFILL_DAYS"):
        digests.backfill_days()
    monkeypatch.setenv("DIGEST_BACKFILL_DAYS", "ninety")
    with pytest.raises(ValueError, match="DIGEST_BACKFILL_DAYS"):
        digests.backfill_days()


def test_generate_due_editions_caps_one_pass_and_reports_the_remainder(monkeypatch):
    monkeypatch.delenv("LIFTWING_API_URL", raising=False)
    digests.capture_recent_rows(
        [
            creation(1, "tool-a", "2026-08-07T12:00:00Z"),
            creation(2, "tool-b", "2026-08-08T12:00:00Z"),
            creation(3, "tool-c", "2026-08-09T12:00:00Z"),
        ]
    )
    pending = len(digests.due_periods(now=datetime(2026, 8, 10, 6)))
    assert pending > 2

    result = digests.generate_due_editions(now=datetime(2026, 8, 10, 6), limit=2)

    # Publication runs after generation in the same pass, so an uncapped
    # generation over a backlog would leave every edition it created unpublished.
    assert result["created"] == 2
    assert result["remaining"] == pending - 2
    assert len(digests.due_periods(now=datetime(2026, 8, 10, 6))) == pending - 2


def test_monthly_period_closes_only_after_utc_month_end():
    digests.capture_recent_rows([creation(1, "july-tool", "2026-07-31T23:59:59Z")])

    july = digests.due_periods(now=datetime(2026, 8, 1, 0, 1))

    assert ("monthly", "2026-07") in {(period.cadence, period.key) for period in july}


def test_create_edition_freezes_facts_and_uses_deterministic_fallback(monkeypatch):
    monkeypatch.delenv("LIFTWING_API_URL", raising=False)
    digests.capture_recent_rows([creation(1, "example", "2026-08-12T12:00:00Z")])
    with db.session_scope() as session:
        session.add(
            CanonicalToolCache(
                tool_name="example",
                record={
                    "name": "example",
                    "title": "Example",
                    "description": "Helps editors review changes.",
                    "url": "https://example.toolforge.org/",
                    "author": [
                        {"name": "Ada Lovelace", "developer_username": "ada-one"},
                        {"name": "Ada Lovelace", "developer_username": "ada-two"},
                        {"name": "Unresolved Author"},
                    ],
                },
                expires_at=datetime(2026, 8, 14),
                stale_until=datetime(2026, 8, 15),
            )
        )
        maintainer = Person(canonical_key="maintainer:grace", public_id="grace-id", display_name="Grace Hopper")
        session.add(maintainer)
        session.flush()
        session.add(PersonProfile(person_id=maintainer.id, visibility="public"))
        session.add(
            ToolPersonRelationship(
                tool_name="example",
                person_id=maintainer.id,
                relationship_type="maintainer",
                verification_status="verified",
                confidence=100,
            )
        )
        resolved_catalog_author = Person(
            canonical_key="author:ada",
            public_id="ada-id",
            display_name="Ada Lovelace",
        )
        session.add(resolved_catalog_author)
        session.flush()
        session.add(PersonProfile(person_id=resolved_catalog_author.id, visibility="public"))
        session.add(
            ToolPersonRelationship(
                tool_name="example",
                person_id=resolved_catalog_author.id,
                relationship_type="author",
                verification_status="verified",
                confidence=100,
            )
        )
        author = Person(canonical_key="author:margaret", public_id="margaret-id", display_name="Margaret Hamilton")
        session.add(author)
        session.flush()
        session.add(PersonProfile(person_id=author.id, visibility="public"))
        session.add(
            ToolPersonRelationship(
                tool_name="example",
                person_id=author.id,
                relationship_type="author",
                verification_status="verified",
                confidence=100,
            )
        )
        second_author = Person(
            canonical_key="author:katherine",
            public_id="katherine-id",
            display_name="Katherine Johnson",
        )
        session.add(second_author)
        session.flush()
        session.add(PersonProfile(person_id=second_author.id, visibility="public"))
        session.add(
            ToolPersonRelationship(
                tool_name="example",
                person_id=second_author.id,
                relationship_type="author",
                verification_status="verified",
                confidence=100,
            )
        )
        hidden = Person(canonical_key="hidden", public_id="hidden-id", display_name="Hidden Person")
        session.add(hidden)
        session.flush()
        session.add(
            ToolPersonRelationship(
                tool_name="example",
                person_id=hidden.id,
                relationship_type="maintainer",
                verification_status="verified",
                confidence=100,
            )
        )
    period = digests.period_for("daily", datetime(2026, 8, 12, 12))

    edition = digests.create_edition(period)
    duplicate = digests.create_edition(period)

    assert edition is not None
    assert duplicate is not None and duplicate.id == edition.id
    assert edition.edition_key == "2026-08-12"
    assert edition.used_fallback is True
    assert "Example" in edition.rendered_html
    assert "toolhub-evolved-digest:daily:2026-08-12:en" in edition.rendered_wikitext
    with db.session_scope() as session:
        assert len(list(session.execute(select(DigestEdition)).scalars())) == 1
        tool = session.execute(select(DigestEditionTool)).scalar_one()
        assert tool.facts["description"] == "Helps editors review changes."
        assert tool.facts["authors"] == [
            {"name": "Ada Lovelace", "url": "https://toolhub-evolved.toolforge.org/people/ada-id"},
            {
                "name": "Unresolved Author",
                "url": "https://toolhub-evolved.toolforge.org/by/Unresolved%20Author",
            },
            {"name": "Katherine Johnson", "url": "https://toolhub-evolved.toolforge.org/people/katherine-id"},
            {"name": "Margaret Hamilton", "url": "https://toolhub-evolved.toolforge.org/people/margaret-id"},
        ]
        assert tool.facts["maintainers"] == [
            {"name": "Grace Hopper", "url": "https://toolhub-evolved.toolforge.org/people/grace-id"}
        ]
        assert tool.highlighted is True
        # Every link a digest publishes is an Evolved link, tool pages included.
        # Nothing else pins the origin of this one, so a revert to the official
        # base would otherwise ship silently into email and onto Meta.
        assert tool.facts["toolhub_url"] == "https://toolhub-evolved.toolforge.org/tools/example"
    assert "https://toolhub.wikimedia.org" not in edition.rendered_html
    assert "https://toolhub.wikimedia.org" not in edition.rendered_wikitext
    assert "https://toolhub.wikimedia.org" not in edition.rendered_text
    assert "https://example.toolforge.org/" in edition.rendered_html
    assert "Ada Lovelace" in edition.rendered_wikitext
    assert "Grace Hopper" in edition.rendered_text


def test_digest_attributes_only_current_verified_relationships(monkeypatch):
    monkeypatch.delenv("LIFTWING_API_URL", raising=False)
    digests.capture_recent_rows([creation(1, "relationship-tool", "2026-08-12T12:00:00Z")])
    relationships = (
        ("Current Person", "verified", None),
        ("Unverified Person", "unverified", None),
        ("Stale Person", "stale", None),
        ("Failed Person", "failed", None),
        ("Expired Person", "verified", datetime(2020, 1, 1)),
    )
    with db.session_scope() as session:
        session.add(
            CanonicalToolCache(
                tool_name="relationship-tool",
                record={"name": "relationship-tool", "title": "Relationship Tool"},
                expires_at=datetime(2026, 8, 14),
                stale_until=datetime(2026, 8, 15),
            )
        )
        for display_name, verification_status, expires_at in relationships:
            person = Person(
                canonical_key=f"relationship:{display_name}",
                public_id=display_name.casefold().replace(" ", "-"),
                display_name=display_name,
            )
            session.add(person)
            session.flush()
            session.add(PersonProfile(person_id=person.id, visibility="public"))
            session.add(
                ToolPersonRelationship(
                    tool_name="relationship-tool",
                    person_id=person.id,
                    relationship_type="maintainer",
                    verification_status=verification_status,
                    confidence=100,
                    expires_at=expires_at,
                )
            )

    edition = digests.create_edition(digests.period_for("daily", datetime(2026, 8, 12, 12)))

    assert edition is not None
    with db.session_scope() as session:
        tool = session.execute(select(DigestEditionTool)).scalar_one()
        assert tool.facts["maintainer_names"] == ["Current Person"]
        assert tool.facts["maintainers"] == [
            {
                "name": "Current Person",
                "url": "https://toolhub-evolved.toolforge.org/people/current-person",
            }
        ]


def test_model_prompt_requests_grounded_people_names_but_forbids_model_links():
    facts = [
        {
            "name": "known",
            "author_names": ["Ada Lovelace"],
            "maintainer_names": ["Grace Hopper"],
            "toolhub_url": "https://toolhub-evolved.toolforge.org/tools/known",
            "url": "https://known.toolforge.org/",
        }
    ]

    payload = digests._model_payload(facts, "daily", "llm-qwen36-27b")

    system = payload["messages"][0]["content"]
    supplied = json.loads(payload["messages"][1]["content"])["tools"][0]
    assert "author_names or maintainer_names" in system
    assert "Never emit URLs" in system
    assert "scanning in under a minute" in system
    assert "do not merely repeat the title" in system
    assert "exactly one object for every supplied tool" in system
    assert supplied["author_names"] == ["Ada Lovelace"]
    assert "toolhub_url" not in supplied
    assert "url" not in supplied


def test_model_payload_bounds_busy_periods_but_daily_supplies_every_tool():
    facts = [
        {
            "name": f"tool-{index}",
            "title": f"Tool {index}",
            "description": (f"Description for tool {index}. " * 80),
            "tasks": [f"task-{item}" * 30 for item in range(12)],
            "toolhub_url": f"https://toolhub-evolved.toolforge.org/tools/tool-{index}",
            "url": f"https://tool-{index}.example/",
            "authors": [{"name": "Person", "url": "https://people.example/person"}],
        }
        for index in range(118)
    ]

    monthly = digests._model_payload(facts, "monthly", "llm-qwen36-27b")
    monthly_input = json.loads(monthly["messages"][1]["content"])
    candidates = monthly_input["tools"]
    candidate_indexes = [int(item["name"].removeprefix("tool-")) for item in candidates]

    assert monthly_input["period_tool_count"] == 118
    assert monthly_input["selected_tool_count"] == digests.MAX_HIGHLIGHTS
    assert f"exactly {digests.MAX_HIGHLIGHTS} objects" in monthly["messages"][0]["content"]
    assert digests.MAX_HIGHLIGHTS <= len(candidates) <= digests.MAX_MODEL_CANDIDATES
    assert len(json.dumps(candidates, ensure_ascii=False).encode()) <= digests.MAX_MODEL_FACTS_BYTES
    assert min(candidate_indexes) < 10
    assert max(candidate_indexes) > 100
    assert all(set(item) <= {"name", *digests.EVIDENCE_FIELDS} for item in candidates)

    daily = digests._model_payload(facts, "daily", "llm-qwen36-27b")
    daily_input = json.loads(daily["messages"][1]["content"])
    assert daily_input["candidate_count"] == 118
    assert [item["name"] for item in daily_input["tools"]] == [fact["name"] for fact in facts]


def test_weekly_and_monthly_select_all_tools_below_the_limit():
    facts = [
        {"name": f"tool-{index}", "description": f"Description for tool {index}."} for index in range(3)
    ]
    payload = digests._model_payload(facts, "weekly", "llm-qwen36-27b")
    model_input = json.loads(payload["messages"][1]["content"])
    assert model_input["selected_tool_count"] == 3
    assert "exactly 3 objects" in payload["messages"][0]["content"]

    incomplete = {
        "introduction": "Three tools support distinct Wikimedia workflows.",
        "highlights": [
            {
                "tool_name": fact["name"],
                "blurb": f"Tool {index} supports a documented workflow.",
                "evidence_field": "description",
                "evidence": fact["description"],
            }
            for index, fact in enumerate(facts[:2])
        ],
    }
    with pytest.raises(ValueError, match="select exactly"):
        digests.validate_editorial(incomplete, facts, cadence="weekly")

    complete = {**incomplete, "highlights": [
        {
            "tool_name": fact["name"],
            "blurb": f"Tool {index} supports a documented workflow.",
            "evidence_field": "description",
            "evidence": fact["description"],
        }
        for index, fact in enumerate(facts)
    ]}
    assert len(digests.validate_editorial(complete, facts, cadence="monthly")["highlights"]) == 3


def test_model_editorial_rejects_unknown_tools_and_links():
    facts = [{"name": "known"}]
    with pytest.raises(ValueError, match="unknown"):
        digests.validate_editorial(
            {"introduction": "New tools.", "highlights": [{"tool_name": "invented", "blurb": "Useful."}]},
            facts,
        )


def test_model_editorial_rejects_prose_that_exceeds_reading_limits():
    facts = [{"name": "known", "description": "Helps editors review changes."}]
    with pytest.raises(ValueError, match="introduction exceeded"):
        digests.validate_editorial(
            {
                "introduction": " ".join(["word"] * (digests.MAX_INTRODUCTION_WORDS + 1)),
                "highlights": [
                    {
                        "tool_name": "known",
                        "blurb": "Helps editors review changes.",
                        "evidence_field": "description",
                        "evidence": "Helps editors review changes.",
                    }
                ],
            },
            facts,
        )


def test_daily_editorial_must_mention_every_tool_exactly_once():
    facts = [
        {"name": "one", "description": "Helps editors review changes."},
        {"name": "two", "description": "Shows recent Wikimedia activity."},
    ]
    incomplete = {
        "introduction": "Two focused tools support review and activity monitoring.",
        "highlights": [
            {
                "tool_name": "one",
                "blurb": "The first tool helps editors review changes.",
                "evidence_field": "description",
                "evidence": "Helps editors review changes.",
            }
        ],
    }

    with pytest.raises(ValueError, match="every supplied tool"):
        digests.validate_editorial(incomplete, facts, cadence="daily")

    fallback = digests._fallback_editorial(facts, "daily")
    assert [item["tool_name"] for item in fallback["highlights"]] == ["one", "two"]
    with pytest.raises(ValueError, match="blurb exceeded"):
        digests.validate_editorial(
            {
                "introduction": "A focused review tool arrived.",
                "highlights": [
                    {
                        "tool_name": "known",
                        "blurb": " ".join(["word"] * (digests.MAX_BLURB_WORDS + 1)),
                        "evidence_field": "description",
                        "evidence": "Helps editors review changes.",
                    }
                ],
            },
            facts,
        )


def test_model_editorial_requires_verbatim_frozen_fact_evidence():
    facts = [{"name": "known", "description": "Helps editors review changes."}]
    accepted = digests.validate_editorial(
        {
            "introduction": "A focused review tool arrived.",
            "highlights": [
                {
                    "tool_name": "known",
                    "blurb": "It supports change review workflows.",
                    "evidence_field": "description",
                    "evidence": "Helps editors review changes.",
                }
            ],
        },
        facts,
    )
    assert accepted["highlights"][0]["evidence_field"] == "description"
    excerpt = digests.validate_editorial(
        {
            "introduction": "A focused review tool arrived.",
            "highlights": [
                {
                    "tool_name": "known",
                    "blurb": "It supports change review workflows.",
                    "evidence_field": "description",
                    "evidence": "Helps editors review changes",
                }
            ],
        },
        facts,
    )
    assert excerpt["highlights"][0]["evidence"] == "Helps editors review changes"
    with pytest.raises(ValueError, match="evidence"):
        digests.validate_editorial(
            {
                "introduction": "A focused review tool arrived.",
                "highlights": [
                    {
                        "tool_name": "known",
                        "blurb": "It supports editors.",
                        "evidence_field": "description",
                        "evidence": "editors",
                    }
                ],
            },
            facts,
        )
    with pytest.raises(ValueError, match="evidence"):
        digests.validate_editorial(
            {
                "introduction": "A focused review tool arrived.",
                "highlights": [
                    {
                        "tool_name": "known",
                        "blurb": "It is extremely popular.",
                        "evidence_field": "description",
                        "evidence": "Millions of editors use it.",
                    }
                ],
            },
            facts,
        )


def test_model_editorial_resolves_only_unique_exact_tool_titles():
    facts = [
        {"name": "toolforge-example", "title": "Example Tool", "description": "Helps editors."},
        {"name": "other", "title": "Shared title", "description": "First."},
        {"name": "another", "title": "Shared title", "description": "Second."},
    ]
    accepted = digests.validate_editorial(
        {
            "introduction": "One useful tool arrived.",
            "highlights": [
                {
                    "tool_name": "Example Tool",
                    "blurb": "It helps editors.",
                    "evidence_field": "description",
                    "evidence": "Helps editors.",
                }
            ],
        },
        facts,
    )
    assert accepted["highlights"][0]["tool_name"] == "toolforge-example"

    with pytest.raises(ValueError, match="unknown"):
        digests.validate_editorial(
            {
                "introduction": "Ambiguous tool.",
                "highlights": [
                    {
                        "tool_name": "Shared title",
                        "blurb": "It does something.",
                        "evidence_field": "description",
                        "evidence": "First.",
                    }
                ],
            },
            facts,
        )
    with pytest.raises(ValueError, match="links"):
        digests.validate_editorial(
            {
                "introduction": "New tools.",
                "highlights": [{"tool_name": "toolforge-example", "blurb": "See https://malicious.invalid"}],
            },
            facts,
        )


class FakeWiki:
    def __init__(self):
        self.pages = {}
        self.emails = []
        self.talk = []

    def page_source(self, _domain, title):
        return self.pages.get(title, ("", ""))

    def user_exists(self, _domain, _username):
        return True

    def user_identity_matches(self, _domain, _username, _global_user_id=""):
        return True

    def edit_page(self, domain, title, text, **_kwargs):
        self.pages[title] = (text, "42")
        return WikiEditResult(title, "42", f"https://{domain}/wiki/{title}")

    def email_user(self, domain, username, subject, text):
        self.emails.append((domain, username, subject, text))
        return "success"

    def append_talk_section(self, domain, username, title, text, marker):
        self.talk.append((domain, username, title, text, marker))
        return WikiEditResult(f"User talk:{username}", "84", f"https://{domain}/wiki/User_talk:{username}")


def _generated_edition(monkeypatch):
    monkeypatch.delenv("LIFTWING_API_URL", raising=False)
    digests.capture_recent_rows([creation(1, "example", "2026-08-12T12:00:00Z")])
    edition = digests.create_edition(digests.period_for("daily", datetime(2026, 8, 12, 12)))
    assert edition is not None
    return edition


def _identity_provider(username="Example"):
    return SimpleNamespace(
        lookup=lambda global_id: SimpleNamespace(global_user_id=global_id, username=username, registration="")
    )


def test_meta_publication_is_immutable_and_records_revision(monkeypatch):
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    edition = _generated_edition(monkeypatch)
    wiki = FakeWiki()

    published = digests.publish_edition(edition.id, client=wiki)
    again = digests.publish_edition(edition.id, client=wiki)

    assert published.status == "published"
    assert published.meta_page_title == "Toolhub/Digest/Daily/2026-08-12"
    assert published.meta_revision_id == "42"
    assert again.id == published.id
    assert len(wiki.pages) == 1


def test_meta_wikitext_neutralizes_tool_and_model_markup(monkeypatch):
    monkeypatch.delenv("LIFTWING_API_URL", raising=False)
    digests.capture_recent_rows([creation(1, "unsafe", "2026-08-12T12:00:00Z")])
    with db.session_scope() as session:
        session.add(
            CanonicalToolCache(
                tool_name="unsafe",
                record={
                    "name": "unsafe",
                    "title": "{{Danger}} [[Category:Injected]]",
                    "description": "== Heading == {{Template}} [[File:Bad.svg]].",
                },
                expires_at=datetime(2026, 8, 14),
                stale_until=datetime(2026, 8, 15),
            )
        )

    edition = digests.create_edition(digests.period_for("daily", datetime(2026, 8, 12, 12)))

    assert edition is not None
    assert "{{Danger}}" not in edition.rendered_wikitext
    assert "[[Category:Injected]]" not in edition.rendered_wikitext
    assert "&#123;&#123;Danger&#125;&#125;" in edition.rendered_wikitext
    assert "&#91;&#91;Category&#58;Injected&#93;&#93;" in edition.rendered_wikitext


@pytest.mark.parametrize(
    "unsafe_url",
    ("https://[", "https://example.org/]\n==Injected digest heading=="),
    ids=("malformed-host", "wikitext-delimiters"),
)
def test_digest_omits_malformed_or_wikitext_unsafe_direct_urls(monkeypatch, unsafe_url):
    monkeypatch.delenv("LIFTWING_API_URL", raising=False)
    digests.capture_recent_rows([creation(1, "unsafe-url", "2026-08-12T12:00:00Z")])
    with db.session_scope() as session:
        session.add(
            CanonicalToolCache(
                tool_name="unsafe-url",
                record={
                    "name": "unsafe-url",
                    "title": "Unsafe URL",
                    "description": "A tool whose direct URL must be omitted safely.",
                    "url": unsafe_url,
                },
                expires_at=datetime(2026, 8, 14),
                stale_until=datetime(2026, 8, 15),
            )
        )

    edition = digests.create_edition(digests.period_for("daily", datetime(2026, 8, 12, 12)))

    assert edition is not None
    assert "Open tool" not in edition.rendered_wikitext
    assert "Injected digest heading" not in edition.rendered_wikitext
    with db.session_scope() as session:
        tool = session.execute(select(DigestEditionTool)).scalar_one()
        assert tool.facts["url"] == ""


def test_meta_archive_refuses_collisions_and_retries_without_new_editions(monkeypatch):
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    published = digests.publish_edition(_generated_edition(monkeypatch).id, client=FakeWiki())
    assert published.status == "published"
    wiki = FakeWiki()
    wiki.pages["Toolhub/Digest/Archive"] = ("Human-maintained page", "9")

    first = digests.publish_pending(client=wiki)

    assert first == {"published": 0, "failed": 1}
    with db.session_scope() as session:
        state = session.get(DigestOperationalState, digests.ARCHIVE_STATE_KEY)
        assert state is not None and "already exists" in state.last_error
    del wiki.pages["Toolhub/Digest/Archive"]

    second = digests.publish_pending(client=wiki)

    assert second == {"published": 0, "failed": 0}
    with db.session_scope() as session:
        state = session.get(DigestOperationalState, digests.ARCHIVE_STATE_KEY)
        assert state.last_error is None
        assert state.last_success_at is not None


def test_delivery_outbox_sends_email_and_talk_page_once(monkeypatch):
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    monkeypatch.setenv("DIGEST_SIGNING_SECRET", "test-digest-secret")
    edition = _generated_edition(monkeypatch)
    wiki = FakeWiki()
    published = digests.publish_edition(edition.id, client=wiki)
    with db.session_scope() as session:
        user = User(wm_sub="7", username="Example", wikimedia_global_user_id="70")
        session.add(user)
        session.flush()
        session.add_all(
            [
                DigestSubscription(
                    user_id=user.id,
                    channel="email",
                    cadence="daily",
                    wiki_username="Example",
                    active=True,
                    confirmed_at=datetime(2026, 8, 13),
                ),
                DigestSubscription(
                    user_id=user.id,
                    channel="talk",
                    cadence="daily",
                    wiki_domain="fr.wikipedia.org",
                    wiki_username="Exemple",
                    active=True,
                    confirmed_at=datetime(2026, 8, 13),
                ),
            ]
        )

    assert digest_delivery.queue_deliveries(published.id) == 2
    assert digest_delivery.queue_deliveries(published.id) == 0
    result = digest_delivery.deliver_pending(client=wiki, identity_provider=_identity_provider())

    assert result == {
        "delivered": 2,
        "retry": 0,
        "suspended": 0,
        "failed": 0,
        "cancelled": 0,
        "skipped": 0,
    }
    assert len(wiki.emails) == 1
    assert len(wiki.talk) == 1
    with db.session_scope() as session:
        assert {row.status for row in session.execute(select(DigestDelivery)).scalars()} == {"delivered"}


def test_permanent_wikimedia_email_failure_suspends_only_that_subscription(monkeypatch):
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    monkeypatch.setenv("DIGEST_SIGNING_SECRET", "test-digest-secret")
    edition = _generated_edition(monkeypatch)
    published = digests.publish_edition(edition.id, client=FakeWiki())

    class DisabledEmailWiki(FakeWiki):
        def email_user(self, *_args, **_kwargs):
            raise WikimediaAPIError("nowikiemail", "User disabled wiki email", permanent=True)

    with db.session_scope() as session:
        user = User(wm_sub="7", username="Example", wikimedia_global_user_id="70")
        session.add(user)
        session.flush()
        session.add(
            DigestSubscription(
                user_id=user.id,
                channel="email",
                cadence="daily",
                wiki_username="Example",
                active=True,
                confirmed_at=datetime(2026, 8, 13),
            )
        )
    digest_delivery.queue_deliveries(published.id)

    result = digest_delivery.deliver_pending(
        client=DisabledEmailWiki(), identity_provider=_identity_provider()
    )

    assert result["suspended"] == 1
    with db.session_scope() as session:
        subscription = session.execute(select(DigestSubscription)).scalar_one()
        assert subscription.active is False


def test_service_account_failure_retries_without_unsubscribing_user(monkeypatch):
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    monkeypatch.setenv("DIGEST_SIGNING_SECRET", "test-digest-secret")
    published = digests.publish_edition(_generated_edition(monkeypatch).id, client=FakeWiki())

    class MisconfiguredWiki(FakeWiki):
        def email_user(self, *_args, **_kwargs):
            raise WikimediaAPIError(
                "unexpected-account",
                "Bot token uses the wrong account",
                permanent=True,
                recipient_failure=False,
            )

    with db.session_scope() as session:
        user = User(wm_sub="service", username="Example", wikimedia_global_user_id="73")
        session.add(user)
        session.flush()
        session.add(
            DigestSubscription(
                user_id=user.id,
                channel="email",
                cadence="daily",
                wiki_username="Example",
                active=True,
                confirmed_at=published.period_end,
            )
        )
    digest_delivery.queue_deliveries(published.id)

    result = digest_delivery.deliver_pending(
        client=MisconfiguredWiki(), identity_provider=_identity_provider()
    )

    assert result["retry"] == 1
    with db.session_scope() as session:
        assert session.execute(select(DigestSubscription)).scalar_one().active is True


def test_delivery_eligibility_is_measured_against_the_period_not_publication_time(monkeypatch):
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    edition = _generated_edition(monkeypatch)
    published = digests.publish_edition(edition.id, client=FakeWiki())
    with db.session_scope() as session:
        user = User(wm_sub="late", username="Late", wikimedia_global_user_id="71")
        session.add(user)
        session.flush()
        session.add(
            DigestSubscription(
                user_id=user.id,
                channel="talk",
                cadence="daily",
                wiki_username="Late",
                active=True,
                confirmed_at=published.period_end + timedelta(microseconds=1),
            )
        )

    # published_at is later still, so the old publication-time comparison would
    # have accepted this subscription for a period that closed before it existed.
    assert published.published_at > published.period_end
    assert digest_delivery.queue_deliveries(published.id) == 0


def test_backfilled_editions_publish_everywhere_but_are_never_pushed(monkeypatch):
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    edition = _generated_edition(monkeypatch)
    published = digests.publish_edition(edition.id, client=FakeWiki())
    with db.session_scope() as session:
        user = User(wm_sub="old", username="Old", wikimedia_global_user_id="74")
        session.add(user)
        session.flush()
        session.add(
            DigestSubscription(
                user_id=user.id,
                channel="talk",
                cadence="daily",
                wiki_username="Old",
                active=True,
                # Subscribed long before the period, so only the lateness bound
                # can keep a bulk backfill out of this subscriber's talk page.
                confirmed_at=published.period_start - timedelta(days=365),
            )
        )
        stale = session.get(DigestEdition, published.id)
        stale.published_at = stale.period_end + timedelta(days=90)

    assert digest_delivery.queue_deliveries(published.id) == 0

    with db.session_scope() as session:
        recovered = session.get(DigestEdition, published.id)
        # Still fully published: the website, the feeds and Meta are unaffected.
        assert recovered.status == "published"
        assert recovered.meta_revision_id
        recovered.published_at = recovered.period_end + timedelta(days=2)

    # A genuine two-day recovery is not a backfill and still delivers.
    assert digest_delivery.queue_deliveries(published.id) == 1


def test_publication_lateness_bound_is_configurable_and_rejects_nonsense(monkeypatch):
    assert digest_delivery.max_publication_lateness_days() == digest_delivery.DEFAULT_MAX_PUBLICATION_LATENESS_DAYS
    monkeypatch.setenv("DIGEST_MAX_PUBLICATION_LATENESS_DAYS", "3")
    assert digest_delivery.max_publication_lateness_days() == 3
    monkeypatch.setenv("DIGEST_MAX_PUBLICATION_LATENESS_DAYS", "0")
    with pytest.raises(ValueError, match="DIGEST_MAX_PUBLICATION_LATENESS_DAYS"):
        digest_delivery.max_publication_lateness_days()
    monkeypatch.setenv("DIGEST_MAX_PUBLICATION_LATENESS_DAYS", "soon")
    with pytest.raises(ValueError, match="DIGEST_MAX_PUBLICATION_LATENESS_DAYS"):
        digest_delivery.max_publication_lateness_days()


def test_delivery_refreshes_renamed_wikimedia_identity(monkeypatch):
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    monkeypatch.setenv("DIGEST_SIGNING_SECRET", "test-digest-secret")
    published = digests.publish_edition(_generated_edition(monkeypatch).id, client=FakeWiki())
    with db.session_scope() as session:
        user = User(wm_sub="rename", username="Old", wikimedia_global_user_id="72")
        session.add(user)
        session.flush()
        session.add(
            DigestSubscription(
                user_id=user.id,
                channel="talk",
                cadence="daily",
                wiki_domain="fr.wikipedia.org",
                wiki_username="Old",
                active=True,
                confirmed_at=published.period_end,
            )
        )
    digest_delivery.queue_deliveries(published.id)
    wiki = FakeWiki()

    result = digest_delivery.deliver_pending(client=wiki, identity_provider=_identity_provider("NewName"))

    assert result["delivered"] == 1
    assert wiki.talk[0][1] == "NewName"
    assert f"[{published.meta_page_url} Read the complete digest" in wiki.talk[0][3]
    with db.session_scope() as session:
        assert session.execute(select(DigestSubscription)).scalar_one().wiki_username == "NewName"


def test_unsubscribe_token_outlives_confirmation_window(monkeypatch):
    monkeypatch.setenv("DIGEST_SIGNING_SECRET", "test-digest-secret")
    monkeypatch.setattr("itsdangerous.timed.TimestampSigner.get_timestamp", lambda _self: 1)
    unsubscribe = digest_delivery.subscription_token(1, 2, "unsubscribe")
    confirmation = digest_delivery.subscription_token(1, 2, "confirm")
    monkeypatch.setattr(
        "itsdangerous.timed.TimestampSigner.get_timestamp",
        lambda _self: digest_delivery.CONFIRMATION_MAX_AGE_SECONDS + 2,
    )

    assert digest_delivery.read_subscription_token(unsubscribe, "unsubscribe") == (1, 2)
    with pytest.raises(ValueError, match="expired"):
        digest_delivery.read_subscription_token(confirmation, "confirm")


def test_wikimedia_local_identity_must_match_stable_central_id(monkeypatch):
    client = WikimediaClient(access_token="token")
    monkeypatch.setattr(
        client,
        "request",
        lambda *_args, **_kwargs: {
            "query": {"users": [{"name": "Renamed", "centralids": {"CentralAuth": 9001}}]}
        },
    )

    assert client.user_identity_matches("fr.wikipedia.org", "Renamed", "9001") is True
    assert client.user_identity_matches("fr.wikipedia.org", "Renamed", "42") is False


def test_wikimedia_destination_validation_rejects_non_wikimedia_hosts():
    assert clean_wiki_domain("fr.wikipedia.org") == "fr.wikipedia.org"
    with pytest.raises(ValueError, match="Wikimedia"):
        clean_wiki_domain("meta.wikimedia.org.attacker.example")


def test_liftwing_destination_is_restricted_to_public_qwen_chat_completions():
    valid = (
        "https://api.wikimedia.org/service/lw/inference/v1/models/"
        "llm-qwen36-27b/openai/v1/chat/completions"
    )
    assert digests.clean_liftwing_endpoint(valid, model="llm-qwen36-27b") == valid
    with pytest.raises(ValueError, match="chat-completions"):
        digests.clean_liftwing_endpoint(
            "https://api.wikimedia.org.attacker.example/service/lw/inference/v1/models/"
            "llm-qwen36-27b/openai/v1/chat/completions"
        )
    with pytest.raises(ValueError, match="chat-completions"):
        digests.clean_liftwing_endpoint("https://api.wikimedia.org/w/api.php")
    with pytest.raises(ValueError, match="chat-completions"):
        digests.clean_liftwing_endpoint(
            "https://api.wikimedia.org/service/lw/inference/v1/models/llm-qwen36-27b:predict"
        )
    with pytest.raises(ValueError, match="chat-completions"):
        digests.clean_liftwing_endpoint(valid, model="llm-qwen3-14b")


def test_liftwing_qwen_adapter_uses_openai_contract_and_strips_reasoning(monkeypatch):
    endpoint = (
        "https://api.wikimedia.org/service/lw/inference/v1/models/"
        "llm-qwen36-27b/openai/v1/chat/completions"
    )
    monkeypatch.setenv("LIFTWING_API_URL", endpoint)
    monkeypatch.setenv("LIFTWING_MODEL", "llm-qwen36-27b")
    monkeypatch.setenv("LIFTWING_USER_AGENT", "ToolhubDigest/1.0 (https://tool.example/contact)")
    monkeypatch.setenv("LIFTWING_ACCESS_TOKEN", "must-not-be-sent")
    captured = {}
    model_output = {
        "introduction": "One focused editing tool arrived.",
        "highlights": [
            {
                "tool_name": "known",
                "blurb": "It supports review workflows.",
                "evidence_field": "description",
                "evidence": "Helps editors review changes.",
            }
        ],
    }

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            content = f"<think>private reasoning</think>```json\n{json.dumps(model_output)}\n```"
            return {"choices": [{"message": {"content": content}}]}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(digests.requests, "post", post)

    editorial, model, used_fallback, _response = digests.generate_editorial(
        [{"name": "known", "description": "Helps editors review changes."}],
        "daily",
    )

    assert used_fallback is False
    assert model == "llm-qwen36-27b"
    assert editorial["introduction"] == "One focused editing tool arrived."
    assert captured["url"] == endpoint
    assert captured["json"]["model"] == "llm-qwen36-27b"
    assert "reasoning" not in captured["json"]
    assert captured["headers"]["Api-User-Agent"] == "ToolhubDigest/1.0 (https://tool.example/contact)"
    assert "Authorization" not in captured["headers"]


def test_meta_base_title_rejects_wikitext_control_characters(monkeypatch):
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest]]{{Danger")
    with pytest.raises(ValueError, match="MediaWiki title"):
        digests.meta_base_title()


def _web_client():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    application.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    return application.test_client()


def test_public_archive_detail_and_full_content_rss(monkeypatch):
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    client = _web_client()
    edition = _generated_edition(monkeypatch)
    digests.publish_edition(edition.id, client=FakeWiki())

    archive = client.get("/v1/digests/?cadence=daily").get_json()
    detail = client.get("/v1/digests/daily/2026-08-12/").get_json()
    feed = client.get("/feeds/digests/daily.xml")

    assert archive["editions"][0]["editionKey"] == "2026-08-12"
    assert archive["editions"][0]["toolCount"] == 1
    assert "html" not in archive["editions"][0]
    assert "tools" not in archive["editions"][0]
    assert detail["tools"][0]["name"] == "example"
    assert feed.status_code == 200
    assert b"<content:encoded>" in feed.data
    assert b"Toolhub/Digest/Daily/2026-08-12" in feed.data


def test_historical_website_editions_use_liftwing_without_entering_delivery_channels(monkeypatch):
    client = _web_client()
    digests.capture_recent_rows(
        [
            creation(1, "july-tool", "2026-07-31T12:00:00Z"),
            creation(2, "august-tool", "2026-08-09T12:00:00Z"),
        ]
    )

    def editorial(facts, cadence):
        return (
            {"introduction": f"A concise historical {cadence} edition.", "highlights": []},
            "llm-qwen36-27b",
            False,
            {"choices": []},
        )

    monkeypatch.setattr(digests, "generate_editorial", editorial)

    periods = (
        digests.period_for("daily", datetime(2026, 8, 9, 12)),
        digests.period_for("weekly", datetime(2026, 8, 9, 12)),
        digests.period_for("monthly", datetime(2026, 7, 31, 12)),
    )
    editions = [
        digests.create_edition(
            period,
            initial_status=digests.WEBSITE_ONLY_STATUS,
            require_model=True,
        )
        for period in periods
    ]

    assert all(edition is not None for edition in editions)
    with db.session_scope() as session:
        stored = list(session.execute(select(DigestEdition)).scalars())
        assert {edition.status for edition in stored} == {digests.WEBSITE_ONLY_STATUS}
        assert {edition.model_name for edition in stored} == {"llm-qwen36-27b"}
        assert all(edition.published_at is not None for edition in stored)
        assert all("Author: LiftWing Qwen" in edition.rendered_html for edition in stored)
        assert all("preview" not in edition.rendered_html.casefold() for edition in stored)

    archive = client.get("/v1/digests/?cadence=daily").get_json()
    detail = client.get(f"/v1/digests/daily/{archive['editions'][0]['editionKey']}/").get_json()
    assert archive["pagination"]["total"] == 1
    assert detail["author"] == "LiftWing Qwen"
    assert detail["modelName"] == "llm-qwen36-27b"
    assert "publicationScope" not in detail
    for cadence in digests.CADENCES:
        assert b"A concise" not in client.get(f"/feeds/digests/{cadence}.xml").data
    assert digest_delivery.queue_published_editions() == 0
    wiki = FakeWiki()
    assert digests.publish_pending(client=wiki) == {"published": 0, "failed": 0}
    assert wiki.pages == {}
    assert wiki.emails == []
    assert wiki.talk == []

    monkeypatch.setattr(
        digests,
        "generate_editorial",
        lambda _facts, _cadence: ({"introduction": "Fallback.", "highlights": []}, "qwen", True, None),
    )
    with pytest.raises(RuntimeError, match="did not produce"):
        digests.create_edition(
            digests.period_for("daily", datetime(2026, 7, 31, 12)),
            initial_status=digests.WEBSITE_ONLY_STATUS,
            require_model=True,
        )
    with pytest.raises(ValueError, match="unsupported initial"):
        digests.create_edition(periods[0], initial_status="rss_only")


def test_website_only_regeneration_is_atomic_and_keeps_audit_history(monkeypatch):
    digests.capture_recent_rows(
        [
            creation(1, "july-tool", "2026-07-31T12:00:00Z"),
            creation(2, "august-tool", "2026-08-09T12:00:00Z"),
        ]
    )
    periods = [
        digests.period_from_key("daily", "2026-08-09"),
        digests.period_from_key("weekly", "2026-W32"),
        digests.period_from_key("monthly", "2026-07"),
    ]
    round_number = 1

    def editorial(facts, _cadence):
        return (
            {
                "introduction": f"Editorial round {round_number} covers verified tools for Wikimedia contributors.",
                "highlights": [
                    {"tool_name": facts[0]["name"], "blurb": f"Round {round_number} explains the tool clearly."}
                ],
            },
            "llm-qwen36-27b",
            False,
            {"round": round_number},
        )

    monkeypatch.setattr(digests, "generate_editorial", editorial)
    original = [
        digests.create_edition(period, initial_status=digests.WEBSITE_ONLY_STATUS, require_model=True)
        for period in periods
    ]
    original_ids = {edition.id for edition in original if edition is not None}
    round_number = 2

    regenerated = digests.regenerate_website_editions(periods)

    assert {edition.id for edition in regenerated} == original_ids
    assert all("round 2" in edition.introduction.casefold() for edition in regenerated)
    with db.session_scope() as session:
        assert session.query(DigestGenerationAttempt).count() == 6
        assert {attempt.attempt for attempt in session.query(DigestGenerationAttempt)} == {1, 2}
        assert session.query(DigestDelivery).count() == 0
    assert digest_regenerate.run(periods)["publicationScope"] == "website-only"


def test_website_only_regeneration_refuses_a_published_edition_before_mutation(monkeypatch):
    digests.capture_recent_rows([creation(1, "published-tool", "2026-08-09T12:00:00Z")])
    period = digests.period_from_key("daily", "2026-08-09")
    monkeypatch.setattr(
        digests,
        "generate_editorial",
        lambda facts, _cadence: (
            {
                "introduction": "One verified tool supports Wikimedia work.",
                "highlights": [{"tool_name": facts[0]["name"], "blurb": "The tool supports Wikimedia work."}],
            },
            "llm-qwen36-27b",
            False,
            {},
        ),
    )
    edition = digests.create_edition(period)
    assert edition is not None

    with pytest.raises(ValueError, match="non-website"):
        digests.regenerate_website_editions([period])

    with db.session_scope() as session:
        stored = session.get(DigestEdition, edition.id)
        assert stored is not None
        assert stored.introduction == "One verified tool supports Wikimedia work."
        assert session.query(DigestGenerationAttempt).count() == 1


def test_public_archive_pages_through_every_published_edition(monkeypatch):
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    client = _web_client()
    digests.publish_edition(_generated_edition(monkeypatch).id, client=FakeWiki())
    with db.session_scope() as session:
        session.add_all(
            [
                DigestEdition(
                    cadence="daily",
                    edition_key=f"2026-08-{day:02d}",
                    period_start=datetime(2026, 8, day),
                    period_end=datetime(2026, 8, day + 1),
                    status="published",
                    title=f"Day {day}",
                    published_at=datetime(2026, 8, 13),
                )
                for day in (10, 11)
            ]
        )
        session.add(
            DigestEdition(
                cadence="daily",
                edition_key="2026-08-11",
                language_code="fr",
                period_start=datetime(2026, 8, 11),
                period_end=datetime(2026, 8, 12),
                status="published",
                title="Jour 11",
                published_at=datetime(2026, 8, 13),
            )
        )

    second = client.get("/v1/digests/?cadence=daily&limit=1&page=2").get_json()
    third = client.get("/v1/digests/?cadence=daily&limit=1&page=3").get_json()

    assert second["editions"][0]["editionKey"] == "2026-08-11"
    assert second["pagination"] == {"page": 2, "limit": 1, "total": 3, "hasMore": True}
    assert third["editions"][0]["editionKey"] == "2026-08-10"
    assert third["pagination"]["hasMore"] is False


def test_email_confirmation_and_talk_subscription_use_verified_wikimedia_identity(monkeypatch):
    monkeypatch.setenv("DIGEST_SIGNING_SECRET", "test-digest-secret")
    wiki = FakeWiki()
    monkeypatch.setattr(v1_digests_api, "WikimediaClient", lambda: wiki)
    monkeypatch.setattr(
        v1_digests_api,
        "WikimediaIdentityProvider",
        lambda: SimpleNamespace(lookup=lambda _ident: SimpleNamespace(username="RenamedUser")),
    )
    client = _web_client()
    with db.session_scope() as session:
        user = User(wm_sub="91", username="ToolhubName", wikimedia_global_user_id="9001")
        session.add(user)
        session.flush()
        uid = user.id
    with client.session_transaction() as flask_session:
        flask_session.update(uid=uid, csrf="token", epoch=0)

    email = client.post(
        "/v1/digests/subscriptions/",
        json={"channel": "email", "cadence": "weekly", "language": "en"},
        headers={"X-CSRF-Token": "token"},
    )
    assert email.status_code == 201
    # Active on subscribe: OAuth proved the subscriber, and MediaWiki only
    # relays emailuser to an address its owner already confirmed on-wiki.
    assert email.get_json()["subscription"]["active"] is True
    assert email.get_json()["subscription"]["confirmed"] is True
    assert wiki.emails == []

    # Confirmation links already sitting in inboxes must stay harmless.
    email_id = email.get_json()["subscription"]["id"]
    token = digest_delivery.subscription_token(email_id, uid, "confirm")
    confirmed = client.post("/v1/digests/subscriptions/confirm/", json={"token": token})
    assert confirmed.get_json()["subscription"]["confirmed"] is True
    assert confirmed.get_json()["subscription"]["active"] is True

    talk = client.post(
        "/v1/digests/subscriptions/",
        json={"channel": "talk", "cadence": "daily", "wikiDomain": "fr.wikipedia.org"},
        headers={"X-CSRF-Token": "token"},
    )
    assert talk.status_code == 201
    assert talk.get_json()["subscription"]["wikiUsername"] == "RenamedUser"
    assert len(client.get("/v1/user/export/").get_json()["digestSubscriptions"]) == 2
    deleted = client.delete("/v1/user/evolved-data/", headers={"X-CSRF-Token": "token"}).get_json()
    assert deleted["deleted"]["digestSubscriptions"] == 2


def test_scheduled_coordinators_generate_publish_repair_and_bound_delivery(monkeypatch):
    monkeypatch.setattr(digests, "generate_due_editions", lambda **_: {"created": 3, "fallback": 0})
    monkeypatch.setattr(digests, "publish_pending", lambda: {"published": 3, "failed": 0})
    monkeypatch.setattr(digest_delivery, "queue_published_editions", lambda: 2)
    seen = []
    monkeypatch.setattr(digest_delivery, "deliver_pending", lambda *, limit: seen.append(limit) or {"delivered": 2})
    monkeypatch.setenv("DIGEST_DELIVERY_LIMIT", "9999")

    assert digest_publish.run()["publication"]["published"] == 3
    assert digest_deliver.run() == {"queued": 2, "delivery": {"delivered": 2}}
    assert seen == [500]


def test_digest_audit_alerts_on_failed_meta_publication():
    with db.session_scope() as session:
        session.add(
            DigestEdition(
                cadence="daily",
                edition_key="2026-08-12",
                period_start=datetime(2026, 8, 12),
                period_end=datetime(2026, 8, 13),
                status="publication_failed",
            )
        )

    with pytest.raises(digest_audit.DigestAuditError, match="Meta publications failed"):
        digest_audit.audit()


def test_digest_audit_detects_late_ungenerated_period(monkeypatch):
    monkeypatch.setenv("LIFTWING_MODEL", "llm-qwen36-27b")
    monkeypatch.setenv(
        "LIFTWING_API_URL",
        "https://api.wikimedia.org/service/lw/inference/v1/models/llm-qwen36-27b/openai/v1/chat/completions",
    )
    monkeypatch.setattr(digest_audit, "utcnow", lambda: datetime(2026, 8, 14, 9))
    digests.capture_recent_rows([creation(1, "missing", "2026-08-12T12:00:00Z")])

    with pytest.raises(digest_audit.DigestAuditError, match="daily:2026-08-12"):
        digest_audit.audit()


def test_digest_audit_reports_qwen_fallback_when_endpoint_is_configured(monkeypatch):
    edition = _generated_edition(monkeypatch)
    # The fixture pins a fixed calendar date, but the alert only covers periods that
    # closed recently. Move this edition onto the running clock so the test exercises
    # the fallback alarm rather than ageing into a different problem.
    with db.session_scope() as session:
        recent = session.get(DigestEdition, edition.id)
        recent.period_end = utcnow() - timedelta(hours=1)
        recent.period_start = recent.period_end - timedelta(days=1)
    monkeypatch.setenv(
        "LIFTWING_API_URL",
        "https://api.wikimedia.org/service/lw/inference/v1/models/llm-qwen36-27b/openai/v1/chat/completions",
    )
    monkeypatch.setenv("LIFTWING_MODEL", "llm-qwen36-27b")

    with pytest.raises(digest_audit.DigestAuditError, match="fell back"):
        digest_audit.audit()

    assert edition.used_fallback is True


def test_digest_audit_ignores_fallback_on_backfilled_periods(monkeypatch):
    monkeypatch.setenv(
        "LIFTWING_API_URL",
        "https://api.wikimedia.org/service/lw/inference/v1/models/llm-qwen36-27b/openai/v1/chat/completions",
    )
    monkeypatch.setenv("LIFTWING_MODEL", "llm-qwen36-27b")
    # Written moments ago, but for a period that closed months back: catching a stale
    # period up says nothing about whether Lift Wing is serving today's editions.
    with db.session_scope() as session:
        session.add(
            DigestEdition(
                cadence="daily",
                edition_key="2026-04-02",
                period_start=datetime(2026, 4, 2),
                period_end=datetime(2026, 4, 3),
                status="published",
                used_fallback=True,
            )
        )

    status = digest_audit.audit()

    assert status["recentFallbacks"] == 0


def test_meta_blacklist_rejection_is_terminal_and_never_republished(monkeypatch):
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    edition = _generated_edition(monkeypatch)

    class BlacklistingWiki(FakeWiki):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def edit_page(self, *_args, **_kwargs):
            self.attempts += 1
            raise WikimediaAPIError("spamblacklist", "yapk. is blacklisted", permanent=True, recipient_failure=False)

    wiki = BlacklistingWiki()
    with pytest.raises(WikimediaAPIError, match="blacklisted"):
        digests.publish_edition(edition.id, client=wiki)
    with db.session_scope() as session:
        blocked = session.get(DigestEdition, edition.id)
        assert blocked.status == digests.PUBLICATION_BLOCKED_STATUS
        assert "blacklisted" in blocked.last_error

    assert digests.publish_pending(client=wiki) == {"published": 0, "failed": 0}
    assert wiki.attempts == 1


def test_transient_publication_failure_stays_retryable(monkeypatch):
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    edition = _generated_edition(monkeypatch)

    class OfflineWiki(FakeWiki):
        def page_source(self, *_args):
            raise OSError("offline")

    with pytest.raises(OSError, match="offline"):
        digests.publish_edition(edition.id, client=OfflineWiki())

    assert digests.publish_pending(client=FakeWiki())["published"] == 1


def test_digest_audit_reports_blocked_publications_without_alarming(monkeypatch):
    monkeypatch.setenv(
        "LIFTWING_API_URL",
        "https://api.wikimedia.org/service/lw/inference/v1/models/llm-qwen36-27b/openai/v1/chat/completions",
    )
    monkeypatch.setenv("LIFTWING_MODEL", "llm-qwen36-27b")
    with db.session_scope() as session:
        session.add_all(
            [
                DigestEdition(
                    cadence="daily",
                    edition_key="2026-08-12",
                    period_start=datetime(2026, 8, 12),
                    period_end=datetime(2026, 8, 13),
                    status=digests.PUBLICATION_BLOCKED_STATUS,
                ),
                DigestEdition(
                    cadence="daily",
                    edition_key="2021-04-02",
                    period_start=datetime(2021, 4, 2),
                    period_end=datetime(2021, 4, 3),
                    status=digests.OUT_OF_SCOPE_STATUS,
                    used_fallback=True,
                ),
            ]
        )

    status = digest_audit.audit()

    assert status["healthy"] is True
    assert status["blockedPublications"] == 1
    assert status["recentFallbacks"] == 0


def test_public_digest_origin_rejects_paths_and_non_https(monkeypatch):
    monkeypatch.setenv("DIGEST_PUBLIC_BASE_URL", "https://tool.example/digests")
    with pytest.raises(ValueError, match="HTTPS origin"):
        digest_delivery.public_base_url()
    monkeypatch.setenv("DIGEST_PUBLIC_BASE_URL", "http://tool.example")
    with pytest.raises(ValueError, match="HTTPS origin"):
        digest_delivery.public_base_url()


def test_wikimedia_writer_fails_closed_when_token_uses_the_wrong_account(monkeypatch):
    monkeypatch.setenv("WIKIMEDIA_ACCOUNT_NAME", "ExpectedBot")
    client = WikimediaClient(access_token="token")
    monkeypatch.setattr(
        client,
        "request",
        lambda *_args, **_kwargs: {
            "query": {"userinfo": {"name": "DifferentBot"}, "tokens": {"csrftoken": "token+\\"}}
        },
    )

    with pytest.raises(WikimediaAPIError, match="DifferentBot") as failure:
        client.csrf_token("meta.wikimedia.org")
    assert failure.value.permanent is True


def test_wikimedia_writer_accepts_the_underscore_spelling_of_its_own_account(monkeypatch):
    """The configured name and the API answer are two spellings of one account."""
    monkeypatch.setenv("WIKIMEDIA_ACCOUNT_NAME", "NellieBly_Bot")
    client = WikimediaClient(access_token="token")
    monkeypatch.setattr(
        client,
        "request",
        lambda *_args, **_kwargs: {
            "query": {"userinfo": {"name": "NellieBly Bot"}, "tokens": {"csrftoken": "csrf-value"}}
        },
    )

    assert client.csrf_token("meta.wikimedia.org") == "csrf-value"


def test_wikimedia_writer_still_rejects_an_account_differing_only_in_case(monkeypatch):
    """Spelling folds; case does not. MediaWiki capitalizes only the first letter."""
    monkeypatch.setenv("WIKIMEDIA_ACCOUNT_NAME", "Nellie_Bly")
    client = WikimediaClient(access_token="token")
    monkeypatch.setattr(
        client,
        "request",
        lambda *_args, **_kwargs: {
            "query": {"userinfo": {"name": "Nellie bly"}, "tokens": {"csrftoken": "csrf-value"}}
        },
    )

    with pytest.raises(WikimediaAPIError, match="Nellie bly") as failure:
        client.csrf_token("meta.wikimedia.org")
    assert failure.value.permanent is True


def test_toolforge_manifest_schedules_publish_delivery_and_audit_in_utc():
    manifest = (ROOT / "jobs.yaml").read_text(encoding="utf-8")
    assert "name: digest-publish" in manifest
    assert 'schedule: "15 6 * * *"' in manifest
    assert "name: digest-deliver" in manifest
    assert "name: digest-audit" in manifest


def test_wikimedia_client_normalizes_transport_auth_and_api_failures(monkeypatch):
    monkeypatch.setenv("WIKIMEDIA_ACCOUNT_NAME", "DigestBot")
    client = WikimediaClient(access_token=" bearer ", user_agent=" digest-agent ")
    assert client._headers() == {
        "Accept": "application/json",
        "User-Agent": "digest-agent",
        "Authorization": "Bearer bearer",
    }
    assert WikimediaClient(access_token="", user_agent="agent")._headers() == {
        "Accept": "application/json",
        "User-Agent": "agent",
    }

    class Response:
        status_code = 200
        content = b"{}"

        def json(self):
            return {"query": {"ok": True}}

    monkeypatch.setattr(wikimedia_delivery.requests, "request", lambda *_args, **_kwargs: Response())
    assert client.request("meta.wikimedia.org", "GET", {"action": "query"})["query"]["ok"] is True

    response = Response()
    response.content = b"x" * (wikimedia_delivery.MAX_RESPONSE_BYTES + 1)
    monkeypatch.setattr(wikimedia_delivery.requests, "request", lambda *_args, **_kwargs: response)
    with pytest.raises(WikimediaAPIError) as oversized:
        client.request("meta.wikimedia.org", "GET", {})
    assert oversized.value.code == "response-too-large"

    response.content = b"{}"
    response.status_code = 503
    response.json = lambda: {"error": {"code": "nowikiemail", "info": "disabled"}}
    with pytest.raises(WikimediaAPIError) as api_failure:
        client.request("meta.wikimedia.org", "POST", {})
    assert api_failure.value.recipient_failure is True

    response.json = lambda: {"error": {"code": "spamblacklist", "info": "yapk. is blacklisted"}}
    with pytest.raises(WikimediaAPIError) as blacklisted:
        client.request("meta.wikimedia.org", "POST", {})
    assert blacklisted.value.permanent is True
    assert blacklisted.value.recipient_failure is False

    response.status_code = 200
    response.json = lambda: (_ for _ in ()).throw(ValueError("bad json"))
    with pytest.raises(WikimediaAPIError) as transport:
        client.request("meta.wikimedia.org", "GET", {})
    assert transport.value.code == "transport"


def test_wikimedia_client_covers_tokens_reads_identity_and_writes(monkeypatch):
    monkeypatch.setenv("WIKIMEDIA_ACCOUNT_NAME", "DigestBot")
    client = WikimediaClient(access_token="token")
    calls = []

    def request(_domain, method, params):
        calls.append((method, dict(params)))
        action = params["action"]
        if action == "query" and params.get("meta"):
            return {"query": {"userinfo": {"name": "DigestBot"}, "tokens": {"csrftoken": "csrf"}}}
        if action == "query" and params.get("prop") == "revisions":
            return {
                "query": {
                    "pages": [
                        {"revisions": [{"revid": 12, "slots": {"main": {"content": "source"}}}]}
                    ]
                }
            }
        if action == "query" and params.get("list") == "users":
            return {"query": {"users": [{"name": "DigestBot", "centralids": {"CentralAuth": 9}}]}}
        if action == "edit":
            return {"edit": {"result": "Success", "newrevid": 13}}
        if action == "emailuser":
            return {"emailuser": {"result": "Success"}}
        raise AssertionError(params)

    monkeypatch.setattr(client, "request", request)
    assert client.csrf_token("meta.wikimedia.org") == "csrf"
    assert client.csrf_token("meta.wikimedia.org") == "csrf"
    assert client.page_source("meta.wikimedia.org", "Toolhub/Digest") == ("source", "12")
    assert client.user_exists("meta.wikimedia.org", "DigestBot") is True
    assert client.user_identity_matches("meta.wikimedia.org", "DigestBot", "9") is True
    assert client.user_identity_matches("meta.wikimedia.org", "", "9") is False
    edit = client.edit_page(
        "meta.wikimedia.org",
        "Toolhub/Digest",
        "text",
        summary="publish",
        create_only=True,
        base_revision_id="12",
    )
    assert edit.revision_id == "13"
    assert client.email_user("meta.wikimedia.org", "DigestBot", "subject", "text") == "success"
    assert any(params.get("createonly") == 1 and params.get("baserevid") == "12" for _, params in calls)

    monkeypatch.setattr(client, "page_source", lambda *_args: ("marker", "22"))
    existing = client.append_talk_section("en.wikipedia.org", "DigestBot", "Digest", "text", "marker")
    assert existing.revision_id == "22"

    monkeypatch.setattr(client, "page_source", lambda *_args: ("old", "23"))
    appended = client.append_talk_section("en.wikipedia.org", "DigestBot", "Digest", "text", "marker")
    assert appended.revision_id == "13"


def test_wikimedia_client_retries_bad_tokens_and_rejects_malformed_success(monkeypatch):
    client = WikimediaClient(access_token="token")
    tokens = iter(["old", "new"])
    monkeypatch.setattr(client, "csrf_token", lambda _domain, refresh=False: next(tokens))
    attempts = []

    def retry_request(_domain, _method, params):
        attempts.append(params["token"])
        if len(attempts) == 1:
            raise WikimediaAPIError("badtoken", "expired")
        return {"edit": {"result": "Success", "oldrevid": 8}}

    monkeypatch.setattr(client, "request", retry_request)
    assert client.edit_page("meta.wikimedia.org", "Title", "text", summary="summary").revision_id == "8"
    assert attempts == ["old", "new"]

    monkeypatch.setattr(client, "_csrf_post", lambda *_args, **_kwargs: {})
    with pytest.raises(WikimediaAPIError, match="edit did not"):
        client.edit_page("meta.wikimedia.org", "Title", "text", summary="summary")
    monkeypatch.setattr(client, "page_source", lambda *_args: ("", ""))
    with pytest.raises(WikimediaAPIError, match="Talk-page"):
        client.append_talk_section("meta.wikimedia.org", "User", "Digest", "text", "marker")
    with pytest.raises(WikimediaAPIError, match="email did not"):
        client.email_user("meta.wikimedia.org", "User", "subject", "text")


def test_wikimedia_client_rejects_anonymous_tokens_and_non_badtoken_errors(monkeypatch):
    client = WikimediaClient(access_token="token")
    monkeypatch.setattr(
        client,
        "request",
        lambda *_args, **_kwargs: {
            "query": {"userinfo": {"name": ""}, "tokens": {"csrftoken": wikimedia_delivery.ANONYMOUS_CSRF_TOKEN}}
        },
    )
    with pytest.raises(WikimediaAPIError) as anonymous:
        client.csrf_token("meta.wikimedia.org", refresh=True)
    assert anonymous.value.recipient_failure is False

    monkeypatch.setattr(client, "csrf_token", lambda *_args, **_kwargs: "token")
    monkeypatch.setattr(
        client,
        "request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(WikimediaAPIError("readonly", "readonly")),
    )
    with pytest.raises(WikimediaAPIError, match="readonly"):
        client._csrf_post("meta.wikimedia.org", {"action": "edit"})


def test_digest_fact_parsing_period_edges_and_empty_capture():
    assert digests.parse_upstream_timestamp("") is None
    assert digests.parse_upstream_timestamp("2026-08-12T02:00:00+02:00") == datetime(2026, 8, 12)
    assert digests.capture_recent_rows([{"content_type": "list"}]) == 0
    assert digests._upstream_id(
        {"content_id": "tool", "timestamp": "2026-08-12T00:00:00Z", "user": "Editor"}
    ).startswith("recent-sha256:")

    aware = datetime(2026, 8, 12, 12, tzinfo=UTC)
    assert digests.period_for("weekly", aware).key == "2026-W33"
    december = digests.period_for("monthly", datetime(2026, 12, 20))
    assert december.end == datetime(2027, 1, 1)
    with pytest.raises(ValueError, match="unsupported"):
        digests.period_for("yearly", aware)

    assert digests._fact_text({"mul": "Universal"}) == "Universal"
    assert digests._fact_text({"fr": "Outil"}) == "Outil"
    assert digests._fact_list("not-a-list") == []
    assert digests._fact_list([" one ", "", 2]) == ["one", "2"]
    assert digests._first_sentence("") == "A newly registered Toolhub tool."
    assert digests._first_sentence("First sentence. Second sentence.") == "First sentence."


def test_digest_model_response_shapes_and_validation_failures():
    assert digests._extract_model_json({"value": 1}) == {"value": 1}
    assert digests._extract_model_json({"predictions": [{"introduction": "Hi"}]}) == {
        "introduction": "Hi"
    }
    assert digests._extract_model_json({"choices": [{"text": '{"introduction":"Hi"}'}]}) == {
        "introduction": "Hi"
    }
    with pytest.raises(TypeError, match="not an object"):
        digests._extract_model_json([])
    with pytest.raises(TypeError, match="JSON object"):
        digests._extract_model_json({"choices": [{"text": "[1]"}]})

    facts = [{"name": "known", "tasks": ["review"]}]
    with pytest.raises(ValueError, match="requires"):
        digests.validate_editorial({}, facts)
    with pytest.raises(TypeError, match="not an object"):
        digests.validate_editorial({"introduction": "Intro", "highlights": ["bad"]}, facts)
    with pytest.raises(ValueError, match="duplicate"):
        digests.validate_editorial(
            {
                "introduction": "Intro",
                "highlights": [
                    {
                        "tool_name": "known",
                        "blurb": "Review helper.",
                        "evidence_field": "tasks",
                        "evidence": "review",
                    },
                    {
                        "tool_name": "known",
                        "blurb": "Review helper again.",
                        "evidence_field": "tasks",
                        "evidence": "review",
                    },
                ],
            },
            facts,
        )


def test_digest_generation_falls_back_on_bad_model_response(monkeypatch):
    monkeypatch.setenv(
        "LIFTWING_API_URL",
        "https://api.wikimedia.org/service/lw/inference/v1/models/llm-qwen36-27b/openai/v1/chat/completions",
    )
    monkeypatch.setenv("LIFTWING_MODEL", "llm-qwen36-27b")
    monkeypatch.setenv("LIFTWING_TIMEOUT_SECONDS", "0")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "not-json"}}]}

    monkeypatch.setattr(digests.requests, "post", lambda *_args, **_kwargs: Response())
    editorial, model, fallback, response = digests.generate_editorial(
        [{"name": "known", "description": "Useful. More."}], "daily"
    )
    assert model == "llm-qwen36-27b"
    assert fallback is True
    assert response is not None
    assert "JSONDecodeError" in response["_toolhub_generation_error"]
    assert editorial["highlights"][0]["blurb"] == "Useful."


def test_digest_generation_preserves_liftwing_http_failure(monkeypatch):
    monkeypatch.setenv(
        "LIFTWING_API_URL",
        "https://api.wikimedia.org/service/lw/inference/v1/models/llm-qwen36-27b/openai/v1/chat/completions",
    )
    monkeypatch.setenv("LIFTWING_MODEL", "llm-qwen36-27b")

    class Response:
        def raise_for_status(self):
            raise requests.HTTPError("500 Server Error from LiftWing")

    monkeypatch.setattr(digests.requests, "post", lambda *_args, **_kwargs: Response())

    _editorial, _model, fallback, response = digests.generate_editorial(
        [{"name": "known", "description": "Useful."}], "monthly"
    )

    assert fallback is True
    assert response == {"_toolhub_generation_error": "HTTPError: 500 Server Error from LiftWing"}


def test_digest_titles_rendering_empty_editions_and_due_generation(monkeypatch):
    weekly = digests.period_for("weekly", datetime(2026, 8, 12))
    monthly = digests.period_for("monthly", datetime(2026, 8, 12))
    assert "to" in digests._edition_title(weekly)
    assert digests._edition_title(monthly) == "Toolhub Monthly — August 2026"
    facts = [
        {
            "name": "featured",
            "title": "Featured",
            "toolhub_url": "https://tool/featured",
            "url": "https://featured.example/",
            "authors": [{"name": "Ada", "url": "https://people.example/ada"}],
            "maintainers": [{"name": "Grace", "url": "https://people.example/grace"}],
        },
        {
            "name": "other",
            "title": "Other",
            "toolhub_url": "https://tool/other",
            "authors": [None, {"name": "Unsafe", "url": "javascript:alert(1)"}],
        },
    ]
    editorial = {
        "introduction": "Two tools arrived.",
        "highlights": [{"tool_name": "featured", "blurb": "It helps."}],
    }
    rendered = digests.render_editorial(weekly, editorial, facts, used_fallback=False)
    assert "All other additions" in rendered[0]
    assert "Open tool" in rendered[0]
    assert "https://people.example/ada" in rendered[0]
    assert "Authors:" in rendered[1]
    assert "Maintainers: Grace" in rendered[2]
    assert "Unsafe" not in rendered[0]
    assert "Lift Wing" in rendered[2]
    daily_editorial = {
        "introduction": "Two tools support distinct Wikimedia workflows.",
        "highlights": [
            {"tool_name": "featured", "blurb": "It helps."},
            {"tool_name": "other", "blurb": "It helps too."},
        ],
    }
    daily_rendered = digests.render_editorial(
        digests.period_for("daily", datetime(2026, 8, 12)), daily_editorial, facts, used_fallback=False
    )
    assert "Every new tool" in daily_rendered[0]
    assert "EVERY NEW TOOL" in daily_rendered[2]
    assert "All other additions" not in daily_rendered[0]
    assert digests._safe_http_url("javascript:alert(1)") == ""
    assert digests.create_edition(digests.period_for("daily", datetime(2020, 1, 1))) is None

    periods = [digests.period_for("daily", datetime(2026, 8, day)) for day in (10, 11, 12)]
    monkeypatch.setattr(digests, "due_periods", lambda now=None: periods)
    editions = iter([SimpleNamespace(used_fallback=True), None])

    def create(_period):
        if _period == periods[1]:
            raise ValueError("malformed")
        return next(editions)

    monkeypatch.setattr(digests, "create_edition", create)
    assert digests.generate_due_editions(now=datetime(2026, 8, 13)) == {
        "created": 1,
        "fallback": 1,
        "failed": 1,
        "remaining": 0,
    }


def test_digest_publication_missing_collision_marker_and_archive_paths(monkeypatch):
    with pytest.raises(ValueError, match="required"):
        digests.meta_base_title()
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    with pytest.raises(ValueError, match="does not exist"):
        digests.publish_edition(999, client=FakeWiki())

    edition = _generated_edition(monkeypatch)

    collision = FakeWiki()
    collision.pages["Toolhub/Digest/Daily/2026-08-12"] = ("human page", "4")
    with pytest.raises(WikimediaAPIError, match="already exists"):
        digests.publish_edition(edition.id, client=collision)

    class FailingWiki(FakeWiki):
        def page_source(self, *_args):
            raise OSError("offline")

    with pytest.raises(OSError, match="offline"):
        digests.publish_edition(edition.id, client=FailingWiki())
    with db.session_scope() as session:
        assert session.get(DigestEdition, edition.id).status == "publication_failed"

    marker_wiki = FakeWiki()
    title = "Toolhub/Digest/Daily/2026-08-12"
    marker_wiki.pages[title] = (digests.edition_marker(edition), "77")
    published = digests.publish_edition(edition.id, client=marker_wiki)
    assert published.meta_revision_id == "77"
    assert published.meta_page_url.endswith("Toolhub/Digest/Daily/2026-08-12")

    empty_archive = FakeWiki()
    assert digests.refresh_meta_archive(client=empty_archive).endswith("Toolhub/Digest/Archive")
    archive_title = "Toolhub/Digest/Archive"
    source, revision = empty_archive.pages[archive_title]
    empty_archive.pages[archive_title] = (source, revision)
    assert digests.refresh_meta_archive(client=empty_archive).endswith(archive_title)


def test_digest_defensive_capture_and_publish_pending_paths(monkeypatch):
    row = creation(99, "narrowed", "2026-08-12T00:00:00Z")
    monkeypatch.setattr(digests, "is_tool_creation", lambda _row: True)
    monkeypatch.setattr(digests, "parse_upstream_timestamp", lambda _value: None)
    assert digests.capture_recent_rows([row]) == 0
    monkeypatch.undo()

    assert digests.publish_pending(client=FakeWiki()) == {"published": 0, "failed": 0}

    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    edition = _generated_edition(monkeypatch)
    queued = []
    monkeypatch.setattr(digest_delivery, "queue_deliveries", lambda edition_id: queued.append(edition_id) or 0)
    result = digests.publish_pending(client=FakeWiki())
    assert result == {"published": 1, "failed": 0}
    assert queued == [edition.id]

    with db.session_scope() as session:
        session.get(DigestEdition, edition.id).status = "validated"
    monkeypatch.setattr(digests, "publish_edition", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad")))
    assert digests.publish_pending(client=FakeWiki()) == {"published": 0, "failed": 1}


def test_digest_publication_tolerates_delete_during_failed_external_write(monkeypatch):
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    edition = _generated_edition(monkeypatch)

    class DeleteThenFailWiki(FakeWiki):
        def page_source(self, *_args):
            with db.session_scope() as session:
                session.delete(session.get(DigestEdition, edition.id))
            raise OSError("deleted while offline")

    with pytest.raises(OSError, match="deleted"):
        digests.publish_edition(edition.id, client=DeleteThenFailWiki())


def _authenticated_digest_client(*, global_id="9001"):
    client = _web_client()
    with db.session_scope() as session:
        user = User(wm_sub=f"digest-api-{global_id}", username="DigestUser", wikimedia_global_user_id=global_id)
        session.add(user)
        session.flush()
        user_id = user.id
    with client.session_transaction() as flask_session:
        flask_session.update(uid=user_id, csrf="token", epoch=0)
    return client, user_id


def test_digest_public_api_rejects_invalid_queries_and_handles_empty_results():
    client = _web_client()
    assert client.get("/v1/digests/").get_json()["editions"] == []
    assert client.get("/v1/digests/?cadence=yearly").status_code == 400
    assert client.get("/v1/digests/?limit=bad").status_code == 400
    assert client.get("/v1/digests/daily/missing/").status_code == 404
    assert client.get("/feeds/digests/yearly.xml").status_code == 404
    empty_feed = client.get("/feeds/digests/daily.xml")
    assert empty_feed.status_code == 200
    assert b"<lastBuildDate>" in empty_feed.data


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (None, "JSON object"),
        ({"channel": "sms", "cadence": "daily"}, "email or talk"),
        ({"channel": "email", "cadence": "yearly"}, "daily, weekly, or monthly"),
        ({"channel": "email", "cadence": "daily", "language": "fr"}, "only English"),
        ({"channel": "talk", "cadence": "daily", "wikiDomain": "evil.example"}, "Wikimedia"),
    ],
)
def test_digest_subscription_request_validation(payload, message):
    client, _user_id = _authenticated_digest_client()
    response = client.post(
        "/v1/digests/subscriptions/",
        data="null" if payload is None else json.dumps(payload),
        content_type="application/json",
        headers={"X-CSRF-Token": "token"},
    )
    assert response.status_code == 400
    assert message in response.get_json()["error"]


def test_digest_subscription_adopts_the_official_global_id_for_an_older_session(monkeypatch):
    """A session predating the sign-in fix must not be told to connect an account it already has.

    Sign-in resolves the global id now, but an account that signed in before it
    did carries a session that never revisits identity, and nothing else fills
    the column until a reconciliation pass runs -- hours, on the scheduled
    cadence. The official account projection already knows the answer, so the
    endpoint reads it rather than refusing a signed-in user.
    """
    client, user_id = _authenticated_digest_client(global_id=None)
    with db.session_scope() as session:
        session.add(
            ToolhubAccountProjection(
                toolhub_user_id="digest-api-None",
                username="DigestUser",
                wikimedia_global_user_id="9001",
            )
        )
    monkeypatch.setattr(
        v1_digests_api,
        "WikimediaIdentityProvider",
        lambda: SimpleNamespace(lookup=lambda gid: SimpleNamespace(username="DigestUser") if gid == "9001" else None),
    )
    monkeypatch.setattr(
        v1_digests_api,
        "WikimediaClient",
        lambda: SimpleNamespace(user_identity_matches=lambda *_args: True),
    )
    response = client.post(
        "/v1/digests/subscriptions/",
        json={"channel": "email", "cadence": "daily"},
        headers={"X-CSRF-Token": "token"},
    )
    assert response.status_code == 201
    with db.session_scope() as session:
        assert session.get(User, user_id).wikimedia_global_user_id == "9001"


def test_digest_subscription_requires_resolvable_connected_identity(monkeypatch):
    client, _user_id = _authenticated_digest_client(global_id=None)
    response = client.post(
        "/v1/digests/subscriptions/",
        json={"channel": "email", "cadence": "daily"},
        headers={"X-CSRF-Token": "token"},
    )
    assert response.status_code == 400
    assert "sign out and sign in again" in response.get_json()["error"]

    client, _user_id = _authenticated_digest_client()
    monkeypatch.setattr(v1_digests_api, "WikimediaIdentityProvider", lambda: SimpleNamespace(lookup=lambda _gid: None))
    response = client.post(
        "/v1/digests/subscriptions/",
        json={"channel": "email", "cadence": "daily"},
        headers={"X-CSRF-Token": "token"},
    )
    assert response.status_code == 502


def test_digest_subscription_reports_misconfigured_wikimedia_headers(monkeypatch):
    """A rejected header envvar is a server misconfiguration, not an upstream outage."""
    client, _user_id = _authenticated_digest_client()
    monkeypatch.setattr(
        v1_digests_api,
        "WikimediaIdentityProvider",
        lambda: SimpleNamespace(lookup=lambda _gid: SimpleNamespace(username="DigestUser")),
    )

    def refuse():
        message = "WIKIMEDIA_ACCESS_TOKEN contains whitespace or control characters"
        raise ValueError(message)

    monkeypatch.setattr(v1_digests_api, "WikimediaClient", refuse)
    response = client.post(
        "/v1/digests/subscriptions/",
        json={"channel": "talk", "cadence": "daily", "wikiDomain": "en.wikipedia.org"},
        headers={"X-CSRF-Token": "token"},
    )
    assert response.status_code == 500
    # The variable name is the actionable part and is safe to surface; the
    # value it holds is a credential and never appears in the message.
    assert "WIKIMEDIA_ACCESS_TOKEN" in response.get_json()["error"]


def test_digest_subscription_handles_local_identity_and_confirmation_failures(monkeypatch):
    client, _user_id = _authenticated_digest_client()
    identity = SimpleNamespace(username="DigestUser")
    monkeypatch.setattr(
        v1_digests_api,
        "WikimediaIdentityProvider",
        lambda: SimpleNamespace(lookup=lambda _gid: identity),
    )

    class MissingWiki(FakeWiki):
        def user_identity_matches(self, *_args):
            return False

    monkeypatch.setattr(v1_digests_api, "WikimediaClient", MissingWiki)
    missing = client.post(
        "/v1/digests/subscriptions/",
        json={"channel": "talk", "cadence": "daily", "wikiDomain": "en.wikipedia.org"},
        headers={"X-CSRF-Token": "token"},
    )
    assert missing.status_code == 400

    class BrokenWiki(FakeWiki):
        def user_identity_matches(self, *_args):
            raise WikimediaAPIError("readonly", "API unavailable")

    monkeypatch.setattr(v1_digests_api, "WikimediaClient", BrokenWiki)
    broken = client.post(
        "/v1/digests/subscriptions/",
        json={"channel": "talk", "cadence": "daily", "wikiDomain": "en.wikipedia.org"},
        headers={"X-CSRF-Token": "token"},
    )
    assert broken.status_code == 502
    assert broken.get_json()["code"] == "readonly"

    class EmailFailureWiki(FakeWiki):
        def email_user(self, *_args):
            message = "mail unavailable"
            raise OSError(message)

    # Subscribing no longer sends anything, so a wiki that cannot deliver mail
    # can no longer turn a valid subscription into a 502.
    monkeypatch.setattr(v1_digests_api, "WikimediaClient", EmailFailureWiki)
    monkeypatch.setenv("DIGEST_SIGNING_SECRET", "secret")
    email = client.post(
        "/v1/digests/subscriptions/",
        json={"channel": "email", "cadence": "daily"},
        headers={"X-CSRF-Token": "token"},
    )
    assert email.status_code == 201
    assert email.get_json()["subscription"]["active"] is True
    with db.session_scope() as session:
        stored = session.execute(
            select(DigestSubscription).where(DigestSubscription.channel == "email")
        ).scalar_one()
        assert stored.last_error is None


def test_digest_subscription_listing_reactivation_tokens_delete_and_status(monkeypatch):
    client, user_id = _authenticated_digest_client()
    wiki = FakeWiki()
    monkeypatch.setattr(v1_digests_api, "WikimediaClient", lambda: wiki)
    monkeypatch.setattr(
        v1_digests_api,
        "WikimediaIdentityProvider",
        lambda: SimpleNamespace(lookup=lambda _gid: SimpleNamespace(username="DigestUser")),
    )
    payload = {"channel": "talk", "cadence": "weekly", "wikiDomain": "en.wikipedia.org"}
    first = client.post(
        "/v1/digests/subscriptions/", json=payload, headers={"X-CSRF-Token": "token"}
    ).get_json()["subscription"]
    second = client.post(
        "/v1/digests/subscriptions/", json=payload, headers={"X-CSRF-Token": "token"}
    ).get_json()["subscription"]
    assert first["id"] == second["id"]
    assert len(client.get("/v1/digests/subscriptions/").get_json()["subscriptions"]) == 1
    assert client.get("/v1/digests/status/").status_code == 200

    monkeypatch.setenv("DIGEST_SIGNING_SECRET", "secret")
    assert client.post("/v1/digests/subscriptions/confirm/", json={"token": "bad"}).status_code == 400
    read_token = v1_digests_api.read_subscription_token
    monkeypatch.setattr(v1_digests_api, "read_subscription_token", lambda *_args: (999, user_id))
    assert client.post("/v1/digests/subscriptions/confirm/", json={"token": "ignored"}).status_code == 404

    monkeypatch.setattr(v1_digests_api, "read_subscription_token", read_token)
    unsubscribe = digest_delivery.subscription_token(first["id"], user_id, "unsubscribe")
    response = client.post("/v1/digests/subscriptions/unsubscribe/", json={"token": unsubscribe})
    assert response.get_json()["subscription"]["active"] is False
    assert client.delete(
        "/v1/digests/subscriptions/999/", headers={"X-CSRF-Token": "token"}
    ).status_code == 404
    assert client.delete(
        f"/v1/digests/subscriptions/{first['id']}/", headers={"X-CSRF-Token": "token"}
    ).status_code == 200


def test_digest_subscription_tokens_and_confirmation_fail_closed(monkeypatch):
    monkeypatch.delenv("DIGEST_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("TOOLHUB_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="required"):
        digest_delivery.subscription_token(1, 2, "confirm")

    monkeypatch.setenv("DIGEST_SIGNING_SECRET", "secret")
    wrong_action = digest_delivery._serializer().dumps(
        {"subscription_id": 1, "user_id": 2, "action": "unsubscribe"}
    )
    with pytest.raises(ValueError, match="action"):
        digest_delivery.read_subscription_token(wrong_action, "confirm")
    malformed = digest_delivery._serializer().dumps({"action": "confirm"})
    with pytest.raises(ValueError, match="payload"):
        digest_delivery.read_subscription_token(malformed, "confirm")


def test_digest_delivery_queue_repair_and_backfill_paths(monkeypatch):
    assert digest_delivery.queue_deliveries(999) == 0
    edition = _generated_edition(monkeypatch)
    assert digest_delivery.queue_deliveries(edition.id) == 0

    calls = iter([None, 7])

    def concurrent(_edition_id):
        value = next(calls)
        if value is None:
            from sqlalchemy.exc import IntegrityError

            raise IntegrityError("insert", {}, Exception("duplicate"))
        return value

    monkeypatch.setattr(digest_delivery, "_queue_deliveries_once", concurrent)
    assert digest_delivery.queue_deliveries(edition.id) == 7
    monkeypatch.setattr(digest_delivery, "queue_deliveries", lambda edition_id: edition_id)
    with db.session_scope() as session:
        edition.status = "published"
        session.add(edition)
        session.flush()
        edition_id = edition.id
    assert digest_delivery.queue_published_editions() == edition_id


def _delivery_subscription(monkeypatch, *, active=True):
    monkeypatch.setenv("DIGEST_META_BASE_TITLE", "Toolhub/Digest")
    monkeypatch.setenv("DIGEST_SIGNING_SECRET", "secret")
    published = digests.publish_edition(_generated_edition(monkeypatch).id, client=FakeWiki())
    with db.session_scope() as session:
        user = User(wm_sub=f"delivery-{active}", username="User", wikimedia_global_user_id="81")
        session.add(user)
        session.flush()
        subscription = DigestSubscription(
            user_id=user.id,
            channel="email",
            cadence="daily",
            wiki_domain="meta.wikimedia.org",
            wiki_username="User",
            active=active,
            confirmed_at=published.period_end,
        )
        session.add(subscription)
        session.flush()
        delivery = DigestDelivery(edition_id=published.id, subscription_id=subscription.id)
        session.add(delivery)
        session.flush()
        return published.id, subscription.id, delivery.id


def test_digest_delivery_identity_resolution_failures(monkeypatch):
    _edition_id, subscription_id, _delivery_id = _delivery_subscription(monkeypatch)
    wiki = FakeWiki()
    with db.session_scope() as session:
        session.get(User, session.get(DigestSubscription, subscription_id).user_id).wikimedia_global_user_id = None
    with pytest.raises(ValueError, match="connected"):
        digest_delivery._current_identity(subscription_id, wiki, _identity_provider(), {})

    with db.session_scope() as session:
        session.get(User, session.get(DigestSubscription, subscription_id).user_id).wikimedia_global_user_id = "81"
    with pytest.raises(RuntimeError, match="resolved"):
        digest_delivery._current_identity(
            subscription_id, wiki, SimpleNamespace(lookup=lambda _gid: None), {}
        )

    wiki.user_identity_matches = lambda *_args: False
    with pytest.raises(WikimediaAPIError) as mismatch:
        digest_delivery._current_identity(subscription_id, wiki, _identity_provider(), {})
    assert mismatch.value.recipient_failure is True

    class DeleteSubscriptionWiki(FakeWiki):
        def user_identity_matches(self, *_args):
            with db.session_scope() as session:
                session.delete(session.get(DigestSubscription, subscription_id))
            return True

    with pytest.raises(ValueError, match="disappeared"):
        digest_delivery._current_identity(
            subscription_id, DeleteSubscriptionWiki(), _identity_provider(), {}
        )


def test_digest_delivery_failure_terminal_cancelled_and_skipped_paths(monkeypatch):
    now = datetime(2026, 8, 13)
    assert digest_delivery._record_failure(999, 999, ValueError("missing"), now) == "skipped"

    _edition_id, subscription_id, delivery_id = _delivery_subscription(monkeypatch)
    with db.session_scope() as session:
        session.get(DigestDelivery, delivery_id).attempts = digest_delivery.MAX_ATTEMPTS - 1
    assert digest_delivery._record_failure(delivery_id, subscription_id, ValueError("terminal"), now) == "failed"
    recipient_error = WikimediaAPIError("nowikiemail", "disabled", permanent=True)
    assert digest_delivery._record_failure(delivery_id, 999, recipient_error, now) == "suspended"

    assert digest_delivery._deliver_one(999, FakeWiki(), _identity_provider(), {}, now) == "skipped"
    with db.session_scope() as session:
        session.get(DigestSubscription, subscription_id).active = False
        session.get(DigestDelivery, delivery_id).status = "pending"
    assert digest_delivery._deliver_one(
        delivery_id, FakeWiki(), _identity_provider(), {}, now
    ) == "cancelled"
    with db.session_scope() as session:
        assert session.get(DigestDelivery, delivery_id).status == "cancelled"

    with pytest.raises(ValueError, match="unsupported"):
        digest_delivery._deliver(
            SimpleNamespace(), SimpleNamespace(channel="sms"), FakeWiki()
        )


def test_digest_delivery_handles_rows_deleted_after_external_success(monkeypatch):
    edition_id, subscription_id, delivery_id = _delivery_subscription(monkeypatch)

    class DeleteAfterSendWiki(FakeWiki):
        def email_user(self, *_args):
            with db.session_scope() as session:
                session.delete(session.get(DigestDelivery, delivery_id))
            return "success"

    assert digest_delivery._deliver_one(
        delivery_id,
        DeleteAfterSendWiki(),
        _identity_provider(),
        {},
        datetime(2026, 8, 13),
    ) == "delivered"

    with db.session_scope() as session:
        replacement = DigestDelivery(edition_id=edition_id, subscription_id=subscription_id)
        session.add(replacement)
        session.flush()
        replacement_id = replacement.id

    class DeleteSubscriptionAfterSendWiki(FakeWiki):
        def email_user(self, *_args):
            with db.session_scope() as session:
                session.delete(session.get(DigestSubscription, subscription_id))
            return "success"

    assert digest_delivery._deliver_one(
        replacement_id,
        DeleteSubscriptionAfterSendWiki(),
        _identity_provider(),
        {},
        datetime(2026, 8, 13),
    ) == "delivered"

    monkeypatch.setattr(digest_delivery, "WikimediaClient", FakeWiki)
    monkeypatch.setattr(digest_delivery, "WikimediaIdentityProvider", lambda: _identity_provider())
    assert digest_delivery.deliver_pending(limit=0) == {
        "delivered": 0,
        "retry": 0,
        "suspended": 0,
        "failed": 0,
        "cancelled": 0,
        "skipped": 0,
    }


@pytest.mark.parametrize(
    ("cadence", "key"),
    [
        ("daily", "2026-99-99"),
        ("daily", "2026-8-09"),
        ("weekly", "2026-32"),
        ("weekly", "2026-W99"),
        ("monthly", "2026-99"),
        ("yearly", "2026"),
    ],
)
def test_digest_period_keys_reject_invalid_or_unsupported_values(cadence, key):
    with pytest.raises(ValueError, match="digest edition"):
        digests.period_from_key(cadence, key)


def test_compact_model_facts_drop_empty_lists_and_keep_nonempty_evidence():
    compact = digests._compact_model_fact(  # noqa: SLF001 - contract at the Lift Wing boundary
        {"name": "alpha", "tasks": ["", " editing "], "keywords": [], "description": " Useful "}
    )

    assert compact == {"name": "alpha", "description": "Useful", "tasks": ["editing"]}


def test_website_only_regeneration_validates_input_and_external_state(monkeypatch):
    period = digests.period_from_key("daily", "2026-08-09")
    with pytest.raises(ValueError, match="one or more unique"):
        digests.regenerate_website_editions([])
    with pytest.raises(ValueError, match="one or more unique"):
        digests.regenerate_website_editions([period, period])
    with pytest.raises(ValueError, match="captured creation events"):
        digests.regenerate_website_editions([period])

    digests.capture_recent_rows([creation(1, "external-tool", "2026-08-09T12:00:00Z")])
    monkeypatch.setattr(
        digests,
        "generate_editorial",
        lambda facts, _cadence: (
            {
                "introduction": "One verified tool supports Wikimedia work.",
                "highlights": [{"tool_name": facts[0]["name"], "blurb": "It supports Wikimedia work."}],
            },
            "llm-qwen36-27b",
            False,
            {},
        ),
    )
    edition = digests.create_edition(period, initial_status=digests.WEBSITE_ONLY_STATUS, require_model=True)
    with db.session_scope() as session:
        session.get(DigestEdition, edition.id).meta_page_url = "https://meta.wikimedia.org/wiki/Example"

    with pytest.raises(ValueError, match="external publication state"):
        digests.regenerate_website_editions([period])


def test_create_edition_returns_the_winner_of_a_concurrent_insert(monkeypatch):
    digests.capture_recent_rows([creation(1, "race-tool", "2026-08-09T12:00:00Z")])
    period = digests.period_from_key("daily", "2026-08-09")
    monkeypatch.setattr(
        digests,
        "generate_editorial",
        lambda facts, _cadence: (
            {
                "introduction": "One verified tool supports Wikimedia work.",
                "highlights": [{"tool_name": facts[0]["name"], "blurb": "It supports Wikimedia work."}],
            },
            "llm-qwen36-27b",
            False,
            {},
        ),
    )
    winner = SimpleNamespace(id=99)
    calls = iter((None, winner))
    monkeypatch.setattr(digests, "_existing_edition", lambda *_args, **_kwargs: next(calls))

    assert digests.create_edition(period) is winner
