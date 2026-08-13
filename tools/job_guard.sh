#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Stop executing one scheduled child after repeated consecutive failures.
set -eu

JOB_NAME=""
MAX_FAILURES=3
RESET=0
# A lock is released by the EXIT trap, which never runs when the pod is killed
# (SIGKILL on a job timeout or an eviction). The lock then blocks every later
# invocation forever, and because a skip exits 0 the failure mail never fires:
# one killed run silently retires the job. Reclaiming a lock older than any
# legitimate run makes that self-healing. Keep this above the job's own
# timeout so a slow run is never mistaken for an abandoned one.
STALE_AFTER=3600
# Tripping the breaker used to be permanent: a transient upstream blip that
# failed three runs retired the job until someone ran --reset by hand, and the
# skip exits 0 so nothing said so. The crawler sat disabled from 2026-08-03 to
# 2026-08-13 while the underlying fault had long cleared. Allow one trial run
# after a cooldown instead, so recovery is automatic and a still-broken job
# simply re-trips.
RETRY_AFTER=3600

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
cleanup() {
	rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup 0 HUP INT TERM

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

if [ "$disabled" -eq 1 ] || [ "$failure_streak" -ge "$MAX_FAILURES" ]; then
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
run_started="$(date +%s)"
set +e
"$@"
status=$?
set -e
run_finished="$(date +%s)"

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
		--exit-code "$status" >/dev/null 2>&1 || true
fi

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
if [ "$failure_streak" -ge "$MAX_FAILURES" ]; then
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
