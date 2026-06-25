// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";
import { icon } from "./icon.js";

const BUTTON_SIZE_CLASSES = new Map([
	["sm", "btn--sm"],
	["md", "btn--md"],
	["lg", "btn--lg"]
]);
const BUTTON_VARIANT_CLASSES = new Map([
	["danger", "btn--danger"],
	["outline", "btn--outline"],
	["primary", "btn--primary"],
	["subtle", "btn--subtle"]
]);

function classList(parts) {
	return parts.filter(Boolean).join(" ");
}

function sizeClass(size) {
	return BUTTON_SIZE_CLASSES.get(size) || BUTTON_SIZE_CLASSES.get("md");
}

function variantClass(variant) {
	return BUTTON_VARIANT_CLASSES.get(variant) || BUTTON_VARIANT_CLASSES.get("outline");
}

function disabledAttrs(tag, disabled) {
	if (!disabled) return "";
	return tag === "a" ? ' aria-disabled="true" tabindex="-1"' : " disabled";
}

function outboundHref(href) {
	return /^https?:\/\//i.test(String(href || ""));
}

function withRelToken(attrs, token) {
	const input = attrs || "";
	const rel = /(^|\s)rel=(["'])(.*?)\2/i;
	if (rel.test(input)) {
		return input.replace(rel, (match, prefix, quote, value) => {
			const tokens = value.split(/\s+/).filter(Boolean);
			const seen = new Set(tokens.map((t) => t.toLowerCase()));
			if (!seen.has(token)) {
				tokens.push(token);
			}
			return `${prefix}rel=${quote}${tokens.join(" ")}${quote}`;
		});
	}
	return input ? `${input} rel="${token}"` : `rel="${token}"`;
}

function commonAttrs(tag, opts) {
	const extraAttrs = tag === "a" && outboundHref(opts.href) ? withRelToken(opts.attrs, "nofollow") : opts.attrs || "";
	return `${tag === "a" ? ` href="${opts.href}"` : ` type="${esc(opts.type || "button")}"`}${disabledAttrs(tag, opts.disabled)}${extraAttrs ? ` ${extraAttrs}` : ""}`;
}

export function button(label, opts = {}) {
	const tag = opts.href ? "a" : "button";
	const variant = opts.variant || "outline";
	const { size: requestedSize } = opts;
	const size = requestedSize || "md";
	const cls = classList(["btn", variantClass(variant), sizeClass(size), opts.cls]);
	const body = `${opts.icon ? `${icon(opts.icon)} ` : ""}${esc(label)}`;
	return `<${tag} class="${cls}"${commonAttrs(tag, opts)}>${body}</${tag}>`;
}

export function iconButton(iconName, ariaLabel, opts = {}) {
	if (!ariaLabel) throw new Error("iconButton requires an ariaLabel");
	const tag = opts.href ? "a" : "button";
	const { size: requestedSize } = opts;
	const size = requestedSize || "md";
	const variant = opts.variant && opts.variant !== "ghost" ? variantClass(opts.variant) : "";
	const cls = classList(["btn", "btn--icon", variant, sizeClass(size), opts.cls]);
	return `<${tag} class="${cls}" aria-label="${esc(ariaLabel)}"${commonAttrs(tag, opts)}>${icon(iconName)}</${tag}>`;
}
