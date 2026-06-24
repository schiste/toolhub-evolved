#!/bin/sh
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
