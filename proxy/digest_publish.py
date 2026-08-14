# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate missed closed UTC editions and publish them to Meta-Wiki."""

from backend import digests, job_runner


def run() -> dict[str, object]:
    """Generate and publish in one locked, restart-safe coordinator pass."""
    generated = digests.generate_due_editions()
    publication = digests.publish_pending()
    return {"generated": generated, "publication": publication}


def main() -> int:
    return job_runner.run_job("digest-publish", run, lock=True)


if __name__ == "__main__":  # pragma: no cover - Toolforge entrypoint
    raise SystemExit(main())
