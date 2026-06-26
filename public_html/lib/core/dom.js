// SPDX-License-Identifier: GPL-3.0-or-later
/** @type {(selector: string, root?: ParentNode) => HTMLElement | null} */
export const $ = (s, r) => /** @type {HTMLElement | null} */ ((r || document).querySelector(s));
/** @type {(selector: string, root?: ParentNode) => HTMLElement[]} */
export const $$ = (s, r) => /** @type {HTMLElement[]} */ ([...(r || document).querySelectorAll(s)]);
/** Query a form control by selector (typed for .value/.checked access). */
/** @type {(selector: string, root?: ParentNode) => HTMLInputElement | null} */
export const $input = (s, r) => /** @type {HTMLInputElement | null} */ ((r || document).querySelector(s));

/** @param {string} str */
export function hash(str) {
	let h = 0;
	for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
	return Math.abs(h);
}
/** @param {unknown} s */
export function esc(s) {
	return String(s === null || s === undefined ? "" : s)
		.replaceAll("&", "&amp;")
		.replaceAll("<", "&lt;")
		.replaceAll(">", "&gt;")
		.replaceAll('"', "&quot;")
		.replaceAll("'", "&#39;");
}
/** @param {unknown} u */
export function normalizeVcsUrl(u) {
	const raw = String(u === null || u === undefined ? "" : u).trim();
	if (!raw) return raw;
	try {
		let s = raw;
		let changed = false;
		if (/^git\+/i.test(s)) {
			s = s.replace(/^git\+/i, "");
			changed = true;
		}
		const scp = /^git@([^\s:]+):(.+)$/.exec(s);
		if (scp) {
			s = `https://${scp[1]}/${scp[2].replace(/^\/+/, "")}`;
			changed = true;
		} else {
			const ssh = /^ssh:\/\/git@([^\s/]+)\/(.+)$/i.exec(s);
			if (ssh) {
				s = `https://${ssh[1]}/${ssh[2].replace(/^\/+/, "")}`;
				changed = true;
			}
		}
		return changed ? s.replace(/\.git(?=([#?]|$))/i, "") : raw;
	} catch {
		return raw;
	}
}
/** @param {unknown} u */
export function safeUrl(u) {
	const s = String(u === null || u === undefined ? "" : u).trim();
	return /^https?:\/\//i.test(s) ? esc(s) : "";
}
/** @param {unknown} value */
export function dirAttrs(value) {
	return value ? ' dir="auto"' : "";
}
