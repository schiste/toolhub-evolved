// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "node:test";
import { scanText } from "../../tools/checks.mjs";

test("scanText flags external _blank links without rel=noopener", () => {
	const bad = `<a href="https://x.test" target="_blank">x</a>`;
	const issues = scanText(bad, "f.js");
	assert.equal(issues.length, 1);
	assert.match(issues[0].message, /rel="noopener"/);
	assert.equal(issues[0].line, 1);
});

test("scanText accepts _blank links that set rel=noopener", () => {
	const ok = `<a href="https://x.test" target="_blank" rel="noopener nofollow">x</a>`;
	assert.deepEqual(scanText(ok, "f.js"), []);
});

test("scanText trusts a templated rel value", () => {
	const ok = `<a href="\${u}" target="_blank" rel="\${EXTERNAL_REL}">x</a>`;
	assert.deepEqual(scanText(ok, "f.js"), []);
});

test("scanText flags hash-router URLs", () => {
	const bad = `line1\n<a href="/#/search">Search</a>`;
	const issues = scanText(bad, "f.js");
	assert.equal(issues.length, 1);
	assert.match(issues[0].message, /hash-router/);
	assert.equal(issues[0].line, 2);
});

test("scanText passes clean internal links", () => {
	assert.deepEqual(scanText(`<a href="/search">Search</a>`, "f.js"), []);
});
