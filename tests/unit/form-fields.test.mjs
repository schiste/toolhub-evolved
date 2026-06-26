// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { afterEach, test } from "vitest";
import {
	fInput,
	fArea,
	fCheck,
	fSelect,
	fieldValue,
	checkedValue,
	setFieldError,
	clearFieldError,
	TOOL_TYPES
} from "../../public_html/lib/atoms/form-fields.js";

afterEach(() => {
	document.body.innerHTML = "";
});

// ---- fInput -------------------------------------------------------------------
test("fInput() basic field with error slot", () => {
	assert.equal(
		fInput("Name", "name", "val"),
		'<label class="le__label">Name\n\t\t\n\t\t<input class="le__input" id="name" type="text" aria-describedby="name-err" maxlength="300" value="val"  /><span class="le__error" id="name-err" hidden></span></label>'
	);
});

test("fInput() required with hint, custom type, max, placeholder", () => {
	assert.equal(
		fInput("Name", "name", "", { req: true, hint: "help", type: "email", max: 50, ph: "e.g." }),
		'<label class="le__label">Name <span class="le__req">*</span>\n\t\t <span class="le__hint" id="name-hint">help</span>\n\t\t<input class="le__input" id="name" type="email" required aria-describedby="name-hint name-err" maxlength="50" value="" placeholder="e.g." /><span class="le__error" id="name-err" hidden></span></label>'
	);
});

test("fInput() required but reqMark:false omits the asterisk", () => {
	assert.equal(
		fInput("Name", "name", "v", { req: true, reqMark: false }),
		'<label class="le__label">Name\n\t\t\n\t\t<input class="le__input" id="name" type="text" required aria-describedby="name-err" maxlength="300" value="v"  /><span class="le__error" id="name-err" hidden></span></label>'
	);
});

test("fInput() errorSlot:false drops the error span and aria-describedby, keeps cls", () => {
	assert.equal(
		fInput("Name", "name", "v", { errorSlot: false, cls: "x" }),
		'<label class="le__label">Name\n\t\t\n\t\t<input class="le__input x" id="name" type="text" maxlength="300" value="v"  /></label>'
	);
});

test("fInput() null/undefined value renders empty value attribute", () => {
	assert.equal(
		fInput("Name", "name", null),
		'<label class="le__label">Name\n\t\t\n\t\t<input class="le__input" id="name" type="text" aria-describedby="name-err" maxlength="300" value=""  /><span class="le__error" id="name-err" hidden></span></label>'
	);
});

test("fInput() numeric value is stringified", () => {
	assert.equal(
		fInput("Name", "name", 42),
		'<label class="le__label">Name\n\t\t\n\t\t<input class="le__input" id="name" type="text" aria-describedby="name-err" maxlength="300" value="42"  /><span class="le__error" id="name-err" hidden></span></label>'
	);
});

test("fInput() escapes the value", () => {
	assert.match(fInput("L", "id", "<x>&"), /value="&lt;x&gt;&amp;"/);
});

// ---- fArea --------------------------------------------------------------------
test("fArea() basic textarea, hint arg null uses no hint", () => {
	assert.equal(
		fArea("Bio", "bio", "text", null),
		'<label class="le__label">Bio\n\t\t<textarea class="le__input" id="bio" rows="3" maxlength="2000">text</textarea></label>'
	);
});

test("fArea() hint passed as argument", () => {
	assert.equal(
		fArea("Bio", "bio", "", "arg hint"),
		'<label class="le__label">Bio <span class="le__hint" id="bio-hint">arg hint</span>\n\t\t<textarea class="le__input" id="bio" rows="3" aria-describedby="bio-hint" maxlength="2000"></textarea></label>'
	);
});

test("fArea() falls back to opts.hint when hint arg is null; honours rows/ph/cls", () => {
	assert.equal(
		fArea("Bio", "bio", "", null, { hint: "opt hint", rows: 5, ph: "ph", cls: "c" }),
		'<label class="le__label">Bio <span class="le__hint" id="bio-hint">opt hint</span>\n\t\t<textarea class="le__input c" id="bio" rows="5" aria-describedby="bio-hint" maxlength="2000" placeholder="ph"></textarea></label>'
	);
});

test("fArea() max:false removes the maxlength attribute", () => {
	assert.equal(
		fArea("Bio", "bio", "", null, { max: false }),
		'<label class="le__label">Bio\n\t\t<textarea class="le__input" id="bio" rows="3"></textarea></label>'
	);
});

test("fArea() numeric max overrides default", () => {
	assert.equal(
		fArea("Bio", "bio", "", null, { max: 99 }),
		'<label class="le__label">Bio\n\t\t<textarea class="le__input" id="bio" rows="3" maxlength="99"></textarea></label>'
	);
});

test("fArea() null value renders empty body", () => {
	assert.equal(
		fArea("Bio", "bio", null, null),
		'<label class="le__label">Bio\n\t\t<textarea class="le__input" id="bio" rows="3" maxlength="2000"></textarea></label>'
	);
});

test("fArea() hint=undefined (vs null) also falls back to opts.hint", () => {
	// Distinguishes `hint === null || hint === undefined` from `hint === null || false`.
	assert.equal(
		fArea("Bio", "bio", "", undefined, { hint: "opt hint" }),
		'<label class="le__label">Bio <span class="le__hint" id="bio-hint">opt hint</span>\n\t\t<textarea class="le__input" id="bio" rows="3" aria-describedby="bio-hint" maxlength="2000"></textarea></label>'
	);
});

// ---- fCheck -------------------------------------------------------------------
test("fCheck() unchecked", () => {
	assert.equal(
		fCheck("Agree", "agree"),
		'<label class="le__check"><input type="checkbox" id="agree" /> Agree</label>'
	);
});

test("fCheck() checked", () => {
	assert.equal(
		fCheck("Agree", "agree", true),
		'<label class="le__check"><input type="checkbox" id="agree" checked /> Agree</label>'
	);
});

// ---- fSelect ------------------------------------------------------------------
test("fSelect() marks the selected option and renders em-dash for empty", () => {
	assert.equal(
		fSelect("Type", "type", "bot", ["", "web app", "bot"]),
		'<label class="le__label">Type\n\t\t<select class="le__input" id="type"><option value="">—</option><option value="web app">web app</option><option value="bot" selected>bot</option></select></label>'
	);
});

test("fSelect() null value selects the empty option; honours hint + cls", () => {
	assert.equal(
		fSelect("Type", "type", null, ["", "a"], { hint: "h", cls: "c" }),
		'<label class="le__label">Type <span class="le__hint" id="type-hint">h</span>\n\t\t<select class="le__input c" id="type" aria-describedby="type-hint"><option value="" selected>—</option><option value="a">a</option></select></label>'
	);
});

// ---- TOOL_TYPES ---------------------------------------------------------------
test("TOOL_TYPES is the exact ordered list", () => {
	assert.deepEqual(TOOL_TYPES, [
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
	]);
});

// ---- DOM helpers --------------------------------------------------------------
test("fieldValue() returns trimmed value, empty when missing", () => {
	document.body.innerHTML = '<input id="f1" value="  hi  " />';
	assert.equal(fieldValue("f1"), "hi");
	assert.equal(fieldValue("nope"), "");
});

test("checkedValue() reflects the checkbox state", () => {
	document.body.innerHTML = '<input id="c1" type="checkbox" checked /><input id="c2" type="checkbox" />';
	assert.equal(checkedValue("c1"), true);
	assert.equal(checkedValue("c2"), false);
	assert.equal(checkedValue("nope"), false);
});

test("setFieldError() marks the field invalid and shows the message", () => {
	document.body.innerHTML = '<input id="e1" /><span id="e1-err" hidden></span>';
	setFieldError("e1", "Bad");
	const el = document.querySelector("#e1");
	const err = document.querySelector("#e1-err");
	assert.equal(el.getAttribute("aria-invalid"), "true");
	assert.equal(el.classList.contains("is-invalid"), true);
	assert.equal(err.textContent, "Bad");
	assert.equal(err.hidden, false);
});

test("setFieldError() is a no-op when the error element is missing", () => {
	document.body.innerHTML = '<input id="e2" />';
	setFieldError("e2", "Bad");
	const el = document.querySelector("#e2");
	assert.equal(el.getAttribute("aria-invalid"), null);
	assert.equal(el.classList.contains("is-invalid"), false);
});

test("clearFieldError() resets the invalid state and hides the message", () => {
	document.body.innerHTML = '<input id="e3" /><span id="e3-err"></span>';
	setFieldError("e3", "Bad");
	clearFieldError("e3");
	const el = document.querySelector("#e3");
	const err = document.querySelector("#e3-err");
	assert.equal(el.getAttribute("aria-invalid"), null);
	assert.equal(el.classList.contains("is-invalid"), false);
	assert.equal(err.textContent, "");
	assert.equal(err.hidden, true);
});

test("clearFieldError() is a no-op when elements are missing", () => {
	document.body.innerHTML = '<input id="e4" />';
	// no #e4-err present → returns early without throwing
	clearFieldError("e4");
	assert.equal(document.querySelector("#e4").getAttribute("aria-invalid"), null);
});
