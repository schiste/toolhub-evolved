// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";
import { fmt, t } from "../core/i18n.js";
import { completeness, endorsementOf, fitsContext, freshness, getUserContext } from "../core/signals.js";
import { icon } from "./icon.js";

const STATUS_CLASSES = new Map([
	["green", { dot: "dot--green", status: "status--green" }],
	["red", { dot: "dot--red", status: "status--red" }],
	["yellow", { dot: "dot--yellow", status: "status--yellow" }],
	["grey", { dot: "dot--grey", status: "status--grey" }]
]);

/** @param {string} level */
function statusClasses(level) {
	return STATUS_CLASSES.get(level) || /** @type {{ dot: string; status: string }} */ (STATUS_CLASSES.get("green"));
}

/**
 * @param {{ level: string; label: string }} state
 * @param {string} [extraClass]
 */
function statusMarkup(state, extraClass = "") {
	const classes = statusClasses(state.level);
	const extra = extraClass ? ` ${extraClass}` : "";
	return `<span class="status ${classes.status}${extra}"><span class="dot ${classes.dot}"></span>${esc(state.label)}</span>`;
}

/** @param {Tool} t */
export function statusBadge(t) {
	// status is a typed ToolStatus set by normalizeTool()/statusOf(); the fallback
	// only guards a (type-impossible) missing status on a hand-built fixture.
	const st = t.status || {
		// Stryker disable next-line StringLiteral: statusClasses() maps any unrecognized level (including "") to the green classes, so the default level string is not observable in the output — equivalent.
		level: "green",
		label: "Healthy"
	};
	// "Healthy" is the absence of news and gets no badge. Everything else is
	// something the reader would want to know before installing.
	return t.deprecated || t.experimental || t.lifecycle === "archived" ? statusMarkup(st) : "";
}
/**
 * @param {number | null | undefined} count
 * @param {{ compact?: boolean }} [opts]
 */
export function endorsementChip(count, opts = {}) {
	const n = Number(count) || 0;
	if (!n) return "";
	const text = opts.compact
		? t("badges.listCount", "$1 {{PLURAL:$2|list|lists}}", fmt(n), n)
		: t("badges.inLists", "In $1 {{PLURAL:$2|list|lists}}", fmt(n), n);
	const cls = opts.compact ? " signal--compact signal--lists" : "";
	return `<span class="signal${cls}" title="${esc(t("badges.appearsInLists", "Appears in $1 {{PLURAL:$2|curated list|curated lists}}", fmt(n), n))}">${icon("list")} ${text}</span>`;
}
/**
 * @param {{ total?: number; filled?: number; items?: { ok: boolean; label: string }[] }} c
 * @param {{ details?: boolean, numeric?: boolean }} [opts]
 */
export function completenessMeter(c, opts = {}) {
	const score =
		c && Object.prototype.hasOwnProperty.call(c, "total")
			? c
			: /** @type {{ total?: number; filled?: number }} */ (
					completeness(/** @type {Tool} */ (/** @type {unknown} */ (c || {})))
				);
	const total = Math.max(0, Number(score && score.total) || 0);
	const filled = Math.max(0, Math.min(total, Number(score && score.filled) || 0));
	const pct = total ? Math.round((filled / total) * 100) : 0;
	const title = completenessTitle(
		/** @type {{ items?: { ok: boolean; label: string }[] }} */ (score),
		filled,
		total,
		opts
	);
	if (total && filled === total && !opts.numeric) {
		return `<span class="signal signal--complete" title="${esc(title)}">${icon("check")} ${t("badges.wellDocumented", "Well documented")}</span>`;
	}
	const cls = total && filled === total ? " signal--complete" : "";
	const aria = opts.details ? ` aria-label="${esc(title)}"` : "";
	return `<span class="signal${cls}" title="${esc(title)}"${aria}><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:${pct}%"></span></span>${filled}/${total}</span>`;
}

/**
 * @param {{ items?: { ok: boolean; label: string }[] }} score
 * @param {number} filled
 * @param {number} total
 * @param {{ details?: boolean }} opts
 */
function completenessTitle(score, filled, total, opts) {
	const headline = t("badges.fieldsComplete", "Listing $1 of $2 fields complete", filled, total);
	if (!opts.details || !Array.isArray(score.items) || score.items.length === 0) return headline;
	const rows = score.items.map((item) => {
		const state = item.ok ? t("badges.done", "Done") : t("badges.missing", "Missing");
		return t("badges.fieldState", "$1: $2", state, item.label);
	});
	return [headline, ...rows].join("\n");
}
// The per-field checklist that pairs with completenessMeter (tool page + styleguide).
/**
 * @param {{ items?: { ok: boolean; label: string }[] }} complete
 */
export function completenessList(complete) {
	const rows = (complete.items || [])
		.map(
			/** @param {{ ok: boolean; label: string }} item */
			(item) =>
				`<li><span class="complete-list__icon${item.ok ? "" : " complete-list__icon--empty"}">${item.ok ? icon("check") : "○"}</span><span>${esc(item.label)}</span></li>`
		)
		.join("");
	return `<ul class="complete-list">${rows}</ul>`;
}
/** @param {Tool} tool */
export function fitChip(tool) {
	if (!fitsContext(tool, getUserContext()).fits) return "";
	return `<span class="signal signal--fit">${icon("check")} ${t("badges.fitsYou", "Fits you")}</span>`;
}
/** @param {Tool} tool */
export function freshnessNote(tool) {
	if (!freshness(tool).fresh) return "";
	return `<span class="signal">${t("badges.maintained", "Maintained")}</span>`;
}
export { endorsementOf };
