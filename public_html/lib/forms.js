// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "./dom.js";

// Shared form-field renderers (reused by all Lane B forms).
export function fInput(label, id, value, opts) {
	opts = opts || {};
	return `<label class="le__label">${esc(label)}${opts.req && opts.reqMark !== false ? ' <span class="le__req">*</span>' : ""}
		<input class="le__input" id="${id}" type="${opts.type || "text"}"${opts.req ? " required" : ""} maxlength="${opts.max || 300}" value="${esc(value == null ? "" : value)}" ${opts.ph ? `placeholder="${esc(opts.ph)}"` : ""} /></label>`;
}
export function fArea(label, id, value, hint, opts) {
	opts = opts || {};
	return `<label class="le__label">${esc(label)}${hint ? ` <span class="le__hint">${esc(hint)}</span>` : ""}
		<textarea class="le__input" id="${id}" rows="3" maxlength="${opts.max || 2000}">${esc(value == null ? "" : value)}</textarea></label>`;
}
export function fCheck(label, id, checked) {
	return `<label class="le__check"><input type="checkbox" id="${id}"${checked ? " checked" : ""} /> ${esc(label)}</label>`;
}
export const TOOL_TYPES = ["", "web app", "desktop app", "bot", "gadget", "user script", "command line tool", "coding framework", "lua module", "template", "other"];
export function fSelect(label, id, value, options) {
	return `<label class="le__label">${esc(label)}
		<select class="le__input" id="${id}">${options.map((o) => `<option value="${esc(o)}"${o === (value || "") ? " selected" : ""}>${esc(o || "—")}</option>`).join("")}</select></label>`;
}
export function fieldValue(id) { const el = document.getElementById(id); return el ? el.value.trim() : ""; }
export function checkedValue(id) { const el = document.getElementById(id); return !!(el && el.checked); }
