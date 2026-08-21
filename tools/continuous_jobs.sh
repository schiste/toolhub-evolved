#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Print the name of every continuous job declared in jobs.yaml, one per line.
#
# Split out of deploy.sh so the rule that decides which workers a deploy must
# restart is testable on its own. Deriving the list from jobs.yaml rather than
# naming the jobs here means a continuous job added later is restarted without
# anyone remembering to come back and add it.
set -eu

JOBS_FILE="${1:-$(cd "$(dirname "$0")/.." && pwd)/jobs.yaml}"

if [ ! -f "$JOBS_FILE" ]; then
	echo "continuous-jobs: no such file: $JOBS_FILE" >&2
	exit 1
fi

# `continuous:` has to be indented and start the line's content, so the prose
# in jobs.yaml that discusses continuous jobs -- and there is a lot of it, all
# of it in `#` comments -- is not mistaken for a declaration.
awk '
	/^- name:[[:space:]]/ { name = $3; next }
	/^[[:space:]]+continuous:[[:space:]]*true[[:space:]]*$/ {
		if (name != "") {
			print name
		}
	}
' "$JOBS_FILE"
