#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Stop executing one scheduled child after repeated consecutive failures.
set -eu

JOB_NAME=""
MAX_FAILURES=3
RESET=0

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

STATE_DIR="${TOOLHUB_JOB_GUARD_DIR:-$HOME/.toolhub-job-guard}"
STATE_FILE="$STATE_DIR/$JOB_NAME.state"
LOCK_DIR="$STATE_DIR/.$JOB_NAME.lock"
mkdir -p "$STATE_DIR"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
	echo "job-guard: another $JOB_NAME invocation is already running; skipping" >&2
	exit 0
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
if [ -f "$STATE_FILE" ]; then
	failure_streak="$(sed -n 's/^failure_streak=//p' "$STATE_FILE" | head -n 1)"
	disabled="$(sed -n 's/^disabled=//p' "$STATE_FILE" | head -n 1)"
	failure_streak="${failure_streak:-0}"
	disabled="${disabled:-0}"
fi

if [ "$disabled" -eq 1 ] || [ "$failure_streak" -ge "$MAX_FAILURES" ]; then
	printf '%s\n' "job-guard: $JOB_NAME is disabled after $failure_streak consecutive failures; run with --reset to resume"
	exit 0
fi

[ "$#" -gt 0 ] || { echo "job-guard: missing child command" >&2; exit 2; }
set +e
"$@"
status=$?
set -e

tmp="$STATE_FILE.$$"
if [ "$status" -eq 0 ]; then
	cat > "$tmp" <<EOF
failure_streak=0
disabled=0
last_exit=0
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
EOF
mv "$tmp" "$STATE_FILE"
if [ "$disabled" -eq 1 ]; then
	echo "job-guard: $JOB_NAME reached $failure_streak consecutive failures and is now disabled" >&2
fi
exit "$status"
