// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "vitest";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

function read(rel) {
	return fs.readFileSync(path.join(ROOT, rel), "utf8");
}

function criticalCss(html) {
	const match = html.match(/<style data-critical-css>([\s\S]*?)<\/style>/);
	return match ? match[1] : "";
}

test("router loads high-cost feature routes as their own chunks", () => {
	const router = read("public_html/views/router.js");
	for (const specifier of [
		"./recent.js",
		"./members.js",
		"./accounts.js",
		"./crawler.js",
		"./audit.js",
		"./account-settings.js",
		"./developer-settings.js",
		"./my-tools.js"
	]) {
		assert.ok(router.includes(`loadRouteModule("${specifier}"`));
	}
	assert.doesNotMatch(router, /loadRouteModule\("\.\/parity\.js"/);
	assert.doesNotMatch(router, /loadRouteModule\("\.\/account\.js"/);
});

test("index.html has critical shell CSS and defers full design-system CSS", () => {
	const html = read("public_html/index.html");
	const headBeforeNoscript = html.split("<noscript>")[0];
	const deferredLinks = html.match(/rel="preload" href="\/styles\/[^"]+\.css" as="style" data-deferred-style/g) || [];
	const noscriptStylesheets = html.match(/<link rel="stylesheet" href="\/styles\/[^"]+\.css" \/>/g) || [];
	assert.match(headBeforeNoscript, /<style data-critical-css>/);
	assert.match(headBeforeNoscript, /--container-wide:\s*1760px/);
	assert.match(headBeforeNoscript, /\.footer__cols\s*{/);
	assert.match(headBeforeNoscript, /\.footer__bottom\s*{/);
	assert.equal(deferredLinks.length, 6);
	assert.equal(noscriptStylesheets.length, 6);
	assert.doesNotMatch(headBeforeNoscript, /rel="stylesheet" href="\/styles\//);
	assert.doesNotMatch(headBeforeNoscript, /styleguide\.css/);
	assert.doesNotMatch(headBeforeNoscript, /onload=/);
});

test("critical shell CSS hides deferred dialogs and stabilizes account chrome", () => {
	const html = read("public_html/index.html");
	const css = criticalCss(html);
	assert.match(css, /\.hidden\s*{\s*display:\s*none;\s*}/);
	assert.match(css, /\.acct__btn,/);
	assert.match(css, /\.acct__btn \.avatar\s*{/);
	assert.match(css, /\.lang__btn/);
	assert.match(css, /\.theme-toggle__opt\s*{/);
	assert.match(html, /<div class="acct" id="account">\s*<a class="btn btn--outline btn--md" href="\/login"/);
	assert.ok(html.indexOf("<style data-critical-css>") < html.indexOf('<div class="command-palette hidden"'));
});

test("main.js activates deferred styles before the first route render", () => {
	const main = read("public_html/main.js");
	assert.match(main, /function activateDeferredStyles\(\)/);
	assert.ok(main.indexOf("activateDeferredStyles();") < main.lastIndexOf("runRender().finally("));
});

test("optional command palette cannot block the application module graph", () => {
	const main = read("public_html/main.js");
	assert.doesNotMatch(main, /from\s+["']\.\/lib\/organisms\/command-palette\.js["']/);
	assert.match(main, /import\(["']\.\/lib\/organisms\/command-palette\.js["']\)/);
	assert.match(main, /\.catch\(\(\) => undefined\)/);
});

test("boot watchdog is bounded and renders an explicit retry state", () => {
	const html = read("public_html/index.html");
	assert.match(html, /function showBootFailure\(\)/);
	assert.match(html, /Toolhub could not finish loading/);
	assert.match(html, /sessionStorage\.removeItem\(RELOAD_KEY\);\s*location\.reload\(\)/);
	assert.match(html, /setTimeout\(recoverBoot, 15000\)/);
});

test("styleguide CSS is owned by the styleguide route", () => {
	const styleguide = read("public_html/views/styleguide.js");
	assert.match(styleguide, /STYLEGUIDE_STYLESHEET = "\/styles\/styleguide\.css"/);
	assert.match(styleguide, /styles:\s*\[STYLEGUIDE_STYLESHEET\]/);
	assert.match(styleguide, /data-route-style="styleguide"/);
});
