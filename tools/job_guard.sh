#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Stop executing one scheduled child after repeated consecutive failures.
set -eu

JOB_NAME=""
MAX_FAILURES=3
RESET=0
# How long a lock may go untouched before a later run treats it as abandoned.
# A signalled run hands its own lock back below, so this covers only the ways a
# run can stop without getting to run any code at all: SIGKILL after the grace
# period, an eviction, a node going away. The lock would otherwise block every
# later invocation forever, and because a skip exits 0 the failure mail never
# fires: one killed run silently retires the job.
#
# This is measured from the owner's last heartbeat, not from when the lock was
# taken, which is what makes one number right for every job. It used to be
# derived -- twice each job's timeout, on the reasoning that nothing alive can
# hold a lock past twice the point the platform kills it. That is sound for the
# question "could this still be running", and wrong for the question that
# actually matters, "how long is the job silent afterwards": the threshold has
# to be crossed *and then noticed by a run*, so a job whose schedule is tighter
# than its own threshold loses every tick in between. Measured across jobs.yaml
# on 2026-09-04, one abandoned lock cost inference-enrichment 1 run,
# people-reconcile-incremental 10, and api-cache-invalidator -- a minute
# schedule against the 3600s default -- a full 60.
#
# A heartbeat answers the liveness question directly, so the window can be
# short without ever reclaiming from a run still doing work: a live owner keeps
# touching its lock however long it takes, and a dead one stops immediately.
#
# 330 rather than a round 300 because a threshold is only ever compared against
# it by a run, so one that lands on a schedule is decided by jitter rather than
# by the clock -- 300 would sit exactly on digest-deliver's five minutes. See
# test_no_reclaim_threshold_lands_on_the_schedule_it_will_be_measured_against.
STALE_AFTER=330
# How often the owner touches its lock while it works. Eleven of these fit inside
# STALE_AFTER, so a reclaim needs ten consecutive misses -- comfortably more
# than an NFS attribute cache can hide, and the directory these locks live on is
# NFS. Overridable for tests, which cannot wait out real intervals.
HEARTBEAT_SECONDS="${TOOLHUB_JOB_GUARD_HEARTBEAT_SECONDS:-30}"
# Tripping the breaker used to be permanent: a transient upstream blip that
# failed three runs retired the job until someone ran --reset by hand, and the
# skip exits 0 so nothing said so. The crawler sat disabled from 2026-08-03 to
# 2026-08-13 while the underlying fault had long cleared. Allow one trial run
# after a cooldown instead, so recovery is automatic and a still-broken job
# simply re-trips.
RETRY_AFTER=3600
# An alarm job reports on something other than itself: it exits non-zero exactly
# when the thing it watches is broken. Counting those exits as its own failures
# retires the alarm while the fault it exists to report is still there, which is
# why job-watchdog runs outside this script entirely. digest-audit has the same
# shape and did not get the same treatment: it tripped the breaker on 2026-08-30
# over a genuinely missing daily edition and spent a day muted. Wrapping is still
# worth having for such a job -- the lock, the abandoned-lock reclaim, and the
# run row that /workers reads all come from here -- so the breaker alone is what
# switches off, leaving every non-zero exit to reach the failure mail.
NO_BREAKER=0

while [ "$#" -gt 0 ]; do
	case "$1" in
		--job-name)
			[ "$#" -ge 2 ] || { echo "job-guard: --job-name needs a value" >&2; exit 2; }
			JOB_NAME="$2"
			shift 2
			;;
		--max-failures)
			[ "$#" -ge 2 ] || { echo "job-guard: --max-failures needs a value" >&2; exit 2; }
			MAX_FAILURES="$2"
			shift 2
			;;
		--stale-after)
			[ "$#" -ge 2 ] || { echo "job-guard: --stale-after needs a value" >&2; exit 2; }
			STALE_AFTER="$2"
			shift 2
			;;
		--retry-after)
			[ "$#" -ge 2 ] || { echo "job-guard: --retry-after needs a value" >&2; exit 2; }
			RETRY_AFTER="$2"
			shift 2
			;;
		--no-breaker)
			NO_BREAKER=1
			shift
			;;
		--reset)
			RESET=1
			shift
			;;
		--)
			shift
			break
			;;
		*)
			echo "job-guard: unknown option: $1" >&2
			exit 2
			;;
	esac
done

case "$JOB_NAME" in
	""|*[!A-Za-z0-9_.-]*)
		echo "job-guard: job name must contain only letters, numbers, dots, underscores, and hyphens" >&2
		exit 2
		;;
esac

case "$MAX_FAILURES" in
	''|*[!0-9]*)
		echo "job-guard: max failures must be a positive integer" >&2
		exit 2
		;;
esac
[ "$MAX_FAILURES" -gt 0 ] || { echo "job-guard: max failures must be positive" >&2; exit 2; }

case "$STALE_AFTER" in
	''|*[!0-9]*)
		echo "job-guard: stale-after must be a non-negative integer number of seconds" >&2
		exit 2
		;;
esac

case "$RETRY_AFTER" in
	''|*[!0-9]*)
		echo "job-guard: retry-after must be a non-negative integer number of seconds" >&2
		exit 2
		;;
esac

STATE_DIR="${TOOLHUB_JOB_GUARD_DIR:-$HOME/.toolhub-job-guard}"
STATE_FILE="$STATE_DIR/$JOB_NAME.state"
LOCK_DIR="$STATE_DIR/.$JOB_NAME.lock"
mkdir -p "$STATE_DIR"

lock_age_seconds() {
	lock_started="$(stat -c %Y "$LOCK_DIR" 2>/dev/null || stat -f %m "$LOCK_DIR" 2>/dev/null || echo '')"
	[ -n "$lock_started" ] || return 1
	echo $(($(date +%s) - lock_started))
}

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
	reclaimed=0
	if [ "$STALE_AFTER" -gt 0 ] && lock_age="$(lock_age_seconds)" && [ "$lock_age" -ge "$STALE_AFTER" ]; then
		# Abandoned, not overlapping: stderr so the failure mail reports that a
		# previous run died without releasing its lock.
		echo "job-guard: reclaiming $JOB_NAME lock abandoned ${lock_age}s ago" >&2
		rmdir "$LOCK_DIR" 2>/dev/null || true
		mkdir "$LOCK_DIR" 2>/dev/null && reclaimed=1
	fi
	if [ "$reclaimed" -eq 0 ]; then
		# stdout, not stderr: a skipped overlap is a deliberate non-run with a
		# zero exit, like --reset and the disabled branch below. Minute-scheduled
		# jobs overlap routinely, and routing that to <job>.err buries real
		# failures.
		printf '%s\n' "job-guard: another $JOB_NAME invocation is already running; skipping"
		exit 0
	fi
fi
child=""
heartbeat=""
# Touch the lock while this run works, so its age means "silent since" rather
# than "started at". Backgrounded rather than woven into the child's own loop
# because the guard wraps arbitrary commands and cannot ask them to check in.
# It exits on its own if the lock disappears, so a reclaimed owner stops
# refreshing a directory that now belongs to somebody else.
if [ "$STALE_AFTER" -gt 0 ] && [ "$HEARTBEAT_SECONDS" -gt 0 ]; then
	# Detached from this run's stdout and stderr, not merely silent. Killing the
	# subshell does not kill the `sleep` it is blocked in, and an orphaned sleep
	# holding the job's output pipe keeps any caller that reads to EOF waiting
	# out the full interval after the run is over -- which is every caller that
	# captures output, the test harness included.
	(
		while sleep "$HEARTBEAT_SECONDS"; do
			# -c so this can only ever update an existing directory. A plain
			# touch would recreate a reclaimed lock as a *file*, which mkdir can
			# never take again -- the job would be locked out permanently by the
			# very thing meant to keep it running.
			touch -c "$LOCK_DIR" 2>/dev/null || exit 0
			[ -d "$LOCK_DIR" ] || exit 0
		done
	) >/dev/null 2>&1 </dev/null &
	heartbeat=$!
fi
cleanup() {
	# Stop the heartbeat before releasing, or it can recreate the directory it
	# was touching a moment after rmdir and lock the job out for good.
	if [ -n "$heartbeat" ]; then
		kill "$heartbeat" 2>/dev/null || true
		wait "$heartbeat" 2>/dev/null || true
	fi
	rmdir "$LOCK_DIR" 2>/dev/null || true
}
terminated() {
	# The platform stops a job by signalling this shell and killing the pod a
	# grace period later, so this is the only chance to hand the lock back.
	# Stop the child first and wait for it: releasing the lock while the child
	# is still writing would let the next tick start a second concurrent run,
	# which is the one thing the lock exists to prevent.
	if [ -n "$child" ]; then
		kill "$child" 2>/dev/null || true
		wait "$child" 2>/dev/null || true
	fi
	cleanup
	trap - 0
	exit $((128 + $1))
}
trap cleanup 0
trap 'terminated 1' HUP
trap 'terminated 2' INT
trap 'terminated 15' TERM

if [ "$RESET" -eq 1 ]; then
	rm -f "$STATE_FILE"
	echo "job-guard: reset $JOB_NAME"
	exit 0
fi

failure_streak=0
disabled=0
last_failure_at=0
if [ -f "$STATE_FILE" ]; then
	failure_streak="$(sed -n 's/^failure_streak=//p' "$STATE_FILE" | head -n 1)"
	disabled="$(sed -n 's/^disabled=//p' "$STATE_FILE" | head -n 1)"
	last_failure_at="$(sed -n 's/^last_failure_at=//p' "$STATE_FILE" | head -n 1)"
	failure_streak="${failure_streak:-0}"
	disabled="${disabled:-0}"
	last_failure_at="${last_failure_at:-0}"
fi

if [ "$NO_BREAKER" -eq 0 ] && { [ "$disabled" -eq 1 ] || [ "$failure_streak" -ge "$MAX_FAILURES" ]; }; then
	cooled_for=$(($(date +%s) - last_failure_at))
	if [ "$RETRY_AFTER" -gt 0 ] && [ "$last_failure_at" -gt 0 ] && [ "$cooled_for" -ge "$RETRY_AFTER" ]; then
		# Half-open: one trial run. Success below clears the streak; a failure
		# re-arms the cooldown, so a genuinely broken job still runs rarely.
		echo "job-guard: retrying disabled $JOB_NAME after ${cooled_for}s; one trial run" >&2
	else
		printf '%s\n' "job-guard: $JOB_NAME is disabled after $failure_streak consecutive failures; run with --reset to resume"
		exit 0
	fi
fi

[ "$#" -gt 0 ] || { echo "job-guard: missing child command" >&2; exit 2; }
# Where the child leaves the summary it printed, for the recorder below to
# attach to the run row. The child knows what work it did but cannot write the
# row -- only this guard can tell a run that finished from one that was killed
# without a word -- so the two halves meet in a file. Removed before the child
# starts rather than matched by timestamp afterwards: the lock above already
# guarantees one run of this job at a time, so anything present when the child
# exits was written by that child.
SUMMARY_FILE="$STATE_DIR/$JOB_NAME.summary.json"
rm -f "$SUMMARY_FILE"
export TOOLHUB_JOB_SUMMARY_FILE="$SUMMARY_FILE"
run_started="$(date +%s)"
set +e
# Started in the background and waited for, not run in the foreground. A shell
# waiting on a foreground command defers a trapped signal until that command
# finishes, so the handler above could never run before the pod was killed: a
# job stopped at its timeout left its lock behind every single time, and the
# next --stale-after seconds of ticks all skipped. Waiting on a background
# child lets the signal be handled while the child is still running, which is
# what turns the abandoned-lock reclaim back into the last resort it was
# written to be. "wait" reports the child's own exit status, so nothing
# downstream can tell the difference.
"$@" &
child=$!
wait "$child"
status=$?
child=""
set -e
run_finished="$(date +%s)"

# backend.job_contract.EXIT_SKIPPED: the child took no shared lock and so did
# no work. Handled here, before anything is recorded, because the two things
# that read an exit code both get it wrong otherwise: job_runs would publish a
# successful run that never happened, and Toolforge would mail about a non-zero
# exit that is entirely routine. This is the same deliberate non-run as the
# overlap skip above, which exits before reaching this point, so it leaves the
# same trace -- none -- and the breaker state is untouched rather than reset,
# because a skip is no evidence that a previously failing job has recovered.
if [ "$status" -eq 75 ]; then
	exit 0
fi

# Publish the run so /workers can show it. Best effort in every direction: a
# missing recorder or an unreachable database must never turn a healthy job
# into a failed one, which is why the exit status is captured above and
# restored below rather than being whatever this writes.
if [ -n "${TOOLHUB_DB_URL:-}" ] && [ -x "${TOOLHUB_JOB_RUN_PYTHON:-$HOME/www/python/venv/bin/python}" ]; then
	"${TOOLHUB_JOB_RUN_PYTHON:-$HOME/www/python/venv/bin/python}" \
		"$(dirname "$0")/job_run_record.py" \
		--job-name "$JOB_NAME" \
		--started "$run_started" \
		--finished "$run_finished" \
		--exit-code "$status" \
		--summary-file "$SUMMARY_FILE" >/dev/null 2>&1 || true
fi
rm -f "$SUMMARY_FILE"

tmp="$STATE_FILE.$$"
if [ "$status" -eq 0 ]; then
	cat > "$tmp" <<EOF
failure_streak=0
disabled=0
last_exit=0
last_failure_at=0
EOF
	mv "$tmp" "$STATE_FILE"
	exit 0
fi

failure_streak=$((failure_streak + 1))
disabled=0
if [ "$NO_BREAKER" -eq 0 ] && [ "$failure_streak" -ge "$MAX_FAILURES" ]; then
	disabled=1
fi
cat > "$tmp" <<EOF
failure_streak=$failure_streak
disabled=$disabled
last_exit=$status
last_failure_at=$run_finished
EOF
mv "$tmp" "$STATE_FILE"
if [ "$disabled" -eq 1 ]; then
	echo "job-guard: $JOB_NAME reached $failure_streak consecutive failures and is now disabled" >&2
fi
exit "$status"
