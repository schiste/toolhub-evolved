# SPDX-License-Identifier: GPL-3.0-or-later
"""Run deterministic people identity reconciliation for the local catalog."""

from __future__ import annotations

import argparse
import os
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

from backend import db, job_runner, people_reconcile

if TYPE_CHECKING:
    from collections.abc import Iterator

# Every mode below takes one shared advisory lock, and every schedule that
# uses it fires on the minute: `* * * * *` at :00 of each minute, `43 * * * *`
# at :43:00, `13 5 * * 0` at 05:13:00. They do not queue behind one another,
# they race, at the same instant, on every run. So each mode needs a stated
# answer to "how long is winning this worth to me", and the honest measure is
# what losing costs: how long until this mode gets another attempt.
#
#   --queue            another attempt in 1 minute  -> never waits
#   --reconverge       another attempt in 1 hour    -> waits
#   --identities-only  another attempt in 1 hour    -> waits
#   --apply            another attempt in 7 days    -> waits longest
#
# The earlier rule read the contention backwards: it gave the only wait to
# --reconverge on the grounds that "the full pass is the run everyone else is
# waiting on". The full pass is in fact the mode most often turned away, and
# the one that pays a week for it -- on 2026-08-23 it reclaimed its file lock,
# lost this one to the drain, and exited in four seconds having done nothing.
#
# The numbers are measured, not chosen. The drain holds the lock for 6-11s in
# practice against a 300s timeout ceiling. 120s has been --reconverge's wait
# since 2026-08-17, over which it lost the lock on 3.6% of runs, against 26.7%
# for --identities-only -- the same shape of job, same hourly cadence, no
# wait. So 120s is what an hour of loss buys, demonstrated. Only the full pass
# can afford to outlast the drain's ceiling as well, and it is the one whose
# next chance is seven days away, so it alone is given that much.
HOURLY_LOCK_WAIT_SECONDS = 120
FULL_PASS_LOCK_WAIT_SECONDS = 600


def _lock_wait_seconds(args: argparse.Namespace) -> int:
    """How long this mode is willing to lose to the race for the shared lock.

    Set by how soon this mode gets another attempt, never by how much work it
    is carrying: the drain is the largest job here by volume and is the one
    that must never wait, because sixty seconds later it tries again.

    The modes with no schedule -- a bare dry run, and --retirements -- are only
    ever started by hand, so nothing will retry them at all. They wait the
    longest for the same reason the weekly pass does.
    """
    if args.queue:
        return 0
    if args.reconverge or args.identities_only:
        return HOURLY_LOCK_WAIT_SECONDS
    return FULL_PASS_LOCK_WAIT_SECONDS


@contextmanager
def _timed(into: dict[str, float], name: str) -> Iterator[None]:
    """Record how long one phase of a sweep took, in the summary it reports.

    A sweep that is killed at its timeout writes nothing at all, so the only
    evidence left is the duration of the runs that did finish -- one number for
    work that is really a bounded remote batch followed by an unbounded local
    scan. Which half is consuming the budget decides whether the answer is a
    smaller batch or more time, and without this it can only be guessed at.
    """
    started = time.monotonic()
    try:
        yield
    finally:
        into[name] = round(time.monotonic() - started, 1)


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
        phase_seconds: dict[str, float] = {}
        if discover and not args.identities_only:
            with _timed(phase_seconds, "rebuild"), db.session_scope() as session:
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
        with _timed(phase_seconds, "remote"):
            resolved_identities, resolved_registry = (
                people_reconcile.resolve_remote_batches(
                    candidate_label_limit=args.candidate_label_limit,
                    registry_label_limit=args.registry_label_limit,
                )
                if discover
                else (None, None)
            )
        with _timed(phase_seconds, "local"), db.session_scope() as session:
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
        summary["phaseSeconds"] = phase_seconds
        return summary

    # Per backend.job_contract: tools this pass could not reconcile stay queued
    # with their retry state and are reported as `failed`. The sweep ran, so it
    # must not count toward the guard's breaker -- this is the job whose
    # ten-day outage the breaker and lock work came from.
    return job_runner.run_job(
        "people-reconcile",
        body,
        lock=True,
        lock_wait_seconds=_lock_wait_seconds(args),
        # Every mode here re-decides from present evidence and writes in one
        # transaction, so a run that lost its connection left nothing behind and
        # a second attempt reaches the same state the first would have.
        retry_on_disconnect=True,
    )


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
