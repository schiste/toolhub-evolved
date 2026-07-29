// SPDX-License-Identifier: GPL-3.0-or-later
import { cleanLangCode, esc } from "./dom.js";

export const DEFAULT_LOCALE = "en";
export const LOCALE_KEY = "toolhub-locale";
export const PSEUDO_LOCALE = "en-x-pseudo";
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

/** @type {Readonly<Record<string, string>>} */
export const BOOT_MESSAGES = Object.freeze({
	"api.liveDataUpdated": "Live Toolhub data updated.",
	"api.refreshFailed": "Showing saved Toolhub data; refresh failed.",
	"api.refreshingLiveData": "Refreshing live Toolhub data...",
	"router.backToHome": "Back to home",
	"router.loadErrorTitle": "Couldn't load live data",
	"router.loadingToolhubData": "Loading Toolhub data"
});

function storedLocale() {
	try {
		return globalThis.localStorage?.getItem(LOCALE_KEY) || "";
	} catch {
		return "";
	}
}

/** @param {unknown} locale */
function cleanLocale(locale) {
	const normalized = String(locale || DEFAULT_LOCALE)
		.trim()
		.replaceAll("_", "-");
	if (!normalized) return DEFAULT_LOCALE;
	try {
		return Intl.getCanonicalLocales(normalized)[0] || DEFAULT_LOCALE;
	} catch {
		return DEFAULT_LOCALE;
	}
}

export function appLocale() {
	return cleanLocale(storedLocale() || DEFAULT_LOCALE);
}
export const LOCALE = appLocale();

/* ---- Message catalog (t) ------------------------------------------------
   Chrome strings live in code as `t("key", "English…", params)`: the English
   source doubles as the fallback, and `i18n/en.json` is generated from the
   sources (npm run i18n:extract) so translatewiki-style catalogs always match.
   Non-English catalogs are fetched at boot (main.js) and installed here. */
/** Locales available to the switcher. `en-x-pseudo` is generated at runtime for QA. */
export const AVAILABLE_LOCALES = ["en", PSEUDO_LOCALE];
/** @type {Record<string, string>} */
let messages = {};
const ELEMENT_PLACEHOLDER = /\{([A-Za-z][A-Za-z0-9]*)}/g;
const MESSAGE_PLACEHOLDER = /\{[A-Za-z][A-Za-z0-9]*}/g;
const PSEUDO_MAP = Object.freeze(
	/** @type {Record<string, string>} */ ({
		A: "Å",
		B: "Ɓ",
		C: "Ç",
		D: "Ḓ",
		E: "Ḗ",
		F: "Ƒ",
		G: "Ĝ",
		H: "Ħ",
		I: "Ī",
		J: "Ĵ",
		K: "Ķ",
		L: "Ŀ",
		M: "Ḿ",
		N: "Ƞ",
		O: "Ö",
		P: "Ƥ",
		Q: "Ǭ",
		R: "Ř",
		S: "Ş",
		T: "Ţ",
		U: "Û",
		V: "Ṽ",
		W: "Ŵ",
		X: "Ẋ",
		Y: "Ẏ",
		Z: "Ż",
		a: "å",
		b: "ƀ",
		c: "ç",
		d: "ḓ",
		e: "ḗ",
		f: "ƒ",
		g: "ĝ",
		h: "ħ",
		i: "ī",
		j: "ĵ",
		k: "ķ",
		l: "ļ",
		m: "ḿ",
		n: "ƞ",
		o: "ǿ",
		p: "ƥ",
		q: "զ",
		r: "ř",
		s: "ş",
		t: "ŧ",
		u: "û",
		v: "ṽ",
		w: "ŵ",
		x: "ẋ",
		y: "ẏ",
		z: "ž"
	})
);

/**
 * @param {unknown} locale
 * @returns {boolean}
 */
export function isPseudoLocale(locale = LOCALE) {
	return cleanLocale(locale) === PSEUDO_LOCALE;
}

/** @param {string} segment */
function pseudoSegment(segment) {
	return segment.replaceAll(/[A-Za-z]/g, (char) => PSEUDO_MAP[char] || char);
}

/**
 * Expand and accent a source message while leaving `{placeholders}` intact.
 * @param {unknown} text
 */
export function pseudoLocalize(text) {
	const source = String(text ?? "");
	if (!source) return "";
	let out = "";
	let lastIndex = 0;
	for (const match of source.matchAll(MESSAGE_PLACEHOLDER)) {
		const index = match.index ?? 0;
		out += pseudoSegment(source.slice(lastIndex, index));
		out += match[0];
		lastIndex = index + match[0].length;
	}
	out += pseudoSegment(source.slice(lastIndex));
	const transformable = source.replaceAll(MESSAGE_PLACEHOLDER, "").trim();
	const expansion = transformable ? "~".repeat(Math.max(1, Math.ceil(transformable.length * 0.3))) : "";
	return `[${out}${expansion}]`;
}

/** @param {unknown} catalog */
export function setMessages(catalog) {
	messages = catalog && typeof catalog === "object" ? /** @type {Record<string, string>} */ (catalog) : {};
}

/**
 * @param {string} key
 * @param {string | undefined} fallback
 * @param {Record<string, string | number> | undefined} params
 */
function lookupMessage(key, fallback, params) {
	const hasCatalogMessage = Object.prototype.hasOwnProperty.call(messages, key);
	const hasBootMessage = Object.prototype.hasOwnProperty.call(BOOT_MESSAGES, key);
	let out = hasCatalogMessage ? String(messages[key]) : (fallback ?? BOOT_MESSAGES[key] ?? key);
	if (isPseudoLocale() && (hasCatalogMessage || hasBootMessage || fallback !== undefined)) out = pseudoLocalize(out);
	if (params) {
		for (const [k, v] of Object.entries(params)) out = out.replaceAll(`{${k}}`, String(v));
	}
	return out;
}

/**
 * Translate a chrome string. `fallback` is the English source (also what the
 * catalog extractor collects); `params` fill `{name}` placeholders after
 * lookup, so translations control word order.
 * @param {string} key
 * @param {string} [fallback]
 * @param {Record<string, string | number>} [params]
 */
export function t(key, fallback, params) {
	return lookupMessage(key, fallback, params);
}

/**
 * Translate a message whose source entry is extracted from structured markup
 * such as `data-i18n` in the static shell.
 * @param {string} key
 * @param {string} fallback
 * @param {Record<string, string | number>} [params]
 */
export function tData(key, fallback, params) {
	return lookupMessage(key, fallback, params);
}

/**
 * Translate compact UI text with caller-owned inline markup. Translated text
 * and params are escaped; only `elements` values are inserted as trusted HTML.
 * @param {string} key
 * @param {string} fallback
 * @param {Record<string, string>} elements trusted HTML snippets keyed by `{name}`
 * @param {Record<string, string | number>} [params]
 */
export function tWithElements(key, fallback, elements, params) {
	const message = lookupMessage(key, fallback, params);
	let out = "";
	let lastIndex = 0;
	for (const match of message.matchAll(ELEMENT_PLACEHOLDER)) {
		const index = match.index ?? 0;
		out += esc(message.slice(lastIndex, index));
		out += Object.hasOwn(elements, match[1]) ? elements[match[1]] : esc(match[0]);
		lastIndex = index + match[0].length;
	}
	return out + esc(message.slice(lastIndex));
}
/**
 * Persist a locale choice; the app reloads so every `Intl` formatter and the
 * document `lang`/`dir` rebind to it (main.js owns the reload).
 * @param {string} locale
 */
export function setLocale(locale) {
	try {
		globalThis.localStorage?.setItem(LOCALE_KEY, String(locale));
	} catch {
		// Locale persistence is progressive enhancement; the shell must still boot.
	}
}
/**
 * Resolve a localized API field and preserve the selected language when the API
 * exposes one. Toolhub usually sends plain strings plus a record-level
 * `_language`; future/mocked localized maps use their map key as the field
 * language.
 * @param {unknown} value
 * @param {unknown} [fallbackLang]
 * @returns {{ value: any, lang: string | null }}
 */
export function localizedField(value, fallbackLang) {
	const fallback = cleanLangCode(fallbackLang) || null;
	if (value && typeof value === "object" && !Array.isArray(value)) {
		const map = /** @type {Record<string, unknown>} */ (value);
		const keys = [LOCALE, LOCALE.split("-")[0], DEFAULT_LOCALE, ...Object.keys(map)];
		for (const key of keys) {
			if (Object.prototype.hasOwnProperty.call(map, key)) {
				return { value: map[key], lang: cleanLangCode(key) || fallback };
			}
		}
		return { value: "", lang: null };
	}
	return { value, lang: fallback };
}
/**
 * Localized-field resolver for API data (audit §2.2 item 2): Toolhub fields
 * are usually plain strings, but when a per-language object arrives, prefer
 * the active locale, then its base language, then English, then anything.
 * @param {unknown} value
 * @returns {any}
 */
export function pickLocalized(value) {
	return localizedField(value).value;
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
