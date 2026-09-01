// SPDX-License-Identifier: GPL-3.0-or-later
// Small generic helpers shared across core modules.

// Lazily build + cache an async result. The builder runs at most once; its
// promise (resolved OR rejected) is cached — matching the hand-rolled
// `let p = null; if (!p) p = build(); return p;` pattern it replaces.
/**
 * @template T
 * @param {() => T | Promise<T>} builder
 * @returns {() => Promise<T>}
 */
export function memoizeAsync(builder) {
	/** @type {Promise<T> | null} */
	let promise = null;
	return () => promise || (promise = Promise.resolve().then(builder));
}

// Normalize a tag/term value to a comparable token: string, trimmed, lowercased.
/**
 * @param {unknown} value
 * @returns {string}
 */
export function normStr(value) {
	return String(value ?? "")
		.trim()
		.toLowerCase();
}

/**
 * Whether a value is present: a non-empty array, or anything but null,
 * undefined and the empty string.
 *
 * Lived in api.js, which is about talking to Toolhub and has nothing to do
 * with this.
 * @param {any} v
 * @returns {boolean}
 */
/** @param {unknown} v */
export function hasValue(v) {
	return Array.isArray(v) ? v.length > 0 : v !== null && v !== undefined && v !== "";
}

/* Generic list<->text conversion for comma-separated form fields. These were
   in store.js, which is the localStorage layer and never had anything to do
   with them. */
/** @param {any[]} a @returns {string} */
export function toCsv(a) {
	return (a || []).join(", ");
}
/** @param {string} s @returns {string[]} */
export function fromCsv(s) {
	return String(s || "")
		.split(",")
		.map((x) => x.trim())
		.filter(Boolean);
}

/* The statistics and data-layer reports both print catalogue counts and the
   moment their snapshot was taken, and each had grown its own byte-identical
   copy of these two. The only thing that differed was the message key for an
   unreadable date, so the fallback arrives as an argument: util.js is generic
   and stays out of the i18n catalogue. */
/** @param {unknown} value @returns {string} */
export function formatCount(value) {
	return new Intl.NumberFormat().format(Number(value) || 0);
}

/** @param {unknown} value @param {string} unavailable @returns {string} */
export function formatDateTime(value, unavailable) {
	const date = new Date(String(value || ""));
	return Number.isNaN(date.getTime())
		? unavailable
		: new Intl.DateTimeFormat(undefined, { dateStyle: "long", timeStyle: "short" }).format(date);
}
