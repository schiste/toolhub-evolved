// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test, vi } from "vitest";
// toolsByAuthor hits the network (paginate → apiGet), so it is fixture-driven here.
// authorProfileUrl, grid, toolCard, and the dom/i18n helpers stay real so the rendered
// HTML — and the `(t) => toolCard(t)` mapper arrow — is exercised end to end.
import { viewAuthor } from "../../public_html/views/authors.js";
import { icon } from "../../public_html/lib/atoms/icon.js";
import * as authorIndex from "../../public_html/lib/core/author-index.js";

vi.mock("../../public_html/lib/core/author-index.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, toolsByAuthor: vi.fn() };
});

const tool = (name, title) => ({ name, title, keywords: [], forWikis: [] });

test("viewAuthor renders the author name, count, back link and a tools grid", async () => {
	authorIndex.toolsByAuthor.mockResolvedValue({
		name: "Ada Lovelace",
		tools: [tool("t1", "Tool One"), tool("t2", "Tool Two")],
		profile: { url: "https://example.org/ada" }
	});
	const view = await viewAuthor("ada");

	assert.equal(view.title, "Ada Lovelace — Toolhub");
	assert.match(view.html, /<a class="back" href="\/search">← Back to tools<\/a>/);
	assert.match(view.html, /<h1 class="page__title" dir="auto">Ada Lovelace<\/h1>/);
	// countLabel(2, "tool", "tools") → "2 tools" (kills the "tool"/"tools" literals + count).
	assert.match(view.html, /<p class="page__intro">2 tools<\/p>/);
	// Real grid + the mapper arrow produce one card per tool.
	assert.match(view.html, /<ul class="card-grid grid-tools" role="list">/);
	assert.match(view.html, /data-tool="t1"/);
	assert.match(view.html, /data-tool="t2"/);
	// Author profile link present and outbound, with the real external icon
	// (kills icon("external") → icon("")).
	assert.match(
		view.html,
		/<a class="author-page__profile" href="https:\/\/example\.org\/ada" target="_blank" rel="noopener nofollow">Author profile /
	);
	assert.ok(view.html.includes(`Author profile ${icon("external")}</a>`));
});

test("viewAuthor uses the requested name and singular label when the index omits them", async () => {
	// No `name` → falls back to the requested name; no `tools` → empty array → empty state.
	authorIndex.toolsByAuthor.mockResolvedValue({ profile: {} });
	const view = await viewAuthor("Grace Hopper");

	assert.equal(view.title, "Grace Hopper — Toolhub");
	assert.match(view.html, /<h1 class="page__title" dir="auto">Grace Hopper<\/h1>/);
	// Empty tools → empty state, never a grid.
	assert.match(view.html, /<p class="empty">No tools found for this author\.<\/p>/);
	assert.doesNotMatch(view.html, /card-grid/);
	// No profile → profileLink is exactly "" (kills the `: ""` → injected-string mutant):
	// the inner head <div> closes and the section-head <div> closes with only whitespace
	// between them — an injected fallback string would appear there.
	assert.doesNotMatch(view.html, /author-page__profile/);
	assert.match(view.html, /<\/p(?:>\s*<\/div){2}>/);
});

test("viewAuthor shows exactly one tool with the singular 'tool' label", async () => {
	authorIndex.toolsByAuthor.mockResolvedValue({ name: "Solo", tools: [tool("only", "Only Tool")], profile: {} });
	const view = await viewAuthor("Solo");
	assert.match(view.html, /<p class="page__intro">1 tool<\/p>/);
	assert.match(view.html, /<ul class="card-grid grid-tools" role="list">/);
});

test("viewAuthor builds a Meta-Wiki profile URL from a wikiUsername", async () => {
	authorIndex.toolsByAuthor.mockResolvedValue({
		name: "Wiki User",
		tools: [],
		profile: { wikiUsername: "Wiki User" }
	});
	const view = await viewAuthor("Wiki User");
	assert.match(
		view.html,
		/href="https:\/\/meta\.wikimedia\.org\/wiki\/User:Wiki%20User" target="_blank" rel="noopener nofollow"/
	);
});

test("viewAuthor drops an unsafe (non-http) profile URL via safeUrl", async () => {
	authorIndex.toolsByAuthor.mockResolvedValue({
		name: "Sneaky",
		tools: [],
		// authorProfileUrl returns this verbatim; safeUrl must reject it, so no link renders.
		profile: { url: "javascript:alert(1)" }
	});
	const view = await viewAuthor("Sneaky");
	assert.doesNotMatch(view.html, /author-page__profile/);
	assert.doesNotMatch(view.html, /javascript:/);
});
