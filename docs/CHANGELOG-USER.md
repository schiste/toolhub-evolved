<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-race-that-ran-every-minute -->
<!-- Release title: The Race That Ran Every Minute -->
<!-- Source range: 687bd78..3de43e8 (1 commit) -->

# What's New for Users

- Four separate jobs keep Evolved's contributor records consistent, and only one of them can run at a time. They take turns through a single marker: whoever claims it first does the work, and the others step aside. That part was working. What nobody had noticed is that they all reach for it at the very same second.
- Every one of these jobs is scheduled on the minute, and one of them runs every minute. So they never queue politely behind each other -- they collide, on every single run, and the loser simply gives up and waits for its next turn.
- Giving up costs almost nothing if your next turn is a minute away. It costs a great deal if your next turn is a week away. The full weekly rebuild of contributor identities is exactly that job, and it had been told to give up immediately: on 23 August it woke, collided with the once-a-minute job, and went back to sleep after four seconds having rebuilt nothing. The next attempt was seven days later.
- Each job now waits for its turn in proportion to what missing it would cost. The once-a-minute job still never waits, because it tries again immediately. The hourly jobs wait two minutes. The weekly rebuild waits ten.
- The waiting is a limit, not a delay: when nothing is in the way the job starts instantly, and in practice the job it collides with finishes in about ten seconds. The hourly identity job had been losing better than one run in four this way, and should now lose almost none.
