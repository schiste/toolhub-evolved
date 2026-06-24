// SPDX-License-Identifier: GPL-3.0-or-later
import { esc, hash, safeUrl } from "../core/dom.js";

export const AVATAR_COLORS = [
	"#0c57a8", "#246342", "#8a4b08", "#970302", "#5748b5",
	"#305d70", "#0e65c0", "#308557", "#b03b78", "#1f6f8b",
];
export function avatar(title, cls) {
	const ch = (title || "?").trim().charAt(0).toUpperCase();
	const color = AVATAR_COLORS[hash(title || "?") % AVATAR_COLORS.length];
	return `<span class="avatar ${cls || ""}" style="background:${color}" aria-hidden="true">${esc(ch)}</span>`;
}
// Commons "File:Foo.svg" page URL → a rendered thumbnail URL.
export function commonsThumb(fileUrl, w) {
	const m = /File(?::|%3A)(.+)$/i.exec(fileUrl || "");
	if (!m) return null;
	let fileName = m[1];
	try {
		fileName = decodeURIComponent(fileName);
	} catch (e) {
		fileName = m[1];
	}
	return "https://commons.wikimedia.org/wiki/Special:FilePath/" + encodeURIComponent(fileName) + "?width=" + w;
}
function isCommonsFilePageUrl(url) {
	return /\/wiki\/File(?::|%3A)/i.test(String(url || "").split(/[?#]/, 1)[0]);
}
function isDirectImageUrl(url) {
	const s = String(url || "").trim();
	if (!/^https?:\/\//i.test(s)) return false;
	if (/Special:FilePath/i.test(s) || /upload\.wikimedia\.org/i.test(s)) return true;
	const withoutQuery = s.split(/[?#]/, 1)[0];
	if (isCommonsFilePageUrl(s)) return false;
	try {
		return /\.(png|jpe?g|gif|svg|webp)$/i.test(new URL(s).pathname);
	} catch (e) {
		return /\.(png|jpe?g|gif|svg|webp)$/i.test(withoutQuery);
	}
}
// Tool icon: real Commons image if the tool has one, else a letter avatar.
export function toolIcon(t, variant) {
	const px = variant === "lg" ? 72 : 48;
	const cls = "avatar" + (variant === "lg" ? " avatar--lg" : "");
	const direct = isDirectImageUrl(t.icon) ? t.icon : null;
	const src = safeUrl(direct || commonsThumb(t.icon, px * 2));
	if (src) {
		return `<img class="${cls} avatar--img" src="${src}" alt="" width="${px}" height="${px}" loading="lazy" />`;
	}
	return avatar(t.title, variant === "lg" ? "avatar--lg" : "");
}
