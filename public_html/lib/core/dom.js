// SPDX-License-Identifier: GPL-3.0-or-later
export const $ = (s, r) => (r || document).querySelector(s);
export const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

export function hash(str) { let h = 0; for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0; return Math.abs(h); }
export function esc(s) {
	return String(s == null ? "" : s)
		.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
export function safeUrl(u) { const s = String(u == null ? "" : u).trim(); return /^https?:\/\//i.test(s) ? esc(s) : ""; }
export function dirAttrs(value) { return value ? ' dir="auto"' : ""; }
