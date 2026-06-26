// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "node:test";
import { scanTemplates, scanText } from "../../tools/checks.mjs";

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

// Fixtures use escaped \${ / \` so the literal source text contains real
// template interpolations without tripping no-template-curly-in-string.
test("scanTemplates flags a raw risky-field interpolation in HTML", () => {
	const code = `export const v = (t) => \`<h2>\${t.title}</h2>\`;`;
	const issues = scanTemplates(code, "v.js");
	assert.equal(issues.length, 1);
	assert.match(issues[0].message, /unescaped interpolation/);
	assert.equal(issues[0].line, 1);
});

test("scanTemplates accepts esc(), components, and bare vars", () => {
	const code = `export const v = (t, rows) => \`<h2>\${esc(t.title)}</h2>\${icon('x')}\${rows}<b>\${t.count}</b>\`;`;
	assert.deepEqual(scanTemplates(code, "v.js"), []);
});

test("scanTemplates ignores non-HTML template literals", () => {
	const code = `export const u = (t) => \`/tools/\${t.title}\`;`; // a URL, no HTML tag
	assert.deepEqual(scanTemplates(code, "u.js"), []);
});

test("scanTemplates accepts non-risky member access (config/CSS)", () => {
	const code = `export const v = (opts) => \`<input type="\${opts.type}" rows="\${opts.rows}">\`;`;
	assert.deepEqual(scanTemplates(code, "v.js"), []);
});

test("scanTemplates sees risky fields inside ternary/logical", () => {
	const code = `export const v = (t) => \`<p>\${t.deprecated ? t.name : ""}</p><i>\${t && t.description}</i>\`;`;
	assert.equal(scanTemplates(code, "v.js").length, 2);
});
