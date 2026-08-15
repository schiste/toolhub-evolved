// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import {
	buildToolinfo,
	formatMultilingualUrls,
	normalizeToolinfoAuthors,
	parseMultilingualUrls,
	prefillToolinfo,
	toolforgeToolinfoName,
	toolinfoJson,
	validateToolinfo
} from "../../public_html/lib/core/toolinfo-generator.js";

test("prefill creates the canonical Toolforge name and enriches the matching author", () => {
	const result = prefillToolinfo(
		{
			name: "old-name",
			title: "My tool",
			description: "Useful metadata.",
			url: "https://example.org/",
			author: [{ name: "Christophe" }],
			keywords: ["editing", "reports"]
		},
		{
			projectName: "example",
			displayName: "Christophe",
			wikiUsername: "Schiste",
			developerUsernames: ["schiste"],
			identityVerified: true,
			isAuthor: true
		}
	);

	assert.equal(result.name, "toolforge-example");
	assert.deepEqual(result.author, [{ name: "Christophe", wiki_username: "Schiste", developer_username: "schiste" }]);
	assert.equal(result.keywords, "editing, reports");
});

test("prefill creates a reviewable record for an unregistered Toolforge project", () => {
	const result = prefillToolinfo(
		{},
		{
			projectName: "citation-bot",
			displayName: "Ada",
			wikiUsername: "Ada",
			developerUsernames: ["ada"],
			identityVerified: true,
			isAuthor: true
		}
	);

	assert.deepEqual(
		{
			name: result.name,
			title: result.title,
			url: result.url,
			forWikis: result.for_wikis,
			languages: result.available_ui_languages,
			author: result.author
		},
		{
			name: "toolforge-citation-bot",
			title: "Citation Bot",
			url: "https://citation-bot.toolforge.org/",
			forWikis: ["*"],
			languages: ["en"],
			author: [{ name: "Ada", wiki_username: "Ada", developer_username: "ada" }]
		}
	);
});

test("multiple developer identities are never collapsed into one author handle", () => {
	const result = prefillToolinfo(
		{},
		{
			projectName: "shared",
			displayName: "Ada",
			developerUsernames: ["ada", "ada-alt"],
			identityVerified: true,
			isAuthor: true
		}
	);
	assert.deepEqual(result.author, [{ name: "Ada" }]);
});

test("maintainership alone does not create authorship or enrich an unverified match", () => {
	const maintainer = prefillToolinfo(
		{},
		{ projectName: "example", displayName: "Ada", wikiUsername: "AdaWiki", identityVerified: true, isAuthor: false }
	);
	assert.deepEqual(maintainer.author, []);

	const unverified = prefillToolinfo(
		{ author: [{ name: "Ada" }] },
		{ displayName: "Ada", wikiUsername: "AdaWiki", identityVerified: false, isAuthor: true }
	);
	assert.deepEqual(unverified.author, [{ name: "Ada" }]);
});

test("author and multilingual helpers preserve supported schema shapes", () => {
	assert.deepEqual(normalizeToolinfoAuthors("Ada"), [{ name: "Ada" }]);
	assert.equal(
		formatMultilingualUrls([
			{ language: "en", url: "https://example.org/en" },
			{ language: "fr", url: "https://example.org/fr" }
		]),
		"en | https://example.org/en\nfr | https://example.org/fr"
	);
	assert.deepEqual(parseMultilingualUrls("en | https://example.org/en\nhttps://example.org/default"), [
		{ language: "en", url: "https://example.org/en" },
		{ language: "en", url: "https://example.org/default" }
	]);
	assert.equal(parseMultilingualUrls("https://example.org/docs"), "https://example.org/docs");
	assert.deepEqual(parseMultilingualUrls("https://example.org/docs", { alwaysArray: true }), [
		{ language: "en", url: "https://example.org/docs" }
	]);
});

test("build omits empty and inapplicable fields and serializes with a final newline", () => {
	const built = buildToolinfo({
		name: "toolforge-example",
		title: "Example",
		description: "Description",
		url: "https://example.toolforge.org/",
		_language: "en",
		author: [{ name: "Ada" }, { name: "" }],
		deprecated: false,
		replaced_by: "https://example.org/new",
		experimental: true,
		license: ""
	});

	assert.equal(built._schema, "/toolinfo/1.2.2");
	assert.equal(built.replaced_by, undefined);
	assert.equal(built.deprecated, undefined);
	assert.equal(built.experimental, true);
	assert.equal(built.license, undefined);
	assert.deepEqual(built.author, [{ name: "Ada" }]);
	assert.ok(toolinfoJson(built).endsWith("\n"));
});

test("validation catches official schema constraints and accepts a valid record", () => {
	const valid = prefillToolinfo(
		{ title: "Example", description: "Description", tool_type: "web app", license: "GPL-3.0-or-later" },
		{ projectName: "example", displayName: "Ada" }
	);
	assert.deepEqual(validateToolinfo(valid, { projectName: "example" }), []);

	const invalid = {
		...valid,
		name: "wrong",
		url: "javascript:alert(1)",
		tool_type: "spaceship",
		for_wikis: ["example.org"],
		available_ui_languages: ["not a language"],
		icon: "https://example.org/icon.svg",
		user_docs_url: [{ language: "bad code", url: "nope" }],
		author: [{ name: "Ada", email: "not-an-email", url: "ftp://example.org" }]
	};
	const errors = validateToolinfo(invalid, { projectName: "example" });
	assert.ok(errors.some((error) => error.includes("name must be toolforge-example")));
	assert.ok(errors.some((error) => error.includes("tool_type")));
	assert.ok(errors.some((error) => error.includes("for_wikis")));
	assert.ok(errors.some((error) => error.includes("Author email")));
});

test("toolforge name helper removes a repeated prefix", () => {
	assert.equal(toolforgeToolinfoName("toolforge-example"), "toolforge-example");
	assert.equal(toolforgeToolinfoName(""), "");
});
