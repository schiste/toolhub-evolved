// SPDX-License-Identifier: GPL-3.0-or-later
/**
 * The mark beside a field no maintainer published.
 *
 * What matters is which way it errs. A field a maintainer did publish must
 * carry nothing, and so must a field this codebase knows nothing about -- a
 * footnote on most of the catalogue would say less than no footnote at all.
 */
import assert from "node:assert/strict";
import { test } from "vitest";
import { sourceMark } from "../../public_html/lib/atoms/source-mark.js";

/** @param {string} source @param {Record<string, unknown>} [extra] */
const projectionFor = (source, extra = {}) => ({
	provenance: { user_docs_url: [{ source, effective: true, ...extra }] }
});

test("sourceMark() marks a value read off a wiki page", () => {
	const html = sourceMark("user_docs_url", projectionFor("wikimedia_user_script"));
	assert.match(html, /<sup class="source-mark"/);
	assert.match(html, /aria-label="Not from a toolinfo\.json: read from the wiki page beside the script"/);
});

test("sourceMark() names the wiki's gadget definition when that is the source", () => {
	assert.match(sourceMark("user_docs_url", projectionFor("wiki_gadget_definition")), /gadget definition/);
});

test("sourceMark() names repository analysis when that is the source", () => {
	assert.match(sourceMark("user_docs_url", projectionFor("repository_analysis")), /tool&#39;s repository/);
});

test("sourceMark() marks a reviewed Evolved correction too", () => {
	// A person rather than a machine, and still not a maintainer's toolinfo.json.
	assert.match(sourceMark("user_docs_url", projectionFor("evolved_curation")), /reviewed Toolhub Evolved/);
});

test("sourceMark() falls back to naming an unrecognized source verbatim", () => {
	assert.match(sourceMark("user_docs_url", projectionFor("some_future_lane")), /some_future_lane/);
});

test("sourceMark() escapes what it puts in the label", () => {
	const html = sourceMark("user_docs_url", projectionFor('"><script>'));
	assert.ok(!html.includes("<script>"));
});

test("sourceMark() leaves a field the official catalogue published unmarked", () => {
	assert.equal(sourceMark("user_docs_url", projectionFor("official_toolhub")), "");
});

test("sourceMark() leaves a field from a crawled toolinfo.json unmarked", () => {
	assert.equal(sourceMark("user_docs_url", projectionFor("official_toolinfo")), "");
	assert.equal(sourceMark("user_docs_url", projectionFor("self_hosted_toolinfo")), "");
});

test("sourceMark() reads the effective row rather than the first one", () => {
	const projection = {
		provenance: {
			user_docs_url: [
				{ source: "wikimedia_user_script", effective: false },
				{ source: "official_toolhub", effective: true }
			]
		}
	};
	assert.equal(sourceMark("user_docs_url", projection), "");
});

test("sourceMark() falls back to the first row when none is marked effective", () => {
	const projection = { provenance: { user_docs_url: [{ source: "wikimedia_user_script" }] } };
	assert.match(sourceMark("user_docs_url", projection), /source-mark/);
});

test("sourceMark() says nothing about a field with no provenance recorded", () => {
	// Silence is not evidence that a value was derived.
	assert.equal(sourceMark("description", projectionFor("wikimedia_user_script")), "");
	assert.equal(sourceMark("user_docs_url", { provenance: { user_docs_url: [] } }), "");
});

test("sourceMark() says nothing when there is no projection at all", () => {
	assert.equal(sourceMark("user_docs_url", null), "");
	assert.equal(sourceMark("user_docs_url", undefined), "");
	assert.equal(sourceMark("user_docs_url", { provenance: "not an object" }), "");
});
