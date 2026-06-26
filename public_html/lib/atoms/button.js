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

/**
 * @typedef {object} ButtonOpts
 * @property {string} [href]
 * @property {string} [variant]
 * @property {string} [size]
 * @property {string} [cls]
 * @property {string} [icon]
 * @property {string} [type]
 * @property {boolean} [disabled]
 * @property {string} [attrs]
 */

/**
 * @param {(string | false | null | undefined)[]} parts
 * @returns {string}
 */
function classList(parts) {
	return parts.filter(Boolean).join(" ");
}

/** @param {string | undefined} size */
function sizeClass(size) {
	return BUTTON_SIZE_CLASSES.get(/** @type {string} */ (size)) || BUTTON_SIZE_CLASSES.get("md");
}

/** @param {string | undefined} variant */
function variantClass(variant) {
	return BUTTON_VARIANT_CLASSES.get(/** @type {string} */ (variant)) || BUTTON_VARIANT_CLASSES.get("outline");
}

/**
 * @param {string} tag
 * @param {boolean | undefined} disabled
 */
function disabledAttrs(tag, disabled) {
	if (!disabled) return "";
	return tag === "a" ? ' aria-disabled="true" tabindex="-1"' : " disabled";
}

/** @param {string | undefined} href */
function outboundHref(href) {
	// Stryker disable next-line StringLiteral: outboundHref is only reached when tag === "a", i.e. opts.href is truthy, so the `|| ""` fallback is unreachable — equivalent.
	return /^https?:\/\//i.test(String(href || ""));
}

/**
 * @param {string | undefined} attrs
 * @param {string} token
 * @returns {string}
 */
function withRelToken(attrs, token) {
	const input = attrs || "";
	const rel = /(^|\s)rel=(["'])(.*?)\2/i;
	if (rel.test(input)) {
		return input.replace(
			rel,
			/**
			 * @param {string} match
			 * @param {string} prefix
			 * @param {string} quote
			 * @param {string} value
			 */
			(match, prefix, quote, value) => {
				// Stryker disable next-line Regex: `\s+` → `\s` only changes how runs of whitespace split, but .filter(Boolean) drops the resulting empty tokens either way, so the token list is identical — equivalent.
				const tokens = value.split(/\s+/).filter(Boolean);
				const seen = new Set(tokens.map((t) => t.toLowerCase()));
				if (!seen.has(token)) {
					tokens.push(token);
				}
				return `${prefix}rel=${quote}${tokens.join(" ")}${quote}`;
			}
		);
	}
	return input ? `${input} rel="${token}"` : `rel="${token}"`;
}

/**
 * @param {string} tag
 * @param {ButtonOpts} opts
 */
function commonAttrs(tag, opts) {
	// Stryker disable next-line ConditionalExpression: `tag === "a"` is redundant with `outboundHref(opts.href)` — tag is "a" exactly when opts.href is truthy, and outboundHref(falsy href) is always false, so `tag === "a" && …` ≡ `true && …`. (Co-disables the outer ternary's true/false mutants, which the rel tests still assert.)
	const extraAttrs = tag === "a" && outboundHref(opts.href) ? withRelToken(opts.attrs, "nofollow") : opts.attrs || "";
	return `${tag === "a" ? ` href="${opts.href}"` : ` type="${esc(opts.type || "button")}"`}${disabledAttrs(tag, opts.disabled)}${extraAttrs ? ` ${extraAttrs}` : ""}`;
}

/**
 * @param {string} label
 * @param {ButtonOpts} [opts]
 * @returns {string}
 */
export function button(label, opts = {}) {
	const tag = opts.href ? "a" : "button";
	// Stryker disable next-line StringLiteral: variantClass("") falls back to the same "btn--outline" as variantClass("outline"), so the default string is not observable — equivalent.
	const variant = opts.variant || "outline";
	const { size: requestedSize } = opts;
	// Stryker disable next-line StringLiteral: sizeClass("") falls back to the same "btn--md" as sizeClass("md"), so the default string is not observable — equivalent.
	const size = requestedSize || "md";
	const cls = classList(["btn", variantClass(variant), sizeClass(size), opts.cls]);
	const body = `${opts.icon ? `${icon(opts.icon)} ` : ""}${esc(label)}`;
	return `<${tag} class="${cls}"${commonAttrs(tag, opts)}>${body}</${tag}>`;
}

/**
 * @param {string} iconName
 * @param {string} ariaLabel
 * @param {ButtonOpts} [opts]
 * @returns {string}
 */
export function iconButton(iconName, ariaLabel, opts = {}) {
	if (!ariaLabel) throw new Error("iconButton requires an ariaLabel");
	const tag = opts.href ? "a" : "button";
	const { size: requestedSize } = opts;
	// Stryker disable next-line StringLiteral: sizeClass("") falls back to the same "btn--md" as sizeClass("md"), so the default string is not observable — equivalent.
	const size = requestedSize || "md";
	const variant = opts.variant && opts.variant !== "ghost" ? variantClass(opts.variant) : "";
	const cls = classList(["btn", "btn--icon", variant, sizeClass(size), opts.cls]);
	return `<${tag} class="${cls}" aria-label="${esc(ariaLabel)}"${commonAttrs(tag, opts)}>${icon(iconName)}</${tag}>`;
}
