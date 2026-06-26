// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test, vi, beforeEach } from "vitest";
// globalGraph (network), communityColors/forceGraph (canvas), openQuickView and hasContext
// are all mocked so the legend HTML + mount() wiring are exercised deterministically. esc stays real.
import { viewGraph } from "../../public_html/views/graph.js";
import * as graphCore from "../../public_html/lib/core/graph.js";
import * as forceGraphMod from "../../public_html/lib/organisms/force-graph.js";
import * as quickview from "../../public_html/lib/organisms/quickview.js";
import * as signals from "../../public_html/lib/core/signals.js";

vi.mock("../../public_html/lib/core/graph.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, globalGraph: vi.fn() };
});
vi.mock("../../public_html/lib/organisms/force-graph.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, communityColors: vi.fn(), forceGraph: vi.fn() };
});
vi.mock("../../public_html/lib/organisms/quickview.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, openQuickView: vi.fn() };
});
vi.mock("../../public_html/lib/core/signals.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, hasContext: vi.fn() };
});

beforeEach(() => {
	vi.clearAllMocks();
	document.body.innerHTML = "";
});

test("viewGraph: a populated map renders the legend, truncated note, canvas, and mounts the force graph", async () => {
	const g = {
		nodes: [{ id: "a" }, { id: "b" }],
		truncated: true,
		communityMeta: [
			{ id: 1, label: "Alpha", size: 5 },
			{ id: 2, label: "Beta", size: 3 }
		]
	};
	graphCore.globalGraph.mockResolvedValue(g);
	// Map keyed so Alpha (id 1) resolves on the first branch (get(id)) and Beta (id 2) only
	// on the second branch (get(String(id))) — exercising both sides of the `||`.
	forceGraphMod.communityColors.mockReturnValue(
		new Map([
			[1, "#aaa"],
			["2", "#bbb"],
			["other", "#ccc"]
		])
	);
	signals.hasContext.mockReturnValue(true);

	const view = await viewGraph();
	assert.equal(view.title, "Tool map — Toolhub");
	assert.match(view.html, /<h1 class="page__title">Tool map<\/h1>/);
	// Populated → the empty placeholder is exactly "" : the canvas closes directly onto the
	// legend (kills the `? ""` → injected-string mutant).
	assert.match(view.html, /<div id="graph-canvas" class="graph__canvas"><\/div>\s*<div class="graph__legend"/);

	// Alpha: color via get(1); Beta: color via get("2"); size + label escaped.
	assert.match(
		view.html,
		/<span class="graph__swatch" style="background: #aaa"><\/span><span class="graph__legend-text">Alpha <span class="graph__legend-count">\(5\)<\/span><\/span>/
	);
	assert.match(
		view.html,
		/<span class="graph__swatch" style="background: #bbb"><\/span><span class="graph__legend-text">Beta <span class="graph__legend-count">\(3\)<\/span><\/span>/
	);
	// The trailing "Other" entry uses colors.get("other").
	assert.match(
		view.html,
		/<span class="graph__swatch" style="background: #ccc"><\/span><span class="graph__legend-text">Other<\/span>/
	);
	// hasContext() true → the "Fits you" entry is appended.
	assert.match(view.html, /graph__swatch--halo"><\/span><span class="graph__legend-text">Fits you<\/span>/);
	// Items joined with "" → adjacent legend items (kills the .join("") separator).
	assert.match(view.html, /<\/span><\/span><span class="graph__legend-item">/);
	// truncated → the note shows the node count.
	assert.match(view.html, /<p class="graph__note">Showing the 2 best-documented tools\.<\/p>/);
	// Populated → no empty-state paragraph.
	assert.doesNotMatch(view.html, /No richly documented tools/);

	// mount() wires the force graph onto the canvas element.
	document.body.innerHTML = '<div id="graph-canvas"></div>';
	const target = document.querySelector("#graph-canvas");
	const handle = { stop() {} };
	forceGraphMod.forceGraph.mockReturnValue(handle);
	view.mount();
	assert.equal(forceGraphMod.forceGraph.mock.calls.length, 1);
	assert.deepEqual(forceGraphMod.forceGraph.mock.calls[0], [
		target,
		g,
		{ onSelect: quickview.openQuickView, height: 560 }
	]);
	assert.equal(target.forceGraphHandle, handle);
});

test("viewGraph: an empty map shows the empty state, no truncated note, and no 'Fits you'", async () => {
	graphCore.globalGraph.mockResolvedValue({ nodes: [], truncated: false, communityMeta: [] });
	forceGraphMod.communityColors.mockReturnValue(new Map([["other", "#ccc"]]));
	signals.hasContext.mockReturnValue(false);

	const view = await viewGraph();
	assert.match(view.html, /<p class="empty">No richly documented tools are available for the map right now\.<\/p>/);
	assert.doesNotMatch(view.html, /graph__note/);
	assert.doesNotMatch(view.html, /Fits you/);
	// Legend still carries the "Other" entry.
	assert.match(view.html, /graph__legend-text">Other<\/span>/);
	// Not truncated → truncatedNote is exactly "" : the legend div closes directly onto the
	// graph div (kills the `: ""` → injected-string mutant).
	assert.match(view.html, /Other(?:<\/span>){2}<\/div>\s*<\/div>/);

	// mount() is a no-op when there are no nodes, even though the canvas exists.
	document.body.innerHTML = '<div id="graph-canvas"></div>';
	view.mount();
	assert.equal(forceGraphMod.forceGraph.mock.calls.length, 0);
});

test("viewGraph: mount() does nothing when the canvas element is absent", async () => {
	graphCore.globalGraph.mockResolvedValue({ nodes: [{ id: "a" }], truncated: false, communityMeta: [] });
	forceGraphMod.communityColors.mockReturnValue(new Map([["other", "#ccc"]]));
	signals.hasContext.mockReturnValue(false);

	const view = await viewGraph();
	document.body.innerHTML = ""; // no #graph-canvas
	view.mount();
	assert.equal(forceGraphMod.forceGraph.mock.calls.length, 0);
});

test("viewGraph: a missing communityMeta yields only the 'Other' legend entry", async () => {
	// communityMeta is undefined → the `|| []` guard must produce no per-community items;
	// an injected non-empty fallback array would render a phantom "(undefined)" entry.
	graphCore.globalGraph.mockResolvedValue({ nodes: [{ id: "a" }], truncated: false });
	forceGraphMod.communityColors.mockReturnValue(new Map([["other", "#ccc"]]));
	signals.hasContext.mockReturnValue(false);

	const view = await viewGraph();
	assert.match(view.html, /graph__legend-text">Other<\/span>/);
	assert.doesNotMatch(view.html, /\(undefined\)/);
});
