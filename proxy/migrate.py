# SPDX-License-Identifier: GPL-3.0-or-later
"""One-off data migrations, run once per deploy before the webservice restarts.

Schema setup (`backend.db.init_schema`) runs inside every worker process at
startup and is deliberately DDL-only. Anything proportional to table size has
to live here instead: run from a worker, a row-level migration executes once
per process on every restart, with several workers doing it at once, against
tables live requests need — which is exactly how a deploy turns into an outage.

Every migration below is idempotent and batched into short transactions, so
re-running this is cheap and safe, and a partial run simply resumes.

    tools/deploy.sh runs this automatically. Manually:
        webservice python3.13 shell -- \
          ~/www/python/venv/bin/python ~/repo/proxy/migrate.py
"""

import os
import sys
from dataclasses import dataclass

from backend import DEFAULT_DB_URL, api_cache, canonical_tools, catalog_projection, db


@dataclass(frozen=True)
class MigrationResult:
    """Rows touched by one named migration."""

    name: str
    rows: int

    def log_line(self) -> str:
        """Return the operator-facing summary for one migration."""
        return f"  {self.name}: {self.rows} rows" if self.rows else f"  {self.name}: up to date"


def run_once() -> list[MigrationResult]:
    """Apply every pending data migration and report what each one touched."""
    return [
        MigrationResult("api_cache index columns", api_cache.backfill_index_columns()),
        MigrationResult("canonical search_text", canonical_tools.backfill_search_text()),
        MigrationResult(
            "catalog projections",
            catalog_projection.refresh_candidates(limit=catalog_projection.MAX_REFRESH_TOOLS)["refreshed"],
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    """Jobs/deploy entrypoint: prepare the schema, then migrate row data.

    `--require-configured-db` refuses to run against the local SQLite default.
    Toolforge only injects the tool's environment into webservice and job pods,
    not into a `become` shell, so a deploy step that simply reads TOOLHUB_DB_URL
    silently migrates a stale repo-local database and reports success. This
    makes that failure loud instead.
    """
    args = sys.argv[1:] if argv is None else argv
    configured = os.environ.get("TOOLHUB_DB_URL")
    if "--require-configured-db" in args and not configured:
        sys.stderr.write(
            "migrate: TOOLHUB_DB_URL is unset, so this would migrate the local SQLite default\n"
            "         instead of the configured database. Run it where the tool environment\n"
            "         exists (webservice/job pod), not from a plain `become` shell.\n"
        )
        return 1
    db.configure(configured or DEFAULT_DB_URL)
    db.init_schema()
    sys.stdout.write(f"migrate: dialect={db.engine().dialect.name} configured_db_url={'yes' if configured else 'no'}\n")
    for result in run_once():
        sys.stdout.write(f"{result.log_line()}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - deploy entrypoint, exercised via main() in tests
    raise SystemExit(main())
