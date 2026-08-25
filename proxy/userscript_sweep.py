# SPDX-License-Identifier: GPL-3.0-or-later
"""Toolforge job entrypoint for the user-script census."""

from __future__ import annotations

import os
import sys

from backend import (
    job_runner,
    userscript_creation_dates,
    userscript_projection,
    userscript_sweep,
    userscript_toolinfo,
    wiki_edit_dates,
    wiki_registry,
    wiki_replica,
    wiki_schedule,
)
from backend.wikimedia_delivery import WikimediaClient

LANE = wiki_schedule.USERSCRIPT_LANE

# The wikis a run covers when there is no registry to ask yet -- what the first
# run after a deployment does, before the weekly registry job has filled the
# roster in, and the list this lane covered for its whole life before the roster
# existed.
FALLBACK_WIKIS = "fr.wikipedia.org,meta.wikimedia.org,en.wikipedia.org"

# How long a run may spend reading wikis, out of the hour between runs. Twenty
# minutes rather than the whole hour because these are not the only jobs on the
# cluster: the replicas are shared with the gadget lane, and the database with
# two dozen other jobs including a projection refresh that averages nine
# minutes. A budget is a floor on how much of the hour is left for them.
DEFAULT_BUDGET = 1200


class CensusIncompleteError(RuntimeError):
    """Raised when no wiki this run attempted could be covered."""


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _progress(summary: dict) -> str:
    """Render the part of a run's result the other mode has no equivalent of.

    Written into the same line rather than a second one because these are the
    numbers that say whether a wiki is converging. For a sweep: which road named
    its pages, how many there are, and how far this run got -- a census that
    quietly stopped being exact, a replica that went away leaving a capped search
    behind, shows up here rather than only as a total that stopped growing.

    For a watch it is the cursor, which is the only thing in the whole run that
    says how current the census is. Every other number a watch prints describes
    the run; the wiki timestamp it has consumed up to describes the data. A watch
    resuming a month back reports five pages written and looks like a quiet hour,
    and the line said nothing to tell the two apart. `none` is a cursor that has
    never been set, which starts at the oldest row the wiki still keeps.

    `windows` is how many recent-changes windows the run got through, and
    `behind` says it stopped because it ran out of them rather than because it
    reached the present. Together they are the difference between a cursor that
    is close because the wiki is quiet and one that is close because the run
    worked for it -- and, while a wiki is catching up, the only number that says
    it still is.
    """
    if summary.get("mode") == "sweep":
        return (
            f" source={summary['source']} enumerated={summary['enumerated']} "
            f"sweep_cursor={summary['sweep_cursor']} complete={int(bool(summary['complete']))}"
        )
    return (
        f" cursor={summary['cursor'] or 'none'} windows={summary['windows']}{' behind=1' if summary['behind'] else ''}"
    )


def _override() -> list[str]:
    """List the wikis an operator named by hand, if any."""
    raw = os.environ.get("USERSCRIPT_WIKIS", "")
    return [wiki.strip() for wiki in raw.split(",") if wiki.strip()]


def _queue() -> tuple[wiki_schedule.Due, ...]:
    """Decide which wikis this run covers, and in which order.

    An override wins outright: someone asking for three named wikis wants those
    three, now, whatever the schedule thinks -- which is also how a full sweep
    of one big wiki is asked for. Otherwise the queue answers, and an empty
    queue means one of two very different things: every wiki is up to date,
    which is the healthy steady state, or the registry has never been filled in,
    which is where a fresh deployment sits until the weekly job runs. Only the
    second is worth falling back for, so the registry is asked which it is.
    """
    if override := _override():
        return wiki_schedule.named(override)
    if queue := wiki_schedule.due(LANE):
        return queue
    if wiki_registry.projects():
        return ()
    return wiki_schedule.named([wiki.strip() for wiki in FALLBACK_WIKIS.split(",") if wiki.strip()])


def main() -> int:
    """Sweep or watch each configured wiki's user-space script pages, then rank them.

    A full sweep is thousands of requests and is not something to run hourly, so
    the schedule runs a watch and the sweep is asked for explicitly. The first
    run on a wiki has no cursor, and a watch with no cursor would learn only
    what changed since it started -- so a wiki with no completed sweep gets one
    whether or not this run asked for it.

    The projection follows every run, including one that wrote nothing. It reads
    no wiki and takes seconds, while the collapse it recomputes is global: one
    new page can change which page is the original of a script, so a directory
    rebuilt only when the sweep found something would drift out of agreement
    with the pages it claims to describe.

    Creation dates are stamped in between, because the collapse breaks its ties
    on them. They come from the Wiki Replicas rather than the API, so on a host
    with no replica credentials that step writes nothing and the collapse falls
    back to discovery order -- which is why it reports whether it reached a
    replica separately from how many rows it wrote.

    Last-edit dates are stamped on the same trip and offered for every page on
    every run. The sweep itself dates the pages it fetches, but a watch fetches
    only what moved and a sweep skips pages whose latest revision it already
    holds -- so the pages the sweep can date are precisely the ones already
    dated, and everything ingested before this field existed would stay blank
    forever. One replica query per wiki dates the whole corpus instead, and
    writes only where the answer moved something forward.
    """
    full = os.environ.get("USERSCRIPT_SWEEP", "").strip().lower() in {"1", "true", "yes"}
    limit = _int_env("USERSCRIPT_LIMIT", 0)
    watch_limit = _int_env("USERSCRIPT_WATCH_LIMIT", userscript_sweep.WATCH_LIMIT) or userscript_sweep.WATCH_LIMIT
    watch_windows = (
        _int_env("USERSCRIPT_WATCH_WINDOWS", userscript_sweep.WATCH_WINDOWS) or userscript_sweep.WATCH_WINDOWS
    )

    def cover(client: WikimediaClient, entry: wiki_schedule.Due, connect: wiki_replica.Connect) -> bool:
        """Bring one wiki up to date and report what that took, in five lines.

        What it returns is the one bit the schedule learns from: whether this
        wiki was worth reading. A wiki that keeps answering "nothing written" is
        asked less often, which is how a thousand corpora fit into a budget
        sized for the handful that actually move.
        """
        wiki = entry.wiki
        known = wiki_schedule.addresses([entry])
        summary = userscript_sweep.run(
            client.request,
            wiki,
            full=full,
            limit=limit,
            watch_limit=watch_limit,
            watch_windows=watch_windows,
        )
        collisions = summary["collisions"]
        oversized = summary["oversized"]
        sys.stdout.write(
            "userscript-census: "
            f"wiki={summary['wiki']} mode={summary['mode']} "
            f"asked={summary['asked']} fetched={summary['fetched']} "
            f"written={summary['written']} skipped={summary['skipped']} "
            f"unreadable={summary['unreadable']}"
            # Pages no request can carry, kept off `unreadable` so that one
            # stays a number worth looking at. Printed only when it happens,
            # and when it does it is not an incident: enwiki has one
            # bot-maintained list that has been past the response cap for
            # months and grows by a few hundred bytes a day.
            f"{f' oversized={oversized}' if oversized else ''}"
            # Only when they happened. A field that is almost always 0 trains
            # the reader to skip the line it appears on. `collisions` counts
            # load edges the database folded onto another edge of the same page
            # and this run therefore dropped -- expected to be zero, and worth a
            # look when it is not, because it means some page spells one target
            # two ways and only the collation knows they are one.
            f"{' lagged=1' if summary['lagged'] else ''}"
            f"{f' collisions={collisions}' if collisions else ''}"
            f"{_progress(summary)}\n",
        )
        stamped = userscript_creation_dates.backfill([wiki], connect=connect, known=known)
        sys.stdout.write(
            "userscript-creation-dates: "
            f"wiki={wiki} replica={'yes' if wiki in stamped else 'no'} "
            f"stamped={stamped.get(wiki, 0)}\n",
        )
        edited = wiki_edit_dates.backfill_scripts([wiki], connect=connect, known=known)
        sys.stdout.write(
            "userscript-edit-dates: "
            f"wiki={wiki} replica={'yes' if wiki in edited else 'no'} "
            f"stamped={edited.get(wiki, 0)}\n",
        )
        ranked = userscript_projection.project(wiki)
        sys.stdout.write(
            "userscript-directory: "
            f"wiki={ranked['wiki']} candidates={ranked['candidates']} "
            f"originals={ranked['originals']} active={ranked['active']} "
            f"archive={ranked['archive']}\n",
        )
        # Follows every projection, including one that changed nothing. It talks
        # to no wiki -- it rebuilds records from what the directory concluded --
        # so running it unconditionally means a change to what this codebase
        # considers a tool takes effect on the next sweep rather than waiting
        # for a wiki to be edited.
        catalogued = userscript_toolinfo.synchronize(wiki)
        sys.stdout.write(
            "userscript-catalogue: "
            f"wiki={catalogued['wiki']} originals={catalogued['originals']} "
            f"written={catalogued['written']} unchanged={catalogued['unchanged']} "
            f"stylesheet={catalogued['stylesheet']} unnamed={catalogued['unnamed']} "
            f"duplicate={catalogued['duplicate']} conflicted={catalogued['conflicted']} "
            f"retired={catalogued['retired']}\n",
        )
        return bool(summary["written"] or catalogued["written"] or catalogued["retired"])

    def body() -> None:
        """Cover as many wikis as the run has time for, and let each one fail on its own.

        Every Wikimedia wiki has user scripts and a thousand corpora will not
        fit in one hour, so the run takes the wikis it owes a turn, most overdue
        first, and stops when its budget is spent. It never stops mid-wiki: a
        half-swept corpus is worse than a run that finished late, and the wiki
        after it is only more overdue next time.

        The wikis are independent corpora that happen to share a run, so a run
        that stops at the first exception spends its whole budget on the wikis
        before the bad one and never reaches the wikis after it. That is not
        hypothetical: on 2026-08-23 a single Meta page whose loads collided
        under the database's collation raised out of Meta's ingest, and because
        enwiki was third in the list, enwiki's first sweep stopped advancing --
        three runs later the job guard disabled the job, and neither wiki moved
        again. Ordering decided which corpus starved, which is not a thing
        ordering should decide.

        A failing wiki no longer fails the run either, which is the other half
        of that lesson and a deliberate change of contract. With three wikis, an
        unreachable one meant something was wrong and the guard was right to
        escalate. With a thousand, some wiki is always having a bad day, and a
        run that failed for it would have the guard disable the whole census
        within three ticks -- starving nine hundred and ninety-nine corpora for
        one wiki's outage. The failure is recorded on the wiki instead, which
        backs it off and leaves its place in the rotation intact. What still
        fails the run is every attempted wiki failing: that is the shape of a
        real problem rather than one wiki's bad afternoon.
        """
        budget = wiki_schedule.Budget(_int_env("USERSCRIPT_BUDGET_SECONDS", DEFAULT_BUDGET))
        queue = _queue()
        covered: list[str] = []
        failed: list[str] = []
        client = WikimediaClient()
        # One connection per replica instance for the whole pass, rather than
        # one per wiki. Eight instances serve every Wikimedia wiki and one of
        # them serves 869, and the queue has already ordered the run so that a
        # section's wikis are covered together.
        with wiki_replica.pooled() as connect:
            for entry in queue:
                if not budget.remains():
                    break
                wiki_schedule.start(entry.wiki, LANE)
                try:
                    changed = cover(client, entry, connect)
                except Exception as error:  # noqa: BLE001 - one wiki's failure is not the next wiki's
                    failed.append(entry.wiki)
                    wiki_schedule.settle(entry.wiki, LANE, wiki_schedule.Outcome(error=type(error).__name__))
                    sys.stdout.write(
                        f"userscript-census: wiki={entry.wiki} failed error={type(error).__name__}: {error}\n",
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
            "userscript-census: "
            f"queued={len(queue)} covered={len(covered)} failed={len(failed)} "
            f"seconds={budget.spent():.0f} backlog={wiki_schedule.backlog(LANE)}\n",
        )
        if failed and not covered:
            message = f"census failed for every wiki attempted: {', '.join(failed)}"
            raise CensusIncompleteError(message)

    return job_runner.run_job("userscript-census", body)


if __name__ == "__main__":  # pragma: no cover - job entrypoint, exercised via main() in tests
    raise SystemExit(main())
