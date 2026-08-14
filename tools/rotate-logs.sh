#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Cap the tool account's log files with copy-truncate rotation (jobs.yaml).
#
# Rotation MUST copy-and-truncate rather than rename. uwsgi holds ~/uwsgi.log
# open, and the jobs framework holds each <job>.out/.err open for the life of a
# run; renaming leaves those writers attached to the rotated inode, so the live
# path stays at zero bytes while the archive grows forever. Truncating in place
# keeps the inode, at the cost of losing whatever is written in the narrow
# window between the copy and the truncate.
#
# Inspection: docs/RUNBOOK.md § Logs.
set -eu

DIR="${TOOLHUB_LOG_DIR:-$HOME}"
MAX_BYTES="${TOOLHUB_LOG_MAX_BYTES:-8388608}" # 8 MiB
KEEP_DEFAULT="${TOOLHUB_LOG_KEEP:-5}"
DEPLOY_RETENTION_DAYS="${TOOLHUB_DEPLOY_LOG_RETENTION_DAYS:-14}"

command -v gzip >/dev/null 2>&1 || {
	echo "rotate-logs: gzip not found" >&2
	exit 1
}

case "$MAX_BYTES$KEEP_DEFAULT$DEPLOY_RETENTION_DAYS" in
	*[!0-9]*)
		echo "rotate-logs: max bytes, keep count, and retention days must be non-negative integers" >&2
		exit 2
		;;
esac
[ "$KEEP_DEFAULT" -ge 1 ] || { echo "rotate-logs: keep count must be at least 1" >&2; exit 2; }

# How many compressed generations to keep for one log file, by base name.
#
# TODO(christophe): these files do not carry equal value. ~/uwsgi.log is the
# application-error trail an incident is reconstructed from, so depth there buys
# forensics. The per-job .out files are mostly successful-run chatter, where the
# same depth buys little and costs quota. Right now everything gets the same
# KEEP_DEFAULT; split it if the trade-off is worth the asymmetry to you.
keep_for() {
	case "$1" in
		uwsgi.log) echo "$KEEP_DEFAULT" ;;
		*.err) echo "$KEEP_DEFAULT" ;;
		*) echo "$KEEP_DEFAULT" ;;
	esac
}

# Rotate one file if it has grown past the threshold; 1 means "left alone".
rotate_one() {
	log="$1"
	name="$(basename "$log")"
	keep="$(keep_for "$name")"
	size="$(wc -c <"$log" | tr -d ' ')"
	[ "$size" -ge "$MAX_BYTES" ] || return 1

	rm -f -- "$log.$keep.gz"
	i=$((keep - 1))
	while [ "$i" -ge 1 ]; do
		if [ -f "$log.$i.gz" ]; then
			mv -- "$log.$i.gz" "$log.$((i + 1)).gz"
		fi
		i=$((i - 1))
	done

	# Truncate immediately after the copy so the lost-write window stays as
	# small as possible; compressing the archive afterwards costs nothing live.
	cp -- "$log" "$log.1"
	: >"$log"
	gzip -f -- "$log.1"
	echo "rotate-logs: rotated $name ($size bytes), keeping $keep generations"
	return 0
}

checked=0
rotated=0
for log in "$DIR"/uwsgi.log "$DIR"/*.out "$DIR"/*.err "$DIR"/deployment-logs/*.out "$DIR"/deployment-logs/*.err; do
	[ -f "$log" ] || continue # unmatched globs arrive literally
	checked=$((checked + 1))
	if rotate_one "$log"; then
		rotated=$((rotated + 1))
	fi
done

pruned=0
if [ -d "$DIR/deployment-logs" ]; then
	while IFS= read -r expired; do
		[ -n "$expired" ] || continue
		rm -f -- "$expired"
		pruned=$((pruned + 1))
	done <<EOF
$(find "$DIR/deployment-logs" -type f \( -name '*.out' -o -name '*.err' -o -name '*.gz' \) -mtime "+$DEPLOY_RETENTION_DAYS" -print)
EOF
fi

echo "rotate-logs: $checked files checked, $rotated rotated, $pruned expired deploy logs pruned, threshold $MAX_BYTES bytes"
