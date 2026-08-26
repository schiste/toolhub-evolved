<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: a-column-sized-for-a-cursor -->
<!-- Release title: A Column Sized for a Cursor -->
<!-- Source range: f6ae78d4..ab3a2c27 (1 commit) -->

# Technical and Marketing Notes

- `/v1/userscripts/wikis/` returned 500 on every request after the previous deploy: `pymysql.err.DataError: (1406, "Data too long for column 'value' at row 1")`. The roster measures ~300 KiB across 1,028 wikis; `api_cache_meta.value` was `Text`, which MariaDB caps at 65,535 bytes. The rebuild itself succeeded — the failure was the commit.
- Nothing in the suite could have caught it. SQLite ignores declared column widths, so an oversized value is written without complaint by every test that runs against the test database. The guard is therefore a DDL assertion — `ApiCacheMeta.__table__.c.value.type.compile(mysql.dialect()) == "MEDIUMTEXT"` — confirmed to fail when the column is narrowed back, plus a subset check tying the migration's widening list to what the models declare.
- Second defect, and the one that made a slow path into an outage: `_store` shared the request's transaction, so a failed cache write destroyed an answer already in hand. `snapshot()` now stores in its own transaction and logs on failure, degrading to what the endpoint did before the cache existed. `refresh()` still raises, because a job whose only product is the stored row has produced nothing — `userscript_sweep` already reports that as the run's failure.
- `_widen_digest_render_columns` becomes table-driven `_widen_text_columns` over `WIDENED_TEXT_COLUMNS`; `digest_editions` was the first table to hit this ceiling and `api_cache_meta` is the second. Its `NOT NULL` clause is now read back from the column rather than hardcoded, since `MODIFY COLUMN` restates the whole definition and a wrong clause would rewrite nullability while appearing to widen. `DIGEST_RENDER_TEXT` is renamed `LARGE_TEXT` accordingly.
- Validation: 3,215 proxy tests pass, 25 skipped. New coverage on both sides of a failed store, the widening across both tables, a nullable column surviving it, the compiled ceiling, and the widening list against the models. ruff check/format and cspell clean.
