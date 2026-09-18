# Contributing to Toolhub Evolved

Toolhub Evolved is an independently run companion interface for the official
Toolhub catalog. Contributions to this repository improve the Evolved service;
they do not change the canonical Toolhub API, catalog records, or Wikimedia
policy. Report upstream Toolhub behavior through the official Toolhub
Phabricator project and link the upstream task when an Evolved change depends
on it.

## Before you start

For an Evolved change, open or update a GitHub issue with the user-visible
problem, the affected boundary, and the validation you expect. For an upstream
Toolhub change, use Wikimedia Phabricator instead. Keep the two references
linked rather than silently treating one tracker as the source of truth for
the other.

Do not edit generated Aethyme files such as `AGENTS.md`, `CLAUDE.md`, or the
generated skill projections by hand. Change the repository overrides and rerun
the documented Aethyme enhancement command when that generated material really
needs to change.

## Local setup

The supported CI versions are Node.js 22 and Python 3.11. From a fresh clone:

```sh
npm ci
python3.11 -m venv .venv
.venv/bin/python -m pip install -r proxy/requirements.txt
.venv/bin/python -m pip install -r tools/python-quality-requirements.txt
```

The browser application needs the Flask proxy for local API requests:

```sh
export TOOLHUB_INSECURE_COOKIES=1
.venv/bin/python proxy/app.py
```

The proxy serves the application at `http://localhost:8000/`. Do not use a
development sign-in to test official writes: local development sessions are
Evolved-only and never grant Toolhub permissions.

## Validation

Run the smallest relevant check while iterating, then the repository gates
before requesting review:

```sh
npm run test:unit
npm run i18n:check
npm run preflight
PYTHONPATH=proxy .venv/bin/pytest tests/proxy -q --cov --cov-report=term-missing
npm run test:e2e
```

Changes to user-visible copy must use the i18n helpers and keep `en.json`,
`qqq.json`, and `locales.js` generated and in sync. Passing the i18n checks
means the English source is translation-ready; it does not mean that a
non-English catalog has been reviewed or shipped.

## Review checklist

Before asking for review, confirm that:

- the change preserves official Toolhub as the canonical catalog and write
  authority;
- Evolved-owned data is labelled, permission-checked, and review-gated where
  it becomes public;
- focused tests cover the changed behavior and the relevant full gate passes;
- API and UI copy explain whether data is official, local, cached, pending, or
  unavailable;
- new messages have translator context and positional parameters are tested;
- no credentials, private catalog snapshots, fake production metrics, or
  browser-local demo writes were introduced; and
- operational or deployment documentation is updated when the release path or
  data contract changes.

Use typed commit subjects such as `fix(i18n): remove stale legal copy`. A
substantive commit should explain the problem, decision, rationale, and
validation in its body. When multiple agent sessions share the repository,
use the Aethyme broker to lease files, submit the verified session, and let the
maintainer review the promoted commit before publishing it.

## Deployment boundary

Only an authorized maintainer publishes to the default branch or deploys the
Toolforge service. Before release, verify the exact source commit, production
manifest, and build. The Toolforge helper performs the pull, production build,
webservice restart, and post-deploy contract checks:

```sh
become toolhub-evolved
cd ~/repo
sh tools/deploy.sh
```

After deployment, verify `/healthz`, `/v1/catalog/health/`, `/v1/config/`, and
the anonymous write guard. The detailed Toolforge procedure, rollback rules,
and operational health checks live in `docs/deploy-toolforge.md` and
`docs/RUNBOOK.md`.
