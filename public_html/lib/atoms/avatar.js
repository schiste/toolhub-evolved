// SPDX-License-Identifier: GPL-3.0-or-later
import { esc, hash } from "../core/dom.js";

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
	const m = /File:(.+)$/.exec(fileUrl || "");
	if (!m) return null;
	return "https://commons.wikimedia.org/wiki/Special:FilePath/" + encodeURIComponent(decodeURIComponent(m[1])) + "?width=" + w;
}
// Tool icon: real Commons image if the tool has one, else a letter avatar.
export function toolIcon(t, variant) {
	const px = variant === "lg" ? 72 : 48;
	const cls = "avatar" + (variant === "lg" ? " avatar--lg" : "");
	const thumb = commonsThumb(t.icon, px * 2);
	if (thumb) {
		return `<img class="${cls} avatar--img" src="${esc(thumb)}" alt="" width="${px}" height="${px}" loading="lazy" />`;
	}
	return avatar(t.title, variant === "lg" ? "avatar--lg" : "");
}
