// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";
import { icon } from "./icon.js";

function classList(parts) {
	return parts.filter(Boolean).join(" ");
}

function disabledAttrs(tag, disabled) {
	if (!disabled) return "";
	return tag === "a" ? ' aria-disabled="true" tabindex="-1"' : " disabled";
}

function commonAttrs(tag, opts) {
	return `${tag === "a" ? ` href="${opts.href}"` : ` type="${esc(opts.type || "button")}"`}${disabledAttrs(tag, opts.disabled)}${opts.attrs ? " " + opts.attrs : ""}`;
}

export function button(label, opts = {}) {
	const tag = opts.href ? "a" : "button";
	const variant = opts.variant || "outline";
	const size = opts.size || "md";
	const cls = classList(["btn", `btn--${variant}`, `btn--${size}`, opts.cls]);
	const body = `${opts.icon ? icon(opts.icon) + " " : ""}${esc(label)}`;
	return `<${tag} class="${cls}"${commonAttrs(tag, opts)}>${body}</${tag}>`;
}

export function iconButton(iconName, ariaLabel, opts = {}) {
	if (!ariaLabel) throw new Error("iconButton requires an ariaLabel");
	const tag = opts.href ? "a" : "button";
	const size = opts.size || "md";
	const variant = opts.variant && opts.variant !== "ghost" ? `btn--${opts.variant}` : "";
	const cls = classList(["btn", "btn--icon", variant, `btn--${size}`, opts.cls]);
	return `<${tag} class="${cls}" aria-label="${esc(ariaLabel)}"${commonAttrs(tag, opts)}>${icon(iconName)}</${tag}>`;
}
