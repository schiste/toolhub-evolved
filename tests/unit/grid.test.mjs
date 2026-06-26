// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { grid } from "../../public_html/lib/organisms/grid.js";

test("grid wraps each rendered item in <li> with index", () => {
	const html = grid("two-col", ["a", "b", "c"], (it, i) => `${it}:${i}`);
	assert.equal(html, `<ul class="card-grid two-col" role="list"><li>a:0</li><li>b:1</li><li>c:2</li></ul>`);
});

test("grid with empty items has no list children", () => {
	const html = grid("solo", [], () => "never");
	assert.equal(html, `<ul class="card-grid solo" role="list"></ul>`);
});

test("grid passes both item and index through to render", () => {
	/** @type {Array<[unknown, number]>} */
	const seen = [];
	grid("x", [{ k: 1 }, { k: 2 }], (it, i) => {
		seen.push([it, i]);
		return "";
	});
	assert.deepEqual(seen, [
		[{ k: 1 }, 0],
		[{ k: 2 }, 1]
	]);
});

test("grid interpolates the class name verbatim", () => {
	assert.equal(
		grid("my-class", ["z"], (it) => it),
		`<ul class="card-grid my-class" role="list"><li>z</li></ul>`
	);
});
