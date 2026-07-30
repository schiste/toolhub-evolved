// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { icon } from "../atoms/icon.js";

/** @param {unknown} value */
function num(value) {
	const n = Number(value);
	return Number.isFinite(n) ? n : null;
}

/** @param {unknown} value */
function gradeLabel(value) {
	const grade = String(value || "");
	if (grade === "strong") return t("toolHealth.gradeStrong", "Strong");
	if (grade === "good") return t("toolHealth.gradeGood", "Good");
	if (grade === "needs-attention") return t("toolHealth.gradeAttention", "Needs attention");
	if (grade === "unknown") return t("toolHealth.gradeUnknown", "Unknown");
	return t("toolHealth.gradeRisk", "High risk");
}

/** @param {unknown} grade */
function toneForGrade(grade) {
	const value = String(grade || "");
	if (value === "strong" || value === "good") return "good";
	if (value === "needs-attention") return "watch";
	if (value === "unknown") return "unknown";
	return "risk";
}

/** @param {unknown} status */
function maintainerLabel(status) {
	const value = String(status || "unknown");
	if (value === "maintained") return t("toolHealth.maintained", "Maintained");
	if (value === "active-maintainer") return t("toolHealth.activeMaintainer", "Active maintainer");
	if (value === "verified-maintainer") return t("toolHealth.verifiedMaintainer", "Verified maintainer");
	if (value === "maintainer-stale") return t("toolHealth.maintainerStale", "Maintainer stale");
	return t("toolHealth.maintainerUnknown", "Maintainer unknown");
}

/** @param {unknown} value */
function scoreText(value) {
	const score = num(value);
	return score === null ? "—" : String(Math.round(score));
}

/** @param {any} dimension */
function dimensionRow(dimension) {
	const score = scoreText(dimension?.score);
	const weight = num(dimension?.weight);
	const confidence = num(dimension?.confidence);
	const meta = [
		t("toolHealth.scoreValue", "score {score}", { score }),
		weight === null ? "" : t("toolHealth.weightValue", "weight {weight}", { weight: String(weight) }),
		confidence === null
			? ""
			: t("toolHealth.confidenceValue", "confidence {confidence}", {
					confidence: `${Math.round(confidence * 100)}%`
				})
	]
		.filter(Boolean)
		.join(" · ");
	return `<li class="health-popover__row">
		<strong>${esc(dimension?.label || dimension?.key || "")}</strong>
		<span>${esc(meta)}</span>
		${dimension?.status ? `<span>${esc(String(dimension.status))}</span>` : ""}
		${dimension?.summary ? `<em>${esc(String(dimension.summary))}</em>` : ""}
	</li>`;
}

/** @param {any} summary */
function dimensionsList(summary) {
	const dimensions = Array.isArray(summary?.health?.dimensions) ? summary.health.dimensions : [];
	if (dimensions.length === 0) {
		return `<p class="health-popover__empty">${t("toolHealth.noDimensions", "No local dimensions are available yet.")}</p>`;
	}
	return `<ul class="health-popover__rows" role="list">${dimensions.map((/** @type {any} */ item) => dimensionRow(item)).join("")}</ul>`;
}

/** @param {any} summary */
function calculationText(summary) {
	const calc = summary?.health?.calculation || {};
	const included = num(calc.includedDimensionCount) || 0;
	const total = num(calc.dimensionCount) || 0;
	const weight = num(calc.includedWeight);
	return t(
		"toolHealth.calculation",
		"Calculation: weighted average across {included} of {total} dimensions; included weight {weight}.",
		{
			included: String(included),
			total: String(total),
			weight: weight === null ? "0" : String(weight)
		}
	);
}

/** @param {any} dimension */
function dimensionTooltipLine(dimension) {
	const label = String(dimension?.label || dimension?.key || "");
	const score = scoreText(dimension?.score);
	const weight = num(dimension?.weight);
	const confidence = num(dimension?.confidence);
	const parts = [
		t("toolHealth.scoreValue", "score {score}", { score }),
		weight === null ? "" : t("toolHealth.weightValue", "weight {weight}", { weight: String(weight) }),
		confidence === null
			? ""
			: t("toolHealth.confidenceValue", "confidence {confidence}", {
					confidence: `${Math.round(confidence * 100)}%`
				}),
		dimension?.status ? String(dimension.status) : ""
	].filter(Boolean);
	return `${label}: ${parts.join(" · ")}`;
}

/** @param {any} summary */
function healthScoreTooltip(summary) {
	const health = summary?.health || {};
	const score = scoreText(health.score);
	const grade = gradeLabel(health.grade);
	const dimensions = Array.isArray(health.dimensions) ? health.dimensions : [];
	const lines = [
		t("toolHealth.scoreTitle", "Local Evolved health score"),
		t("toolHealth.scoreTooltipSummary", "Health {score} · {grade}", { score, grade }),
		calculationText(summary)
	];
	if (dimensions.length > 0) {
		lines.push(t("toolHealth.includedDimensions", "Included dimensions:"));
		for (const item of dimensions) lines.push(`- ${dimensionTooltipLine(item)}`);
	} else {
		lines.push(t("toolHealth.noDimensions", "No local dimensions are available yet."));
	}
	return lines.join("\n");
}

/** @param {any} summary */
export function healthScoreChip(summary) {
	if (!summary?.health) return "";
	const score = scoreText(summary.health.score);
	const grade = gradeLabel(summary.health.grade);
	const tone = toneForGrade(summary.health.grade);
	const tooltip = healthScoreTooltip(summary);
	return `<span class="health-score health-score--${esc(tone)}" title="${esc(tooltip)}" aria-label="${esc(tooltip)}" tabindex="0">
		${icon("analyze")} <span>${t("toolHealth.healthScore", "Health {score}", { score })}</span><span class="health-score__grade">${esc(grade)}</span>
		<span class="health-score__tooltip" aria-hidden="true">${esc(tooltip)}</span>
	</span>`;
}

/**
 * @param {any} summary
 * @param {{ compact?: boolean }} [opts]
 */
export function maintainerDisclosure(summary, opts = {}) {
	if (!summary?.maintainerDimension && !summary?.maintainer) return "";
	const dimension = summary?.maintainerDimension || {};
	const status = String(dimension.status || "unknown");
	const tone =
		status === "maintained" || status === "active-maintainer"
			? "good"
			: status.includes("stale")
				? "risk"
				: "watch";
	const counts = summary?.maintainer?.counts || {};
	const confidence =
		num(dimension.bestConfidence ?? summary?.maintainer?.bestConfidence) ??
		Math.round((num(dimension.confidence) || 0) * 100);
	const label = maintainerLabel(status);
	const compact = opts.compact ? " health-popover--compact" : "";
	return `<details class="health-popover${compact}">
		<summary class="health-chip health-chip--${esc(tone)}" aria-label="${esc(t("toolHealth.openMaintainerSignals", "{label}; open calculation signals", { label }))}">
			${icon("group")} <span class="health-chip__label">${esc(label)}</span>
		</summary>
		<div class="health-popover__panel">
			<div class="health-popover__head">
				<strong>${esc(label)}</strong>
				<span>${t("toolHealth.confidenceValue", "confidence {confidence}", { confidence: `${Math.round(confidence)}%` })}</span>
			</div>
			<dl class="health-popover__facts">
				<div><dt>${t("toolHealth.maintainers", "Maintainers")}</dt><dd>${esc(String(counts.maintainers ?? 0))}</dd></div>
				<div><dt>${t("toolHealth.verified", "Verified")}</dt><dd>${esc(String(counts.verifiedMaintainers ?? 0))}</dd></div>
				<div><dt>${t("toolHealth.active", "Active")}</dt><dd>${esc(String(counts.activeMaintainers ?? 0))}</dd></div>
			</dl>
			${dimensionsList(summary)}
			<p class="health-popover__formula">${esc(calculationText(summary))}</p>
		</div>
	</details>`;
}
