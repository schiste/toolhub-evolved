// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $input, esc } from "../core/dom.js";

// Shared form-field renderers (reused by all Lane B forms).
/**
 * @typedef {object} FieldOpts
 * @property {string} [hint]
 * @property {boolean} [errorSlot]
 * @property {string} [cls]
 * @property {boolean} [req]
 * @property {boolean} [reqMark]
 * @property {string} [type]
 * @property {number | false} [max]
 * @property {string} [ph]
 * @property {number} [rows]
 */

/**
 * @param {string} id
 * @param {string | undefined} hint
 */
function fHint(id, hint) {
	return hint ? ` <span class="le__hint" id="${esc(id)}-hint">${esc(hint)}</span>` : "";
}

/**
 * @param {string} id
 * @param {string | null | undefined} hint
 * @param {boolean} hasError
 */
function fDescAttrs(id, hint, hasError) {
	/** @type {string[]} */
	const ids = [];
	if (hint) ids.push(`${id}-hint`);
	if (hasError) ids.push(`${id}-err`);
	return ids.length > 0 ? ` aria-describedby="${ids.map((item) => esc(item)).join(" ")}"` : "";
}

/** @param {FieldOpts} opts */
function fInputClass(opts) {
	return `le__input${opts.cls ? ` ${esc(opts.cls)}` : ""}`;
}

/**
 * @param {string} label
 * @param {string} id
 * @param {string | number | null | undefined} value
 * @param {FieldOpts} [opts]
 * @returns {string}
 */
export function fInput(label, id, value, opts = {}) {
	const hint = opts.hint;
	const hasError = opts.errorSlot !== false;
	return `<label class="le__label">${esc(label)}${opts.req && opts.reqMark !== false ? ' <span class="le__req">*</span>' : ""}
		${fHint(id, hint)}
		<input class="${fInputClass(opts)}" id="${id}" type="${opts.type || "text"}"${opts.req ? " required" : ""}${fDescAttrs(id, hint, hasError)} maxlength="${opts.max || 300}" value="${esc(value === null || value === undefined ? "" : value)}" ${opts.ph ? `placeholder="${esc(opts.ph)}"` : ""} />${hasError ? `<span class="le__error" id="${esc(id)}-err" hidden></span>` : ""}</label>`;
}
/**
 * @param {string} label
 * @param {string} id
 * @param {string | number | null | undefined} value
 * @param {string | null | undefined} hint
 * @param {FieldOpts} [opts]
 * @returns {string}
 */
export function fArea(label, id, value, hint, opts = {}) {
	const fieldHint = hint === null || hint === undefined ? opts.hint : hint;
	const maxAttr = opts.max === false ? "" : ` maxlength="${opts.max || 2000}"`;
	return `<label class="le__label">${esc(label)}${fHint(id, fieldHint)}
		<textarea class="${fInputClass(opts)}" id="${id}" rows="${opts.rows || 3}"${fDescAttrs(id, fieldHint, false)}${maxAttr}${opts.ph ? ` placeholder="${esc(opts.ph)}"` : ""}>${esc(value === null || value === undefined ? "" : value)}</textarea></label>`;
}
/**
 * @param {string} label
 * @param {string} id
 * @param {boolean} [checked]
 * @returns {string}
 */
export function fCheck(label, id, checked) {
	return `<label class="le__check"><input type="checkbox" id="${id}"${checked ? " checked" : ""} /> ${esc(label)}</label>`;
}
export const TOOL_TYPES = [
	"",
	"web app",
	"desktop app",
	"bot",
	"gadget",
	"user script",
	"command line tool",
	"coding framework",
	"lua module",
	"template",
	"other"
];
/**
 * @param {string} label
 * @param {string} id
 * @param {string | null | undefined} value
 * @param {string[]} options
 * @param {FieldOpts} [opts]
 * @returns {string}
 */
export function fSelect(label, id, value, options, opts = {}) {
	const hint = opts.hint;
	return `<label class="le__label">${esc(label)}${fHint(id, hint)}
		<select class="${fInputClass(opts)}" id="${id}"${fDescAttrs(id, hint, false)}>${options.map((o) => `<option value="${esc(o)}"${o === (value || "") ? " selected" : ""}>${esc(o || "—")}</option>`).join("")}</select></label>`;
}
/** @param {string} id */
export function fieldValue(id) {
	const el = $input(`#${id}`);
	return el ? el.value.trim() : "";
}
/** @param {string} id */
export function checkedValue(id) {
	const el = $input(`#${id}`);
	return Boolean(el && el.checked);
}
/**
 * @param {string} id
 * @param {string} msg
 */
export function setFieldError(id, msg) {
	const el = $(`#${id}`);
	const err = $(`#${id}-err`);
	if (!el || !err) return;
	el.setAttribute("aria-invalid", "true");
	el.classList.add("is-invalid");
	err.textContent = msg;
	err.hidden = false;
}
/** @param {string} id */
export function clearFieldError(id) {
	const el = $(`#${id}`);
	const err = $(`#${id}-err`);
	if (!el || !err) return;
	el.removeAttribute("aria-invalid");
	el.classList.remove("is-invalid");
	err.textContent = "";
	err.hidden = true;
}
