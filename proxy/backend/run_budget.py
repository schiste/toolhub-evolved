# SPDX-License-Identifier: GPL-3.0-or-later
"""How much wall-clock one scheduled run may still spend.

Every bounded sweep in this repository used to say "how much" with an item
count: 200 inferences, 500 probes, 100 icons. A count is the wrong unit for
the question the schedule actually asks, which is "finish before the next
tick". It has to be guessed from a per-item cost nobody measures again, and
when the guess is low the job idles -- measured on 2026-08-27, the nine
bounded sweeps ran at 0.1% to 12% of their interval, several of them against
five-figure backlogs. When the guess is high the job overruns and the guard
kills it. Neither failure is visible in an exit code.

A deadline needs no guess. The run works until its allowance is gone, so it
self-tunes to whatever the items happen to cost today and can never spill into
the next tick. The count stays as a safety cap for the pathological case --
items that turn out to cost nothing, and a loop that would otherwise write
until the table is exhausted.

`wiki_schedule` grew this first, for the census lanes. It lives here now
because nothing about it is about wikis, and a catalogue sweep importing the
wiki scheduler to get a clock is how the next reader concludes the two are
related.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class Budget:
    """How much wall-clock a run may still spend.

    Held rather than passed around as a deadline so the loop reads as a question
    about the run -- `while budget.remains()` -- and so tests can drive it with
    a clock instead of sleeping.
    """

    def __init__(self, seconds: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        """Start the clock. `clock` is monotonic so a host clock step cannot end a run early."""
        self._clock = clock
        self._seconds = max(0.0, float(seconds))
        self._started = clock()

    @property
    def seconds(self) -> float:
        """The allowance this run began with."""
        return self._seconds

    def spent(self) -> float:
        """How long the run has been going."""
        return self._clock() - self._started

    def left(self) -> float:
        """How much of the allowance is unspent, never below zero."""
        return max(0.0, self._seconds - self.spent())

    def remains(self) -> bool:
        """Whether there is any allowance left to start another item with.

        Checked before an item rather than after, so the last item a run starts
        is one it had time for. It may still overrun -- nothing here interrupts
        an item mid-flight, because a half-written answer is worse than a late
        run -- but it will not start one with nothing left.
        """
        return self.left() > 0


def from_env(name: str, default: int) -> Budget:
    """Return the budget named by `name` seconds, falling back to `default`.

    Unset, empty, unparseable and negative all mean the default rather than an
    unbounded run: a typo in a job definition must not be the thing that lets a
    sweep run until the guard kills it.
    """
    raw = os.environ.get(name, "").strip()
    try:
        seconds = int(raw)
    except ValueError:
        seconds = default
    return Budget(seconds if seconds > 0 else default)
