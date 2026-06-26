// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, normalizeVcsUrl, safeUrl } from "../core/dom.js";
import { countLabel } from "../core/i18n.js";
import { button } from "./button.js";

/**
 * @param {string} k
 * @param {string | null | undefined} v
 */
export function metaItem(k, v) {
	return `<div><div class="meta__k">${k}</div><div class="meta__v" dir="auto">${v || "—"}</div></div>`;
}
/**
 * @param {string} label
 * @param {string | null | undefined} url
 */
export function linkOut(label, url) {
	const raw = String(url === null || url === undefined ? "" : url).trim();
	if (!raw) return "";
	const u = safeUrl(normalizeVcsUrl(raw));
	if (u) {
		return button(label, {
			// Stryker disable next-line StringLiteral: button()'s variantClass("") falls back to the same "btn--outline" as variantClass("outline"), so "outline" → "" is not observable — equivalent.
			variant: "outline",
			href: u,
			icon: "external",
			attrs: 'target="_blank" rel="noopener nofollow"'
		});
	}
	return `<span class="linkout-bad">${esc(label)}: <span${dirAttrs(raw)}>${esc(raw)}</span></span>`;
}
/** @param {string[] | null | undefined} a @returns {string} */
export const wikiLabel = (a) =>
	!a || a.length === 0 ? "Any wiki" : a.includes("*") ? "All wikis" : a.map((item) => esc(item)).join(", ");
/** @param {string[] | null | undefined} a @returns {string} */
export const langLabel = (a) => (!a || a.length === 0 ? "English (default)" : a.map((item) => esc(item)).join(", "));
// Compact "works on" label for cards (full list shown on the detail page).
/** @param {string[] | null | undefined} a @returns {string} */
export const wikiShort = (a) =>
	!a || a.length === 0
		? "Any wiki"
		: a.includes("*")
			? "All wikis"
			: a.length === 1
				? a[0]
				: // Stryker disable next-line StringLiteral: this branch runs only when a.length >= 2, so countLabel() always selects the plural form; the singular "wiki" is unreachable (co-disables the asserted "wikis" literal on this line) — equivalent.
					countLabel(a.length, "wiki", "wikis");
/**
 * @param {Tool} t
 * @param {{ limit?: number | null; empty?: string }} [opts]
 * @returns {string}
 */
export function keywordTags(t, opts = {}) {
	const keys =
		// Stryker disable next-line ConditionalExpression: mutating `opts.limit === undefined` to false only changes the undefined case, where the else-branch runs `.slice(0, undefined)` — a full shallow copy identical to `t.keywords || []` — so it is equivalent. (ArrayDeclaration mutants on this line stay killed.)
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
/** @param {Tool} t */
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
