# SPDX-License-Identifier: GPL-3.0-or-later
"""Digest event, UTC period, and immutable edition tests."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from flask import Flask
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
import backend.v1_digests as v1_digests_api  # noqa: E402
import digest_audit  # noqa: E402
import digest_deliver  # noqa: E402
import digest_publish  # noqa: E402
from backend import db, digest_delivery, digests  # noqa: E402
from backend.models import (  # noqa: E402
    DigestDelivery,
    CanonicalToolCache,
    DigestEdition,
    DigestEditionTool,
    DigestOperationalState,
    DigestSubscription,
    ToolActivityEvent,
    User,
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
                record={"name": "example", "title": "Example", "description": "Helps editors review changes."},
                expires_at=datetime(2026, 8, 14),
                stale_until=datetime(2026, 8, 15),
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
        assert tool.highlighted is True


def test_model_editorial_rejects_unknown_tools_and_links():
    facts = [{"name": "known"}]
    with pytest.raises(ValueError, match="unknown"):
        digests.validate_editorial(
            {"introduction": "New tools.", "highlights": [{"tool_name": "invented", "blurb": "Useful."}]},
            facts,
        )


def test_model_editorial_requires_exact_frozen_fact_evidence():
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
    with pytest.raises(ValueError, match="links"):
        digests.validate_editorial(
            {
                "introduction": "New tools.",
                "highlights": [{"tool_name": "known", "blurb": "See https://malicious.invalid"}],
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
                confirmed_at=published.published_at,
            )
        )
    digest_delivery.queue_deliveries(published.id)

    result = digest_delivery.deliver_pending(
        client=MisconfiguredWiki(), identity_provider=_identity_provider()
    )

    assert result["retry"] == 1
    with db.session_scope() as session:
        assert session.execute(select(DigestSubscription)).scalar_one().active is True


def test_delivery_eligibility_starts_at_confirmation_not_historical_publication(monkeypatch):
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
                confirmed_at=published.published_at + timedelta(microseconds=1),
            )
        )

    assert digest_delivery.queue_deliveries(published.id) == 0


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
                confirmed_at=published.published_at,
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
    assert detail["tools"][0]["name"] == "example"
    assert feed.status_code == 200
    assert b"<content:encoded>" in feed.data
    assert b"Toolhub/Digest/Daily/2026-08-12" in feed.data


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
    assert email.get_json()["subscription"]["active"] is False
    confirmation_link = next(line for line in wiki.emails[0][3].splitlines() if line.startswith("http"))
    token = parse_qs(urlparse(confirmation_link).query)["token"][0]
    confirmed = client.post("/v1/digests/subscriptions/confirm/", json={"token": token})
    assert confirmed.get_json()["subscription"]["confirmed"] is True

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
    monkeypatch.setattr(digests, "generate_due_editions", lambda: {"created": 3, "fallback": 0})
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
    monkeypatch.setenv(
        "LIFTWING_API_URL",
        "https://api.wikimedia.org/service/lw/inference/v1/models/llm-qwen36-27b/openai/v1/chat/completions",
    )
    monkeypatch.setenv("LIFTWING_MODEL", "llm-qwen36-27b")

    with pytest.raises(digest_audit.DigestAuditError, match="fell back"):
        digest_audit.audit()

    assert edition.used_fallback is True


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


def test_toolforge_manifest_schedules_publish_delivery_and_audit_in_utc():
    manifest = (ROOT / "jobs.yaml").read_text(encoding="utf-8")
    assert "name: digest-publish" in manifest
    assert 'schedule: "15 6 * * *"' in manifest
    assert "name: digest-deliver" in manifest
    assert "name: digest-audit" in manifest
