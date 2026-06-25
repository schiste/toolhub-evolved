// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, normalizeVcsUrl, safeUrl } from "../core/dom.js";
import { countLabel } from "../core/i18n.js";
import { button } from "./button.js";

export function metaItem(k, v) {
	return `<div><div class="meta__k">${k}</div><div class="meta__v" dir="auto">${v || "—"}</div></div>`;
}
export function linkOut(label, url) {
	const raw = String(url === null || url === undefined ? "" : url).trim();
	if (!raw) return "";
	const u = safeUrl(normalizeVcsUrl(raw));
	if (u) {
		return button(label, {
			variant: "outline",
			href: u,
			icon: "external",
			attrs: 'target="_blank" rel="noopener nofollow"'
		});
	}
	return `<span class="linkout-bad">${esc(label)}: <span${dirAttrs(raw)}>${esc(raw)}</span></span>`;
}
export const wikiLabel = (a) =>
	!a || a.length === 0 ? "Any wiki" : a.includes("*") ? "All wikis" : a.map((item) => esc(item)).join(", ");
export const langLabel = (a) => (!a || a.length === 0 ? "English (default)" : a.map((item) => esc(item)).join(", "));
// Compact "works on" label for cards (full list shown on the detail page).
export const wikiShort = (a) =>
	!a || a.length === 0
		? "Any wiki"
		: a.includes("*")
			? "All wikis"
			: a.length === 1
				? a[0]
				: countLabel(a.length, "wiki", "wikis");
export function keywordTags(t, opts = {}) {
	const keys =
		opts.limit === null || opts.limit === undefined ? t.keywords || [] : (t.keywords || []).slice(0, opts.limit);
	return (
		keys
			.map(
				(k) =>
					`<a class="tag" href="/search?keywords__term=${encodeURIComponent(k)}"${dirAttrs(k)}>${esc(k)}</a>`
			)
			.join("") ||
		opts.empty ||
		""
	);
}
export function glanceChips(t) {
	return [
		t.toolType && `<span class="glance"${dirAttrs(t.toolType)}>${esc(t.toolType)}</span>`,
		t.license && `<span class="glance"${dirAttrs(t.license)}>${esc(t.license)}</span>`,
		`<span class="glance"${dirAttrs(wikiLabel(t.forWikis))}>${esc(wikiLabel(t.forWikis))}</span>`,
		t.uiLanguages &&
			t.uiLanguages.length > 0 &&
			`<span class="glance">${esc(countLabel(t.uiLanguages.length, "language", "languages"))}</span>`
	]
		.filter(Boolean)
		.join("");
}
