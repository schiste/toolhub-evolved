#!/bin/sh
# Toolforge deploy/update helper. Run as the tool account:
#   become <toolname> && sh ~/repo/tools/deploy.sh
# Pulls the latest code and (re)starts the webservice serving ~/public_html.
set -eu

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "Updating $REPO_DIR ..."
git -C "$REPO_DIR" pull --ff-only

# Ensure ~/public_html points at the repo's static web root.
if [ ! -L "$HOME/public_html" ] || [ "$(readlink "$HOME/public_html")" != "$REPO_DIR/public_html" ]; then
	echo "Linking ~/public_html -> $REPO_DIR/public_html"
	rm -rf "$HOME/public_html"
	ln -s "$REPO_DIR/public_html" "$HOME/public_html"
fi

echo "Restarting webservice ..."
if webservice status >/dev/null 2>&1; then
	webservice restart
else
	webservice --backend=kubernetes php8.2 start
fi

echo "Done. https://$(basename "$(whoami)" | sed 's/^tools\.//').toolforge.org/"
