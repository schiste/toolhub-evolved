// SPDX-License-Identifier: GPL-3.0-or-later
import { esc, hash, safeUrl } from "../core/dom.js";

export const AVATAR_COLORS = [
	"var(--wmf-blue-aaa)",
	"var(--wmf-green-aaa)",
	"var(--color-warning-text)",
	"var(--wmf-red-aaa)",
	"var(--wmf-purple)",
	"var(--color-text-muted)",
	"var(--color-progressive)",
	"var(--color-success)",
	"var(--color-favorite)",
	"var(--color-progressive-hover)"
];
/**
 * @param {string | null | undefined} title
 * @param {string} [cls]
 * @returns {string}
 */
export function avatar(title, cls) {
	const ch = (title || "?").trim().charAt(0).toUpperCase();
	const color = AVATAR_COLORS[hash(title || "?") % AVATAR_COLORS.length];
	return `<span class="avatar ${cls || ""}" style="background:${color}" aria-hidden="true">${esc(ch)}</span>`;
}
// Commons "File:Foo.svg" page URL → a rendered thumbnail URL.
/**
 * @param {string | null | undefined} fileUrl
 * @param {number} w
 * @returns {string | null}
 */
export function commonsThumb(fileUrl, w) {
	// Stryker disable next-line StringLiteral: the `|| ""` fallback only fires for a falsy fileUrl; the sentinel string contains no "file:"/"file%3a", so exec() returns null exactly like exec("") does — equivalent.
	const m = /file(?::|%3a)(.+)$/i.exec(fileUrl || "");
	if (!m) return null;
	let fileName = m[1];
	// Stryker disable BlockStatement: the catch body `fileName = m[1]` is a provable no-op — on a decode failure the assignment in the try never lands, so fileName is still m[1] — making the empty-catch mutant equivalent. (The region also spans the try; the decode behaviour stays verified by the commonsThumb decode/percent-encoding assertions.)
	try {
		fileName = decodeURIComponent(fileName);
	} catch {
		fileName = m[1];
	}
	// Stryker restore BlockStatement
	return `https://commons.wikimedia.org/wiki/Special:FilePath/${encodeURIComponent(fileName)}?width=${w}`;
}
/** @param {string | null | undefined} url */
function isCommonsFilePageUrl(url) {
	// Stryker disable next-line StringLiteral: the only caller passes the already http-validated `s`, so url is never falsy here and the `|| ""` fallback is unreachable — equivalent.
	return /\/wiki\/file(?::|%3a)/i.test(String(url || "").split(/[#?]/, 1)[0]);
}
/** @param {string | null | undefined} url */
function isDirectImageUrl(url) {
	// Stryker disable next-line StringLiteral: the `|| ""` fallback only fires for a falsy url; the sentinel is not an http(s) URL, so it fails the ^https? guard below exactly like "" does (and commonsThumb still keys off the original t.icon) — equivalent.
	const s = String(url || "").trim();
	if (!/^https?:\/\//i.test(s)) return false;
	if (/special:filepath/i.test(s) || /upload\.wikimedia\.org/i.test(s)) return true;
	const withoutQuery = s.split(/[#?]/, 1)[0];
	if (isCommonsFilePageUrl(s)) return false;
	try {
		return /\.(png|jpe?g|gif|svg|webp)$/i.test(new URL(s).pathname);
	} catch {
		return /\.(png|jpe?g|gif|svg|webp)$/i.test(withoutQuery);
	}
}
// Tool icon: real Commons image if the tool has one, else a letter avatar.
/**
 * @param {Tool} t
 * @param {string} [variant]
 * @returns {string}
 */
export function toolIcon(t, variant) {
	const px = variant === "lg" ? 72 : 48;
	const cls = `avatar${variant === "lg" ? " avatar--lg" : ""}`;
	const direct = isDirectImageUrl(t.icon) ? t.icon : null;
	const src = safeUrl(direct || commonsThumb(t.icon, px * 2));
	if (src) {
		return `<img class="${cls} avatar--img" src="${src}" alt="" width="${px}" height="${px}" loading="lazy" />`;
	}
	return avatar(t.title, variant === "lg" ? "avatar--lg" : "");
}
