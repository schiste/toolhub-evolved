// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";

// Shared form-field renderers (reused by all Lane B forms).
function fHint(id, hint) {
	return hint ? ` <span class="le__hint" id="${esc(id)}-hint">${esc(hint)}</span>` : "";
}

function fDescAttrs(id, hint, hasError) {
	const ids = [];
	if (hint) ids.push(`${id}-hint`);
	if (hasError) ids.push(`${id}-err`);
	return ids.length ? ` aria-describedby="${ids.map(esc).join(" ")}"` : "";
}

function fInputClass(opts) {
	return `le__input${opts.cls ? " " + esc(opts.cls) : ""}`;
}

export function fInput(label, id, value, opts) {
	opts = opts || {};
	const hint = opts.hint;
	const hasError = opts.errorSlot !== false;
	return `<label class="le__label">${esc(label)}${opts.req && opts.reqMark !== false ? ' <span class="le__req">*</span>' : ""}
		${fHint(id, hint)}
		<input class="${fInputClass(opts)}" id="${id}" type="${opts.type || "text"}"${opts.req ? " required" : ""}${fDescAttrs(id, hint, hasError)} maxlength="${opts.max || 300}" value="${esc(value == null ? "" : value)}" ${opts.ph ? `placeholder="${esc(opts.ph)}"` : ""} />${hasError ? `<span class="le__error" id="${esc(id)}-err" hidden></span>` : ""}</label>`;
}
export function fArea(label, id, value, hint, opts) {
	opts = opts || {};
	hint = hint == null ? opts.hint : hint;
	const maxAttr = opts.max === false ? "" : ` maxlength="${opts.max || 2000}"`;
	return `<label class="le__label">${esc(label)}${fHint(id, hint)}
		<textarea class="${fInputClass(opts)}" id="${id}" rows="${opts.rows || 3}"${fDescAttrs(id, hint, false)}${maxAttr}${opts.ph ? ` placeholder="${esc(opts.ph)}"` : ""}>${esc(value == null ? "" : value)}</textarea></label>`;
}
export function fCheck(label, id, checked) {
	return `<label class="le__check"><input type="checkbox" id="${id}"${checked ? " checked" : ""} /> ${esc(label)}</label>`;
}
export const TOOL_TYPES = ["", "web app", "desktop app", "bot", "gadget", "user script", "command line tool", "coding framework", "lua module", "template", "other"];
export function fSelect(label, id, value, options, opts) {
	opts = opts || {};
	const hint = opts.hint;
	return `<label class="le__label">${esc(label)}${fHint(id, hint)}
		<select class="${fInputClass(opts)}" id="${id}"${fDescAttrs(id, hint, false)}>${options.map((o) => `<option value="${esc(o)}"${o === (value || "") ? " selected" : ""}>${esc(o || "—")}</option>`).join("")}</select></label>`;
}
export function fieldValue(id) { const el = document.getElementById(id); return el ? el.value.trim() : ""; }
export function checkedValue(id) { const el = document.getElementById(id); return !!(el && el.checked); }
export function setFieldError(id, msg) {
	const el = document.getElementById(id);
	const err = document.getElementById(`${id}-err`);
	if (!el || !err) return;
	el.setAttribute("aria-invalid", "true");
	el.classList.add("is-invalid");
	err.textContent = msg;
	err.hidden = false;
}
export function clearFieldError(id) {
	const el = document.getElementById(id);
	const err = document.getElementById(`${id}-err`);
	if (!el || !err) return;
	el.removeAttribute("aria-invalid");
	el.classList.remove("is-invalid");
	err.textContent = "";
	err.hidden = true;
}
