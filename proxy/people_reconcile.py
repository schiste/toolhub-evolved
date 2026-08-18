# SPDX-License-Identifier: GPL-3.0-or-later
"""Run deterministic people identity reconciliation for the local catalog."""

from __future__ import annotations

import argparse
import os

from backend import db, job_runner, people_reconcile

# --reconverge runs hourly, but the lock it shares is held for the whole of the
# weekly full pass -- longer than the gap between two reconverge runs. So the
# job's premise that "skipped now, converges an hour later" costs nothing does
# not hold while that pass runs: it is skipped every hour until the pass ends.
# On 2026-08-17 five consecutive attempts were skipped that way. Queueing
# briefly turns that run of skips into one short wait. Only this mode waits:
# the per-minute drain has another attempt sixty seconds later and should keep
# skipping, and the full pass is the run everyone else is waiting on.
RECONVERGE_LOCK_WAIT_SECONDS = 120


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
    parser.add_argument(
        "--reconverge",
        action="store_true",
        help="re-decide a bounded batch of unresolved attributions against present evidence",
    )
    parser.add_argument(
        "--reconverge-limit",
        type=int,
        default=int(os.environ.get("PEOPLE_RECONVERGE_LIMIT", people_reconcile.DEFAULT_RECONVERGE_LIMIT)),
        help="unresolved attribution rows to re-decide per run (0 disables)",
    )
    args = parser.parse_args(argv)
    # Argument validation needs no database and no lock, so it happens before
    # either is taken rather than after winning a race for them.
    if sum((args.queue, args.retirements, args.identities_only, args.reconverge)) > 1:
        parser.error("--queue, --retirements, --identities-only, and --reconverge are mutually exclusive")

    def body() -> dict:
        if args.retirements:
            return people_reconcile.drain_queue(reason="canonical_retired")
        if args.reconverge:
            with db.session_scope() as session:
                return people_reconcile.reconverge_attributions(session, limit=args.reconverge_limit)
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
                    # The remote phase below is the one that runs after every
                    # evidence write, so only it reconverges. Doing it twice
                    # would advance the cursor past rows this pass never read.
                    reconverge_limit=0,
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
                reconverge_limit=args.reconverge_limit,
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
    return job_runner.run_job(
        "people-reconcile",
        body,
        lock=True,
        lock_wait_seconds=RECONVERGE_LOCK_WAIT_SECONDS if args.reconverge else 0,
        # Every mode here re-decides from present evidence and writes in one
        # transaction, so a run that lost its connection left nothing behind and
        # a second attempt reaches the same state the first would have.
        retry_on_disconnect=True,
    )


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
