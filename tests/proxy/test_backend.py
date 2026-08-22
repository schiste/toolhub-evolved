# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the backend package: db plumbing, security guards, OAuth, /v1 API.

Every test runs on a fresh in-memory SQLite database; OAuth's upstream calls
are monkeypatched. The suite exercises every branch (the coverage gate is
100% with branch coverage across app, backend and crawl).
"""

import sys
from base64 import b64encode
from collections import deque
from contextlib import contextmanager
from datetime import timedelta
from json import dumps
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from flask import Flask
from sqlalchemy import inspect, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
import backend.v1 as v1_api  # noqa: E402
import backend.v1_common as v1_common_api  # noqa: E402
import backend.v1_me as v1_me_api  # noqa: E402
import backend.v1_write as v1_write_api  # noqa: E402
from backend import (  # noqa: E402
    api_cache,
    author_claims,
    authz,
    canonical_tools,
    catalog_read,
    catalog_projection,
    db,
    github_issues,
    graph_payload,
    maintainer_index,
    people_index,
    people_policy,
    recent_owners,
    security,
    sync,
    token_crypto,
    tool_summaries,
    toolhub,
)
from backend.author_claims import (  # noqa: E402
    AuthorNameProvider,
    SignedToolinfoProvider,
    ToolforgeMaintainerProvider,
    ToolhubWriteProvider,
)
from backend.public_identity import (  # noqa: E402
    PublicIdentityResolver,
    ToolforgeIdentityProvider,
    WikimediaIdentityProvider,
)
from backend.models import (  # noqa: E402
    ActivityRow,
    ApiCache,
    ApiCacheMeta,
    CanonicalToolCache,
    CatalogCuration,
    CatalogFacetValue,
    CrawlerRun,
    CrawlerUrl,
    Favorite,
    IssueReport,
    Person,
    PersonActivitySummary,
    PersonIdentifier,
    PersonProfile,
    PersonReconciliationConflict,
    PersonReconciliationMapping,
    PersonReconciliationRun,
    SourceAnalysisReport,
    ToolAuthorClaim,
    ToolAuthorKey,
    ToolEvent,
    ToolHealthTarget,
    ToolforgeAccountProjection,
    ToolforgeMembershipProjection,
    ToolhubToken,
    ToolinfoControlChallenge,
    ToolinfoDiscovery,
    ToolinfoDiscoveryMeta,
    ToolinfoSource,
    ToolinfoSourceItem,
    ToolList,
    ToolMedia,
    ToolOverlay,
    ToolOwnerCache,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    ToolRecord,
    ToolSummaryCache,
    ToolThanks,
    ToolhubAccountProjection,
    ToolhubAccountSyncState,
    UnresolvedAttributionEvidence,
    User,
    utcnow,
)
from backend.v1 import (  # noqa: E402
    FEED_KEEP_CAP,
)
from backend.v1_common import (  # noqa: E402
    invalidate_official_api_cache,
    iso,
    merged_maps,
    parse_iso,
    parse_optional_iso,
    string_payload_value,
)
from backend.author_claims import author_names_from_toolhub_tool as _toolhub_author_names  # noqa: E402
from backend.v1_write import (  # noqa: E402
    _message_from_payload,
    _official_annotation_payload,
    _official_id,
    _string_list,
    _validation_errors,
)

TOOLSADMIN_MAINTAINERS_TABLE_HTML = """
<div class="cdx-table">
  <div class="cdx-table__header">
    <div class="cdx-table__header__caption" aria-hidden="true">Maintainers</div>
  </div>
  <div class="cdx-table__table-wrapper">
    <table class="cdx-table__table">
      <caption>Maintainers</caption>
      <tbody>
        <tr><td>Schiste</td></tr>
      </tbody>
    </table>
  </div>
</div>
"""


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


@pytest.fixture(autouse=True)
def _offline_toolforge_ldap(monkeypatch):
    """Keep identity tests off real CentralAuth and Wikimedia LDAP."""
    monkeypatch.setattr(
        v1_api,
        "PUBLIC_IDENTITY_RESOLVER",
        PublicIdentityResolver(
            wikimedia=WikimediaIdentityProvider(fetcher=lambda _id: (404, {})),
            toolforge=ToolforgeIdentityProvider(lookup=lambda _name: []),
        ),
    )


def identity_resolver(username, *tools, global_id="160", toolforge_uid=None):
    return PublicIdentityResolver(
        wikimedia=WikimediaIdentityProvider(
            fetcher=lambda _id: (200, {"query": {"globaluserinfo": {"id": global_id, "name": username}}})
        ),
        toolforge=ToolforgeIdentityProvider(
            lookup=lambda _name: [
                {
                    "uid": [toolforge_uid or username.casefold()],
                    "uidNumber": ["3067"],
                    "cn": [username],
                    "wikimediaGlobalAccountId": [global_id],
                    "wikimediaGlobalAccountName": [username],
                    "memberOf": [f"cn=tools.{tool},ou=servicegroups,dc=wikimedia,dc=org" for tool in tools],
                }
            ]
        ),
    )


def add_user(username="Ada", wm_sub="42", role=authz.ROLE_USER, wikimedia_global_user_id=None):
    with db.session_scope() as s:
        user = User(
            wm_sub=wm_sub,
            username=username,
            role=role,
            wikimedia_global_user_id=wikimedia_global_user_id,
        )
        s.add(user)
        s.flush()
        return user.id


def add_toolforge_account(
    *,
    global_id="160",
    developer_username="Schiste",
    shell_username="schiste",
    tools=("toolhub-evolved",),
):
    with db.session_scope() as s:
        s.add(
            ToolforgeAccountProjection(
                uid_number="3067",
                uid=shell_username,
                normalized_uid=shell_username.casefold(),
                developer_username=developer_username,
                normalized_developer_username=developer_username.casefold(),
                wikimedia_global_user_id=global_id,
            )
        )
        for tool_name in tools:
            s.add(ToolforgeMembershipProjection(uid_number="3067", tool_name=tool_name))


def sign_in(client, uid, csrf="tok"):
    with db.session_scope() as s:
        user = s.get(User, uid)
        epoch = user.session_epoch or 0 if user is not None else 0
    with client.session_transaction() as sess:
        sess["uid"] = uid
        sess["csrf"] = csrf
        sess["epoch"] = epoch  # sign-out bumps this; a stale cookie must not authenticate


def put_overlay(client, key, value, csrf="tok"):
    return client.put(f"/v1/overlay/{key}", json=value, headers={"X-CSRF-Token": csrf})


# ---- register / config -----------------------------------------------------


def test_register_env_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("TOOLHUB_DB_URL", f"sqlite:///{tmp_path}/nested/env.sqlite3")
    monkeypatch.setenv("TOOLHUB_SECRET_KEY", "env-secret")
    monkeypatch.setenv("TOOLHUB_INSECURE_COOKIES", "1")
    application = Flask(__name__)
    backend.register(application)
    assert application.secret_key == "env-secret"
    assert application.config["SESSION_COOKIE_SECURE"] is False
    assert (tmp_path / "nested").is_dir()


def test_register_refuses_to_start_without_a_session_secret(monkeypatch):
    monkeypatch.delenv("TOOLHUB_SECRET_KEY", raising=False)
    monkeypatch.delenv("TOOLHUB_INSECURE_COOKIES", raising=False)
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    with pytest.raises(RuntimeError, match="TOOLHUB_SECRET_KEY is required"):
        backend.register(Flask(__name__))


def test_register_allows_an_ephemeral_secret_only_in_development(monkeypatch):
    monkeypatch.delenv("TOOLHUB_SECRET_KEY", raising=False)
    monkeypatch.setenv("TOOLHUB_INSECURE_COOKIES", "1")
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    application = Flask(__name__)
    backend.register(application)
    assert len(application.secret_key) == 64  # random hex fallback, dev only
    assert application.config["SESSION_COOKIE_SECURE"] is False


# ---- route guard inventory -------------------------------------------------

# Every /v1 route must carry @login_required or @write_guard, unless it is listed
# here with the reason it may be reached anonymously. The value is the reason, so
# adding a public endpoint is a deliberate edit somebody reviews rather than a
# decorator quietly left off — which is exactly how /v1/recent/owners/ shipped as
# an unauthenticated upstream amplifier.
PUBLIC_V1_ROUTES = {
    "/healthz": "liveness probe, no data",
    "/v1/config/": "public feature flags for the signed-out SPA",
    "/v1/digests/": "public immutable digest archive; local DB only",
    "/v1/digests/<cadence>/<edition_key>/": "public immutable digest edition; local DB only",
    "/v1/digests/subscriptions/confirm/": "signed single-subscription email confirmation capability",
    "/v1/digests/subscriptions/unsubscribe/": "signed single-subscription unsubscribe capability",
    "/v1/user/": "reports authenticated:false when signed out",
    "/v1/canonical/tools/": "public canonical Toolhub cache; local DB only and already-public catalog data",
    "/v1/catalog/": "public cache-only compatibility root; no request-time upstream access",
    "/v1/catalog/<path:path>": "public local replica reads with bounded pagination; no network I/O",
    "/v1/catalog/health/": "public replica generation and freshness metadata; local DB only",
    "/v1/catalog/tools/<name>/projection/": "public versioned projection assembled only from local public evidence",
    "/v1/catalog/tools/<name>/icon/": "public bounded icon bytes previously validated by a background job",
    "/v1/catalog/curations/<int:curation_id>/": "public approved correction evidence; pending rows remain hidden",
    "/v1/graph/": "public similarity graph derived from local canonical Toolhub cache; no upstream fetch",
    "/v1/home/": ("public landing page composed from the local catalog replica and local summaries"),
    "/v1/search/tools/": "public search over local records; local DB only",
    "/v1/statistics/": "public cached quality snapshot derived only from local public catalog evidence",
    "/v1/facets/tools/": "public faceted discovery by analyzer signals and declared metadata; rate limited",
    "/v1/facets/values/": "public facet value listing and adoption counts; rate limited",
    "/v1/userscripts/wikis/": "public list of wikis with a user-script directory; local DB only, rate limited",
    "/v1/userscripts/directory/": (
        "public directory of user scripts projected from already-public wiki pages; local DB only, rate limited"
    ),
    "/v1/userscripts/script/": "public per-script detail and the pages folded under it; local DB only, rate limited",
    "/v1/workers/": "public scheduled-job health; job names, schedules, and run outcomes carry no user data",
    "/v1/tools/<name>/signals/": "public per-tool signal summary; local DB only",
    "/v1/tools/summaries/": "public card summaries from local health and maintainer indexes; no upstream fetch",
    "/v1/accounts/": "public official Toolhub account projection; local DB only and reads are rate limited",
    "/v1/accounts/<toolhub_user_id>/": (
        "public official Toolhub account detail; local DB only and reads are rate limited"
    ),
    "/v1/community/": "public unified directory over local projections; reads are rate limited",
    "/v1/people/": "public local people search; reads are rate limited",
    "/v1/people/attributions/": "public unresolved-label discovery over local evidence; reads are rate limited",
    "/v1/people/resolve/": "public exact-handle resolution over local public identities; reads are rate limited",
    "/v1/people/<person_reference>/": "public local person profile; reads are rate limited",
    "/v1/people/tools/<name>/": (
        "public normalized people and typed tool relationships; evidence is redacted and reads are rate limited"
    ),
    "/v1/tools/<name>/media/": "GET is public; the POST half calls write_guard inside _tool_media_post",
    "/v1/recent/owners/": "public Recent enrichment; rate limited and local catalog only",
    "/feeds/recent.xml": "public RSS feed generated from the local recent-change replica",
    "/feeds/tools/recently-updated.xml": "public RSS feed generated from local catalog ordering",
    "/feeds/lists.xml": "public RSS feed generated from persisted list replica pages",
    "/feeds/tools/<path:name>/revisions.xml": "public RSS feed generated from persisted revision responses",
    "/feeds/lists/<list_id>/revisions.xml": "public RSS feed generated from persisted revision responses",
    "/feeds/digests/<cadence>.xml": "public RSS feed generated from immutable published digest editions",
    "/toolinfo.json": "public feed the official Toolhub crawler ingests",
}


def _v1_rules(app):
    # Every v1 blueprint, not just the original one. backend/v1.py was split by
    # resource family, so routes now live under endpoints like "v1_write." and
    # "v1_catalog." too. Matching only "v1." quietly dropped them from the guard
    # audit below — the check would still pass while covering a fraction of the
    # surface it claims to.
    return [rule for rule in app.url_map.iter_rules() if rule.endpoint.split(".", 1)[0].startswith("v1")]


def test_every_v1_route_is_guarded_or_allowlisted(app):
    unguarded = sorted(
        str(rule.rule)
        for rule in _v1_rules(app)
        if not hasattr(app.view_functions[rule.endpoint], security.GUARD_ATTR)
        and str(rule.rule) not in PUBLIC_V1_ROUTES
    )
    assert unguarded == [], (
        f"unguarded /v1 routes: {unguarded}. Add @login_required or @write_guard, "
        "or add the route to PUBLIC_V1_ROUTES with the reason it is safe anonymously."
    )


def test_public_route_allowlist_has_no_stale_entries(app):
    live = {str(rule.rule) for rule in _v1_rules(app)}
    assert sorted(set(PUBLIC_V1_ROUTES) - live) == [], "allowlist names routes that no longer exist"
    # A route that later gained a guard should leave the allowlist, or the list
    # stops describing the real surface.
    now_guarded = sorted(
        path
        for path in PUBLIC_V1_ROUTES
        for rule in _v1_rules(app)
        if str(rule.rule) == path and hasattr(app.view_functions[rule.endpoint], security.GUARD_ATTR)
    )
    assert now_guarded == [], f"these are guarded now and can leave PUBLIC_V1_ROUTES: {now_guarded}"


def test_catalog_projection_and_reviewed_curation_are_local_only(client):
    now = utcnow()
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="alpha",
                record={"name": "alpha", "title": "Alpha", "url": "https://official.example"},
                source_url="https://toolhub.wikimedia.org/api/tools/alpha/",
                fetched_at=now,
                expires_at=now,
                stale_until=now,
            )
        )
    catalog_projection.refresh_tool_names(["alpha"])

    projected = client.get("/v1/catalog/tools/alpha/projection/")
    assert projected.status_code == 200
    assert projected.get_json()["record"]["url"] == "https://official.example"
    assert projected.headers["ETag"]

    uid = add_user()
    sign_in(client, uid)
    response = client.post(
        "/v1/catalog/tools/alpha/curations/",
        json={"patch": {"url": "https://corrected.example"}, "rationale": "The official URL is obsolete."},
        headers={"X-CSRF-Token": "tok"},
    )
    assert response.status_code == 201
    curation_id = response.get_json()["item"]["id"]
    assert client.get(f"/v1/catalog/curations/{curation_id}/").status_code == 404

    reviewer_id = add_user("Reviewer", "2", role=authz.ROLE_REVIEWER)
    sign_in(client, reviewer_id)
    approved = client.put(
        f"/v1/moderation/public-data/catalog-curations/{curation_id}/",
        json={"reviewStatus": "approved"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert approved.status_code == 200
    assert client.get(f"/v1/catalog/curations/{curation_id}/").status_code == 200
    assert client.get("/v1/catalog/tools/alpha/projection/").get_json()["record"]["url"] == (
        "https://corrected.example"
    )
    with db.session_scope() as s:
        assert s.get(CatalogCuration, curation_id).reviewed_by_user_id == reviewer_id


# ---- public RSS feeds ------------------------------------------------------


def test_recent_rss_feed_uses_local_recent_replica(client, monkeypatch):
    monkeypatch.setenv("TOOLHUB_EVOLVED_BASE_URL", "https://evolved.example")

    def fake_collection(path, params):
        assert (path, params) == ("/api/recent/", {"page_size": v1_api.RSS_FEED_PAGE_SIZE})
        return {
            "results": [
                {
                    "id": 7,
                    "timestamp": "2026-07-30T12:00:00Z",
                    "content_type": "tool",
                    "content_id": "abc-tool",
                    "content_title": "A & B tool",
                    "parent_id": 5,
                    "user": {"username": "Ada"},
                    "comment": "Fixed <metadata>",
                }
            ]
        }

    monkeypatch.setattr(catalog_read, "collection_payload", fake_collection)
    resp = client.get("/feeds/recent.xml")

    assert resp.status_code == 200
    assert resp.content_type == "application/rss+xml; charset=utf-8"
    text = resp.get_data(as_text=True)
    assert "Toolhub recent changes" in text
    assert "A &amp; B tool" in text
    assert "Fixed &lt;metadata&gt;" in text
    assert "https://evolved.example/tools/abc-tool" in text
    root = ET.fromstring(text)
    assert root.tag == "rss"
    assert root.find("./channel/item/guid").text == "toolhub-recent:7"


def test_cached_feed_links_ignore_a_forged_host_header(client, monkeypatch):
    """A forged Host must not reach <link>/<guid> in a publicly cached feed.

    Feeds go out as `Cache-Control: public, max-age=300`, so a Host-derived base
    URL is cache poisoning: one request decides what every later reader sees for
    five minutes. Production reads TOOLHUB_EVOLVED_BASE_URL only — the same rule
    backend.oauth._callback_url already applies to the OAuth callback.
    """
    monkeypatch.delenv("TOOLHUB_EVOLVED_BASE_URL", raising=False)
    monkeypatch.delenv("TOOLHUB_INSECURE_COOKIES", raising=False)
    monkeypatch.setattr(
        catalog_read,
        "collection_payload",
        lambda *_a, **_k: {"results": [{"id": 1, "content_type": "tool", "content_id": "t"}]},
    )

    resp = client.get("/feeds/recent.xml", headers={"Host": "evil.example"})

    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "evil.example" not in text
    assert v1_api.DEFAULT_PUBLIC_BASE_URL in text


def test_catalog_rss_feeds_use_matching_local_replica_surfaces(client, monkeypatch):
    monkeypatch.setenv("TOOLHUB_EVOLVED_BASE_URL", "https://evolved.example")

    monkeypatch.setattr(
        catalog_read,
        "search_payload",
        lambda _params: {
            "results": [
                {
                    "name": "maps-tool",
                    "title": {"en": "Maps tool"},
                    "description": {"en": "Map helper"},
                    "modified_date": "2026-07-29T10:00:00Z",
                }
            ]
        },
    )
    monkeypatch.setattr(
        catalog_read,
        "collection_payload",
        lambda _path, _params: {"results": [{"id": 42, "title": "Starter list", "description": "For new editors"}]},
    )
    revision_payloads = deque(
        [
            {"results": [{"id": 9, "timestamp": "2026-07-28T10:00:00Z", "user": {"username": "Grace"}}]},
            {"results": [{"id": 8, "timestamp": "2026-07-27T10:00:00Z", "comment": "List update"}]},
        ]
    )
    monkeypatch.setattr(
        catalog_read,
        "cached_payload",
        lambda _url: (dumps(revision_payloads.popleft()).encode(), "application/json", 200),
    )

    assert "Maps tool" in client.get("/feeds/tools/recently-updated.xml").get_data(as_text=True)
    assert "Starter list" in client.get("/feeds/lists.xml").get_data(as_text=True)
    assert "Toolhub revisions: Foo/Bar" in client.get("/feeds/tools/Foo%2FBar/revisions.xml").get_data(as_text=True)
    assert "Toolhub list revisions: 42" in client.get("/feeds/lists/42/revisions.xml").get_data(as_text=True)


def test_rss_feed_remains_available_with_an_empty_local_replica(client, monkeypatch):
    monkeypatch.setattr(catalog_read, "collection_payload", lambda *_args, **_kwargs: {"results": []})
    resp = client.get("/feeds/recent.xml")

    assert resp.status_code == 200
    assert "<channel>" in resp.get_data(as_text=True)


# ---- db plumbing -----------------------------------------------------------


def test_db_requires_configure():
    saved_engine, saved_factory = db._engine, db._session_factory
    db._engine, db._session_factory = None, None
    try:
        with pytest.raises(RuntimeError):
            db.engine()
        with pytest.raises(RuntimeError), db.session_scope():
            pass
    finally:
        db._engine, db._session_factory = saved_engine, saved_factory


def test_db_reconfigure_disposes_and_file_url(tmp_path):
    db.configure("sqlite://")
    db.configure(f"sqlite:///{tmp_path}/file.sqlite3")  # non-memory branch + dispose branch
    db.init_schema()
    with db.session_scope() as s:
        s.add(User(wm_sub="x", username="y"))
    db.configure("sqlite://")
    db.init_schema()


def test_init_schema_creates_persistent_api_cache_table():
    db.configure("sqlite://")
    db.init_schema()
    cols = {col["name"] for col in inspect(db.engine()).get_columns(ApiCache.__tablename__)}
    assert {
        "url_hash",
        "url",
        "status",
        "content_type",
        "body",
        "fetched_at",
        "expires_at",
        "stale_until",
        "etag",
        "last_modified",
        "last_error",
    }.issubset(cols)
    meta_cols = {col["name"] for col in inspect(db.engine()).get_columns(ApiCacheMeta.__tablename__)}
    assert {"key", "value", "updated_at"}.issubset(meta_cols)


def test_init_schema_creates_tool_summary_cache_table():
    db.configure("sqlite://")
    db.init_schema()
    cols = {col["name"] for col in inspect(db.engine()).get_columns(ToolSummaryCache.__tablename__)}

    assert {
        "tool_name",
        "summary",
        "source",
        "sync_status",
        "computed_at",
        "expires_at",
        "stale_until",
        "last_error",
    }.issubset(cols)


def test_init_schema_creates_tool_author_claim_tables():
    db.configure("sqlite://")
    db.init_schema()
    cols = {col["name"] for col in inspect(db.engine()).get_columns(ToolAuthorClaim.__tablename__)}
    assert {
        "id",
        "tool_name",
        "author_name",
        "toolhub_username",
        "user_id",
        "verification_status",
        "verification_method",
        "requested_relationship",
        "evidence_url",
        "evidence_payload",
        "checked_at",
        "expires_at",
        "revoked_at",
        "last_error",
        "created_at",
        "updated_at",
    }.issubset(cols)
    challenge_cols = {col["name"] for col in inspect(db.engine()).get_columns(ToolinfoControlChallenge.__tablename__)}
    assert {
        "id",
        "user_id",
        "tool_name",
        "toolinfo_url",
        "challenge_token",
        "status",
        "expires_at",
        "verified_at",
        "last_checked_at",
        "last_error",
    }.issubset(challenge_cols)
    key_cols = {col["name"] for col in inspect(db.engine()).get_columns(ToolAuthorKey.__tablename__)}
    assert {
        "id",
        "toolhub_username",
        "user_id",
        "key_id",
        "public_key",
        "algorithm",
        "created_at",
        "revoked_at",
        "last_used_at",
    }.issubset(key_cols)

    with db.session_scope() as s:
        claim = ToolAuthorClaim(tool_name="toolforge-example", author_name="Display Name", toolhub_username="owner")
        key = ToolAuthorKey(toolhub_username="owner", key_id="k1", public_key="pk")
        s.add(claim)
        s.add(key)
        s.flush()
        assert claim.verification_status == sync.AUTHOR_CLAIM_UNVERIFIED
        assert claim.verification_method == sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME
        assert claim.checked_at is not None
        assert key.algorithm == "ed25519"

    with pytest.raises(IntegrityError):
        with db.session_scope() as s:
            s.add(
                ToolAuthorClaim(
                    tool_name="toolforge-example",
                    author_name="Display Name",
                    toolhub_username="owner",
                    verification_method=sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
                )
            )


def test_init_schema_creates_people_evidence_and_activity_tables():
    db.configure("sqlite://")
    db.init_schema()
    edge_cols = {col["name"] for col in inspect(db.engine()).get_columns(ToolRelationshipEvidence.__tablename__)}
    assert {
        "id",
        "tool_name",
        "person_id",
        "relationship_type",
        "source",
        "method",
        "verification_status",
        "confidence",
        "evidence_url",
        "evidence_payload",
        "evidence_key",
        "observed_name",
        "toolhub_canonical",
        "first_seen_at",
        "checked_at",
        "expires_at",
        "last_error",
    }.issubset(edge_cols)
    rollup_cols = {col["name"] for col in inspect(db.engine()).get_columns(PersonActivitySummary.__tablename__)}
    assert {
        "person_id",
        "related_tool_count",
        "verified_tool_count",
        "contribution_count",
        "recent_contribution_count",
        "last_contribution_at",
        "activity_status",
        "computed_at",
        "stale_at",
    }.issubset(rollup_cols)
    mapping_cols = {col["name"] for col in inspect(db.engine()).get_columns(PersonReconciliationMapping.__tablename__)}
    assert {
        "evidence",
        "decision",
        "reviewed_by_user_id",
        "reviewed_at",
        "review_notes",
        "updated_at",
    }.issubset(mapping_cols)
    conflict_cols = {
        col["name"] for col in inspect(db.engine()).get_columns(PersonReconciliationConflict.__tablename__)
    }
    assert {
        "status",
        "reviewed_by_user_id",
        "reviewed_at",
        "review_notes",
        "last_seen_at",
    }.issubset(conflict_cols)

    with db.session_scope() as s:
        person = Person(canonical_key="toolhub:ada", display_name="Ada")
        s.add(person)
        s.flush()
        edge = ToolRelationshipEvidence(
            tool_name="ada-tool",
            person_id=person.id,
            relationship_type=sync.PERSON_REL_AUTHOR,
            source="toolhub_author_metadata",
            method="toolhub_author_metadata",
        )
        rollup = PersonActivitySummary(person_id=person.id)
        s.add(edge)
        s.add(rollup)
        s.flush()
        assert edge.verification_status == sync.AUTHOR_CLAIM_UNVERIFIED
        assert edge.confidence == 0
        assert rollup.activity_status == "unknown"
        assert rollup.related_tool_count == 0


def test_people_graph_deduplicates_stable_identity_and_keeps_roles_separate():
    db.configure("sqlite://")
    db.init_schema()
    with db.session_scope() as s:
        from backend import people_index

        people_index.replace_source_evidence(
            s,
            "ada-tool",
            "toolhub_author_metadata",
            [
                {
                    "display_name": "Ada Lovelace",
                    "toolhub_username": "Ada",
                    "relationship_type": sync.PERSON_REL_AUTHOR,
                    "method": "toolhub_author_metadata",
                    "confidence": 45,
                    "toolhub_canonical": True,
                }
            ],
        )
        relationships = people_index.replace_source_evidence(
            s,
            "ada-tool",
            "evolved_author_claim",
            [
                {
                    "display_name": "Ada",
                    "toolhub_username": "Ada",
                    "relationship_type": sync.PERSON_REL_MAINTAINER,
                    "method": sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                    "verification_status": sync.AUTHOR_CLAIM_VERIFIED,
                    "confidence": 95,
                }
            ],
        )
        summary = people_index.public_people_summary(s, "ada-tool")

        assert len(relationships) == 1
        assert s.query(Person).count() == 1
        assert s.query(PersonIdentifier).count() == 1
        assert s.query(ToolPersonRelationship).count() == 2
        assert summary["counts"][sync.PERSON_REL_AUTHOR] == 1
        assert summary["counts"][sync.PERSON_REL_MAINTAINER] == 1
        assert summary["people"][0]["identityQuality"] == "handle"
        assert summary["people"][0]["identifiers"] == [
            {"namespace": "toolhub_username", "value": "Ada", "kind": "handle"}
        ]
        author = next(
            relationship
            for relationship in summary["people"][0]["relationships"]
            if relationship["type"] == sync.PERSON_REL_AUTHOR
        )
        assert author["evidence"][0]["identityBasis"] == "handle"
        assert author["evidence"][0]["relationshipBasis"] == "authorship_attribution"


def test_init_schema_creates_toolinfo_discovery_table():
    db.configure("sqlite://")
    db.init_schema()
    cols = {col["name"] for col in inspect(db.engine()).get_columns(ToolinfoDiscovery.__tablename__)}
    assert {
        "id",
        "tool_name",
        "tool_url",
        "status",
        "method",
        "toolinfo_url",
        "tool_names",
        "payload",
        "attempts",
        "checked_at",
        "expires_at",
        "last_error",
        "source",
        "sync_status",
    }.issubset(cols)
    meta_cols = {col["name"] for col in inspect(db.engine()).get_columns(ToolinfoDiscoveryMeta.__tablename__)}
    assert {"key", "value", "updated_at"}.issubset(meta_cols)
    source_cols = {col["name"] for col in inspect(db.engine()).get_columns(ToolinfoSource.__tablename__)}
    assert {
        "id",
        "official_id",
        "url",
        "source_kind",
        "created_by_username",
        "created_by_user_id",
        "created_date",
        "last_seen_at",
        "last_fetched_at",
        "status",
        "status_code",
        "valid",
        "item_count",
        "last_error",
        "last_run_id",
        "source",
        "sync_status",
    }.issubset(source_cols)
    item_cols = {col["name"] for col in inspect(db.engine()).get_columns(ToolinfoSourceItem.__tablename__)}
    assert {
        "id",
        "tool_name",
        "source_id",
        "source_url",
        "title",
        "tool_url",
        "payload",
        "last_seen_at",
        "last_error",
        "source",
        "sync_status",
    }.issubset(item_cols)


def test_init_schema_creates_source_analysis_report_table():
    db.configure("sqlite://")
    db.init_schema()
    cols = {col["name"] for col in inspect(db.engine()).get_columns(SourceAnalysisReport.__tablename__)}
    assert {
        "id",
        "user_id",
        "created_by_user_id",
        "tool_name",
        "source_label",
        "report",
        "review_status",
        "review_notes",
        "created_at",
        "reviewed_at",
        "source",
        "sync_status",
    }.issubset(cols)

    with db.session_scope() as s:
        user = User(wm_sub="source-user", username="SourceUser")
        s.add(user)
        s.flush()
        row = SourceAnalysisReport(user_id=user.id, created_by_user_id=user.id, report={"summary": {}})
        s.add(row)
        s.flush()
        assert row.review_status == sync.REVIEW_OPEN
        assert row.source == sync.SOURCE_LOCAL
        assert row.sync_status == sync.SYNC_EVOLVED_REAL


def test_api_cache_recent_poll_baselines_marker_without_invalidating(app, monkeypatch):
    clock = {"t": utcnow()}
    monkeypatch.setattr(api_cache, "utcnow", lambda: clock["t"])
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/tools/my-tool/",
        api_cache.CacheableResponse(200, "application/json", b'{"name":"my-tool"}'),
    )

    first = [{}, {"id": 1, "timestamp": "2026-07-27T10:00:00Z", "content_type": "tool", "content_id": "my-tool"}]
    assert api_cache.maybe_poll_recent_changes(lambda: first) == 0
    with db.session_scope() as s:
        assert s.query(ApiCache).count() == 1
        assert s.get(ApiCacheMeta, "recent_latest_marker") is not None

    second = [{"id": 2, "timestamp": "2026-07-27T11:00:00Z", "content_type": "tool", "content_id": "my-tool"}]
    assert api_cache.maybe_poll_recent_changes(lambda: second) == 0
    with db.session_scope() as s:
        assert s.query(ApiCache).count() == 1


def test_api_cache_recent_poll_invalidates_changed_tool_and_list_rows(app, monkeypatch):
    clock = {"t": utcnow()}
    monkeypatch.setattr(api_cache, "utcnow", lambda: clock["t"])
    baseline = [{"id": 10, "timestamp": "2026-07-27T09:00:00Z", "content_type": "tool", "content_id": "old"}]
    assert api_cache.maybe_poll_recent_changes(lambda: baseline) == 0

    cached_urls = [
        "https://toolhub.wikimedia.org/api/tools/my-tool/",
        "https://toolhub.wikimedia.org/api/tools/my-tool/revisions/?page_size=20",
        "https://toolhub.wikimedia.org/api/search/tools/?q=my-tool",
        "https://toolhub.wikimedia.org/api/ui/home/",
        "https://toolhub.wikimedia.org/api/recent/?page_size=100",
        "https://toolhub.wikimedia.org/api/lists/77/",
        "https://toolhub.wikimedia.org/api/lists/?page=1",
        "https://toolhub.wikimedia.org/api/tools/other-tool/",
    ]
    for url in cached_urls:
        api_cache.put_success(url, api_cache.CacheableResponse(200, "application/json", b"{}"))
    clock["t"] += timedelta(seconds=api_cache.RECENT_POLL_SECONDS + 1)

    rows = [
        {"id": 12, "timestamp": "2026-07-27T11:00:00Z", "content_type": "list", "content_id": 77},
        {"id": 11, "timestamp": "2026-07-27T10:00:00Z", "content_type": "tool", "content_id": "my-tool"},
        {"id": 10, "timestamp": "2026-07-27T09:00:00Z", "content_type": "tool", "content_id": "old"},
    ]
    assert api_cache.maybe_poll_recent_changes(lambda: rows) == 7
    with db.session_scope() as s:
        assert [row.url for row in s.query(ApiCache).all()] == ["https://toolhub.wikimedia.org/api/tools/other-tool/"]


def test_api_cache_recent_poll_processes_page_when_old_marker_is_not_seen(app, monkeypatch):
    clock = {"t": utcnow()}
    monkeypatch.setattr(api_cache, "utcnow", lambda: clock["t"])
    baseline = [{"id": 1, "timestamp": "2026-07-27T09:00:00Z", "content_type": "tool", "content_id": "old"}]
    assert api_cache.maybe_poll_recent_changes(lambda: baseline) == 0
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/search/tools/?q=my-tool",
        api_cache.CacheableResponse(200, "application/json", b"{}"),
    )
    clock["t"] += timedelta(seconds=api_cache.RECENT_POLL_SECONDS + 1)

    rows = [
        {"id": 3, "timestamp": "2026-07-27T11:00:00Z", "content_type": "tool", "content_id": "my-tool"},
        {"id": 2, "timestamp": "2026-07-27T10:00:00Z", "content_type": "tool"},
    ]
    assert api_cache.maybe_poll_recent_changes(lambda: rows) == 1
    with db.session_scope() as s:
        assert s.query(ApiCache).count() == 0


def test_api_cache_direct_invalidation_helpers_cover_noop_and_collection_paths(app):
    policy = api_cache.policy_for_url("https://toolhub.wikimedia.org/api/tools/my-tool/")
    assert policy.stale_until_seconds == policy.fresh_seconds + policy.stale_if_error_seconds
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/lists/?page=1",
        api_cache.CacheableResponse(200, "application/json", b"{}"),
    )
    api_cache.refresh("https://toolhub.wikimedia.org/api/missing/")
    assert api_cache.invalidate_tool("") == 0
    assert api_cache.invalidate_list("") == 0
    assert (
        api_cache.invalidate_recent_rows([{"content_type": "crawler_url", "content_id": "1"}, {"content_type": "tool"}])
        == 0
    )
    assert api_cache.invalidate_list_collection() == 1


def test_api_cache_invalidation_matches_sub_resources_and_encoded_names(app):
    """Invalidation matches on stored index columns, not a re-parse of every URL."""
    for url in (
        "https://toolhub.wikimedia.org/api/tools/my%20tool/",
        "https://toolhub.wikimedia.org/api/tools/my%20tool/revisions/?page_size=20",
        "https://toolhub.wikimedia.org/api/tools/other/",
    ):
        api_cache.put_success(url, api_cache.CacheableResponse(200, "application/json", b"{}"))
    # The detail read and its sub-resource go; an unrelated tool stays.
    assert api_cache.invalidate_tool("my tool") == 2
    with db.session_scope() as s:
        assert s.query(ApiCache).count() == 1


def test_api_cache_rows_without_an_invalidation_key_are_backfilled_not_dropped(app):
    """Pre-migration rows have no path, so nothing could evict them. Give them one.

    Deleting instead would empty the shared cache exactly when a deploy restarts
    every worker, sending the resulting cold traffic straight upstream.
    """
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/tools/legacy/",
        api_cache.CacheableResponse(200, "application/json", b'{"cached":true}'),
    )
    with db.session_scope() as s:
        s.query(ApiCache).update({ApiCache.path: "", ApiCache.collection: "", ApiCache.detail_key: ""})
    # A row with no index key is invisible to invalidation ...
    assert api_cache.invalidate_tool("legacy") == 0

    assert api_cache.backfill_index_columns() == 1
    assert api_cache.backfill_index_columns() == 0  # idempotent

    # ... and after the backfill it is both intact and evictable.
    with db.session_scope() as s:
        row = s.query(ApiCache).one()
        assert bytes(row.body) == b'{"cached":true}'
        assert (row.path, row.collection, row.detail_key) == ("/api/tools/legacy/", "tools", "legacy")
    assert api_cache.invalidate_tool("legacy") == 1


def test_api_cache_recent_poll_handles_invalid_marker_empty_rows_and_fetch_errors(app, monkeypatch):
    clock = {"t": utcnow()}
    monkeypatch.setattr(api_cache, "utcnow", lambda: clock["t"])
    with db.session_scope() as s:
        s.add(ApiCacheMeta(key="recent_last_polled_at", value="not-a-date"))

    assert api_cache.maybe_poll_recent_changes(lambda: [{}]) == 0
    clock["t"] += timedelta(seconds=api_cache.RECENT_POLL_SECONDS + 1)
    assert api_cache.maybe_poll_recent_changes(lambda: (_ for _ in ()).throw(RuntimeError("boom"))) == 0


def test_api_cache_database_failures_do_not_break_callers(app, monkeypatch):
    @contextmanager
    def broken_session_scope():
        raise SQLAlchemyError("db down")
        yield

    monkeypatch.setattr(api_cache.db, "session_scope", broken_session_scope)
    assert api_cache.get("https://toolhub.wikimedia.org/api/tools/my-tool/") is None
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/tools/my-tool/",
        api_cache.CacheableResponse(200, "application/json", b"{}"),
    )
    api_cache.refresh("https://toolhub.wikimedia.org/api/tools/my-tool/")
    api_cache.mark_failure("https://toolhub.wikimedia.org/api/tools/my-tool/", "timeout")
    assert api_cache.invalidate_list_collection() == 0
    assert api_cache.maybe_poll_recent_changes(lambda: []) == 0


def test_api_cache_needs_refresh_assumes_stale_when_the_database_is_down(app, monkeypatch):
    @contextmanager
    def broken_session_scope():
        raise SQLAlchemyError("db down")
        yield

    monkeypatch.setattr(api_cache.db, "session_scope", broken_session_scope)
    # Fail towards refetching rather than serving something we cannot verify.
    assert api_cache.needs_refresh("https://toolhub.wikimedia.org/api/tools/my-tool/") is True


def test_owner_label_extraction_handles_every_shape_toolhub_returns():
    assert recent_owners.owner_from_tool_record("not-a-dict") == ""
    assert recent_owners.owner_from_tool_record({"author": [{"bio": "no usable key"}, {"name": "Ada"}]}) == "Ada"
    assert recent_owners.owner_from_tool_record({"author": [{"developer_username": "dev"}]}) == "dev"
    assert recent_owners.owner_from_tool_record({"author": ["", "  ", "Grace"]}) == "Grace"
    assert (
        recent_owners.owner_from_tool_record({"author": [None, {"created": 1}], "created_by": {"username": "Bo"}})
        == "Bo"
    )
    assert recent_owners.owner_from_tool_record({"author": []}) == ""


def test_owner_cache_database_failures_do_not_break_the_recent_page(app, monkeypatch):
    @contextmanager
    def broken_session_scope():
        raise SQLAlchemyError("db down")
        yield

    monkeypatch.setattr(recent_owners.db, "session_scope", broken_session_scope)
    # Every path degrades to "no cache" rather than raising into the request.
    assert recent_owners._cached_owner("t") is None
    recent_owners._store_owner("t", "Ada")
    recent_owners._mark_failure("t", "boom")
    assert recent_owners.purge_expired() == 0
    assert recent_owners.resolve_owners(["t"])["owners"] == {"t": ""}


def test_fully_expired_owner_row_is_treated_as_a_miss(client):
    now = utcnow()
    with db.session_scope() as s:
        # Past both windows but not yet swept by purge_expired().
        s.add(
            ToolOwnerCache(
                tool_name="ancient",
                owner="Stale Ada",
                fetched_at=now - timedelta(days=30),
                expires_at=now - timedelta(days=29),
                stale_until=now - timedelta(days=1),
            )
        )
    assert recent_owners._cached_owner("ancient") is None  # too old to serve, even as stale


def test_mark_failure_ignores_a_tool_with_no_cached_row(client):
    recent_owners._mark_failure("never-cached", "boom")  # no row → nothing to annotate
    with db.session_scope() as s:
        assert s.get(ToolOwnerCache, "never-cached") is None


def test_api_cache_recent_poll_keeps_removed_count_when_marker_write_fails(app, monkeypatch):
    clock = {"t": utcnow()}
    monkeypatch.setattr(api_cache, "utcnow", lambda: clock["t"])
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/search/tools/?q=my-tool",
        api_cache.CacheableResponse(200, "application/json", b"{}"),
    )

    original_set_metadata = api_cache._set_metadata

    def flaky_set_metadata(*args):
        if args[1] == "recent_latest_marker":
            raise SQLAlchemyError("db down")
        return original_set_metadata(*args)

    monkeypatch.setattr(api_cache, "_set_metadata", flaky_set_metadata)
    rows = [{"id": 3, "timestamp": "2026-07-27T11:00:00Z", "content_type": "tool", "content_id": "my-tool"}]
    assert api_cache.maybe_poll_recent_changes(lambda: rows) == 0
    clock["t"] += timedelta(seconds=api_cache.RECENT_POLL_SECONDS + 1)
    with db.session_scope() as s:
        original_set_metadata(s, "recent_latest_marker", '{"id":"1","timestamp":"old"}', clock["t"])
    assert api_cache.maybe_poll_recent_changes(lambda: rows) == 1


def test_official_cache_invalidation_helper_handles_edge_paths(monkeypatch):
    calls = []
    monkeypatch.setattr(api_cache, "invalidate_tool", lambda name: calls.append(("tool", name)))
    monkeypatch.setattr(api_cache, "invalidate_list", lambda ident: calls.append(("list", ident)))
    monkeypatch.setattr(api_cache, "invalidate_list_collection", lambda: calls.append(("lists", "*")))

    assert string_payload_value("not-json", "name") is None
    assert string_payload_value({"id": None, "name": " from-request "}, "id", "name") == "from-request"
    assert string_payload_value({"id": "", "name": "from-empty-fallback"}, "id", "name") == "from-empty-fallback"
    invalidate_official_api_cache("/not-api", None, None)
    invalidate_official_api_cache("/api/tools/", {}, {})
    invalidate_official_api_cache("/api/tools/", {"name": "from-request"}, ["not-a-dict"])
    invalidate_official_api_cache("/api/lists/", {}, {})

    assert calls == [("tool", "from-request"), ("lists", "*")]


def test_session_scope_rolls_back_on_error(app):
    with pytest.raises(ValueError, match="boom"), db.session_scope() as s:
        s.add(User(wm_sub="r", username="r"))
        raise ValueError("boom")
    with db.session_scope() as s:
        assert s.query(User).count() == 0


def test_schema_upgrade_and_sync_cleaners_cover_legacy_metadata():
    db.configure("sqlite://")
    eng = db.engine()
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE favorites (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE lists (client_id VARCHAR(64) PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE tools (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE tool_overlays (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE crawler_urls (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE tool_thanks (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE tool_health_targets (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE tool_media (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE tool_catalog_sync_state (key VARCHAR(64) PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE person_tool_relationships (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql(
            "CREATE TABLE repository_analysis_state (tool_name VARCHAR(255) PRIMARY KEY, attempts INTEGER)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE person_reconciliation_queue (tool_name VARCHAR(255) PRIMARY KEY, attempts INTEGER)"
        )
        conn.exec_driver_sql("CREATE TABLE person_reconciliation_conflicts (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO repository_analysis_state (tool_name, attempts) VALUES ('legacy', NULL)")
        conn.exec_driver_sql("INSERT INTO person_reconciliation_queue (tool_name, attempts) VALUES ('legacy', NULL)")
    db._upgrade_schema()
    user_columns = {col["name"] for col in inspect(eng).get_columns("users")}
    assert "role" in user_columns
    favorite_columns = {col["name"] for col in inspect(eng).get_columns("favorites")}
    assert {"created_by_user_id", "source", "sync_status", "last_synced_at", "last_error"}.issubset(favorite_columns)
    tool_columns = {col["name"] for col in inspect(eng).get_columns("tools")}
    assert {"created_by_user_id", "review_status", "deleted_at"}.issubset(tool_columns)
    list_columns = {col["name"] for col in inspect(eng).get_columns("lists")}
    assert {"last_toolhub_response", "validation_errors"}.issubset(list_columns)
    overlay_columns = {col["name"] for col in inspect(eng).get_columns("tool_overlays")}
    assert {"last_toolhub_response", "validation_errors"}.issubset(overlay_columns)
    crawler_columns = {col["name"] for col in inspect(eng).get_columns("crawler_urls")}
    assert {"last_toolhub_response", "validation_errors"}.issubset(crawler_columns)
    media_columns = {col["name"] for col in inspect(eng).get_columns("tool_media")}
    assert {"created_by_user_id", "review_status", "sync_status", "deleted_at"}.issubset(media_columns)
    thanks_columns = {col["name"] for col in inspect(eng).get_columns("tool_thanks")}
    assert {"created_by_user_id", "review_status", "source", "sync_status"}.issubset(thanks_columns)
    health_columns = {col["name"] for col in inspect(eng).get_columns("tool_health_targets")}
    assert {"source", "sync_status", "review_status", "last_synced_at", "deleted_at"}.issubset(health_columns)
    catalog_columns = {col["name"] for col in inspect(eng).get_columns("tool_catalog_sync_state")}
    assert {
        "reconcile_next_page",
        "reconcile_cycles_completed",
        "reconcile_last_at",
        "recent_latest_marker",
        "recent_pending_tools",
        "recent_scan_page",
        "recent_scan_latest_marker",
        "recent_scan_boundary_marker",
        "recent_cursor_recovery_required",
        "recent_last_at",
        "detail_hydration_cursor",
        "detail_hydration_pending_tools",
        "status",
        "last_started_at",
        "last_success_at",
        "last_completed_at",
        "last_error",
        "source",
        "sync_status",
    }.issubset(catalog_columns)
    relationship_columns = {col["name"] for col in inspect(eng).get_columns("person_tool_relationships")}
    assert "verified_at" in relationship_columns
    conflict_columns = {col["name"] for col in inspect(eng).get_columns("person_reconciliation_conflicts")}
    assert {"status", "reviewed_by_user_id", "reviewed_at", "review_notes", "last_seen_at"}.issubset(conflict_columns)
    with eng.connect() as conn:
        assert conn.scalar(select(text("attempts")).select_from(text("repository_analysis_state"))) == 0
        assert conn.scalar(select(text("attempts")).select_from(text("person_reconciliation_queue"))) == 0

    with db.advisory_lock("test-lock") as acquired:
        assert acquired is True

    assert sync.clean_source("official") == "official"
    assert sync.clean_source("bogus") == "local"
    assert sync.clean_sync_status("sync_error") == "sync_error"
    assert sync.clean_sync_status("bogus") == "local_draft"
    assert sync.clean_review_status("approved") == "approved"
    assert sync.clean_review_status("bogus") == "pending"
    assert sync.clean_author_claim_status("verified") == "verified"
    assert sync.clean_author_claim_status("bogus") == "unverified"
    assert sync.clean_author_claim_method("toolforge_maintainer") == "toolforge_maintainer"
    assert sync.clean_author_claim_method("bogus") == "author_display_name"
    assert sync.clean_error(None) is None
    assert sync.clean_error("  upstream refused  ") == "upstream refused"
    assert sync.clean_error("   ") is None
    assert sync.clean_int(None) is None
    assert sync.clean_int("") is None
    assert sync.clean_int("42") == 42
    assert sync.clean_int(object()) is None
    assert sync.created_by_user_id(ToolList(created_by_user_id=7, user_id=8, client_id="l", title="L")) == 7
    assert sync.created_by_user_id(ToolList(user_id=8, client_id="legacy", title="L")) == 8
    assert sync.created_by_user_id(object()) is None

    db.configure("sqlite://")
    db.init_schema()


def test_advisory_lock_does_not_mask_success_when_mariadb_resets_release_connection(monkeypatch):
    from types import SimpleNamespace

    from sqlalchemy.exc import SQLAlchemyError

    class FakeConnection:
        def __init__(self):
            self.calls = 0
            self.invalidated = False
            self.closed = False

        def scalar(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return 1
            raise SQLAlchemyError("server reset idle advisory-lock connection")

        def invalidate(self):
            self.invalidated = True

        def close(self):
            self.closed = True

    connection = FakeConnection()
    fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="mysql"), connect=lambda: connection)
    monkeypatch.setattr(db, "engine", lambda: fake_engine)

    with db.advisory_lock("long-job") as acquired:
        assert acquired is True

    assert connection.invalidated is True
    assert connection.closed is True


# ---- Evolved-local authorization ------------------------------------------


def test_authz_role_cleaning_permissions_and_labels():
    assert authz.clean_role("reviewer") == authz.ROLE_REVIEWER
    assert authz.clean_role("bogus") == authz.ROLE_USER
    assert authz.role_label(authz.ROLE_ADMIN) == "Admin/operator"
    assert authz.role_label("bogus") == "Signed-in user"
    assert authz.ACTION_PUBLIC_REVIEW not in authz.role_permissions(authz.ROLE_USER)
    assert authz.ACTION_PUBLIC_REVIEW in authz.role_permissions(authz.ROLE_REVIEWER)
    assert authz.ACTION_OPERATOR in authz.role_permissions(authz.ROLE_ADMIN)


def test_authz_can_separates_owned_data_from_evolved_roles():
    owner = User(id=1, wm_sub="1", username="Owner", role=authz.ROLE_USER)
    admin = User(id=2, wm_sub="2", username="Admin", role=authz.ROLE_ADMIN)
    assert authz.can(None, authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=1)) is False
    assert authz.can(owner, "unknown.action") is False
    assert authz.can(owner, authz.ACTION_PRIVATE_READ) is False
    assert authz.can(owner, authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=1)) is True
    assert authz.can(admin, authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=1)) is False
    assert authz.can(admin, authz.ACTION_PUBLIC_REVIEW) is True
    assert authz.can(admin, authz.ACTION_TOOLHUB_WRITE) is True


def test_authz_accepts_orm_owner_columns():
    user = User(id=7, wm_sub="7", username="Reviewer", role=authz.ROLE_REVIEWER)
    assert authz.can(user, authz.ACTION_PRIVATE_WRITE, ToolList(user_id=7, client_id="l", title="L")) is True
    assert (
        authz.can(
            user,
            authz.ACTION_PRIVATE_DELETE,
            ToolHealthTarget(tool_name="t", target_url="https://t.example", created_by_user_id=7),
        )
        is True
    )
    assert authz.can(user, authz.ACTION_PRIVATE_WRITE, object()) is False


def test_authz_login_role_from_env(monkeypatch):
    monkeypatch.setenv(authz.ADMIN_USERS_ENV, "42, Ada")
    monkeypatch.setenv(authz.REVIEWER_USERS_ENV, "Grace")
    assert authz.configured_login_role("42", "Someone") == authz.ROLE_ADMIN
    assert authz.configured_login_role("9", "ada") == authz.ROLE_ADMIN
    assert authz.configured_login_role("10", "Grace") == authz.ROLE_REVIEWER
    assert authz.configured_login_role("11", "Linus") == authz.ROLE_USER
    assert authz.role_for_login("11", "Linus", authz.ROLE_REVIEWER) == authz.ROLE_REVIEWER
    assert authz.role_for_login("42", "Someone", authz.ROLE_USER) == authz.ROLE_ADMIN


def test_toolhub_author_names_ignore_unknown_author_shapes():
    assert _toolhub_author_names({"author": [None], "modified_by": {"username": "Ada"}}) == []


def test_author_name_provider_records_unverified_claims(client):
    user = User(id=7, wm_sub="7", username="Ada")
    with db.session_scope() as s:
        rows = AuthorNameProvider().record(
            s,
            user,
            tool_name="ada-tool",
            author_names=["Ada", "ada", ""],
            evidence_url="https://toolhub.example/search",
            evidence_payload={"searchTerms": ["Ada"]},
        )
        assert len(rows) == 1
        payload = author_claims.claim_payload(rows[0])
        assert payload["verificationStatus"] == sync.AUTHOR_CLAIM_UNVERIFIED
        assert payload["verificationMethod"] == sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME
        assert payload["isVerified"] is False
        forced = author_claims.record_author_claim(
            s,
            tool_name="ada-tool",
            author_name="Ada",
            toolhub_username="Ada",
            verification_status=sync.AUTHOR_CLAIM_VERIFIED,
            verification_method=sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
        )
        assert forced.verification_status == sync.AUTHOR_CLAIM_UNVERIFIED


def test_claim_payload_marks_expired_verified_claims_stale(client):
    with db.session_scope() as s:
        row = ToolAuthorClaim(
            tool_name="stale-tool",
            author_name="Ada",
            toolhub_username="Ada",
            verification_status=sync.AUTHOR_CLAIM_VERIFIED,
            verification_method=sync.AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
            expires_at=utcnow() - timedelta(seconds=1),
        )
        s.add(row)
        s.flush()
        payload = author_claims.claim_payload(row)
    assert payload["verificationStatus"] == sync.AUTHOR_CLAIM_STALE
    assert payload["isVerified"] is False


def test_toolinfo_control_challenge_requires_published_token_before_claiming(client, monkeypatch):
    uid = add_user(username="Ada")
    sign_in(client, uid)
    monkeypatch.setattr(v1_common_api, "fetch_matching_item", lambda _url, name: {"name": name})
    created = client.post(
        "/v1/toolinfo/ownership-challenges/",
        json={"toolName": "ada-tool", "toolinfoUrl": "https://example.org/toolinfo.json"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert created.status_code == 201
    challenge = created.get_json()["challenge"]
    assert challenge["field"] == "x_toolhub_evolved_verification.challenge"
    with db.session_scope() as s:
        assert s.query(ToolAuthorClaim).count() == 0
        assert s.query(ToolinfoControlChallenge).count() == 1

    missing = client.post(
        f"/v1/toolinfo/ownership-challenges/{challenge['id']}/verify/",
        headers={"X-CSRF-Token": "tok"},
    )
    assert missing.status_code == 400
    assert "challenge" in missing.get_json()["error"]

    monkeypatch.setattr(
        v1_common_api,
        "fetch_matching_item",
        lambda _url, name: {
            "name": name,
            "x_toolhub_evolved_verification": {"challenge": challenge["token"]},
        },
    )
    verified = client.post(
        f"/v1/toolinfo/ownership-challenges/{challenge['id']}/verify/",
        headers={"X-CSRF-Token": "tok"},
    )
    assert verified.status_code == 200
    assert verified.get_json()["claim"]["verificationMethod"] == sync.AUTHOR_CLAIM_TOOLINFO_URL_CONTROL
    assert verified.get_json()["claim"]["isVerified"] is True
    with db.session_scope() as s:
        claim = s.query(ToolAuthorClaim).one()
        assert claim.verification_method == sync.AUTHOR_CLAIM_TOOLINFO_URL_CONTROL
        assert claim.evidence_url == "https://example.org/toolinfo.json"


def test_toolforge_maintainer_provider_verifies_sul_bound_ldap_membership(client):
    uid = add_user(username="schiste", wikimedia_global_user_id="160")
    user = User(id=uid, wm_sub="42", username="schiste", wikimedia_global_user_id="160")
    add_toolforge_account()
    provider = ToolforgeMaintainerProvider(fetcher=lambda _name: pytest.fail("must not fetch HTML"))
    with db.session_scope() as s:
        rows = provider.verify(
            s,
            user,
            tool_name="toolhub-evolved",
            author_names=["Christophe"],
            toolhub_tool={"url": "https://toolhub-evolved.toolforge.org"},
        )
        assert len(rows) == 1
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_VERIFIED
        assert rows[0].verification_method == sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER
        repeated = provider.verify(
            s,
            user,
            tool_name="toolhub-evolved",
            author_names=["Christophe"],
            toolhub_tool={"url": "https://toolhub-evolved.toolforge.org"},
        )
        assert [row.id for row in repeated] == [rows[0].id]
    assert rows[0].evidence_payload["toolforgeDeveloperUsername"] == "Schiste"
    assert rows[0].evidence_payload["toolforgeShellUsername"] == "schiste"


def test_claim_method_overrides_a_malformed_stored_relationship(client):
    uid = add_user(username="Ada")
    with db.session_scope() as s:
        user = s.get(User, uid)
        claim = ToolAuthorClaim(
            tool_name="ada-tool",
            author_name="Ada",
            toolhub_username="Ada",
            user_id=uid,
            verification_method=sync.AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
            verification_status=sync.AUTHOR_CLAIM_VERIFIED,
            requested_relationship=sync.PERSON_REL_CATALOG_ACTOR,
        )
        s.add(claim)
        s.flush()

        assert author_claims.claim_payload(claim)["requestedRelationship"] == sync.PERSON_REL_RECORD_OWNER
        maintainer_index.sync_author_claim_edges(s, tool_names=["ada-tool"], user_ids=[uid])
        assert s.query(ToolPersonRelationship).one().relationship_type == sync.PERSON_REL_RECORD_OWNER

        author_claims.record_author_claim(
            s,
            tool_name="ada-tool",
            author_name="Ada",
            toolhub_username=user.username,
            user_id=user.id,
            verification_status=sync.AUTHOR_CLAIM_VERIFIED,
            verification_method=sync.AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
        )
        assert claim.requested_relationship == sync.PERSON_REL_RECORD_OWNER


def test_toolforge_maintainer_provider_retries_failed_claims(client):
    uid = add_user(username="schiste", wikimedia_global_user_id="160")
    user = User(id=uid, wm_sub="42", username="schiste", wikimedia_global_user_id="160")
    add_toolforge_account()
    with db.session_scope() as s:
        author_claims.record_author_claim(
            s,
            tool_name="toolhub-evolved",
            author_name="Christophe",
            toolhub_username="schiste",
            verification_status=sync.AUTHOR_CLAIM_FAILED,
            verification_method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
            expires_at=utcnow() + timedelta(days=1),
            last_error="user is not listed as a Toolforge maintainer",
        )
        rows = ToolforgeMaintainerProvider(fetcher=lambda _name: pytest.fail("must not fetch HTML")).verify(
            s,
            user,
            tool_name="toolhub-evolved",
            author_names=["Christophe"],
            toolhub_tool={"url": "https://toolhub-evolved.toolforge.org"},
        )
        assert len(rows) == 1
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_VERIFIED
        assert rows[0].last_error is None


def test_author_claim_provider_parsers_cover_malformed_public_shapes():
    assert author_claims.parse_toolsadmin_maintainers(TOOLSADMIN_MAINTAINERS_TABLE_HTML) == ["Schiste"]
    assert author_claims.parse_toolsadmin_maintainers(
        "<table><tr><td>Not a maintainer</td></tr></table>"
        "<table><caption>Other</caption><tbody><tr><td>Also not</td></tr></tbody></table>"
        "<table><caption>Maintainers</caption><tbody><tr><td>"
        '<a href="/profile/ada/">Ada Lovelace</a></td></tr></tbody></table>'
    ) == ["Ada Lovelace"]
    assert author_claims.parse_toolsadmin_maintainers('<a href="/profile/blank/"> </a>') == []
    assert author_claims.parse_toolsadmin_maintainers("<p>No maintainers here</p>") == []
    assert author_claims.parse_toolsadmin_maintainers(
        "Maintainers Maintainers Ada\nGrace Git repositories"
    ) == ["Ada", "Grace"]
    assert author_claims.author_names_from_toolinfo({"author": "Ada"}) == ["Ada"]
    assert author_claims.author_names_from_toolinfo({"author": "Magnus Manske, JoanJoc"}) == [
        "Magnus Manske",
        "JoanJoc",
    ]
    assert author_claims.author_names_from_toolinfo({"author": "Lovelace, Ada"}) == ["Lovelace, Ada"]
    assert author_claims.author_names_from_toolinfo({"author": [None]}) == []
    assert author_claims.toolforge_names_from_toolhub_tool(
        "plain",
        {"api_url": "https://toolsadmin.wikimedia.org/tools/id/from-api/toolinfo/1.2/toolinfo.json"},
    ) == ["from-api"]
    assert (
        author_claims.toolforge_names_from_toolhub_tool(
            "plain",
            {"api_url": "https://toolsadmin.wikimedia.org/tools/id"},
        )
        == []
    )
    assert author_claims.signature_meta({"x_toolhub_evolved_signature": {"key_id": "k1"}}) is None


def test_toolforge_maintainer_provider_records_failures(client):
    uid = add_user(username="Ada")
    user = User(id=uid, wm_sub="42", username="Ada")
    provider = ToolforgeMaintainerProvider(fetcher=lambda _name: pytest.fail("must not fetch HTML"))
    with db.session_scope() as s:
        rows = provider.verify(
            s,
            user,
            tool_name="toolforge-alpha",
            author_names=["Ada"],
            toolhub_tool={},
        )
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_FAILED
        assert "SUL-bound" in rows[0].last_error
    provider = ToolforgeMaintainerProvider(fetcher=lambda _name: pytest.fail("must not fetch HTML"))
    with db.session_scope() as s:
        rows = provider.verify(
            s,
            user,
            tool_name="toolforge-beta",
            author_names=["Ada"],
            toolhub_tool={},
        )
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_FAILED
        assert "SUL-bound" in rows[0].last_error


def test_toolforge_maintainer_provider_fails_closed_when_sul_has_no_membership(client):
    uid = add_user(username="Ada", wikimedia_global_user_id="160")
    user = User(id=uid, wm_sub="42", username="Ada", wikimedia_global_user_id="160")

    with db.session_scope() as session:
        rows = ToolforgeMaintainerProvider(fetcher=lambda _name: pytest.fail("must not fetch HTML")).verify(
            session,
            user,
            tool_name="toolforge-missing",
            author_names=["Ada"],
            toolhub_tool={},
        )

    assert rows[0].verification_status == sync.AUTHOR_CLAIM_FAILED
    assert "SUL-bound" in rows[0].last_error


def test_toolforge_maintainer_provider_matches_any_validated_project_alias(client):
    uid = add_user(username="Ada", wikimedia_global_user_id="160")
    user = User(id=uid, wm_sub="42", username="Ada", wikimedia_global_user_id="160")
    add_toolforge_account(developer_username="AdaDeveloper", shell_username="ada", tools=("beta",))
    provider = ToolforgeMaintainerProvider(fetcher=lambda _name: pytest.fail("must not fetch HTML"))
    with db.session_scope() as s:
        rows = provider.verify(
            s,
            user,
            tool_name="toolforge-alpha",
            author_names=["Ada"],
            toolhub_tool={"url": "https://beta.toolforge.org"},
        )
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_VERIFIED
        assert rows[0].evidence_payload["toolforgeToolName"] == "beta"


def test_toolforge_maintainer_provider_does_not_use_toolsadmin_fetch_errors(client):
    uid = add_user(username="Ada")
    user = User(id=uid, wm_sub="42", username="Ada")

    def fetcher(_name):
        raise toolhub.requests.ConnectionError("offline")

    with db.session_scope() as s:
        rows = ToolforgeMaintainerProvider(fetcher=fetcher).verify(
            s,
            user,
            tool_name="toolforge-alpha",
            author_names=[],
            toolhub_tool={},
        )
        assert rows[0].author_name == "Ada"
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_FAILED
        assert "SUL-bound" in rows[0].last_error


def test_toolforge_provider_skips_non_toolforge_candidates(client):
    uid = add_user(username="Ada")
    user = User(id=uid, wm_sub="42", username="Ada")
    with db.session_scope() as s:
        assert (
            ToolforgeMaintainerProvider(fetcher=lambda name: pytest.fail("should not fetch")).verify(
                s,
                user,
                tool_name="plain-tool",
                author_names=["Ada"],
                toolhub_tool={"url": "https://example.org"},
            )
            == []
        )


def test_toolhub_write_provider_records_tool_write_claims(client, monkeypatch):
    monkeypatch.setenv("TOOLHUB_API_BASE", "https://toolhub.example")
    uid = add_user(username="Ada")
    user = User(id=uid, wm_sub="42", username="Ada")
    provider = ToolhubWriteProvider()
    with db.session_scope() as s:
        assert (
            provider.record_success(
                s,
                user,
                method="POST",
                path="/api/lists/",
                request_payload={"title": "L"},
                response_payload={"id": 1},
            )
            == []
        )
        rows = provider.record_success(
            s,
            user,
            method="PUT",
            path="/api/tools/ada-tool/annotations/",
            request_payload={},
            response_payload={"name": "ada-tool", "author": [{"name": "Ada Lovelace"}]},
        )
        assert rows[0].author_name == "Ada Lovelace"
        assert rows[0].verification_method == sync.AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS
        assert rows[0].evidence_url == "https://toolhub.example/api/tools/ada-tool/"
        rows = provider.record_success(
            s,
            user,
            method="POST",
            path="/api/tools/",
            request_payload={"name": "created-tool"},
            response_payload={},
        )
        assert rows[0].author_name == "Ada"


def test_successful_toolhub_write_provider_errors_are_non_fatal(client, monkeypatch):
    class RaisingProvider:
        def record_success(self, *args, **kwargs):
            raise RuntimeError("claim storage down")

    monkeypatch.setattr(v1_common_api, "TOOLHUB_WRITE_PROVIDER", RaisingProvider())
    v1_common_api.record_successful_toolhub_write(  # noqa: SLF001 - tests private non-fatal side effect
        User(id=1, wm_sub="1", username="Ada"),
        "POST",
        "/api/tools/",
        {"name": "ada-tool"},
        {"name": "ada-tool"},
    )


def test_signed_toolinfo_provider_verifies_registered_key(client):
    uid = add_user(username="Ada")
    user = User(id=uid, wm_sub="42", username="Ada")
    sig = "c2ln"
    toolinfo = {
        "name": "signed-tool",
        "title": "Signed",
        "author": [{"name": "Ada Lovelace"}],
        "x_toolhub_evolved_signature": {"key_id": "k1", "signature": sig},
    }
    calls = []

    def verifier(public_key, signature, message):
        calls.append((public_key, signature, message))

    with db.session_scope() as s:
        s.add(ToolAuthorKey(toolhub_username="Ada", key_id="k1", public_key="pk"))
        rows = SignedToolinfoProvider(verifier).verify(
            s,
            user,
            toolinfo=toolinfo,
            evidence_url="https://example.org/toolinfo.json",
        )
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_VERIFIED
        assert rows[0].verification_method == sync.AUTHOR_CLAIM_SIGNED_TOOLINFO
        assert rows[0].evidence_payload["signaturePrefix"] == sig
        assert s.query(ToolAuthorKey).one().last_used_at is not None
    assert calls == [
        (
            "pk",
            b"sig",
            b'{"author":[{"name":"Ada Lovelace"}],"name":"signed-tool","title":"Signed"}',
        )
    ]


def test_signed_toolinfo_provider_records_failures(client):
    uid = add_user(username="Ada")
    user = User(id=uid, wm_sub="42", username="Ada")
    provider = SignedToolinfoProvider(lambda *_args: None)
    base = {"name": "signed-tool", "author": "Ada"}
    with db.session_scope() as s:
        assert provider.verify(s, user, toolinfo={"name": "unsigned"}) == []
        assert (
            provider.verify(s, user, toolinfo={"x_toolhub_evolved_signature": {"key_id": "k1", "signature": "xx"}})
            == []
        )
        rows = provider.verify(
            s,
            user,
            toolinfo={
                **base,
                "x-toolhub-evolved-signature": {"keyId": "missing", "signature": "c2ln"},
            },
        )
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_FAILED
        assert rows[0].last_error == "public key not found"
        rows = provider.verify(
            s,
            user,
            toolinfo={**base, "x_toolhub_evolved_signature": {"key_id": "k1", "algorithm": "rsa", "signature": "c2ln"}},
        )
        assert rows[0].last_error == "unsupported signature algorithm"
        s.add(ToolAuthorKey(toolhub_username="Ada", key_id="k1", public_key="pk"))
        rows = provider.verify(
            s,
            user,
            toolinfo={**base, "x_toolhub_evolved_signature": {"key_id": "k1", "signature": "***"}},
        )
        assert rows[0].verification_status == sync.AUTHOR_CLAIM_FAILED
        assert "Only base64 data" in rows[0].last_error


def test_signed_toolinfo_provider_records_verifier_failure(client):
    uid = add_user(username="Ada")
    user = User(id=uid, wm_sub="42", username="Ada")

    def verifier(*_args):
        raise ValueError("bad signature")

    with db.session_scope() as s:
        s.add(ToolAuthorKey(toolhub_username="Ada", key_id="k1", public_key="pk"))
        rows = SignedToolinfoProvider(verifier).verify(
            s,
            user,
            toolinfo={
                "name": "signed-tool",
                "author": [],
                "x_toolhub_evolved_signature": {"key_id": "k1", "signature": "c2ln"},
            },
        )
        assert rows[0].author_name == "Ada"
        assert rows[0].last_error == "bad signature"


def test_ed25519_public_key_validation_without_crypto_dependency(monkeypatch):
    monkeypatch.setattr(author_claims, "Ed25519PublicKey", None)
    monkeypatch.setattr(author_claims, "load_pem_public_key", None)
    valid_raw = b64encode(b"1" * 32).decode("ascii")
    assert author_claims.validate_ed25519_public_key(valid_raw) == valid_raw
    valid_pem = "-----BEGIN PUBLIC KEY-----\nplaceholder\n-----END PUBLIC KEY-----"
    assert author_claims.validate_ed25519_public_key(valid_pem) == valid_pem
    with pytest.raises(ValueError, match="required"):
        author_claims.validate_ed25519_public_key("")
    with pytest.raises(ValueError, match="not a private key"):
        author_claims.validate_ed25519_public_key("-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----")
    with pytest.raises(ValueError, match="PUBLIC KEY"):
        author_claims.validate_ed25519_public_key("-----BEGIN CERTIFICATE-----\nnope\n-----END CERTIFICATE-----")
    with pytest.raises(ValueError, match="PEM or base64"):
        author_claims.validate_ed25519_public_key("***")
    with pytest.raises(ValueError, match="32 bytes"):
        author_claims.validate_ed25519_public_key(b64encode(b"short").decode("ascii"))


# ---- security guards -------------------------------------------------------


def test_v1_user_reports_anonymous_session(client):
    resp = client.get("/v1/user/")
    assert resp.status_code == 200
    assert resp.get_json() == {"authenticated": False}


def test_v1_user_stale_uid_clears_session(client):
    sign_in(client, 999)
    resp = client.get("/v1/user/")
    assert resp.status_code == 200
    assert resp.get_json() == {"authenticated": False}


def test_v1_user_ok(client):
    uid = add_user()
    sign_in(client, uid)
    data = client.get("/v1/user/").get_json()
    assert data["authenticated"] is True
    assert data["username"] == "Ada"
    assert data["csrf"] == "tok"
    assert data["evolvedRole"] == "user"
    assert data["evolvedRoleLabel"] == "Signed-in user"
    assert authz.ACTION_PRIVATE_WRITE in data["evolvedPermissions"]


def test_author_keys_require_login_and_csrf(client):
    assert client.get("/v1/author-keys/").status_code == 401
    uid = add_user()
    sign_in(client, uid)
    assert client.post("/v1/author-keys/", json={"keyId": "k1", "publicKey": "pk"}).status_code == 403
    assert client.delete("/v1/author-keys/k1/").status_code == 403


def test_author_key_lifecycle(client):
    uid = add_user()
    sign_in(client, uid)
    public_key = b64encode(b"1" * 32).decode("ascii")
    resp = client.post(
        "/v1/author-keys/",
        json={"keyId": "release-2026", "publicKey": public_key},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["key"]["keyId"] == "release-2026"
    assert data["key"]["algorithm"] == "ed25519"
    assert data["key"]["fingerprint"].startswith("SHA256:")
    assert data["key"]["revokedAt"] == ""

    listed = client.get("/v1/author-keys/").get_json()
    assert listed["username"] == "Ada"
    assert listed["keys"][0]["keyId"] == "release-2026"

    duplicate = client.post(
        "/v1/author-keys/",
        json={"keyId": "release-2026", "publicKey": public_key},
        headers={"X-CSRF-Token": "tok"},
    )
    assert duplicate.status_code == 409

    revoked = client.delete("/v1/author-keys/release-2026/", headers={"X-CSRF-Token": "tok"}).get_json()
    assert revoked["key"]["revokedAt"].endswith("Z")


def test_account_owned_claims_and_keys_survive_username_change(client):
    uid = add_user(username="Ada", wm_sub="42")
    sign_in(client, uid)
    public_key = b64encode(b"1" * 32).decode("ascii")
    assert (
        client.post(
            "/v1/author-keys/",
            json={"keyId": "stable-owner", "publicKey": public_key},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 201
    )
    with db.session_scope() as s:
        s.add(
            ToolAuthorClaim(
                tool_name="ada-tool",
                author_name="Ada Lovelace",
                toolhub_username="Ada",
                user_id=uid,
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                verification_method=sync.AUTHOR_CLAIM_SIGNED_TOOLINFO,
            )
        )
        s.get(User, uid).username = "Countess"

    listed = client.get("/v1/author-keys/").get_json()
    assert listed["username"] == "Countess"
    assert [key["keyId"] for key in listed["keys"]] == ["stable-owner"]
    exported = client.get("/v1/user/export/").get_json()
    assert [claim["toolName"] for claim in exported["authorClaims"]] == ["ada-tool"]

    with db.session_scope() as s:
        key = s.query(ToolAuthorKey).one()
        assert key.user_id == uid
        assert key.toolhub_username == "Ada"  # display snapshot; never used as ownership


def test_author_key_registration_validates_input(client):
    uid = add_user()
    sign_in(client, uid)
    assert client.post("/v1/author-keys/", data="not json", headers={"X-CSRF-Token": "tok"}).status_code == 400
    assert (
        client.post(
            "/v1/author-keys/",
            json={"keyId": "bad key", "publicKey": b64encode(b"1" * 32).decode("ascii")},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/author-keys/",
            json={"keyId": "k1", "algorithm": "rsa", "publicKey": b64encode(b"1" * 32).decode("ascii")},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    resp = client.post(
        "/v1/author-keys/",
        json={"keyId": "k1", "publicKey": "-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 400
    assert "public key" in resp.get_json()["error"]


def test_author_key_revoke_reports_bad_or_missing_keys(client):
    uid = add_user()
    sign_in(client, uid)
    assert client.delete("/v1/author-keys/bad%20key/", headers={"X-CSRF-Token": "tok"}).status_code == 400
    assert client.delete("/v1/author-keys/missing/", headers={"X-CSRF-Token": "tok"}).status_code == 404
    with db.session_scope() as s:
        s.add(
            ToolAuthorKey(
                toolhub_username="Ada",
                key_id="revoked",
                public_key=b64encode(b"1" * 32).decode("ascii"),
                revoked_at=utcnow(),
            )
        )
    resp = client.delete("/v1/author-keys/revoked/", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 200
    assert resp.get_json()["key"]["revokedAt"].endswith("Z")


def test_toolinfo_signing_payload_uses_registered_active_key(client):
    uid = add_user()
    sign_in(client, uid)
    with db.session_scope() as s:
        s.add(ToolAuthorKey(toolhub_username="Ada", key_id="k1", public_key=b64encode(b"1" * 32).decode("ascii")))
    toolinfo = {
        "title": "Signed",
        "name": "signed-tool",
        "author": [{"name": "Ada"}],
        "x_toolhub_evolved_signature": {"key_id": "old", "signature": "old"},
    }
    resp = client.post(
        "/v1/toolinfo/signing-payload/",
        json={"keyId": "k1", "toolinfo": toolinfo},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["toolName"] == "signed-tool"
    assert data["signatureField"] == "x_toolhub_evolved_signature"
    assert data["signatureMetadata"] == {
        "algorithm": "ed25519",
        "key_id": "k1",
        "signature": "<base64 signature>",
    }
    assert data["canonicalPayload"] == '{"author":[{"name":"Ada"}],"name":"signed-tool","title":"Signed"}'
    assert data["canonicalPayloadBase64"] == b64encode(data["canonicalPayload"].encode()).decode("ascii")
    assert data["signedToolinfoPreview"]["x_toolhub_evolved_signature"] == data["signatureMetadata"]


def test_toolinfo_signing_payload_rejects_missing_or_revoked_key(client):
    uid = add_user()
    sign_in(client, uid)
    assert (
        client.post("/v1/toolinfo/signing-payload/", data="not json", headers={"X-CSRF-Token": "tok"}).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/toolinfo/signing-payload/",
            json={"keyId": "bad key", "toolinfo": {"name": "signed-tool"}},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/toolinfo/signing-payload/",
            json={"keyId": "missing", "toolinfo": "["},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/toolinfo/signing-payload/",
            json={"keyId": "missing", "toolinfo": []},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/toolinfo/signing-payload/",
            json={"keyId": "missing", "toolinfo": {"name": "signed-tool"}},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 404
    )
    with db.session_scope() as s:
        s.add(
            ToolAuthorKey(
                toolhub_username="Ada",
                key_id="revoked",
                public_key=b64encode(b"1" * 32).decode("ascii"),
                revoked_at=utcnow(),
            )
        )
    assert (
        client.post(
            "/v1/toolinfo/signing-payload/",
            json={"keyId": "revoked", "toolinfo": {"name": "signed-tool"}},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/toolinfo/signing-payload/",
            json={"keyId": "revoked", "toolinfo": {"title": "missing name"}},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )


def test_source_analysis_requires_login_and_csrf(client):
    assert client.get("/v1/source-analysis/").status_code == 401
    assert client.get("/v1/source-analysis/1/").status_code == 401
    uid = add_user()
    sign_in(client, uid)
    assert client.post("/v1/source-analysis/", json={"files": []}).status_code == 403
    assert client.post("/v1/source-analysis/1/review/", json={"reviewStatus": "approved"}).status_code == 403


def test_source_analysis_lifecycle_stores_redacted_reports(client):
    uid = add_user()
    sign_in(client, uid)
    invalid_body = client.post("/v1/source-analysis/", data="not json", headers={"X-CSRF-Token": "tok"})
    assert invalid_body.status_code == 400
    invalid_files = client.post(
        "/v1/source-analysis/",
        json={"files": [{"path": "image.png", "content": "ignored"}]},
        headers={"X-CSRF-Token": "tok"},
    )
    assert invalid_files.status_code == 400
    invalid_context = client.post(
        "/v1/source-analysis/",
        json={"files": [{"path": "src/app.js", "content": "const api = new mw.Api();"}], "repositoryContext": []},
        headers={"X-CSRF-Token": "tok"},
    )
    assert invalid_context.status_code == 400

    resp = client.post(
        "/v1/source-analysis/",
        json={
            "toolName": "sample-tool",
            "sourceLabel": "local checkout",
            "repositoryContext": {
                "repository": {"url": "https://github.com/example/tool", "branch": "main"},
                "declared": {"oauthScopes": ["editpage"]},
            },
            "files": [
                {
                    "path": "src/app.js",
                    "content": "\n".join(
                        [
                            "const api = new mw.Api();",
                            "api.postWithToken('csrf', { action: 'edit', title: 'Sandbox' });",
                            "const client_secret = 'secret-value-123';",
                        ]
                    ),
                }
            ],
        },
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 201
    data = resp.get_json()["sourceAnalysis"]
    report_id = data["id"]
    assert data["toolName"] == "sample-tool"
    assert data["sourceLabel"] == "local checkout"
    assert data["reviewStatus"] == sync.REVIEW_OPEN
    assert data["syncStatus"] == sync.SYNC_EVOLVED_REAL
    assert data["report"]["summary"]["filesAnalyzed"] == 1
    assert data["report"]["repositoryContext"]["repository"]["url"] == "https://github.com/example/tool"
    assert data["report"]["summary"]["assessmentCount"] >= 6
    assert "secret-value-123" not in dumps(data)
    assert "credential-like-source" in {item["value"] for item in data["report"]["warnings"]}

    listed = client.get("/v1/source-analysis/?tool=sample-tool&limit=2").get_json()
    assert listed["count"] == 1
    assert listed["results"][0]["id"] == report_id
    detail = client.get(f"/v1/source-analysis/{report_id}/").get_json()
    assert detail["sourceAnalysis"]["id"] == report_id

    invalid_review_body = client.post(
        f"/v1/source-analysis/{report_id}/review/",
        data="not json",
        headers={"X-CSRF-Token": "tok"},
    )
    assert invalid_review_body.status_code == 400
    invalid_review = client.post(
        f"/v1/source-analysis/{report_id}/review/",
        json={"reviewStatus": "accepted"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert invalid_review.status_code == 400
    reviewed = client.post(
        f"/v1/source-analysis/{report_id}/review/",
        json={"reviewStatus": sync.REVIEW_APPROVED, "reviewNotes": "Matches the code."},
        headers={"X-CSRF-Token": "tok"},
    ).get_json()["sourceAnalysis"]
    assert reviewed["reviewStatus"] == sync.REVIEW_APPROVED
    assert reviewed["reviewNotes"] == "Matches the code."
    assert reviewed["reviewedAt"].endswith("Z")

    reopened = client.post(
        f"/v1/source-analysis/{report_id}/review/",
        json={"reviewStatus": sync.REVIEW_OPEN},
        headers={"X-CSRF-Token": "tok"},
    ).get_json()["sourceAnalysis"]
    assert reopened["reviewedAt"] == ""


def test_source_analysis_reports_are_private_exportable_and_deletable(client):
    first_uid = add_user(username="Ada", wm_sub="1")
    second_uid = add_user(username="Grace", wm_sub="2")
    with db.session_scope() as s:
        s.add(
            SourceAnalysisReport(
                user_id=first_uid,
                created_by_user_id=first_uid,
                tool_name="ada-tool",
                source_label="repo",
                report={"summary": {"filesAnalyzed": 1}},
            )
        )
        s.add(
            SourceAnalysisReport(
                user_id=second_uid,
                created_by_user_id=second_uid,
                tool_name="grace-tool",
                report={"summary": {"filesAnalyzed": 1}},
            )
        )
    sign_in(client, first_uid)
    private_list = client.get("/v1/source-analysis/").get_json()
    assert private_list["count"] == 1
    report_id = private_list["results"][0]["id"]
    assert client.get("/v1/source-analysis/999/").status_code == 404
    assert (
        client.post(
            "/v1/source-analysis/999/review/", json={"reviewStatus": "approved"}, headers={"X-CSRF-Token": "tok"}
        ).status_code
        == 404
    )

    exported = client.get("/v1/user/export/").get_json()
    assert exported["sourceAnalysisReports"][0]["id"] == report_id
    deleted = client.delete("/v1/user/evolved-data/", headers={"X-CSRF-Token": "tok"}).get_json()
    assert deleted["deleted"]["sourceAnalysisReports"] == 1
    assert client.get("/v1/source-analysis/").get_json()["count"] == 0

    sign_in(client, second_uid)
    assert client.get("/v1/source-analysis/").get_json()["count"] == 1


def test_maintainer_index_builds_public_safe_summary_from_claims():
    db.configure("sqlite://")
    db.init_schema()
    with db.session_scope() as s:
        user = User(wm_sub="maintainer-1", username="Ada", registered_at=utcnow() - timedelta(days=12))
        s.add(user)
        s.add(
            ToolAuthorClaim(
                tool_name="ada-tool",
                author_name="Ada Lovelace",
                toolhub_username="Ada",
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                verification_method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                evidence_url="https://toolsadmin.wikimedia.org/tools/id/ada-tool",
                evidence_payload={
                    "discoveryMethod": "toolforge_ldap_membership",
                    "toolforgeUidNumber": "1001",
                    "toolforgeToolName": "ada-tool",
                },
            )
        )
        s.flush()

        edges = maintainer_index.sync_author_claim_edges(s, usernames=["Ada"])
        summary = maintainer_index.public_tool_summary(s, "ada-tool")

        assert len(edges) == 1
        assert summary["status"] == "verified"
        assert summary["counts"][sync.PERSON_REL_MAINTAINER] == 1
        assert summary["healthCounts"]["verifiedPeople"] == 1
        assert summary["healthCounts"]["activePeople"] == 0
        assert summary["bestConfidence"] == 95
        assert summary["people"][0]["activity"]["status"] == "unknown"
        assert "private evidence" not in dumps(summary)


def test_maintainer_index_uses_strongest_claim_for_duplicate_public_edge():
    db.configure("sqlite://")
    db.init_schema()
    now = utcnow()
    with db.session_scope() as s:
        s.add(User(wm_sub="maintainer-duplicate", username="Schiste", registered_at=now - timedelta(days=3)))
        s.add_all(
            [
                ToolAuthorClaim(
                    tool_name="toolforge-toolhub-evolved",
                    author_name="Christophe",
                    toolhub_username="schiste",
                    verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                    verification_method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                    checked_at=now - timedelta(days=30),
                    expires_at=now - timedelta(days=1),
                    evidence_payload={
                        "discoveryMethod": "toolforge_ldap_membership",
                        "toolforgeUidNumber": "1001",
                        "toolforgeToolName": "toolhub-evolved",
                    },
                ),
                ToolAuthorClaim(
                    tool_name="toolforge-toolhub-evolved",
                    author_name="Schiste",
                    toolhub_username="Schiste",
                    verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                    verification_method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                    checked_at=now,
                    expires_at=now + timedelta(days=1),
                    evidence_payload={
                        "discoveryMethod": "toolforge_ldap_membership",
                        "toolforgeUidNumber": "1001",
                        "toolforgeToolName": "toolhub-evolved",
                    },
                ),
            ]
        )
        s.flush()

        edges = maintainer_index.sync_author_claim_edges(s, tool_names=["toolforge-toolhub-evolved"])
        summary = maintainer_index.public_tool_summary(s, "toolforge-toolhub-evolved")

        assert len(edges) == 1
        assert summary["status"] == "verified"
        assert summary["healthCounts"]["verifiedPeople"] == 1
        assert summary["bestConfidence"] == 95
        assert summary["people"][0]["displayName"] == "Schiste"
        assert summary["people"][0]["relationships"][0]["status"] == sync.AUTHOR_CLAIM_VERIFIED


def test_canonical_tools_endpoint_reads_local_cache_only(client):
    now = utcnow()
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="cached-tool",
                record={"name": "cached-tool", "title": "Cached Tool", "description": "Stored canonical data"},
                source_url="https://toolhub.wikimedia.org/api/tools/cached-tool/",
                fetched_at=now,
                expires_at=now + timedelta(minutes=15),
                stale_until=now + timedelta(days=1),
            )
        )

    by_name = client.get("/v1/canonical/tools/?name=cached-tool").get_json()
    search = client.get("/v1/canonical/tools/?q=stored").get_json()

    assert by_name["count"] == 1
    assert by_name["results"][0]["record"]["title"] == "Cached Tool"
    assert by_name["cachePolicy"]["upstream"] is False
    assert search["count"] == 1
    assert search["results"][0]["toolName"] == "cached-tool"


def test_canonical_search_filters_in_sql_and_escapes_like_wildcards(app):
    canonical_tools.upsert_records(
        [
            {"name": "percent-tool", "title": "100% coverage", "description": "about percentages"},
            {"name": "plain-tool", "title": "Plain", "description": "nothing special"},
        ],
        source_url="https://toolhub.wikimedia.org/api/search/tools/",
    )

    # "%" is a literal here, not the LIKE wildcard that would match everything.
    matched = canonical_tools.search("100%")
    assert [row["toolName"] for row in matched] == ["percent-tool"]
    assert [row["toolName"] for row in canonical_tools.search("_lain")] == []
    assert {row["toolName"] for row in canonical_tools.search("tool")} == {"percent-tool", "plain-tool"}
    # The limit is applied by the database, not after loading the table.
    assert len(canonical_tools.search("", limit=1)) == 1


def test_canonical_search_text_backfills_for_rows_cached_before_the_column(app):
    canonical_tools.upsert_records(
        [{"name": "legacy-tool", "title": "Legacy", "description": "cached earlier"}],
        source_url="https://toolhub.wikimedia.org/api/search/tools/",
    )
    with db.session_scope() as s:
        s.query(CanonicalToolCache).update({CanonicalToolCache.search_text: ""})
    assert canonical_tools.search("cached earlier") == []

    assert canonical_tools.backfill_search_text() == 1
    assert [row["toolName"] for row in canonical_tools.search("cached earlier")] == ["legacy-tool"]


def test_sparse_listing_upsert_preserves_rich_detail_metadata(client):
    canonical_tools.upsert_records(
        [
            {
                "name": "rich-tool",
                "title": "Original title",
                "keywords": ["images"],
                "tasks": ["Upload files"],
                "for_wikis": ["commons.wikimedia.org"],
            }
        ],
        source_url="https://toolhub.wikimedia.org/api/tools/rich-tool/",
        detail=True,
    )

    canonical_tools.upsert_records(
        [{"name": "rich-tool", "title": "Updated title", "tasks": []}],
        source_url="https://toolhub.wikimedia.org/api/tools/?page=1",
        detail=False,
    )

    cached = canonical_tools.tools_by_name(["rich-tool"])["rich-tool"]
    assert cached["record"]["title"] == "Updated title"
    assert cached["record"]["tasks"] == ["Upload files"]
    assert cached["record"]["for_wikis"] == ["commons.wikimedia.org"]
    assert cached["sourceUrl"].endswith("/api/tools/rich-tool/")


def _stub_summary_executor(monkeypatch):
    """Keep summary materialization off background threads inside a test.

    Reads only ever queue a build now, so a live executor would race the
    explicit refresh() these tests use to materialize deterministically.
    """

    class NoopExecutor:
        def submit(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(tool_summaries, "_EXECUTOR", NoopExecutor())
    tool_summaries._REFRESHING.clear()


def test_tool_summaries_endpoint_returns_local_health_and_maintainer_status(client, monkeypatch):
    db.configure("sqlite://")
    db.init_schema()
    _stub_summary_executor(monkeypatch)
    now = utcnow()
    with db.session_scope() as s:
        user = User(wm_sub="maintainer-summary", username="Ada", registered_at=now - timedelta(days=2))
        s.add(user)
        s.flush()
        s.add(
            ToolAuthorClaim(
                tool_name="ada-tool",
                author_name="Ada Lovelace",
                toolhub_username="Ada",
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                verification_method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
                checked_at=now,
                expires_at=now + timedelta(days=1),
                evidence_payload={
                    "discoveryMethod": "toolforge_ldap_membership",
                    "toolforgeUidNumber": "1001",
                    "toolforgeToolName": "ada-tool",
                },
            )
        )
        s.add(
            SourceAnalysisReport(
                user_id=user.id,
                created_by_user_id=user.id,
                tool_name="ada-tool",
                review_status=sync.REVIEW_APPROVED,
                reviewed_at=now,
                report={
                    "healthCore": {
                        "score": 80,
                        "grade": "good",
                        "confidence": 0.75,
                        "sourceMaintenanceStatus": "quiet",
                        "maintainerActivityStatus": "active",
                        "stewardshipStatus": "source-stale-maintainer-active",
                        "dimensions": [{"key": "tool-health", "score": 80}],
                    },
                    "repositoryContext": {
                        "repository": {
                            "url": "https://github.com/example/ada-tool",
                            "branch": "main",
                            "commitSha": "0123456789abcdef",
                            "lastCommitAt": "2026-07-29T12:00:00Z",
                            "commitCount": 42,
                        }
                    },
                },
            )
        )
        s.add(
            ToolHealthTarget(
                tool_name="ada-tool",
                target_url="https://ada.example/healthz",
                created_by_user_id=user.id,
                review_status=sync.REVIEW_APPROVED,
                enabled=True,
                last_status="healthy",
                last_checked_at=now,
            )
        )

    # The read never builds; it reports the name as pending and queues it.
    pending = client.get("/v1/tools/summaries/?name=ada-tool").get_json()
    assert pending["results"] == {}
    assert pending["cacheMeta"]["ada-tool"]["status"] == "pending"

    tool_summaries.refresh(["ada-tool"], v1_common_api.build_local_tool_summary)  # noqa: SLF001 - background worker's job
    data = client.get("/v1/tools/summaries/?name=ada-tool").get_json()
    summary = data["results"]["ada-tool"]

    assert data["cachePolicy"]["upstream"] is False
    assert summary["maintainer"]["status"] == "verified"
    assert summary["maintainerDimension"]["status"] == "maintained"
    assert summary["health"]["score"] >= 80
    assert summary["health"]["calculation"]["formula"] == "weighted_average(included dimension scores)"
    assert summary["health"]["sourceHealth"]["repository"] == {
        "url": "https://github.com/example/ada-tool",
        "branch": "main",
        "commitSha": "0123456789abcdef",
        "lastCommitAt": "2026-07-29T12:00:00Z",
        "commitCount": 42,
    }
    assert {item["key"] for item in summary["health"]["dimensions"]} == {
        "source-health",
        "maintainer-status",
        "runtime-health",
    }


def test_a_summary_rebuild_survives_the_build_invalidating_its_own_row(client, monkeypatch):
    """Rebuild a summary twice over the real builder, not a stub.

    `build_local_tool_summary` opens with `sync_author_claim_edges`, whose
    `affected` set always contains the tool being summarised, so every build
    reaches `replace_source_evidence` and its closing `s.delete(summary)` --
    against the very row `refresh` loaded to overwrite. The first rebuild of any
    tool therefore deletes its own target, and `_store` calls `s.add` on an
    instance the autoflush in `build_local_tool_summary` has already deleted.
    A tool with no cached row never noticed, which is why the failure only
    appeared for tools that had been summarised once before.
    """
    db.configure("sqlite://")
    db.init_schema()
    _stub_summary_executor(monkeypatch)

    tool_summaries.refresh(["patch-demo"], v1_common_api.build_local_tool_summary)
    with db.session_scope() as s:
        assert s.get(ToolSummaryCache, "patch-demo") is not None

    # The rebuild is the case that mattered: the row now exists, so refresh
    # loads it and hands it to a build that deletes it.
    tool_summaries.refresh(["patch-demo"], v1_common_api.build_local_tool_summary)
    with db.session_scope() as s:
        rebuilt = s.get(ToolSummaryCache, "patch-demo")
        assert rebuilt is not None
        assert rebuilt.summary["toolName"] == "patch-demo"
        assert rebuilt.last_error is None


def test_tool_summaries_endpoint_reuses_materialized_read_model(client, monkeypatch):
    db.configure("sqlite://")
    db.init_schema()
    _stub_summary_executor(monkeypatch)
    calls = []

    def build_summary(_s, tool_name):
        calls.append(tool_name)
        return {
            "toolName": tool_name,
            "health": {"score": 77, "grade": "good", "status": "watch", "dimensions": []},
            "maintainer": {"status": "unknown"},
            "maintainerDimension": {"status": "unknown"},
            "source": sync.SOURCE_LOCAL,
            "syncStatus": sync.SYNC_EVOLVED_REAL,
        }

    monkeypatch.setattr(v1_common_api, "build_local_tool_summary", build_summary)

    first = client.get("/v1/tools/summaries/?name=cached-tool")
    # Nothing is materialized on the read path, so the first response builds nothing.
    assert calls == []
    tool_summaries.refresh(["cached-tool"], build_summary)
    second = client.get("/v1/tools/summaries/?name=cached-tool")
    third = client.get("/v1/tools/summaries/?name=cached-tool")

    first_data = first.get_json()
    second_data = second.get_json()
    assert calls == ["cached-tool"]  # the extra reads reuse the materialized row
    assert first_data["results"] == {}
    assert first_data["cacheMeta"]["cached-tool"]["status"] == "pending"
    assert second_data["cacheMeta"]["cached-tool"]["status"] == "hit"
    assert second_data["results"]["cached-tool"]["health"]["score"] == 77
    assert third.get_json()["cacheMeta"]["cached-tool"]["status"] == "hit"
    assert "max-age=300" in second.headers["Cache-Control"]
    assert "stale-if-error=86400" in second.headers["Cache-Control"]
    with db.session_scope() as s:
        row = s.get(ToolSummaryCache, "cached-tool")
        assert row.summary["health"]["score"] == 77


def test_tool_summaries_endpoint_serves_stale_rows_and_queues_refresh(client, monkeypatch):
    db.configure("sqlite://")
    db.init_schema()
    now = utcnow()
    with db.session_scope() as s:
        s.add(
            ToolSummaryCache(
                tool_name="stale-tool",
                summary={"toolName": "stale-tool", "health": {"score": 42}},
                computed_at=now - timedelta(hours=1),
                expires_at=now - timedelta(minutes=1),
                stale_until=now + timedelta(hours=1),
            )
        )
    queued = []
    monkeypatch.setattr(tool_summaries, "queue_refresh", lambda names, _builder: queued.extend(names))

    data = client.get("/v1/tools/summaries/?name=stale-tool").get_json()

    assert data["results"]["stale-tool"]["health"]["score"] == 42
    assert data["cacheMeta"]["stale-tool"]["status"] == "stale"
    assert queued == ["stale-tool"]


def test_tool_summary_cache_refresh_worker_updates_rows_and_records_errors(monkeypatch):
    db.configure("sqlite://")
    db.init_schema()
    now = utcnow()
    with db.session_scope() as s:
        s.add(
            ToolSummaryCache(
                tool_name="queued-tool",
                summary={"toolName": "queued-tool", "health": {"score": 10}},
                computed_at=now - timedelta(hours=1),
                expires_at=now - timedelta(minutes=1),
                stale_until=now + timedelta(hours=1),
            )
        )
        s.add(
            ToolSummaryCache(
                tool_name="error-tool",
                summary={"toolName": "error-tool", "health": {"score": 20}},
                computed_at=now - timedelta(hours=1),
                expires_at=now - timedelta(minutes=1),
                stale_until=now + timedelta(hours=1),
            )
        )
        s.add(
            ToolSummaryCache(
                tool_name="expired-tool",
                summary={"toolName": "expired-tool", "health": {"score": 30}},
                computed_at=now - timedelta(days=2),
                expires_at=now - timedelta(days=1),
                stale_until=now - timedelta(minutes=1),
            )
        )

    submitted = []

    class InlineExecutor:
        def submit(self, fn, names, builder):
            submitted.append(names)
            fn(names, builder)

    def build_summary(_s, tool_name):
        return {"toolName": tool_name, "health": {"score": 88}}

    def fail_summary(_s, _tool_name):
        raise RuntimeError("refresh boom")

    monkeypatch.setattr(tool_summaries, "_EXECUTOR", InlineExecutor())
    tool_summaries._REFRESHING.clear()

    assert tool_summaries.summaries_for([], build_summary) == tool_summaries.SummaryRead(results={}, cache_meta={})
    assert tool_summaries.refresh([], build_summary) == 0
    stale_read = tool_summaries.summaries_for(["error-tool"], build_summary, refresh_stale=False)
    assert stale_read.cache_meta["error-tool"]["status"] == "stale"
    # Past stale_until the body is unservable, so the row is queued for rebuild
    # rather than rebuilt inline; same for a name with no row at all.
    expired_read = tool_summaries.summaries_for(["expired-tool"], build_summary)
    assert expired_read.cache_meta["expired-tool"]["status"] == "pending"
    assert expired_read.results == {}
    unknown_read = tool_summaries.summaries_for(["never-seen"], build_summary, refresh_stale=False)
    assert unknown_read.cache_meta["never-seen"]["status"] == "pending"
    assert unknown_read.results == {}
    tool_summaries.queue_refresh(["queued-tool", "queued-tool"], build_summary)
    tool_summaries._REFRESHING.add("queued-tool")
    tool_summaries.queue_refresh(["queued-tool"], build_summary)
    tool_summaries._REFRESHING.clear()
    tool_summaries.queue_refresh(["error-tool", "missing-tool"], fail_summary)

    # The expired read queued its own rebuild, ahead of the explicit queue calls.
    assert submitted == [("expired-tool",), ("queued-tool",), ("error-tool", "missing-tool")]
    with db.session_scope() as s:
        assert s.get(ToolSummaryCache, "queued-tool").summary["health"]["score"] == 88
        assert s.get(ToolSummaryCache, "error-tool").last_error == "refresh boom"
    assert tool_summaries._REFRESHING == set()


def test_public_json_response_supports_etag_revalidation(client):
    first = client.get("/v1/graph/")
    not_modified = client.get("/v1/graph/", headers={"If-None-Match": first.headers["ETag"]})

    assert first.status_code == 200
    assert "max-age=300" in first.headers["Cache-Control"]
    assert not_modified.status_code == 304
    assert not_modified.get_data() == b""


def test_graph_payload_exposes_canonical_project_and_language_facets(monkeypatch):
    monkeypatch.setattr(
        graph_payload.canonical_tools,
        "records",
        lambda limit: [
            {
                "toolName": "commons-tool",
                "record": {
                    "name": "commons-tool",
                    "title": "Commons tool",
                    "keywords": ["images"],
                    "for_wikis": ["commons.wikimedia.org"],
                    "available_ui_languages": ["en", "fr"],
                },
            }
        ],
    )

    payload = graph_payload.build()

    assert payload["nodes"] == [
        {
            "id": "commons-tool",
            "title": "Commons tool",
            "community": 0,
            "weight": 0,
            "endorsement": 0,
            "fits": False,
            "projects": ["commons.wikimedia.org"],
            "languages": ["en", "fr"],
            "group": 0,
            "groupValues": [0],
        }
    ]


def test_graph_endpoint_passes_limit_and_grouping_parameters(client, monkeypatch):
    captured = {}

    def fake_payload(**kwargs):
        captured.update(kwargs)
        return {"nodes": [], "edges": []}

    monkeypatch.setattr(v1_api.graph_payload, "payload", fake_payload)
    response = client.get("/v1/graph/?limit=4000&groupBy=language")

    assert response.status_code == 200
    assert captured == {"limit": "4000", "group_by": "language"}


def test_graph_payload_preserves_similarity_edges_in_grouped_views(monkeypatch):
    monkeypatch.setattr(
        graph_payload.canonical_tools,
        "records",
        lambda limit: [
            {
                "toolName": "english-tool",
                "record": {
                    "name": "english-tool",
                    "title": "English tool",
                    "keywords": ["images"],
                    "available_ui_languages": ["en"],
                },
            },
            {
                "toolName": "french-tool",
                "record": {
                    "name": "french-tool",
                    "title": "French tool",
                    "keywords": ["images"],
                    "available_ui_languages": ["fr"],
                },
            },
        ],
    )

    payload = graph_payload.build(limit=4000, group_by="language")

    assert payload["nodeLimit"] == 4000
    assert payload["layout"] == "force"
    assert payload["edges"] == [{"source": "english-tool", "target": "french-tool", "weight": 1.0}]
    assert [group["label"] for group in payload["groupMeta"]] == ["en", "fr"]


def test_graph_payload_preserves_multi_value_memberships_and_counts(monkeypatch):
    monkeypatch.setattr(
        graph_payload.canonical_tools,
        "records",
        lambda limit: [
            {
                "toolName": "multi-tool",
                "record": {
                    "name": "multi-tool",
                    "title": "Multi tool",
                    "keywords": ["images"],
                    "for_wikis": ["Commons.wikimedia.org", "www.wikidata.org"],
                },
            },
            {
                "toolName": "commons-tool",
                "record": {
                    "name": "commons-tool",
                    "title": "Commons tool",
                    "keywords": ["images"],
                    "for_wikis": ["commons.wikimedia.org"],
                },
            },
        ],
    )

    payload = graph_payload.build(group_by="project")

    by_name = {node["id"]: node for node in payload["nodes"]}
    assert by_name["multi-tool"]["groupValues"] == [0, 1]
    assert by_name["multi-tool"]["group"] == 0
    assert payload["groupMeta"] == [
        {"id": 0, "label": "Wikimedia Commons", "size": 2},
        {"id": 1, "label": "Wikidata", "size": 1},
    ]


def test_graph_payload_merges_project_aliases_and_family_wildcards(monkeypatch):
    records = []
    for name, project in (
        ("domain", "www.wikidata.org"),
        ("label", "Wikidata"),
        ("family", "*.wikisource.org"),
    ):
        records.append(
            {
                "toolName": name,
                "record": {"name": name, "title": name, "keywords": ["images"], "for_wikis": [project]},
            }
        )
    monkeypatch.setattr(graph_payload.canonical_tools, "records", lambda limit: records)

    payload = graph_payload.build(group_by="project")

    assert payload["groupMeta"] == [
        {"id": 0, "label": "Wikidata", "size": 2},
        {"id": 1, "label": "Wikisource", "size": 1},
    ]


def test_graph_payload_splits_technology_values_and_extracts_platforms(monkeypatch):
    records = [
        {
            "toolName": "mixed-stack",
            "record": {
                "name": "mixed-stack",
                "title": "Mixed stack",
                "keywords": ["images"],
                "technology_used": ["Toolforge", "Deno, Kubernetes, React, Preact"],
            },
        },
        {
            "toolName": "php-stack",
            "record": {
                "name": "php-stack",
                "title": "PHP stack",
                "keywords": ["images"],
                "technology_used": ["toolforge", "PHP"],
            },
        },
    ]
    monkeypatch.setattr(graph_payload.canonical_tools, "records", lambda limit: records)

    technology = graph_payload.build(group_by="technology")
    platform = graph_payload.build(group_by="platform")

    assert [group["label"] for group in technology["groupMeta"]] == ["Deno", "PHP", "Preact", "React"]
    assert platform["groupMeta"] == [
        {"id": 0, "label": "Toolforge", "size": 2},
        {"id": 1, "label": "Kubernetes", "size": 1},
    ]
    coverage = {item["id"]: item for item in platform["groupingMeta"]}
    assert coverage["technology"]["enabled"] is True
    assert coverage["platform"]["enabled"] is True


def test_graph_payload_reports_grouping_coverage(monkeypatch):
    records = []
    for index in range(20):
        record = {"name": f"tool-{index}", "title": f"Tool {index}", "keywords": ["images"]}
        if index < 2:
            record["for_wikis"] = ["commons.wikimedia.org" if index % 2 else "www.wikidata.org"]
        records.append({"toolName": record["name"], "record": record})
    monkeypatch.setattr(graph_payload.canonical_tools, "records", lambda limit: records)

    payload = graph_payload.build()
    coverage = {item["id"]: item for item in payload["groupingMeta"]}

    assert coverage["similarity"]["enabled"] is True
    assert coverage["project"] == {
        "id": "project",
        "covered": 2,
        "total": 20,
        "coverage": 0.1,
        "distinctValues": 2,
        "enabled": True,
    }
    assert coverage["task"]["enabled"] is False


def test_graph_payload_shared_cache_survives_worker_memory_reset(client, monkeypatch):
    graph_payload._CACHE.clear()
    api_cache.clear()
    built = {"nodes": [{"id": "shared"}], "edges": [], "generatedAt": "2026-08-01T00:00:00Z"}
    monkeypatch.setattr(graph_payload, "build", lambda **_kwargs: built)

    assert graph_payload.payload(force_refresh=True) == built
    graph_payload._CACHE.clear()
    monkeypatch.setattr(graph_payload, "build", lambda **_kwargs: pytest.fail("shared cache should avoid rebuild"))

    assert graph_payload.payload() == built


def test_graph_payload_cache_key_is_schema_versioned():
    assert graph_payload._cache_url(250, "project").endswith("limit=250&groupBy=project&version=5")


def test_graph_payload_serves_stale_shared_data_while_refreshing(client, monkeypatch):
    graph_payload._CACHE.clear()
    graph_payload._REFRESHING.clear()
    api_cache.clear()
    clock = {"now": utcnow()}
    monkeypatch.setattr(api_cache, "utcnow", lambda: clock["now"])
    old = {"nodes": [{"id": "old"}], "edges": [], "generatedAt": "old"}
    api_cache.put_success(
        graph_payload._cache_url(250, "similarity"),
        api_cache.CacheableResponse(
            status=200,
            content_type="application/json",
            body=dumps(old).encode(),
        ),
        fresh_seconds=1,
        stale_if_error_seconds=60,
    )
    clock["now"] += timedelta(seconds=2)
    fresh = {"nodes": [{"id": "fresh"}], "edges": [], "generatedAt": "fresh"}
    monkeypatch.setattr(graph_payload, "build", lambda **_kwargs: fresh)

    class InlineExecutor:
        def submit(self, fn, *args):
            fn(*args)

    monkeypatch.setattr(graph_payload, "_EXECUTOR", InlineExecutor())

    assert graph_payload.payload() == old
    graph_payload._CACHE.clear()
    assert graph_payload.payload() == fresh
    assert graph_payload._REFRESHING == set()


@pytest.mark.parametrize("body", [b"not-json", b'[{"nodes":[],"edges":[]}]', b'{"nodes":[]}'])
def test_graph_payload_rebuilds_invalid_shared_rows(client, monkeypatch, body):
    graph_payload._CACHE.clear()
    api_cache.clear()
    api_cache.put_success(
        graph_payload._cache_url(250, "similarity"),
        api_cache.CacheableResponse(status=200, content_type="application/json", body=body),
    )
    rebuilt = {"nodes": [], "edges": [], "generatedAt": "rebuilt"}
    monkeypatch.setattr(graph_payload, "build", lambda **_kwargs: rebuilt)

    assert graph_payload.payload() == rebuilt


def test_graph_payload_worker_cache_bounds_and_refresh_guards(client, monkeypatch):
    graph_payload._CACHE.clear()
    for index in range(graph_payload.GRAPH_CACHE_MAX_ENTRIES):
        graph_payload._CACHE[str(index)] = {"payload": {}, "expires_at": utcnow()}
    graph_payload._remember("new", {"nodes": [], "edges": []})
    assert len(graph_payload._CACHE) == graph_payload.GRAPH_CACHE_MAX_ENTRIES
    assert "new" in graph_payload._CACHE

    cache_key = "250:similarity"
    graph_payload._REFRESHING.add(cache_key)
    monkeypatch.setattr(graph_payload, "build", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("refresh")))
    graph_payload._refresh_worker(250, "similarity", cache_key)
    assert cache_key not in graph_payload._REFRESHING

    class RejectSubmit:
        def submit(self, *_args):
            pytest.fail("an already-running graph refresh must not be submitted twice")

    graph_payload._REFRESHING.add(cache_key)
    monkeypatch.setattr(graph_payload, "_EXECUTOR", RejectSubmit())
    graph_payload._queue_refresh(250, "similarity", cache_key)
    graph_payload._REFRESHING.clear()
    graph_payload._CACHE.clear()


def test_latest_public_health_core_query_uses_mariadb_portable_null_ordering():
    compiled = str(v1_common_api.latest_public_health_core_statement("ada-tool").compile(dialect=mysql.dialect()))

    assert "NULLS LAST" not in compiled.upper()
    assert "source_analysis_reports.reviewed_at IS NULL" in compiled


def test_person_activity_summary_refresh_distinguishes_empty_and_full_scope():
    db.configure("sqlite://")
    db.init_schema()
    with db.session_scope() as s:
        user = User(wm_sub="maintainer-empty", username="Ada")
        s.add(user)
        s.flush()
        from backend import people_index

        people_index.link_user(s, user)
        assert people_index.refresh_activity_summaries(s, person_ids=set()) == []
        assert s.query(PersonActivitySummary).count() == 0

        summaries = people_index.refresh_activity_summaries(s)
        assert len(summaries) == 1
        assert s.query(PersonActivitySummary).count() == 1


def test_public_tool_people_endpoint_reads_local_toolhub_and_evolved_evidence(client):
    with db.session_scope() as s:
        user = User(wm_sub="42", username="Ada", registered_at=utcnow() - timedelta(days=5))
        s.add(user)
        s.add(
            ToolAuthorClaim(
                tool_name="ada-tool",
                author_name="Ada Lovelace",
                toolhub_username="Ada",
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                verification_method=sync.AUTHOR_CLAIM_SIGNED_TOOLINFO,
                evidence_payload={"signature": "private signature payload"},
            )
        )
        s.flush()
        from backend import people_index

        people_index.link_user(s, user)
        maintainer_index.replace_toolhub_metadata_edges(
            s,
            "ada-tool",
            {
                "name": "ada-tool",
                "author": [{"name": "Ada Lovelace", "developer_username": "Ada", "wiki_username": "AdaWiki"}],
                "created_by": {"id": 42, "username": "Ada"},
                "modified_by": {"id": 43, "username": "Grace"},
            },
        )
        maintainer_index.sync_author_claim_edges(s, tool_names=["ada-tool"])

    resp = client.get("/v1/people/tools/ada-tool/")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["toolName"] == "ada-tool"
    assert data["counts"] == {
        sync.PERSON_REL_AUTHOR: 1,
        sync.PERSON_REL_MAINTAINER: 1,
    }
    assert data["canonicalAuthority"]["catalog"] == "toolhub"
    assert "private signature payload" not in dumps(data)
    assert data["unresolvedAttributions"] == []
    ada_person = next(item for item in data["people"] if item["displayName"] == "Ada")
    assert {item["namespace"] for item in ada_person["identifiers"]} == {
        "toolhub_user_id",
        "toolhub_username",
    }
    assert any(item["displayName"] == "Ada Lovelace" for item in data["people"])
    assert {relationship["type"] for relationship in ada_person["relationships"]} == {sync.PERSON_REL_MAINTAINER}
    assert data["unresolvedCounts"][sync.PERSON_REL_AUTHOR] == 0
    assert sync.PERSON_REL_RECORD_OWNER not in dumps(data)
    assert sync.PERSON_REL_CATALOG_ACTOR not in dumps(data)

    with db.session_scope() as s:
        internal_roles = set(
            s.execute(
                select(ToolPersonRelationship.relationship_type).where(ToolPersonRelationship.tool_name == "ada-tool")
            ).scalars()
        )
    assert sync.PERSON_REL_CATALOG_ACTOR in internal_roles


def test_account_directory_searches_projection_and_links_only_stable_identity(client, monkeypatch):
    monkeypatch.setattr(
        toolhub,
        "public_api_get",
        lambda *_args, **_kwargs: pytest.fail("account directory reads must remain local"),
    )
    now = utcnow()
    with db.session_scope() as s:
        linked = Person(canonical_key="toolhub_user_id:42", display_name="Magnus Manske", identity_quality="stable_id")
        conflicting_toolhub = Person(
            canonical_key="toolhub_user_id:43",
            display_name="Conflicting Toolhub",
            identity_quality="stable_id",
        )
        conflicting_wikimedia = Person(
            canonical_key="wikimedia_global_user_id:100043",
            display_name="Conflicting Wikimedia",
            identity_quality="stable_id",
        )
        s.add_all([linked, conflicting_toolhub, conflicting_wikimedia])
        s.flush()
        s.add_all(
            [
                PersonIdentifier(
                    person_id=linked.id,
                    namespace=people_index.NS_TOOLHUB_USER_ID,
                    value="42",
                    normalized_value="42",
                    identifier_kind=people_index.IDENTIFIER_STABLE,
                ),
                PersonIdentifier(
                    person_id=linked.id,
                    namespace=people_index.NS_WIKIMEDIA_GLOBAL_USER_ID,
                    value="100042",
                    normalized_value="100042",
                    identifier_kind=people_index.IDENTIFIER_STABLE,
                ),
                PersonIdentifier(
                    person_id=conflicting_toolhub.id,
                    namespace=people_index.NS_TOOLHUB_USER_ID,
                    value="43",
                    normalized_value="43",
                    identifier_kind=people_index.IDENTIFIER_STABLE,
                ),
                PersonIdentifier(
                    person_id=conflicting_wikimedia.id,
                    namespace=people_index.NS_WIKIMEDIA_GLOBAL_USER_ID,
                    value="100043",
                    normalized_value="100043",
                    identifier_kind=people_index.IDENTIFIER_STABLE,
                ),
            ]
        )
        accounts = []
        for index in range(1, 56):
            username = (
                "Magnus Manske" if index == 42 else ("Conflicted Account" if index == 43 else f"Account {index:03d}")
            )
            groups = ["admin"] if index == 42 else []
            accounts.append(
                ToolhubAccountProjection(
                    toolhub_user_id=str(index),
                    username=username,
                    normalized_username=username.casefold(),
                    groups=groups,
                    groups_search="\nadmin\n" if groups else "",
                    wikimedia_global_user_id=str(100_000 + index),
                    date_joined=now - timedelta(days=index),
                    generation=1,
                )
            )
        s.add_all(accounts)
        s.add(
            ToolhubAccountSyncState(
                key="official_accounts",
                active_generation=1,
                cycles_completed=1,
                total_count=55,
                status="error",
                last_completed_at=now,
                last_success_at=now,
                last_error="upstream refresh failed",
            )
        )

    first = client.get("/v1/accounts/?page_size=24&ordering=name").get_json()
    assert first["count"] == 55
    assert first["pageCount"] == 3
    assert len(first["results"]) == 24
    assert first["next"] == "/v1/accounts/?page_size=24&ordering=name&page=2"
    assert first["sync"]["status"] == "stale"
    assert first["canonicalAuthority"] == {"accounts": "toolhub"}

    searched = client.get("/v1/accounts/?q=manske").get_json()
    assert searched["count"] == 1
    account = searched["results"][0]
    assert account["id"] == "42"
    assert account["personId"] == linked.public_id
    assert account["identityLinkStatus"] == "linked"
    assert account["identityLinkBasis"] == ["toolhub_user_id", "wikimedia_global_user_id"]
    grouped = client.get("/v1/accounts/?group=ADMIN").get_json()
    assert [row["id"] for row in grouped["results"]] == ["42"]
    recent = client.get("/v1/accounts/?ordering=recent&page_size=1").get_json()
    assert recent["results"][0]["id"] == "1"
    detail = client.get("/v1/accounts/42/").get_json()
    assert detail["username"] == "Magnus Manske"
    conflict = client.get("/v1/accounts/43/").get_json()
    assert conflict["personId"] is None
    assert conflict["identityLinkStatus"] == "conflict"
    assert client.get("/v1/accounts/?q=%25").get_json()["count"] == 0
    for path in (
        "/v1/accounts/?page=0",
        "/v1/accounts/?page_size=nope",
        "/v1/accounts/?ordering=relationship",
    ):
        assert client.get(path).status_code == 400
    assert client.get("/v1/accounts/9999/").status_code == 404


def test_community_search_collapses_stable_accounts_and_preserves_unresolved_labels(client, monkeypatch):
    monkeypatch.setattr(
        toolhub,
        "public_api_get",
        lambda *_args, **_kwargs: pytest.fail("community search must remain local"),
    )
    now = utcnow()
    with db.session_scope() as s:
        magnus = Person(
            canonical_key="toolhub_user_id:152",
            display_name="Magnus Manske",
            identity_quality="stable_id",
        )
        display_only = Person(
            canonical_key="display:legacy-tool:author:magnus-manske",
            display_name="Magnus Manske",
            identity_quality="display_name",
        )
        metadata_handle_only = Person(
            canonical_key="toolforge:magnus-manske",
            display_name="Magnus Manske",
            # Reproduces a legacy stale quality flag after an immutable ID moved
            # to the canonical account person.
            identity_quality="stable",
        )
        linked_account_only = Person(
            canonical_key="toolhub_user_id:153",
            display_name="Linked Account Only",
            identity_quality="stable_id",
        )
        toolhub_actor = Person(
            canonical_key="toolhub_user_id:9",
            display_name="Toolhub",
            identity_quality="stable_id",
        )
        s.add_all([magnus, display_only, metadata_handle_only, linked_account_only, toolhub_actor])
        s.flush()
        s.add_all(
            [
                PersonIdentifier(
                    person_id=magnus.id,
                    namespace=people_index.NS_TOOLHUB_USER_ID,
                    value="152",
                    normalized_value="152",
                    identifier_kind=people_index.IDENTIFIER_STABLE,
                ),
                PersonIdentifier(
                    person_id=metadata_handle_only.id,
                    namespace=people_index.NS_TOOLFORGE_USERNAME,
                    value="Magnus Manske",
                    normalized_value="magnus manske",
                    identifier_kind=people_index.IDENTIFIER_HANDLE,
                    source="legacy_untrusted_metadata",
                ),
                PersonIdentifier(
                    person_id=metadata_handle_only.id,
                    namespace=people_index.NS_WIKI_USERNAME,
                    value="User:Magnus Manske",
                    normalized_value="user:magnus manske",
                    identifier_kind=people_index.IDENTIFIER_HANDLE,
                    source="legacy_untrusted_metadata",
                ),
                PersonIdentifier(
                    person_id=toolhub_actor.id,
                    namespace=people_index.NS_TOOLHUB_USER_ID,
                    value="9",
                    normalized_value="9",
                    identifier_kind=people_index.IDENTIFIER_STABLE,
                ),
                PersonIdentifier(
                    person_id=linked_account_only.id,
                    namespace=people_index.NS_TOOLHUB_USER_ID,
                    value="153",
                    normalized_value="153",
                    identifier_kind=people_index.IDENTIFIER_STABLE,
                ),
                PersonIdentifier(
                    person_id=linked_account_only.id,
                    namespace=people_index.NS_WIKIMEDIA_GLOBAL_USER_ID,
                    value="9002",
                    normalized_value="9002",
                    identifier_kind=people_index.IDENTIFIER_STABLE,
                ),
                PersonIdentifier(
                    person_id=magnus.id,
                    namespace=people_index.NS_WIKIMEDIA_GLOBAL_USER_ID,
                    value="9001",
                    normalized_value="9001",
                    identifier_kind=people_index.IDENTIFIER_STABLE,
                ),
                PersonProfile(person_id=magnus.id, visibility="public"),
                ToolPersonRelationship(
                    tool_name="magnus-tool",
                    person_id=magnus.id,
                    relationship_type=sync.PERSON_REL_MAINTAINER,
                    verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                    confidence=100,
                    evidence_count=2,
                    toolhub_canonical=True,
                ),
                ToolRelationshipEvidence(
                    tool_name="magnus-tool",
                    person_id=magnus.id,
                    relationship_type=sync.PERSON_REL_MAINTAINER,
                    source="toolforge_toolsadmin",
                    method="toolforge_maintainer",
                    evidence_key="magnus-tool:magnus",
                    observed_name="Magnus Manske",
                    verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                    confidence=100,
                    checked_at=now,
                ),
                ToolPersonRelationship(
                    tool_name="legacy-tool",
                    person_id=display_only.id,
                    relationship_type=sync.PERSON_REL_AUTHOR,
                    verification_status=sync.AUTHOR_CLAIM_UNVERIFIED,
                    confidence=20,
                    evidence_count=1,
                    toolhub_canonical=True,
                ),
                ToolPersonRelationship(
                    tool_name="metadata-handle-tool",
                    person_id=metadata_handle_only.id,
                    relationship_type=sync.PERSON_REL_AUTHOR,
                    verification_status=sync.AUTHOR_CLAIM_UNVERIFIED,
                    confidence=45,
                    evidence_count=1,
                    toolhub_canonical=True,
                ),
                ToolPersonRelationship(
                    tool_name="magnus-tool",
                    person_id=toolhub_actor.id,
                    relationship_type=sync.PERSON_REL_CATALOG_ACTOR,
                    verification_status=sync.AUTHOR_CLAIM_UNVERIFIED,
                    confidence=55,
                    evidence_count=1,
                    toolhub_canonical=True,
                ),
                CanonicalToolCache(
                    tool_name="magnus-tool",
                    record={"name": "magnus-tool", "title": "Magnus Tool"},
                    search_text="magnus manske magnus tool",
                    expires_at=now + timedelta(hours=1),
                    stale_until=now + timedelta(days=1),
                ),
                CanonicalToolCache(
                    tool_name="description-only",
                    record={
                        "name": "description-only",
                        "title": "Plantel Converter",
                        "description": "Based on a script by Magnus Manske",
                        "author": [{"name": "Someone Else"}],
                    },
                    search_text="plantel converter based on a script by magnus manske someone else",
                    expires_at=now + timedelta(hours=1),
                    stale_until=now + timedelta(days=1),
                ),
                ToolhubAccountProjection(
                    toolhub_user_id="152",
                    username="Magnus Manske",
                    normalized_username="magnus manske",
                    wikimedia_global_user_id="9001",
                    generation=1,
                ),
                ToolhubAccountProjection(
                    toolhub_user_id="999",
                    username="Official Only",
                    normalized_username="official only",
                    generation=1,
                ),
                ToolhubAccountProjection(
                    toolhub_user_id="153",
                    username="Linked Account Only",
                    normalized_username="linked account only",
                    wikimedia_global_user_id="9002",
                    generation=1,
                ),
                ToolhubAccountSyncState(
                    key="official_accounts",
                    active_generation=1,
                    cycles_completed=1,
                    total_count=3,
                    status="complete",
                    last_completed_at=now,
                    last_success_at=now,
                ),
            ]
        )
        # Magnus-scale regression: hundreds of label-only observations must
        # remain one supporting evidence cluster, never hundreds of profiles.
        extra_display_people = [
            Person(
                canonical_key=f"display:legacy-tool-{index}:author:magnus-manske",
                display_name="Magnus Manske",
                identity_quality="display_name",
            )
            for index in range(2, 324)
        ]
        s.add_all(extra_display_people)
        s.flush()
        s.add_all(
            [
                ToolPersonRelationship(
                    tool_name=f"legacy-tool-{index}",
                    person_id=person.id,
                    relationship_type=sync.PERSON_REL_AUTHOR,
                    verification_status=sync.AUTHOR_CLAIM_UNVERIFIED,
                    confidence=20,
                    evidence_count=1,
                    toolhub_canonical=True,
                )
                for index, person in enumerate(extra_display_people, start=2)
            ]
        )
        s.add_all(
            [
                UnresolvedAttributionEvidence(
                    tool_name=f"legacy-attribution-{index}",
                    observed_label="Magnus Manske",
                    normalized_label="magnus manske",
                    relationship_type=sync.PERSON_REL_AUTHOR,
                    source="toolhub_author_metadata",
                    method="toolhub_author_metadata",
                    evidence_key=str(index),
                    verification_status=sync.AUTHOR_CLAIM_UNVERIFIED,
                    confidence=45,
                    toolhub_canonical=True,
                    checked_at=now,
                )
                for index in range(324)
            ]
        )

    response = client.get("/v1/community/?q=Magnus%20Manske")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["counts"] == {
        "people": 1,
        "accounts": 0,
        "tools": 1,
        "otherToolMatches": 1,
        "unresolvedAttributions": 0,
        "foldedUnresolvedAttributions": 1,
    }
    assert [item["kind"] for item in payload["results"]] == ["person"]
    assert payload["primaryResults"] == payload["results"]
    person = payload["results"][0]
    assert person["person"]["id"] == magnus.public_id
    assert person["matchBasis"] == ["account", "identity"]
    assert person["identityEvidence"] == {
        "officialToolhubAccount": True,
        "toolforgeHandle": False,
        "wikiHandle": False,
        "wikimediaIdentity": True,
    }
    assert person["officialAccountMatches"] == [
        {
            "id": "152",
            "identityLinkBasis": ["toolhub_user_id", "wikimedia_global_user_id"],
            "username": "Magnus Manske",
        }
    ]
    assert person["supportingEvidence"][0]["label"] == "Magnus Manske"
    assert person["supportingEvidence"][0]["relationshipBreakdown"] == [
        {
            "bestConfidence": 45,
            "evidenceCount": 324,
            "status": "unverified",
            "toolCount": 324,
            "type": "author",
        }
    ]
    assert payload["unresolvedEvidence"] == {"count": 0, "results": [], "truncated": False}
    assert payload["relatedTools"]["count"] == 1
    related_tool = payload["relatedTools"]["results"][0]
    assert related_tool["tool"]["name"] == "magnus-tool"
    assert related_tool["match"]["reason"] == "person_relationship"
    assert [(row["type"], row["status"]) for row in related_tool["relationships"]] == [
        (sync.PERSON_REL_MAINTAINER, sync.AUTHOR_CLAIM_VERIFIED)
    ]
    assert related_tool["relationships"][0]["evidence"][0]["method"] == "toolforge_maintainer"
    assert payload["otherMatches"]["count"] == 1
    assert payload["otherMatches"]["results"][0]["tool"]["name"] == "description-only"
    assert payload["otherMatches"]["results"][0]["match"] == {
        "field": "description",
        "reason": "description_mention",
        "value": "Based on a script by Magnus Manske",
    }
    assert all(item.get("person", {}).get("displayName") != "Toolhub" for item in payload["results"])
    assert payload["canonicalAuthority"] == {
        "accounts": "toolhub",
        "catalog": "toolhub",
        "profiles": "toolhub-evolved",
    }

    by_tool = client.get("/v1/community/?q=magnus-tool").get_json()
    assert by_tool["results"] == []
    assert by_tool["relatedTools"]["results"][0]["matchBasis"] == ["name"]
    assert by_tool["relatedTools"]["results"][0]["match"]["reason"] == "exact_name"

    account_only = client.get("/v1/community/?q=official%20only").get_json()
    assert account_only["counts"] == {
        "people": 0,
        "accounts": 1,
        "tools": 0,
        "otherToolMatches": 0,
        "unresolvedAttributions": 0,
        "foldedUnresolvedAttributions": 0,
    }
    assert account_only["results"][0]["account"]["identityLinkStatus"] == "unlinked"
    linked_only = client.get("/v1/community/?q=linked%20account%20only").get_json()
    assert linked_only["results"][0]["kind"] == "account"
    assert linked_only["results"][0]["account"]["personId"] == linked_account_only.public_id
    assert linked_only["results"][0]["relationshipSummary"]["toolCountsByType"] == {
        sync.PERSON_REL_AUTHOR: 0,
        sync.PERSON_REL_MAINTAINER: 0,
    }
    assert client.get("/v1/community/?q=official%20only&contributor=observed").get_json()["count"] == 0

    for path in (
        "/v1/community/?page=0",
        "/v1/community/?page_size=nope",
        "/v1/community/?ordering=alphabetical",
        "/v1/community/?contributor=registered",
    ):
        assert client.get(path).status_code == 400


def test_people_directory_contributor_filter_reports_observed_activity_basis(client):
    now = utcnow()
    with db.session_scope() as s:
        people = [
            Person(canonical_key=f"toolhub_user_id:{index}", display_name=name, identity_quality="stable_id")
            for index, name in ((1, "Canonical Actor"), (2, "Approved Contributor"), (3, "Registered Only"))
        ]
        s.add_all(people)
        s.flush()
        for index, person in enumerate(people, start=1):
            s.add(
                PersonIdentifier(
                    person_id=person.id,
                    namespace=people_index.NS_TOOLHUB_USER_ID,
                    value=str(index),
                    normalized_value=str(index),
                    identifier_kind=people_index.IDENTIFIER_STABLE,
                )
            )
            s.add(PersonProfile(person_id=person.id, visibility="public"))
        s.add(
            ToolPersonRelationship(
                tool_name="actor-tool",
                person_id=people[0].id,
                relationship_type=sync.PERSON_REL_CATALOG_ACTOR,
                verification_status=sync.AUTHOR_CLAIM_UNVERIFIED,
                confidence=55,
                evidence_count=1,
                toolhub_canonical=True,
            )
        )
        s.add_all(
            [
                PersonActivitySummary(person_id=people[0].id, contribution_count=0, computed_at=now),
                PersonActivitySummary(person_id=people[1].id, contribution_count=3, computed_at=now),
                PersonActivitySummary(person_id=people[2].id, contribution_count=0, computed_at=now),
            ]
        )

    data = client.get("/v1/people/?contributor=observed&ordering=name").get_json()

    assert [row["displayName"] for row in data["results"]] == ["Approved Contributor", "Canonical Actor"]
    by_name = {row["displayName"]: row["contributor"] for row in data["results"]}
    assert by_name["Canonical Actor"] == {
        "eligible": True,
        "bases": ["observed_public_contribution"],
        "approvedPublicContributionCount": 0,
    }
    assert by_name["Approved Contributor"]["bases"] == ["observed_public_contribution"]
    assert by_name["Approved Contributor"]["approvedPublicContributionCount"] == 3
    assert client.get("/v1/people/?contributor=registered").status_code == 400


def test_public_tool_people_endpoint_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(security, "read_rate_limited", lambda _remote_addr: True)
    resp = client.get("/v1/people/tools/ada-tool/")
    assert resp.status_code == 429
    assert resp.get_json()["error"] == "rate limit exceeded"


def test_person_profile_paginates_prolific_relationships_without_upstream_fan_out(client, monkeypatch):
    monkeypatch.setattr(
        toolhub,
        "public_api_get",
        lambda *_args, **_kwargs: pytest.fail("person profiles must not fetch Toolhub tool details"),
    )
    now = utcnow()
    with db.session_scope() as s:
        user = User(wm_sub="prolific-42", username="Prolific Maintainer")
        s.add(user)
        s.flush()
        person = people_index.link_user(s, user)
        public_id = person.public_id
        relationships = [
            ToolPersonRelationship(
                tool_name=f"profile-tool-{index:03d}",
                person_id=person.id,
                relationship_type=sync.PERSON_REL_AUTHOR,
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                confidence=90,
                evidence_count=1 if index == 24 else 0,
            )
            for index in range(250)
        ]
        relationships.append(
            ToolPersonRelationship(
                tool_name="profile-tool-024",
                person_id=person.id,
                relationship_type=sync.PERSON_REL_MAINTAINER,
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                confidence=95,
                evidence_count=1,
            )
        )
        s.add_all(relationships)
        s.add_all(
            [
                ToolRelationshipEvidence(
                    tool_name="profile-tool-024",
                    person_id=person.id,
                    relationship_type=sync.PERSON_REL_AUTHOR,
                    source="toolhub_author_metadata",
                    method="toolhub_author_metadata",
                    evidence_key="author-24",
                    observed_name="Prolific Maintainer",
                    verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                    confidence=90,
                ),
                ToolRelationshipEvidence(
                    tool_name="profile-tool-024",
                    person_id=person.id,
                    relationship_type=sync.PERSON_REL_MAINTAINER,
                    source="toolforge_toolsadmin",
                    method="toolforge_maintainer",
                    evidence_key="maintainer-24",
                    observed_name="Prolific Maintainer",
                    verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                    confidence=95,
                ),
                CanonicalToolCache(
                    tool_name="profile-tool-024",
                    record={
                        "name": "profile-tool-024",
                        "title": "Canonical Tool 24",
                        "description": "A locally cached canonical summary.",
                        "secret": "must not leave the compact projection",
                    },
                    expires_at=now + timedelta(hours=1),
                    stale_until=now + timedelta(hours=2),
                ),
            ]
        )

    first = client.get(f"/v1/people/{public_id}/")
    assert first.status_code == 200
    first_data = first.get_json()
    assert first_data["toolCount"] == 250
    assert first_data["tools"] | {"results": []} == {
        "count": 250,
        "page": 1,
        "pageSize": 24,
        "pageCount": 11,
        "nextPage": 2,
        "previousPage": None,
        "next": f"/v1/people/{public_id}/?tool_page=2",
        "previous": None,
        "results": [],
    }
    assert len(first_data["tools"]["results"]) == 24
    assert first_data["tools"]["results"][0]["name"] == "profile-tool-000"
    assert first_data["tools"]["results"][-1]["name"] == "profile-tool-023"

    second = client.get(f"/v1/people/{public_id}/?tool_page=2&tool_page_size=24").get_json()
    assert second["tools"]["page"] == 2
    assert len(second["tools"]["results"]) == 24
    assert second["tools"]["previous"] == f"/v1/people/{public_id}/?tool_page=1&tool_page_size=24"
    assert second["tools"]["next"] == f"/v1/people/{public_id}/?tool_page=3&tool_page_size=24"
    cached = second["tools"]["results"][0]
    assert cached["name"] == "profile-tool-024"
    assert cached["summaryStatus"] == "available"
    assert cached["summary"]["title"] == "Canonical Tool 24"
    assert "secret" not in cached["summary"]
    assert {relationship["type"] for relationship in cached["relationships"]} == {
        sync.PERSON_REL_AUTHOR,
        sync.PERSON_REL_MAINTAINER,
    }
    assert {relationship["evidence"][0]["source"] for relationship in cached["relationships"]} == {
        "toolhub_author_metadata",
        "toolforge_toolsadmin",
    }
    missing = second["tools"]["results"][1]
    assert missing["name"] == "profile-tool-025"
    assert missing["summaryStatus"] == "missing"
    assert missing["summary"]["_missingCanonical"] is True

    final = client.get(f"/v1/people/{public_id}/?tool_page=999").get_json()
    assert final["tools"]["page"] == 11
    assert [row["name"] for row in final["tools"]["results"]] == [
        f"profile-tool-{index:03d}" for index in range(240, 250)
    ]
    capped = client.get(f"/v1/people/{public_id}/?tool_page_size=500").get_json()
    assert capped["tools"]["pageSize"] == 50
    assert capped["tools"]["pageCount"] == 5
    assert len(capped["tools"]["results"]) == 50
    for query in ("tool_page=0", "tool_page=nope", "tool_page_size=0"):
        assert client.get(f"/v1/people/{public_id}/?{query}").status_code == 400


def test_person_profile_uses_immutable_public_id_and_evolved_owned_content(client):
    uid = add_user(username="Ada", wm_sub="42")
    sign_in(client, uid)

    initial = client.get("/v1/me/profile/").get_json()["profile"]
    public_id = initial["personId"]
    assert len(public_id) == 36

    updated = client.put(
        "/v1/me/profile/",
        json={
            "bio": "Builds Wikimedia tools.",
            "websiteUrl": "https://example.org/ada",
            "avatarUrl": "http://unsafe.example/avatar.png",
            "location": "London",
            "links": ["https://meta.wikimedia.org/wiki/User:Ada", "javascript:alert(1)"],
        },
        headers={"X-CSRF-Token": "tok"},
    ).get_json()["profile"]
    assert updated["personId"] == public_id
    assert updated["avatarUrl"] == ""
    assert updated["links"] == ["https://meta.wikimedia.org/wiki/User:Ada"]

    public = client.get(f"/v1/people/{public_id}/").get_json()
    public_slug = public["slug"]
    assert public_slug.startswith("ada-")
    assert public["canonicalPath"] == f"/people/{public_slug}"
    assert client.get(f"/v1/people/{public_slug}/").get_json()["id"] == public_id
    assert public["profile"]["bio"] == "Builds Wikimedia tools."
    assert public["canonicalAuthority"] == {"catalog": "toolhub", "profiles": "toolhub-evolved"}
    search = client.get("/v1/people/?q=ada").get_json()
    assert search["results"][0]["id"] == public_id
    assert search["results"][0]["profile"]["bio"] == "Builds Wikimedia tools."

    hidden = client.put(
        "/v1/me/profile/",
        json={"bio": "Private bio", "visibility": "private"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert hidden.status_code == 200
    assert client.get(f"/v1/people/{public_id}/").get_json()["profile"] == {}
    assert client.get("/v1/people/?q=ada").get_json()["results"][0]["profile"] == {}

    with db.session_scope() as s:
        user = s.get(User, uid)
        assert user is not None
        user.username = "Renamed"
        from backend import people_index

        people_index.link_user(s, user)
        person = s.get(Person, user.person_id)
        assert person.public_id == public_id
        assert person.public_slug == public_slug
        assert person.display_name == "Renamed"
        current_handles = {
            row.value
            for row in s.query(PersonIdentifier).filter_by(
                person_id=person.id,
                namespace=people_index.NS_TOOLHUB_USERNAME,
                is_current=True,
            )
        }
        assert current_handles == {"Renamed"}
        assert s.query(PersonIdentifier).filter_by(value="Ada", is_current=False).count() == 1


def test_unified_claim_api_preserves_history_and_withdraws_revoked_evidence(client, monkeypatch):
    uid = add_user(username="Ada", wm_sub="42")
    sign_in(client, uid)
    canonical = {
        "name": "ada-tool",
        "title": "Ada Tool",
        "author": [{"name": "Ada Lovelace"}],
        "url": "https://example.org/ada-tool",
    }
    monkeypatch.setattr(toolhub, "public_api_get", lambda *_args, **_kwargs: canonical)

    options = client.get("/v1/tools/ada-tool/claim-options/")
    assert options.status_code == 200
    payload = options.get_json()
    assert payload["canonicalAuthority"] == {"catalog": "toolhub", "claims": "toolhub-evolved"}
    assert {row["relationship"] for row in payload["options"]} == {
        sync.PERSON_REL_AUTHOR,
        sync.PERSON_REL_MAINTAINER,
    }
    assert next(row for row in payload["options"] if row["method"] == sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME)[
        "authorNames"
    ] == ["Ada Lovelace"]

    created = client.post(
        "/v1/tools/ada-tool/claims/",
        json={"method": sync.AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME, "authorName": "Ada Lovelace"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert created.status_code == 201
    claim = created.get_json()["claims"][0]
    assert claim["requestedRelationship"] == sync.PERSON_REL_AUTHOR
    assert claim["verificationStatus"] == sync.AUTHOR_CLAIM_UNVERIFIED
    assert claim["isVerified"] is False
    history = client.get("/v1/me/claims/").get_json()["claims"]
    assert [row["id"] for row in history] == [claim["id"]]

    revoked = client.delete(
        f"/v1/claims/{claim['id']}/",
        headers={"X-CSRF-Token": "tok"},
    )
    assert revoked.status_code == 200
    assert revoked.get_json()["claim"]["verificationStatus"] == sync.AUTHOR_CLAIM_REVOKED
    assert revoked.get_json()["claim"]["revokedAt"]
    assert client.get("/v1/me/claims/").get_json()["claims"][0]["verificationStatus"] == sync.AUTHOR_CLAIM_REVOKED
    with db.session_scope() as s:
        assert (
            s.query(ToolRelationshipEvidence)
            .filter_by(tool_name="ada-tool", source=maintainer_index.SOURCE_AUTHOR_CLAIM, withdrawn_at=None)
            .count()
            == 0
        )
        withdrawn = (
            s.query(ToolRelationshipEvidence)
            .filter_by(tool_name="ada-tool", source=maintainer_index.SOURCE_AUTHOR_CLAIM)
            .one()
        )
        assert withdrawn.withdrawn_at is not None
        assert s.query(ToolPersonRelationship).filter_by(tool_name="ada-tool").count() == 0


def test_tool_viewer_context_uses_only_current_relationships_owned_by_the_signed_in_person(client):
    viewer_id = add_user(username="Viewer", wm_sub="viewer-42")
    other_id = add_user(username="Other", wm_sub="other-43")
    with db.session_scope() as s:
        viewer = s.get(User, viewer_id)
        other = s.get(User, other_id)
        viewer_person = people_index.link_user(s, viewer)
        other_person = people_index.link_user(s, other)
        s.add_all(
            [
                ToolPersonRelationship(
                    tool_name="viewer-tool",
                    person_id=viewer_person.id,
                    relationship_type=sync.PERSON_REL_MAINTAINER,
                    verification_status=sync.AUTHOR_CLAIM_UNVERIFIED,
                    confidence=35,
                    evidence_count=1,
                ),
                ToolPersonRelationship(
                    tool_name="viewer-tool",
                    person_id=other_person.id,
                    relationship_type=sync.PERSON_REL_RECORD_OWNER,
                    verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                    confidence=90,
                    evidence_count=1,
                ),
            ]
        )
    assert client.get("/v1/tools/viewer-tool/viewer-context/").status_code == 401

    sign_in(client, viewer_id)
    contributor = client.get("/v1/tools/viewer-tool/viewer-context/")
    assert contributor.status_code == 200
    assert contributor.headers["Cache-Control"] == "private, no-store"
    assert contributor.get_json()["audience"] == people_policy.VIEWER_AUDIENCE_CONTRIBUTOR
    assert contributor.get_json()["qualifyingRelationships"] == []
    assert "evidencePayload" not in dumps(contributor.get_json())

    with db.session_scope() as s:
        viewer = s.get(User, viewer_id)
        relationship = (
            s.query(ToolPersonRelationship)
            .filter_by(
                tool_name="viewer-tool",
                person_id=viewer.person_id,
                relationship_type=sync.PERSON_REL_MAINTAINER,
            )
            .one()
        )
        relationship.verification_status = sync.AUTHOR_CLAIM_VERIFIED
        relationship.expires_at = utcnow() + timedelta(days=1)

    maintainer = client.get("/v1/tools/viewer-tool/viewer-context/").get_json()
    assert maintainer["audience"] == people_policy.VIEWER_AUDIENCE_MAINTAINER
    assert maintainer["qualifyingRelationships"][0]["type"] == sync.PERSON_REL_MAINTAINER

    with db.session_scope() as s:
        viewer = s.get(User, viewer_id)
        s.add(
            ToolPersonRelationship(
                tool_name="viewer-tool",
                person_id=viewer.person_id,
                relationship_type=sync.PERSON_REL_RECORD_OWNER,
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                confidence=90,
                evidence_count=1,
            )
        )

    authority = client.get("/v1/tools/viewer-tool/viewer-context/").get_json()
    assert authority["audience"] == "tool_manager"
    assert authority["qualifyingRelationships"] == [maintainer["qualifyingRelationships"][0]]


def test_unified_claim_api_verifies_toolforge_membership_as_maintainer(client, monkeypatch):
    uid = add_user(username="Schiste", wm_sub="42", wikimedia_global_user_id="160")
    sign_in(client, uid)
    canonical = {
        "name": "toolhub-evolved",
        "title": "Toolhub Evolved",
        "author": [{"name": "Christophe"}],
        "url": "https://toolhub-evolved.toolforge.org",
    }
    monkeypatch.setattr(toolhub, "public_api_get", lambda *_args, **_kwargs: canonical)
    monkeypatch.setattr(v1_api, "PUBLIC_IDENTITY_RESOLVER", identity_resolver("Schiste", "toolhub-evolved"))

    created = client.post(
        "/v1/tools/toolhub-evolved/claims/",
        json={"method": sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER},
        headers={"X-CSRF-Token": "tok"},
    )
    assert created.status_code == 201
    claim = created.get_json()["claims"][0]
    assert claim["requestedRelationship"] == sync.PERSON_REL_MAINTAINER
    assert claim["isVerified"] is True
    assert claim["evidencePayload"]["toolforgeUsername"] == "Schiste"
    assert claim["evidencePayload"]["toolforgeDeveloperUsername"] == "Schiste"
    assert claim["evidencePayload"]["toolforgeShellUsername"] == "schiste"
    assert claim["evidencePayload"]["ldapServiceGroup"] == "tools.toolhub-evolved"
    with db.session_scope() as s:
        relationship = s.query(ToolPersonRelationship).filter_by(tool_name="toolhub-evolved").one()
        assert relationship.relationship_type == sync.PERSON_REL_MAINTAINER
        assert relationship.toolhub_canonical is False
        assert (
            s.query(PersonIdentifier)
            .filter_by(namespace="toolforge_username", normalized_value="schiste")
            .one()
            .person_id
            == relationship.person_id
        )


def test_multiple_evidence_rows_collapse_to_one_relationship():
    db.configure("sqlite://")
    db.init_schema()
    from backend import people_index

    with db.session_scope() as s:
        for source, confidence in (("toolhub_author_metadata", 45), ("signed_toolinfo", 88)):
            people_index.replace_source_evidence(
                s,
                "ada-tool",
                source,
                [
                    {
                        "display_name": "Ada",
                        "toolhub_username": "Ada",
                        "relationship_type": sync.PERSON_REL_AUTHOR,
                        "method": source,
                        "verification_status": sync.AUTHOR_CLAIM_VERIFIED,
                        "confidence": confidence,
                        "toolhub_canonical": source == "toolhub_author_metadata",
                    }
                ],
            )
        relationship = s.query(ToolPersonRelationship).one()
        assert relationship.evidence_count == 2
        assert relationship.confidence == 88
        assert relationship.toolhub_canonical is True
        assert s.query(ToolRelationshipEvidence).count() == 2


def test_stable_toolhub_id_never_inherits_the_previous_owner_of_a_reused_handle():
    db.configure("sqlite://")
    db.init_schema()
    from backend import people_index

    with db.session_scope() as s:
        previous = people_index.ensure_person(s, display_name="Alice", toolhub_username="Alice")
        current = people_index.ensure_person(
            s,
            display_name="New Alice",
            toolhub_user_id="42",
            toolhub_username="Alice",
        )

        assert current.id != previous.id
        stable = s.query(PersonIdentifier).filter_by(namespace="toolhub_user_id", normalized_value="42").one()
        handle = s.query(PersonIdentifier).filter_by(namespace="toolhub_username", normalized_value="alice").one()
        assert stable.person_id == current.id
        assert handle.person_id == current.id


def test_display_only_observations_are_scoped_instead_of_globally_merged():
    db.configure("sqlite://")
    db.init_schema()
    from backend import people_index

    observation = [{"display_name": "Alex", "relationship_type": sync.PERSON_REL_AUTHOR}]
    with db.session_scope() as s:
        people_index.replace_source_evidence(s, "first-tool", "toolhub_author_metadata", observation)
        people_index.replace_source_evidence(s, "second-tool", "toolhub_author_metadata", observation)
        first_ids = {row.id for row in s.query(UnresolvedAttributionEvidence).all()}

        assert len(first_ids) == 2
        people_index.replace_source_evidence(s, "first-tool", "toolhub_author_metadata", observation)
        assert {row.id for row in s.query(UnresolvedAttributionEvidence).all()} == first_ids

        assert people_index.find_people(s, "Alex") == []
        assert s.query(Person).count() == 0
        assert people_index.unresolved_attributions(s, "Alex") == [
            {
                "label": "Alex",
                "identityStatus": "unresolved_attribution",
                "attributionCount": 2,
                "toolCount": 2,
                "evidenceCount": 2,
                "bestConfidence": 0,
                "relationshipTypes": [sync.PERSON_REL_AUTHOR],
                "relationshipBreakdown": [
                    {
                        "type": sync.PERSON_REL_AUTHOR,
                        "status": "unverified",
                        "toolCount": 2,
                        "evidenceCount": 2,
                        "bestConfidence": 0,
                    }
                ],
            }
        ]

        summary = people_index.public_people_summary(s, "first-tool")
        assert summary["people"] == []
        assert summary["counts"][sync.PERSON_REL_AUTHOR] == 0
        assert summary["unresolvedCounts"][sync.PERSON_REL_AUTHOR] == 1
        assert summary["unresolvedAttributions"][0]["label"] == "Alex"


def test_people_directory_publishes_structured_handles_but_not_display_labels():
    db.configure("sqlite://")
    db.init_schema()
    from backend import people_index

    with db.session_scope() as s:
        s.add(Person(canonical_key="display:orphan", display_name="Orphan", identity_quality="display_name"))
        people_index.replace_source_evidence(
            s,
            "visible-tool",
            "toolhub_author_metadata",
            [{"display_name": "Visible", "relationship_type": sync.PERSON_REL_AUTHOR}],
        )
        people_index.replace_source_evidence(
            s,
            "handle-tool",
            "toolhub_author_metadata",
            [
                {
                    "display_name": "Handle backed",
                    "toolhub_username": "handle-backed",
                    "relationship_type": sync.PERSON_REL_AUTHOR,
                }
            ],
        )

        assert [item["displayName"] for item in people_index.find_people(s, "")] == ["Handle backed"]
        assert {item["label"] for item in people_index.unresolved_attributions(s)} == {"Visible"}


def test_people_directory_endpoint_separates_unresolved_attributions(client):
    with db.session_scope() as s:
        from backend import people_index

        people_index.replace_source_evidence(
            s,
            "display-tool",
            "toolhub_author_metadata",
            [{"display_name": "Alex", "relationship_type": sync.PERSON_REL_AUTHOR}],
        )
        people_index.replace_source_evidence(
            s,
            "handle-tool",
            "toolhub_author_metadata",
            [
                {
                    "display_name": "Alex Maintainer",
                    "wiki_username": "alex-maintainer",
                    "relationship_type": sync.PERSON_REL_MAINTAINER,
                }
            ],
        )

    data = client.get("/v1/people/?q=alex").get_json()
    assert data["count"] == 1
    assert [item["displayName"] for item in data["results"]] == ["Alex Maintainer"]
    assert "unresolvedAttributions" not in data

    unresolved = client.get("/v1/people/attributions/?q=alex").get_json()
    assert unresolved["count"] == 1
    assert {item["label"] for item in unresolved["results"]} == {"Alex"}


def _add_directory_person(
    session,
    *,
    display_name,
    stable_id,
    tool_name,
    role=sync.PERSON_REL_AUTHOR,
    status=sync.AUTHOR_CLAIM_UNVERIFIED,
    confidence=0,
    activity="unknown",
    expires_at=None,
    toolhub_username="",
):
    from backend import people_index

    person = people_index.ensure_person(
        session,
        display_name=display_name,
        toolhub_user_id=stable_id,
        toolhub_username=toolhub_username,
    )
    session.flush()
    session.add(
        ToolPersonRelationship(
            tool_name=tool_name,
            person_id=person.id,
            relationship_type=role,
            verification_status=status,
            confidence=confidence,
            evidence_count=1,
            expires_at=expires_at,
        )
    )
    session.add(
        PersonActivitySummary(
            person_id=person.id,
            related_tool_count=1,
            verified_tool_count=1 if status == sync.AUTHOR_CLAIM_VERIFIED else 0,
            activity_status=activity,
        )
    )
    return person


def test_people_directory_returns_real_totals_and_stable_pages(client):
    with db.session_scope() as s:
        for index in range(55):
            _add_directory_person(
                s,
                display_name=f"Person {index:02d}",
                stable_id=f"directory-{index}",
                tool_name=f"tool-{index}",
            )

    first = client.get("/v1/people/?page_size=24&ordering=name").get_json()
    second = client.get("/v1/people/?page=2&page_size=24&ordering=name").get_json()

    assert first["count"] == 55
    assert first["pageCount"] == 3
    assert len(first["results"]) == 24
    assert first["previous"] is None
    assert "page=2" in first["next"]
    assert [person["displayName"] for person in second["results"][:2]] == ["Person 24", "Person 25"]
    assert "page=1" in second["previous"]
    assert "page=3" in second["next"]


def test_people_directory_prioritizes_exact_stable_ids_and_handles(client):
    with db.session_scope() as s:
        _add_directory_person(
            s,
            display_name="42",
            stable_id="display-42",
            tool_name="display-tool",
        )
        _add_directory_person(
            s,
            display_name="Identifier Match",
            stable_id="42",
            tool_name="identifier-tool",
        )
        _add_directory_person(
            s,
            display_name="Magnus",
            stable_id="display-magnus",
            tool_name="magnus-display-tool",
        )
        _add_directory_person(
            s,
            display_name="Structured Handle",
            stable_id="handle-magnus",
            toolhub_username="Magnus",
            tool_name="magnus-handle-tool",
        )

    stable = client.get("/v1/people/?q=42").get_json()
    handle = client.get("/v1/people/?q=Magnus").get_json()

    assert stable["results"][0]["displayName"] == "Identifier Match"
    assert handle["results"][0]["displayName"] == "Structured Handle"


def test_people_directory_combines_role_verification_activity_and_project_filters(client):
    now = utcnow()
    with db.session_scope() as s:
        matching = _add_directory_person(
            s,
            display_name="Matching Maintainer",
            stable_id="matching",
            tool_name="matching-tool",
            role=sync.PERSON_REL_MAINTAINER,
            status=sync.AUTHOR_CLAIM_VERIFIED,
            confidence=95,
            activity="active",
            expires_at=now + timedelta(days=1),
        )
        s.add_all(
            [
                ToolPersonRelationship(
                    tool_name="matching-secondary-tool",
                    person_id=matching.id,
                    relationship_type=sync.PERSON_REL_MAINTAINER,
                    verification_status=sync.AUTHOR_CLAIM_UNVERIFIED,
                    evidence_count=1,
                ),
                ToolPersonRelationship(
                    tool_name="matching-tool",
                    person_id=matching.id,
                    relationship_type=sync.PERSON_REL_RECORD_OWNER,
                    verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                    confidence=90,
                    evidence_count=1,
                    expires_at=now + timedelta(days=1),
                ),
            ]
        )
        _add_directory_person(
            s,
            display_name="Wrong Project",
            stable_id="wrong-project",
            tool_name="wrong-project-tool",
            role=sync.PERSON_REL_MAINTAINER,
            status=sync.AUTHOR_CLAIM_VERIFIED,
            activity="active",
        )
        _add_directory_person(
            s,
            display_name="Unverified Maintainer",
            stable_id="unverified",
            tool_name="unverified-tool",
            role=sync.PERSON_REL_MAINTAINER,
            activity="active",
        )
        _add_directory_person(
            s,
            display_name="Expired Maintainer",
            stable_id="expired",
            tool_name="expired-tool",
            role=sync.PERSON_REL_MAINTAINER,
            status=sync.AUTHOR_CLAIM_VERIFIED,
            activity="active",
            expires_at=now - timedelta(seconds=1),
        )
        for tool_name in ("matching-tool", "unverified-tool", "expired-tool"):
            s.add(CatalogFacetValue(tool_name=tool_name, field="wiki", value="wikidata.org", label="Wikidata"))
        matching_id = matching.public_id

    filtered = client.get(
        "/v1/people/?role=maintainer&verification=verified&activity=active&project=wikidata.org"
    ).get_json()
    renewal = client.get("/v1/people/?verification=renewal_needed").get_json()

    assert [person["id"] for person in filtered["results"]] == [matching_id]
    assert filtered["results"][0]["relationshipSummary"]["verifiedTypes"] == [sync.PERSON_REL_MAINTAINER]
    assert filtered["results"][0]["relationshipSummary"]["toolCountsByType"] == {
        sync.PERSON_REL_AUTHOR: 0,
        sync.PERSON_REL_MAINTAINER: 2,
    }
    assert filtered["results"][0]["relationshipSummary"]["verifiedToolCountsByType"] == {
        sync.PERSON_REL_AUTHOR: 0,
        sync.PERSON_REL_MAINTAINER: 1,
    }
    assert renewal["results"] == []
    assert client.get("/v1/people/?role=record_owner").status_code == 400


def test_unresolved_attributions_have_independent_pagination(client):
    from backend import people_index

    with db.session_scope() as s:
        for index in range(25):
            people_index.replace_source_evidence(
                s,
                f"unresolved-tool-{index}",
                "toolhub_author_metadata",
                [{"display_name": f"Unresolved {index:02d}", "relationship_type": sync.PERSON_REL_AUTHOR}],
            )

    page = client.get("/v1/people/attributions/?q=Unresolved&page=2&page_size=10").get_json()

    assert page["count"] == 25
    assert page["pageCount"] == 3
    assert len(page["results"]) == 10
    assert page["results"][0]["label"] == "Unresolved 10"
    assert "page=3" in page["next"]


@pytest.mark.parametrize(
    "path",
    (
        "/v1/people/?page=0",
        "/v1/people/?page_size=nope",
        "/v1/people/?role=administrator",
        "/v1/people/?verification=old",
        "/v1/people/?activity=recent",
        "/v1/people/?ordering=random",
        "/v1/people/attributions/?role=administrator",
    ),
)
def test_people_directory_rejects_invalid_parameters(client, path):
    assert client.get(path).status_code == 400


def test_legacy_people_resolver_requires_one_unique_exact_handle(client):
    from backend import people_index, people_reconcile

    with db.session_scope() as s:
        reconciliation_run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(reconciliation_run)
        s.flush()
        resolved = people_index.ensure_person(
            s,
            display_name="Ada Lovelace",
            toolhub_user_id="1",
            toolhub_username="Ada",
        )
        first_same_name = people_index.ensure_person(
            s,
            display_name="Shared Name",
            toolhub_user_id="2",
            toolforge_username="first-handle",
        )
        second_same_name = people_index.ensure_person(
            s,
            display_name="Shared Name",
            toolhub_user_id="3",
            wiki_username="second-handle",
        )
        cross_namespace_one = people_index.ensure_person(
            s,
            display_name="Cross One",
            toolhub_user_id="4",
            toolforge_username="shared-handle",
        )
        cross_namespace_two = people_index.ensure_person(
            s,
            display_name="Cross Two",
            toolhub_user_id="5",
            wiki_username="shared-handle",
        )
        canonical_magnus = people_index.ensure_person(
            s,
            display_name="Magnus Manske",
            toolhub_user_id="152",
            toolhub_username="Magnus Manske",
        )
        mapped_magnus_source = people_index.ensure_person(
            s,
            display_name="Magnus Manske",
            toolforge_username="Magnus Manske",
            source="toolforge_toolsadmin",
        )
        s.add(
            PersonReconciliationMapping(
                run_id=reconciliation_run.id,
                source_person_id=mapped_magnus_source.id,
                target_person_id=canonical_magnus.id,
                source_key=mapped_magnus_source.canonical_key,
                target_key=canonical_magnus.canonical_key,
                decision=people_reconcile.MAPPING_AUTO_LINK,
                reason="same_verified_structured_handle",
                confidence=90,
            )
        )
        people_index.replace_source_evidence(
            s,
            "unresolved-tool",
            "source",
            [{"display_name": "Magnus Manske", "relationship_type": sync.PERSON_REL_AUTHOR}],
        )
        resolved_public_id = resolved.public_id
        same_name_ids = {first_same_name.public_id, second_same_name.public_id}
        cross_namespace_ids = {cross_namespace_one.public_id, cross_namespace_two.public_id}
        canonical_magnus_id = canonical_magnus.public_id

    exact = client.get("/v1/people/resolve/?handle=ada").get_json()
    assert exact["status"] == "resolved"
    assert exact["matchType"] == "handle"
    assert exact["person"]["id"] == resolved_public_id
    assert exact["person"]["matchedNamespaces"] == ["toolhub_username"]

    display = client.get("/v1/people/resolve/?handle=Shared%20Name").get_json()
    assert display["status"] == "ambiguous"
    assert display["matchType"] == "display_name"
    assert {person["id"] for person in display["candidates"]} == same_name_ids

    cross_namespace = client.get("/v1/people/resolve/?handle=shared-handle").get_json()
    assert cross_namespace["status"] == "ambiguous"
    assert cross_namespace["matchType"] == "handle"
    assert {person["id"] for person in cross_namespace["candidates"]} == cross_namespace_ids

    canonicalized = client.get("/v1/people/resolve/?handle=Magnus%20Manske").get_json()
    assert canonicalized["status"] == "resolved"
    assert canonicalized["person"]["id"] == canonical_magnus_id
    assert [candidate["id"] for candidate in canonicalized["candidates"]] == [canonical_magnus_id]
    assert canonicalized["unresolvedAttributions"][0]["label"] == "Magnus Manske"

    attribution = client.get("/v1/people/resolve/?handle=Magnus%20Manske&context=attribution").get_json()
    assert attribution["status"] == "resolved"
    assert attribution["matchType"] == "handle"
    assert attribution["person"]["id"] == canonical_magnus_id
    assert attribution["unresolvedAttributions"][0]["label"] == "Magnus Manske"

    assert client.get("/v1/people/resolve/?handle=Nobody").get_json()["status"] == "not_found"
    assert client.get("/v1/people/resolve/").status_code == 400


def test_operator_can_triage_people_conflicts_without_merging(client):
    with db.session_scope() as s:
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        conflict = PersonReconciliationConflict(
            run_id=run.id,
            conflict_type="ambiguous_display_name",
            value="alex",
            details={"candidateCount": 2, "stableEvidenceAvailable": True},
        )
        s.add(conflict)
        s.flush()
        conflict_id = conflict.id

    assert client.get("/v1/moderation/people-conflicts/").status_code == 401
    reviewer_id = add_user(username="Reviewer", wm_sub="reviewer", role=authz.ROLE_REVIEWER)
    sign_in(client, reviewer_id)
    assert client.get("/v1/moderation/people-conflicts/").status_code == 403

    admin_id = add_user(username="Operator", wm_sub="operator", role=authz.ROLE_ADMIN)
    sign_in(client, admin_id)
    pending = client.get("/v1/moderation/people-conflicts/").get_json()
    assert pending["count"] == 1
    assert pending["results"][0]["details"]["stableEvidenceAvailable"] is True

    response = client.put(
        f"/v1/moderation/people-conflicts/{conflict_id}/",
        json={"status": "resolved", "reviewNotes": "Stable account evidence checked."},
        headers={"X-CSRF-Token": "tok"},
    )
    assert response.status_code == 200
    assert response.get_json()["conflict"]["status"] == "resolved"
    assert client.get("/v1/moderation/people-conflicts/").get_json()["count"] == 0
    assert client.get("/v1/moderation/people-conflicts/?status=resolved").get_json()["count"] == 1


def test_operator_approval_moves_evidence_without_changing_role_and_survives_refresh(client):
    from backend import people_index, people_reconcile

    with db.session_scope() as s:
        people_index.replace_source_evidence(
            s,
            "mix-n-match",
            "untrusted_structured_source",
            [
                {
                    "display_name": "Magnus Manske",
                    "wiki_username": "Magnus Manske",
                    "relationship_type": sync.PERSON_REL_AUTHOR,
                    "method": "toolhub_author_metadata",
                }
            ],
        )
        source = s.query(Person).filter_by(identity_quality="handle").one()
        target = people_index.ensure_person(
            s,
            display_name="Magnus Manske",
            toolhub_user_id="152",
            wikimedia_global_user_id="160",
            toolhub_username="Magnus Manske",
        )
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        mapping = PersonReconciliationMapping(
            run_id=run.id,
            source_person_id=source.id,
            target_person_id=target.id,
            source_key=source.canonical_key,
            target_key=target.canonical_key,
            decision="candidate",
            reason="exact_toolhub_username_and_toolforge_membership",
            confidence=90,
            evidence={"toolNames": ["mix-n-match"]},
        )
        s.add(mapping)
        s.flush()
        mapping_id = mapping.id
        source_id = source.id
        target_id = target.id

    assert client.get("/v1/moderation/people-candidates/").status_code == 401
    admin_id = add_user(username="Operator", wm_sub="operator", role=authz.ROLE_ADMIN)
    sign_in(client, admin_id)
    queued = client.get("/v1/moderation/people-candidates/").get_json()
    assert queued["count"] == 1
    assert queued["results"][0]["confidence"] == 90

    approved = client.put(
        f"/v1/moderation/people-candidates/{mapping_id}/",
        json={"decision": "approved", "reviewNotes": "LDAP membership corroborated."},
        headers={"X-CSRF-Token": "tok"},
    )
    assert approved.status_code == 200
    assert approved.get_json()["affectedTools"] == 1
    with db.session_scope() as s:
        evidence = s.query(ToolRelationshipEvidence).one()
        relationship = s.query(ToolPersonRelationship).one()
        assert evidence.person_id == target_id
        assert relationship.person_id == target_id
        assert relationship.relationship_type == sync.PERSON_REL_AUTHOR
        assert s.get(PersonReconciliationMapping, mapping_id).decision == "approved"

        people_index.replace_source_evidence(
            s,
            "mix-n-match",
            "untrusted_structured_source",
            [
                {
                    "display_name": "Magnus Manske",
                    "wiki_username": "Magnus Manske",
                    "relationship_type": sync.PERSON_REL_AUTHOR,
                    "method": "toolhub_author_metadata",
                }
            ],
        )
        assert s.query(ToolRelationshipEvidence).filter_by(person_id=source_id).count() == 1
        assert people_reconcile.apply_durable_mappings_for_tool(s, "mix-n-match") == 1
        people_index.resolve_tool_relationships(s, "mix-n-match")
        assert s.query(ToolRelationshipEvidence).filter_by(person_id=source_id).count() == 0
        assert s.query(ToolRelationshipEvidence).filter_by(person_id=target_id).count() == 1

    directory = client.get("/v1/people/?q=Magnus%20Manske").get_json()
    assert directory["count"] == 1
    assert client.get("/v1/people/attributions/?q=Magnus%20Manske").get_json()["count"] == 0
    assert {item["namespace"] for item in directory["results"][0]["identifiers"]} == {
        "toolhub_user_id",
        "toolhub_username",
        "wikimedia_global_user_id",
    }
    tool_people = client.get("/v1/people/tools/mix-n-match/").get_json()
    assert len(tool_people["people"]) == 1
    assert tool_people["unresolvedAttributions"] == []
    assert {role["type"] for role in tool_people["people"][0]["relationships"]} == {sync.PERSON_REL_AUTHOR}


def test_operator_split_decision_is_durable_and_does_not_move_evidence(client):
    from backend import people_index

    with db.session_scope() as s:
        people_index.replace_source_evidence(
            s,
            "same-label-tool",
            "source",
            [
                {
                    "display_name": "Alex",
                    "wiki_username": "Alex",
                    "relationship_type": sync.PERSON_REL_AUTHOR,
                }
            ],
        )
        source = s.query(Person).one()
        target = people_index.ensure_person(s, display_name="Alex", toolhub_user_id="77")
        run = PersonReconciliationRun(mode="apply", status="completed")
        s.add(run)
        s.flush()
        mapping = PersonReconciliationMapping(
            run_id=run.id,
            source_person_id=source.id,
            target_person_id=target.id,
            source_key=source.canonical_key,
            target_key=target.canonical_key,
            decision="candidate",
        )
        s.add(mapping)
        s.flush()
        mapping_id = mapping.id
        source_id = source.id

    admin_id = add_user(username="Operator", wm_sub="operator", role=authz.ROLE_ADMIN)
    sign_in(client, admin_id)
    response = client.put(
        f"/v1/moderation/people-candidates/{mapping_id}/",
        json={"decision": "split", "reviewNotes": "Different human."},
        headers={"X-CSRF-Token": "tok"},
    )

    assert response.status_code == 200
    assert response.get_json()["affectedTools"] == 0
    with db.session_scope() as s:
        assert s.get(PersonReconciliationMapping, mapping_id).decision == "split"
        assert s.query(ToolRelationshipEvidence).one().person_id == source_id


def test_permanent_evidence_keeps_a_collapsed_relationship_permanent():
    db.configure("sqlite://")
    db.init_schema()
    from backend import people_index

    base = {
        "display_name": "Ada",
        "toolhub_username": "Ada",
        "relationship_type": sync.PERSON_REL_MAINTAINER,
    }
    with db.session_scope() as s:
        people_index.replace_source_evidence(s, "ada-tool", "permanent", [base])
        people_index.replace_source_evidence(
            s,
            "ada-tool",
            "temporary",
            [base | {"expires_at": utcnow() + timedelta(days=1)}],
        )

        assert s.query(ToolPersonRelationship).one().expires_at is None


def test_removing_last_relationship_invalidates_the_person_activity_summary():
    db.configure("sqlite://")
    db.init_schema()
    from backend import people_index

    with db.session_scope() as s:
        people_index.replace_source_evidence(
            s,
            "ada-tool",
            "claim",
            [
                {
                    "display_name": "Ada",
                    "toolhub_username": "Ada",
                    "relationship_type": sync.PERSON_REL_MAINTAINER,
                }
            ],
        )
        person_id = s.query(Person).one().id
        assert s.get(PersonActivitySummary, person_id).related_tool_count == 1

        people_index.replace_source_evidence(s, "ada-tool", "claim", [])

        assert s.get(PersonActivitySummary, person_id).related_tool_count == 0


def test_source_analysis_uses_evolved_maintainer_context_for_named_tools(client):
    uid = add_user(username="Ada")
    sign_in(client, uid)
    with db.session_scope() as s:
        s.add(
            ToolAuthorClaim(
                tool_name="ada-tool",
                author_name="Ada Lovelace",
                toolhub_username="Ada",
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                verification_method=sync.AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
            )
        )

    resp = client.post(
        "/v1/source-analysis/",
        json={
            "toolName": "ada-tool",
            "files": [{"path": "README.md", "content": "Tool docs for en.wikipedia.org."}],
        },
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 201
    report = resp.get_json()["sourceAnalysis"]["report"]
    context = report["repositoryContext"]
    assert context["maintainers"]["source"] == "evolved-people-index"
    assert context["maintainers"]["maintainerCount"] == 1
    assert context["maintainerActivity"]["status"] == "unknown"
    assert report["summary"]["maintainerStatus"] == "unknown"


def test_me_tools_requires_login(client):
    assert client.get("/v1/me/tools/").status_code == 401


def test_me_tools_reads_the_canonical_relationship_graph_without_upstream_search(client, monkeypatch):
    uid = add_user(username="Ada", wikimedia_global_user_id="160")
    sign_in(client, uid)
    with db.session_scope() as s:
        user = s.get(User, uid)
        person = people_index.link_user(s, user)
        now = utcnow()
        s.add(
            CanonicalToolCache(
                tool_name="ada-tool",
                record={"name": "ada-tool", "title": "Ada Tool"},
                fetched_at=now,
                expires_at=now,
                stale_until=now,
            )
        )
        s.add(
            ToolPersonRelationship(
                tool_name="ada-tool",
                person_id=person.id,
                relationship_type=sync.PERSON_REL_MAINTAINER,
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                confidence=100,
                evidence_count=1,
            )
        )

    monkeypatch.setattr(
        toolhub,
        "public_api_get",
        lambda *_args, **_kwargs: pytest.fail("account tool reads must not search upstream"),
    )
    response = client.get("/v1/me/tools/")
    data = response.get_json()

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert data["counts"] == {"verified": 1, "possible": 0}
    assert data["verified"][0]["tool"]["name"] == "ada-tool"
    assert data["verified"][0]["relationships"][0]["requestedRelationship"] == sync.PERSON_REL_MAINTAINER
    assert data["searchTerms"] == ["canonical-relationship-graph"]


def test_overlay_get_requires_login(client):
    assert client.get("/v1/overlay/").status_code == 401


def test_overlay_get_rejects_stale_policy_user(client):
    sign_in(client, 999)
    resp = client.get("/v1/overlay/")
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "sign in required"}


def test_put_requires_login(client):
    assert client.put("/v1/overlay/favorites", json=[]).status_code == 401


def test_put_requires_csrf(client):
    uid = add_user()
    sign_in(client, uid)
    assert client.put("/v1/overlay/favorites", json=[]).status_code == 403  # missing header
    assert put_overlay(client, "favorites", [], csrf="wrong").status_code == 403  # mismatch


def test_put_rejects_csrf_when_session_holds_no_usable_token(client):
    uid = add_user()
    for stored in (None, "", 1234):  # absent, empty, and non-string all fail closed
        sign_in(client, uid)
        with client.session_transaction() as sess:
            sess["csrf"] = stored
        assert put_overlay(client, "favorites", [], csrf="tok").status_code == 403


def test_rate_limit(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    clock = {"t": 100.0}
    monkeypatch.setattr(security.time, "monotonic", lambda: clock["t"])
    for _ in range(security.WRITE_LIMIT):
        assert put_overlay(client, "favorites", ["a"]).status_code == 200
    assert put_overlay(client, "favorites", ["a"]).status_code == 429
    clock["t"] += security.WRITE_WINDOW_SECONDS + 1  # window expires → pruning branch
    assert put_overlay(client, "favorites", ["a"]).status_code == 200


def test_rate_limit_prunes_stale_entries_for_active_user(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    clock = {"t": 100.0}
    monkeypatch.setattr(security.time, "monotonic", lambda: clock["t"])
    security._writes.last_sweep = clock["t"]
    security._writes.times[uid] = deque([clock["t"] - security.WRITE_WINDOW_SECONDS - 1])
    assert put_overlay(client, "favorites", ["a"]).status_code == 200
    assert list(security._writes.times[uid]) == [clock["t"]]


def test_rate_limit_table_evicts_idle_users(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    clock = {"t": 100.0}
    monkeypatch.setattr(security.time, "monotonic", lambda: clock["t"])
    assert put_overlay(client, "favorites", ["a"]).status_code == 200
    security._writes.times[999] = deque()  # an entry whose window already drained
    assert uid in security._writes.times
    clock["t"] += security.WRITE_WINDOW_SECONDS + 1  # idle past the window → swept
    assert put_overlay(client, "favorites", ["a"]).status_code == 200
    assert 999 not in security._writes.times
    assert list(security._writes.times) == [uid]  # only the active writer is retained


def test_sign_out_strands_session_cookies_issued_before_it(client, app):
    uid = add_user()
    sign_in(client, uid)
    assert put_overlay(client, "favorites", ["a"]).status_code == 200
    stolen = app.test_client()  # a copy of the cookie taken while it was valid
    sign_in(stolen, uid)
    client.post("/oauth/logout", data={"csrf": "tok"})
    assert put_overlay(stolen, "favorites", ["b"]).status_code == 401  # epoch bumped → stale
    assert stolen.get("/v1/user/").get_json() == {"authenticated": False}


def test_policy_denial_blocks_private_overlay_writes(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    monkeypatch.setattr(authz, "can", lambda *_args, **_kwargs: False)
    resp = put_overlay(client, "favorites", ["a"])
    assert resp.status_code == 403
    assert resp.get_json() == {"error": "not allowed"}
    with db.session_scope() as s:
        assert s.query(Favorite).count() == 0
        assert s.query(ToolList).count() == 0
        assert s.query(ToolRecord).count() == 0
        assert s.query(CrawlerUrl).count() == 0


def test_policy_denial_blocks_public_evolved_writes(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    monkeypatch.setattr(authz, "can", lambda *_args, **_kwargs: False)

    assert (
        client.post("/v1/tools/alpha/events/", json={"eventType": "view"}, headers={"X-CSRF-Token": "tok"}).status_code
        == 403
    )
    assert client.post("/v1/tools/alpha/thanks/", headers={"X-CSRF-Token": "tok"}).status_code == 403
    assert (
        client.put(
            "/v1/tools/alpha/health-target/",
            json={"url": "https://alpha.example/healthz"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/v1/tools/alpha/media/",
            json={"url": "https://img.example/shot.png", "license": "CC0", "source": "Maintainer"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 403
    )
    with db.session_scope() as s:
        assert s.query(ToolEvent).count() == 0
        assert s.query(ToolThanks).count() == 0
        assert s.query(ToolHealthTarget).count() == 0
        assert s.query(ToolMedia).count() == 0


# ---- overlay round-trips ---------------------------------------------------


def test_overlay_roundtrip_all_keys(client):
    uid = add_user()
    sign_in(client, uid)
    assert put_overlay(client, "favorites", ["tool-b", "tool-a", "tool-b"]).status_code == 200  # dupe dropped
    lists = [
        {
            "id": "demo-1",
            "title": "My list",
            "description": "d",
            "tools": ["tool-a"],
            "modified": "2026-07-25T10:00:00Z",
        }
    ]
    assert put_overlay(client, "lists", lists).status_code == 200
    crawler_urls = [{"url": "https://example.org/t.json", "added": "bogus-date"}]
    assert put_overlay(client, "crawlerUrls", crawler_urls).status_code == 200
    assert put_overlay(client, "toolEdits", {"tool-a": {"title": "New"}}).status_code == 200
    assert put_overlay(client, "toolAnnos", {"tool-a": {"audiences": ["editors"]}}).status_code == 200
    new_tool = {"title": "T", "description": "A tool", "url": "https://example.org", "keywords": ["k"]}
    assert put_overlay(client, "toolNew", {"my-tool": new_tool}).status_code == 200
    revs = [{"id": "d1", "timestamp": "2026-07-25T10:00:00Z", "comment": "Demo: edited"}]
    assert put_overlay(client, "revisions", revs).status_code == 200
    assert put_overlay(client, "revisions", revs).status_code == 200  # idempotent (known id skipped)
    assert put_overlay(client, "auditlogs", [{"id": "d1", "action": "edited"}]).status_code == 200

    data = client.get("/v1/overlay/").get_json()
    assert data["favorites"] == ["tool-b", "tool-a"]
    assert data["lists"][0]["id"] == "demo-1"
    assert data["lists"][0]["modified"] == "2026-07-25T10:00:00Z"
    assert data["lists"][0]["syncStatus"] == "local_draft"
    assert data["crawlerUrls"][0]["url"] == "https://example.org/t.json"
    assert data["crawlerUrls"][0]["syncStatus"] == "local_draft"
    assert data["toolEdits"]["tool-a"]["title"] == "New"
    assert data["toolEdits"]["tool-a"]["syncStatus"] == "local_draft"
    assert data["toolAnnos"]["tool-a"]["audiences"] == ["editors"]
    assert data["toolAnnos"]["tool-a"]["syncStatus"] == "local_draft"
    assert data["toolNew"]["my-tool"]["title"] == "T"
    assert data["toolNew"]["my-tool"]["visibility"] == "private"
    assert data["toolNew"]["my-tool"]["reviewStatus"] == "pending"
    assert data["revisions"] == revs
    assert data["auditlogs"][0]["action"] == "edited"
    with db.session_scope() as s:
        for model in (Favorite, ToolList, CrawlerUrl, ToolOverlay, ToolRecord, ActivityRow):
            assert {row.created_by_user_id for row in s.query(model)} == {uid}


def test_overlay_sync_metadata_roundtrip_and_public_crawler_records(client):
    uid = add_user()
    sign_in(client, uid)
    assert (
        put_overlay(
            client,
            "lists",
            [
                {
                    "id": "official-list",
                    "title": "Official list",
                    "description": "from Toolhub",
                    "tools": ["crawler-tool"],
                    "modified": "2026-07-26T10:00:00Z",
                    "officialId": "77",
                    "syncStatus": "official",
                    "lastError": "  stale cache  ",
                    "toolhubResponse": {"id": 77},
                    "validationErrors": [{"field": "title"}],
                }
            ],
        ).status_code
        == 200
    )
    assert (
        put_overlay(
            client,
            "crawlerUrls",
            [
                {
                    "url": "https://example.org/toolinfo.json",
                    "added": "2026-07-26T11:00:00Z",
                    "id": "88",
                    "syncStatus": "official",
                    "toolhubResponse": {"id": 88},
                    "validationErrors": [{"field": "url"}],
                }
            ],
        ).status_code
        == 200
    )
    assert (
        put_overlay(
            client,
            "toolEdits",
            {
                "crawler-tool": {
                    "title": "Overlay title",
                    "baseRevision": "rev-1",
                    "fieldStatuses": {"title": "accepted"},
                    "reviewStatus": "approved",
                    "lastError": "needs merge",
                    "toolhubResponse": {"message": "bad"},
                    "validationErrors": [{"field": "title"}],
                }
            },
        ).status_code
        == 200
    )
    assert (
        put_overlay(
            client,
            "toolNew",
            {
                "crawler-tool": {
                    "title": "Crawler Tool",
                    "description": "Public via crawler origin",
                    "url": "https://crawler.example",
                    "origin": "crawler",
                    "officialName": "crawler-tool-official",
                    "toolhubResponse": {"id": 99},
                    "validationErrors": [{"field": "url"}],
                    "lastError": "local warning",
                }
            },
        ).status_code
        == 200
    )
    data = client.get("/v1/overlay/").get_json()
    assert data["lists"][0]["officialId"] == 77
    assert data["lists"][0]["lastSyncedAt"] == "2026-07-26T10:00:00Z"
    assert data["lists"][0]["lastError"] == "stale cache"
    assert data["lists"][0]["toolhubResponse"] == {"id": 77}
    assert data["lists"][0]["validationErrors"] == [{"field": "title"}]
    assert data["crawlerUrls"][0]["officialId"] == 88
    assert data["crawlerUrls"][0]["id"] == 88
    assert data["crawlerUrls"][0]["lastSyncedAt"] == "2026-07-26T11:00:00Z"
    assert data["crawlerUrls"][0]["toolhubResponse"] == {"id": 88}
    assert data["crawlerUrls"][0]["validationErrors"] == [{"field": "url"}]
    assert data["toolEdits"]["crawler-tool"]["baseRevision"] == "rev-1"
    assert data["toolEdits"]["crawler-tool"]["fieldStatuses"] == {"title": "accepted"}
    assert data["toolEdits"]["crawler-tool"]["reviewStatus"] == "open"
    assert data["toolEdits"]["crawler-tool"]["toolhubResponse"] == {"message": "bad"}
    assert data["toolEdits"]["crawler-tool"]["validationErrors"] == [{"field": "title"}]
    assert data["toolNew"]["crawler-tool"]["officialName"] == "crawler-tool-official"
    assert data["toolNew"]["crawler-tool"]["visibility"] == "public"
    assert data["toolNew"]["crawler-tool"]["source"] == "local"
    assert data["toolNew"]["crawler-tool"]["reviewStatus"] == "pending"
    assert data["toolNew"]["crawler-tool"]["toolhubResponse"] == {"id": 99}
    assert data["toolNew"]["crawler-tool"]["validationErrors"] == [{"field": "url"}]
    assert client.get("/v1/search/tools/?q=crawler").get_json()["count"] == 0
    assert client.get("/toolinfo.json").get_json() == []
    with db.session_scope() as s:
        row = s.execute(select(ToolRecord).where(ToolRecord.tool_name == "crawler-tool")).scalar_one()
        row.review_status = "approved"
    assert client.get("/v1/search/tools/?q=crawler").get_json()["count"] == 1
    assert client.get("/toolinfo.json").get_json()[0]["name"] == "toolhub-evolved-crawler-tool"


def test_local_overlays_cannot_replace_canonical_tool_identity(client):
    uid = add_user()
    sign_in(client, uid)
    patch = {
        "live-tool": {
            "name": "local-shadow",
            "origin": "api",
            "description": "local note",
            "source": "local",
            "createdByUserId": 999,
            "deletedAt": "2026-07-26T12:00:00Z",
        }
    }
    assert put_overlay(client, "toolEdits", patch).status_code == 200
    data = client.get("/v1/overlay/").get_json()["toolEdits"]["live-tool"]
    assert data["description"] == "local note"
    assert data["source"] == "local"
    assert "name" not in data
    assert "origin" not in data
    assert "createdByUserId" not in data
    assert "deletedAt" not in data
    with db.session_scope() as s:
        stored = s.query(ToolOverlay).filter_by(tool_name="live-tool").one()
        assert stored.patch == {"description": "local note"}


def test_non_reviewer_public_tool_records_require_review_and_preserve_approved_state(client):
    uid_a = add_user("Ada", "1")
    uid_b = add_user("Grace", "2")
    sign_in(client, uid_a)
    public_tool = {
        "title": "Public Draft",
        "description": "Needs review",
        "url": "https://draft.example",
        "visibility": "public",
        "reviewStatus": "approved",
    }
    assert put_overlay(client, "toolNew", {"public-draft": public_tool}).status_code == 200
    own = client.get("/v1/overlay/").get_json()["toolNew"]["public-draft"]
    assert own["reviewStatus"] == "pending"
    assert client.get("/v1/search/tools/?q=public").get_json()["count"] == 0
    with db.session_scope() as s:
        row = s.query(ToolRecord).filter_by(tool_name="public-draft").one()
        row.review_status = "approved"
    assert put_overlay(client, "toolNew", {"public-draft": public_tool}).status_code == 200
    own = client.get("/v1/overlay/").get_json()["toolNew"]["public-draft"]
    assert own["reviewStatus"] == "approved"
    assert client.get("/v1/search/tools/?q=public").get_json()["count"] == 1

    sign_in(client, uid_b)
    public_to_others = client.get("/v1/overlay/").get_json()["toolNew"]["public-draft"]
    assert public_to_others["reviewStatus"] == "approved"
    assert public_to_others["source"] == "local"


def test_overlay_replace_semantics_and_merge(client):
    uid_a = add_user("Ada", "1")
    uid_b = add_user("Grace", "2")
    sign_in(client, uid_a)
    put_overlay(client, "favorites", ["one"])
    put_overlay(client, "favorites", ["two"])  # replaces, not appends
    put_overlay(client, "toolEdits", {"t": {"title": "from-ada"}})
    data = client.get("/v1/overlay/").get_json()
    assert data["favorites"] == ["two"]
    sign_in(client, uid_b)
    put_overlay(client, "toolEdits", {"t": {"title": "from-grace"}})
    data = client.get("/v1/overlay/").get_json()
    assert data["favorites"] == []  # per-user
    assert data["toolEdits"]["t"]["title"] == "from-grace"  # global merge, newest wins


def test_put_validation_errors(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.put("/v1/overlay/favorites", data="not json", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 400  # non-JSON body
    assert put_overlay(client, "favorites", "nope").status_code == 400
    assert put_overlay(client, "favorites", [""]).status_code == 400
    assert put_overlay(client, "lists", "nope").status_code == 400
    assert put_overlay(client, "lists", [{"id": 5}]).status_code == 400
    assert put_overlay(client, "crawlerUrls", [{"url": "http://insecure"}]).status_code == 400
    assert put_overlay(client, "toolEdits", {"t": "not-an-object"}).status_code == 400
    assert put_overlay(client, "toolNew", []).status_code == 400
    # record validation: a broken record must never reach the public feed/search
    assert put_overlay(client, "toolNew", {"bad": {"url": None, "keywords": None}}).status_code == 400
    bad_record = {"bad": {"title": "T", "description": "d", "url": "http://x"}}
    assert put_overlay(client, "toolNew", bad_record).status_code == 400
    assert put_overlay(client, "revisions", [{"no-id": True}]).status_code == 400
    assert put_overlay(client, "unknown-key", []).status_code == 404


TOOL_A = {"title": "Ada's tool", "description": "d", "url": "https://a.example"}


def test_pushed_echoes_never_reowned(client):
    """The pulled cache is globally merged; pushing it back must not re-own
    other users' records (Codex P1 finding on serversync write-through)."""
    uid_a = add_user("Ada", "1")
    uid_b = add_user("Grace", "2")
    sign_in(client, uid_a)
    assert put_overlay(client, "toolNew", {"adas-tool": TOOL_A}).status_code == 200
    assert put_overlay(client, "toolEdits", {"x": {"title": "ada-edit"}}).status_code == 200
    assert put_overlay(client, "revisions", [{"id": "r1", "comment": "ada"}]).status_code == 200
    # B pulls the merged overlay, adds their own tool, and echoes Ada's toolNew
    # row back; the server must skip the foreign toolNew row instead of re-owning it.
    sign_in(client, uid_b)
    pulled = client.get("/v1/overlay/").get_json()
    tool_b = {"title": "Grace's tool", "description": "d", "url": "https://g.example"}
    assert (
        put_overlay(client, "toolNew", {**pulled["toolNew"], "adas-tool": TOOL_A, "graces-tool": tool_b}).status_code
        == 200
    )
    assert put_overlay(client, "toolEdits", pulled["toolEdits"]).status_code == 200  # pure echo
    assert put_overlay(client, "revisions", [*pulled["revisions"], {"id": "r2", "comment": "grace"}]).status_code == 200
    with db.session_scope() as s:
        ada_tool = s.execute(select(ToolRecord).where(ToolRecord.tool_name == "adas-tool")).scalar_one()
        assert ada_tool.user_id == uid_a  # still Ada's — no copy under Grace
        assert s.query(ToolRecord).count() == 2
        assert s.query(ToolOverlay).count() == 1  # echoed edit not duplicated
        assert s.query(ActivityRow).filter(ActivityRow.kind == "revisions").count() == 2  # r1 not re-inserted
    # B genuinely changing an overlay entry makes it B's own contribution
    sign_in(client, uid_b)
    assert put_overlay(client, "toolEdits", {"x": {"title": "grace-edit"}}).status_code == 200
    with db.session_scope() as s:
        assert {(o.user_id, o.patch["title"]) for o in s.query(ToolOverlay)} == {
            (uid_a, "ada-edit"),
            (uid_b, "grace-edit"),
        }


def test_feed_trim(client):
    uid = add_user()
    sign_in(client, uid)
    with db.session_scope() as s:
        for i in range(FEED_KEEP_CAP):
            s.add(
                ActivityRow(
                    kind="revisions",
                    client_id=f"old{i}",
                    user_id=uid,
                    row={"id": f"old{i}"},
                    created_at=utcnow(),
                )
            )
    assert put_overlay(client, "revisions", [{"id": "brand-new"}]).status_code == 200
    with db.session_scope() as s:
        assert s.query(ActivityRow).filter(ActivityRow.kind == "revisions").count() == FEED_KEEP_CAP


def test_crawler_runs_and_user_data_controls(client):
    uid = add_user()
    sign_in(client, uid)
    with db.session_scope() as s:
        s.add(CrawlerRun(urls_count=2, added=1, updated=1, ok=False, errors=["bad url"], sync_status="sync_error"))
        s.add(
            ToolAuthorClaim(
                tool_name="ada-tool",
                author_name="Ada",
                toolhub_username="Ada",
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                verification_method=sync.AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
            )
        )
        s.add(ToolAuthorKey(toolhub_username="Ada", key_id="k1", public_key="pk"))
    runs = client.get("/v1/crawler/runs/").get_json()
    assert runs["count"] == 1
    assert runs["results"][0]["errors"] == ["bad url"]
    assert runs["results"][0]["syncStatus"] == "sync_error"

    assert put_overlay(client, "favorites", ["tool-a"]).status_code == 200
    assert put_overlay(client, "lists", [{"id": "demo-1", "title": "L", "tools": ["tool-a"]}]).status_code == 200
    assert put_overlay(client, "crawlerUrls", [{"url": "https://example.org/toolinfo.json"}]).status_code == 200
    exported = client.get("/v1/user/export/").get_json()
    assert exported["user"] == {"username": "Ada"}
    assert exported["overlay"]["favorites"] == ["tool-a"]
    assert exported["authorClaims"][0]["toolName"] == "ada-tool"
    assert exported["authorKeys"][0]["keyId"] == "k1"
    resp = client.delete("/v1/user/evolved-data/", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 200
    assert resp.get_json()["deleted"]["favorites"] == 1
    assert resp.get_json()["deleted"]["authorClaims"] == 1
    assert resp.get_json()["deleted"]["authorKeys"] == 1
    with db.session_scope() as s:
        assert s.query(CrawlerUrl).count() == 0
        assert s.query(ToolList).count() == 0
        assert s.query(ToolAuthorClaim).count() == 0
        assert s.query(ToolAuthorKey).count() == 0


# ---- iso helpers -----------------------------------------------------------


def test_iso_helpers():
    assert iso(None) == ""
    assert iso(utcnow()).endswith("Z")
    assert parse_iso("2026-07-25T10:00:00+02:00").hour == 8  # aware → UTC naive
    assert parse_iso("2026-07-25T10:00:00").hour == 10  # naive kept
    assert parse_iso(None).year >= 2026  # invalid → now
    assert parse_optional_iso("2026-07-25T10:00:00").hour == 10


def test_merged_maps_handles_legacy_rows_and_missing_review_metadata():
    overlay = ToolOverlay(tool_name="patched", kind="edits", patch={"title": "Patched"}, review_status=None)
    assert merged_maps([overlay]) == {
        "patched": {"title": "Patched", "source": "local", "syncStatus": "local_draft", "syncLabel": "Local draft"}
    }

    class LegacyRow:
        tool_name = "legacy"
        record = {"title": "Legacy"}

    assert merged_maps([LegacyRow()]) == {"legacy": {"title": "Legacy"}}


def test_overlay_hides_foreign_write_diagnostics_but_keeps_them_for_owner(client):
    writer = add_user(username="Writer", wm_sub="writer")
    reader = add_user(username="Reader", wm_sub="reader")
    sign_in(client, writer)
    assert (
        put_overlay(
            client,
            "toolEdits",
            {
                "private-diagnostic-tool": {
                    "title": "A public patch",
                    "syncStatus": "local_fallback",
                    "lastError": "secret permission response",
                    "toolhubResponse": {"detail": "private upstream detail"},
                    "validationErrors": [{"field": "title", "message": "private validation"}],
                }
            },
        ).status_code
        == 200
    )

    sign_in(client, reader)
    foreign = client.get("/v1/overlay/").get_json()["toolEdits"]["private-diagnostic-tool"]
    assert foreign["viewerOwned"] is False
    assert foreign["title"] == "A public patch"
    assert "lastError" not in foreign
    assert "toolhubResponse" not in foreign
    assert "validationErrors" not in foreign

    sign_in(client, writer)
    own = client.get("/v1/overlay/").get_json()["toolEdits"]["private-diagnostic-tool"]
    assert own["viewerOwned"] is True
    assert own["lastError"] == "secret permission response"
    assert own["toolhubResponse"] == {"detail": "private upstream detail"}


# ---- public endpoints ------------------------------------------------------


def test_healthz_ok_and_failure(client):
    assert client.get("/healthz").get_json() == {"ok": True}
    db.configure("sqlite:////nonexistent-dir/x/y.sqlite3")  # unreachable db
    assert client.get("/healthz").status_code == 503
    db.configure("sqlite://")
    db.init_schema()


def test_search_and_toolinfo_feed(client):
    uid = add_user()
    with db.session_scope() as s:
        s.add(
            ToolRecord(
                tool_name="alpha",
                user_id=uid,
                record={
                    "title": "Alpha",
                    "description": "First",
                    "url": "https://a.example",
                    "keywords": ["cite"],
                },
                modified_at=utcnow(),
                visibility="public",
                sync_status="evolved_real",
                review_status="approved",
            )
        )
        s.add(
            ToolRecord(
                tool_name="beta",
                user_id=uid,
                record={"title": "Beta", "description": "Second"},
                modified_at=utcnow(),
                visibility="public",
                sync_status="evolved_real",
                review_status="approved",
            )
        )
    all_results = client.get("/v1/search/tools/").get_json()
    assert all_results["count"] == 2  # empty q matches everything
    assert client.get("/v1/search/tools/?q=alp").get_json()["count"] == 1  # by name
    assert client.get("/v1/search/tools/?q=first").get_json()["count"] == 1  # by description
    assert client.get("/v1/search/tools/?q=cite").get_json()["count"] == 1  # by keyword
    assert client.get("/v1/search/tools/?q=zzz").get_json()["count"] == 0
    feed = client.get("/toolinfo.json").get_json()
    assert len(feed) == 1  # beta has no https url → excluded
    assert feed[0]["name"] == "toolhub-evolved-alpha"
    assert feed[0]["keywords"] == "cite"
    assert feed[0]["_schema"] == "/toolinfo/1.2.2"


def test_real_evolved_signals_and_media(client):
    uid = add_user()
    sign_in(client, uid)
    assert client.get("/v1/tools/alpha/signals/").get_json()["thanks"]["count"] == 0
    assert (
        client.post("/v1/tools/alpha/events/", json={"eventType": "view"}, headers={"X-CSRF-Token": "tok"}).status_code
        == 200
    )
    assert client.post("/v1/tools/alpha/thanks/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    signals = client.get("/v1/tools/alpha/signals/").get_json()
    assert signals["source"] == "local"
    assert signals["syncStatus"] == "evolved_real"
    assert signals["syncLabel"] == "Evolved data"
    assert signals["thanks"]["count"] == 1
    assert signals["thanks"]["userThanked"] is True
    assert signals["thanks"]["syncLabel"] == "Evolved data"
    assert signals["usage30d"]["count"] == 1
    assert signals["usage30d"]["syncLabel"] == "Evolved data"
    assert signals["health"]["status"] == "unknown"
    assert client.delete("/v1/tools/alpha/thanks/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert client.get("/v1/tools/alpha/signals/").get_json()["thanks"]["count"] == 0

    health = client.put(
        "/v1/tools/alpha/health-target/",
        json={"url": "https://alpha.example/healthz"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert health.status_code == 200
    assert health.get_json()["healthTarget"]["reviewStatus"] == "pending"
    assert health.get_json()["healthTarget"]["syncLabel"] == "Evolved data"
    assert client.get("/v1/tools/alpha/signals/").get_json()["health"]["status"] == "unknown"
    with db.session_scope() as s:
        target = s.query(ToolHealthTarget).one()
        target.review_status = "approved"
        target.last_status = "healthy"
        target.last_checked_at = utcnow()
    health_signals = client.get("/v1/tools/alpha/signals/").get_json()["health"]
    assert health_signals["status"] == "healthy"
    assert health_signals["targetUrl"] == "https://alpha.example/healthz"
    assert health_signals["reviewStatus"] == "approved"
    assert health_signals["syncLabel"] == "Evolved data"

    media_payload = {"url": "https://img.example/shot.png", "license": "CC-BY-SA-4.0", "source": "Maintainer upload"}
    media = client.post("/v1/tools/alpha/media/", json=media_payload, headers={"X-CSRF-Token": "tok"})
    assert media.status_code == 200
    assert media.get_json()["media"]["reviewStatus"] == "pending"
    assert media.get_json()["media"]["syncLabel"] == "Evolved data"
    assert client.get("/v1/tools/alpha/media/").get_json()["count"] == 0  # pending media is not public
    with db.session_scope() as s:
        row = s.query(ToolMedia).one()
        row.review_status = "approved"
    media_list = client.get("/v1/tools/alpha/media/").get_json()
    assert media_list["count"] == 1
    assert media_list["results"][0]["syncLabel"] == "Evolved data"
    assert (
        client.delete(f"/v1/media/{media.get_json()['media']['id']}/", headers={"X-CSRF-Token": "tok"}).status_code
        == 200
    )
    with db.session_scope() as s:
        assert s.query(ToolEvent).count() == 1
        assert s.query(ToolThanks).count() == 1
        assert s.query(ToolHealthTarget).count() == 1
        assert s.query(ToolMedia).one().deleted_at is not None


def test_real_signal_media_validation_and_update_paths(client):
    assert client.post("/v1/tools/alpha/media/", json={"url": "https://x.example"}).status_code == 401
    uid = add_user()
    sign_in(client, uid)
    with db.session_scope() as s:
        s.add(ToolThanks(tool_name="legacy-thanks", user_id=uid, active=False))
    assert client.post("/v1/tools/legacy-thanks/thanks/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    with db.session_scope() as s:
        thanks = s.query(ToolThanks).filter_by(tool_name="legacy-thanks").one()
        assert thanks.created_by_user_id == uid
        assert thanks.review_status == "approved"

    assert client.get("/v1/tools/%20/signals/").status_code == 400
    assert (
        client.post("/v1/tools/alpha/events/", json={"eventType": "bogus"}, headers={"X-CSRF-Token": "tok"}).status_code
        == 400
    )
    assert client.post("/v1/tools/%20/thanks/", headers={"X-CSRF-Token": "tok"}).status_code == 400
    assert (
        client.put(
            "/v1/tools/alpha/health-target/",
            json={"url": "ftp://bad.example"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/v1/tools/alpha/health-target/",
            json={"url": "https://alpha.example/first"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/v1/tools/alpha/health-target/",
            json={"url": "https://alpha.example/second"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/v1/tools/alpha/health-target/",
            json={"url": "https://alpha.example/second"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    with db.session_scope() as s:
        target = s.query(ToolHealthTarget).one()
        assert target.target_url == "https://alpha.example/second"
        assert target.enabled is True
        assert target.review_status == "pending"
        assert target.last_error is None

    assert (
        client.post(
            "/v1/tools/%20/media/",
            json={"url": "https://img.example/shot.png", "license": "CC0", "source": "test"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    assert client.post("/v1/tools/alpha/media/", json=[], headers={"X-CSRF-Token": "tok"}).status_code == 400
    assert (
        client.post(
            "/v1/tools/alpha/media/",
            json={"url": "https://img.example/shot.png", "license": "", "source": "test"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    assert client.delete("/v1/media/999/", headers={"X-CSRF-Token": "tok"}).status_code == 404
    with db.session_scope() as s:
        other = User(wm_sub="other", username="Other")
        s.add(other)
        s.flush()
        s.add(
            ToolMedia(
                tool_name="alpha",
                user_id=other.id,
                url="https://img.example/other.png",
                license="CC0",
                source="other",
            )
        )
        s.flush()
        other_media_id = s.query(ToolMedia).filter(ToolMedia.user_id == other.id).one().id
    assert client.delete(f"/v1/media/{other_media_id}/", headers={"X-CSRF-Token": "tok"}).status_code == 404


def test_public_evolved_data_moderation_lifecycle(client):
    uid = add_user("Ada", "1")
    sign_in(client, uid)
    public_tool = {"title": "Public Draft", "description": "Needs review", "url": "https://draft.example"}
    assert put_overlay(client, "toolNew", {"public-draft": {**public_tool, "visibility": "public"}}).status_code == 200
    assert (
        client.put(
            "/v1/tools/public-draft/health-target/",
            json={"url": "https://draft.example/healthz"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    media = client.post(
        "/v1/tools/public-draft/media/",
        json={"url": "https://img.example/draft.png", "license": "CC0", "source": "Maintainer"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert media.status_code == 200
    assert client.post("/v1/tools/public-draft/thanks/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    with db.session_scope() as s:
        tool_row = s.query(ToolRecord).filter_by(tool_name="public-draft").one()
        health_row = s.query(ToolHealthTarget).one()
        media_row = s.query(ToolMedia).filter_by(tool_name="public-draft").one()
        thanks_row = s.query(ToolThanks).one()
        health_row.last_status = "healthy"
        health_row.last_checked_at = utcnow()
        thanks_row.review_status = "pending"
        deleted_media = ToolMedia(
            tool_name="public-draft",
            user_id=uid,
            created_by_user_id=uid,
            url="https://img.example/deleted.png",
            license="CC0",
            source="Maintainer",
            deleted_at=utcnow(),
        )
        private_record = ToolRecord(
            tool_name="private-draft",
            user_id=uid,
            created_by_user_id=uid,
            record={**public_tool, "title": "Private Draft"},
            visibility="private",
            review_status="pending",
        )
        s.add_all([deleted_media, private_record])
        s.flush()
        ids = {
            "tool": tool_row.id,
            "health": health_row.id,
            "media": media_row.id,
            "thanks": thanks_row.id,
            "deletedMedia": deleted_media.id,
            "privateTool": private_record.id,
        }

    assert client.get("/v1/moderation/public-data/").status_code == 403
    reviewer_id = add_user("Reviewer", "2", role=authz.ROLE_REVIEWER)
    sign_in(client, reviewer_id)
    headers = {"X-CSRF-Token": "tok"}
    reviewer_tool = {
        "title": "Reviewer Tool",
        "description": "Reviewer-approved local record",
        "url": "https://reviewer.example",
        "visibility": "public",
        "reviewStatus": "approved",
    }
    assert put_overlay(client, "toolNew", {"reviewer-tool": reviewer_tool}).status_code == 200
    assert client.get("/v1/search/tools/?q=reviewer").get_json()["count"] == 1
    queue = client.get("/v1/moderation/public-data/").get_json()
    assert queue["source"] == "local"
    assert queue["syncStatus"] == "evolved_real"
    assert queue["syncLabel"] == "Evolved data"
    assert queue["count"] == 4
    assert {item["kind"] for item in queue["results"]} == {"tool-records", "health-targets", "media", "thanks"}
    assert {item["data"]["syncLabel"] for item in queue["results"]} == {"Evolved data"}

    assert (
        client.put(
            "/v1/moderation/public-data/unknown/1/", json={"reviewStatus": "approved"}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/v1/moderation/public-data/tool-records/{ids['tool']}/", data="not-json", headers=headers
        ).status_code
        == 400
    )
    assert (
        client.put(
            f"/v1/moderation/public-data/tool-records/{ids['tool']}/",
            json={"reviewStatus": "open"},
            headers=headers,
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/v1/moderation/public-data/tool-records/999/", json={"reviewStatus": "approved"}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/v1/moderation/public-data/tool-records/{ids['privateTool']}/",
            json={"reviewStatus": "approved"},
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/v1/moderation/public-data/media/{ids['deletedMedia']}/",
            json={"reviewStatus": "approved"},
            headers=headers,
        ).status_code
        == 404
    )

    pending = client.put(
        f"/v1/moderation/public-data/tool-records/{ids['tool']}/",
        json={"reviewStatus": "pending"},
        headers=headers,
    )
    assert pending.status_code == 200
    assert pending.get_json()["item"]["data"]["reviewStatus"] == "pending"
    assert client.get("/v1/search/tools/?q=public").get_json()["count"] == 0

    approve_tool = client.put(
        f"/v1/moderation/public-data/tool-records/{ids['tool']}/",
        json={"reviewStatus": "approved"},
        headers=headers,
    )
    assert approve_tool.status_code == 200
    assert approve_tool.get_json()["item"]["data"]["source"] == "local"
    assert approve_tool.get_json()["item"]["data"]["syncLabel"] == "Evolved data"
    assert client.get("/v1/search/tools/?q=public").get_json()["count"] == 1
    assert client.get("/toolinfo.json").get_json()[0]["name"] == "toolhub-evolved-public-draft"

    assert (
        client.put(
            f"/v1/moderation/public-data/health-targets/{ids['health']}/",
            json={"reviewStatus": "approved"},
            headers=headers,
        ).status_code
        == 200
    )
    health = client.get("/v1/tools/public-draft/signals/").get_json()["health"]
    assert health["status"] == "healthy"
    assert health["syncLabel"] == "Evolved data"

    assert (
        client.put(
            f"/v1/moderation/public-data/media/{ids['media']}/",
            json={"review_status": "approved"},
            headers=headers,
        ).status_code
        == 200
    )
    media_list = client.get("/v1/tools/public-draft/media/").get_json()
    assert media_list["count"] == 1
    assert media_list["results"][0]["syncStatus"] == "evolved_real"

    assert (
        client.put(
            f"/v1/moderation/public-data/thanks/{ids['thanks']}/",
            json={"reviewStatus": "rejected"},
            headers=headers,
        ).status_code
        == 200
    )
    assert client.get("/v1/tools/public-draft/signals/").get_json()["thanks"]["count"] == 0
    sign_in(client, uid)
    assert client.post("/v1/tools/public-draft/thanks/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert client.get("/v1/tools/public-draft/signals/").get_json()["thanks"]["count"] == 0
    with db.session_scope() as s:
        assert s.get(ToolThanks, ids["thanks"]).review_status == "rejected"
        activity = s.query(ActivityRow).filter(ActivityRow.action == "public-data-reviewed").all()
        assert len(activity) == 10
        assert {row.kind for row in activity} == {"revisions", "auditlogs"}
        assert len({(row.object_type, row.object_key) for row in activity}) == 4
        assert {row.payload["reviewStatus"] for row in activity if row.object_type == "tool-records"} == {
            "pending",
            "approved",
        }


class FakeResp:
    def __init__(self, payload, status=200, headers=None, content=None):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)
        self.ok = status < 400
        self.headers = headers or {"content-type": "application/json"}
        self.content = content if content is not None else dumps(payload).encode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise toolhub.requests.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


class TextResp:
    status_code = 418
    text = "plain upstream error"
    ok = False

    def json(self):
        raise ValueError("not json")


def test_public_api_url_stays_inside_the_api_tree():
    assert toolhub._public_api_url("/api/tools/").endswith("/api/tools/")
    for path in ("/o/token/", "/api/../o/token/", "api/tools/../../o/token/"):
        with pytest.raises(ValueError, match="anonymous reads"):
            toolhub._public_api_url(path)


def test_request_with_token_stays_inside_the_api_tree(monkeypatch):
    """The authenticated write bridge gets the same path guard as anonymous reads.

    It did not for a while: only _public_api_url checked, so the half carrying a
    user's bearer grant was the unguarded one. A single "../" segment is enough,
    because urllib3 normalizes dot segments when it builds the request line —
    /api/tools/../ leaves as /api/, escaping the resource scope the route named.
    """
    sent = []
    monkeypatch.setattr(toolhub.requests, "request", lambda m, url, **_k: sent.append((m, url)))
    for path in ("/o/token/", "/api/tools/../", "/api/tools/../../o/token/"):
        with pytest.raises(ValueError, match="official API calls"):
            toolhub.request_with_token("PUT", path, access_token="at", json={})
    assert sent == [], f"a refused path still reached the network: {sent}"


def test_official_write_route_refuses_a_scope_escaping_tool_name(client, monkeypatch):
    """The refusal surfaces as a 400, not a 500, and never reaches Toolhub."""
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    calls = []
    monkeypatch.setattr(toolhub.requests, "request", lambda m, url, **_k: calls.append((m, url)))
    resp = client.put("/v1/toolhub/tools/../", json={"name": "x"}, headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 400
    assert calls == []


def test_write_lifecycle_refuses_a_scope_escaping_name_without_storing_a_draft(client, monkeypatch):
    """The second api_request call site is guarded too, and does not fall back.

    _attempt_official_write feeds the /v1/write/* lifecycle, where a refusal is
    normally stored as a local draft. A rejected path is not an upstream outage,
    so it must deny instead — otherwise a draft gets persisted against a path
    that can never become valid.
    """
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    calls = []
    monkeypatch.setattr(toolhub.requests, "request", lambda m, url, **_k: calls.append((m, url)))

    resp = client.delete("/v1/write/tools/../", headers={"X-CSRF-Token": "tok"})

    # 400 specifically, not 404: the route matches and the view runs, so this
    # asserts the guard fired rather than that routing happened to miss.
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid official Toolhub path"
    assert calls == []


def test_debug_forwarded_reports_the_proxy_chain_for_sizing_proxyfix(client):
    """The temporary hop-count probe: signed-in only, and does the N arithmetic.

    ProxyFix(x_for=N) takes the Nth X-Forwarded-For entry from the right, so
    `candidates` is what turns a live request into a decision: the correct N is
    the row holding the caller's own public IP. Delete alongside the route.
    """
    assert client.get("/v1/debug/forwarded/").status_code == 401

    uid = add_user()
    sign_in(client, uid)
    resp = client.get(
        "/v1/debug/forwarded/",
        headers={"X-Forwarded-For": "203.0.113.7, 10.1.2.3", "X-Forwarded-Proto": "https"},
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["xForwardedForEntries"] == ["203.0.113.7", "10.1.2.3"]
    assert body["hopCount"] == 2
    # Rightmost entry is x_for=1; the real client sits one further left here.
    assert body["candidates"] == {"x_for=1": "10.1.2.3", "x_for=2": "203.0.113.7"}
    assert body["xForwardedProto"] == "https"


def stored_grant(uid):
    """Return the decrypted (access, refresh) pair persisted for one user."""
    with db.session_scope() as s:
        row = s.get(ToolhubToken, uid)
        refresh = token_crypto.decrypt(row.refresh_token) if row.refresh_token else None
        return token_crypto.decrypt(row.access_token), refresh


def configure_oauth(monkeypatch):
    monkeypatch.setenv("TOOLHUB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("TOOLHUB_OAUTH_CLIENT_SECRET", "csec")
    # The callback URL is only derived from request headers in development, so
    # tests that drive the flow have to say which of the two modes they are in.
    monkeypatch.setenv("TOOLHUB_INSECURE_COOKIES", "1")


# ---- official Toolhub client helpers ---------------------------------------


def test_toolhub_config_and_authorize_url(monkeypatch):
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("TOOLHUB_API_BASE", raising=False)
    assert toolhub.base_url() == "https://toolhub.wikimedia.org"
    assert toolhub.oauth_client() is None
    assert toolhub.configured() is False
    with pytest.raises(toolhub.ToolhubAuthError):
        toolhub.authorize_url(state="s", redirect_uri="https://evolved.example/oauth/callback")
    with pytest.raises(toolhub.ToolhubAuthError):
        toolhub.exchange_code(code="c", redirect_uri="https://evolved.example/oauth/callback")
    with pytest.raises(toolhub.ToolhubAuthError):
        toolhub.refresh_grant("rt")

    configure_oauth(monkeypatch)
    monkeypatch.setenv("TOOLHUB_API_BASE", "https://toolhub.example/")
    url = toolhub.authorize_url(state="s", redirect_uri="https://evolved.example/oauth/callback")
    assert toolhub.base_url() == "https://toolhub.example"
    assert toolhub.oauth_client() == ("cid", "csec")
    assert "https://toolhub.example/o/authorize/?" in url
    assert "client_id=cid" in url
    assert "redirect_uri=https%3A%2F%2Fevolved.example%2Foauth%2Fcallback" in url
    assert "scope=read+write" in url
    assert "state=s" in url


def test_toolhub_current_user_rejects_bad_shapes(monkeypatch):
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"is_authenticated": False}))
    with pytest.raises(toolhub.ToolhubAuthError):
        toolhub.current_user("at")
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp([]))
    with pytest.raises(toolhub.ToolhubAuthError):
        toolhub.current_user("at")


def test_toolhub_extracts_only_wikimedia_global_identity():
    assert (
        toolhub.wikimedia_global_user_id(
            {
                "social_auth": [
                    {"provider": "github", "uid": "other"},
                    {"provider": "wikimedia", "uid": 160},
                ]
            }
        )
        == "160"
    )
    assert toolhub.wikimedia_global_user_id({"social_auth": "invalid"}) == ""


def test_toolhub_text_error_payload(monkeypatch):
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: TextResp())
    with pytest.raises(toolhub.ToolhubAPIError) as exc:
        toolhub.request_with_token("POST", "/api/tools/", access_token="at", json={"name": "x"})
    assert exc.value.status_code == 418
    assert exc.value.payload == {"message": "plain upstream error"}


def test_toolhub_public_api_get_uses_shared_cache(client, monkeypatch):
    monkeypatch.setenv("TOOLHUB_API_BASE", "https://toolhub.example")
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResp({"results": [{"name": "cached"}]}, headers={"content-type": "application/json", "etag": "e1"})

    monkeypatch.setattr(toolhub.requests, "get", fake_get)
    assert toolhub.public_api_get("/api/search/tools/", params={"author__term": "Ada"}) == {
        "results": [{"name": "cached"}]
    }
    assert calls[0][0] == "https://toolhub.example/api/search/tools/?author__term=Ada"
    assert calls[0][1]["headers"]["Accept"] == "application/json"
    assert toolhub.public_api_get("/api/search/tools/", params={"author__term": "Ada"}) == {
        "results": [{"name": "cached"}]
    }
    assert len(calls) == 1


def test_toolhub_public_api_get_can_bypass_cached_reads_and_refresh_them(client, monkeypatch):
    monkeypatch.setenv("TOOLHUB_API_BASE", "https://toolhub.example")
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResp({"count": 2, "results": [{"name": "fresh"}]})

    url = "https://toolhub.example/api/tools/?page=1&page_size=100"
    api_cache.put_success(
        url,
        api_cache.CacheableResponse(
            status=200,
            content_type="application/json",
            body=b'{"count":3,"results":[{"name":"stale"}]}',
        ),
    )
    monkeypatch.setattr(toolhub.requests, "get", fake_get)

    assert toolhub.public_api_get(
        "/api/tools/",
        params={"page": 1, "page_size": 100},
        read_cache=False,
    ) == {"count": 2, "results": [{"name": "fresh"}]}
    assert len(calls) == 1
    assert toolhub.public_api_get("/api/tools/", params={"page": 1, "page_size": 100}) == {
        "count": 2,
        "results": [{"name": "fresh"}],
    }
    assert len(calls) == 1


def test_toolhub_public_api_get_rejects_non_api_paths():
    with pytest.raises(ValueError, match="/api/"):
        toolhub.public_api_get("/oauth/login")


def test_toolhub_public_api_get_leaves_noncacheable_success_uncached(client, monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResp({"message": "unchanged"}, 304)

    monkeypatch.setattr(toolhub.requests, "get", fake_get)
    assert toolhub.public_api_get("/api/schema/") == {"message": "unchanged"}
    assert toolhub.public_api_get("/api/schema/") == {"message": "unchanged"}
    assert len(calls) == 2


def test_toolhub_public_api_get_raises_upstream_error(client, monkeypatch):
    monkeypatch.setattr(toolhub.requests, "get", lambda *a, **k: FakeResp({"message": "bad"}, 503))
    with pytest.raises(toolhub.ToolhubAPIError) as exc:
        toolhub.public_api_get("/api/search/tools/")
    assert exc.value.status_code == 503
    assert exc.value.payload == {"message": "bad"}


def test_recent_owner_resolver_reads_replica_once_then_uses_owner_cache(client):
    canonical_tools.upsert_records(
        [{"name": "my-tool", "author": [{"name": "Ada Maintainer"}]}], source_url="local-test"
    )
    first = client.get("/v1/recent/owners/?tool=my-tool&tool=my-tool").get_json()
    second = client.get("/v1/recent/owners/?tools=my-tool").get_json()

    assert first["owners"] == {"my-tool": "Ada Maintainer"}
    assert first["meta"]["my-tool"]["cached"] is True
    assert second["owners"] == {"my-tool": "Ada Maintainer"}
    assert second["meta"]["my-tool"]["cached"] is True
    with db.session_scope() as s:
        row = s.get(ToolOwnerCache, "my-tool")
        assert row.owner == "Ada Maintainer"
        assert row.source == "local_catalog"


def test_owner_cache_purges_only_rows_past_their_stale_window(client):
    now = utcnow()
    with db.session_scope() as s:
        s.add(
            ToolOwnerCache(
                tool_name="live", owner="Ada", fetched_at=now, expires_at=now, stale_until=now + timedelta(days=1)
            )
        )
        s.add(
            ToolOwnerCache(
                tool_name="dead", owner="", fetched_at=now, expires_at=now, stale_until=now - timedelta(days=1)
            )
        )
    assert recent_owners.purge_expired() == 1
    with db.session_scope() as s:
        assert s.get(ToolOwnerCache, "live") is not None
        assert s.get(ToolOwnerCache, "dead") is None
    assert recent_owners.purge_expired() == 0  # idempotent


def test_unresolved_owner_rows_expire_far_sooner_than_resolved_ones(client):
    client.get("/v1/recent/owners/?tool=nobody")  # resolves to no owner → negative entry
    with db.session_scope() as s:
        row = s.get(ToolOwnerCache, "nobody")
        # Junk names are the ones an attacker can mint freely, so they must not
        # occupy the table for the full positive-entry week.
        assert (row.stale_until - row.fetched_at).total_seconds() <= (
            recent_owners.OWNER_NEGATIVE_FRESH_SECONDS + recent_owners.OWNER_NEGATIVE_STALE_SECONDS
        )


def test_recent_owners_defers_names_past_the_fetch_budget(client):
    cold = recent_owners.OWNER_FETCH_BUDGET + 6
    canonical_tools.upsert_records(
        [{"name": f"cold-{i}", "author": [{"name": "Ada"}]} for i in range(cold)], source_url="local-test"
    )
    names = "&".join(f"tool=cold-{i}" for i in range(cold))
    data = client.get(f"/v1/recent/owners/?{names}").get_json()

    assert sum(owner == "Ada" for owner in data["owners"].values()) == recent_owners.OWNER_FETCH_BUDGET
    deferred = [n for n, m in data["meta"].items() if m["source"] == recent_owners.SOURCE_DEFERRED]
    assert len(deferred) == cold - recent_owners.OWNER_FETCH_BUDGET
    assert all(data["owners"][name] == "" for name in deferred)
    with db.session_scope() as s:
        # Deferred means unknown, not known-empty: nothing may be cached for them,
        # or the next request would treat the blank as a resolved answer.
        assert all(s.get(ToolOwnerCache, name) is None for name in deferred)


def test_recent_owners_is_rate_limited(client, monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(security.time, "monotonic", lambda: clock["t"])
    for _ in range(security.READ_LIMIT):
        assert client.get("/v1/recent/owners/?tool=warm").status_code == 200
    resp = client.get("/v1/recent/owners/?tool=warm")
    assert resp.status_code == 429
    assert resp.get_json()["error"] == "rate limit exceeded"
    clock["t"] += security.WRITE_WINDOW_SECONDS + 1  # window rolls over
    assert client.get("/v1/recent/owners/?tool=warm").status_code == 200


def test_resolve_owners_without_a_budget_is_unlimited(client):
    # The scheduled prewarm job is trusted and passes no budget.
    result = recent_owners.resolve_owners([f"job-{i}" for i in range(recent_owners.OWNER_FETCH_BUDGET + 3)])
    assert result["count"] == recent_owners.OWNER_FETCH_BUDGET + 3


def test_recent_owner_resolver_returns_stale_owner_when_replica_misses(client):
    with db.session_scope() as s:
        now = utcnow()
        s.add(
            ToolOwnerCache(
                tool_name="stale-tool",
                owner="Cached Owner",
                fetched_at=now - timedelta(days=2),
                expires_at=now - timedelta(seconds=1),
                stale_until=now + timedelta(days=1),
            )
        )

    data = client.get("/v1/recent/owners/?tool=stale-tool").get_json()

    assert data["owners"] == {"stale-tool": "Cached Owner"}
    assert data["meta"]["stale-tool"]["cached"] is True
    assert data["meta"]["stale-tool"]["stale"] is True
    with db.session_scope() as s:
        assert "absent from the local catalog" in s.get(ToolOwnerCache, "stale-tool").last_error


def test_recent_owner_resolver_cleans_bounds_and_negative_caches_failures(client):
    names = "&".join(f"tool=tool-{i}" for i in range(recent_owners.OWNER_MAX_NAMES + 5))
    data = client.get(f"/v1/recent/owners/?tool=&tool=tool-0&{names}").get_json()

    assert data["count"] == recent_owners.OWNER_MAX_NAMES
    assert data["owners"]["tool-0"] == ""
    with db.session_scope() as s:
        row = s.get(ToolOwnerCache, "tool-0")
        assert row.owner == ""
        assert row.last_error
        assert row.expires_at > utcnow()


def test_recent_owner_record_parser_prefers_author_display_name():
    assert (
        recent_owners.owner_from_tool_record({"author": [{"name": "Display", "developer_username": "dev"}]})
        == "Display"
    )
    assert recent_owners.owner_from_tool_record({"author": [{"developer_username": "dev"}]}) == "dev"
    assert recent_owners.owner_from_tool_record({"author": "Plain Author"}) == "Plain Author"
    assert recent_owners.owner_from_tool_record({"created_by": {"username": "creator"}}) == "creator"
    assert recent_owners.owner_from_tool_record({}) == ""


def test_toolhub_refreshes_expired_grant(client, monkeypatch):
    uid = add_user(wm_sub="refresh")
    configure_oauth(monkeypatch)
    toolhub.save_grant(uid, {"access_token": "old", "refresh_token": "rt", "expires_in": -120})
    calls = []
    refreshes = [
        {
            "access_token": "new",
            "refresh_token": "rt2",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "read write",
        },
        {"access_token": "new-no-rotate", "expires_in": 3600},
    ]

    def fake_post(url, **kwargs):
        calls.append(("post", url, kwargs))
        return FakeResp(refreshes.pop(0))

    def fake_request(method, url, **kwargs):
        calls.append(("request", method, url, kwargs))
        return FakeResp({"ok": True})

    monkeypatch.setattr(toolhub.requests, "post", fake_post)
    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    body, status = toolhub.api_request(uid, "POST", "/api/tools/", json={"name": "x"})
    assert (body, status) == ({"ok": True}, 200)
    assert calls[0][0] == "post"
    assert calls[1][3]["headers"]["Authorization"] == "Bearer new"
    assert stored_grant(uid) == ("new", "rt2")
    toolhub.save_grant(uid, {"access_token": "third"})
    assert stored_grant(uid) == ("third", "rt2")
    uid_no_rotate = add_user(wm_sub="refresh-no-rotate")
    toolhub.save_grant(uid_no_rotate, {"access_token": "old2", "refresh_token": "keep", "expires_in": -120})
    toolhub.api_request(uid_no_rotate, "POST", "/api/tools/", json={"name": "x"})
    assert stored_grant(uid_no_rotate) == ("new-no-rotate", "keep")


def test_stored_grants_are_encrypted_at_rest(client):
    uid = add_user(wm_sub="sealed")
    toolhub.save_grant(uid, {"access_token": "secret-access", "refresh_token": "secret-refresh"})
    with db.session_scope() as s:
        row = s.get(ToolhubToken, uid)
        assert row.access_token.startswith(token_crypto.PREFIX)
        assert "secret-access" not in row.access_token  # ciphertext, not an encoding
        assert "secret-refresh" not in row.refresh_token
    assert stored_grant(uid) == ("secret-access", "secret-refresh")


def test_an_unsealed_grant_is_rejected_rather_than_trusted(client, monkeypatch):
    # The pre-encryption plaintext tolerance is gone now that production is fully
    # migrated. An unsealed value must fail closed like any other unreadable one:
    # if a row ever loses its prefix, it is not a token we should be sending.
    uid = add_user(wm_sub="unsealed")
    with db.session_scope() as s:
        s.add(ToolhubToken(user_id=uid, access_token="plain-access", refresh_token="plain-refresh"))
    monkeypatch.setattr(toolhub.requests, "request", lambda *_a, **kw: FakeResp({"ok": True}))
    with pytest.raises(toolhub.ToolhubAuthError):
        toolhub.api_request(uid, "POST", "/api/tools/", json={"name": "x"})
    with db.session_scope() as s:
        assert s.get(ToolhubToken, uid) is None  # dropped; the user re-authorizes


def test_unreadable_grant_is_dropped_and_forces_reauth(client, monkeypatch):
    uid = add_user(wm_sub="rotated")
    toolhub.save_grant(uid, {"access_token": "a", "refresh_token": "r"})
    token_crypto.configure("a-completely-different-session-secret")  # simulate key rotation
    with pytest.raises(toolhub.ToolhubAuthError):
        toolhub.api_request(uid, "POST", "/api/tools/", json={"name": "x"})
    with db.session_scope() as s:
        assert s.get(ToolhubToken, uid) is None  # fail closed: unreadable grant forgotten


def test_token_crypto_requires_configuration(monkeypatch):
    monkeypatch.setattr(token_crypto, "_fernet", None)
    with pytest.raises(RuntimeError, match="configure"):
        token_crypto.encrypt("x")


def test_token_key_env_overrides_the_session_secret(monkeypatch):
    monkeypatch.setenv("TOOLHUB_TOKEN_KEY", "independent-token-key")
    token_crypto.configure("session-secret-a")
    sealed = token_crypto.encrypt("grant")
    token_crypto.configure("session-secret-b")  # session key rotated…
    assert token_crypto.decrypt(sealed) == "grant"  # …grant survives


def test_toolhub_expired_grant_without_refresh_requires_reauth(client):
    uid = add_user(wm_sub="expired")
    with db.session_scope() as s:
        # Sealed, so the read succeeds and we actually reach the expiry check —
        # an unsealed value would fail closed earlier and pass for the wrong reason.
        s.add(ToolhubToken(user_id=uid, access_token=token_crypto.encrypt("old"), expires_at=utcnow()))
    with pytest.raises(toolhub.ToolhubAuthError):
        toolhub.api_request(uid, "POST", "/api/tools/", json={"name": "x"})
    toolhub.revoke_local_grant(uid + 1)  # no-op for missing row


# ---- official Toolhub write bridge ----------------------------------------


def test_official_write_requires_stored_toolhub_grant(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.post("/v1/toolhub/tools/", json={"name": "x"}, headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 401
    assert resp.get_json()["reauth"] is True


def test_official_tool_write_forwards_with_bearer_token(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/tools/my-tool/",
        api_cache.CacheableResponse(200, "application/json", b'{"name":"my-tool","title":"old"}'),
    )
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/search/tools/?q=my-tool",
        api_cache.CacheableResponse(200, "application/json", b'{"results":[]}'),
    )
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResp({"name": "my-tool"}, 201)

    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    payload = {"name": "my-tool", "title": "T", "description": "d", "url": "https://example.org"}
    resp = client.post("/v1/toolhub/tools/", json=payload, headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 201
    assert resp.get_json()["toolhub"] == {"name": "my-tool"}
    assert calls[0][0] == "POST"
    assert calls[0][1] == "https://toolhub.wikimedia.org/api/tools/"
    assert calls[0][2]["headers"]["Authorization"] == "Bearer at"
    assert calls[0][2]["json"] == payload
    with db.session_scope() as s:
        assert s.query(ApiCache).count() == 0
        claim = s.query(ToolAuthorClaim).filter_by(tool_name="my-tool", author_name="Ada").one()
        assert claim.toolhub_username == "Ada"
        assert claim.verification_status == sync.AUTHOR_CLAIM_VERIFIED
        assert claim.verification_method == sync.AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS


def test_official_bridge_routes_forward_all_write_paths(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        return FakeResp({"id": 99})

    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    cases = [
        ("PUT", "/v1/toolhub/tools/my-tool/", {"title": "T"}, "PUT", "/api/tools/my-tool/"),
        ("DELETE", "/v1/toolhub/tools/my-tool/", None, "DELETE", "/api/tools/my-tool/"),
        ("POST", "/v1/toolhub/lists/", {"title": "L"}, "POST", "/api/lists/"),
        ("PUT", "/v1/toolhub/lists/12/", {"title": "L2"}, "PUT", "/api/lists/12/"),
        ("DELETE", "/v1/toolhub/lists/12/", None, "DELETE", "/api/lists/12/"),
        ("POST", "/v1/toolhub/user/favorites/", {"name": "my-tool"}, "POST", "/api/user/favorites/"),
        (
            "POST",
            "/v1/toolhub/crawler/urls/",
            {"url": "https://example.org/toolinfo.json"},
            "POST",
            "/api/crawler/urls/",
        ),
        ("DELETE", "/v1/toolhub/crawler/urls/9/", None, "DELETE", "/api/crawler/urls/9/"),
    ]
    for method, path, payload, _upstream_method, upstream_path in cases:
        resp = client.open(method=method, path=path, json=payload, headers={"X-CSRF-Token": "tok"})
        assert resp.status_code == 200
    assert [(method, url.removeprefix("https://toolhub.wikimedia.org")) for method, url, _json in calls] == [
        (upstream_method, upstream_path) for *_local, upstream_method, upstream_path in cases
    ]


def test_official_json_body_must_be_object(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.post("/v1/toolhub/lists/", data="not json", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "body must be a JSON object"}


def test_official_annotation_failure_is_normalized(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"message": "bad payload"}, 400))
    resp = client.put(
        "/v1/toolhub/tools/my-tool/annotations/",
        json={"tool_type": "web app"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["details"] == {"message": "bad payload"}


def test_official_write_upstream_unavailable(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})

    def fail_request(*_args, **_kwargs):
        raise toolhub.requests.ConnectionError("down")

    monkeypatch.setattr(toolhub.requests, "request", fail_request)
    resp = client.post("/v1/toolhub/tools/", json={"name": "x"}, headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 502
    assert resp.get_json() == {"error": "official Toolhub is unavailable"}


def test_official_bridge_respects_evolved_policy_before_toolhub_call(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    calls = []
    monkeypatch.setattr(authz, "can", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(toolhub.requests, "request", lambda *args, **kwargs: calls.append((args, kwargs)))
    resp = client.post("/v1/toolhub/tools/", json={"name": "x"}, headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 403
    assert calls == []


def test_official_delete_normalizes_204(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({}, 204))
    resp = client.delete("/v1/toolhub/user/favorites/my-tool/", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


# ---- official-first write lifecycle ----------------------------------------


TOOL_WRITE_PAYLOAD = {
    "name": "my-tool",
    "title": "My Tool",
    "description": "Useful tool",
    "url": "https://example.org/tool",
    "repository": "https://example.org/repo",
    "license": "GPL-3.0-or-later",
    "tool_type": "web app",
    "keywords": ["demo", 7],
    "for_wikis": ["en.wikipedia.org"],
    "available_ui_languages": ["en"],
    "deprecated": False,
    "experimental": True,
}


def test_write_lifecycle_validation_helpers_normalize_toolhub_errors():
    assert _message_from_payload({"detail": "  explain it  "}, "fallback") == "explain it"
    assert _message_from_payload({"message": ""}, "fallback") == "fallback"
    assert _message_from_payload("plain", "fallback") == "fallback"
    assert _string_list("not-list") == []
    assert _validation_errors(["plain", {"field": "url"}]) == [{"message": "plain"}, {"field": "url"}]
    assert _validation_errors({"errors": ["bad"]}) == [{"message": "bad"}]
    assert _validation_errors({"title": ["too short"], "url": "bad", "message": "ignored"}) == [
        {"field": "title", "messages": ["too short"]},
        {"field": "url", "messages": ["bad"]},
    ]
    assert _validation_errors("plain") == []
    assert _official_annotation_payload({"audiences": [], "tasks": [], "toolType": None, "icon": None}) == {
        "audiences": [],
        "tasks": [],
        "comment": "Annotated from Toolhub Evolved",
    }
    assert _official_id("not-dict", 5) == 5
    assert v1_write_api._create_toolinfo_url({}) == (None, None)
    assert v1_write_api._create_toolinfo_url({"toolinfoUrl": 7}) == (None, None)
    assert v1_write_api._matching_toolinfo_item("bad", "my-tool") is None
    assert v1_write_api._matching_toolinfo_item([{"name": "other"}, None, {"name": "my-tool"}], "my-tool") == {
        "name": "my-tool"
    }
    assert v1_write_api._matching_toolinfo_item([{"name": "other"}], "my-tool") is None
    merged, enriched = v1_write_api._merge_toolinfo_fields(
        {
            "repository": "https://manual.example/repo",
            "license": "Apache-2.0",
            "toolType": "web app",
            "keywords": ["manual"],
            "forWikis": ["en.wikipedia.org"],
            "uiLanguages": ["en"],
            "deprecated": True,
            "experimental": True,
        },
        {
            "repository": "https://toolinfo.example/repo",
            "license": "MIT",
            "toolType": "bot",
            "keywords": ["crawler"],
            "forWikis": ["commons.wikimedia.org"],
            "uiLanguages": ["fr"],
            "deprecated": True,
            "experimental": True,
        },
    )
    assert enriched == []
    assert merged["repository"] == "https://manual.example/repo"


def test_create_toolinfo_fetch_helpers_reuse_crawler_module(monkeypatch):
    import crawl

    monkeypatch.setattr(crawl, "_fetch_json", lambda _session, url: {"url": url})
    assert v1_write_api._fetch_toolinfo_json_once("https://toolinfo.example/toolinfo.json") == {
        "url": "https://toolinfo.example/toolinfo.json"
    }


def test_create_toolinfo_enrichment_handles_invalid_matching_item(monkeypatch):
    fields = {
        "title": "Manual title",
        "description": "Manual description",
        "url": "https://manual.example/tool",
        "repository": None,
        "license": None,
        "toolType": None,
        "keywords": [],
        "forWikis": [],
        "uiLanguages": [],
        "deprecated": False,
        "experimental": False,
        "origin": "api",
    }
    monkeypatch.setattr(
        v1_write_api,
        "_fetch_toolinfo_json_once",
        lambda _url: {"name": "my-tool", "title": "Incomplete", "url": "https://toolinfo.example/tool"},
    )
    merged, item, result = v1_write_api._create_toolinfo_enrichment(
        fields,
        "my-tool",
        "https://toolinfo.example/toolinfo.json",
    )
    assert merged == fields
    assert item["name"] == "my-tool"
    assert result == {
        "url": "https://toolinfo.example/toolinfo.json",
        "ok": False,
        "matched": True,
        "enrichedFields": [],
        "lastError": "my-tool: toolinfo item is missing name, title, description or url",
    }


def test_record_create_toolinfo_evidence_handles_no_item_and_provider_failure(client, monkeypatch):
    uid = add_user(username="schiste")
    with db.session_scope() as s:
        user = s.get(User, uid)
        v1_write_api._record_create_toolinfo_evidence(
            s,
            user,
            "https://toolinfo.example/no-item.json",
            None,
            {"url": "https://toolinfo.example/no-item.json", "ok": True},
        )

    def fail_verify(*_args, **_kwargs):
        msg = "verification backend failed"
        raise RuntimeError(msg)

    monkeypatch.setattr(v1_api.SIGNED_TOOLINFO_PROVIDER, "verify", fail_verify)
    with db.session_scope() as s:
        user = s.get(User, uid)
        v1_write_api._record_create_toolinfo_evidence(
            s,
            user,
            "https://toolinfo.example/provider-failure.json",
            {"name": "my-tool"},
            {"url": "https://toolinfo.example/provider-failure.json", "ok": True},
        )
    with db.session_scope() as s:
        assert s.query(CrawlerUrl).count() == 2


def test_write_tool_create_fetches_toolinfo_and_records_evidence(client, monkeypatch):
    uid = add_user(username="schiste")
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    toolinfo_item = {
        "name": "my-tool",
        "title": "Toolinfo title",
        "description": "Toolinfo description",
        "url": "https://toolinfo.example/tool",
        "repository": "https://toolinfo.example/repo",
        "license": "MIT",
        "tool_type": "bot",
        "keywords": ["crawler", "evolved"],
        "for_wikis": ["commons.wikimedia.org"],
        "available_ui_languages": ["fr"],
        "deprecated": True,
        "experimental": False,
    }
    official_calls = []
    verify_calls = []

    monkeypatch.setattr(v1_write_api, "_fetch_toolinfo_json_once", lambda url: {**toolinfo_item, "url": url})
    monkeypatch.setattr(
        v1_api.SIGNED_TOOLINFO_PROVIDER,
        "verify",
        lambda s, user, *, toolinfo, evidence_url: verify_calls.append((user.username, toolinfo["name"], evidence_url)),
    )

    def fake_request(method, url, **kwargs):
        official_calls.append((method, url, kwargs.get("json")))
        return FakeResp({"name": "my-tool"}, 201)

    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    payload = {
        "name": "my-tool",
        "title": "Manual title",
        "description": "Manual description",
        "url": "https://manual.example/tool",
        "keywords": [],
        "for_wikis": [],
        "available_ui_languages": [],
        "deprecated": False,
        "experimental": False,
        "toolinfo_url": "https://toolinfo.example/toolinfo.json",
    }
    resp = client.post("/v1/write/tools/", json=payload, headers={"X-CSRF-Token": "tok"})
    data = resp.get_json()
    assert resp.status_code == 201
    assert data["crawlerFetch"] == {
        "url": "https://toolinfo.example/toolinfo.json",
        "ok": True,
        "matched": True,
        "enrichedFields": [
            "repository",
            "license",
            "toolType",
            "keywords",
            "forWikis",
            "uiLanguages",
            "deprecated",
        ],
    }
    assert official_calls[0][2] == {
        "name": "my-tool",
        "title": "Manual title",
        "description": "Manual description",
        "url": "https://manual.example/tool",
        "repository": "https://toolinfo.example/repo",
        "license": "MIT",
        "tool_type": "bot",
        "keywords": ["crawler", "evolved"],
        "for_wikis": ["commons.wikimedia.org"],
        "available_ui_languages": ["fr"],
        "deprecated": True,
        "experimental": False,
        "comment": "Published from Toolhub Evolved",
    }
    assert verify_calls == [("schiste", "my-tool", "https://toolinfo.example/toolinfo.json")]
    with db.session_scope() as s:
        crawler = s.execute(
            select(CrawlerUrl).where(CrawlerUrl.url == "https://toolinfo.example/toolinfo.json")
        ).scalar_one()
        assert crawler.sync_status == "evolved_real"
        assert crawler.last_error is None
        activity = s.execute(select(ActivityRow).where(ActivityRow.kind == "revisions")).scalar_one()
        assert activity.payload["crawlerFetch"]["ok"] is True


def test_write_tool_create_toolinfo_fetch_failure_keeps_official_create(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    official_calls = []

    def fail_fetch(_url):
        msg = "temporary crawler outage"
        raise ValueError(msg)

    def fake_request(method, url, **kwargs):
        official_calls.append(kwargs.get("json"))
        return FakeResp({"name": "my-tool"}, 201)

    monkeypatch.setattr(v1_write_api, "_fetch_toolinfo_json_once", fail_fetch)
    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    resp = client.post(
        "/v1/write/tools/",
        json={**TOOL_WRITE_PAYLOAD, "toolinfo_url": "https://toolinfo.example/toolinfo.json"},
        headers={"X-CSRF-Token": "tok"},
    )
    data = resp.get_json()
    assert resp.status_code == 201
    assert data["crawlerFetch"] == {
        "url": "https://toolinfo.example/toolinfo.json",
        "ok": False,
        "matched": False,
        "enrichedFields": [],
        "lastError": "temporary crawler outage",
    }
    assert "toolinfo_url" not in official_calls[0]
    with db.session_scope() as s:
        crawler = s.execute(
            select(CrawlerUrl).where(CrawlerUrl.url == "https://toolinfo.example/toolinfo.json")
        ).scalar_one()
        assert crawler.sync_status == "sync_error"
        assert crawler.last_error == "temporary crawler outage"


def test_write_tool_create_toolinfo_no_match_stays_in_local_fallback_response(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(v1_write_api, "_fetch_toolinfo_json_once", lambda _url: [{"name": "other-tool"}])
    monkeypatch.setattr(toolhub.requests, "request", lambda *_args, **_kwargs: FakeResp({"message": "bad"}, 400))
    resp = client.post(
        "/v1/write/tools/",
        json={**TOOL_WRITE_PAYLOAD, "toolinfo_url": "https://toolinfo.example/toolinfo.json"},
        headers={"X-CSRF-Token": "tok"},
    )
    data = resp.get_json()
    assert resp.status_code == 202
    assert data["crawlerFetch"] == {
        "url": "https://toolinfo.example/toolinfo.json",
        "ok": False,
        "matched": False,
        "enrichedFields": [],
        "lastError": "my-tool: no matching item found in toolinfo",
    }


def test_write_tool_create_success_clears_local_state_and_emits_activity(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    with db.session_scope() as s:
        s.add(
            ToolRecord(
                tool_name="my-tool",
                user_id=uid,
                created_by_user_id=uid,
                record={"title": "Draft", "description": "d", "url": "https://draft.example"},
            )
        )
        s.add(
            ToolOverlay(
                kind="edits",
                tool_name="my-tool",
                user_id=uid,
                created_by_user_id=uid,
                patch={"title": "Local"},
            )
        )
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        return FakeResp({"name": "my-tool"}, 201)

    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    resp = client.post("/v1/write/tools/", json=TOOL_WRITE_PAYLOAD, headers={"X-CSRF-Token": "tok"})
    data = resp.get_json()
    assert resp.status_code == 201
    assert data["result"] == "official"
    assert data["syncStatus"] == "official"
    assert calls == [
        (
            "POST",
            "https://toolhub.wikimedia.org/api/tools/",
            {
                "name": "my-tool",
                "title": "My Tool",
                "description": "Useful tool",
                "url": "https://example.org/tool",
                "repository": "https://example.org/repo",
                "license": "GPL-3.0-or-later",
                "tool_type": "web app",
                "keywords": ["demo", "7"],
                "for_wikis": ["en.wikipedia.org"],
                "available_ui_languages": ["en"],
                "deprecated": False,
                "experimental": True,
                "comment": "Published from Toolhub Evolved",
            },
        )
    ]
    with db.session_scope() as s:
        assert s.query(ToolRecord).count() == 0
        assert s.query(ToolOverlay).count() == 0
        activity = s.execute(select(ActivityRow).where(ActivityRow.kind == "revisions")).scalar_one()
        assert activity.object_type == "tool"
        assert activity.object_key == "my-tool"
        assert activity.action == "created"
        assert activity.official_status == "official"
        assert activity.last_synced_at is not None
        assert activity.row["officialStatus"] == "official"


def test_write_tool_rejection_stores_overlay_fallback_with_validation_errors(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(
        toolhub.requests,
        "request",
        lambda *a, **k: FakeResp({"message": "bad payload", "title": ["too short"]}, 400),
    )
    payload = {**TOOL_WRITE_PAYLOAD, "name": "ignored", "title": "New title"}
    resp = client.put("/v1/write/tools/live-tool/", json=payload, headers={"X-CSRF-Token": "tok"})
    data = resp.get_json()
    assert resp.status_code == 202
    assert data["result"] == "local_fallback"
    assert data["lastError"] == "bad payload"
    assert data["validationErrors"] == [{"field": "title", "messages": ["too short"]}]
    assert data["toolhubStatus"] == 400
    assert data["toolhubCode"] is None
    assert data["local"]["title"] == "New title"
    with db.session_scope() as s:
        overlay = s.execute(select(ToolOverlay).where(ToolOverlay.tool_name == "live-tool")).scalar_one()
        assert overlay.kind == "edits"
        assert overlay.patch["title"] == "New title"
        assert overlay.sync_status == "local_fallback"
        assert overlay.last_toolhub_response == {"message": "bad payload", "title": ["too short"]}
        assert overlay.validation_errors == [{"field": "title", "messages": ["too short"]}]
        activity = s.execute(select(ActivityRow).where(ActivityRow.kind == "auditlogs")).scalar_one()
        assert activity.official_status == "local_fallback"
        assert activity.last_error == "bad payload"
        assert activity.payload["httpStatus"] == 400
        assert activity.payload["submittedFields"] == [
            "deprecated",
            "description",
            "experimental",
            "forWikis",
            "keywords",
            "license",
            "repository",
            "title",
            "toolType",
            "uiLanguages",
            "url",
        ]
        assert "toolhubResponse" not in activity.payload
        assert "local" not in activity.payload


def test_write_tool_rejection_without_local_permission_returns_official_error(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(
        authz,
        "can",
        lambda _user, action, _resource=None: action == authz.ACTION_TOOLHUB_WRITE,
    )
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"message": "denied"}, 403))
    resp = client.post("/v1/write/tools/", json=TOOL_WRITE_PAYLOAD, headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 403
    assert resp.get_json()["lastError"] == "denied"
    with db.session_scope() as s:
        assert s.query(ToolRecord).count() == 0


def test_write_lifecycle_requires_toolhub_grant_before_fallback(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.post("/v1/write/tools/", json=TOOL_WRITE_PAYLOAD, headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 401
    assert resp.get_json()["reauth"] is True
    with db.session_scope() as s:
        assert s.query(ToolRecord).count() == 0


def test_write_annotations_and_crawler_failures_store_local_fallbacks(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})

    def fake_request(method, url, **kwargs):
        if url.endswith("/api/crawler/urls/"):
            raise toolhub.requests.ConnectionError("down")
        assert method == "PUT"
        assert kwargs["json"]["tool_type"] == "web app"
        return FakeResp({"errors": [{"field": "audiences", "message": "bad"}]}, 400)

    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    resp = client.put(
        "/v1/write/tools/my-tool/annotations/",
        json={"audiences": ["editors"], "tasks": ["patrol"], "tool_type": "web app"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 202
    assert resp.get_json()["validationErrors"] == [{"field": "audiences", "message": "bad"}]
    resp = client.post(
        "/v1/write/crawler/urls/",
        json={"url": "https://example.org/toolinfo.json"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert resp.status_code == 202
    assert resp.get_json()["lastError"] == "official Toolhub is unavailable"
    with db.session_scope() as s:
        anno = s.execute(select(ToolOverlay).where(ToolOverlay.kind == "annos")).scalar_one()
        assert anno.validation_errors == [{"field": "audiences", "message": "bad"}]
        crawler = s.execute(select(CrawlerUrl)).scalar_one()
        assert crawler.sync_status == "local_fallback"
        assert crawler.last_error == "official Toolhub is unavailable"


def test_write_list_and_favorite_success_store_official_sync_metadata(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/lists/77/",
        api_cache.CacheableResponse(200, "application/json", b'{"id":77,"title":"old"}'),
    )
    api_cache.put_success(
        "https://toolhub.wikimedia.org/api/lists/?page=1",
        api_cache.CacheableResponse(200, "application/json", b'{"results":[]}'),
    )
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url.removeprefix("https://toolhub.wikimedia.org"), kwargs.get("json")))
        if url.endswith("/api/user/favorites/"):
            return FakeResp({}, 204)
        return FakeResp({"id": 77}, 201)

    monkeypatch.setattr(toolhub.requests, "request", fake_request)
    list_resp = client.post(
        "/v1/write/lists/",
        json={"clientId": "demo-list", "title": "List", "description": "d", "tools": ["my-tool"]},
        headers={"X-CSRF-Token": "tok"},
    )
    fav_resp = client.post(
        "/v1/write/user/favorites/",
        json={"name": "my-tool"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert list_resp.status_code == 201
    assert list_resp.get_json()["local"]["officialId"] == 77
    assert fav_resp.status_code == 200
    assert fav_resp.get_json()["toolhub"] == {"ok": True}
    assert calls[0][:2] == ("POST", "/api/lists/")
    assert calls[1][:2] == ("POST", "/api/user/favorites/")
    with db.session_scope() as s:
        stored_list = s.get(ToolList, "demo-list")
        assert stored_list.official_list_id == 77
        assert stored_list.sync_status == "official"
        assert stored_list.last_synced_at is not None
        favorite = s.execute(select(Favorite).where(Favorite.tool_name == "my-tool")).scalar_one()
        assert favorite.sync_status == "official"
        assert favorite.last_synced_at is not None
        assert s.query(ApiCache).count() == 0


def test_write_delete_failures_do_not_create_canonical_local_deletions(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"message": "not owner"}, 403))
    resp = client.delete("/v1/write/tools/live-tool/", headers={"X-CSRF-Token": "tok"})
    assert resp.status_code == 403
    assert resp.get_json()["lastError"] == "not owner"
    assert client.delete("/v1/write/lists/12/", headers={"X-CSRF-Token": "tok"}).status_code == 403
    assert client.delete("/v1/write/crawler/urls/9/", headers={"X-CSRF-Token": "tok"}).status_code == 403
    with db.session_scope() as s:
        assert s.query(ToolRecord).count() == 0
        assert s.query(ToolOverlay).count() == 0


def test_write_retry_and_discard_paths_for_fallback_records(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    tool_record = {
        "title": "Retry Tool",
        "description": "Retry me",
        "url": "https://retry.example",
        "repository": None,
        "license": None,
        "toolType": None,
        "keywords": [],
        "forWikis": [],
        "uiLanguages": [],
        "deprecated": False,
        "experimental": False,
        "origin": "api",
    }
    with db.session_scope() as s:
        s.add(
            ToolRecord(
                tool_name="retry-tool",
                user_id=uid,
                created_by_user_id=uid,
                record=tool_record,
                sync_status="local_fallback",
            )
        )
        s.add(
            ToolOverlay(
                kind="edits",
                tool_name="edit-retry",
                user_id=uid,
                created_by_user_id=uid,
                patch={k: v for k, v in TOOL_WRITE_PAYLOAD.items() if k != "name"},
                sync_status="local_fallback",
            )
        )
        s.add(
            ToolOverlay(
                kind="annos",
                tool_name="anno-tool",
                user_id=uid,
                created_by_user_id=uid,
                patch={"audiences": ["editors"], "tasks": []},
                sync_status="local_fallback",
            )
        )
        s.add(
            ToolList(
                client_id="demo-retry",
                user_id=uid,
                created_by_user_id=uid,
                title="Retry List",
                description="d",
                tools=["retry-tool"],
                sync_status="local_fallback",
            )
        )
        s.add(
            ToolList(
                client_id="demo-discard",
                user_id=uid,
                created_by_user_id=uid,
                title="Discard List",
                description="d",
                tools=[],
                sync_status="local_fallback",
            )
        )
        s.add(
            CrawlerUrl(
                user_id=uid,
                created_by_user_id=uid,
                url="https://retry.example/toolinfo.json",
                sync_status="local_fallback",
            )
        )
        s.flush()
        crawler_id = s.execute(select(CrawlerUrl.id)).scalar_one()
        s.add(
            CrawlerUrl(
                user_id=uid,
                created_by_user_id=uid,
                url="https://discard.example/toolinfo.json",
                sync_status="local_fallback",
            )
        )
        s.flush()
        discard_crawler_id = (
            s.execute(select(CrawlerUrl.id).where(CrawlerUrl.url == "https://discard.example/toolinfo.json"))
            .scalars()
            .one()
        )
        s.add(Favorite(user_id=uid, created_by_user_id=uid, tool_name="retry-tool", sync_status="local_fallback"))
        s.add(Favorite(user_id=uid, created_by_user_id=uid, tool_name="discard-tool", sync_status="local_fallback"))

    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"id": 501}))
    assert (
        client.post(
            "/v1/write/tools/retry-tool/retry/",
            json={"kind": "new"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/write/tools/edit-retry/retry/",
            json={"kind": "edit"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    assert (
        client.delete(
            "/v1/write/tools/anno-tool/fallback/",
            json={"kind": "annotations"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    assert client.post("/v1/write/lists/demo-retry/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert client.delete("/v1/write/lists/demo-discard/fallback/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert (
        client.post(f"/v1/write/crawler/urls/{crawler_id}/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    )
    assert (
        client.delete(
            f"/v1/write/crawler/urls/{discard_crawler_id}/fallback/", headers={"X-CSRF-Token": "tok"}
        ).status_code
        == 200
    )
    assert client.post("/v1/write/user/favorites/retry-tool/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert (
        client.delete("/v1/write/user/favorites/discard-tool/fallback/", headers={"X-CSRF-Token": "tok"}).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/write/tools/missing/retry/",
            json={"kind": "nope"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 400
    )
    with db.session_scope() as s:
        assert s.query(ToolRecord).count() == 0
        assert s.query(ToolOverlay).count() == 0
        assert s.get(ToolList, "demo-retry").sync_status == "official"
        assert s.get(ToolList, "demo-discard").deleted_at is not None
        assert s.get(CrawlerUrl, crawler_id).sync_status == "official"
        assert s.get(CrawlerUrl, discard_crawler_id) is None
        assert (
            s.execute(select(Favorite).where(Favorite.tool_name == "retry-tool")).scalar_one().sync_status == "official"
        )
        assert s.execute(select(Favorite).where(Favorite.tool_name == "discard-tool")).scalar_one_or_none() is None


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/v1/write/tools/", "not-json"),
        ("POST", "/v1/write/tools/", {"name": "bad"}),
        ("POST", "/v1/write/tools/", {**TOOL_WRITE_PAYLOAD, "toolinfo_url": "http://example.org/toolinfo.json"}),
        ("DELETE", "/v1/write/tools/%20/", None),
        ("PUT", "/v1/write/tools/%20/annotations/", {}),
        ("PUT", "/v1/write/tools/my-tool/annotations/", "not-json"),
        ("POST", "/v1/write/lists/", "not-json"),
        ("POST", "/v1/write/lists/", {"title": ""}),
        ("PUT", "/v1/write/lists/not-a-number/", {"title": "L", "tools": []}),
        ("DELETE", "/v1/write/lists/not-a-number/", None),
        ("POST", "/v1/write/user/favorites/", "not-json"),
        ("POST", "/v1/write/user/favorites/", {}),
        ("DELETE", "/v1/write/user/favorites/%20/", None),
        ("POST", "/v1/write/crawler/urls/", "not-json"),
        ("POST", "/v1/write/crawler/urls/", {"url": "http://example.org/toolinfo.json"}),
        ("POST", "/v1/write/tools/%20/retry/", {"kind": "new"}),
        ("DELETE", "/v1/write/tools/%20/fallback/", {"kind": "new"}),
        ("DELETE", "/v1/write/tools/my-tool/fallback/", {}),
        ("POST", "/v1/write/user/favorites/%20/retry/", None),
        ("DELETE", "/v1/write/user/favorites/%20/fallback/", None),
    ],
)
def test_write_lifecycle_rejects_invalid_inputs(client, method, path, body):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    kwargs = {"headers": {"X-CSRF-Token": "tok"}}
    if isinstance(body, dict):
        kwargs["json"] = body
    elif isinstance(body, str):
        kwargs["data"] = body
    resp = client.open(method=method, path=path, **kwargs)
    assert resp.status_code == 400


def test_write_tool_create_invalid_toolinfo_url_reports_field_validation(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.post(
        "/v1/write/tools/",
        json={**TOOL_WRITE_PAYLOAD, "toolinfo_url": "https://"},
        headers={"X-CSRF-Token": "tok"},
    )

    assert resp.status_code == 400
    data = resp.get_json()
    assert data["lastError"] == "toolinfo URL must include a host."
    assert data["validationErrors"] == [{"field": "toolinfo_url", "message": "toolinfo URL must include a host."}]


def test_write_crawler_url_invalid_url_reports_field_validation(client):
    uid = add_user()
    sign_in(client, uid)
    resp = client.post(
        "/v1/write/crawler/urls/",
        json={"url": "https://"},
        headers={"X-CSRF-Token": "tok"},
    )

    assert resp.status_code == 400
    data = resp.get_json()
    assert data["lastError"] == "crawler URL must include a host."
    assert data["validationErrors"] == [{"field": "url", "message": "crawler URL must include a host."}]


def test_write_lifecycle_success_paths_for_deletes_annotations_and_crawler(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    with db.session_scope() as s:
        s.add(
            ToolList(
                client_id="12",
                user_id=uid,
                created_by_user_id=uid,
                title="Official list cache",
                tools=["my-tool"],
                official_list_id=12,
            )
        )
        s.add(
            CrawlerUrl(
                user_id=uid,
                created_by_user_id=uid,
                url="https://example.org/toolinfo.json",
                official_crawler_url_id=9,
            )
        )
        s.add(Favorite(user_id=uid, created_by_user_id=uid, tool_name="my-tool"))

    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"id": 99}, 200))
    assert (
        client.put(
            "/v1/write/tools/my-tool/annotations/",
            json={"audiences": [], "tasks": [], "icon": "https://example.org/icon.png"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 200
    )
    assert client.delete("/v1/write/tools/my-tool/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert client.delete("/v1/write/lists/12/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    crawler_add = client.post(
        "/v1/write/crawler/urls/",
        json={"url": "https://example.org/new-toolinfo.json"},
        headers={"X-CSRF-Token": "tok"},
    )
    assert crawler_add.status_code == 200
    assert crawler_add.get_json()["local"]["officialId"] == 99
    assert client.delete("/v1/write/crawler/urls/9/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    assert client.delete("/v1/write/user/favorites/my-tool/", headers={"X-CSRF-Token": "tok"}).status_code == 200
    with db.session_scope() as s:
        assert s.get(ToolList, "12").deleted_at is not None
        crawler = s.execute(select(CrawlerUrl).where(CrawlerUrl.official_crawler_url_id == 9)).scalar_one()
        assert crawler.enabled is False
        assert s.execute(select(Favorite).where(Favorite.tool_name == "my-tool")).scalar_one_or_none() is None


def test_write_create_list_favorite_and_delete_fallback_paths(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"message": "fallback please"}, 400))
    tool_resp = client.post("/v1/write/tools/", json=TOOL_WRITE_PAYLOAD, headers={"X-CSRF-Token": "tok"})
    tool_retry_resp = client.post("/v1/write/tools/", json=TOOL_WRITE_PAYLOAD, headers={"X-CSRF-Token": "tok"})
    list_resp = client.post(
        "/v1/write/lists/",
        json={"clientId": "demo-local", "title": "Local", "tools": ["my-tool"]},
        headers={"X-CSRF-Token": "tok"},
    )
    fav_resp = client.post(
        "/v1/write/user/favorites/",
        json={"name": "my-tool"},
        headers={"X-CSRF-Token": "tok"},
    )
    fav_delete_resp = client.delete("/v1/write/user/favorites/my-tool/", headers={"X-CSRF-Token": "tok"})
    assert tool_resp.status_code == 202
    assert tool_retry_resp.status_code == 202
    assert list_resp.status_code == 202
    assert fav_resp.status_code == 202
    assert fav_delete_resp.status_code == 202
    with db.session_scope() as s:
        assert (
            s.execute(select(ToolRecord).where(ToolRecord.tool_name == "my-tool")).scalar_one().sync_status
            == "local_fallback"
        )
        assert s.get(ToolList, "demo-local").sync_status == "local_fallback"
        assert s.execute(select(Favorite).where(Favorite.tool_name == "my-tool")).scalar_one_or_none() is None


def test_write_lifecycle_no_grant_branches_on_existing_retry_records(client):
    uid = add_user()
    sign_in(client, uid)
    with db.session_scope() as s:
        s.add(
            ToolOverlay(
                kind="edits",
                tool_name="edit-tool",
                user_id=uid,
                created_by_user_id=uid,
                patch=TOOL_WRITE_PAYLOAD,
            )
        )
        s.add(ToolList(client_id="demo-list", user_id=uid, created_by_user_id=uid, title="L", tools=[]))
        s.add(CrawlerUrl(user_id=uid, created_by_user_id=uid, url="https://example.org/toolinfo.json"))
        s.flush()
        crawler_id = s.execute(select(CrawlerUrl.id)).scalar_one()
        s.add(Favorite(user_id=uid, created_by_user_id=uid, tool_name="my-tool"))
    cases = [
        ("DELETE", "/v1/write/tools/edit-tool/", None),
        ("PUT", "/v1/write/tools/edit-tool/annotations/", {}),
        ("PUT", "/v1/write/lists/12/", {"title": "L", "tools": []}),
        ("DELETE", "/v1/write/lists/12/", None),
        ("POST", "/v1/write/user/favorites/", {"name": "my-tool"}),
        ("DELETE", "/v1/write/user/favorites/my-tool/", None),
        ("POST", "/v1/write/crawler/urls/", {"url": "https://example.org/new.json"}),
        ("DELETE", "/v1/write/crawler/urls/9/", None),
        ("POST", "/v1/write/tools/edit-tool/retry/", {"kind": "edit"}),
        ("POST", "/v1/write/lists/demo-list/retry/", None),
        ("POST", f"/v1/write/crawler/urls/{crawler_id}/retry/", None),
        ("POST", "/v1/write/user/favorites/my-tool/retry/", None),
    ]
    for method, path, body in cases:
        kwargs = {"headers": {"X-CSRF-Token": "tok"}}
        if body is not None:
            kwargs["json"] = body
        assert client.open(method=method, path=path, **kwargs).status_code == 401


def test_write_retry_failure_and_missing_record_paths(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    with db.session_scope() as s:
        s.add(
            ToolOverlay(
                kind="edits",
                tool_name="edit-tool",
                user_id=uid,
                created_by_user_id=uid,
                patch={k: v for k, v in TOOL_WRITE_PAYLOAD.items() if k != "name"},
                sync_status="local_fallback",
            )
        )
        s.add(
            ToolRecord(
                tool_name="new-fail",
                user_id=uid,
                created_by_user_id=uid,
                record={
                    "title": "New Fail",
                    "description": "Retry fail",
                    "url": "https://new-fail.example",
                    "repository": None,
                    "license": None,
                    "toolType": None,
                    "keywords": [],
                    "forWikis": [],
                    "uiLanguages": [],
                    "deprecated": False,
                    "experimental": False,
                    "origin": "api",
                },
                sync_status="local_fallback",
            )
        )
        s.add(
            ToolList(
                client_id="demo-fail",
                user_id=uid,
                created_by_user_id=uid,
                title="Fail List",
                tools=[],
                sync_status="local_fallback",
            )
        )
        s.add(
            CrawlerUrl(
                user_id=uid,
                created_by_user_id=uid,
                url="https://fail.example/toolinfo.json",
                sync_status="local_fallback",
            )
        )
        s.flush()
        crawler_id = s.execute(select(CrawlerUrl.id)).scalar_one()
        s.add(Favorite(user_id=uid, created_by_user_id=uid, tool_name="fail-tool", sync_status="local_fallback"))
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"message": "still bad"}, 400))
    assert (
        client.post(
            "/v1/write/tools/edit-tool/retry/",
            json={"kind": "edit"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 202
    )
    assert (
        client.post(
            "/v1/write/tools/new-fail/retry/",
            json={"kind": "new"},
            headers={"X-CSRF-Token": "tok"},
        ).status_code
        == 202
    )
    assert client.post("/v1/write/lists/demo-fail/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 202
    assert (
        client.post(f"/v1/write/crawler/urls/{crawler_id}/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 202
    )
    assert client.post("/v1/write/user/favorites/fail-tool/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 202
    missing_cases = [
        ("POST", "/v1/write/tools/missing/retry/", {"kind": "new"}),
        ("POST", "/v1/write/tools/missing/retry/", {"kind": "edit"}),
        ("DELETE", "/v1/write/tools/missing/fallback/", {"kind": "new"}),
        ("POST", "/v1/write/lists/missing/retry/", None),
        ("DELETE", "/v1/write/lists/missing/fallback/", None),
        ("POST", "/v1/write/crawler/urls/999/retry/", None),
        ("DELETE", "/v1/write/crawler/urls/999/fallback/", None),
        ("POST", "/v1/write/user/favorites/missing/retry/", None),
        ("DELETE", "/v1/write/user/favorites/missing/fallback/", None),
    ]
    for method, path, body in missing_cases:
        kwargs = {"headers": {"X-CSRF-Token": "tok"}}
        if body is not None:
            kwargs["json"] = body
        assert client.open(method=method, path=path, **kwargs).status_code == 404


def test_write_retry_permission_denials_for_owned_fallback_records(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    with db.session_scope() as s:
        s.add(ToolList(client_id="demo-denied", user_id=uid, created_by_user_id=uid, title="L", tools=[]))
        s.add(CrawlerUrl(user_id=uid, created_by_user_id=uid, url="https://denied.example/toolinfo.json"))
        s.flush()
        crawler_id = s.execute(select(CrawlerUrl.id)).scalar_one()
        s.add(Favorite(user_id=uid, created_by_user_id=uid, tool_name="denied-tool"))
    monkeypatch.setattr(
        authz,
        "can",
        lambda _user, action, _resource=None: action == authz.ACTION_TOOLHUB_WRITE,
    )
    assert client.post("/v1/write/lists/demo-denied/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 403
    assert (
        client.post(f"/v1/write/crawler/urls/{crawler_id}/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 403
    )
    assert (
        client.post("/v1/write/user/favorites/denied-tool/retry/", headers={"X-CSRF-Token": "tok"}).status_code == 403
    )


def test_write_lifecycle_local_permission_denials_after_official_rejection(client, monkeypatch):
    uid = add_user()
    sign_in(client, uid)
    toolhub.save_grant(uid, {"access_token": "at"})
    monkeypatch.setattr(
        authz,
        "can",
        lambda _user, action, _resource=None: action == authz.ACTION_TOOLHUB_WRITE,
    )
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"message": "no local"}, 400))
    cases = [
        ("PUT", "/v1/write/tools/my-tool/annotations/", {"audiences": []}),
        ("POST", "/v1/write/lists/", {"title": "L", "tools": []}),
        ("POST", "/v1/write/user/favorites/", {"name": "my-tool"}),
        ("DELETE", "/v1/write/user/favorites/my-tool/", None),
        ("POST", "/v1/write/crawler/urls/", {"url": "https://example.org/toolinfo.json"}),
    ]
    for method, path, body in cases:
        kwargs = {"headers": {"X-CSRF-Token": "tok"}}
        if body is not None:
            kwargs["json"] = body
        assert client.open(method=method, path=path, **kwargs).status_code == 400


# ---- oauth -----------------------------------------------------------------


def test_v1_config_reports_oauth(client, monkeypatch):
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("TOOLHUB_DEV_LOGIN", raising=False)
    monkeypatch.delenv("TOOLHUB_GITHUB_TOKEN", raising=False)
    assert client.get("/v1/config/").get_json() == {
        "oauth": False,
        "officialWrites": False,
        "devLogin": False,
        "issueReports": False,
    }
    configure_oauth(monkeypatch)
    assert client.get("/v1/config/").get_json() == {
        "oauth": True,
        "officialWrites": True,
        "devLogin": False,
        "issueReports": False,
    }


def test_issue_report_requires_approval(client):
    uid = add_user("Reporter")
    sign_in(client, uid)
    response = client.post(
        "/v1/issue-reports/",
        json={"clientId": "report12345678", "title": "A report", "description": "Details", "context": {}},
        headers={"X-CSRF-Token": "tok"},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "explicit issue approval is required"


def test_issue_report_publishes_once_and_is_idempotent(client, monkeypatch):
    uid = add_user("Reporter")
    sign_in(client, uid)
    monkeypatch.setenv("TOOLHUB_GITHUB_TOKEN", "server-only")
    calls = []

    def publish(title, body):
        calls.append((title, body))
        return {
            "number": 123,
            "url": "https://github.com/schiste/toolhub-evolved/issues/123",
            "repository": "schiste/toolhub-evolved",
        }

    monkeypatch.setattr(github_issues, "publish_issue", publish)
    payload = {
        "approved": True,
        "clientId": "report12345678",
        "title": "A report",
        "description": "Details",
        "context": {"path": "/tools/example", "console": []},
    }
    first = client.post("/v1/issue-reports/", json=payload, headers={"X-CSRF-Token": "tok"})
    second = client.post("/v1/issue-reports/", json=payload, headers={"X-CSRF-Token": "tok"})
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.get_json() == second.get_json()
    assert len(calls) == 1
    assert "## Context" in calls[0][1]
    with db.session_scope() as s:
        assert s.get(IssueReport, "report12345678").issue_number == 123


def test_dev_login_creates_local_session_without_toolhub_grant(client, monkeypatch):
    monkeypatch.setenv("TOOLHUB_INSECURE_COOKIES", "1")
    monkeypatch.setenv("TOOLHUB_DEV_LOGIN", "1")
    resp = client.get("/oauth/dev-login?username=Schiste&next=/my-tools")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/my-tools"
    me = client.get("/v1/user/").get_json()
    assert me["authenticated"] is True
    assert me["username"] == "Schiste"
    assert me["officialWrites"] is False
    assert me["csrf"]
    with db.session_scope() as s:
        user = s.execute(select(User).where(User.wm_sub == "local-dev")).scalar_one()
        assert user.username == "Schiste"
        assert s.query(ToolhubToken).count() == 0


def test_dev_login_accepts_loopback_hosts_and_updates_existing_user(client, monkeypatch):
    monkeypatch.setenv("TOOLHUB_INSECURE_COOKIES", "1")
    monkeypatch.setenv("TOOLHUB_DEV_LOGIN", "1")
    uid = add_user(username="Old Dev", wm_sub="local-dev")
    toolhub.save_grant(uid, {"access_token": "stale"})

    resp = client.get(
        "/oauth/dev-login?username=New%20Dev&next=/favorites",
        base_url="http://127.0.0.1:8000",
    )

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/favorites"
    assert client.get("/v1/user/", base_url="http://127.0.0.1:8000").get_json()["username"] == "New Dev"
    with db.session_scope() as s:
        user = s.execute(select(User).where(User.wm_sub == "local-dev")).scalar_one()
        assert user.username == "New Dev"
        assert s.query(ToolhubToken).count() == 0

    resp = client.get(
        "/oauth/dev-login?username=Ipv6%20Dev&user_id=ipv6-dev",
        base_url="http://[::1]:8000",
    )

    assert resp.status_code == 302
    with db.session_scope() as s:
        user = s.execute(select(User).where(User.wm_sub == "ipv6-dev")).scalar_one()
        assert user.username == "Ipv6 Dev"


def test_dev_login_is_hidden_unless_explicitly_local(client, monkeypatch):
    monkeypatch.setenv("TOOLHUB_INSECURE_COOKIES", "1")
    monkeypatch.delenv("TOOLHUB_DEV_LOGIN", raising=False)
    assert client.get("/oauth/dev-login").status_code == 404
    monkeypatch.setenv("TOOLHUB_DEV_LOGIN", "1")
    assert client.get("/v1/config/", headers={"Host": "toolhub-evolved.toolforge.org"}).get_json()["devLogin"] is False
    assert client.get("/oauth/dev-login", headers={"Host": "toolhub-evolved.toolforge.org"}).status_code == 404


def test_dev_login_sanitizes_redirects_and_identity(client, monkeypatch):
    monkeypatch.setenv("TOOLHUB_INSECURE_COOKIES", "1")
    monkeypatch.setenv("TOOLHUB_DEV_LOGIN", "1")
    monkeypatch.setenv("TOOLHUB_DEV_USERNAME", "Env Dev")
    monkeypatch.setenv("TOOLHUB_DEV_USER_ID", "env-dev")
    resp = client.get("/oauth/dev-login?next=https://attacker.example/&username=")
    assert resp.headers["Location"] == "/my-tools"
    assert client.get("/v1/user/").get_json()["username"] == "Env Dev"


def test_oauth_login_unconfigured(client, monkeypatch):
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_SECRET", raising=False)
    assert client.get("/oauth/login").status_code == 503


def test_oauth_login_redirects(client, monkeypatch):
    configure_oauth(monkeypatch)
    resp = client.get("/oauth/login")
    assert resp.status_code == 302
    assert "toolhub.wikimedia.org/o/authorize/" in resp.headers["Location"]
    assert "client_id=cid" in resp.headers["Location"]
    assert "scope=read+write" in resp.headers["Location"]


def test_oauth_login_refuses_to_derive_the_callback_from_request_headers(client, monkeypatch):
    configure_oauth(monkeypatch)
    monkeypatch.delenv("TOOLHUB_EVOLVED_BASE_URL", raising=False)
    monkeypatch.delenv("TOOLHUB_INSECURE_COOKIES", raising=False)
    assert client.get("/oauth/login").status_code == 503  # no trusted callback → refuse to start the flow


def test_oauth_login_ignores_a_poisoned_host_header(client, monkeypatch):
    configure_oauth(monkeypatch)
    monkeypatch.setenv("TOOLHUB_EVOLVED_BASE_URL", "https://evolved.example")
    resp = client.get("/oauth/login", headers={"Host": "attacker.example", "X-Forwarded-Proto": "http"})
    location = resp.headers["Location"]
    assert "redirect_uri=https%3A%2F%2Fevolved.example%2Foauth%2Fcallback" in location
    assert "attacker.example" not in location


def test_oauth_callback_refuses_when_no_trusted_callback_is_configured(client, monkeypatch):
    configure_oauth(monkeypatch)
    monkeypatch.setenv("TOOLHUB_INSECURE_COOKIES", "1")
    client.get("/oauth/login")
    with client.session_transaction() as sess:
        state = sess["oauth_state"]
        del sess["oauth_redirect_uri"]  # force the fallback path
    monkeypatch.delenv("TOOLHUB_INSECURE_COOKIES", raising=False)
    resp = client.get(f"/oauth/callback?code=c&state={state}")
    assert resp.headers["Location"] == "/?login=error"


def test_oauth_login_uses_configured_public_base_url(client, monkeypatch):
    configure_oauth(monkeypatch)
    monkeypatch.setenv("TOOLHUB_EVOLVED_BASE_URL", "https://evolved.example")
    resp = client.get("/oauth/login")
    assert "redirect_uri=https%3A%2F%2Fevolved.example%2Foauth%2Fcallback" in resp.headers["Location"]


def test_oauth_callback_rejects_bad_state(client, monkeypatch):
    configure_oauth(monkeypatch)
    resp = client.get("/oauth/callback?code=c&state=unknown")  # no stored state
    assert resp.headers["Location"] == "/?login=error"
    client.get("/oauth/login")
    resp = client.get("/oauth/callback?code=c&state=wrong")  # mismatch
    assert resp.headers["Location"] == "/?login=error"
    client.get("/oauth/login")
    with client.session_transaction() as sess:
        state = sess["oauth_state"]
    resp = client.get(f"/oauth/callback?state={state}")  # missing code
    assert resp.headers["Location"] == "/?login=error"


def test_oauth_callback_unconfigured(client, monkeypatch):
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TOOLHUB_OAUTH_CLIENT_SECRET", raising=False)
    with client.session_transaction() as sess:
        sess["oauth_state"] = "s"
    assert client.get("/oauth/callback?code=c&state=s").headers["Location"] == "/?login=error"


def start_login(client):
    client.get("/oauth/login")
    with client.session_transaction() as sess:
        return sess["oauth_state"]


def test_oauth_callback_upstream_failure(client, monkeypatch):
    configure_oauth(monkeypatch)
    state = start_login(client)

    def fail_post(*_args, **_kwargs):
        raise toolhub.requests.RequestException("down")

    monkeypatch.setattr(toolhub.requests, "post", fail_post)
    assert client.get(f"/oauth/callback?code=c&state={state}").headers["Location"] == "/?login=error"


def test_oauth_callback_bad_profile(client, monkeypatch):
    configure_oauth(monkeypatch)
    state = start_login(client)
    monkeypatch.setattr(toolhub.requests, "post", lambda *a, **k: FakeResp({"access_token": "at"}))
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"unexpected": True}))
    assert client.get(f"/oauth/callback?code=c&state={state}").headers["Location"] == "/?login=error"


def test_oauth_callback_identity_api_failure(client, monkeypatch):
    configure_oauth(monkeypatch)
    state = start_login(client)
    monkeypatch.setattr(toolhub.requests, "post", lambda *a, **k: FakeResp({"access_token": "at"}))
    monkeypatch.setattr(toolhub.requests, "request", lambda *a, **k: FakeResp({"message": "denied"}, 401))
    assert client.get(f"/oauth/callback?code=c&state={state}").headers["Location"] == "/?login=error"


def _toolhub_identity_endpoints(*, detail=None):
    """Answer the two identity endpoints the way official Toolhub actually does.

    /api/user/ is served by the CurrentUser serializer, which carries no
    social_auth whatsoever; only the per-account /api/users/<id>/ row does. A
    fake that returns social_auth from /api/user/ agrees with any code that
    reads it there, and so cannot detect that no login has ever resolved a
    global account id -- which is exactly the bug that shipped.
    """
    account = {"id": 7, "username": "Ada", "social_auth": [{"provider": "wikimedia", "uid": "160"}]}

    def request(method, url, *_args, **_kwargs):
        del method
        if url.endswith("/api/user/"):
            return FakeResp({"id": 7, "username": "Ada", "is_authenticated": True})
        if url.endswith("/api/users/7/"):
            return FakeResp(account, 200) if detail is None else FakeResp(detail, 404)
        raise AssertionError(f"unexpected Toolhub request: {url}")

    return request


def test_oauth_callback_signs_in_when_the_account_row_is_unavailable(client, monkeypatch):
    """Identity is not authentication: a failed global-id lookup must not fail sign-in."""
    configure_oauth(monkeypatch)
    monkeypatch.setattr(toolhub.requests, "post", lambda *a, **k: FakeResp({"access_token": "at", "expires_in": 3600}))
    monkeypatch.setattr(toolhub.requests, "request", _toolhub_identity_endpoints(detail={"detail": "Not found."}))
    state = start_login(client)
    assert client.get(f"/oauth/callback?code=c&state={state}").headers["Location"] == "/"
    assert client.get("/v1/user/").get_json()["authenticated"] is True
    with db.session_scope() as s:
        assert s.query(User).one().wikimedia_global_user_id is None


def test_oauth_callback_success_and_relogin(client, monkeypatch):
    configure_oauth(monkeypatch)
    token_payload = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
    monkeypatch.setattr(toolhub.requests, "post", lambda *a, **k: FakeResp(token_payload))
    monkeypatch.setattr(toolhub.requests, "request", _toolhub_identity_endpoints())
    state = start_login(client)
    assert client.get(f"/oauth/callback?code=c&state={state}").headers["Location"] == "/"
    me = client.get("/v1/user/").get_json()
    assert me["authenticated"] is True
    assert me["username"] == "Ada"
    assert me["csrf"]
    with db.session_scope() as s:
        assert s.query(ToolhubToken).count() == 1
        user = s.query(User).one()
        assert user.wikimedia_global_user_id == "160"
        assert user.person_id is None  # derived identity work cannot gate authentication
        people_index.link_user(s, user)  # the reconciliation worker supplies this projection
    with db.session_scope() as s:
        assert (
            s.query(PersonIdentifier)
            .filter_by(namespace="wikimedia_global_user_id", normalized_value="160")
            .one()
            .person_id
            == s.query(User).one().person_id
        )
    # second login for the same Toolhub user id updates the username instead of duplicating
    monkeypatch.setattr(
        toolhub.requests,
        "request",
        lambda *a, **k: FakeResp({"id": 7, "username": "Ada Renamed", "is_authenticated": True}),
    )
    state = start_login(client)
    client.get(f"/oauth/callback?code=c&state={state}")
    assert client.get("/v1/user/").get_json()["username"] == "Ada Renamed"
    with db.session_scope() as s:
        assert s.query(User).count() == 1


def test_oauth_callback_rolls_back_account_when_grant_storage_fails(client, monkeypatch):
    configure_oauth(monkeypatch)
    monkeypatch.setattr(toolhub.requests, "post", lambda *a, **k: FakeResp({"access_token": "at"}))
    monkeypatch.setattr(
        toolhub.requests,
        "request",
        lambda *a, **k: FakeResp({"id": 7, "username": "Ada", "is_authenticated": True}),
    )
    monkeypatch.setattr(toolhub, "store_grant", lambda *_a, **_k: (_ for _ in ()).throw(SQLAlchemyError("down")))

    state = start_login(client)
    assert client.get(f"/oauth/callback?code=c&state={state}").headers["Location"] == "/?login=error"
    with db.session_scope() as s:
        assert s.query(User).count() == 0
        assert s.query(ToolhubToken).count() == 0


def test_oauth_callback_reports_exhausted_database_lock_without_a_500(client, monkeypatch, caplog):
    configure_oauth(monkeypatch)
    monkeypatch.setattr(toolhub.requests, "post", lambda *a, **k: FakeResp({"access_token": "at"}))
    monkeypatch.setattr(
        toolhub.requests,
        "request",
        lambda *a, **k: FakeResp({"id": 7, "username": "Ada", "is_authenticated": True}),
    )
    locked = SQLAlchemyError("locked")
    locked.orig = RuntimeError(1205, "Lock wait timeout exceeded")
    monkeypatch.setattr(db, "run_with_lock_retry", lambda *_args, **_kwargs: (_ for _ in ()).throw(locked))

    state = start_login(client)
    with caplog.at_level("WARNING", logger="backend.oauth"):
        response = client.get(f"/oauth/callback?code=c&state={state}")

    assert response.status_code == 302
    assert response.headers["Location"] == "/?login=error"
    assert "local database remained locked" in caplog.text


def test_oauth_callback_succeeds_in_production_style_config(client, monkeypatch):
    # Every other OAuth test sets TOOLHUB_INSECURE_COOKIES, which routes _callback_url()
    # down the development branch. Production takes the TOOLHUB_EVOLVED_BASE_URL branch,
    # and that path was never driven through a full login -> callback round trip.
    monkeypatch.setenv("TOOLHUB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("TOOLHUB_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("TOOLHUB_EVOLVED_BASE_URL", "https://toolhub-evolved.toolforge.org")
    monkeypatch.delenv("TOOLHUB_INSECURE_COOKIES", raising=False)
    sent = {}

    def fake_post(_url, **kwargs):
        sent["redirect_uri"] = kwargs["data"]["redirect_uri"]
        return FakeResp({"access_token": "at", "refresh_token": "rt", "expires_in": 3600})

    monkeypatch.setattr(toolhub.requests, "post", fake_post)
    monkeypatch.setattr(
        toolhub.requests,
        "request",
        lambda *a, **k: FakeResp({"id": 7, "username": "Ada", "is_authenticated": True}),
    )
    resp = client.get("/oauth/login")
    assert resp.status_code == 302, "login must not 503 when the base URL is configured"
    with client.session_transaction() as sess:
        state = sess["oauth_state"]
    landed = client.get(f"/oauth/callback?code=c&state={state}").headers["Location"]
    assert sent["redirect_uri"] == "https://toolhub-evolved.toolforge.org/oauth/callback"
    assert landed == "/", f"production config landed on {landed}"
    assert client.get("/v1/user/").get_json()["authenticated"] is True


def test_oauth_callback_logs_a_distinguishable_reason_for_each_failure(client, monkeypatch, caplog):
    configure_oauth(monkeypatch)

    def attempt(**kwargs):
        caplog.clear()
        with caplog.at_level("WARNING", logger="backend.oauth"):
            resp = kwargs.pop("call")()
        assert resp.headers["Location"] == "/?login=error"  # user-facing message stays vague
        return caplog.text

    # A stale/forged state must not look the same in the log as a broken OAuth app.
    state = start_login(client)
    assert "state mismatch" in attempt(call=lambda: client.get("/oauth/callback?code=c&state=wrong"))
    start_login(client)
    assert "without a stored state or a code" in attempt(call=lambda: client.get(f"/oauth/callback?state={state}"))

    # Toolhub naming the cause is the whole point: invalid_client vs invalid_grant is
    # the difference between a bad secret and a stale code.
    def failing_post(*_a, **_k):
        resp = FakeResp({"error": "invalid_client"}, status=401)
        raise toolhub.requests.HTTPError(response=resp)

    monkeypatch.setattr(toolhub.requests, "post", failing_post)
    state = start_login(client)
    text = attempt(call=lambda: client.get(f"/oauth/callback?code=c&state={state}"))
    assert "token endpoint returned HTTP 401" in text
    assert "invalid_client" in text, "Toolhub's own error body must reach the log"

    monkeypatch.setattr(
        toolhub.requests, "post", lambda *_a, **_k: (_ for _ in ()).throw(toolhub.requests.ConnectionError("down"))
    )
    state = start_login(client)
    assert "ConnectionError during the exchange" in attempt(
        call=lambda: client.get(f"/oauth/callback?code=c&state={state}")
    )


def test_oauth_callback_promotes_configured_evolved_role(client, monkeypatch):
    configure_oauth(monkeypatch)
    monkeypatch.setenv(authz.ADMIN_USERS_ENV, "7")
    monkeypatch.setattr(toolhub.requests, "post", lambda *a, **k: FakeResp({"access_token": "at"}))
    monkeypatch.setattr(
        toolhub.requests,
        "request",
        lambda *a, **k: FakeResp({"id": 7, "username": "Ada", "is_authenticated": True}),
    )
    state = start_login(client)
    assert client.get(f"/oauth/callback?code=c&state={state}").headers["Location"] == "/"
    data = client.get("/v1/user/").get_json()
    assert data["evolvedRole"] == "admin"
    assert authz.ACTION_OPERATOR in data["evolvedPermissions"]
    with db.session_scope() as s:
        assert s.query(User).one().role == "admin"


def test_oauth_logout(client):
    uid = add_user()
    toolhub.save_grant(uid, {"access_token": "at"})
    sign_in(client, uid)
    resp = client.post("/oauth/logout", data={"csrf": "tok"})
    assert resp.headers["Location"] == "/"
    assert client.get("/v1/user/").get_json() == {"authenticated": False}
    with db.session_scope() as s:
        assert s.query(ToolhubToken).count() == 0


def test_oauth_logout_without_session(client):
    resp = client.post("/oauth/logout")
    assert resp.headers["Location"] == "/?logout=error"  # no session → no valid CSRF token


def test_oauth_logout_tolerates_sessions_with_no_live_user(client):
    # csrf_ok never touches the database, so both of these reach the bump path
    # with nothing to bump: a session carrying a token but no uid, and one whose
    # account was deleted after the cookie was issued.
    with client.session_transaction() as sess:
        sess["csrf"] = "tok"
    assert client.post("/oauth/logout", data={"csrf": "tok"}).headers["Location"] == "/"
    uid = add_user()
    sign_in(client, uid)
    with db.session_scope() as s:
        s.delete(s.get(User, uid))
    assert client.post("/oauth/logout", data={"csrf": "tok"}).headers["Location"] == "/"


def test_oauth_logout_rejects_get_and_bad_csrf(client):
    uid = add_user()
    sign_in(client, uid)
    assert client.get("/oauth/logout").status_code == 405  # not reachable from <img>/<a>
    resp = client.post("/oauth/logout", data={"csrf": "wrong"})
    assert resp.headers["Location"] == "/?logout=error"
    assert client.get("/v1/user/").get_json()["authenticated"] is True  # still signed in


def test_me_tools_carries_materialized_summaries_without_queueing_builds(client, monkeypatch):
    """The private read ships health scores but never triggers summary builds.

    Building a summary syncs maintainer and people records. Letting a private
    per-user read start that work is what turned this endpoint into a retry
    storm before, so the read has to stay strictly materialized-only.
    """
    uid = add_user(username="Ada Lovelace")
    sign_in(client, uid)
    with db.session_scope() as s:
        user = s.get(User, uid)
        person = people_index.link_user(s, user)
        now = utcnow()
        s.add(
            CanonicalToolCache(
                tool_name="ada-tool",
                record={"name": "ada-tool", "title": "Ada Tool"},
                fetched_at=now,
                expires_at=now,
                stale_until=now,
            )
        )
        s.add(
            ToolPersonRelationship(
                tool_name="ada-tool",
                person_id=person.id,
                relationship_type=sync.PERSON_REL_MAINTAINER,
                verification_status=sync.AUTHOR_CLAIM_VERIFIED,
                confidence=100,
                evidence_count=1,
            )
        )
    queued = []
    monkeypatch.setattr(tool_summaries, "queue_refresh", lambda names, _build: queued.extend(names))
    seen = {}

    def fake_summaries_for(names, build_summary, *, refresh_stale=True, view=tool_summaries.VIEW_FULL):
        seen["names"] = list(names)
        seen["refresh_stale"] = refresh_stale
        seen["view"] = view
        return tool_summaries.SummaryRead(
            results={"ada-tool": {"health": {"score": 71}}},
            cache_meta={"ada-tool": {"status": "fresh"}},
        )

    monkeypatch.setattr(tool_summaries, "summaries_for", fake_summaries_for)

    data = client.get("/v1/me/tools/").get_json()

    assert data["summaries"]["ada-tool"]["health"]["score"] == 71
    assert seen["names"] == ["ada-tool"]
    assert seen["refresh_stale"] is False, "a private read must not queue summary builds"
    assert seen["view"] == tool_summaries.VIEW_CARD, "the signed-in home renders cards, not detail pages"
    assert queued == []


def test_card_view_projects_every_people_identity_and_keeps_the_counts():
    """Cards receive link identities without receiving full person evidence."""
    people = [
        {
            "id": f"person-{index}",
            "displayName": f"Person {index}",
            "profile": {"bio": "large detail-only profile"},
            "relationships": [
                {
                    "type": "maintainer",
                    "status": "verified",
                    "confidence": 100,
                    "evidence": [
                        {"observedName": f"Handle {name_index}", "evidencePayload": {"large": "private"}}
                        for name_index in range(10)
                    ],
                }
            ],
        }
        for index in range(20)
    ]
    full = {
        "toolName": "ada-tool",
        "health": {"score": 71, "grade": "good", "sourceHealth": {"repository": {"branch": "main"}}},
        "maintainerDimension": {"status": "verified-maintainer"},
        "maintainer": {"healthCounts": {"verifiedPeople": 2}, "people": people},
    }
    card = tool_summaries.card_view(full)

    # Everything the card paints up front survives; the popover breakdown is
    # covered separately, since it is fetched after render.
    assert card["health"]["score"] == full["health"]["score"]
    assert card["health"]["grade"] == full["health"]["grade"]
    assert card["maintainerDimension"] == full["maintainerDimension"]
    assert card["maintainer"]["healthCounts"] == {"verifiedPeople": 2}
    assert len(card["maintainer"]["people"]) == len(people)
    first = card["maintainer"]["people"][0]
    assert first == {
        "id": "person-0",
        "displayName": "Person 0",
        "relationships": [
            {
                "type": "maintainer",
                "status": "verified",
                "observedNames": [f"Handle {index}" for index in range(10)],
            }
        ],
    }
    assert len(dumps(card)) < len(dumps(full)) / 2
    # The original is untouched, since it is the cached row's payload.
    assert "people" in full["maintainer"]
    # The count block is mid-rename between `counts` and `healthCounts`. A card
    # that keeps only one name silently loses its confirmed-maintainer byline
    # against a frontend reading the other, so both have to survive.
    legacy = tool_summaries.card_view({"maintainer": {"counts": {"verifiedMaintainers": 3}, "people": [1, 2]}})
    assert legacy["maintainer"] == {"counts": {"verifiedMaintainers": 3}}


def test_card_view_drops_the_popover_breakdown():
    """The breakdown is fetched after render, so it must not ship with the card."""
    full = {
        "health": {
            "score": 71,
            "grade": "good",
            "dimensions": [{"key": "d", "score": 80}],
            "calculation": {"dimensionCount": 4},
            "sourceHealth": {"dimensions": [{"key": "s"}]},
        }
    }
    card = tool_summaries.card_view(full)

    # The chip still renders: score and grade survive.
    assert card["health"]["score"] == 71
    assert card["health"]["grade"] == "good"
    for key in ("dimensions", "calculation", "sourceHealth"):
        assert key not in card["health"], key
    # `dimensions` absent is the marker the frontend reads as "not loaded yet",
    # so it must not be projected as an empty list, which means "none exist".
    assert "dimensions" not in card["health"]
    # The cached row is untouched — the detail page reads it whole.
    assert full["health"]["dimensions"] == [{"key": "d", "score": 80}]


def test_card_view_keeps_an_absent_maintainer_absent():
    """A missing maintainer must not become an empty-but-present one."""
    card = tool_summaries.card_view({"health": {"score": 10}})
    assert "maintainer" not in card
