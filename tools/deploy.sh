#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Toolforge update helper for the Python webservice (Flask app in proxy/).
# Run as the tool account:  become <toolname> && sh ~/repo/tools/deploy.sh
# (First-time setup of the venv is in docs/deploy-toolforge.md.)
set -eu

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "Updating $REPO_DIR ..."
git -C "$REPO_DIR" pull --ff-only

# The python webservice runs ~/www/python/src/app.py (symlinked to proxy/).
mkdir -p "$HOME/www/python"
ln -sfn "$REPO_DIR/proxy" "$HOME/www/python/src"
# uWSGI reads this path; symlinking keeps the deployed settings identical to the
# reviewed file rather than something edited in place on the server.
ln -sfn "$REPO_DIR/proxy/uwsgi.ini" "$HOME/www/python/uwsgi.ini"

# Build the production dist/ (best-effort). app.py serves dist/ when present and
# falls back to public_html/ otherwise, so any failure here just means the raw
# source is served (still gzipped at the edge) — never a broken deploy. Toolforge
# has no Node, so we minify CSS with pure-Python rcssmin in the webservice venv.
VENV_PY="$HOME/www/python/venv/bin/python"

# Run a python script with the tool's environment (TOOLHUB_DB_URL, OAuth
# secrets, ...). Those are injected into webservice/job pods only, never into
# the `become` shell this script runs in, so any step that talks to the
# configured database has to go through here. Output is captured to a file
# because the shell pod does not reliably stream back, then relayed.
run_with_tool_env() {
	_out="$HOME/.deploy-step.out"
	rm -f "$_out"
	# The pod records its own exit status in the file. `webservice shell` does
	# not reliably propagate one (it falls back to streaming logs), so reading
	# the marker is exact where trusting $? or grepping for error text is not.
	webservice python3.13 shell -- \
		sh -c "$VENV_PY $1 > $_out 2>&1; echo \"__EXIT=\$?\" >> $_out" >/dev/null 2>&1 || true

	# The file is written in the pod and read here over NFS, so it can take a
	# moment to become visible. Wait for the marker rather than racing it.
	#
	# Generous on purpose. This budget covers pod scheduling as well as the step
	# itself, and giving up early is worse than waiting: the step keeps running
	# after the deploy aborts, so a schema migration can land while the old code
	# is still being served. A migration that dropped retired tables did exactly
	# that and 500ed the maintainer endpoints until the restart caught up.
	_waited=0
	while [ "$_waited" -lt 600 ]; do
		if grep -q '^__EXIT=' "$_out" 2>/dev/null; then
			break
		fi
		sleep 1
		_waited=$((_waited + 1))
	done

	if [ -f "$_out" ]; then
		grep -v '^__EXIT=' "$_out" | sed 's/^/  /'
	fi
	_status="$(sed -n 's/^__EXIT=//p' "$_out" 2>/dev/null | tail -1)"
	if [ -z "$_status" ]; then
		echo "  step did not report an exit status after ${_waited}s" >&2
		return 1
	fi
	if [ "$_status" -ne 0 ]; then
		echo "  step exited $_status" >&2
		return 1
	fi
	return 0
}

if [ -x "$VENV_PY" ]; then
	# Keep the venv in sync with requirements BEFORE restarting: a pull that adds
	# a dependency (e.g. SQLAlchemy) would otherwise restart into ImportError.
	# Under `set -eu` a failed install aborts the deploy while the old process
	# keeps serving — loud failure, no broken restart.
	echo "Syncing Python dependencies ..."
	"$VENV_PY" -m pip install -q -r "$REPO_DIR/proxy/requirements.txt"
	# Row-level migrations, once, BEFORE the restart. Schema setup inside the
	# webservice is DDL-only on purpose: a migration proportional to table size
	# would otherwise run in every worker on every restart, blocking them from
	# serving. Under `set -eu` a failure aborts the deploy while the old process
	# keeps serving.
	#
	# Run inside a webservice shell, not here: Toolforge injects the tool's
	# environment (TOOLHUB_DB_URL and friends) into webservice and job pods
	# only. A DB step run directly from this script reads no TOOLHUB_DB_URL,
	# falls back to the repo-local SQLite file, and reports success having
	# touched nothing real. --require-configured-db makes that fail loudly.
	echo "Running data migrations ..."
	run_with_tool_env "$REPO_DIR/proxy/migrate.py --require-configured-db"
	# Publish a complete account projection before the new UI can serve it. The
	# sync is resumable, and it retains the last complete generation if Toolhub
	# fails or its reported count changes during the cycle. A failed initial
	# refresh aborts before restart, leaving the previous release serving.
	echo "Refreshing official Toolhub account projection ..."
	run_with_tool_env "$REPO_DIR/proxy/account_sync.py --complete"
	# Materialize a first bounded cross-system identity batch before the new
	# directory is served. The hourly job continues through the remaining
	# population and retries transient CentralAuth or LDAP failures.
	echo "Resolving public identity projection ..."
	run_with_tool_env "$REPO_DIR/proxy/people_reconcile.py --identities-only --candidate-label-limit 100"
	echo "Building production dist/ ..."
	"$VENV_PY" -m pip install -q rcssmin==1.2.2 >/dev/null 2>&1 || true
	"$VENV_PY" "$REPO_DIR/tools/build_changelog.py"
	"$VENV_PY" "$REPO_DIR/tools/record_deployment.py"
	"$VENV_PY" "$REPO_DIR/tools/build_dist.py" || echo "  dist build skipped — serving raw source"
	"$VENV_PY" -c "from pathlib import Path; import sys; path = (Path('$REPO_DIR') / 'dist/data/deployments.json').resolve(); print(f'  release manifest: {path}'); sys.exit('release manifest missing after dist build') if not path.is_file() or path.stat().st_size == 0 else None"
	# Same reason as the migration above: without the tool environment this
	# warmed a repo-local SQLite file and reported "warmed=13" while the
	# configured shared cache stayed cold.
	echo "Prewarming shared API cache ..."
	run_with_tool_env "$REPO_DIR/proxy/cache_invalidation.py" || echo "  prewarm skipped"
else
	echo "Webservice venv not found; serving raw source (dist/ not built)."
fi

echo "Restarting webservice ..."
if webservice status >/dev/null 2>&1; then
	webservice restart
else
	webservice python3.13 start
fi

TOOL_NAME="$(whoami | sed 's/^tools\.//')"
BASE_URL="https://$TOOL_NAME.toolforge.org"

echo "Waiting for webservice to serve the app ..."
attempt=1
ready=0
while [ "$attempt" -le 30 ]; do
	if curl -fsS -o /dev/null "$BASE_URL/" \
		&& curl -fsS -o /dev/null "$BASE_URL/main.js" \
		&& curl -fsS -o /dev/null "$BASE_URL/views/experiments.js" \
		&& curl -fsS -o /dev/null "$BASE_URL/lib/atoms/badges.js"; then
		ready=1
		break
	fi
	sleep 2
	attempt=$((attempt + 1))
done

if [ "$ready" -ne 1 ]; then
	echo "Webservice did not become healthy after restart; current status:" >&2
	webservice status >&2 || true
	exit 1
fi

echo "Prewarming derived Evolved endpoints ..."
# The landing page is one composed payload; warm it so the first visitor after a
# deploy reads a cached row instead of paying for the composition.
if ! curl -fsS --max-time 60 -o /dev/null "$BASE_URL/v1/home/"; then
	echo "  home prewarm skipped" >&2
fi
if ! curl -fsS --max-time 30 -o /dev/null "$BASE_URL/v1/graph/"; then
	echo "  graph prewarm skipped" >&2
fi
if ! curl -fsS --max-time 30 -o /dev/null "$BASE_URL/v1/tools/summaries/?names=toolforge-toolhub-evolved"; then
	echo "  tool summary prewarm skipped" >&2
fi

echo "Done. $BASE_URL/"
