#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Toolforge update helper for the Python webservice (Flask app in proxy/).
# Run as the tool account:  become <toolname> && sh ~/repo/tools/deploy.sh
# (First-time setup of the venv is in docs/deploy-toolforge.md.)
set -eu

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "Updating $REPO_DIR ..."
deploy_head_before="$(git -C "$REPO_DIR" rev-parse HEAD)"
git -C "$REPO_DIR" pull --ff-only
deploy_head_after="$(git -C "$REPO_DIR" rev-parse HEAD)"
deploy_id="$deploy_head_after"
if [ "$deploy_head_before" != "$deploy_head_after" ] && [ "${TOOLHUB_DEPLOY_REEXECUTED:-0}" != "1" ]; then
	echo "Restarting deploy with the updated script ..."
	exec env TOOLHUB_DEPLOY_REEXECUTED=1 sh "$REPO_DIR/tools/deploy.sh"
fi

deploy_short="$(printf '%s' "$deploy_id" | cut -c1-12)"
deploy_run_id="$(date -u +%Y%m%dT%H%M%SZ)-$deploy_short"
deployment_log_dir="$HOME/deployment-logs"
mkdir -p "$deployment_log_dir"

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
deployment_diagnostics="$HOME/deployment-diagnostics.jsonl"
deploy_started="$(date +%s.%N)"
failure_phase="bootstrap"
release_stage=""
cleanup_release_stage() {
	exit_status=$?
	trap - EXIT
	if [ -n "$release_stage" ]; then
		rm -f "$release_stage"
	fi
	if [ "$exit_status" -ne 0 ] && [ -x "$VENV_PY" ]; then
		deploy_finished="$(date +%s.%N)"
		"$VENV_PY" "$REPO_DIR/tools/deployment_diagnostics.py" --output "$deployment_diagnostics" --deployment "$deploy_id" --stage deploy --status failed --started "$deploy_started" --finished "$deploy_finished" --failure-phase "$failure_phase" || true
	fi
	exit "$exit_status"
}
trap cleanup_release_stage EXIT

# Run a Python script with the tool's environment (TOOLHUB_DB_URL, OAuth
# secrets, ...). One-off Jobs provide a bounded lifecycle and durable logs;
# interactive webservice shells can lose their attach stream while the pod
# continues, leaving a deploy unable to determine the real exit status.
run_with_tool_env() {
	_step="$1"
	_command="$2"
	_out="$HOME/${_step}-deploy.out"
	_err="$HOME/${_step}-deploy.err"
	_started="$(date +%s.%N)"
	rm -f "$_out" "$_err"
	if toolforge jobs run --wait 900 --image python3.13 --filelog \
		-o "$_out" -e "$_err" \
		--command "$VENV_PY $_command" \
		"${_step}-deploy"; then
		cat "$_out" 2>/dev/null || true
		cat "$_err" 2>/dev/null >&2 || true
		_finished="$(date +%s.%N)"
		"$VENV_PY" "$REPO_DIR/tools/deployment_diagnostics.py" --output "$deployment_diagnostics" --deployment "$deploy_id" --stage "$_step" --status completed --started "$_started" --finished "$_finished" --metrics-file "$_out" || true
		return 0
	fi
	cat "$_out" 2>/dev/null || true
	cat "$_err" 2>/dev/null >&2 || true
	_finished="$(date +%s.%N)"
	"$VENV_PY" "$REPO_DIR/tools/deployment_diagnostics.py" --output "$deployment_diagnostics" --deployment "$deploy_id" --stage "$_step" --status failed --started "$_started" --finished "$_finished" --metrics-file "$_err" --failure-phase "$_step" || true
	return 1
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
	failure_phase="migrate"
	run_with_tool_env migrate "$REPO_DIR/proxy/migrate.py --require-configured-db"
	echo "Building production dist/ ..."
	failure_phase="build"
	_build_started="$(date +%s.%N)"
	"$VENV_PY" -m pip install -q rcssmin==1.2.2 >/dev/null 2>&1 || true
	release_stage="$(mktemp /tmp/toolhub-evolved-deployment.XXXXXX)"
	"$VENV_PY" "$REPO_DIR/tools/record_deployment.py" --prepare --public-output "$release_stage"
	"$VENV_PY" "$REPO_DIR/tools/build_dist.py" --deployment-manifest "$release_stage"
	"$VENV_PY" -c "from pathlib import Path; import sys; path = (Path('$REPO_DIR') / 'dist/data/deployments.json').resolve(); print(f'  release manifest: {path}'); sys.exit('release manifest missing after dist build') if not path.is_file() or path.stat().st_size == 0 else None"
	_build_finished="$(date +%s.%N)"
	"$VENV_PY" "$REPO_DIR/tools/deployment_diagnostics.py" --output "$deployment_diagnostics" --deployment "$deploy_id" --stage build --status completed --started "$_build_started" --finished "$_build_finished" || true
	# Same reason as the migration above: without the tool environment this
	# warmed a repo-local SQLite file and reported "warmed=13" while the
	# configured shared cache stayed cold.
	echo "Prewarming shared API cache ..."
	run_with_tool_env cache-prewarm "$REPO_DIR/proxy/cache_invalidation.py" || echo "  prewarm skipped"
else
	echo "Webservice venv not found; serving raw source (dist/ not built)."
fi

echo "Restarting webservice ..."
failure_phase="restart"
restart_started="$(date +%s.%N)"
restart_status=0
set +e
if webservice status >/dev/null 2>&1; then
	webservice restart
	restart_status=$?
else
	webservice python3.13 start
	restart_status=$?
fi
set -e
if [ "$restart_status" -ne 0 ]; then
	echo "Restart command returned $restart_status; checking actual service health before failing ..." >&2
fi

TOOL_NAME="$(whoami | sed 's/^tools\.//')"
BASE_URL="https://$TOOL_NAME.toolforge.org"

# A path the build did not produce is not a 404: app.py answers any unknown
# path with index.html and a 200 so client-side routes resolve on a cold URL.
# `curl -f` therefore succeeds against a JS URL that does not exist, which is
# how the probes below kept passing after bundling moved every one of them. The
# content type is what actually distinguishes the asset from the SPA shell.
probe_js() {
	case "$(curl -fsS -o /dev/null -w '%{content_type}' "$1")" in
	*javascript*) return 0 ;;
	*) return 1 ;;
	esac
}

echo "Waiting for webservice to serve the app ..."
attempt=1
ready=0
while [ "$attempt" -le 30 ]; do
	# The entry bundle, the chunk shared by the lazy routes, and two routes that
	# are only reachable through a dynamic import — the same spread the
	# per-module probes covered before the build started concatenating them.
	if curl -fsS -o /dev/null "$BASE_URL/" \
		&& probe_js "$BASE_URL/bundle/app.js" \
		&& probe_js "$BASE_URL/bundle/common.js" \
		&& probe_js "$BASE_URL/bundle/route-views-statistics.js" \
		&& probe_js "$BASE_URL/bundle/route-views-experiments.js"; then
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
restart_finished="$(date +%s.%N)"
restart_result="completed"
if [ "$restart_status" -ne 0 ]; then
	restart_result="recovered"
fi
if [ -x "$VENV_PY" ]; then
	"$VENV_PY" "$REPO_DIR/tools/deployment_diagnostics.py" --output "$deployment_diagnostics" --deployment "$deploy_id" --stage restart --status "$restart_result" --started "$restart_started" --finished "$restart_finished" || true
fi

echo "Prewarming derived Evolved endpoints ..."
failure_phase="prewarm"
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

if [ -n "$release_stage" ]; then
	failure_phase="promote"
	echo "Recording successful deployment ..."
	"$VENV_PY" "$REPO_DIR/tools/record_deployment.py" --promote "$release_stage"
fi

echo "Loading scheduled jobs ..."
failure_phase="jobs"
toolforge jobs load "$REPO_DIR/jobs.yaml"
for retired_job in account-sync toolforge-account-sync catalog-snapshot; do
	if toolforge jobs show "$retired_job" >/dev/null 2>&1; then
		echo "Retiring superseded schedule $retired_job ..."
		toolforge jobs delete "$retired_job"
	fi
done

if [ -x "$VENV_PY" ]; then
	echo "Queuing last-good projection refresh ..."
	projection_out="$deployment_log_dir/projection-refresh-$deploy_run_id.out"
	projection_err="$deployment_log_dir/projection-refresh-$deploy_run_id.err"
	if toolforge jobs run --image python3.13 --filelog \
		-o "$projection_out" -e "$projection_err" \
		--command "$VENV_PY $REPO_DIR/proxy/projection_refresh.py" \
		projection-refresh-deploy; then
		ln -sfn "$projection_out" "$HOME/projection-refresh-deploy.out"
		ln -sfn "$projection_err" "$HOME/projection-refresh-deploy.err"
		echo "  projection logs: $projection_out and $projection_err"
	else
		echo "  projection refresh could not be queued; the scheduled job will retry" >&2
	fi
fi

if [ -x "$VENV_PY" ]; then
	deploy_finished="$(date +%s.%N)"
	"$VENV_PY" "$REPO_DIR/tools/deployment_diagnostics.py" --output "$deployment_diagnostics" --deployment "$deploy_id" --stage deploy --status completed --started "$deploy_started" --finished "$deploy_finished" || true
fi
echo "Done. $BASE_URL/"
