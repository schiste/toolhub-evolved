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

echo "Done. https://$(whoami | sed 's/^tools\.//').toolforge.org/"
