// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, safeUrl } from "./dom.js";
import { countLabel, fmt, plural, views } from "./i18n.js";
import { starString, synthHealth, synthReviews, synthUsage } from "./synth.js";

export function statusBadge(t) {
	const st = t.status || { level: "green", label: "Healthy" };
	return (t.deprecated || t.experimental) ? `<span class="status status--${st.level}"><span class="dot dot--${st.level}"></span>${esc(st.label)}</span>` : "";
}
export function healthBadge(t) {
	const h = synthHealth(t.name);
	return `<span class="status status--${h.level} experimental"><span class="dot dot--${h.level}"></span>${esc(h.label)}</span>`;
}
export function popularityBadge(t) { return `<span class="views experimental"><span aria-hidden="true">🔥</span> ${views(t.weeklyViews)}</span>`; }
export function reviewsBlock(t) {
	const r = synthReviews(t.name);
	return `<div class="reviews__agg">
						<span class="reviews__stars" aria-hidden="true">${starString(r.rating)}</span>
						<span class="reviews__score">${r.rating.toFixed(1)}</span>
						<span class="reviews__count">· ${esc(countLabel(r.count, "review", "reviews"))}</span>
					</div>`;
}
export function usageBlock(t) {
	const u = synthUsage(t.name);
	return `<p class="usage"><strong>${fmt(u)}</strong> ${plural(u, { one: "editor used", other: "editors used" })} this in the last 30 days</p>`;
}
export function metaItem(k, v) { return `<div><div class="meta__k">${k}</div><div class="meta__v" dir="auto">${v || "—"}</div></div>`; }
export function linkOut(label, url) { const u = safeUrl(url); return u ? `<a class="btn btn--outline" href="${u}" target="_blank" rel="noopener">${label} <span aria-hidden="true">↗</span></a>` : ""; }
export const wikiLabel = (a) => (!a || !a.length ? "Any wiki" : a.includes("*") ? "All wikis" : a.map(esc).join(", "));
export const langLabel = (a) => (!a || !a.length ? "English (default)" : a.map(esc).join(", "));
// Compact "works on" label for cards (full list shown on the detail page).
export const wikiShort = (a) => (!a || !a.length ? "Any wiki" : a.includes("*") ? "All wikis" : (a.length === 1 ? a[0] : countLabel(a.length, "wiki", "wikis")));
export function keywordTags(t, opts) {
	opts = opts || {};
	const keys = opts.limit == null ? (t.keywords || []) : (t.keywords || []).slice(0, opts.limit);
	return keys.map((k) => `<a class="tag" href="#/search?keywords__term=${encodeURIComponent(k)}"${dirAttrs(k)}>${esc(k)}</a>`).join("") || (opts.empty || "");
}
export function glanceChips(t) {
	return [
		t.toolType && `<span class="glance"${dirAttrs(t.toolType)}>${esc(t.toolType)}</span>`,
		t.license && `<span class="glance"${dirAttrs(t.license)}>${esc(t.license)}</span>`,
		`<span class="glance"${dirAttrs(wikiLabel(t.forWikis))}>${esc(wikiLabel(t.forWikis))}</span>`,
		(t.uiLanguages && t.uiLanguages.length) && `<span class="glance">${esc(countLabel(t.uiLanguages.length, "language", "languages"))}</span>`,
	].filter(Boolean).join("");
}
