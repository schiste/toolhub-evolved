# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for backend/v1_common.py: the shared helpers used by every /v1 route module.

Every test runs on a fresh in-memory SQLite database (see the `app` fixture);
Toolhub/network calls are monkeypatched. This file is self-contained (no
conftest) and is scoped to closing coverage gaps left by tests/proxy/test_backend.py.
"""

import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
import backend.v1_common as v1c  # noqa: E402
from backend import authz, db, security, source_analysis_common, source_analyzer, toolhub  # noqa: E402
from backend.models import (  # noqa: E402
    ActivityRow,
    CrawlerUrl,
    Favorite,
    Person,
    PersonProfile,
    SourceAnalysisReport,
    ToolAuthorClaim,
    ToolAuthorKey,
    ToolHealthTarget,
    ToolinfoControlChallenge,
    ToolList,
    ToolMedia,
    ToolOverlay,
    ToolPersonRelationship,
    ToolRecord,
    ToolThanks,
    User,
    utcnow,
)
from backend.sync import (
    REVIEW_APPROVED,
    REVIEW_PENDING,
    SYNC_LOCAL_FALLBACK,
    SYNC_OFFICIAL,
)


@pytest.fixture
def app():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    application.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    security.clear_rate_limits()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def add_user(username="Ada", role=authz.ROLE_USER):
    with db.session_scope() as s:
        user = User(wm_sub=username, username=username, role=role)
        s.add(user)
        s.flush()
        return user.id


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def test_iso_present_and_absent():
    now = utcnow()
    assert v1c.iso(now) == now.isoformat(timespec="seconds") + "Z"
    assert v1c.iso(None) == ""


def test_parse_iso_invalid_falls_back_to_now():
    before = utcnow()
    parsed = v1c.parse_iso("not-a-timestamp")
    assert parsed >= before


def test_parse_iso_naive_and_aware():
    naive = v1c.parse_iso("2024-01-01T00:00:00")
    assert naive.tzinfo is None
    aware = v1c.parse_iso("2024-01-01T00:00:00+02:00")
    assert aware.tzinfo is None  # converted to naive UTC


def test_parse_optional_iso_absent_and_present():
    assert v1c.parse_optional_iso(None) is None
    assert v1c.parse_optional_iso("") is None
    assert v1c.parse_optional_iso("2024-01-01T00:00:00") is not None


def test_payload_value_camel_and_snake():
    assert v1c.payload_value({"fooBar": 1}, "fooBar", "foo_bar") == 1
    assert v1c.payload_value({"foo_bar": 2}, "fooBar", "foo_bar") == 2
    assert v1c.payload_value({}, "fooBar", "foo_bar") is None


def test_clean_name_present_and_absent():
    assert v1c.clean_name("  Ada  ") == "Ada"
    assert v1c.clean_name("   ") is None
    assert v1c.clean_name(None) is None
    assert v1c.clean_name("x" * 300) == "x" * v1c.MAX_NAME


# ---------------------------------------------------------------------------
# public_json_response
# ---------------------------------------------------------------------------


def test_public_json_response_fresh_and_not_modified(app):
    with app.test_request_context("/"):
        resp = v1c.public_json_response({"a": 1})
        assert resp.status_code == 200
        etag = resp.headers["ETag"]
    with app.test_request_context("/", headers={"If-None-Match": etag}):
        resp2 = v1c.public_json_response({"a": 1})
        assert resp2.status_code == 304


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def test_media_payload():
    row = ToolMedia(
        id=1,
        tool_name="ada-tool",
        user_id=1,
        url="https://example.org/a.png",
        title="Screenshot",
        license="CC0",
        source="upload",
        review_status=REVIEW_PENDING,
        sync_status=None,
        created_at=utcnow(),
    )
    payload = v1c.media_payload(row)
    assert payload["toolName"] == "ada-tool"
    assert payload["syncStatus"] == v1c.SYNC_EVOLVED_REAL


def test_sync_label_known_and_unknown():
    assert v1c.sync_label(SYNC_OFFICIAL) == "Official Toolhub"
    assert v1c.sync_label("bogus") == "Local draft"
    assert v1c.sync_label(None) == "Local draft"


def test_with_common_meta_minimal_and_full():
    minimal = SimpleNamespace()
    out = v1c.with_common_meta({"id": 1}, minimal)
    assert out["source"] == v1c.SOURCE_LOCAL
    assert "lastSyncedAt" not in out
    assert "lastError" not in out
    assert "officialId" not in out
    assert "toolhubResponse" not in out
    assert "validationErrors" not in out

    full = SimpleNamespace(
        source="official",
        sync_status="evolved_real",
        last_synced_at=utcnow(),
        last_error="boom",
        official_list_id=42,
        official_crawler_url_id=None,
        last_toolhub_response={"ok": True},
        validation_errors=[{"field": "x"}],
    )
    out2 = v1c.with_common_meta({"id": 1}, full, include_official_id=True)
    assert out2["lastSyncedAt"]
    assert out2["lastError"] == "boom"
    assert out2["officialId"] == 42
    assert out2["toolhubResponse"] == {"ok": True}
    assert out2["validationErrors"] == [{"field": "x"}]

    crawler_like = SimpleNamespace(
        official_list_id=None,
        official_crawler_url_id=99,
    )
    out3 = v1c.with_common_meta({"id": 1}, crawler_like, include_official_id=True)
    assert out3["officialId"] == 99
    assert out3["id"] == 99


def test_list_payload_and_crawler_url_payload():
    now = utcnow()
    tl = ToolList(
        client_id="c1",
        user_id=1,
        title="My List",
        description="desc",
        tools=["a"],
        created_at=now,
        modified_at=now,
        official_list_id=7,
    )
    payload = v1c.list_payload(tl)
    assert payload["id"] == "c1"
    assert payload["officialId"] == 7

    cu = CrawlerUrl(
        id=1,
        user_id=1,
        url="https://example.org/toolinfo.json",
        added_at=now,
        enabled=True,
        last_checked_at=None,
        last_status=None,
        official_crawler_url_id=5,
    )
    cpayload = v1c.crawler_url_payload(cu)
    assert cpayload["localId"] == 1
    assert cpayload["officialId"] == 5
    assert cpayload["lastStatus"] == ""


def test_local_tool_is_public_combinations():
    now = utcnow()
    public_approved = ToolRecord(
        tool_name="a", user_id=1, record={"origin": "api"}, visibility="public",
        review_status=REVIEW_APPROVED, modified_at=now,
    )
    assert v1c.local_tool_is_public(public_approved) is True

    public_pending = ToolRecord(
        tool_name="a", user_id=1, record={"origin": "api"}, visibility="public",
        review_status=REVIEW_PENDING, modified_at=now,
    )
    assert v1c.local_tool_is_public(public_pending) is False

    private_crawler = ToolRecord(
        tool_name="a", user_id=1, record={"origin": "crawler"}, visibility="private",
        review_status=REVIEW_APPROVED, modified_at=now,
    )
    assert v1c.local_tool_is_public(private_crawler) is True

    private_plain = ToolRecord(
        tool_name="a", user_id=1, record={"origin": "api"}, visibility="private",
        review_status=REVIEW_APPROVED, modified_at=now,
    )
    assert v1c.local_tool_is_public(private_plain) is False

    non_dict_record = ToolRecord(
        tool_name="a", user_id=1, record=None, visibility="public",
        review_status=REVIEW_APPROVED, modified_at=now,
    )
    assert v1c.local_tool_is_public(non_dict_record) is True


def test_tool_record_payload_minimal_and_full():
    now = utcnow()
    minimal = ToolRecord(tool_name="a", user_id=1, record={"title": "A"}, modified_at=now)
    out = v1c.tool_record_payload(minimal)
    assert out["visibility"] == v1c.VISIBILITY_PRIVATE
    assert "officialName" not in out
    assert "toolhubResponse" not in out
    assert "validationErrors" not in out

    full = ToolRecord(
        tool_name="a",
        user_id=1,
        record={"title": "A"},
        modified_at=now,
        official_name="Official A",
        last_toolhub_response={"ok": True},
        validation_errors=[{"field": "x"}],
        visibility="public",
        review_status=REVIEW_APPROVED,
    )
    out2 = v1c.tool_record_payload(full)
    assert out2["officialName"] == "Official A"
    assert out2["toolhubResponse"] == {"ok": True}
    assert out2["validationErrors"] == [{"field": "x"}]


def test_health_target_payload_and_thanks_payload():
    now = utcnow()
    ht = ToolHealthTarget(
        id=1, tool_name="a", target_url="https://x", created_by_user_id=1,
        review_status=REVIEW_PENDING, enabled=True, last_checked_at=None,
        last_status=None, last_error=None, created_at=now,
    )
    payload = v1c.health_target_payload(ht)
    assert payload["lastStatus"] == ""
    assert payload["lastError"] == ""

    th = ToolThanks(id=1, tool_name="a", user_id=1, active=True, created_at=now, updated_at=now)
    tpayload = v1c.thanks_payload(th)
    assert tpayload["active"] is True


def test_moderation_item_all_kinds():
    now = utcnow()
    curation = SimpleNamespace(
        id=1, tool_name="a", patch={"x": 1}, rationale="why",
        review_status=REVIEW_PENDING, created_by_user_id=1,
        created_at=now, modified_at=now,
    )
    out = v1c.moderation_item("catalog-curations", curation)
    assert out["kind"] == "catalog-curations"
    assert out["data"]["rationale"] == "why"

    tool_record = ToolRecord(id=2, tool_name="a", user_id=1, record={}, modified_at=now)
    out2 = v1c.moderation_item("tool-records", tool_record)
    assert out2["data"]["visibility"] == v1c.VISIBILITY_PRIVATE

    ht = ToolHealthTarget(id=3, tool_name="a", target_url="https://x", created_by_user_id=1, created_at=now)
    out3 = v1c.moderation_item("health-targets", ht)
    assert out3["id"] == 3

    media = ToolMedia(id=4, tool_name="a", user_id=1, url="https://x/a.png", created_at=now)
    out4 = v1c.moderation_item("media", media)
    assert out4["id"] == 4

    thanks = ToolThanks(id=5, tool_name="a", user_id=1, created_at=now, updated_at=now)
    out5 = v1c.moderation_item("thanks", thanks)
    assert out5["id"] == 5


def test_bad_with_and_without_validation_errors(app):
    with app.app_context():
        r1 = v1c.bad("boom")
        assert r1.status_code == 400
        assert "lastError" not in r1.get_json()

        r2 = v1c.bad("boom", [{"field": "x", "message": "bad"}])
        assert r2.get_json()["lastError"] == "boom"
        assert r2.get_json()["validationErrors"]


def test_deny(app):
    with app.app_context():
        resp = v1c.deny(403, "nope")
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "nope"


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [None, "", "   "],
)
def test_url_validation_message_required(value):
    assert v1c.url_validation_message(value, label="URL") == "URL is required."


def test_url_validation_message_too_long():
    long_url = "https://example.org/" + ("a" * v1c.MAX_URL)
    msg = v1c.url_validation_message(long_url, label="URL")
    assert msg == f"URL must be {v1c.MAX_URL} characters or fewer."


def test_url_validation_message_spaces():
    msg = v1c.url_validation_message("https://example.org/has space", label="URL")
    assert msg == "URL cannot contain spaces."


def test_url_validation_message_scheme_https_only():
    msg = v1c.url_validation_message("http://example.org", label="URL")
    assert msg == "URL must use https."


def test_url_validation_message_scheme_http_or_https_allowed():
    msg = v1c.url_validation_message("ftp://example.org", label="URL", https_only=False)
    assert msg == "URL must use http or https."
    ok = v1c.url_validation_message("http://example.org", label="URL", https_only=False)
    assert ok is None


def test_url_validation_message_missing_host():
    msg = v1c.url_validation_message("https:///path", label="URL")
    assert msg == "URL must include a host."


def test_url_validation_message_valid():
    assert v1c.url_validation_message("https://example.org/toolinfo.json", label="URL") is None


def test_url_validation_message_unparsable_raises_value_error(monkeypatch):
    def boom(_value):
        raise ValueError("bad url")

    monkeypatch.setattr(v1c, "urlparse", boom)
    msg = v1c.url_validation_message("https://example.org", label="URL")
    assert msg == "URL is not a valid URL."


def test_url_validation_bad(app):
    with app.app_context():
        resp = v1c.url_validation_bad("toolinfoUrl", "bad url")
        assert resp.status_code == 400
        assert resp.get_json()["validationErrors"] == [{"field": "toolinfoUrl", "message": "bad url"}]


# ---------------------------------------------------------------------------
# Claims / keys
# ---------------------------------------------------------------------------


def test_claim_payload():
    now = utcnow()
    claim = ToolAuthorClaim(
        id=1,
        tool_name="a",
        author_name="Ada",
        toolhub_username="Ada",
        verification_status="verified",
        verification_method="toolinfo_url_control",
        checked_at=now,
        created_at=now,
        updated_at=now,
    )
    payload = v1c.claim_payload(claim)
    assert payload["toolName"] == "a"


def test_author_key_payload():
    now = utcnow()
    key = ToolAuthorKey(
        id=1, toolhub_username="Ada", key_id="k1", public_key="abc", created_at=now,
    )
    payload = v1c.author_key_payload(key)
    assert payload["keyId"] == "k1"
    assert payload["fingerprint"].startswith("SHA256:")


def test_author_claim_owned_by_and_author_key_owned_by(app):
    uid = add_user()
    with db.session_scope() as s:
        user = s.get(User, uid)
        expr = v1c.author_claim_owned_by(user)
        expr2 = v1c.author_key_owned_by(user)
        assert expr is not None
        assert expr2 is not None


def test_source_analysis_payload_dict_and_non_dict_report():
    now = utcnow()
    row_dict = SourceAnalysisReport(
        id=1, user_id=1, tool_name="a", source_label="lbl",
        report={"x": 1}, review_status=REVIEW_PENDING, created_at=now,
    )
    payload = v1c.source_analysis_payload(row_dict)
    assert payload["report"] == {"x": 1}

    row_none = SourceAnalysisReport(
        id=2, user_id=1, tool_name=None, source_label=None,
        report=None, review_status=REVIEW_PENDING, created_at=now,
    )
    payload2 = v1c.source_analysis_payload(row_none)
    assert payload2["report"] == {}
    assert payload2["toolName"] == ""


# ---------------------------------------------------------------------------
# Health / maintainer scoring
# ---------------------------------------------------------------------------


def test_score_grade_all_bands():
    assert v1c.score_grade(None) == "unknown"
    assert v1c.score_grade(90) == "strong"
    assert v1c.score_grade(75) == "good"
    assert v1c.score_grade(55) == "needs-attention"
    assert v1c.score_grade(10) == "high-risk"


def test_health_status_all_bands():
    assert v1c.health_status(None) == "unknown"
    assert v1c.health_status(90) == "healthy"
    assert v1c.health_status(60) == "watch"
    assert v1c.health_status(10) == "at-risk"


def test_bounded_score_clamps():
    assert v1c.bounded_score(-5) == 0
    assert v1c.bounded_score(500) == 100
    assert v1c.bounded_score(50) == 50


def test_summary_dimension_score_present_and_absent():
    dim = v1c.summary_dimension("k", "Label", 90, 1.0, "status", "summary")
    assert dim["includedInScore"] is True
    assert dim["grade"] == "strong"

    dim_none = v1c.summary_dimension("k", "Label", None, 1.0, "status", "summary")
    assert dim_none["includedInScore"] is False
    assert dim_none["score"] is None


def test_latest_public_health_core_statement_compiles():
    stmt = v1c.latest_public_health_core_statement("ada-tool")
    assert "source_analysis_reports" in str(stmt)


def test_source_repository_summary_variants():
    assert v1c.source_repository_summary({}) is None
    assert v1c.source_repository_summary({"repositoryContext": "nope"}) is None
    assert v1c.source_repository_summary({"repositoryContext": {"repository": {}}}) is None

    report = {
        "repositoryContext": {
            "repository": {
                "url": "https://example.org/repo",
                "branch": "",
                "commitCount": "12",
                "contributorCount": None,
                "lastCommitAgeDays": "bad-int",
            }
        }
    }
    summary = v1c.source_repository_summary(report)
    assert summary["url"] == "https://example.org/repo"
    assert "branch" not in summary
    assert summary["commitCount"] == 12
    assert "contributorCount" not in summary
    assert "lastCommitAgeDays" not in summary


def test_source_repository_summary_keeps_false_flags():
    """A host saying "not archived" is a fact; a host with no such field is not."""
    report = {
        "repositoryContext": {
            "repository": {
                "url": "https://example.org/repo",
                "archived": False,
                "dirty": True,
            }
        }
    }
    summary = v1c.source_repository_summary(report)
    assert summary["archived"] is False
    assert summary["dirty"] is True

    unknown = v1c.source_repository_summary(
        {"repositoryContext": {"repository": {"url": "https://example.org/repo", "archived": "yes"}}}
    )
    assert "archived" not in unknown
    assert "dirty" not in unknown


def test_source_repository_summary_covers_every_stored_key():
    """The panel promises the repository record, so no stored key may go unread."""
    repository = {
        "url": "https://example.org/repo",
        "branch": "main",
        "defaultBranch": "main",
        "commitSha": "abc123",
        "lastCommitAt": "2026-08-01T00:00:00Z",
        "analyzedAt": "2026-08-02T00:00:00Z",
        "provider": "github",
        "tag": "v1.2.3",
        "commitCount": 12,
        "contributorCount": 3,
        "lastCommitAgeDays": 21,
        "archived": False,
        "dirty": False,
    }
    assert set(repository) == source_analysis_common.REPOSITORY_CONTEXT_REPOSITORY_KEYS
    assert set(v1c.source_repository_summary({"repositoryContext": {"repository": repository}})) == set(repository)


def test_latest_public_health_core_variants(app):
    uid = add_user()
    now = utcnow()
    with db.session_scope() as s:
        assert v1c.latest_public_health_core(s, "missing-tool") is None

        s.add(
            SourceAnalysisReport(
                user_id=uid, tool_name="no-core", report={"other": 1},
                review_status=REVIEW_APPROVED, created_at=now, reviewed_at=now,
            )
        )
        s.flush()
        assert v1c.latest_public_health_core(s, "no-core") is None

        s.add(
            SourceAnalysisReport(
                user_id=uid,
                tool_name="with-core",
                report={
                    "healthCore": {
                        "score": "77",
                        "grade": "good",
                        "confidence": 0.5,
                        "dimensions": "not-a-list",
                    },
                    "repositoryContext": {"repository": {"url": "https://x"}},
                },
                review_status=REVIEW_APPROVED,
                created_at=now,
                reviewed_at=now,
            )
        )
        s.flush()
        core = v1c.latest_public_health_core(s, "with-core")
        assert core["score"] == 77
        assert core["dimensions"] == []
        assert core["repository"]["url"] == "https://x"


def test_health_target_dimension_none_and_present():
    assert v1c.health_target_dimension(None) is None

    now = utcnow()
    known = ToolHealthTarget(
        id=1, tool_name="a", target_url="https://x", created_by_user_id=1,
        last_status="healthy", last_checked_at=now, last_error=None, created_at=now,
    )
    dim = v1c.health_target_dimension(known)
    assert dim["score"] == 95
    assert dim["confidence"] == 0.9

    unknown_status = ToolHealthTarget(
        id=2, tool_name="a", target_url="https://x", created_by_user_id=1,
        last_status="mystery", last_checked_at=None, last_error="oops", created_at=now,
    )
    dim2 = v1c.health_target_dimension(unknown_status)
    assert dim2["score"] is None
    assert dim2["confidence"] == 0.35
    assert dim2["lastError"] == "oops"


def test_maintainer_activity_label_all_branches():
    assert v1c.maintainer_activity_label("active", "verified") == "maintained"
    assert v1c.maintainer_activity_label("quiet", "probable") == "maintained"
    assert v1c.maintainer_activity_label("active", "unknown") == "active-maintainer"
    assert v1c.maintainer_activity_label("stale", "unknown") == "maintainer-stale"
    assert v1c.maintainer_activity_label("dormant", "unknown") == "maintainer-stale"
    assert v1c.maintainer_activity_label("unknown", "verified") == "verified-maintainer"
    assert v1c.maintainer_activity_label("unknown", "unknown") == "unknown"


def test_maintainer_dimension_score_none_branch():
    dim = v1c.maintainer_dimension({})
    assert dim["score"] is None
    assert dim["counts"] == {}


def test_maintainer_dimension_activity_score_adjustments():
    base = {
        "bestConfidence": 50,
        "healthCounts": {"verifiedPeople": 0, "people": 0},
        "people": [{"activity": {"status": "active"}}],
        "status": "unknown",
    }
    dim = v1c.maintainer_dimension(base)
    # active (+5) then people count is zero -> forced back to None
    assert dim["score"] is None

    for status, expected_included in (
        ("quiet", True),
        ("stale", True),
        ("dormant", True),
    ):
        payload = {
            "bestConfidence": 60,
            "healthCounts": {"verifiedPeople": 2, "people": 3},
            "people": [{"activity": {"status": status}}],
            "status": "unknown",
        }
        dim2 = v1c.maintainer_dimension(payload)
        assert dim2["includedInScore"] is expected_included
        assert dim2["score"] is not None


def test_maintainer_dimension_verified_people_bonus_and_people_missing_key():
    payload = {
        "bestConfidence": 40,
        "healthCounts": {"verifiedPeople": 1},  # no "people" key -> not clean_int -> None
        "people": [],
        "status": "unknown",
    }
    dim = v1c.maintainer_dimension(payload)
    assert dim["score"] is None


def test_health_summary_from_dimensions_weighted_and_empty():
    dims = [
        {"score": 80, "weight": 1.0, "includedInScore": True},
        {"score": 20, "weight": 0.0, "includedInScore": True},
        {"score": 50, "weight": 1.0, "includedInScore": False},
    ]
    summary = v1c.health_summary_from_dimensions("a", dims, source_health=None)
    assert summary["score"] == 80
    assert summary["confidence"] == round(1.0 / 2.0, 2)

    empty = v1c.health_summary_from_dimensions("a", [], source_health=None)
    assert empty["score"] is None
    assert empty["confidence"] == 0


# ---------------------------------------------------------------------------
# tool_names_from_request
# ---------------------------------------------------------------------------


def test_tool_names_from_request_dedupes_and_bounds(app):
    with app.test_request_context("/?name=Ada&name=ada&name=&names=Bee%2CBee%2C%20"):
        names = v1c.tool_names_from_request()
    assert names == ["Ada", "ada", "Bee"]


# ---------------------------------------------------------------------------
# build_local_tool_summary
# ---------------------------------------------------------------------------


def test_build_local_tool_summary_with_source_health_without_runtime_health(app):
    uid = add_user()
    now = utcnow()
    with db.session_scope() as s:
        s.add(
            SourceAnalysisReport(
                user_id=uid,
                tool_name="ada-tool",
                report={"healthCore": {"score": 80, "confidence": 0.5, "dimensions": []}},
                review_status=REVIEW_APPROVED,
                created_at=now,
                reviewed_at=now,
            )
        )
    with db.session_scope() as s:
        summary = v1c.build_local_tool_summary(s, "ada-tool")
    assert summary["toolName"] == "ada-tool"
    assert summary["health"]["sourceHealth"] is not None
    assert any(d["key"] == "source-health" for d in summary["health"]["dimensions"])
    # "maintainerDimension" is always the maintainer-status entry (index 0 when
    # there is no source-health dimension ahead of it, else index 1).
    assert summary["maintainerDimension"]["key"] == "maintainer-status"


def test_build_local_tool_summary_without_source_health_with_runtime_health(app):
    uid = add_user()
    now = utcnow()
    with db.session_scope() as s:
        s.add(
            ToolHealthTarget(
                tool_name="bee-tool",
                target_url="https://x",
                created_by_user_id=uid,
                review_status=REVIEW_APPROVED,
                enabled=True,
                last_status="healthy",
                last_checked_at=now,
                created_at=now,
            )
        )
    with db.session_scope() as s:
        summary = v1c.build_local_tool_summary(s, "bee-tool")
    assert summary["health"]["sourceHealth"] is None
    assert summary["maintainerDimension"]["key"] == "maintainer-status"
    assert any(d["key"] == "runtime-health" for d in summary["health"]["dimensions"])


# ---------------------------------------------------------------------------
# clean_author_key_id
# ---------------------------------------------------------------------------


def test_clean_author_key_id_valid_and_invalid():
    assert v1c.clean_author_key_id("valid-key.1:2_3") == "valid-key.1:2_3"
    assert v1c.clean_author_key_id("has a space") is None
    assert v1c.clean_author_key_id("") is None


# ---------------------------------------------------------------------------
# toolhub_tool_detail / claim_tool_or_error
# ---------------------------------------------------------------------------


def test_toolhub_tool_detail_variants(monkeypatch):
    monkeypatch.setattr(toolhub, "public_api_get", lambda _path: {"name": "ada-tool"})
    assert v1c.toolhub_tool_detail("ada-tool") == {"name": "ada-tool"}

    monkeypatch.setattr(toolhub, "public_api_get", lambda _path: ["not", "a", "dict"])
    assert v1c.toolhub_tool_detail("ada-tool") is None

    monkeypatch.setattr(toolhub, "public_api_get", lambda _path: {"name": ""})
    assert v1c.toolhub_tool_detail("ada-tool") is None


def test_claim_tool_or_error_blank_name(app):
    with app.app_context():
        tool, resp = v1c.claim_tool_or_error("   ")
    assert tool is None
    assert resp.status_code == 400


def test_claim_tool_or_error_toolhub_api_error(app, monkeypatch):
    def boom(_path):
        raise toolhub.ToolhubAPIError(502, {"detail": "upstream down"})

    monkeypatch.setattr(toolhub, "public_api_get", boom)
    with app.app_context():
        tool, resp = v1c.claim_tool_or_error("ada-tool")
    assert tool is None
    assert resp.status_code == 502


def test_claim_tool_or_error_requests_exception(app, monkeypatch):
    def boom(_path):
        raise toolhub.requests.RequestException("network down")

    monkeypatch.setattr(toolhub, "public_api_get", boom)
    with app.app_context():
        tool, resp = v1c.claim_tool_or_error("ada-tool")
    assert tool is None
    assert resp.status_code == 502


def test_claim_tool_or_error_not_found_and_name_mismatch(app, monkeypatch):
    monkeypatch.setattr(toolhub, "public_api_get", lambda _path: None)
    with app.app_context():
        tool, resp = v1c.claim_tool_or_error("ada-tool")
    assert tool is None
    assert resp.status_code == 404

    monkeypatch.setattr(toolhub, "public_api_get", lambda _path: {"name": "other-tool"})
    with app.app_context():
        tool2, resp2 = v1c.claim_tool_or_error("ada-tool")
    assert tool2 is None
    assert resp2.status_code == 404


def test_claim_tool_or_error_success(monkeypatch):
    monkeypatch.setattr(toolhub, "public_api_get", lambda _path: {"name": "ada-tool"})
    tool, resp = v1c.claim_tool_or_error("ada-tool")
    assert resp is None
    assert tool["name"] == "ada-tool"


# ---------------------------------------------------------------------------
# record_successful_toolhub_write
# ---------------------------------------------------------------------------


def test_record_successful_toolhub_write_success(app):
    uid = add_user()
    with db.session_scope() as s:
        user = s.get(User, uid)
        v1c.record_successful_toolhub_write(user, "PATCH", "/api/tools/ada-tool/", None, {"name": "ada-tool"})


def test_record_successful_toolhub_write_swallows_exceptions(app, monkeypatch):
    uid = add_user()

    class RaisingProvider:
        def record_success(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(v1c, "TOOLHUB_WRITE_PROVIDER", RaisingProvider())
    with db.session_scope() as s:
        user = s.get(User, uid)
        # Must not raise.
        v1c.record_successful_toolhub_write(user, "PATCH", "/api/tools/ada-tool/", None, None)


# ---------------------------------------------------------------------------
# current_policy_user / enforce / require_policy / require_policy_or_abort
# ---------------------------------------------------------------------------


def test_current_policy_user_success(app):
    uid = add_user()
    with app.test_request_context("/"):
        session["uid"] = uid
        session["epoch"] = 0
        user, denied = v1c.current_policy_user()
    assert denied is None
    assert user.id == uid


def test_enforce_allowed_and_denied(app):
    uid = add_user()
    with app.app_context(), db.session_scope() as s:
        user = s.get(User, uid)
        allowed = v1c.enforce(user, authz.ACTION_TOOLHUB_WRITE)
        assert allowed is None
        denied = v1c.enforce(user, authz.ACTION_OPERATOR)
        assert denied is not None
        assert denied.status_code == 403


def test_require_policy_allowed_and_denied(app):
    uid = add_user()
    with app.test_request_context("/"):
        session["uid"] = uid
        session["epoch"] = 0
        user, denied = v1c.require_policy(authz.ACTION_TOOLHUB_WRITE)
        assert denied is None
        assert user.id == uid

        user2, denied2 = v1c.require_policy(authz.ACTION_OPERATOR)
        assert user2 is None
        assert denied2.status_code == 403


def test_require_policy_or_abort_allowed(app):
    uid = add_user()
    with app.test_request_context("/"):
        session["uid"] = uid
        session["epoch"] = 0
        user = v1c.require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
        assert user.id == uid


def test_require_policy_or_abort_denied_raises(app):
    uid = add_user()
    with app.test_request_context("/"), pytest.raises(Exception):  # noqa: B017, PT011 - werkzeug HTTPException subtype
        session["uid"] = uid
        session["epoch"] = 0
        v1c.require_policy_or_abort(authz.ACTION_OPERATOR)


# ---------------------------------------------------------------------------
# upstream_path / upstream_path_parts / string_payload_value
# ---------------------------------------------------------------------------


def test_upstream_path():
    assert v1c.upstream_path("tools/ada/") == "/api/tools/ada/"
    assert v1c.upstream_path("/tools/ada/") == "/api/tools/ada/"


def test_upstream_path_parts_filters_empty_segments():
    assert v1c.upstream_path_parts("/api/tools/ada%20tool/") == ["api", "tools", "ada tool"]
    assert v1c.upstream_path_parts("//") == []


def test_string_payload_value_variants():
    assert v1c.string_payload_value(None, "name") is None
    assert v1c.string_payload_value(["not", "a", "dict"], "name") is None
    assert v1c.string_payload_value({"name": None, "title": "  "}, "name", "title") is None
    assert v1c.string_payload_value({"name": None, "title": " Ada "}, "name", "title") == "Ada"


# ---------------------------------------------------------------------------
# invalidate_official_api_cache
# ---------------------------------------------------------------------------


def test_invalidate_official_api_cache_short_or_non_api_path(app):
    v1c.invalidate_official_api_cache("/api", None, None)  # too short, no-op
    v1c.invalidate_official_api_cache("/nope/x/y", None, None)  # not "api"


def test_invalidate_official_api_cache_tools_with_name_in_path(app):
    v1c.invalidate_official_api_cache("/api/tools/ada-tool/", None, None)


def test_invalidate_official_api_cache_tools_name_from_response(app):
    v1c.invalidate_official_api_cache("/api/tools/", None, {"name": "ada-tool"})


def test_invalidate_official_api_cache_tools_name_from_request(app):
    v1c.invalidate_official_api_cache("/api/tools/", {"name": "ada-tool"}, {})


def test_invalidate_official_api_cache_tools_name_missing_entirely(app):
    v1c.invalidate_official_api_cache("/api/tools/", {}, {})


def test_invalidate_official_api_cache_lists_with_id(app):
    v1c.invalidate_official_api_cache("/api/lists/7/", None, None)


def test_invalidate_official_api_cache_lists_id_from_response(app):
    v1c.invalidate_official_api_cache("/api/lists/", None, {"id": 8})


def test_invalidate_official_api_cache_lists_id_missing(app):
    v1c.invalidate_official_api_cache("/api/lists/", None, {})


def test_invalidate_official_api_cache_unrelated_collection(app):
    v1c.invalidate_official_api_cache("/api/users/whoami/", None, None)


# ---------------------------------------------------------------------------
# json_object_body
# ---------------------------------------------------------------------------


def test_json_object_body_valid(app):
    with app.test_request_context("/", json={"a": 1}):
        body, err = v1c.json_object_body()
    assert err is None
    assert body == {"a": 1}


def test_json_object_body_invalid(app):
    with app.test_request_context("/", data="[1,2,3]", content_type="application/json"):
        body, err = v1c.json_object_body()
    assert body is None
    assert err.status_code == 400


# ---------------------------------------------------------------------------
# safe_failure_activity_payload
# ---------------------------------------------------------------------------


def test_safe_failure_activity_payload_local_dict():
    payload = {
        "toolhubResponse": {"status_code": 502, "code": "bad_gateway"},
        "lastError": "boom",
        "local": {"name": "ada-tool", "id": 1, "deleted": False, "custom": "x", "source": "local"},
    }
    safe = v1c.safe_failure_activity_payload(payload)
    assert safe["httpStatus"] == 502
    assert safe["toolhubCode"] == "bad_gateway"
    assert safe["lastError"] == "boom"
    assert safe["submittedFields"] == ["custom"]


def test_safe_failure_activity_payload_local_not_dict():
    payload = {"local": "not-a-dict"}
    safe = v1c.safe_failure_activity_payload(payload)
    assert "submittedFields" not in safe


def test_safe_failure_activity_payload_drops_empty_values():
    payload = {}
    safe = v1c.safe_failure_activity_payload(payload)
    # syncStatus is a fixed non-empty constant, so it always survives the filter;
    # every other (empty/absent) field is dropped.
    assert safe == {"syncStatus": SYNC_LOCAL_FALLBACK}


# ---------------------------------------------------------------------------
# emit_structured_activity
# ---------------------------------------------------------------------------


def test_emit_structured_activity_official_and_fallback(app):
    uid = add_user()
    with db.session_scope() as s:
        user = s.get(User, uid)
        v1c.emit_structured_activity(
            s,
            user,
            action="create",
            object_type="tool",
            object_key="ada-tool",
            official_status=v1c.SYNC_OFFICIAL,
            payload={"name": "ada-tool"},
        )
        v1c.emit_structured_activity(
            s,
            user,
            action="create",
            object_type="tool",
            object_key="bee-tool",
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"local": {"name": "bee-tool"}, "lastError": "nope"},
            title="Bee Tool",
        )
    with db.session_scope() as s:
        rows = list(s.execute(ActivityRow.__table__.select()).all())
    assert len(rows) == 4  # 2 kinds x 2 calls


# ---------------------------------------------------------------------------
# create_control_challenge / verify_control_challenge_record
# ---------------------------------------------------------------------------


def test_create_control_challenge_bad_url(app):
    uid = add_user()
    with app.app_context(), db.session_scope() as s:
        user = s.get(User, uid)
        row, resp = v1c.create_control_challenge(s, user, "ada-tool", "http://insecure.example")
    assert row is None
    assert resp.status_code == 400


def test_create_control_challenge_fetch_raises(app, monkeypatch):
    uid = add_user()
    monkeypatch.setattr(v1c, "fetch_matching_item", lambda _url, _name: (_ for _ in ()).throw(ValueError("no match")))
    with app.app_context(), db.session_scope() as s:
        user = s.get(User, uid)
        row, resp = v1c.create_control_challenge(s, user, "ada-tool", "https://example.org/toolinfo.json")
    assert row is None
    assert resp.status_code == 400
    assert "ada-tool" in resp.get_json()["error"]


def test_create_control_challenge_success(app, monkeypatch):
    uid = add_user()
    monkeypatch.setattr(v1c, "fetch_matching_item", lambda _url, name: {"name": name})
    with db.session_scope() as s:
        user = s.get(User, uid)
        row, resp = v1c.create_control_challenge(s, user, "ada-tool", "https://example.org/toolinfo.json")
    assert resp is None
    assert row.status == v1c.CHALLENGE_STATUS_PENDING


def _make_challenge(uid, *, status=None, expires_at=None):
    now = utcnow()
    row = ToolinfoControlChallenge(
        user_id=uid,
        tool_name="ada-tool",
        toolinfo_url="https://example.org/toolinfo.json",
        challenge_token="tok123",
        status=status or v1c.CHALLENGE_STATUS_PENDING,
        created_at=now,
        expires_at=expires_at or (now + timedelta(hours=1)),
    )
    return row


def test_verify_control_challenge_record_expired(app):
    uid = add_user()
    with app.app_context(), db.session_scope() as s:
        user = s.get(User, uid)
        row = _make_challenge(uid, expires_at=utcnow() - timedelta(hours=1))
        s.add(row)
        s.flush()
        claim, resp = v1c.verify_control_challenge_record(s, user, row)
    assert claim is None
    assert resp.status_code == 409
    assert row.status == v1c.CHALLENGE_STATUS_EXPIRED


def test_verify_control_challenge_record_already_verified_skips_fetch(app, monkeypatch):
    uid = add_user()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("fetch_matching_item should not be called when already verified")

    monkeypatch.setattr(v1c, "fetch_matching_item", fail_if_called)
    with db.session_scope() as s:
        user = s.get(User, uid)
        row = _make_challenge(uid, status=v1c.CHALLENGE_STATUS_VERIFIED)
        s.add(row)
        s.flush()
        claim, resp = v1c.verify_control_challenge_record(s, user, row)
    assert resp is None
    assert claim is not None
    assert row.status == v1c.CHALLENGE_STATUS_VERIFIED


def test_verify_control_challenge_record_fetch_raises(app, monkeypatch):
    uid = add_user()
    monkeypatch.setattr(
        v1c, "fetch_matching_item", lambda _url, _name: (_ for _ in ()).throw(ValueError("fetch failed"))
    )
    with app.app_context(), db.session_scope() as s:
        user = s.get(User, uid)
        row = _make_challenge(uid)
        s.add(row)
        s.flush()
        claim, resp = v1c.verify_control_challenge_record(s, user, row)
    assert claim is None
    assert resp.status_code == 400
    assert row.last_error


def test_verify_control_challenge_record_token_mismatch(app, monkeypatch):
    uid = add_user()
    monkeypatch.setattr(
        v1c,
        "fetch_matching_item",
        lambda _url, name: {"name": name, "x_toolhub_evolved_verification": {"challenge": "wrong-token"}},
    )
    with app.app_context(), db.session_scope() as s:
        user = s.get(User, uid)
        row = _make_challenge(uid)
        s.add(row)
        s.flush()
        claim, resp = v1c.verify_control_challenge_record(s, user, row)
    assert claim is None
    assert resp.status_code == 400
    assert row.last_error


def test_verify_control_challenge_record_success(app, monkeypatch):
    uid = add_user()
    monkeypatch.setattr(
        v1c,
        "fetch_matching_item",
        lambda _url, name: {"name": name, "x_toolhub_evolved_verification": {"challenge": "tok123"}},
    )
    with db.session_scope() as s:
        user = s.get(User, uid)
        row = _make_challenge(uid)
        s.add(row)
        s.flush()
        claim, resp = v1c.verify_control_challenge_record(s, user, row)
    assert resp is None
    assert claim is not None
    assert row.status == v1c.CHALLENGE_STATUS_VERIFIED
    assert row.last_error is None


# ---------------------------------------------------------------------------
# profile_payload
# ---------------------------------------------------------------------------


def test_profile_payload_none_and_present():
    person = Person(id=1, canonical_key="ck1", public_id="p1", display_name="Ada")
    out = v1c.profile_payload(None, person)
    assert out["bio"] == ""
    assert out["visibility"] == "public"

    now = utcnow()
    profile = PersonProfile(
        person_id=1, bio="hi", avatar_url="https://x/a.png", website_url="https://x",
        location="Earth", links=None, visibility="private", updated_at=now,
    )
    out2 = v1c.profile_payload(profile, person)
    assert out2["bio"] == "hi"
    assert out2["links"] == []
    assert out2["visibility"] == "private"

    profile2 = PersonProfile(
        person_id=1, bio="hi", links=[{"label": "x", "url": "https://x"}], visibility="public", updated_at=now,
    )
    out3 = v1c.profile_payload(profile2, person)
    assert out3["links"] == [{"label": "x", "url": "https://x"}]


# ---------------------------------------------------------------------------
# merged_maps
# ---------------------------------------------------------------------------


def test_merged_maps_overlay_and_plain_rows():
    now = utcnow()
    overlay_owned = ToolOverlay(
        kind="edits", tool_name="a", user_id=1, patch={"title": "A"}, modified_at=now,
        base_revision="rev1", field_statuses={"title": "edited"}, review_status="approved",
    )
    overlay_other = ToolOverlay(
        kind="edits", tool_name="b", user_id=2, patch={"title": "B"}, modified_at=now,
        base_revision=None, field_statuses=None, review_status=None,
        last_error="secret", last_toolhub_response={"x": 1}, validation_errors=[{"y": 1}],
    )
    plain = SimpleNamespace(tool_name="c", record={"title": "C"})

    merged = v1c.merged_maps([overlay_owned, overlay_other, plain], viewer_uid=1)
    assert merged["a"]["baseRevision"] == "rev1"
    assert merged["a"]["fieldStatuses"] == {"title": "edited"}
    assert merged["a"]["reviewStatus"] == "approved"
    assert merged["a"]["viewerOwned"] is True

    assert merged["b"]["viewerOwned"] is False
    assert "lastError" not in merged["b"]
    assert "toolhubResponse" not in merged["b"]
    assert "validationErrors" not in merged["b"]

    assert merged["c"] == {"title": "C"}

    merged_no_viewer = v1c.merged_maps([overlay_owned], viewer_uid=None)
    assert "viewerOwned" not in merged_no_viewer["a"]


# ---------------------------------------------------------------------------
# assemble_overlay
# ---------------------------------------------------------------------------


def test_assemble_overlay_full(app):
    owner = add_user(username="Owner")
    other = add_user(username="Other")
    now = utcnow()
    with db.session_scope() as s:
        s.add(Favorite(user_id=owner, tool_name="fav-tool", position=0))
        s.add(
            ToolList(
                client_id="list1", user_id=owner, title="L", description="", tools=[],
                created_at=now, modified_at=now,
            )
        )
        s.add(
            CrawlerUrl(
                user_id=owner, url="https://example.org/toolinfo.json", added_at=now, enabled=True,
            )
        )
        s.add(
            ToolOverlay(
                kind="edits", tool_name="edited-tool", user_id=owner, patch={"title": "E"}, modified_at=now,
            )
        )
        s.add(
            ToolOverlay(
                kind="annos", tool_name="anno-tool", user_id=owner, patch={"note": "N"}, modified_at=now,
            )
        )
        # Owned public+approved -> included, viewerOwned True.
        s.add(
            ToolRecord(
                tool_name="owned-public", user_id=owner, record={"origin": "api"}, visibility="public",
                review_status=REVIEW_APPROVED, modified_at=now,
            )
        )
        # Owned private -> included (always visible to owner), viewerOwned True.
        s.add(
            ToolRecord(
                tool_name="owned-private", user_id=owner, record={"origin": "api"}, visibility="private",
                review_status=REVIEW_PENDING, modified_at=now,
                last_error="oops", last_toolhub_response={"x": 1}, validation_errors=[{"y": 1}],
            )
        )
        # Other user's public+approved -> included, viewerOwned False, sensitive fields stripped.
        s.add(
            ToolRecord(
                tool_name="other-public", user_id=other, record={"origin": "api"}, visibility="public",
                review_status=REVIEW_APPROVED, modified_at=now,
                last_error="oops", last_toolhub_response={"x": 1}, validation_errors=[{"y": 1}],
            )
        )
        # Other user's public+pending -> excluded entirely by the query filter
        # (not selected: visibility=public with deleted_at None still selected by
        # the query, but local_tool_is_public() is False so triggers `continue`).
        s.add(
            ToolRecord(
                tool_name="other-public-pending", user_id=other, record={"origin": "api"}, visibility="public",
                review_status=REVIEW_PENDING, modified_at=now,
            )
        )
        s.add(
            ActivityRow(
                kind="revisions", client_id="r1", user_id=owner, row={"comment": "hi"}, created_at=now,
            )
        )
        s.add(
            ActivityRow(
                kind="auditlogs", client_id="a1", user_id=owner, row={"action": "create"}, created_at=now,
            )
        )

    overlay = v1c.assemble_overlay(owner)
    assert overlay["favorites"] == ["fav-tool"]
    assert overlay["lists"][0]["id"] == "list1"
    assert overlay["crawlerUrls"][0]["url"] == "https://example.org/toolinfo.json"
    assert "edited-tool" in overlay["toolEdits"]
    assert "anno-tool" in overlay["toolAnnos"]

    tool_new = overlay["toolNew"]
    assert tool_new["owned-public"]["viewerOwned"] is True
    assert tool_new["owned-private"]["viewerOwned"] is True
    assert tool_new["owned-private"]["lastError"] == "oops"
    assert tool_new["other-public"]["viewerOwned"] is False
    assert "lastError" not in tool_new["other-public"]
    assert "other-public-pending" not in tool_new

    assert overlay["revisions"] == [] or isinstance(overlay["revisions"], list)
    assert overlay["auditlogs"] == [] or isinstance(overlay["auditlogs"], list)


# ---------------------------------------------------------------------------
# clean_tool_record
# ---------------------------------------------------------------------------


def test_clean_tool_record_invalid_variants():
    assert v1c.clean_tool_record({}) is None
    assert v1c.clean_tool_record({"title": "", "description": "d", "url": "https://x"}) is None
    assert v1c.clean_tool_record({"title": "T", "description": None, "url": "https://x"}) is None
    assert v1c.clean_tool_record({"title": "T", "description": "d", "url": "http://x"}) is None
    assert v1c.clean_tool_record({"title": "T", "description": "d", "url": 5}) is None


def test_clean_tool_record_valid_full():
    rec = {
        "title": "T",
        "description": "d",
        "url": "https://x",
        "deprecated": True,
        "experimental": False,
        "origin": "crawler",
        "repository": "https://repo",
        "license": "",
        "toolType": None,
        "keywords": ["a", 1, 2.5, None],
        "forWikis": "not-a-list",
        "uiLanguages": ["en"],
    }
    clean = v1c.clean_tool_record(rec)
    assert clean["deprecated"] is True
    assert clean["origin"] == "crawler"
    assert clean["repository"] == "https://repo"
    assert clean["license"] is None
    assert clean["toolType"] is None
    assert clean["keywords"] == ["a", "1", "2.5"]
    assert clean["forWikis"] == []
    assert clean["uiLanguages"] == ["en"]


def test_clean_tool_record_default_origin():
    rec = {"title": "T", "description": "d", "url": "https://x", "origin": "api"}
    clean = v1c.clean_tool_record(rec)
    assert clean["origin"] == "api"


# ---------------------------------------------------------------------------
# data_patch
# ---------------------------------------------------------------------------


def test_data_patch_strips_meta_and_canonical_keys():
    patch = {"title": "T", "source": "local", "name": "n", "origin": "api", "keep": 1}
    cleaned = v1c.data_patch(patch)
    assert cleaned == {"title": "T", "keep": 1}


def test_source_technology_summary_carries_only_technologies_with_a_declared_version():
    report = {
        "technology": [
            {"value": "Flask", "label": "Flask", "version": "3.0.2", "versionSpecs": ["==3.0.2"]},
            {"value": "Python", "label": "Python", "versionSpecs": [">=3.11"]},
            {"value": "JavaScript", "label": "JavaScript"},
            "not a row",
        ]
    }
    assert v1c.source_technology_summary(report) == [
        {"value": "Flask", "label": "Flask", "version": "3.0.2", "spec": "==3.0.2"},
        # A range is a declaration without a release, so it travels as a spec.
        {"value": "Python", "label": "Python", "spec": ">=3.11"},
    ]


def test_source_technology_summary_drops_the_spec_when_manifests_disagree():
    """Two constraints mean no single declaration, so neither is shown as the one."""
    report = {"technology": [{"value": "Flask", "label": "Flask", "versionSpecs": ["==2.3.3", "==3.0.2"]}]}
    assert v1c.source_technology_summary(report) == []


def test_source_technology_summary_is_empty_without_a_technology_list():
    assert v1c.source_technology_summary({}) == []
    assert v1c.source_technology_summary({"technology": "nope"}) == []


def test_source_technology_summary_stops_at_the_public_cap():
    report = {
        "technology": [
            {"value": f"Tech{index}", "label": f"Tech{index}", "version": "1.0.0"}
            for index in range(v1c.MAX_PUBLIC_TECHNOLOGIES + 5)
        ]
    }
    assert len(v1c.source_technology_summary(report)) == v1c.MAX_PUBLIC_TECHNOLOGIES
