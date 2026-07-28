// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test } from "vitest";

import {
	changeSignature,
	fieldChange,
	fieldChanges,
	mountChangeReview
} from "../../public_html/lib/molecules/change-review.js";

beforeEach(() => {
	document.body.innerHTML = "";
});

test("fieldChanges normalizes text, booleans, sets, and ordered lists", () => {
	const changes = fieldChanges([
		{ key: "title", label: "Title", before: "Old", after: "  New  " },
		{ key: "keywords", label: "Keywords", before: ["beta", "alpha"], after: ["alpha", "beta"], type: "set" },
		{ key: "tools", label: "Tools", before: ["alpha", "bravo"], after: ["bravo", "alpha"], type: "ordered-list" },
		{ key: "deprecated", label: "Deprecated", before: false, after: true, type: "boolean" },
		{ key: "empty", label: "Empty", before: null, after: "", type: "text" }
	]);

	assert.deepEqual(
		changes.map((change) => change.key),
		["title", "tools", "deprecated"]
	);
	assert.equal(changes[0].after, "New");
	assert.equal(changes[1].reordered, true);
	assert.equal(changes[2].after, true);
});

test("fieldChange records added and removed list values", () => {
	const change = fieldChange({
		key: "audiences",
		label: "Audiences",
		before: ["editors", "admins"],
		after: ["editors", "researchers"],
		type: "set"
	});

	assert.deepEqual(change.added, ["researchers"]);
	assert.deepEqual(change.removed, ["admins"]);
});

test("changeSignature is stable for equivalent change data", () => {
	const changes = fieldChanges([{ key: "title", label: "Title", before: "A", after: "B" }]);
	assert.equal(changeSignature(changes), changeSignature(changes));
});

test("mountChangeReview blocks until the user confirms the current change set", () => {
	document.body.innerHTML = `<form><div class="le__actions"><button type="submit">Save</button></div></form>`;
	const form = document.querySelector("form");
	const review = mountChangeReview(form);
	const changes = fieldChanges([{ key: "title", label: "Title", before: "Old", after: "New" }]);
	let proceeded = 0;
	form.addEventListener("submit", (event) => {
		event.preventDefault();
		if (review.shouldProceed(changes)) proceeded += 1;
	});

	assert.equal(review.shouldProceed(changes), false);
	assert.equal(proceeded, 0);
	assert.equal(document.querySelector("[data-change-review]").hidden, false);
	assert.ok(document.body.textContent.includes("Old"));
	assert.ok(document.body.textContent.includes("New"));

	document.querySelector("[data-change-review-confirm]").dispatchEvent(new MouseEvent("click", { bubbles: true }));

	assert.equal(proceeded, 1);
	assert.equal(document.querySelector("[data-change-review]").hidden, true);
});

test("mountChangeReview reset invalidates a previously confirmed signature", () => {
	document.body.innerHTML = `<form><div class="le__actions"></div></form>`;
	const form = document.querySelector("form");
	const review = mountChangeReview(form);
	const changes = fieldChanges([{ key: "title", label: "Title", before: "Old", after: "New" }]);

	assert.equal(review.shouldProceed(changes), false);
	document.querySelector("[data-change-review-confirm]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	review.reset();

	assert.equal(review.shouldProceed(changes), false);
	assert.equal(document.querySelector("[data-change-review]").hidden, false);
});
