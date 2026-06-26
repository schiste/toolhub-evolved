// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import {
	metaItem,
	linkOut,
	wikiLabel,
	langLabel,
	wikiShort,
	keywordTags,
	glanceChips
} from "../../public_html/lib/atoms/labels.js";
import { icon } from "../../public_html/lib/atoms/icon.js";

// ---- metaItem -----------------------------------------------------------------
test("metaItem() renders key + value", () => {
	assert.equal(
		metaItem("Key", "Val"),
		'<div><div class="meta__k">Key</div><div class="meta__v" dir="auto">Val</div></div>'
	);
});

test("metaItem() falls back to em-dash for empty/null value", () => {
	assert.equal(
		metaItem("Key", null),
		'<div><div class="meta__k">Key</div><div class="meta__v" dir="auto">—</div></div>'
	);
	assert.equal(
		metaItem("Key", ""),
		'<div><div class="meta__k">Key</div><div class="meta__v" dir="auto">—</div></div>'
	);
});

// ---- linkOut ------------------------------------------------------------------
test("linkOut() empty for empty/null/undefined url", () => {
	assert.equal(linkOut("Repo", ""), "");
	assert.equal(linkOut("Repo", null), "");
	assert.equal(linkOut("Repo", undefined), "");
	assert.equal(linkOut("Repo", "   "), "");
});

test("linkOut() renders an outbound button for an https url", () => {
	assert.equal(
		linkOut("Repo", "https://github.com/a/b"),
		`<a class="btn btn--outline btn--md" href="https://github.com/a/b" target="_blank" rel="noopener nofollow">${icon("external")} Repo</a>`
	);
});

test("linkOut() normalizes a git+ url before linking", () => {
	assert.equal(
		linkOut("Repo", "git+https://github.com/a/b.git"),
		`<a class="btn btn--outline btn--md" href="https://github.com/a/b" target="_blank" rel="noopener nofollow">${icon("external")} Repo</a>`
	);
});

test("linkOut() normalizes an scp-style git url before linking", () => {
	assert.equal(
		linkOut("Repo", "git@github.com:a/b.git"),
		`<a class="btn btn--outline btn--md" href="https://github.com/a/b" target="_blank" rel="noopener nofollow">${icon("external")} Repo</a>`
	);
});

test("linkOut() renders a bad-link span for an unusable url", () => {
	assert.equal(
		linkOut("Repo", "not a url"),
		'<span class="linkout-bad">Repo: <span dir="auto">not a url</span></span>'
	);
});

// ---- wikiLabel ----------------------------------------------------------------
test("wikiLabel() variants", () => {
	assert.equal(wikiLabel([]), "Any wiki");
	assert.equal(wikiLabel(null), "Any wiki");
	assert.equal(wikiLabel(["*"]), "All wikis");
	assert.equal(wikiLabel(["en.wp", "fr.wp"]), "en.wp, fr.wp");
});

// ---- langLabel ----------------------------------------------------------------
test("langLabel() variants", () => {
	assert.equal(langLabel([]), "English (default)");
	assert.equal(langLabel(null), "English (default)");
	assert.equal(langLabel(["en", "fr"]), "en, fr");
});

// ---- wikiShort ----------------------------------------------------------------
test("wikiShort() variants", () => {
	assert.equal(wikiShort([]), "Any wiki");
	assert.equal(wikiShort(null), "Any wiki");
	assert.equal(wikiShort(["*"]), "All wikis");
	assert.equal(wikiShort(["en.wp"]), "en.wp");
	assert.equal(wikiShort(["a", "b", "c"]), "3 wikis");
});

// ---- keywordTags --------------------------------------------------------------
test("keywordTags() applies a limit", () => {
	assert.equal(
		keywordTags({ keywords: ["x", "y", "z"] }, { limit: 2 }),
		'<a class="tag" href="/search?keywords__term=x" dir="auto">x</a><a class="tag" href="/search?keywords__term=y" dir="auto">y</a>'
	);
});

test("keywordTags() renders all keywords when no limit option is given", () => {
	assert.equal(
		keywordTags({ keywords: ["x", "y"] }),
		'<a class="tag" href="/search?keywords__term=x" dir="auto">x</a><a class="tag" href="/search?keywords__term=y" dir="auto">y</a>'
	);
});

test("keywordTags() limit null renders all keywords", () => {
	assert.equal(
		keywordTags({ keywords: ["a", "b", "c"] }, { limit: null }),
		'<a class="tag" href="/search?keywords__term=a" dir="auto">a</a><a class="tag" href="/search?keywords__term=b" dir="auto">b</a><a class="tag" href="/search?keywords__term=c" dir="auto">c</a>'
	);
});

test("keywordTags() empty uses the empty option fallback", () => {
	assert.equal(keywordTags({ keywords: [] }, { empty: "none" }), "none");
});

test("keywordTags() empty without option returns empty string", () => {
	assert.equal(keywordTags({ keywords: [] }), "");
});

test("keywordTags() missing keywords falls back to an empty list (both branches)", () => {
	// t.keywords is undefined => `t.keywords || []`. Kills the ArrayDeclaration
	// fallback mutants on both the no-limit and the slice branch.
	assert.equal(keywordTags({}), "");
	assert.equal(keywordTags({}, { limit: 2 }), "");
});

// ---- glanceChips --------------------------------------------------------------
test("glanceChips() renders all chip types when present", () => {
	assert.equal(
		glanceChips({ toolType: "bot", license: "MIT", forWikis: ["en.wp"], uiLanguages: ["en", "fr"] }),
		'<span class="glance" dir="auto">bot</span><span class="glance" dir="auto">MIT</span><span class="glance" dir="auto">en.wp</span><span class="glance">2 languages</span>'
	);
});

test("glanceChips() renders only the wiki chip for a minimal tool", () => {
	assert.equal(glanceChips({ forWikis: [] }), '<span class="glance" dir="auto">Any wiki</span>');
});

test("glanceChips() omits the language chip when uiLanguages is empty (length > 0)", () => {
	// An empty array is truthy, so `uiLanguages.length > 0` (not >= 0) gates the chip;
	// without .filter(Boolean) the falsy `false` would serialise into the output.
	assert.equal(glanceChips({ forWikis: [], uiLanguages: [] }), '<span class="glance" dir="auto">Any wiki</span>');
});

test("glanceChips() singular 'language' for exactly one ui language", () => {
	assert.equal(
		glanceChips({ forWikis: ["en.wp"], uiLanguages: ["en"] }),
		'<span class="glance" dir="auto">en.wp</span><span class="glance">1 language</span>'
	);
});
