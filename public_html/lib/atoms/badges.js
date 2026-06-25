// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";
import { countLabel, views } from "../core/i18n.js";
import { completeness, endorsementOf, fitsContext, freshness, getUserContext } from "../core/signals.js";
import { synthHealth } from "../core/synth.js";
import { icon } from "./icon.js";

export function statusBadge(t) {
	const st = t.status || { level: "green", label: "Healthy" };
	return (t.deprecated || t.experimental) ? `<span class="status status--${st.level}"><span class="dot dot--${st.level}"></span>${esc(st.label)}</span>` : "";
}
export function healthBadge(t) {
	const h = synthHealth(t.name);
	return `<span class="status status--${h.level} experimental"><span class="dot dot--${h.level}"></span>${esc(h.label)}</span>`;
}
export function popularityBadge(t) { return `<span class="views experimental">${icon("popular")} ${views(t.weeklyViews)}</span>`; }
export function endorsementChip(count) {
	const n = Number(count) || 0;
	if (!n) return "";
	const label = n === 1 ? "list" : "lists";
	return `<span class="signal" title="${esc("Appears in " + countLabel(n, "curated list", "curated lists"))}">${icon("list")} In ${n} ${label}</span>`;
}
export function completenessMeter(c) {
	const score = c && Object.prototype.hasOwnProperty.call(c, "total") ? c : completeness(c || {});
	const total = Math.max(0, Number(score && score.total) || 0);
	const filled = Math.max(0, Math.min(total, Number(score && score.filled) || 0));
	const pct = total ? Math.round((filled / total) * 100) : 0;
	if (total && filled === total) {
		return `<span class="signal signal--complete" title="${esc(`Listing ${filled} of ${total} fields complete`)}">${icon("check")} Well documented</span>`;
	}
	return `<span class="signal" title="${esc(`Listing ${filled} of ${total} fields complete`)}"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:${pct}%"></span></span>${filled}/${total}</span>`;
}
export function fitChip(tool) {
	if (!fitsContext(tool, getUserContext()).fits) return "";
	return `<span class="signal signal--fit">${icon("check")} Fits you</span>`;
}
export function freshnessNote(tool) {
	if (!freshness(tool).fresh) return "";
	return '<span class="signal">Maintained</span>';
}
export { endorsementOf };
