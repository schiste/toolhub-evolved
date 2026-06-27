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
	// Stryker disable next-line ArithmeticOperator: '+' → '-' yields the exact negation of the accumulator at every step (g_n = -h_n by induction from h_0 = 0), and Math.abs makes the returned hash identical.
	for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
	return Math.abs(h);
}
/** @param {unknown} s */
export function esc(s) {
	return String(s ?? "")
		.replaceAll("&", "&amp;")
		.replaceAll("<", "&lt;")
		.replaceAll(">", "&gt;")
		.replaceAll('"', "&quot;")
		.replaceAll("'", "&#39;");
}
/** @param {unknown} u */
export function normalizeVcsUrl(u) {
	const raw = String(u ?? "").trim();
	// Stryker disable next-line ConditionalExpression: the only falsy `raw` is "", which also falls through the (no-match) transforms to `return … : raw`, yielding the same "".
	if (!raw) return raw;
	// No try/catch: the body only runs regex tests and string replaces on an
	// already-stringified value (raw), none of which can throw.
	let s = raw;
	let changed = false;
	if (/^git\+/i.test(s)) {
		// Stryker disable next-line Regex: gated by the line above (s starts with "git+"), so dropping the ^ anchor still replaces the same single leading occurrence (replace() without /g replaces only the first match).
		s = s.replace(/^git\+/i, "");
		changed = true;
	}
	// Stryker disable next-line Regex: the trailing '$' is redundant after a greedy final group (.+), so '(.+)$' → '(.+)' is equivalent; the co-located ^-removal variant is otherwise exercised by the scp tests.
	const scp = /^git@([^\s:]+):(.+)$/.exec(s);
	if (scp) {
		s = `https://${scp[1]}/${scp[2].replace(/^\/+/, "")}`;
		changed = true;
	} else {
		// Stryker disable next-line Regex: the trailing '$' is redundant after a greedy final group (.+), so '(.+)$' → '(.+)' is equivalent; the co-located ^-removal variant is otherwise exercised by the ssh tests.
		const ssh = /^ssh:\/\/git@([^\s/]+)\/(.+)$/i.exec(s);
		if (ssh) {
			s = `https://${ssh[1]}/${ssh[2].replace(/^\/+/, "")}`;
			changed = true;
		}
	}
	return changed ? s.replace(/\.git(?=([#?]|$))/i, "") : raw;
}
/** @param {unknown} u */
export function safeUrl(u) {
	// Stryker disable next-line LogicalOperator,StringLiteral: any falsy-non-null u and String(null)/String(undefined) ("null"/"undefined") all fail the http(s) test() below exactly as "" does, so `u ?? ""` → `u || ""` and mutating the "" default are both unobservable here — equivalent.
	const s = String(u ?? "").trim();
	return /^https?:\/\//i.test(s) ? esc(s) : "";
}
/** @param {unknown} value */
export function dirAttrs(value) {
	return value ? ' dir="auto"' : "";
}
