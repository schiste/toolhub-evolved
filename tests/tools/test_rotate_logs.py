# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the copy-truncate log rotator."""

import gzip
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROTATE = ROOT / "tools" / "rotate-logs.sh"


def run_rotate(log_dir: Path, *, max_bytes: int = 100, keep: int = 3) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(ROTATE)],
        cwd=ROOT,
        env={
            "HOME": str(log_dir),
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "TOOLHUB_LOG_DIR": str(log_dir),
            "TOOLHUB_LOG_MAX_BYTES": str(max_bytes),
            "TOOLHUB_LOG_KEEP": str(keep),
            "TOOLHUB_DEPLOY_LOG_RETENTION_DAYS": "14",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_rotates_oversized_log_and_preserves_the_inode(tmp_path):
    """The open-file-descriptor guarantee: writers must stay attached after rotation."""
    log = tmp_path / "uwsgi.log"
    log.write_text("x" * 500)
    inode = log.stat().st_ino

    result = run_rotate(tmp_path)

    assert result.returncode == 0, result.stderr
    assert log.read_text() == ""  # truncated in place, not renamed
    assert log.stat().st_ino == inode  # a live uwsgi keeps writing here
    assert gzip.decompress((tmp_path / "uwsgi.log.1.gz").read_bytes()) == b"x" * 500
    assert "1 rotated" in result.stdout


def test_leaves_logs_under_the_threshold_alone(tmp_path):
    log = tmp_path / "crawler.out"
    log.write_text("short")

    result = run_rotate(tmp_path)

    assert result.returncode == 0, result.stderr
    assert log.read_text() == "short"
    assert not (tmp_path / "crawler.out.1.gz").exists()
    assert "1 files checked, 0 rotated" in result.stdout


def test_shifts_generations_and_drops_the_oldest(tmp_path):
    log = tmp_path / "catalog-sync.err"
    for run in range(4):  # keep=3, so the fourth rotation evicts the first
        log.write_text(f"run{run}" + "y" * 500)
        assert run_rotate(tmp_path, keep=3).returncode == 0

    assert not (tmp_path / "catalog-sync.err.4.gz").exists()
    newest = gzip.decompress((tmp_path / "catalog-sync.err.1.gz").read_bytes())
    oldest = gzip.decompress((tmp_path / "catalog-sync.err.3.gz").read_bytes())
    assert newest.startswith(b"run3")
    assert oldest.startswith(b"run1")  # run0 rotated out


def test_covers_uwsgi_and_every_job_stream(tmp_path):
    for name in ("uwsgi.log", "crawler.out", "crawler.err"):
        (tmp_path / name).write_text("z" * 500)
    (tmp_path / "notes.txt").write_text("z" * 500)  # not a log stream

    result = run_rotate(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "3 files checked, 3 rotated" in result.stdout
    assert not (tmp_path / "notes.txt.1.gz").exists()
    assert (tmp_path / "notes.txt").read_text() == "z" * 500


def test_rotates_and_prunes_per_deployment_streams(tmp_path):
    deployment_logs = tmp_path / "deployment-logs"
    deployment_logs.mkdir()
    current = deployment_logs / "projection-refresh-current.out"
    expired = deployment_logs / "projection-refresh-expired.err"
    current.write_text("z" * 500)
    expired.write_text("old failure")
    old = time.time() - 16 * 24 * 60 * 60
    os.utime(expired, (old, old))

    result = run_rotate(tmp_path)

    assert result.returncode == 0, result.stderr
    assert current.read_text() == ""
    assert (deployment_logs / "projection-refresh-current.out.1.gz").is_file()
    assert not expired.exists()
    assert "1 expired deploy logs pruned" in result.stdout


def test_empty_log_directory_is_a_clean_no_op(tmp_path):
    """Unmatched globs arrive literally; they must not be mistaken for files."""
    result = run_rotate(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "0 files checked, 0 rotated" in result.stdout


def test_rejects_a_nonsense_keep_count(tmp_path):
    result = run_rotate(tmp_path, keep=0)

    assert result.returncode == 2
    assert "at least 1" in result.stderr


def test_jobs_manifest_runs_rotate_logs_under_job_guard():
    manifest = (ROOT / "jobs.yaml").read_text(encoding="utf-8")

    assert "- name: rotate-logs" in manifest
    assert "job_guard.sh --job-name rotate-logs" in manifest
    assert "tools/rotate-logs.sh" in manifest
