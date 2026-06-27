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

# Build the minified dist/ (best-effort). app.py serves dist/ when present and
# falls back to public_html/ otherwise, so any failure here just means the raw
# source is served (still gzipped at the edge) — never a broken deploy. Toolforge
# has no Node, so we minify with pure-Python rjsmin/rcssmin in the webservice venv.
VENV_PY="$HOME/www/python/venv/bin/python"
if [ -x "$VENV_PY" ]; then
	echo "Building minified dist/ ..."
	"$VENV_PY" -m pip install -q rjsmin==1.2.5 rcssmin==1.2.2 >/dev/null 2>&1 || true
	"$VENV_PY" "$REPO_DIR/tools/build_dist.py" || echo "  minify skipped — serving raw source"
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

echo "Done. $BASE_URL/"
