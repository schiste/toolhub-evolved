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
			export const status = t("apiExplorer.requestComplete", "GET {path} returned {status}.");`
		]
	]);
	assert.deepEqual(problems, []);
	assert.deepEqual(catalog, {
		"apiExplorer.requestComplete": "GET {path} returned {status}.",
		"apiExplorer.runRequest": "Run request"
	});
	assert.equal(
		renderCatalog(catalog),
		'{\n\t"apiExplorer.requestComplete": "GET {path} returned {status}.",\n\t"apiExplorer.runRequest": "Run request"\n}\n'
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
			t("bad.html", "Click <strong>now</strong>");
			t("bad.placeholder", "Saved {count, plural, one {tool} other {tools}}.");`
		]
	]);
	assert.match(problems.join("\n"), /non-literal key/);
	assert.match(problems.join("\n"), /without a literal English fallback/);
	assert.match(problems.join("\n"), /key must be dot-separated ASCII/);
	assert.match(problems.join("\n"), /fallback contains HTML/);
	assert.match(problems.join("\n"), /placeholder "\{count, plural, one \{tool}" must be a simple named parameter/);
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
