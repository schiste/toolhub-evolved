// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";
import { countLabel, views } from "../core/i18n.js";
import { completeness, endorsementOf, fitsContext, freshness, getUserContext } from "../core/signals.js";
import { synthHealth } from "../core/synth.js";
import { icon } from "./icon.js";

const STATUS_CLASSES = new Map([
	["green", { dot: "dot--green", status: "status--green" }],
	["red", { dot: "dot--red", status: "status--red" }],
	["yellow", { dot: "dot--yellow", status: "status--yellow" }]
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
	return t.deprecated || t.experimental ? statusMarkup(st) : "";
}
/** @param {Tool} t */
export function healthBadge(t) {
	const h = synthHealth(t.name);
	return statusMarkup(h, "experimental");
}
/** @param {Tool} t */
export function popularityBadge(t) {
	return `<span class="views experimental">${icon("popular")} ${views(t.weeklyViews)}</span>`;
}
/** @param {number | null | undefined} count */
export function endorsementChip(count) {
	const n = Number(count) || 0;
	if (!n) return "";
	const label = n === 1 ? "list" : "lists";
	return `<span class="signal" title="${esc(`Appears in ${countLabel(n, "curated list", "curated lists")}`)}">${icon("list")} In ${n} ${label}</span>`;
}
/**
 * @param {{ total?: number; filled?: number; items?: { ok: boolean; label: string }[] }} c
 */
export function completenessMeter(c) {
	const score =
		c && Object.prototype.hasOwnProperty.call(c, "total")
			? c
			: /** @type {{ total?: number; filled?: number }} */ (
					completeness(/** @type {Tool} */ (/** @type {unknown} */ (c || {})))
				);
	const total = Math.max(0, Number(score && score.total) || 0);
	const filled = Math.max(0, Math.min(total, Number(score && score.filled) || 0));
	const pct = total ? Math.round((filled / total) * 100) : 0;
	if (total && filled === total) {
		return `<span class="signal signal--complete" title="${esc(`Listing ${filled} of ${total} fields complete`)}">${icon("check")} Well documented</span>`;
	}
	return `<span class="signal" title="${esc(`Listing ${filled} of ${total} fields complete`)}"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:${pct}%"></span></span>${filled}/${total}</span>`;
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
	return `<span class="signal signal--fit">${icon("check")} Fits you</span>`;
}
/** @param {Tool} tool */
export function freshnessNote(tool) {
	if (!freshness(tool).fresh) return "";
	return '<span class="signal">Maintained</span>';
}
export { endorsementOf };
