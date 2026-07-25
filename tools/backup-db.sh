#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Nightly ToolsDB backup with 14-day rotation (scheduled via jobs.yaml).
# Requires TOOLHUB_DB_NAME (e.g. s12345__toolhub_evolved) in the tool's envvars.
# Restore drill: docs/RUNBOOK.md § Backups.
set -eu

DB="${TOOLHUB_DB_NAME:?set TOOLHUB_DB_NAME (e.g. s12345__toolhub_evolved)}"
DEST="${TOOLHUB_BACKUP_DIR:-$HOME/backups}"
HOST="${TOOLHUB_DB_HOST:-tools.db.svc.wikimedia.cloud}"
KEEP=14

mkdir -p "$DEST"
STAMP="$(date -u +%Y%m%d-%H%M)"
OUT="$DEST/$DB-$STAMP.sql.gz"

# replica.my.cnf holds the tool's ToolsDB credentials (standard on Toolforge).
mariadb-dump --defaults-file="$HOME/replica.my.cnf" -h "$HOST" "$DB" | gzip >"$OUT"
echo "backup: wrote $OUT ($(du -h "$OUT" | cut -f1))"

# Rotate: keep the newest $KEEP dumps.
ls -1t "$DEST/$DB"-*.sql.gz | tail -n +"$((KEEP + 1))" | while read -r old; do
	rm -- "$old"
	echo "backup: rotated out $old"
done
