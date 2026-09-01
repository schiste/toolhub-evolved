# SPDX-License-Identifier: GPL-3.0-or-later

"""Enforce the committed mutation-score and infrastructure-quality floors."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = ROOT / ".python-mutation-ratchet.json"
DEFAULT_STATS = ROOT / "mutants" / "mutmut-cicd-stats.json"
DEFAULT_MUTANTS_ROOT = ROOT / "mutants" / "backend"
AREA_MODULES = {
    "authentication": ("authz", "security", "token_crypto"),
    "outboundIo": ("outbound",),
    "dataIntegrity": ("sync", "v1_write", "inference_enrichment", "source_analysis_assessments"),
}
TIMEOUT_EXIT_CODE = -24


def mutation_score(stats: dict[str, int]) -> float:
    """Return killed-or-timed-out mutants as a percentage of decided mutants."""
    caught = stats.get("killed", 0) + stats.get("timeout", 0) + stats.get("caught_by_type_check", 0)
    denominator = caught + stats.get("survived", 0)
    return 100.0 if denominator == 0 else caught * 100.0 / denominator


def violations(stats: dict[str, int], policy: dict[str, Any]) -> list[str]:
    """Describe every score regression or untrustworthy mutation result."""
    score = mutation_score(stats)
    problems = []
    if score + 1e-9 < float(policy["minimumScore"]):
        problems.append(f"score {score:.2f}% is below floor {float(policy['minimumScore']):.2f}%")
    limits = {
        "no_tests": "maximumNoTests",
        "suspicious": "maximumSuspicious",
        "segfault": "maximumSegfault",
        "check_was_interrupted_by_user": "maximumInterrupted",
    }
    for field, policy_key in limits.items():
        actual = int(stats.get(field, 0))
        maximum = int(policy[policy_key])
        if actual > maximum:
            problems.append(f"{field} {actual} exceeds maximum {maximum}")
    return problems


def area_stats(mutants_root: Path) -> dict[str, dict[str, int | float]]:
    """Classify decided mutants by critical security and integrity area."""
    result: dict[str, dict[str, int | float]] = {}
    for area, modules in AREA_MODULES.items():
        killed = survived = timeout = infrastructure = 0
        for module in modules:
            path = mutants_root / f"{module}.py.meta"
            metadata = json.loads(path.read_text(encoding="utf-8"))
            exit_codes = metadata["exit_code_by_key"].values()
            survived += sum(code == 0 for code in exit_codes)
            killed += sum(code == 1 for code in exit_codes)
            timeout += sum(code == TIMEOUT_EXIT_CODE for code in exit_codes)
            infrastructure += sum(code not in {0, 1, TIMEOUT_EXIT_CODE} for code in exit_codes)
        decided = killed + timeout + survived
        score = 100.0 if decided == 0 else (killed + timeout) * 100.0 / decided
        result[area] = {
            "killed": killed,
            "timeout": timeout,
            "survived": survived,
            "infrastructure": infrastructure,
            "score": score,
        }
    return result


def area_violations(areas: dict[str, dict[str, int | float]], policy: dict[str, Any]) -> list[str]:
    """Prevent a gain in one critical area from hiding a regression in another."""
    problems = []
    for area, minimum in policy["areaMinimumScores"].items():
        score = float(areas[area]["score"])
        if score + 1e-9 < float(minimum):
            problems.append(f"{area} score {score:.2f}% is below floor {float(minimum):.2f}%")
    return problems


def markdown_summary(score: float, stats: dict[str, int], areas: dict[str, dict[str, int | float]]) -> str:
    """Render a compact scope classification for the Actions step summary."""
    lines = [
        "## Python mutation triage",
        "",
        f"Overall score: **{score:.2f}%** ({stats.get('survived', 0)} survivors)",
        "",
        "| Area | Score | Killed | Timeout | Survived | Infrastructure |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for area, values in areas.items():
        lines.append(
            f"| {area} | {float(values['score']):.2f}% | {values['killed']} | "
            f"{values['timeout']} | {values['survived']} | {values['infrastructure']} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    parser.add_argument("--mutants-root", type=Path, default=DEFAULT_MUTANTS_ROOT)
    parser.add_argument("--format", choices=("text", "markdown"), default="text")
    args = parser.parse_args(argv)
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    stats = json.loads(args.stats.read_text(encoding="utf-8"))
    score = mutation_score(stats)
    areas = area_stats(args.mutants_root)
    if args.format == "markdown":
        print(markdown_summary(score, stats, areas))  # noqa: T201
        return 1 if violations(stats, policy) + area_violations(areas, policy) else 0
    print(  # noqa: T201 - CI result is intentionally visible in job output.
        f"python-mutation: score={score:.2f}% killed={stats.get('killed', 0)} "
        f"timeout={stats.get('timeout', 0)} survived={stats.get('survived', 0)} "
        f"no_tests={stats.get('no_tests', 0)}"
    )
    for area, values in areas.items():
        print(  # noqa: T201
            f"python-mutation: area={area} score={float(values['score']):.2f}% "
            f"killed={values['killed']} timeout={values['timeout']} "
            f"survived={values['survived']} infrastructure={values['infrastructure']}"
        )
    problems = violations(stats, policy) + area_violations(areas, policy)
    if problems:
        print(f"python-mutation: {'; '.join(problems)}", file=sys.stderr)  # noqa: T201
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
