// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import {
	metaItem,
	invalidUrlNotice,
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
		'<span class="linkout-bad" role="note" aria-label="Repo: invalid URL" data-url-state="invalid"><span class="linkout-bad__label">Repo</span><span class="linkout-bad__state">Invalid URL</span><span class="linkout-bad__url" dir="auto">not a url</span></span>'
	);
});

test("linkOut() labels malformed http-like values instead of linking them", () => {
	assert.equal(
		linkOut("Issues", "https://exa mple.org/issues"),
		'<span class="linkout-bad" role="note" aria-label="Issues: invalid URL" data-url-state="invalid"><span class="linkout-bad__label">Issues</span><span class="linkout-bad__state">Invalid URL</span><span class="linkout-bad__url" dir="auto">https://exa mple.org/issues</span></span>'
	);
});

test("invalidUrlNotice() escapes label and raw URL text", () => {
	assert.equal(
		invalidUrlNotice("<Repo>", "javascript:alert('<x>')"),
		'<span class="linkout-bad" role="note" aria-label="&lt;Repo&gt;: invalid URL" data-url-state="invalid"><span class="linkout-bad__label">&lt;Repo&gt;</span><span class="linkout-bad__state">Invalid URL</span><span class="linkout-bad__url" dir="auto">javascript:alert(&#39;&lt;x&gt;&#39;)</span></span>'
	);
	assert.equal(invalidUrlNotice("Repo", ""), "");
	assert.equal(invalidUrlNotice("Repo", null), "");
	assert.equal(invalidUrlNotice("Repo", undefined), "");
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

test("keywordTags marks an inferred keyword and leaves the maintainer's alone", () => {
	const tool = { keywords: ["citations", "links"] };
	const projection = {
		provenance: {
			keywords: [
				{ value: "citations", source: "official_toolhub", effective: true },
				{ value: "links", source: "llm_inference", effective: true }
			]
		}
	};

	const html = keywordTags(tool, { projection });

	// One mark, on the inferred tag only.
	assert.equal(html.match(/source-mark/g)?.length, 1);
	assert.match(html, /links<\/a><sup class="source-mark"/);
	assert.match(html, /citations<\/a><a class="tag"/);
});

test("keywordTags without a projection marks nothing rather than implying provenance", () => {
	// A caller that never had the projection cannot tell the sources apart, and
	// an unmarked list would claim they are all a maintainer's.
	const html = keywordTags({ keywords: ["citations", "links"] }, {});
	assert.equal(html.includes("source-mark"), false);
});
