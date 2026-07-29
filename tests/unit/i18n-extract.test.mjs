// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import {
	extractCatalogFromEntries,
	messagePlaceholders,
	renderCatalog,
	validateMessageShape
} from "../../tools/i18n-extract.mjs";

test("extractCatalogFromEntries collects stable English source messages", () => {
	const { catalog, problems } = extractCatalogFromEntries([
		[
			"public_html/demo.js",
			`import { t } from "./i18n.js";
			export const label = t("apiExplorer.runRequest", "Run request");
			export const status = t("apiExplorer.requestComplete", "GET {path} returned {status}.");
			export const inline = tWithElements("home.ctaBody", "Add {toolinfo} to your repository.", { toolinfo: "<code>toolinfo.json</code>" });`
		],
		[
			"public_html/index.html",
			`<a data-i18n="shell.skipToContent">Skip to content</a>
			<button aria-label="Close quick view" data-i18n-aria-label="shell.closeQuickView"></button>
			<input placeholder="Search tools or actions..." data-i18n-placeholder="commandPalette.inputPlaceholder" />`
		]
	]);
	assert.deepEqual(problems, []);
	assert.deepEqual(catalog, {
		"apiExplorer.requestComplete": "GET {path} returned {status}.",
		"apiExplorer.runRequest": "Run request",
		"commandPalette.inputPlaceholder": "Search tools or actions...",
		"home.ctaBody": "Add {toolinfo} to your repository.",
		"shell.closeQuickView": "Close quick view",
		"shell.skipToContent": "Skip to content"
	});
	assert.equal(
		renderCatalog(catalog),
		'{\n\t"apiExplorer.requestComplete": "GET {path} returned {status}.",\n\t"apiExplorer.runRequest": "Run request",\n\t"commandPalette.inputPlaceholder": "Search tools or actions...",\n\t"home.ctaBody": "Add {toolinfo} to your repository.",\n\t"shell.closeQuickView": "Close quick view",\n\t"shell.skipToContent": "Skip to content"\n}\n'
	);
});

test("extractCatalogFromEntries reports translatewiki-hostile message shapes", () => {
	const { problems } = extractCatalogFromEntries([
		[
			"public_html/bad.js",
			`import { t } from "./i18n.js";
			t(dynamicKey, "Dynamic key");
			t("missingFallback");
			t("missingdot", "No namespace");
			t("home.ctaBodyBefore", "Split");
			t("bad.html", "Click <strong>now</strong>");
			t("bad.placeholder", "Saved {count, plural, one {tool} other {tools}}.");`
		],
		[
			"public_html/bad.html",
			`<button data-i18n-aria-label="bad.missingAttr"></button>
			<span data-i18n="bad.missingFallback"></span>`
		]
	]);
	assert.match(problems.join("\n"), /non-literal key/);
	assert.match(problems.join("\n"), /without a literal English fallback/);
	assert.match(problems.join("\n"), /key must be dot-separated ASCII/);
	assert.match(problems.join("\n"), /looks like a split prose fragment/);
	assert.match(problems.join("\n"), /fallback contains HTML/);
	assert.match(problems.join("\n"), /placeholder "\{count, plural, one \{tool}" must be a simple named parameter/);
	assert.match(problems.join("\n"), /without aria-label fallback/);
	assert.match(problems.join("\n"), /without text or data-i18n-fallback/);
});

test("extractCatalogFromEntries rejects duplicate keys with different fallbacks", () => {
	const { problems } = extractCatalogFromEntries([
		["public_html/a.js", `t("dup.key", "First");`],
		["public_html/b.js", `t("dup.key", "Second");`]
	]);
	assert.match(problems.join("\n"), /key "dup.key" has two different fallbacks/);
});

test("message shape helpers accept existing key and placeholder conventions", () => {
	assert.deepEqual(messagePlaceholders("Copied {label} in {duration} ms."), ["label", "duration"]);
	assert.deepEqual(validateMessageShape("developerSettings.toolinfoSchema", "Inspect {count} tools."), []);
});
