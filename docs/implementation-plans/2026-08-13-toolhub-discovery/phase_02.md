# Toolhub Discovery Implementation Plan — Phase 2: Ranked Search

> **For Claude:** REQUIRED SUB-SKILL: Use ed3d-plan-and-execute:executing-an-implementation-plan to implement this plan task-by-task.

**Goal:** Relevance-ranked canonical-catalog search on both database backends, and canonical keywords folded into the search haystack.

**Architecture:** `canonical_tools.search()` keeps its signature and `_payload` response shape but gains a ranked path: SQLite FTS5 (standalone virtual table synced by triggers) in dev, MariaDB InnoDB FULLTEXT (`MATCH ... AGAINST` natural-language mode) on Toolforge ToolsDB (MariaDB 10.6.19 — FULLTEXT supported). LIKE remains as the explicit fallback when no ranked index is available. DDL lives in a new `proxy/backend/search_index.py` invoked from `db.init_schema()`; row-proportional population lives in `proxy/migrate.py`.

**Tech Stack:** SQLAlchemy 2 with raw-SQL `text()` for FTS5/FULLTEXT (no ORM support for MATCH), pytest with in-memory SQLite.

**Scope:** Phase 2 of 5 from `docs/design-plans/2026-08-13-toolhub-discovery.md`. Independent of Phase 1.

**Codebase verified:** 2026-08-13.

---

## Verified facts this phase relies on

- **DESIGN DEVIATION (intentional, carry into all later phases):** the design doc says ranked search surfaces through `/v1/search/tools/`. Verification showed `/v1/search/tools/` (`proxy/backend/v1.py:598-625`) searches locally-registered `ToolRecord` rows and is consumed by `public_html/views/search.js` for federated local results — it must NOT change. The canonical-catalog search is `canonical_tools.search()` (`proxy/backend/canonical_tools.py:304-318`), whose only caller is `/v1/canonical/tools/` (`proxy/backend/v1.py:525-550`, param `q`), consumed by `public_html/lib/core/api.js`. Ranked search goes there.
- `search_text` derivation: `@validates("record")` hook at `models.py:145-156` — joins `name`, `title`, `description`, casefolds, truncates to `SEARCH_TEXT_MAX_CHARS = 4000` (`models.py:30`). Keywords are currently omitted.
- `backfill_search_text` (`canonical_tools.py:239-268`) shows the sanctioned batched-rewrite pattern and the "reassignment re-derives search_text" trick (`row.record = row.record or {}`).
- `db.init_schema()` runs in every worker at startup (schema setup plus cheap idempotent upgrades — see `_upgrade_schema`); anything row-proportional belongs in `proxy/migrate.py` (its module docstring is explicit). The engine is obtained via `db.engine()`; `db.advisory_lock` (`proxy/backend/db.py:324-351`) exists for cross-worker DDL races.
- SQLite FTS5: no ORM support — raw `text()` SQL; standalone FTS5 table is correct here because `canonical_tool_cache` has a TEXT primary key (`tool_name`), and external-content FTS5 requires an INTEGER rowid. `bm25()`/`ORDER BY rank` for ranking (lower rank = better).
- MariaDB FULLTEXT caveats: `innodb_ft_min_token_size` default 3 (2-char tokens unmatchable), default stopword list, TF-IDF-style relevance (not BM25 — fine, both are "relevance ordered").
- FTS5 MATCH has query syntax; raw user input with `"`, `-`, `:` raises `OperationalError`. Always convert user input to quoted phrase tokens.
- **Recall constraint (load-bearing):** today's LIKE search is substring matching, and `public_html/views/search.js:222,251` feeds user-typed partial queries into it via `/v1/canonical/tools/?q=`. Token-based ranked search alone would drop "citat"-style partial matches (FTS5 matches whole tokens; MariaDB additionally ignores tokens under `innodb_ft_min_token_size=3` and stopwords). The implementation below therefore (a) uses prefix matching on the trailing token, and (b) tops up from the LIKE path whenever ranked results come up short — substring recall must not regress.

---

### Task 1: Fold keywords into `search_text`

**Files:**
- Modify: `proxy/backend/models.py:145-156` (`_derive_search_text`) and the comment at `models.py:129-131`
- Test: `tests/proxy/test_canonical_search.py` (create)

**Step 1: Write the failing test**

Create `tests/proxy/test_canonical_search.py`:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Ranked canonical-catalog search across both database backends."""

from datetime import timedelta

import pytest

from backend import canonical_tools, db
from backend.models import CanonicalToolCache, utcnow


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def _add_tool(s, name, *, title="", description="", keywords=None, fetched_at=None):
    s.add(
        CanonicalToolCache(
            tool_name=name,
            record={
                "name": name,
                "title": title,
                "description": description,
                "keywords": keywords or [],
            },
            fetched_at=fetched_at or utcnow(),
            expires_at=utcnow() + timedelta(hours=1),
            stale_until=utcnow() + timedelta(hours=2),
        )
    )


def test_search_text_includes_keywords():
    with db.session_scope() as s:
        _add_tool(s, "sfedits", title="SF edits", description="Edit stream", keywords=["citation", "bot"])
    with db.session_scope() as s:
        row = s.query(CanonicalToolCache).one()
        assert "citation" in row.search_text
        assert "bot" in row.search_text


def test_search_text_ignores_malformed_keywords():
    with db.session_scope() as s:
        _add_tool(s, "weird", title="w", description="d")
        s.add(
            CanonicalToolCache(
                tool_name="weird2",
                record={"name": "weird2", "keywords": "not-a-list"},
                expires_at=utcnow(),
                stale_until=utcnow(),
            )
        )
    with db.session_scope() as s:
        assert s.query(CanonicalToolCache).count() == 2
```

**Step 2: Run to verify failure**

Run: `PYTHONPATH=proxy pytest tests/proxy/test_canonical_search.py -q`
Expected: `test_search_text_includes_keywords` FAILS (keywords absent).

**Step 3: Implement**

In `models.py`, replace the body of `_derive_search_text` (keep the docstring, extend it with one line noting keywords are included for discovery search):

```python
        source = record or {}
        raw_keywords = source.get("keywords")
        keywords = " ".join(str(k or "") for k in raw_keywords) if isinstance(raw_keywords, list) else ""
        parts = (source.get("name"), source.get("title"), source.get("description"), keywords)
        self.search_text = "\n".join(str(part or "") for part in parts).casefold()[:SEARCH_TEXT_MAX_CHARS]
        return record
```

Update the column comment at lines 129-131 to say "name/title/description/keywords".

**Step 4: Run tests** — expect PASS. Then run the whole suite (`PYTHONPATH=proxy pytest tests/proxy -q`): existing tests asserting on `search_text` content may need their expectations extended (fix the tests only where the new keyword content is legitimately present).

**Step 5: Re-derive stored rows via migrate.py**

Add a migration `rederive_search_text_keywords()` to `proxy/migrate.py` following its existing pattern: batched loop (500 rows) ordered by `tool_name`, for each row compute the expected `search_text` (re-assign `row.record = row.record or {}` — the validator re-derives) **only when** the stored value differs from the derived value; return the touched count. Idempotent because the second run derives identical text. Include a test in `tests/proxy/test_canonical_search.py` seeding a row with pre-keyword `search_text` (bypass the validator by updating the column directly with `s.execute(update(...))`), running the migration, and asserting the keyword is now present and a second run touches 0 rows.

**Step 6: Lint and commit**

```bash
ruff check proxy && ruff format proxy
git add proxy/backend/models.py proxy/migrate.py tests/proxy/test_canonical_search.py
git commit -m "feat: include canonical keywords in search haystack"
```

---

### Task 2: Search-index DDL module

**Files:**
- Create: `proxy/backend/search_index.py`
- Modify: `proxy/backend/db.py` (call from `init_schema()` — read the function first and add the call after `create_all`)
- Test: `tests/proxy/test_canonical_search.py` (extend)

**Step 1: Write the failing tests**

```python
from sqlalchemy import text

from backend import search_index


def test_fts_table_and_triggers_created_on_sqlite():
    with db.session_scope() as s:
        names = {
            row[0]
            for row in s.execute(
                text("SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')")
            )
        }
    assert "canonical_tool_search" in names
    assert {"canonical_tool_search_ai", "canonical_tool_search_au", "canonical_tool_search_ad"} <= names


def test_fts_rows_follow_cache_rows():
    with db.session_scope() as s:
        _add_tool(s, "sfedits", title="SF edits", description="stream", keywords=["bot"])
    with db.session_scope() as s:
        assert s.execute(
            text("SELECT count(*) FROM canonical_tool_search WHERE tool_name = 'sfedits'")
        ).scalar() == 1
        s.execute(text("DELETE FROM canonical_tool_cache WHERE tool_name = 'sfedits'"))
    with db.session_scope() as s:
        assert s.execute(text("SELECT count(*) FROM canonical_tool_search")).scalar() == 0


def test_mariadb_ddl_statements_are_stable():
    statements = search_index.mariadb_statements()
    assert any("ADD FULLTEXT INDEX IF NOT EXISTS" in stmt for stmt in statements)
    assert any("canonical_tool_cache" in stmt for stmt in statements)
```

**Step 2: Run to verify failure** — `ImportError` / missing table.

**Step 3: Implement**

Create `proxy/backend/search_index.py`:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Dialect-specific ranked-search index DDL for the canonical tool cache.

SQLAlchemy's create_all cannot express an FTS5 virtual table or add a
FULLTEXT index to an existing table, so this module owns that DDL. All
statements are idempotent (IF NOT EXISTS) because init_schema runs in every
worker process at startup. Population of a freshly created FTS table is
row-proportional and therefore lives in proxy/migrate.py, not here.
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

# Standalone FTS5 table rather than external-content: canonical_tool_cache has
# a TEXT primary key and external content requires an INTEGER rowid. At most
# ~5k rows x 4KB search_text, so duplicating the haystack is cheap.
_SQLITE_STATEMENTS = (
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS canonical_tool_search
    USING fts5(tool_name UNINDEXED, search_text)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS canonical_tool_search_ai
    AFTER INSERT ON canonical_tool_cache BEGIN
      INSERT INTO canonical_tool_search(tool_name, search_text)
      VALUES (new.tool_name, new.search_text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS canonical_tool_search_au
    AFTER UPDATE OF search_text, tool_name ON canonical_tool_cache BEGIN
      DELETE FROM canonical_tool_search WHERE tool_name = old.tool_name;
      INSERT INTO canonical_tool_search(tool_name, search_text)
      VALUES (new.tool_name, new.search_text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS canonical_tool_search_ad
    AFTER DELETE ON canonical_tool_cache BEGIN
      DELETE FROM canonical_tool_search WHERE tool_name = old.tool_name;
    END
    """,
)


def mariadb_statements() -> tuple[str, ...]:
    """Return the MariaDB DDL as data so tests can pin it without a MariaDB."""
    return (
        """
        ALTER TABLE canonical_tool_cache
        ADD FULLTEXT INDEX IF NOT EXISTS ft_canonical_search_text (search_text)
        """,
    )


def ensure_search_index(engine: Engine) -> bool:
    """Create the SQLite ranked-search index if missing.

    SQLite only, deliberately: creating a table's FIRST InnoDB FULLTEXT
    index rebuilds the table — row-proportional work that must not run in
    init_schema (every uWSGI worker executes it at startup; see
    proxy/migrate.py's docstring for why that pattern causes outages). The
    MariaDB index is created once per deploy by the migrate.py migration
    below. Returns False rather than raising when DDL fails: search degrades
    to the LIKE fallback, which must never take the app down — but the
    failure is logged loudly, because a silent False means production
    quietly running unranked forever.
    """
    if engine.dialect.name != "sqlite":
        return False
    try:
        with engine.begin() as conn:
            for statement in _SQLITE_STATEMENTS:
                conn.execute(text(statement))
    except SQLAlchemyError:
        _log.exception("ranked-search index DDL failed; search degrades to LIKE")
        return False
    return True
```

Add `import logging` and `_log = logging.getLogger(__name__)` at the top (the `oauth.py` idiom). Wire into `proxy/backend/db.py`: in `init_schema()` (line 318), after `create_all`, call `search_index.ensure_search_index(engine())` (the accessor at `db.py:310`), using a local import inside `init_schema` to avoid the import cycle.

**The MariaDB index is a migrate.py migration** (added in Step 5 alongside FTS population): `ensure_canonical_fulltext_index()` — on a non-MariaDB session return 0; otherwise take `db.advisory_lock` **binding and checking the result** (the lock yields a bool and, with the default `timeout_seconds=0`, contention returns immediately — see `catalog_statistics.py:274-290` for the idiom):

```python
with db.advisory_lock("canonical-search-index", timeout_seconds=30) as acquired:
    if not acquired:
        return 0
    # ALTER TABLE ... ADD FULLTEXT INDEX IF NOT EXISTS ... (mariadb_statements());
    # IF NOT EXISTS makes re-runs free. Return 1 the run that creates it, else 0.
```

**Step 4: Run tests** — PASS, plus full suite (existing tests create schema constantly; the DDL must be cheap and quiet).

**Step 5: The two migrate.py migrations**

Add both to `proxy/migrate.py` (same pattern as the others) and register them in the run list: `ensure_canonical_fulltext_index()` per Task 2 above (MariaDB-only; advisory-locked; 0 on SQLite), and `populate_canonical_tool_search()`: one idempotent statement executed only on SQLite —

```sql
INSERT INTO canonical_tool_search(tool_name, search_text)
SELECT c.tool_name, c.search_text FROM canonical_tool_cache c
WHERE c.tool_name NOT IN (SELECT tool_name FROM canonical_tool_search)
```

(dialect check via the session/engine; on MariaDB return an untouched result — the FULLTEXT index indexes existing rows itself). Test: seed rows via raw INSERT into `canonical_tool_cache` with triggers dropped (or insert into cache, delete from FTS, run migration, assert restored; second run touches 0).

**Step 6: Lint and commit**

```bash
ruff check proxy && ruff format proxy
git add proxy/backend/search_index.py proxy/backend/db.py proxy/migrate.py tests/proxy/test_canonical_search.py
git commit -m "feat: maintain ranked-search indexes for the canonical cache"
```

---

### Task 3: Ranked `canonical_tools.search()`

**Files:**
- Modify: `proxy/backend/canonical_tools.py:304-318`
- Test: `tests/proxy/test_canonical_search.py` (extend)

**Step 1: Write the failing tests**

```python
def test_search_keeps_substring_recall():
    """The SPA search box sends partial words; ranked search must not lose them."""
    with db.session_scope() as s:
        _add_tool(
            s,
            "citation-hunt",
            title="Citation Hunt",
            description="Find unsourced statements",
            keywords=["citation"],
        )
        _add_tool(s, "sfedits", title="SF edits", description="stream")
    assert "citation-hunt" in [r["toolName"] for r in canonical_tools.search("citat")]
    assert "sfedits" in [r["toolName"] for r in canonical_tools.search("sf")]  # < min token size


def test_search_ranks_by_relevance_not_recency():
    with db.session_scope() as s:
        # Older row is the better match; recency ordering would invert this.
        _add_tool(
            s,
            "citation-hunt",
            title="Citation Hunt",
            description="Find unsourced statements and add citations",
            keywords=["citation", "references"],
            fetched_at=utcnow() - timedelta(days=30),
        )
        _add_tool(
            s,
            "freshtool",
            title="Fresh tool",
            description="Mentions citation once",
            fetched_at=utcnow(),
        )
    results = canonical_tools.search("citation")
    assert [r["toolName"] for r in results][0] == "citation-hunt"
    # Response contract unchanged: same payload keys as tools_by_name.
    assert {"toolName", "record", "sourceUrl", "source", "syncStatus"} <= set(results[0])


def test_search_survives_fts_syntax_characters():
    with db.session_scope() as s:
        _add_tool(s, "sfedits", title="SF edits", description="stream")
    for hostile in ('citation" OR', "a-b", "col:umn", '""', "*"):
        assert isinstance(canonical_tools.search(hostile), list)


def test_search_empty_query_and_fallback():
    with db.session_scope() as s:
        _add_tool(s, "sfedits", title="SF edits", description="stream")
    assert canonical_tools.search("")  # empty query: recency-ordered listing
    with db.session_scope() as s:
        s.execute(text("DROP TABLE canonical_tool_search"))
    assert [r["toolName"] for r in canonical_tools.search("edits")] == ["sfedits"]  # LIKE fallback
```

**Step 2: Run to verify failure** — ranking test fails (recency ordering).

**Step 3: Implement**

In `canonical_tools.py`, keep `search()`'s signature and empty-term behavior; replace the term path:

```python
def _fts_match_expression(term: str) -> str:
    """Convert raw user input into safe FTS5 phrase tokens.

    FTS5 MATCH has operator syntax ("-", ":", quotes) that raises on arbitrary
    input; quoting every whitespace token as a phrase makes any input legal
    and means multi-word queries require all words (implicit AND). The
    trailing token gets a prefix star because interactive callers send
    partial words ("citat") that must still match.
    """
    tokens = [t.replace('"', '""') for t in term.split() if t]
    if not tokens:
        return ""
    quoted = [f'"{t}"' for t in tokens]
    quoted[-1] = f"{quoted[-1]}*"
    return " ".join(quoted)


def _boolean_match_expression(term: str) -> str:
    """MariaDB BOOLEAN MODE expression: every token required, prefix-matched.

    Boolean mode (unlike natural-language mode) supports the trailing "*",
    which is what keeps partial-word queries working; operator characters in
    user input are stripped rather than escaped because none of them occur in
    tool vocabulary.
    """
    tokens = ["".join(ch for ch in t if ch not in '+-<>()~*"@') for t in term.split()]
    return " ".join(f"+{t}*" for t in tokens if t)


def _search_ranked(s: Session, term: str, capped: int) -> list[dict[str, Any]] | None:
    """Relevance-ordered payloads via the dialect's ranked index, or None.

    Takes the caller's session: one search must not cost three transactions.
    """
    match = _fts_match_expression(term)
    if not match:
        return None
    try:
        dialect = s.get_bind().dialect.name
        if dialect == "sqlite":
            names = [
                row[0]
                for row in s.execute(
                    text(
                        "SELECT tool_name FROM canonical_tool_search "
                        "WHERE canonical_tool_search MATCH :match "
                        "ORDER BY rank LIMIT :limit"
                    ),
                    {"match": match, "limit": capped},
                )
            ]
        elif dialect in ("mysql", "mariadb"):
            boolean = _boolean_match_expression(term)
            if not boolean:
                return None
            names = [
                row[0]
                for row in s.execute(
                    text(
                        "SELECT tool_name FROM canonical_tool_cache "
                        "WHERE MATCH(search_text) AGAINST(:q IN BOOLEAN MODE) "
                        "ORDER BY MATCH(search_text) AGAINST(:q IN BOOLEAN MODE) DESC "
                        "LIMIT :limit"
                    ),
                    {"q": boolean, "limit": capped},
                )
            ]
        else:
            return None
        rows = {
            row.tool_name: row
            for row in s.execute(
                select(CanonicalToolCache).where(CanonicalToolCache.tool_name.in_(names))
            ).scalars()
        }
        return [_payload(rows[name]) for name in names if name in rows]
    except SQLAlchemyError:
        # Missing index (fresh DB before migrate has run): degrade to LIKE
        # rather than failing reads.
        return None
```

Then restructure `search()` to use ONE session for the whole operation:

```python
def search(query: str = "", *, limit: int = MAX_SEARCH_RESULTS) -> list[dict[str, Any]]:
    """Search cached canonical records, best matches first.

    Relevance-ranked via the dialect's full-text index when available,
    topped up by the deterministic substring path so partial-word recall
    ("citat", "sf") never regresses; recency-ordered listing when the query
    is empty. Filtering and limiting happen in SQL.
    """
    term = str(query or "").strip().casefold()
    capped = max(1, min(MAX_SEARCH_RESULTS, int(limit or MAX_SEARCH_RESULTS)))
    statement = select(CanonicalToolCache).order_by(CanonicalToolCache.fetched_at.desc(), CanonicalToolCache.tool_name)
    with db.session_scope() as s:
        if not term:
            return [_payload(row) for row in s.execute(statement.limit(capped)).scalars()]
        ranked = _search_ranked(s, term, capped) or []
        if len(ranked) >= capped:
            return ranked
        # Top up from the substring path: token/prefix matching cannot see
        # mid-word fragments ("dits"), and MariaDB drops sub-3-char tokens
        # and stopwords entirely. Ranked hits keep their order and lead.
        # Over-fetch by the ranked count so dedup can't shrink a full page.
        found = {payload["toolName"] for payload in ranked}
        like_statement = statement.where(
            CanonicalToolCache.search_text.like(f"%{_escape_like(term)}%", escape="\\")
        ).limit(capped + len(found))
        extras = [
            _payload(row)
            for row in s.execute(like_statement).scalars()
            if row.tool_name not in found
        ]
    return (ranked + extras)[:capped]
```

Keep imports at the top (`text`, `SQLAlchemyError`, `Session` — check the import block once and add what is missing).

**Step 4: Run tests** — PASS; then full suite + coverage:

Run: `PYTHONPATH=proxy pytest tests/proxy -q --cov --cov-report=term-missing`
Expected: PASS, ≥ 91.7%. `_boolean_match_expression` is pure — test it directly (operator stripping, empty result, prefix stars). The MariaDB execution branch of `_search_ranked` is unreachable on SQLite; do NOT fake it with a stub session (that tests the stub, not MariaDB) — the small uncovered branch is acceptable within the 91.7% overall ratchet, and real MariaDB behavior is exercised by the post-deploy manual check.

**Step 5: Contract test for `/v1/canonical/tools/`**

Grep `tests/proxy/test_backend.py` for `canonical/tools` and extend (or add in `test_canonical_search.py` using the Flask `app`/`client` fixtures from `test_backend.py:143-154`): `GET /v1/canonical/tools/?q=citation` returns the existing shape — keys `count`, `results`, `source`, `syncStatus`, `cachePolicy` — with ranked ordering. This pins the JS consumer's contract (`public_html/lib/core/api.js`).

**Step 6: Lint and commit**

```bash
ruff check proxy && ruff format proxy
git add proxy/backend/canonical_tools.py tests/proxy/
git commit -m "feat: rank canonical tool search by relevance"
```

---

## Phase completion check

- Ranking smoke test green: best textual match beats most-recently-fetched.
- Recall tests green: partial-word ("citat") and sub-3-character ("sf") queries still return their tools — the SPA search box must lose nothing it matches today.
- Hostile query strings return results or empty lists, never 500s.
- `/v1/canonical/tools/` contract test green (shape unchanged).
- Full suite + coverage ratchet green; ruff clean.
- Manual: `PYTHONPATH=proxy python proxy/migrate.py` then `curl 'localhost:8000/v1/canonical/tools/?q=citation'` returns relevance-ordered results on a populated dev DB.
