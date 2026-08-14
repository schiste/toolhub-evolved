# SPDX-License-Identifier: GPL-3.0-or-later
"""Run deterministic people identity reconciliation for the local catalog."""

from __future__ import annotations

import argparse
import os

from backend import db, job_runner, people_reconcile


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
        "--registry-label-limit",
        type=int,
        default=int(os.environ.get("PEOPLE_REGISTRY_LABEL_LIMIT", "0")),
        help="handle-shaped labels to resolve against CentralAuth per run (0 disables)",
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        help="process the bounded incremental queue instead of running a historical scan",
    )
    parser.add_argument(
        "--retirements",
        action="store_true",
        help="drain confirmed canonical-retirement rows before deployment",
    )
    parser.add_argument(
        "--identities-only",
        action="store_true",
        help="resolve a bounded identity batch without rebuilding every tool",
    )
    args = parser.parse_args(argv)
    # Argument validation needs no database and no lock, so it happens before
    # either is taken rather than after winning a race for them.
    if sum((args.queue, args.retirements, args.identities_only)) > 1:
        parser.error("--queue, --retirements, and --identities-only are mutually exclusive")

    def body() -> dict:
        if args.retirements:
            return people_reconcile.drain_queue(reason="canonical_retired")
        if args.queue:
            return people_reconcile.process_queue(
                limit=int(os.environ.get("PEOPLE_RECONCILE_QUEUE_LIMIT", people_reconcile.DEFAULT_QUEUE_LIMIT))
            )
        mode = people_reconcile.MODE_APPLY if args.apply or args.identities_only else people_reconcile.MODE_DRY_RUN
        discover = args.apply or args.identities_only
        if discover and not args.identities_only:
            with db.session_scope() as session:
                local_summary = people_reconcile.run(
                    session,
                    mode=mode,
                    discover_candidates=False,
                    rebuild_tools=True,
                    sync_accounts=True,
                )
        else:
            local_summary = None
        resolved_identities, resolved_registry = (
            people_reconcile.resolve_remote_batches(
                candidate_label_limit=args.candidate_label_limit,
                registry_label_limit=args.registry_label_limit,
            )
            if discover
            else (None, None)
        )
        with db.session_scope() as session:
            summary = people_reconcile.run(
                session,
                mode=mode,
                discover_candidates=discover,
                candidate_label_limit=args.candidate_label_limit,
                registry_label_limit=args.registry_label_limit,
                rebuild_tools=not args.identities_only and local_summary is None,
                sync_accounts=not args.identities_only and local_summary is None,
                resolved_identity_candidates=resolved_identities,
                resolved_registry_candidates=resolved_registry,
            )
        if local_summary is not None:
            summary["toolsRebuilt"] = local_summary["toolsRebuilt"]
            summary["localPhase"] = local_summary
        return summary

    # Per backend.job_contract: tools this pass could not reconcile stay queued
    # with their retry state and are reported as `failed`. The sweep ran, so it
    # must not count toward the guard's breaker -- this is the job whose
    # ten-day outage the breaker and lock work came from.
    return job_runner.run_job("people-reconcile", body, lock=True)


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
