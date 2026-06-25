#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
set -eu

git config core.hooksPath .githooks
chmod +x .githooks/pre-push tools/quality.mjs tools/install-hooks.sh tools/replay-gate.sh

npm ci
npx playwright install chromium

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
"$PYTHON_BIN" -m venv .quality/python
.quality/python/bin/python -m pip install --upgrade pip
.quality/python/bin/python -m pip install -r tools/python-quality-requirements.txt

echo "Git hooks installed: pre-push runs tools/quality.mjs"
