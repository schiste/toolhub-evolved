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
import { sourceMark, valueMark } from "../../public_html/lib/atoms/source-mark.js";

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

/**
 * The per-value mark, for a list that now holds two sources at once.
 *
 * Below KEYWORD_FILL_FLOOR the projection lets inference extend a keyword list
 * somebody else started. A per-field mark resolves to whichever row won the
 * field -- the maintainer's -- and would print nothing while displaying the
 * model's words as theirs.
 */
const MIXED_KEYWORDS = {
	provenance: {
		keywords: [
			{ value: "citations", source: "official_toolhub", effective: true },
			{ value: "links", source: "llm_inference", effective: true },
			{ value: "unused", source: "llm_inference", effective: false }
		]
	}
};

test("valueMark marks the inferred keyword in a mixed list", () => {
	const mark = valueMark("keywords", "links", MIXED_KEYWORDS);
	assert.match(mark, /source-mark/);
	assert.match(mark, /language model/);
});

test("valueMark leaves the maintainer's keyword in the same list unmarked", () => {
	assert.equal(valueMark("keywords", "citations", MIXED_KEYWORDS), "");
});

test("sourceMark alone would have marked neither, which is why valueMark exists", () => {
	// The field's effective row is the maintainer's, so the whole list reads as
	// theirs. This is the regression the per-value mark prevents.
	assert.equal(sourceMark("keywords", MIXED_KEYWORDS), "");
});

test("valueMark follows the value rather than its casing", () => {
	assert.match(valueMark("keywords", "  LINKS ", MIXED_KEYWORDS), /source-mark/);
});

test("valueMark ignores a value that was inferred but not published", () => {
	// `unused` stayed evidence-only past the ceiling; nothing displays it, and a
	// mark for it would attach to a tag that is not there.
	assert.equal(valueMark("keywords", "nothing-like-this", MIXED_KEYWORDS), "");
});

test("valueMark says nothing when there is no projection to consult", () => {
	assert.equal(valueMark("keywords", "links", null), "");
	assert.equal(valueMark("keywords", "links", { provenance: {} }), "");
});

/* Both inference lanes publish under `llm_inference`, and they do not read the
   same thing: a user script's answer comes from its source code, a gadget's
   from the description its wiki shows -- `wiki_gadgets` stores no source. One
   label for both told roughly 10,000 gadget keywords they came from source code
   nobody opened, which is the confusion the mark exists to prevent. */
test("a gadget's inferred keyword says which text was actually read", () => {
	const projection = {
		provenance: {
			keywords: [{ value: "clipboard", source: "llm_inference", lane: "gadget", effective: true }]
		}
	};
	const html = valueMark("keywords", "clipboard", projection);
	assert.match(html, /gadget&#39;s own description/);
	assert.doesNotMatch(html, /source code/);
});

test("a user script's inferred keyword still says source code", () => {
	const projection = {
		provenance: { keywords: [{ value: "links", source: "llm_inference", effective: true }] }
	};
	assert.match(valueMark("keywords", "links", projection), /source code/);
});

test("a lane on a transcribing source does not borrow the inference wording", () => {
	// `lane` says which text a model was given. A future source that recorded
	// one must not inherit a sentence about a language model that never ran.
	const projection = {
		provenance: {
			keywords: [{ value: "x", source: "wikimedia_user_script", lane: "gadget", effective: true }]
		}
	};
	const html = valueMark("keywords", "x", projection);
	assert.match(html, /wiki page beside the script/);
	assert.doesNotMatch(html, /language model/);
});
