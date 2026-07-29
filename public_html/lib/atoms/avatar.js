// SPDX-License-Identifier: GPL-3.0-or-later
import { esc, hash, isHttpUrl, safeHttpUrl } from "../core/dom.js";

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
const ICON_META_CACHE = new Map();
/**
 * @param {string | null | undefined} title
 * @param {string} [cls]
 * @returns {string}
 */
export function avatar(title, cls) {
	return avatarMarkup(title, cls);
}

/**
 * @param {string | null | undefined} title
 * @param {string | undefined} cls
 * @param {string} [attrs]
 * @returns {string}
 */
function avatarMarkup(title, cls, attrs = "") {
	const ch = (title || "?").trim().charAt(0).toUpperCase();
	const color = AVATAR_COLORS[hash(title || "?") % AVATAR_COLORS.length];
	return `<span class="avatar ${cls || ""}" style="background:${color}"${attrs} aria-hidden="true">${esc(ch)}</span>`;
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
	if (!isHttpUrl(s)) return false;
	if (/special:filepath/i.test(s) || /upload\.wikimedia\.org/i.test(s)) return true;
	if (isCommonsFilePageUrl(s)) return false;
	return /\.(png|jpe?g|gif|svg|webp)$/i.test(new URL(s).pathname);
}
/** @param {Tool} t @param {string | undefined} variant */
function iconCacheKey(t, variant) {
	return `${variant === "lg" ? "lg" : ""}\u0000${String(t.name || "")}\u0000${String(t.title || "")}\u0000${String(t.icon ?? "").trim()}`;
}
/**
 * @param {Tool} t
 * @param {string} [variant]
 * @returns {{ state: "direct" | "commons" | "generated" | "invalid", src: string, raw: string, title: string, px: number, variant: string }}
 */
export function iconMeta(t, variant) {
	const key = iconCacheKey(t, variant);
	const cached = ICON_META_CACHE.get(key);
	if (cached) return cached;
	const px = variant === "lg" ? 72 : 48;
	const raw = String(t.icon ?? "").trim();
	const title = String(t.title || t.name || "");
	let state = /** @type {"direct" | "commons" | "generated" | "invalid"} */ (raw ? "invalid" : "generated");
	let src = "";
	if (raw) {
		const direct = isDirectImageUrl(raw) ? raw : "";
		const commons = direct ? "" : commonsThumb(raw, px * 2) || "";
		src = safeHttpUrl(direct || commons);
		if (src) state = direct ? "direct" : "commons";
	}
	const meta = Object.freeze({ state, src, raw, title, px, variant: variant === "lg" ? "lg" : "" });
	ICON_META_CACHE.set(key, meta);
	return meta;
}
/** @param {{ state: string, raw: string, title: string }} meta */
function iconDataAttrs(meta) {
	return ` data-icon-state="${esc(meta.state)}" data-icon-source="${esc(meta.raw)}" data-icon-fallback="${esc(meta.title)}"`;
}
// Tool icon: real Commons image if the tool has one, else a letter avatar.
/**
 * @param {Tool} t
 * @param {string} [variant]
 * @returns {string}
 */
export function toolIcon(t, variant) {
	const meta = iconMeta(t, variant);
	const cls = `avatar${variant === "lg" ? " avatar--lg" : ""}`;
	if (meta.src) {
		return `<img class="${cls} avatar--img" src="${meta.src}" alt="" width="${meta.px}" height="${meta.px}" loading="lazy"${iconDataAttrs(meta)} />`;
	}
	return avatar(meta.title, variant === "lg" ? "avatar--lg" : "");
}

/**
 * @param {string | null | undefined} title
 * @param {string} [variant]
 * @param {string} [source]
 */
export function iconFallbackAvatar(title, variant, source = "") {
	return avatarMarkup(
		title,
		variant === "lg" ? "avatar--lg" : "",
		` data-icon-state="unavailable"${source ? ` data-icon-source="${esc(source)}"` : ""}`
	);
}
