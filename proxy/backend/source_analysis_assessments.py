# SPDX-License-Identifier: GPL-3.0-or-later
"""Assessments, health dimensions, and stewardship status.

Turns a finished findings report and its repository context into the eight
assessments, the weighted health dimensions built from them, and the composite
healthCore. Reads the report; never produces one. Depends only on
source_analysis_common, so the scanning rules and this module cannot import each
other.

Split out of source_analyzer.py, which had grown past 3800 lines.
"""

from __future__ import annotations

from typing import Any

from backend.source_analysis_common import (
    ASSESSMENT_ATTENTION_SCORE,
    ASSESSMENT_GOOD_SCORE,
    ASSESSMENT_STRONG_SCORE,
    HEALTH_DIMENSIONS,
    HEALTH_MIN_SCORING_CONFIDENCE,
    MAINTAINER_DIMENSION_WEIGHT,
    MAX_ASSESSMENT_SIGNALS,
    MULTIPLE_CONTRIBUTOR_MIN,
    SCORING_MIN_CONFIDENCE,
    SMALL_COMMIT_HISTORY_THRESHOLD,
    _category_counts,
    _clean_context_string,
    _context_kinds,
    _declared_list,
    _has_category,
    _has_write_access,
    _int_context_value,
    _maintainer_status,
    _parse_iso_datetime,
    _publishable_rows,
)


def _maintainer_activity_context(maintainers: object, repository: object) -> dict[str, Any]:
    if not isinstance(maintainers, dict) or not maintainers:
        return {}
    age_days = _int_context_value(maintainers.get("lastActivityAgeDays"))
    if age_days is None:
        last_activity = _parse_iso_datetime(maintainers.get("lastActivityAt"))
        analyzed_at = _parse_iso_datetime(maintainers.get("analyzedAt"))
        if analyzed_at is None and isinstance(repository, dict):
            analyzed_at = _parse_iso_datetime(repository.get("analyzedAt"))
        if last_activity is not None and analyzed_at is not None:
            age_days = max(0, (analyzed_at - last_activity).days)
    status = _maintainer_status(age_days)
    maintainer_count = _int_context_value(maintainers.get("maintainerCount"))
    active_count = _int_context_value(maintainers.get("activeMaintainerCount"))
    recent_activity_count = _int_context_value(maintainers.get("recentActivityCount"))
    signals: list[dict[str, Any]] = []
    if age_days is not None:
        signals.append({"kind": "last-maintainer-activity-age", "value": age_days, "unit": "days"})
    if maintainer_count is not None:
        signals.append({"kind": "maintainer-count", "value": maintainer_count})
    if active_count is not None:
        signals.append({"kind": "active-maintainer-count", "value": active_count})
    if recent_activity_count is not None:
        signals.append({"kind": "recent-maintainer-activity-count", "value": recent_activity_count})
    source = _clean_context_string(maintainers.get("source"))
    if source:
        signals.append({"kind": "maintainer-activity-source", "value": source})
    return {
        "status": status,
        "stale": status in {"stale", "dormant"},
        "lastActivityAgeDays": age_days,
        "maintainerCount": maintainer_count,
        "activeMaintainerCount": active_count,
        "recentActivityCount": recent_activity_count,
        "signals": signals[:MAX_ASSESSMENT_SIGNALS],
    }


def _first_finding_evidence(report: dict[str, Any], bucket: str) -> dict[str, Any] | None:
    rows = report.get(bucket)
    for row in rows if isinstance(rows, list) else []:
        evidence = row.get("evidence") if isinstance(row, dict) else []
        if isinstance(evidence, list) and evidence:
            return evidence[0]
    return None


def _first_context_evidence(context: dict[str, Any], section: str, kind: str | None = None) -> dict[str, Any] | None:
    rows = context.get(section)
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if kind is None or row.get("kind") == kind:
            return {
                "path": row.get("path", ""),
                "line": row.get("line", 0),
                "match": row.get("match", ""),
                "excerpt": row.get("kind", ""),
            }
    return None


def _score_grade(score: int) -> str:
    if score >= ASSESSMENT_STRONG_SCORE:
        return "strong"
    if score >= ASSESSMENT_GOOD_SCORE:
        return "good"
    if score >= ASSESSMENT_ATTENTION_SCORE:
        return "needs-attention"
    return "high-risk"


def _bounded_score(value: int) -> int:
    return max(0, min(100, value))


def _assessment_signal(
    status: str, label: str, detail: str = "", evidence: dict[str, Any] | None = None
) -> dict[str, Any]:
    signal: dict[str, Any] = {"status": status, "label": label}
    if detail:
        signal["detail"] = detail
    if evidence:
        signal["evidence"] = evidence
    return signal


def _assessment(  # noqa: PLR0913, PLR0917 - assessment payload fields are clearer as explicit arguments.
    key: str,
    label: str,
    score: int,
    confidence: float,
    summary: str,
    signals: list[dict[str, Any]],
    recommendations: list[str],
) -> dict[str, Any]:
    bounded = _bounded_score(score)
    return {
        "key": key,
        "label": label,
        "score": bounded,
        "grade": _score_grade(bounded),
        "confidence": round(max(0.1, min(0.99, confidence)), 2),
        "summary": summary,
        "signals": signals[:MAX_ASSESSMENT_SIGNALS],
        "recommendations": recommendations[:MAX_ASSESSMENT_SIGNALS],
    }


def _metadata_completeness_assessment(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    documentation = _context_kinds(context, "documentation")
    score = 20
    signals: list[dict[str, Any]] = []
    recommendations: list[str] = []
    buckets = (
        ("projects", "Projects detected", "Add target wiki/project metadata.", 15),
        ("apis", "API usage detected", "Document which APIs the tool uses.", 15),
        ("technology", "Technology detected", "Declare the tool technology stack.", 15),
        ("dependencies", "Dependencies detected", "Declare key external libraries.", 15),
    )
    for bucket, label, recommendation, points in buckets:
        has_bucket = bool(_publishable_rows(report.get(bucket, []), SCORING_MIN_CONFIDENCE))
        score += points if has_bucket else 0
        if has_bucket:
            signals.append(_assessment_signal("positive", label, evidence=_first_finding_evidence(report, bucket)))
        else:
            signals.append(_assessment_signal("negative", recommendation))
            recommendations.append(recommendation)
    if "readme" in documentation:
        score += 10
        signals.append(
            _assessment_signal(
                "positive", "README present", evidence=_first_context_evidence(context, "documentation", "readme")
            )
        )
    else:
        recommendations.append("Add a README with purpose, setup, and usage.")
    if "license" in documentation:
        score += 10
        signals.append(
            _assessment_signal(
                "positive",
                "License file present",
                evidence=_first_context_evidence(context, "documentation", "license"),
            )
        )
    else:
        recommendations.append("Add a license file or declare the license in Toolhub.")
    return _assessment(
        "metadata-completeness",
        "Metadata completeness",
        score,
        0.72 + min(0.2, len(signals) * 0.02),
        "How much useful Toolhub metadata can be derived from the submitted context.",
        signals,
        recommendations,
    )


def _permission_clarity_assessment(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    raw_access = report["accessRights"]
    access = _publishable_rows(raw_access, SCORING_MIN_CONFIDENCE)
    auth = _publishable_rows(report["authentication"], SCORING_MIN_CONFIDENCE)
    scopes = {item["value"] for item in _publishable_rows(report["oauthScopes"], SCORING_MIN_CONFIDENCE)}
    declared_scopes = _declared_list(context, "oauthScopes")
    admin_access = _has_category(access, "administrator", SCORING_MIN_CONFIDENCE)
    write_access = _has_write_access(access, SCORING_MIN_CONFIDENCE)
    signals: list[dict[str, Any]] = []
    recommendations: list[str] = []
    score = 55
    if not access:
        if raw_access:
            signals.append(_assessment_signal("neutral", "Only low-provenance access evidence found"))
            recommendations.append("Confirm whether low-provenance access strings describe runtime behavior.")
        else:
            signals.append(_assessment_signal("neutral", "No MediaWiki access actions detected"))
            recommendations.append("Confirm whether the tool is read-only or needs wiki permissions.")
    elif write_access:
        score = 65
        signals.append(
            _assessment_signal(
                "neutral", "Write-capable actions detected", evidence=_first_finding_evidence(report, "accessRights")
            )
        )
        if auth:
            score += 15
            signals.append(
                _assessment_signal(
                    "positive",
                    "Authentication handling detected",
                    evidence=_first_finding_evidence(report, "authentication"),
                )
            )
        else:
            score -= 25
            signals.append(_assessment_signal("negative", "No authentication signal found for write actions"))
            recommendations.append("Document OAuth, bot-password, or token handling for write actions.")
        if scopes:
            score += 10
            signals.append(
                _assessment_signal("positive", "OAuth scopes inferred from source", detail=", ".join(sorted(scopes)))
            )
        else:
            recommendations.append("Declare the OAuth scopes required by this tool.")
        if admin_access:
            score -= 20
            signals.append(_assessment_signal("negative", "Elevated wiki actions detected"))
            recommendations.append("Separate administrator-level actions from normal user workflows.")
    else:
        score = 90
        signals.append(
            _assessment_signal(
                "positive",
                "Only read-oriented actions detected",
                evidence=_first_finding_evidence(report, "accessRights"),
            )
        )
    if declared_scopes:
        score += 5
        signals.append(
            _assessment_signal("positive", "Declared OAuth scopes supplied", detail=", ".join(sorted(declared_scopes)))
        )
        missing = sorted(scopes - declared_scopes)
        if missing:
            score -= 15
            signals.append(
                _assessment_signal(
                    "negative", "Inferred scopes missing from declared context", detail=", ".join(missing)
                )
            )
            recommendations.append("Reconcile declared OAuth scopes with source-code usage.")
    return _assessment(
        "permission-clarity",
        "Permission clarity",
        score,
        0.66 + min(0.25, len(access + auth + raw_access) * 0.03),
        "How clearly the source explains required wiki access, OAuth scopes, and authentication.",
        signals,
        recommendations,
    )


def _dependency_health_assessment(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    categories = _category_counts(context)
    has_manifest = bool(context.get("manifests"))
    has_lockfile = bool(context.get("lockfiles"))
    dependency_count = len(_publishable_rows(report["dependencies"], SCORING_MIN_CONFIDENCE))
    signals: list[dict[str, Any]] = []
    recommendations: list[str] = []
    score = 40
    if has_manifest:
        score += 20
        signals.append(
            _assessment_signal(
                "positive", "Dependency manifest present", evidence=_first_context_evidence(context, "manifests")
            )
        )
    else:
        recommendations.append("Add a package manifest so dependencies are declared explicitly.")
    if dependency_count:
        score += 15
        signals.append(
            _assessment_signal(
                "positive",
                "External dependencies detected",
                detail=str(dependency_count),
                evidence=_first_finding_evidence(report, "dependencies"),
            )
        )
    else:
        score -= 20
        signals.append(_assessment_signal("negative", "No dependency evidence found"))
    if has_lockfile or categories.get("locked", 0):
        score += 15
        signals.append(
            _assessment_signal(
                "positive",
                "Lockfile or locked dependency evidence present",
                evidence=_first_context_evidence(context, "lockfiles"),
            )
        )
    else:
        recommendations.append("Commit a lockfile or provide one in the analysis bundle for reproducibility checks.")
    if categories.get("imported", 0) and not has_manifest:
        score -= 10
        signals.append(_assessment_signal("negative", "Dependencies inferred only from imports"))
    return _assessment(
        "dependency-health",
        "Dependency health",
        score,
        0.58 + min(0.32, (len(categories) + int(has_manifest) + int(has_lockfile)) * 0.08),
        "Whether dependency evidence is declared, reproducible, and separated from weak import inference.",
        signals,
        recommendations,
    )


def _security_review_assessment(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    warnings = _publishable_rows(report["warnings"], SCORING_MIN_CONFIDENCE)
    warning_values = {item["value"] for item in warnings}
    documentation = _context_kinds(context, "documentation")
    score = 85
    signals: list[dict[str, Any]] = []
    recommendations: list[str] = []
    if "credential-like-source" in warning_values:
        score -= 35
        signals.append(
            _assessment_signal(
                "negative",
                "Credential-looking source was redacted",
                evidence=_first_finding_evidence(report, "warnings"),
            )
        )
        recommendations.append(
            "Rotate any exposed credential-looking values and move secrets to runtime configuration."
        )
    if "administrator-actions" in warning_values:
        score -= 20
        signals.append(_assessment_signal("negative", "Administrator or suppressive actions need review"))
        recommendations.append("Document why elevated wiki rights are necessary.")
    if "write-without-auth-signal" in warning_values:
        score -= 20
        signals.append(_assessment_signal("negative", "Write action without authentication evidence"))
        recommendations.append("Add explicit authentication/token handling or document why it is external.")
    if report["authentication"]:
        score += 5
        signals.append(
            _assessment_signal(
                "positive", "Authentication signal detected", evidence=_first_finding_evidence(report, "authentication")
            )
        )
    if "security" in documentation:
        score += 5
        signals.append(
            _assessment_signal(
                "positive",
                "Security policy present",
                evidence=_first_context_evidence(context, "documentation", "security"),
            )
        )
    return _assessment(
        "security-review",
        "Security review",
        score,
        0.7 + min(0.2, len(report["warnings"]) * 0.04),
        "Static risk signals that should be reviewed before publishing metadata suggestions.",
        signals,
        recommendations,
    )


def _maintenance_readiness_assessment(context: dict[str, Any]) -> dict[str, Any]:
    documentation = _context_kinds(context, "documentation")
    repository = context.get("repository") if isinstance(context.get("repository"), dict) else {}
    score = 25
    signals: list[dict[str, Any]] = []
    recommendations: list[str] = []
    if "readme" in documentation:
        score += 20
        signals.append(
            _assessment_signal(
                "positive", "README present", evidence=_first_context_evidence(context, "documentation", "readme")
            )
        )
    else:
        recommendations.append("Add a README with setup and maintainer guidance.")
    if "license" in documentation:
        score += 10
        signals.append(_assessment_signal("positive", "License present"))
    else:
        recommendations.append("Add or declare a license.")
    if context.get("tests"):
        score += 15
        signals.append(
            _assessment_signal("positive", "Tests detected", evidence=_first_context_evidence(context, "tests"))
        )
    else:
        recommendations.append("Add a small automated test suite or smoke test.")
    if context.get("ci"):
        score += 15
        signals.append(
            _assessment_signal("positive", "CI configuration detected", evidence=_first_context_evidence(context, "ci"))
        )
    else:
        recommendations.append("Add CI to run lint/tests on changes.")
    if documentation & {"changelog", "contributing", "security", "owners"}:
        score += 10
        signals.append(_assessment_signal("positive", "Maintainer/process documentation present"))
    if repository:
        score += 10
        signals.append(_assessment_signal("positive", "Repository metadata supplied"))
    return _assessment(
        "maintenance-readiness",
        "Maintenance readiness",
        score,
        0.6 + min(0.3, len(signals) * 0.05),
        "Whether the repository has enough maintenance, docs, tests, and CI context for Toolhub reviewers.",
        signals,
        recommendations,
    )


def _activity_status_scoring(
    context: dict[str, Any], status: str, age_days: int | None
) -> tuple[int, list[dict[str, Any]], list[str]]:
    """Score one repository activity status, with the guidance that fits it.

    Archived costs the same as dormant by deliberate policy: read-only means no
    fix will ever land, whatever the maintainer intended. That does conflate
    "finished" and "moved to another forge" with "abandoned" -- recording a
    successor is what separates them, and where one exists it replaces the
    dead-end advice rather than the score.
    """
    if status == "archived":
        return (
            -35,
            [_assessment_signal("negative", "Repository is archived (read-only)")],
            [_lifecycle_recommendation(context, "Find a maintained alternative.")],
        )
    if status == "active":
        return 30, [_assessment_signal("positive", "Recent repository activity", detail=f"{age_days} days")], []
    if status == "quiet":
        return (
            10,
            [_assessment_signal("neutral", "Repository activity is quiet", detail=f"{age_days} days")],
            ["Confirm the repository still reflects the deployed tool."],
        )
    if status == "stale":
        return (
            -20,
            [_assessment_signal("negative", "Repository has stale activity", detail=f"{age_days} days")],
            ["Ask the maintainer to confirm ownership and deployment status."],
        )
    if status == "dormant":
        return (
            -35,
            [_assessment_signal("negative", "Repository appears dormant", detail=f"{age_days} days")],
            [_lifecycle_recommendation(context, "Flag the tool for maintainer outreach or archival review.")],
        )
    return (
        0,
        [_assessment_signal("neutral", "No last-commit age supplied")],
        ["Provide last commit date or age for no-longer-maintained checks."],
    )


def _maintenance_activity_assessment(context: dict[str, Any]) -> dict[str, Any]:
    maintenance = context.get("maintenance") if isinstance(context.get("maintenance"), dict) else {}
    repository = context.get("repository") if isinstance(context.get("repository"), dict) else {}
    status = str(maintenance.get("status") or "unknown")
    age_days = _int_context_value(maintenance.get("lastCommitAgeDays"))
    contributor_count = _int_context_value(maintenance.get("contributorCount"))
    commit_count = _int_context_value(maintenance.get("commitCount"))
    delta, signals, recommendations = _activity_status_scoring(context, status, age_days)
    score = 50 + delta
    if contributor_count is not None and contributor_count >= MULTIPLE_CONTRIBUTOR_MIN:
        score += 10
        signals.append(_assessment_signal("positive", "Multiple contributors detected", detail=str(contributor_count)))
    elif contributor_count == 1:
        score -= 10
        signals.append(_assessment_signal("neutral", "Single-contributor repository", detail="1"))
        recommendations.append("Consider adding secondary maintainer or ownership metadata.")
    if commit_count is not None and commit_count < SMALL_COMMIT_HISTORY_THRESHOLD:
        score -= 10
        signals.append(_assessment_signal("neutral", "Very small commit history", detail=str(commit_count)))
    if _replaced_by(context):
        signals.append(_assessment_signal("positive", "Replacement tool recorded", detail=_replaced_by(context)))
    if repository.get("dirty") is True:
        signals.append(_assessment_signal("neutral", "Local checkout had uncommitted changes"))
    return _assessment(
        "maintenance-activity",
        "Maintenance activity",
        score,
        0.56 + min(0.34, len(signals) * 0.08),
        "Whether repository activity suggests the tool is actively maintained or needs outreach.",
        signals,
        recommendations,
    )


def _operational_readiness_assessment(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    declared = context.get("declared") if isinstance(context.get("declared"), dict) else {}
    api_values = {item["value"] for item in report["apis"]}
    score = 35
    signals: list[dict[str, Any]] = []
    recommendations: list[str] = []
    if context.get("runtime"):
        score += 20
        signals.append(
            _assessment_signal(
                "positive",
                "Runtime/deploy configuration detected",
                evidence=_first_context_evidence(context, "runtime"),
            )
        )
    else:
        recommendations.append("Provide runtime or deployment configuration in the analysis context.")
    if "toolforge" in api_values or "toolforge" in _context_kinds(context, "runtime"):
        score += 20
        signals.append(_assessment_signal("positive", "Toolforge context detected"))
    if context.get("health") or declared.get("healthUrl"):
        score += 15
        signals.append(
            _assessment_signal(
                "positive", "Health-check signal present", evidence=_first_context_evidence(context, "health")
            )
        )
    else:
        recommendations.append("Expose or document a lightweight health endpoint for web services.")
    if context.get("ci"):
        score += 10
        signals.append(_assessment_signal("positive", "CI can support deployment confidence"))
    return _assessment(
        "operational-readiness",
        "Operational readiness",
        score,
        0.56 + min(0.34, len(signals) * 0.08),
        "Whether the repository exposes enough runtime and deployment signals for operators.",
        signals,
        recommendations,
    )


def _frontend_accessibility_assessment(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    technology_values = {item["value"] for item in _publishable_rows(report["technology"], SCORING_MIN_CONFIDENCE)}
    has_frontend = bool(technology_values & {"JavaScript", "TypeScript", "React", "Vue", "MediaWiki JavaScript"})
    if not has_frontend:
        return None
    dependency_values = {item["value"] for item in report["dependencies"]}
    score = 45
    signals: list[dict[str, Any]] = []
    recommendations: list[str] = []
    if context.get("accessibility"):
        score += 20
        signals.append(
            _assessment_signal(
                "positive",
                "Accessibility markup or tests detected",
                evidence=_first_context_evidence(context, "accessibility"),
            )
        )
    else:
        recommendations.append(
            "Add visible accessibility markers such as labels, aria state, or keyboard handling tests."
        )
    if any("axe" in value for value in dependency_values):
        score += 20
        signals.append(_assessment_signal("positive", "Automated a11y tooling dependency detected"))
    else:
        recommendations.append("Add automated a11y checks for web-facing tools.")
    if context.get("tests"):
        score += 10
        signals.append(_assessment_signal("positive", "Frontend-adjacent tests detected"))
    return _assessment(
        "frontend-accessibility",
        "Frontend accessibility",
        score,
        0.54 + min(0.34, len(signals) * 0.1),
        "Whether web-facing code includes deterministic accessibility evidence.",
        signals,
        recommendations,
    )


def _assessment_summary(assessments: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [int(item["score"]) for item in assessments]
    return {
        "assessmentCount": len(assessments),
        "assessmentScore": round(sum(scores) / len(scores)) if scores else 0,
    }


def _assessment_index(assessments: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("key")): item for item in assessments}


def _health_dimension(  # noqa: PLR0913 - public health dimension fields are intentionally explicit.
    key: str,
    label: str,
    score: int | None,
    weight: float,
    summary: str,
    *,
    confidence: float,
    status: str = "",
    components: tuple[str, ...] = (),
    applicable: bool = True,
) -> dict[str, Any]:
    bounded = _bounded_score(score) if score is not None else None
    grade = _score_grade(bounded) if bounded is not None else ("unknown" if applicable else "not-applicable")
    return {
        "key": key,
        "label": label,
        "score": bounded,
        "grade": grade,
        "status": status or grade,
        "weight": weight,
        "confidence": round(max(0.1, min(0.99, confidence)), 2),
        "applicable": applicable,
        "includedInScore": bounded is not None and applicable,
        "components": list(components),
        "summary": summary,
    }


def _health_dimension_from_assessments(
    index: dict[str, dict[str, Any]],
    spec: tuple[str, str, tuple[str, ...], float, str],
) -> dict[str, Any]:
    key, label, assessment_keys, weight, summary = spec
    rows = [index[item] for item in assessment_keys if item in index]
    if not rows:
        return _health_dimension(
            key,
            label,
            None,
            weight,
            summary,
            confidence=0.1,
            components=assessment_keys,
            applicable=key != "accessibility",
        )
    score = round(sum(int(item.get("score") or 0) for item in rows) / len(rows))
    confidence = sum(float(item.get("confidence") or 0.1) for item in rows) / len(rows)
    return _health_dimension(
        key,
        label,
        score,
        weight,
        summary,
        confidence=confidence,
        components=assessment_keys,
    )


def _maintainer_activity_score(activity: dict[str, Any]) -> int | None:
    status = str(activity.get("status") or "unknown")
    if status == "unknown":
        return None
    score = {"active": 85, "quiet": 70, "stale": 40, "dormant": 20}.get(status, 50)
    active_count = _int_context_value(activity.get("activeMaintainerCount"))
    maintainer_count = _int_context_value(activity.get("maintainerCount"))
    recent_activity_count = _int_context_value(activity.get("recentActivityCount"))
    if active_count is not None:
        if active_count >= MULTIPLE_CONTRIBUTOR_MIN:
            score += 10
        elif active_count == 0:
            score -= 15
    if maintainer_count is not None:
        if maintainer_count >= MULTIPLE_CONTRIBUTOR_MIN:
            score += 5
        elif maintainer_count == 0:
            score -= 25
    if recent_activity_count is not None and recent_activity_count > 0:
        score += 5
    return _bounded_score(score)


def _maintainer_activity_dimension(context: dict[str, Any]) -> dict[str, Any]:
    activity = context.get("maintainerActivity") if isinstance(context.get("maintainerActivity"), dict) else {}
    score = _maintainer_activity_score(activity)
    status = str(activity.get("status") or "unknown")
    detail = (
        "Maintainer activity supplied by trusted context." if activity else "No maintainer activity context supplied."
    )
    return _health_dimension(
        "maintainer-activity",
        "Maintainer activity",
        score,
        MAINTAINER_DIMENSION_WEIGHT,
        detail,
        confidence=0.82 if activity else 0.25,
        status=status,
    )


def _replaced_by(context: dict[str, Any]) -> str:
    lifecycle = context.get("lifecycle") if isinstance(context.get("lifecycle"), dict) else {}
    return str(lifecycle.get("replacedBy") or "").strip()


def _lifecycle_recommendation(context: dict[str, Any], fallback: str) -> str:
    """Name the successor when the maintainer recorded one.

    Telling somebody to go find an alternative, or asking a maintainer to
    confirm a tool they already retired, is wasted advice when the answer is
    sitting in the catalogue.
    """
    replaced_by = _replaced_by(context)
    return f"Use the recorded replacement: {replaced_by}" if replaced_by else fallback


def _terminal_stewardship(context: dict[str, Any], source_status: str) -> str:
    """Return the verdict no amount of maintainer activity can change, or "".

    These three do not combine with maintainer status the way the rest of the
    ladder does. A superseded tool stays superseded however busy its author is
    elsewhere, and an archived repository will receive no further work either
    way -- so pairing them with maintainer activity would only dilute them.
    """
    lifecycle = context.get("lifecycle") if isinstance(context.get("lifecycle"), dict) else {}
    # A recorded successor is the most complete thing a maintainer can say: it
    # answers "what should I use instead", which the inferred ladder below only
    # gestures at. So it wins even over an archived repository.
    if _replaced_by(context):
        return "superseded"
    if lifecycle.get("deprecated") is True:
        return "deprecated"
    if source_status == "archived":
        return "archived"
    return ""


def _stewardship_status(context: dict[str, Any]) -> str:
    source = context.get("maintenance") if isinstance(context.get("maintenance"), dict) else {}
    maintainer = context.get("maintainerActivity") if isinstance(context.get("maintainerActivity"), dict) else {}
    source_status = str(source.get("status") or "unknown")
    maintainer_status = str(maintainer.get("status") or "unknown")
    terminal = _terminal_stewardship(context, source_status)
    if terminal:
        return terminal
    stale_source = source_status in {"stale", "dormant"}
    active_maintainer = maintainer_status in {"active", "quiet"}
    stale_maintainer = maintainer_status in {"stale", "dormant"}
    if stale_source and active_maintainer:
        return "source-stale-maintainer-active"
    if stale_source and stale_maintainer:
        return "at-risk"
    if source_status in {"active", "quiet"} and stale_maintainer:
        return "maintainer-outreach-needed"
    if source_status == "active" and maintainer_status == "active":
        return "healthy"
    return "needs-context" if "unknown" in {source_status, maintainer_status} else "watch"


def _health_core(assessments: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    index = _assessment_index(assessments)
    dimensions = [_health_dimension_from_assessments(index, spec) for spec in HEALTH_DIMENSIONS]
    dimensions.insert(2, _maintainer_activity_dimension(context))
    score_weight = sum(float(item["weight"]) for item in dimensions if item["includedInScore"])
    total_weight = sum(float(item["weight"]) for item in dimensions if item["applicable"])
    weighted_score = sum(float(item["score"]) * float(item["weight"]) for item in dimensions if item["includedInScore"])
    score = round(weighted_score / score_weight) if score_weight else 0
    # Confidence used to be score_weight / total_weight -- the share of applicable
    # weight that produced a number at all. Dimensions produce a number whether or
    # not they found anything, because most of them score the absence of a thing as
    # a low score rather than as silence, so that ratio stayed high no matter how
    # little was known. A repository holding one file containing `print(1)` was
    # graded high-risk at 0.81. The dimensions themselves knew better -- they
    # reported confidences of 0.1 to 0.68 for that repository -- but the composite
    # discarded them. It now carries them, so a grade is only as believed as the
    # evidence under it.
    confidence = (
        sum(float(item["weight"]) * float(item["confidence"] or 0) for item in dimensions if item["includedInScore"])
        / total_weight
        if total_weight
        else 0.0
    )
    maintenance = context.get("maintenance") if isinstance(context.get("maintenance"), dict) else {}
    maintainer = context.get("maintainerActivity") if isinstance(context.get("maintainerActivity"), dict) else {}
    return {
        "schemaVersion": 1,
        "score": score,
        # The dimensions and the score stay visible; only the verdict is withheld.
        # A reader can still see what was measured and judge it themselves.
        "grade": _score_grade(score) if confidence >= HEALTH_MIN_SCORING_CONFIDENCE else "unknown",
        "confidence": round(confidence, 2),
        "sourceMaintenanceStatus": str(maintenance.get("status") or "unknown"),
        "maintainerActivityStatus": str(maintainer.get("status") or "unknown"),
        "stewardshipStatus": _stewardship_status(context),
        "replacedBy": _replaced_by(context),
        "dimensions": dimensions,
    }


def _health_summary(health_core: dict[str, Any]) -> dict[str, Any]:
    return {
        "healthScore": int(health_core.get("score") or 0),
        "healthGrade": str(health_core.get("grade") or "unknown"),
        "healthConfidence": float(health_core.get("confidence") or 0),
        "maintenanceStatus": str(health_core.get("sourceMaintenanceStatus") or "unknown"),
        "maintainerStatus": str(health_core.get("maintainerActivityStatus") or "unknown"),
        "stewardshipStatus": str(health_core.get("stewardshipStatus") or "needs-context"),
    }


def _assessments(report: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        _metadata_completeness_assessment(report, context),
        _permission_clarity_assessment(report, context),
        _dependency_health_assessment(report, context),
        _security_review_assessment(report, context),
        _maintenance_readiness_assessment(context),
        _maintenance_activity_assessment(context),
        _operational_readiness_assessment(report, context),
    ]
    frontend = _frontend_accessibility_assessment(report, context)
    if frontend is not None:
        rows.append(frontend)
    return rows
