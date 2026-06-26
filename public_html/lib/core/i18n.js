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
export function appLocale() {
	const stored = localStorage.getItem("toolhub-locale");
	return (stored || DEFAULT_LOCALE).replaceAll("_", "-");
}
export const LOCALE = appLocale();
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
	return rel ? `Updated ${rel}` : "";
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
	return `${compactFmt(n)} ${plural(n, { one: "view", other: "views" })}`;
}
