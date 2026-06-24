// SPDX-License-Identifier: GPL-3.0-or-later
export const $ = (s, r) => (r || document).querySelector(s);
export const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

export function hash(str) { let h = 0; for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0; return Math.abs(h); }
export function esc(s) {
	return String(s == null ? "" : s)
		.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
export function normalizeVcsUrl(u) {
	const raw = String(u == null ? "" : u).trim();
	if (!raw) return raw;
	try {
		let s = raw;
		let changed = false;
		if (/^git\+/i.test(s)) {
			s = s.replace(/^git\+/i, "");
			changed = true;
		}
		const scp = /^git@([^:\s]+):(.+)$/.exec(s);
		if (scp) {
			s = "https://" + scp[1] + "/" + scp[2].replace(/^\/+/, "");
			changed = true;
		} else {
			const ssh = /^ssh:\/\/git@([^/\s]+)\/(.+)$/i.exec(s);
			if (ssh) {
				s = "https://" + ssh[1] + "/" + ssh[2].replace(/^\/+/, "");
				changed = true;
			}
		}
		return changed ? s.replace(/\.git(?=([?#]|$))/i, "") : raw;
	} catch (e) {
		return raw;
	}
}
export function safeUrl(u) { const s = String(u == null ? "" : u).trim(); return /^https?:\/\//i.test(s) ? esc(s) : ""; }
export function dirAttrs(value) { return value ? ' dir="auto"' : ""; }
