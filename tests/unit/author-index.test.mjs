// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import * as authorIndex from "../../public_html/lib/core/author-index.js";

test("authorProfileUrl prefers an explicit url, then a wiki username, else null", () => {
	assert.equal(authorIndex.authorProfileUrl(null), null);
	assert.equal(authorIndex.authorProfileUrl(undefined), null);
	assert.equal(authorIndex.authorProfileUrl({}), null);
	assert.equal(authorIndex.authorProfileUrl({ url: "https://ada.example" }), "https://ada.example");
	assert.equal(
		authorIndex.authorProfileUrl({ wikiUsername: "Ada Lovelace" }),
		"https://meta.wikimedia.org/wiki/User:Ada%20Lovelace"
	);
	// url wins over wikiUsername
	assert.equal(
		authorIndex.authorProfileUrl({ url: "https://ada.example", wikiUsername: "Ada" }),
		"https://ada.example"
	);
});

const seenUrls = [];
/**
 * @param {any} payload single-page list response
 */
function withFetch(payload, run) {
	const original = globalThis.fetch;
	seenUrls.length = 0;
	globalThis.fetch = async (url) => {
		seenUrls.push(String(url));
		// Only the real search endpoint returns data; a mutated path yields nothing.
		return {
			ok: true,
			json: async () => (String(url).includes("/search/tools/") ? payload : { results: [], next: null })
		};
	};
	return Promise.resolve()
		.then(run)
		.finally(() => {
			globalThis.fetch = original;
		});
}

test("toolsByAuthor folds matching author records into one profile (first url/wiki wins)", async () => {
	const payload = {
		next: null,
		results: [
			{ name: "t1", author: [{ name: "Ada Lovelace", url: "https://ada.example", wiki_username: "AdaWiki" }] },
			{
				name: "t2",
				author: [{ name: "ADA LOVELACE", url: "https://other.example", wiki_username: "OtherWiki" }]
			},
			{ name: "t3", author: [{ name: "Someone Else" }] },
			{ name: "t4" } // author-less => exercises authorRecords' empty fallback
		]
	};
	const entry = await withFetch(payload, () => authorIndex.toolsByAuthor("Ada Lovelace"));
	// requestedName has no matching author records, so name stays the last matching author.name.
	assert.equal(entry.name, "ADA LOVELACE");
	assert.equal(entry.tools.length, 4);
	// first matching record with a url/wiki wins; later ones do not overwrite.
	assert.equal(entry.profile.url, "https://ada.example");
	assert.equal(entry.profile.wikiUsername, "AdaWiki");
	// the request hits the search endpoint with the author term and ordering.
	assert.equal(seenUrls.length, 1);
	assert.ok(seenUrls[0].includes("/search/tools/"), seenUrls[0]);
	assert.ok(seenUrls[0].includes("ordering=-score"), seenUrls[0]);
	assert.ok(seenUrls[0].includes("author__term=Ada"), seenUrls[0]);
});

test("toolsByAuthor keeps the requested name and empty profile when nothing matches", async () => {
	const payload = {
		next: null,
		results: [{ name: "t9", author: [{ name: "Different Person" }] }]
	};
	const entry = await withFetch(payload, () => authorIndex.toolsByAuthor("Nobody Matches (unique-b)"));
	assert.equal(entry.name, "Nobody Matches (unique-b)");
	assert.equal(entry.tools.length, 1);
	assert.deepEqual(entry.profile, {});
});

test("toolsByAuthor recovers from a pagination failure with an empty tool list", async () => {
	// A null record makes the per-item map (normalizeTool) throw, rejecting paginate;
	// toolsByAuthor's .catch(() => []) then yields an empty entry.
	const payload = { next: null, results: [null] };
	const entry = await withFetch(payload, () => authorIndex.toolsByAuthor("Crash Author (unique-c)"));
	assert.equal(entry.name, "Crash Author (unique-c)");
	assert.deepEqual(entry.tools, []);
	assert.deepEqual(entry.profile, {});
});
