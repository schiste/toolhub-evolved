# SPDX-License-Identifier: GPL-3.0-or-later
"""Toolforge job entrypoint for the gadget census."""

from __future__ import annotations

import os
import sys

from backend import (
    gadget_creation_dates,
    gadget_inventory,
    gadget_toolinfo,
    job_runner,
    wiki_edit_dates,
    wiki_registry,
    wiki_replica,
    wiki_schedule,
)
from backend.wikimedia_delivery import WikimediaClient

LANE = wiki_schedule.GADGET_LANE

# The wikis a run covers when there is no registry to ask yet. Not a default in
# the ordinary sense -- it is what the first run after a deployment does, before
# the weekly registry job has populated the roster -- and it is the list this
# lane covered for its whole life before the roster existed.
FALLBACK_WIKIS = "fr.wikipedia.org,meta.wikimedia.org,en.wikipedia.org"

# How long a run may spend reading wikis. Half an hour on a job that runs every
# six hours: the inventory is one request and one replica query per wiki, so
# this is several hundred wikis a run, and the other three and a half hours
# belong to the two dozen jobs that share this database.
DEFAULT_BUDGET = 1800


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _override() -> list[str]:
    """List the wikis an operator named by hand, if any."""
    raw = os.environ.get("GADGET_WIKIS", "")
    return [wiki.strip() for wiki in raw.split(",") if wiki.strip()]


def _queue() -> tuple[wiki_schedule.Due, ...]:
    """Decide which wikis this run covers, and in which order.

    An override wins outright: someone asking for three named wikis wants those
    three, now, whatever the schedule thinks. Otherwise the queue answers, and
    an empty queue means one of two very different things -- every wiki is up to
    date, which is the healthy steady state, or the registry has never been
    filled in, which is the state a fresh deployment is in until the weekly job
    runs. Only the second is worth falling back for, so the registry is asked
    which one it is rather than guessed at.
    """
    if override := _override():
        return wiki_schedule.named(override)
    if queue := wiki_schedule.due(LANE):
        return queue
    if wiki_registry.projects():
        return ()
    return wiki_schedule.named([wiki.strip() for wiki in FALLBACK_WIKIS.split(",") if wiki.strip()])


def cover(client: WikimediaClient, entry: wiki_schedule.Due, connect: wiki_replica.Connect) -> bool:
    """Read one wiki's gadgets and rebuild its catalogue entries. Says whether anything moved.

    Creation dates are stamped between the two passes, so a gadget dated for the
    first time publishes that date on the same tick rather than the next one.
    Last-edit dates are stamped alongside them, and unlike creation dates they
    are re-asked for every gadget on every tick: a definition page does not
    change when the code it points at is rewritten, so the inventory pass can
    report a gadget entirely unchanged on the very run its source moved.

    The catalogue pass follows every read, including one that changed nothing
    and one that failed. It talks to no wiki -- it rebuilds records from what
    the inventory stored -- so it costs seconds, and running it unconditionally
    means a change to what this codebase considers a tool takes effect on the
    next tick rather than waiting for a wiki to edit its definitions.

    What it returns is the one bit the schedule learns from: whether this wiki
    was worth reading. A wiki that keeps answering "nothing moved" is asked less
    often, which is how a thousand wikis fit into a budget sized for a hundred.
    """
    wiki = entry.wiki
    known = wiki_schedule.addresses([entry])
    read = gadget_inventory.ingest(client.request, wiki)
    sys.stdout.write(
        "gadget-inventory: "
        f"wiki={read['wiki']} read={'yes' if read['read'] else 'no'} "
        f"reason={read['reason']} "
        f"declared={read['declared']} added={read['added']} "
        f"updated={read['updated']} folded={read['folded']} "
        f"retired={read['retired']}\n",
    )
    stamped = gadget_creation_dates.backfill([wiki], connect=connect, known=known)
    sys.stdout.write(
        f"gadget-creation-dates: wiki={wiki} replica={'yes' if stamped else 'no'} stamped={stamped.get(wiki, 0)}\n",
    )
    edited = wiki_edit_dates.backfill_gadgets([wiki], connect=connect, known=known)
    sys.stdout.write(
        f"gadget-edit-dates: wiki={wiki} replica={'yes' if wiki in edited else 'no'} stamped={edited.get(wiki, 0)}\n",
    )
    catalogued = gadget_toolinfo.synchronize(wiki)
    sys.stdout.write(
        "gadget-catalogue: "
        f"wiki={catalogued['wiki']} declared={catalogued['declared']} "
        f"written={catalogued['written']} unchanged={catalogued['unchanged']} "
        f"hidden={catalogued['hidden']} unnamed={catalogued['unnamed']} "
        f"duplicate={catalogued['duplicate']} conflicted={catalogued['conflicted']} "
        f"retired={catalogued['retired']}\n",
    )
    return bool(read["added"] or read["updated"] or read["retired"] or catalogued["written"] or catalogued["retired"])


def main() -> int:
    """Cover as many wikis as the run has time for, most overdue first.

    Every Wikimedia wiki has gadgets and a thousand of them will not fit in one
    run, so the run takes the wikis it owes a turn and stops when its budget is
    spent. It never stops mid-wiki: a half-covered wiki is worse than a run that
    finished a few minutes late, and the wiki after it is only more overdue.

    The whole pass shares one replica connection per instance. Eight instances
    serve every wiki and one of them serves 869, so a run that reordered its
    wikis by section -- which the queue has already done -- opens single-digit
    connections where a naive pass would open one per wiki.

    A wiki that fails is recorded, backed off and left behind; the run does not
    fail with it. That is a deliberate change from three wikis to a thousand.
    With three, one unreachable wiki meant something was wrong and the job guard
    was right to escalate. With a thousand, some wiki is always having a bad
    day, and a run that failed for it would have the guard disable the entire
    census within three ticks -- starving the other nine hundred and ninety-nine
    for one wiki's outage. What still fails the run is every attempted wiki
    failing, which is the shape of a real problem: no credentials, no network,
    a broken deployment.
    """

    def body() -> None:
        budget = wiki_schedule.Budget(_int_env("GADGET_BUDGET_SECONDS", DEFAULT_BUDGET))
        queue = _queue()
        covered: list[str] = []
        failed: list[str] = []
        client = WikimediaClient()
        with wiki_replica.pooled() as connect:
            for entry in queue:
                if not budget.remains():
                    break
                wiki_schedule.start(entry.wiki, LANE)
                try:
                    changed = cover(client, entry, connect)
                except Exception as error:  # noqa: BLE001 - one wiki's failure is not the next wiki's
                    failed.append(entry.wiki)
                    wiki_schedule.settle(entry.wiki, LANE, wiki_schedule.Outcome(error=f"{type(error).__name__}"))
                    sys.stdout.write(
                        f"gadget-census: wiki={entry.wiki} failed error={type(error).__name__}: {error}\n",
                    )
                else:
                    covered.append(entry.wiki)
                    wiki_schedule.settle(
                        entry.wiki,
                        LANE,
                        wiki_schedule.Outcome(changed=changed, closed=entry.closed),
                    )
        # `backlog` is the number that says whether this schedule is keeping up.
        # Everything else on the line describes the run; this describes the work
        # still owed, and a backlog that grows every tick is a budget decision
        # rather than something the queue can fix by itself.
        sys.stdout.write(
            "gadget-census: "
            f"queued={len(queue)} covered={len(covered)} failed={len(failed)} "
            f"seconds={budget.spent():.0f} backlog={wiki_schedule.backlog(LANE)}\n",
        )
        if failed and not covered:
            message = f"census failed for every wiki attempted: {', '.join(failed)}"
            raise RuntimeError(message)

    return job_runner.run_job("gadget-census", body)


if __name__ == "__main__":  # pragma: no cover - job entrypoint, exercised via main() in tests
    raise SystemExit(main())
