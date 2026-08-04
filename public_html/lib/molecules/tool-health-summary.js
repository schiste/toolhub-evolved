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
	if (grade === "strong") return t("toolHealth.gradeStrong", "Legendary");
	if (grade === "good") return t("toolHealth.gradeGood", "Great");
	if (grade === "needs-attention") return t("toolHealth.gradeAttention", "Needs attention");
	if (grade === "unknown") return t("toolHealth.gradeUnknown", "Unknown");
	return t("toolHealth.gradeRisk", "Needs attention");
}

/** @param {unknown} value */
function shortGradeLabel(value) {
	const grade = String(value || "");
	if (grade === "strong") return t("toolHealth.gradeStrongShort", "Legendary");
	if (grade === "good") return t("toolHealth.gradeGoodShort", "Great");
	if (grade === "needs-attention") return t("toolHealth.gradeWatchShort", "Needs attention");
	if (grade === "unknown") return t("toolHealth.gradeUnknownShort", "Unknown");
	return t("toolHealth.gradeRiskShort", "Needs attention");
}

/** @param {unknown} grade */
function toneForGrade(grade) {
	const value = String(grade || "");
	if (value === "strong") return "legendary";
	if (value === "good") return "good";
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

/** @param {unknown} status */
function shortMaintainerLabel(status) {
	const value = String(status || "unknown");
	if (value === "maintained") return t("toolHealth.maintainedShort", "Maintained");
	if (value === "active-maintainer") return t("toolHealth.activeMaintainerShort", "Active");
	if (value === "verified-maintainer") return t("toolHealth.verifiedMaintainerShort", "Verified");
	if (value === "maintainer-stale") return t("toolHealth.maintainerStaleShort", "Stale");
	return t("toolHealth.maintainerUnknownShort", "Unknown");
}

/** @param {unknown} value */
function scoreText(value) {
	const score = num(value);
	return score === null ? "—" : String(Math.round(score));
}

/** @param {unknown} value */
function fixedText(value) {
	const n = num(value);
	if (n === null) return "0";
	return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, "");
}

/** @param {unknown} value */
function percentText(value) {
	const n = num(value);
	return n === null ? "—" : `${Math.round(n * 100)}%`;
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

/**
 * @param {any} health
 * @returns {any[]}
 */
function includedDimensions(health) {
	const dimensions = Array.isArray(health?.dimensions) ? health.dimensions : [];
	return dimensions.filter(
		(/** @type {any} */ item) => item?.includedInScore && num(item?.score) !== null && num(item?.weight) !== null
	);
}

/** @param {any} health */
function includedWeight(health) {
	const calcWeight = num(health?.calculation?.includedWeight);
	if (calcWeight !== null) return calcWeight;
	return includedDimensions(health).reduce(
		(/** @type {number} */ total, /** @type {any} */ item) => total + (num(item?.weight) || 0),
		0
	);
}

/** @param {any} health */
function weightedSum(health) {
	return includedDimensions(health).reduce(
		(/** @type {number} */ total, /** @type {any} */ item) =>
			total + (num(item?.score) || 0) * (num(item?.weight) || 0),
		0
	);
}

/** @param {any} health */
function rawScore(health) {
	const weight = includedWeight(health);
	return weight > 0 ? weightedSum(health) / weight : null;
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

/** @param {any} summary */
function scoreArithmeticText(summary) {
	const health = summary?.health || {};
	const sum = weightedSum(health);
	const weight = includedWeight(health);
	const raw = rawScore(health);
	return t(
		"toolHealth.scoreArithmetic",
		"Weighted points {weightedSum} divided by total included weight {weight} gives {raw}; rounded score {score}.",
		{
			weightedSum: fixedText(sum),
			weight: fixedText(weight),
			raw: raw === null ? "—" : fixedText(raw),
			score: scoreText(health.score)
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
		dimension?.includedInScore === false ? t("toolHealth.excluded", "excluded") : "",
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
		calculationText(summary),
		scoreArithmeticText(summary)
	];
	if (dimensions.length > 0) {
		lines.push(t("toolHealth.includedDimensions", "Included dimensions:"));
		for (const item of dimensions) lines.push(`- ${dimensionTooltipLine(item)}`);
	} else {
		lines.push(t("toolHealth.noDimensions", "No local dimensions are available yet."));
	}
	return lines.join("\n");
}

/** @param {any} dimension */
function healthDimensionRow(dimension) {
	const score = num(dimension?.score);
	const weight = num(dimension?.weight);
	const included = Boolean(dimension?.includedInScore && score !== null && weight !== null);
	const contribution = score !== null && weight !== null && included ? score * weight : null;
	return `<li class="health-score__row${included ? "" : " health-score__row--excluded"}">
		<div class="health-score__row-head">
			<strong>${esc(dimension?.label || dimension?.key || "")}</strong>
			<span>${esc(dimension?.status ? String(dimension.status) : included ? t("toolHealth.included", "included") : t("toolHealth.excluded", "excluded"))}</span>
		</div>
		<dl class="health-score__metrics">
			<div><dt>${t("toolHealth.metricScore", "Score")}</dt><dd>${esc(scoreText(dimension?.score))}</dd></div>
			<div><dt>${t("toolHealth.metricWeight", "Weight")}</dt><dd>${esc(weight === null ? "—" : fixedText(weight))}</dd></div>
			<div><dt>${t("toolHealth.metricConfidence", "Confidence")}</dt><dd>${esc(percentText(dimension?.confidence))}</dd></div>
			<div><dt>${t("toolHealth.metricWeightedPoints", "Weighted points")}</dt><dd>${esc(contribution === null ? "—" : fixedText(contribution))}</dd></div>
		</dl>
		<p>${esc(
			included
				? t("toolHealth.dimensionEquation", "{score} × {weight} = {points} weighted points.", {
						score: scoreText(score),
						weight: fixedText(weight),
						points: fixedText(contribution)
					})
				: t(
						"toolHealth.dimensionExcluded",
						"This dimension is shown for context but is not included in the score."
					)
		)}</p>
		${dimension?.summary ? `<em>${esc(String(dimension.summary))}</em>` : ""}
	</li>`;
}

/** @param {any} sourceHealth */
function sourceHealthBreakdown(sourceHealth) {
	const dimensions = Array.isArray(sourceHealth?.dimensions) ? sourceHealth.dimensions : [];
	if (dimensions.length === 0) return "";
	return `<section class="health-score__section" aria-label="${esc(t("toolHealth.sourceBreakdown", "Source health breakdown"))}">
		<h3>${t("toolHealth.sourceBreakdown", "Source health breakdown")}</h3>
		<p>${t("toolHealth.sourceBreakdownIntro", "These deterministic analyzer dimensions explain the source-health input before it is combined with maintainer status.")}</p>
		<ul class="health-score__rows" role="list">${dimensions.map((/** @type {any} */ item) => healthDimensionRow(item)).join("")}</ul>
	</section>`;
}

/** @param {any} summary */
function healthScorePanel(summary) {
	const health = summary?.health || {};
	const score = scoreText(health.score);
	const grade = gradeLabel(health.grade);
	const dimensions = Array.isArray(health.dimensions) ? health.dimensions : [];
	const weight = includedWeight(health);
	const sum = weightedSum(health);
	const raw = rawScore(health);
	return `<div class="health-popover__panel health-score__panel">
		<div class="health-popover__head">
			<strong>${t("toolHealth.scoreTitle", "Local Evolved health score")}</strong>
			<span>${t("toolHealth.scoreTooltipSummary", "Health {score} · {grade}", { score, grade })}</span>
		</div>
		<p class="health-score__formula">${esc(calculationText(summary))}</p>
		<p class="health-score__equation">${esc(
			t(
				"toolHealth.scoreEquation",
				"{weightedSum} weighted points ÷ {weight} total weight = {raw}; rounded to {score}.",
				{
					weightedSum: fixedText(sum),
					weight: fixedText(weight),
					raw: raw === null ? "—" : fixedText(raw),
					score
				}
			)
		)}</p>
		${
			dimensions.length > 0
				? `<ul class="health-score__rows" role="list">${dimensions.map((/** @type {any} */ item) => healthDimensionRow(item)).join("")}</ul>`
				: `<p class="health-popover__empty">${t("toolHealth.noDimensions", "No local dimensions are available yet.")}</p>`
		}
		${sourceHealthBreakdown(health.sourceHealth)}
		<p class="health-score__learn"><a href="/health-score">${t("toolHealth.learnMore", "How the health score system works")}</a></p>
	</div>`;
}

/**
 * @param {any} summary
 * @param {{ compact?: boolean }} [opts]
 */
export function healthScoreChip(summary, opts = {}) {
	if (!summary?.health) return "";
	const score = scoreText(summary.health.score);
	const grade = opts.compact ? shortGradeLabel(summary.health.grade) : gradeLabel(summary.health.grade);
	const fullGrade = gradeLabel(summary.health.grade);
	const tone = toneForGrade(summary.health.grade);
	const tooltip = healthScoreTooltip(summary);
	const compactClass = opts.compact ? " health-popover--compact" : "";
	const chipClass = opts.compact ? " health-score--compact" : "";
	const visibleScore = opts.compact ? esc(score) : t("toolHealth.healthScore", "Health {score}", { score });
	return `<details class="health-popover health-popover--score${compactClass}">
		<summary class="status health-score health-score--${esc(tone)}${chipClass}" title="${esc(tooltip)}" aria-label="${esc(t("toolHealth.openScoreSignals", "Health {score} · {grade}; open calculation details", { score, grade: fullGrade }))}">
			${icon("analyze")} <span>${visibleScore}</span><span class="health-score__grade">${esc(grade)}</span>
		</summary>
		${healthScorePanel(summary)}
	</details>`;
}

/**
 * @param {any} summary
 * @param {{ compact?: boolean, short?: boolean }} [opts]
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
	const counts = summary?.maintainer?.healthCounts || {};
	const confidence =
		num(dimension.bestConfidence ?? summary?.maintainer?.bestConfidence) ??
		Math.round((num(dimension.confidence) || 0) * 100);
	const label = maintainerLabel(status);
	const visibleLabel = opts.short ? shortMaintainerLabel(status) : label;
	const compact = opts.compact ? " health-popover--compact" : "";
	const chipClass = opts.compact ? " health-chip--compact" : "";
	return `<details class="health-popover${compact}">
		<summary class="status health-chip health-chip--${esc(tone)}${chipClass}" title="${esc(label)}" aria-label="${esc(t("toolHealth.openMaintainerSignals", "{label}; open calculation signals", { label }))}">
			${icon("group")} <span class="health-chip__label">${esc(visibleLabel)}</span>
		</summary>
		<div class="health-popover__panel">
			<div class="health-popover__head">
				<strong>${esc(label)}</strong>
				<span>${t("toolHealth.confidenceValue", "confidence {confidence}", { confidence: `${Math.round(confidence)}%` })}</span>
			</div>
			<dl class="health-popover__facts">
				<div><dt>${t("toolHealth.maintainers", "Maintainers")}</dt><dd>${esc(String(counts.maintainers ?? 0))}</dd></div>
				<div><dt>${t("toolHealth.verified", "Verified")}</dt><dd>${esc(String(counts.verifiedPeople ?? 0))}</dd></div>
				<div><dt>${t("toolHealth.active", "Active")}</dt><dd>${esc(String(counts.activePeople ?? 0))}</dd></div>
			</dl>
			${dimensionsList(summary)}
			<p class="health-popover__formula">${esc(calculationText(summary))}</p>
		</div>
	</details>`;
}
