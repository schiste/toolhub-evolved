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
        "--candidate-label-limit",
        type=int,
        default=int(os.environ.get("PEOPLE_IDENTITY_CANDIDATE_LIMIT", people_reconcile.DEFAULT_CANDIDATE_LABEL_LIMIT)),
        help="maximum unresolved labels to check against Toolhub during an apply run",
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        help="process the bounded incremental queue instead of running a historical scan",
    )
    parser.add_argument(
        "--queue-all",
        action="store_true",
        help="drain all currently actionable queue rows in bounded batches",
    )
    parser.add_argument(
        "--identities-only",
        action="store_true",
        help="resolve a bounded identity batch without rebuilding every tool",
    )
    args = parser.parse_args(argv)
    db.configure(os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL)
    db.init_schema()
    with db.advisory_lock("toolhub-evolved:people-reconcile") as acquired:
        if not acquired:
            sys.stdout.write(json.dumps({"locked": True}, sort_keys=True) + "\n")
            return 0
        if sum((args.queue, args.queue_all, args.identities_only)) > 1:
            parser.error("--queue, --queue-all, and --identities-only are mutually exclusive")
        if args.queue_all:
            summary = people_reconcile.drain_queue()
        elif args.queue:
            summary = people_reconcile.process_queue(
                limit=int(os.environ.get("PEOPLE_RECONCILE_QUEUE_LIMIT", people_reconcile.DEFAULT_QUEUE_LIMIT))
            )
        else:
            mode = people_reconcile.MODE_APPLY if args.apply or args.identities_only else people_reconcile.MODE_DRY_RUN
            with db.session_scope() as session:
                summary = people_reconcile.run(
                    session,
                    mode=mode,
                    discover_candidates=args.apply or args.identities_only,
                    candidate_label_limit=args.candidate_label_limit,
                    rebuild_tools=not args.identities_only,
                )
    sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
    return 1 if int(summary.get("failed") or 0) else 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
