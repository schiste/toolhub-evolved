// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, normalizeVcsUrl, safeHttpUrl } from "../core/dom.js";
import { countLabel, t } from "../core/i18n.js";
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
export function invalidUrlNotice(label, url) {
	const raw = String(url ?? "").trim();
	if (!raw) return "";
	const aria = t("labels.invalidUrlAria", "{label}: invalid URL", { label });
	const state = t("labels.invalidUrl", "Invalid URL");
	return `<span class="linkout-bad" role="note" aria-label="${esc(aria)}" data-url-state="invalid"><span class="linkout-bad__label">${esc(label)}</span><span class="linkout-bad__state">${esc(state)}</span><span class="linkout-bad__url"${dirAttrs(raw)}>${esc(raw)}</span></span>`;
}
/**
 * @param {string} label
 * @param {string | null | undefined} url
 */
export function linkOut(label, url) {
	const raw = String(url ?? "").trim();
	if (!raw) return "";
	const u = safeHttpUrl(normalizeVcsUrl(raw));
	if (u) {
		return button(label, {
			// Stryker disable next-line StringLiteral: button()'s variantClass("") falls back to the same "btn--outline" as variantClass("outline"), so "outline" → "" is not observable — equivalent.
			variant: "outline",
			href: u,
			icon: "external",
			attrs: 'target="_blank" rel="noopener nofollow"'
		});
	}
	return invalidUrlNotice(label, raw);
}
/** @param {string[] | null | undefined} a @returns {string} */
export const wikiLabel = (a) =>
	!a || a.length === 0
		? t("labels.anyWiki", "Any wiki")
		: a.includes("*")
			? t("labels.allWikis", "All wikis")
			: a.map((item) => esc(item)).join(", ");
/** @param {string[] | null | undefined} a @returns {string} */
export const langLabel = (a) =>
	!a || a.length === 0 ? t("labels.englishDefault", "English (default)") : a.map((item) => esc(item)).join(", ");
// Compact "works on" label for cards (full list shown on the detail page).
/** @param {string[] | null | undefined} a @returns {string} */
export const wikiShort = (a) =>
	!a || a.length === 0
		? t("labels.anyWiki", "Any wiki")
		: a.includes("*")
			? t("labels.allWikis", "All wikis")
			: a.length === 1
				? a[0]
				: // Stryker disable next-line StringLiteral: this branch runs only when a.length >= 2, so countLabel() always selects the plural form; the singular "wiki" is unreachable (co-disables the asserted "wikis" literal on this line) — equivalent.
					countLabel(a.length, t("labels.wikiOne", "wiki"), t("labels.wikiOther", "wikis"));
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
/** @param {Tool} tool */
export function glanceChips(tool) {
	return [
		tool.toolType && `<span class="glance"${dirAttrs(tool.toolType)}>${esc(tool.toolType)}</span>`,
		tool.license && `<span class="glance"${dirAttrs(tool.license)}>${esc(tool.license)}</span>`,
		`<span class="glance"${dirAttrs(wikiLabel(tool.forWikis))}>${esc(wikiLabel(tool.forWikis))}</span>`,
		tool.uiLanguages &&
			tool.uiLanguages.length > 0 &&
			`<span class="glance">${esc(countLabel(tool.uiLanguages.length, t("labels.languageOne", "language"), t("labels.languageOther", "languages")))}</span>`
	]
		.filter(Boolean)
		.join("");
}
