# SPDX-License-Identifier: GPL-3.0-or-later
"""Run deterministic people identity reconciliation for the local catalog."""

from __future__ import annotations

import argparse
import json
import os
import sys

from backend import DEFAULT_DB_URL, db, people_reconcile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="materialize historical edges, merge deterministic identities, and rebuild relationships",
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        help="process the bounded incremental queue instead of running a historical scan",
    )
    args = parser.parse_args(argv)
    db.configure(os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL)
    db.init_schema()
    if args.queue:
        summary = people_reconcile.process_queue(
            limit=int(os.environ.get("PEOPLE_RECONCILE_QUEUE_LIMIT", people_reconcile.DEFAULT_QUEUE_LIMIT))
        )
        sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
        return 0
    mode = people_reconcile.MODE_APPLY if args.apply else people_reconcile.MODE_DRY_RUN
    with db.session_scope() as session:
        summary = people_reconcile.run(session, mode=mode)
    sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
