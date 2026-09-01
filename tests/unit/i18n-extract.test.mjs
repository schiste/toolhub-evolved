// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import {
	extractCatalogFromEntries,
	messageDocumentation,
	messageKeyContext,
	messageParameters,
	renderCatalog,
	renderDocsCatalog,
	renderLocalesModule,
	validateLocaleCatalog,
	validateMessageShape,
	validateReviewManifest
} from "../../tools/i18n-extract.mjs";

test("extractCatalogFromEntries collects stable English source messages", () => {
	const { catalog, problems } = extractCatalogFromEntries([
		[
			"public_html/demo.js",
			`import { t } from "./i18n.js";
			export const label = t("apiExplorer.runRequest", "Run request");
			export const status = t("apiExplorer.requestComplete", "GET $1 returned $2.", path, code);
			export const count = t("search.toolCount", "$1 {{PLURAL:$2|tool|tools}}", fmt(n), n);
			export const inline = tWithElements("home.ctaBody", "Add $1 to your repository.", { html: "<code>toolinfo.json</code>" });`
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
		"apiExplorer.requestComplete": "GET $1 returned $2.",
		"apiExplorer.runRequest": "Run request",
		"commandPalette.inputPlaceholder": "Search tools or actions...",
		"home.ctaBody": "Add $1 to your repository.",
		"search.toolCount": "$1 {{PLURAL:$2|tool|tools}}",
		"shell.closeQuickView": "Close quick view",
		"shell.skipToContent": "Skip to content"
	});
});

test("renderCatalog emits tab-indented JSON, sorted, with @metadata first", () => {
	assert.equal(
		renderCatalog({ "b.two": "Two", "a.one": "One" }, { locale: "en" }),
		'{\n\t"@metadata": {\n\t\t"locale": "en"\n\t},\n\t"a.one": "One",\n\t"b.two": "Two"\n}\n'
	);
	assert.equal(renderCatalog({ "b.two": "Two", "a.one": "One" }), '{\n\t"a.one": "One",\n\t"b.two": "Two"\n}\n');
});

test("renderDocsCatalog keeps written documentation and generates context for the rest", () => {
	const docs = renderDocsCatalog(
		{ "a.plain": "Hello", "b.params": "GET $1 returned $2." },
		{ "a.plain": "Greeting shown on the home page." }
	);
	assert.equal(docs["a.plain"], "Greeting shown on the home page.");
	assert.equal(
		docs["b.params"],
		"Message shown in the b interface for params.\n\nParameters:\n" +
			"* $1 - Value substituted for $1 in the source message “GET $1 returned $2.”.\n" +
			"* $2 - Value substituted for $2 in the source message “GET $1 returned $2.”."
	);
	assert.doesNotMatch(JSON.stringify(docs), /TODO/);
});

test("message documentation turns stable keys into translator context", () => {
	assert.equal(messageKeyContext("dataLayer.summaryTitle"), "data layer › summary title");
	assert.equal(
		messageDocumentation("dataLayer.summaryTitle", "Overall filling"),
		"Message shown in the data layer interface for summary title."
	);
});

test("legacy documentation stubs are replaced instead of preserved", () => {
	const docs = renderDocsCatalog(
		{ "dataLayer.summaryTitle": "Overall filling" },
		{ "dataLayer.summaryTitle": "TODO: document this message." }
	);
	assert.equal(docs["dataLayer.summaryTitle"], "Message shown in the data layer interface for summary title.");
});

test("renderLocalesModule lists shipped catalogs in sorted order", () => {
	assert.match(renderLocalesModule(["fr", "en"]), /export const SHIPPED_LOCALES = \["en","fr"\];/);
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
			t("bad.magicWord", "{{GENDER:$1|he|she}} edited it", who);
			t("bad.paramGap", "$1 and $3", a, b, c);
			t("bad.argCount", "Only $1 here", a, b);
			t("bad.stillNamed", "Saved {count} tools", n);`
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
	assert.match(problems.join("\n"), /\{\{GENDER:…}}, which lib\/core\/i18n\.js does not implement/);
	assert.match(problems.join("\n"), /parameters must run \$1\.\.\$n without gaps/);
	assert.match(problems.join("\n"), /uses \$1\.\.\$1 but is called with 2 argument\(s\)/);
	assert.match(problems.join("\n"), /still has the pre-banana placeholder "\{count}"/);
	assert.match(problems.join("\n"), /without aria-label fallback/);
	assert.match(problems.join("\n"), /without text or data-i18n-fallback/);
});

test("literal braces are fine in a message that takes no arguments", () => {
	// Banana treats `{…}` as ordinary text, so an API path template is valid.
	const { problems } = extractCatalogFromEntries([
		["public_html/ok.js", `t("experiments.toolDetailsNeed", "GET /api/tools/{name}/ and revisions");`]
	]);
	assert.deepEqual(problems, []);
});

test("extractCatalogFromEntries rejects duplicate keys with different fallbacks", () => {
	const { problems } = extractCatalogFromEntries([
		["public_html/a.js", `t("dup.key", "First");`],
		["public_html/b.js", `t("dup.key", "Second");`]
	]);
	assert.match(problems.join("\n"), /key "dup.key" has two different fallbacks/);
});

test("message shape helpers accept the banana conventions", () => {
	assert.deepEqual(messageParameters("Copied $2 in $1 ms."), [1, 2]);
	assert.deepEqual(messageParameters("$1 of $1"), [1]);
	assert.deepEqual(messageParameters("no parameters"), []);
	assert.deepEqual(validateMessageShape("developerSettings.toolinfoSchema", "Inspect $1 tools.", 1), []);
	assert.deepEqual(validateMessageShape("search.toolCount", "$1 {{PLURAL:$2|tool|tools}}", 2), []);
	assert.deepEqual(validateMessageShape("people.name", "{{bidi:$1}} contributed", 1), []);
	// Without a call site there is no argument count to check against.
	assert.deepEqual(validateMessageShape("shell.skipToContent", "Skip to content"), []);
});

test("shipped locale validation requires complete keys and parameter parity", () => {
	const source = { "app.greeting": "Hello $1", "app.title": "Catalog" };
	assert.deepEqual(
		validateLocaleCatalog(source, { "app.greeting": "Bonjour $1", "app.title": "Catalogue" }, "fr"),
		[]
	);
	const problems = validateLocaleCatalog(
		source,
		{ "@metadata": { locale: "fr" }, "app.greeting": "Bonjour", "app.extra": "Extra" },
		"fr"
	);
	assert.match(problems.join("\n"), /missing 1\/2 source messages: app\.title/);
	assert.match(problems.join("\n"), /has 1 unknown messages: app\.extra/);
	assert.match(problems.join("\n"), /message "app\.greeting" parameters differ: expected \$1, got none/);
});

test("translation review evidence names a real shipped message pair", () => {
	const source = { "app.title": "Catalog" };
	const locales = { fr: { "app.title": "Catalogue" } };
	assert.deepEqual(
		validateReviewManifest(
			{
				version: 1,
				reviewed: [{ locale: "fr", key: "app.title", reviewedBy: "Ada", reviewedAt: "2026-09-01" }]
			},
			source,
			locales
		),
		[]
	);
	const problems = validateReviewManifest(
		{
			version: 2,
			reviewed: [
				{ locale: "de", key: "app.unknown", reviewedBy: "", reviewedAt: "September" },
				{ locale: "de", key: "app.unknown", reviewedBy: "Ada", reviewedAt: "2026-09-01" }
			]
		},
		source,
		locales
	);
	assert.match(problems.join("\n"), /version must be 1/);
	assert.match(problems.join("\n"), /names unshipped locale de/);
	assert.match(problems.join("\n"), /names unknown message app\.unknown/);
	assert.match(problems.join("\n"), /needs reviewedBy/);
	assert.match(problems.join("\n"), /needs reviewedAt in YYYY-MM-DD form/);
	assert.match(problems.join("\n"), /duplicates de:app\.unknown/);
});
