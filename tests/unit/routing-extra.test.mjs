// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import * as routing from "../../public_html/lib/core/routing.js";

test("PERSONAS and NEEDS hold the exact icon/label/facet triples", () => {
	assert.deepEqual(routing.PERSONAS, [
		["edit", "Editors", "editor"],
		["code", "Developers", "developer"],
		["book", "Readers", "reader"],
		["research", "Researchers", "researcher"],
		["admin", "Admins", "admin"],
		["group", "Organizers", "organizer"]
	]);
	assert.deepEqual(routing.NEEDS, [
		["edit", "Edit content", "editing"],
		["add", "Create content", "creating"],
		["tag", "Categorize content", "categorizing"],
		["upload", "Upload media", "uploading"],
		["analyze", "Analyze data", "analysis"],
		["convert", "Convert & transform", "converting"],
		["book", "Read & browse", "reading"]
	]);
});

test("parseRoute reflects the current pathname", () => {
	window.history.replaceState({}, "", "/tools/Example");
	assert.deepEqual(routing.parseRoute(), { path: "/tools/Example" });
	window.history.replaceState({}, "", "/");
	assert.deepEqual(routing.parseRoute(), { path: "/" });
});

test("normalizeLegacyHashRoute rewrites #/… to a real path, else returns false", () => {
	window.history.replaceState({}, "", "/base");
	location.hash = "#/tools/Legacy";
	assert.equal(routing.normalizeLegacyHashRoute(), true);
	assert.equal(location.pathname, "/tools/Legacy");

	window.history.replaceState({}, "", "/base");
	location.hash = "#notaroute";
	assert.equal(routing.normalizeLegacyHashRoute(), false);

	window.history.replaceState({}, "", "/base2");
	assert.equal(routing.normalizeLegacyHashRoute(), false);
});

test("navigateTo pushes (or replaces) same-origin paths and dispatches the event", () => {
	window.history.replaceState({}, "", "/start");
	let fired = 0;
	const handler = () => {
		fired += 1;
	};
	window.addEventListener("toolhub:navigate", handler);
	try {
		const len0 = history.length;
		routing.navigateTo("/tools/abc");
		assert.equal(location.pathname, "/tools/abc");
		assert.equal(fired, 1);
		const lenAfterPush = history.length;
		assert.equal(lenAfterPush, len0 + 1); // pushState grows the stack

		routing.navigateTo("/tools/def", { replace: true });
		assert.equal(location.pathname, "/tools/def");
		assert.equal(fired, 2);
		assert.equal(history.length, lenAfterPush); // replaceState does not grow it

		// Navigating to the current path dispatches but does not push a new entry.
		const lenBefore = history.length;
		routing.navigateTo("/tools/def");
		assert.equal(fired, 3);
		assert.equal(history.length, lenBefore);
	} finally {
		window.removeEventListener("toolhub:navigate", handler);
	}
});

test("navigateTo to a cross-origin href hands off to location and does not dispatch", () => {
	window.history.replaceState({}, "", "/start");
	let fired = 0;
	const handler = () => {
		fired += 1;
	};
	window.addEventListener("toolhub:navigate", handler);
	try {
		routing.navigateTo("https://other.example/elsewhere");
		assert.equal(location.href, "https://other.example/elsewhere");
		assert.equal(fired, 0);
	} finally {
		window.removeEventListener("toolhub:navigate", handler);
		// Restore the same-origin location for any later tests in this file.
		location.href = "http://localhost:3000/";
		window.history.replaceState({}, "", "/");
	}
});
