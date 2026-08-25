# SPDX-License-Identifier: GPL-3.0-or-later
"""The webservice template is the only place the pod's memory limit is set."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "proxy" / "service.template"
# Toolforge's default container limit. A template that does not beat this is
# decoration: the pod would get the same memory with no file at all.
DEFAULT_MEMORY_MIB = 512
MIB_PER_UNIT = {"Mi": 1, "Gi": 1024}


def _settings() -> dict[str, str]:
    """Read the flat `key: value` map, the way job_catalog reads jobs.yaml.

    PyYAML is deliberately not a dependency of this repository, and this file is
    the same shape jobs.yaml is: scalar values and comment lines. Parsing it here
    the same way keeps the test honest about what the file may contain.
    """
    settings = {}
    for raw in TEMPLATE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(":")
        settings[key.strip()] = value.strip()
    return settings


def test_exactly_one_service_template_is_checked_in():
    """`webservice` exits 1 when it finds a second one, so the tool stops starting.

    It searches ~, ~/www/python/src, ~/www/js and ~/public_html. Only one of
    those resolves into this repository -- ~/www/python/src is a symlink to
    proxy/ -- but a second copy anywhere here is a copy waiting to be deployed
    into one of the others.
    """
    tracked = subprocess.run(  # noqa: S603 - fixed argument list, no shell
        ["git", "ls-files", "*service.template"],  # noqa: S607 - git resolved from PATH by design
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    assert tracked == ["proxy/service.template"]


def test_the_template_type_matches_the_one_deploy_starts():
    """A mismatch means the memory limit below applies to a service nobody runs."""
    deploy = (ROOT / "tools" / "deploy.sh").read_text(encoding="utf-8")
    started = re.search(r"webservice (\S+) start", deploy)

    assert started is not None, "deploy.sh no longer starts a typed webservice"
    assert _settings()["type"] == started.group(1)


def test_the_template_raises_the_memory_limit_above_the_toolforge_default():
    memory = _settings()["mem"]
    match = re.fullmatch(r"(\d+)(Mi|Gi)", memory)

    assert match is not None, f"unparseable memory limit {memory!r}"
    assert int(match.group(1)) * MIB_PER_UNIT[match.group(2)] > DEFAULT_MEMORY_MIB
