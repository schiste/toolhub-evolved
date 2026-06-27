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
