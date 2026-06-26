// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "node:test";
import { scanA11y, scanComments, scanFloating, scanTemplates, scanText } from "../../tools/checks.mjs";

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

// ---- scanA11y -------------------------------------------------------------
test("scanA11y flags <img> with no alt and accepts decorative alt=''", () => {
	assert.match(scanA11y(`<img src="x.png">`, "f.js")[0].message, /alt attribute/);
	assert.deepEqual(scanA11y(`<img src="x.png" alt="">`, "f.js"), []);
	assert.deepEqual(scanA11y(`<img src="x.png" alt="A logo">`, "f.js"), []);
});

test("scanA11y flags a placeholder-only form control", () => {
	const issues = scanA11y(`<input type="search" placeholder="Search…">`, "f.js");
	assert.equal(issues.length, 1);
	assert.match(issues[0].message, /accessible name/);
});

test("scanA11y accepts every labelling pattern, literal or interpolated", () => {
	assert.deepEqual(scanA11y(`<label>Name <input type="text"></label>`, "f.js"), []); // wrapping
	assert.deepEqual(scanA11y(`<label for="q">Q</label><input id="q" type="search">`, "f.js"), []); // for/id
	assert.deepEqual(scanA11y(`<input type="search" aria-label="Search tools">`, "f.js"), []); // aria-label
	assert.deepEqual(scanA11y(`<input type="search" aria-label="\${i18n('search')}">`, "f.js"), []); // i18n lookup
	assert.deepEqual(scanA11y(`<select aria-labelledby="lbl"><option>a</option></select>`, "f.js"), []);
});

test("scanA11y ignores self-named inputs (submit/hidden/button/reset)", () => {
	assert.deepEqual(scanA11y(`<input type="submit" value="Go"><input type="hidden" name="t">`, "f.js"), []);
});

test("scanA11y flags positive tabindex but not 0 or -1", () => {
	assert.match(scanA11y(`<div tabindex="3">x</div>`, "f.js")[0].message, /positive tabindex/);
	assert.deepEqual(scanA11y(`<div tabindex="0">x</div><main tabindex="-1"></main>`, "f.js"), []);
});

test("scanA11y does not treat a CSS selector string as a tabindex element", () => {
	const code = `const SEL = 'a[href],button:not([tabindex="-1"])';`;
	assert.deepEqual(scanA11y(code, "f.js"), []);
});

test("scanA11y flags an icon-only control but not one with visible text or a name", () => {
	assert.match(scanA11y(`<button type="button">\${icon("close")}</button>`, "f.js")[0].message, /icon-only/);
	assert.deepEqual(scanA11y(`<button type="button" aria-label="Close">\${icon("close")}</button>`, "f.js"), []);
	assert.deepEqual(scanA11y(`<button type="button">\${icon("add")} <span>Add</span></button>`, "f.js"), []);
	assert.deepEqual(scanA11y(`<a href="/x">\${icon("ext")} Profile</a>`, "f.js"), []);
});

// ---- scanComments (commented-out code) ------------------------------------
test("scanComments flags disabled statements, blocks, imports, and block comments", () => {
	assert.match(scanComments(`// foo(x);`, "f.js")[0].message, /commented-out code/);
	assert.equal(scanComments(`// if (ready) {\n//   start();\n// }`, "f.js").length, 1);
	assert.equal(scanComments(`// import { x } from "./y.js";`, "f.js").length, 1);
	assert.equal(scanComments(`/* const n = 1; */`, "f.js").length, 1);
	assert.equal(scanComments(`x = 1; // n--;`, "f.js").length, 1);
});

test("scanComments ignores prose, JSDoc types, and bare identifiers", () => {
	assert.deepEqual(scanComments(`// url -> { data, ts }`, "f.js"), []); // prose, not valid JS
	assert.deepEqual(scanComments(`/** @returns {{ a: string }[]} */\nexport const f = () => [];`, "f.js"), []);
	assert.deepEqual(scanComments(`// returns the count.`, "f.js"), []);
	assert.deepEqual(scanComments(`// done;`, "f.js"), []); // bare identifier, not an action
	assert.deepEqual(scanComments(`// Wrap user data in esc() before use.`, "f.js"), []);
});

test("scanComments reports the comment's line number", () => {
	const issues = scanComments(`const ok = 1;\n\n// legacyInit();`, "f.js");
	assert.equal(issues.length, 1);
	assert.equal(issues[0].line, 3);
});

// ---- scanFloating (unhandled async data calls) ----------------------------
test("scanFloating flags a bare data-fetch call", () => {
	const issues = scanFloating(`async function f() { apiGet("/tools/"); }`, "f.js");
	assert.equal(issues.length, 1);
	assert.match(issues[0].message, /floating promise/);
});

test("scanFloating accepts await/return/assignment/.catch/void", () => {
	assert.deepEqual(scanFloating(`async function f() { await apiGet("/x"); }`, "f.js"), []);
	assert.deepEqual(scanFloating(`function f() { return getTool("x"); }`, "f.js"), []);
	assert.deepEqual(scanFloating(`async function f() { const d = await paginate("/x"); return d; }`, "f.js"), []);
	assert.deepEqual(scanFloating(`function f() { apiGet("/x").catch(() => {}); }`, "f.js"), []);
	assert.deepEqual(scanFloating(`function f() { void getToolsByName(["a"]); }`, "f.js"), []);
});

test("scanFloating ignores void UI functions and unrelated calls", () => {
	assert.deepEqual(scanFloating(`function h() { render(); refreshHome(); }`, "f.js"), []);
	assert.deepEqual(scanFloating(`function h() { doThing(); store.set("k", 1); }`, "f.js"), []);
});
