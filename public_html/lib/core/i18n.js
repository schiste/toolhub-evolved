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
	"api.liveDataUpdated": "Local catalog data updated.",
	"api.refreshFailed": "Showing the last published catalog generation.",
	"api.refreshingLiveData": "Checking the local catalog...",
	"router.backToHome": "Back to home",
	"router.loadErrorTitle": "Couldn't load the local catalog",
	"router.loadErrorBody": "The local catalog replica could not be read ($1).",
	"router.loadingPage": "Loading page"
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
   Chrome strings live in code as `t("key", "English…", ...params)`: the English
   source doubles as the fallback, and `i18n/en.json` is generated from the
   sources (npm run i18n:extract) so the shipped catalog can never drift.

   Messages use the banana format translatewiki speaks, the same as upstream
   Toolhub: positional `$1` parameters plus the `{{PLURAL:…}}` and `{{bidi:…}}`
   magic words. That is why a message group needs no bespoke configuration, and
   why banana-checker can validate parameter parity across every translation.
   Non-English catalogs are fetched at boot (main.js) and installed here. */
// The list of selectable locales lives in ./available-locales.js: this module is
// in almost every module graph, so a dependency here shifts import timing app-wide.
/** @type {Record<string, string>} */
let messages = {};
/** @type {Set<string> | null} */
let knownMessageKeys = null;
const BANANA_PARAM = /\$(\d+)/g;
/** `{{NAME:arg|arg…}}`; scanned rather than matched so nested braces survive. */
const MAGIC_OPEN = "{{";
const MAGIC_CLOSE = "}}";
/** Unicode FSI/PDI: isolate interpolated text so its direction cannot leak. */
const FIRST_STRONG_ISOLATE = "⁨";
const POP_DIRECTIONAL_ISOLATE = "⁩";
const pluralRules = new Intl.PluralRules(LOCALE);
/**
 * This locale's plural categories in CLDR order (`zero one two few many other`,
 * filtered to the ones it uses) — the positional order banana PLURAL forms are
 * written in. English has two, Russian four, Arabic six. The order is imposed
 * here because engines disagree about `resolvedOptions().pluralCategories`:
 * newer V8 returns CLDR order, older V8 (Node ≤22, older browsers) returns it
 * alphabetically, which would point every positional form at the wrong category.
 */
const PLURAL_CATEGORIES = /** @type {Intl.LDMLPluralRule[]} */ (["zero", "one", "two", "few", "many", "other"]).filter(
	(category) => pluralRules.resolvedOptions().pluralCategories.includes(category)
);
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
 * Expand and accent a source message while leaving `$1` parameters intact.
 * Runs after magic words are expanded, so only plain text and `$n` remain.
 * @param {unknown} text
 */
export function pseudoLocalize(text) {
	const source = String(text ?? "");
	if (!source) return "";
	let out = "";
	let lastIndex = 0;
	for (const match of source.matchAll(BANANA_PARAM)) {
		const index = match.index ?? 0;
		out += pseudoSegment(source.slice(lastIndex, index));
		out += match[0];
		lastIndex = index + match[0].length;
	}
	out += pseudoSegment(source.slice(lastIndex));
	const transformable = source.replaceAll(BANANA_PARAM, "").trim();
	const expansion = transformable ? "~".repeat(Math.max(1, Math.ceil(transformable.length * 0.3))) : "";
	return `[${out}${expansion}]`;
}

/**
 * Restrict `t()` to a set of keys, rendering anything else as a visible marker;
 * pass null to accept every key, which is how the app itself always runs.
 *
 * With no catalog installed `t(key, fallback)` returns the fallback, so under
 * the unit suite the key selects nothing and any key at all renders the same
 * English. That is invisible in a passing run and fatal under mutation testing:
 * rewriting `t("facetGroup.keywords", "Keywords")` as `t("", "Keywords")`
 * produces an identical page, so no test can tell the two apart. Roughly 4,000
 * call sites became unfalsifiable that way when the English moved behind `t()`.
 * tests/unit/_i18n-keys.mjs installs the generated catalog's key set for the
 * whole suite, which puts the key back into the rendered output and lets the
 * assertions already written against that English carry it again.
 * @param {Iterable<string> | null} keys
 */
export function setKnownMessageKeys(keys) {
	knownMessageKeys = keys ? new Set(keys) : null;
}

/**
 * Install a fetched catalog. translatewiki writes an `@metadata` block into
 * every catalog it produces, and only string values are messages, so both are
 * dropped here rather than leaking into `t()` lookups.
 * @param {unknown} catalog
 */
export function setMessages(catalog) {
	messages = {};
	if (!catalog || typeof catalog !== "object") return;
	for (const [key, value] of Object.entries(catalog)) {
		if (!key.startsWith("@") && typeof value === "string") messages[key] = value;
	}
}

/** @param {unknown} value @returns {value is { html: string }} */
function isHtmlParam(value) {
	return Boolean(value) && typeof value === "object" && typeof (/** @type {any} */ (value).html) === "string";
}

/** @param {unknown} value */
function paramText(value) {
	return isHtmlParam(value) ? "" : String(value);
}

/**
 * Substitute `$1…$n`. An index with no parameter is left as written, so a
 * message that outlives its call site degrades visibly instead of silently.
 * @param {string} text
 * @param {readonly unknown[]} params
 */
function resolveParams(text, params) {
	return text.replaceAll(BANANA_PARAM, (raw, index) => {
		const value = params[Number(index) - 1];
		return value === undefined ? raw : paramText(value);
	});
}

/**
 * Locate the balanced `{{…}}` span at or after `from`, so a magic word nested
 * inside another one does not terminate the outer match early.
 * @param {string} text
 * @param {number} from
 * @returns {{ open: number, close: number } | null} `close` is the index past `}}`
 */
function findMagicWord(text, from) {
	const open = text.indexOf(MAGIC_OPEN, from);
	if (open < 0) return null;
	let depth = 0;
	for (let i = open; i < text.length - 1; i++) {
		if (text.startsWith(MAGIC_OPEN, i)) {
			depth++;
			i++;
		} else if (text.startsWith(MAGIC_CLOSE, i)) {
			depth--;
			i++;
			if (depth === 0) return { open, close: i + 1 };
		}
	}
	return null;
}

/**
 * Split magic-word arguments on top-level `|` only, so a form containing a
 * nested magic word survives intact.
 * @param {string} body
 * @returns {string[]}
 */
function splitMagicArgs(body) {
	const parts = [];
	let depth = 0;
	let start = 0;
	for (let i = 0; i < body.length; i++) {
		if (body.startsWith(MAGIC_OPEN, i)) {
			depth++;
			i++;
		} else if (body.startsWith(MAGIC_CLOSE, i)) {
			depth = Math.max(0, depth - 1);
			i++;
		} else if (body[i] === "|" && depth === 0) {
			parts.push(body.slice(start, i));
			start = i + 1;
		}
	}
	parts.push(body.slice(start));
	return parts;
}

/**
 * Pick a banana PLURAL form. An explicit `N=form` wins for that exact count;
 * otherwise forms are positional in this locale's CLDR category order
 * (`PLURAL_CATEGORIES`, normalized above — engine order is not trusted). A
 * message carrying fewer forms than the locale needs (an English source read in
 * Arabic, say) falls back to its last form rather than dropping the text.
 * @param {number} count
 * @param {string[]} forms
 */
function selectPluralForm(count, forms) {
	const positional = [];
	for (const form of forms) {
		const explicit = /^(\d+)\s*=([\s\S]*)$/.exec(form);
		if (!explicit) {
			positional.push(form);
			continue;
		}
		if (Number(explicit[1]) === count) return explicit[2];
	}
	const index = PLURAL_CATEGORIES.indexOf(pluralRules.select(Math.abs(count)));
	return positional[index] ?? positional.at(-1) ?? "";
}

/**
 * Expand `{{PLURAL:…}}` and `{{bidi:…}}`. Parameters are resolved for the
 * control argument only — `$n` inside the selected text stays a placeholder and
 * is filled afterwards, so a parameter value containing `|` or `{{` can never
 * be re-read as syntax.
 * @param {string} text
 * @param {readonly unknown[]} params
 */
function expandMagicWords(text, params) {
	let out = text;
	let cursor = 0;
	// Bounded: a hostile or malformed catalog must not spin the render loop.
	for (let pass = 0; pass < 100; pass++) {
		const span = findMagicWord(out, cursor);
		if (!span) break;
		const body = out.slice(span.open + MAGIC_OPEN.length, span.close - MAGIC_CLOSE.length);
		const colon = body.indexOf(":");
		const name = colon < 0 ? "" : body.slice(0, colon).trim().toLowerCase();
		const args = colon < 0 ? [] : splitMagicArgs(body.slice(colon + 1));
		let replacement = null;
		if (name === "plural" && args.length > 1) {
			const count = Number(resolveParams(args[0], params));
			replacement = selectPluralForm(Number.isFinite(count) ? count : 0, args.slice(1));
		} else if (name === "bidi" && args.length > 0) {
			replacement = `${FIRST_STRONG_ISOLATE}${args.join("|")}${POP_DIRECTIONAL_ISOLATE}`;
		}
		if (replacement === null) {
			// Unknown magic word: leave it verbatim and keep scanning past it.
			cursor = span.open + MAGIC_OPEN.length;
			continue;
		}
		out = out.slice(0, span.open) + replacement + out.slice(span.close);
		cursor = span.open;
	}
	return out;
}

/**
 * Resolve a key to its message with magic words expanded and `$n` still in
 * place, so callers decide how each parameter is escaped.
 * @param {string} key
 * @param {string | undefined} fallback
 * @param {readonly unknown[]} params
 */
function resolveMessage(key, fallback, params) {
	if (knownMessageKeys && !knownMessageKeys.has(String(key))) return `[unknown i18n key ${String(key)}]`;
	const hasCatalogMessage = Object.prototype.hasOwnProperty.call(messages, key);
	const hasBootMessage = Object.prototype.hasOwnProperty.call(BOOT_MESSAGES, key);
	let out = hasCatalogMessage ? String(messages[key]) : (fallback ?? BOOT_MESSAGES[key] ?? key);
	out = expandMagicWords(out, params);
	if (isPseudoLocale() && (hasCatalogMessage || hasBootMessage || fallback !== undefined)) out = pseudoLocalize(out);
	return out;
}

/**
 * Translate a chrome string. `fallback` is the English source (also what the
 * catalog extractor collects); `params` fill `$1…$n` after lookup, so
 * translations control word order and plural form.
 * @param {string} key
 * @param {string} [fallback]
 * @param {...(string | number)} params
 */
export function t(key, fallback, ...params) {
	return resolveParams(resolveMessage(key, fallback, params), params);
}

/**
 * Translate a message whose source entry is extracted from structured markup
 * such as `data-i18n` in the static shell.
 * @param {string} key
 * @param {string} fallback
 * @param {...(string | number)} params
 */
export function tData(key, fallback, ...params) {
	// Resolves directly rather than delegating to t(): a t() call with a
	// non-literal key is exactly what the catalog extractor refuses to see.
	return resolveParams(resolveMessage(key, fallback, params), params);
}

/**
 * Translate compact UI text with caller-owned inline markup. The translated
 * text and every plain parameter are escaped; only a parameter wrapped as
 * `{ html }` is inserted as trusted markup, so neither a translator nor live
 * API data can introduce HTML.
 * @param {string} key
 * @param {string} fallback
 * @param {...(string | number | { html: string })} params positional `$1…$n`
 */
export function tWithElements(key, fallback, ...params) {
	const message = resolveMessage(key, fallback, params);
	let out = "";
	let lastIndex = 0;
	for (const match of message.matchAll(BANANA_PARAM)) {
		const index = match.index ?? 0;
		const value = params[Number(match[1]) - 1];
		out += esc(message.slice(lastIndex, index));
		if (value === undefined) out += esc(match[0]);
		else out += isHtmlParam(value) ? value.html : esc(String(value));
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
	return rel ? t("time.updated", "Updated $1", rel) : "";
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
