// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "./dom.js";

export const DEFAULT_LOCALE = "en";
export const RTL_LANGS = new Set([
	"ar",
	"arc",
	"ckb",
	"dv",
	"fa",
	"ha",
	"he",
	"khw",
	"ks",
	"ku",
	"ps",
	"sd",
	"ug",
	"ur",
	"yi"
]);
export const LOCALE_KEY = "toolhub-locale";
export function appLocale() {
	const stored = localStorage.getItem(LOCALE_KEY);
	return (stored || DEFAULT_LOCALE).replaceAll("_", "-");
}
export const LOCALE = appLocale();

/* ---- Message catalog (t) ------------------------------------------------
   Chrome strings live in code as `t("key", "English…", params)`: the English
   source doubles as the fallback, and `i18n/en.json` is generated from the
   sources (npm run i18n:extract) so translatewiki-style catalogs always match.
   Non-English catalogs are fetched at boot (main.js) and installed here. */
/** Locales a catalog ships for (the switcher offers the rest as "not yet"). */
export const AVAILABLE_LOCALES = ["en"];
/** @type {Record<string, string>} */
let messages = {};
/** @param {unknown} catalog */
export function setMessages(catalog) {
	messages = catalog && typeof catalog === "object" ? /** @type {Record<string, string>} */ (catalog) : {};
}
/**
 * Translate a chrome string. `fallback` is the English source (also what the
 * catalog extractor collects); `params` fill `{name}` placeholders after
 * lookup, so translations control word order.
 * @param {string} key
 * @param {string} fallback
 * @param {Record<string, string | number>} [params]
 */
export function t(key, fallback, params) {
	let out = Object.prototype.hasOwnProperty.call(messages, key) ? String(messages[key]) : fallback;
	if (params) {
		for (const [k, v] of Object.entries(params)) out = out.replaceAll(`{${k}}`, String(v));
	}
	return out;
}
/**
 * Persist a locale choice; the app reloads so every `Intl` formatter and the
 * document `lang`/`dir` rebind to it (main.js owns the reload).
 * @param {string} locale
 */
export function setLocale(locale) {
	localStorage.setItem(LOCALE_KEY, String(locale));
}
/**
 * Localized-field resolver for API data (audit §2.2 item 2): Toolhub fields
 * are usually plain strings, but when a per-language object arrives, prefer
 * the active locale, then its base language, then English, then anything.
 * @param {unknown} value
 * @returns {any}
 */
export function pickLocalized(value) {
	if (value && typeof value === "object" && !Array.isArray(value)) {
		const map = /** @type {Record<string, unknown>} */ (value);
		return map[LOCALE] ?? map[LOCALE.split("-")[0]] ?? map[DEFAULT_LOCALE] ?? Object.values(map)[0] ?? "";
	}
	return value;
}
const numberFmt = new Intl.NumberFormat(LOCALE);
const compactNumberFmt = new Intl.NumberFormat(LOCALE, { notation: "compact", maximumFractionDigits: 1 });
const relativeTimeFmt = new Intl.RelativeTimeFormat(LOCALE, { numeric: "auto" });
const dateTimeFmt = new Intl.DateTimeFormat(LOCALE, { dateStyle: "medium", timeStyle: "short" });
const pluralRules = new Intl.PluralRules(LOCALE);
/** @param {string} locale */
export function localeDir(locale) {
	return RTL_LANGS.has(String(locale).split("-")[0].toLowerCase()) ? "rtl" : "ltr";
}
export function applyLocaleAttrs() {
	document.documentElement.lang = LOCALE;
	document.documentElement.dir = localeDir(LOCALE);
}
/** @param {unknown} n */
export function fmt(n) {
	return numberFmt.format(Number(n) || 0);
}
/** @param {unknown} n */
export function compactFmt(n) {
	return compactNumberFmt.format(Number(n) || 0);
}
/**
 * @param {unknown} n
 * @param {Record<string, string>} forms
 */
export function plural(n, forms) {
	const cat = pluralRules.select(Math.abs(Number(n) || 0));
	return forms[cat] || forms.other || forms.one || "";
}
/**
 * @param {unknown} n
 * @param {string} one
 * @param {string} other
 */
export function countLabel(n, one, other) {
	const value = Number(n) || 0;
	return `${fmt(value)} ${plural(value, { one, other })}`;
}
/** @param {string | null | undefined} iso */
export function relativeTime(iso) {
	if (!iso) return "";
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return "";
	const delta = date.getTime() - Date.now();
	const abs = Math.abs(delta);
	if (abs < 86400000) return relativeTimeFmt.format(0, "day");
	if (abs < 30 * 86400000) return relativeTimeFmt.format(Math.round(delta / 86400000), "day");
	if (abs < 365 * 86400000) return relativeTimeFmt.format(Math.round(delta / (30 * 86400000)), "month");
	return relativeTimeFmt.format(Math.round(delta / (365 * 86400000)), "year");
}
/** @param {string | null | undefined} iso */
export function relTime(iso) {
	const rel = relativeTime(iso);
	return rel ? t("time.updated", "Updated {rel}", { rel }) : "";
}
/**
 * @param {string | null | undefined} iso
 * @param {string | null | undefined} [cls]
 * @param {string | null | undefined} [text]
 */
export function timeTag(iso, cls, text) {
	if (!iso) return "";
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return "";
	const label = text || relativeTime(iso);
	const classAttr = cls ? ` class="${esc(cls)}"` : "";
	return `<time${classAttr} datetime="${esc(date.toISOString())}" title="${esc(dateTimeFmt.format(date))}">${esc(label)}</time>`;
}
/**
 * @param {string | null | undefined} iso
 * @param {string} [cls]
 */
export function updatedTimeTag(iso, cls) {
	return timeTag(iso, cls, relTime(iso));
}
/** @param {unknown} n */
export function views(n) {
	return `${compactFmt(n)} ${plural(n, { one: t("count.viewOne", "view"), other: t("count.viewOther", "views") })}`;
}
