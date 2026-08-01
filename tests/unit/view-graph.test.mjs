// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test, vi, beforeEach } from "vitest";
// backend graph payload (network), communityColors/forceGraph (canvas), openQuickView and hasContext
// are all mocked so the legend HTML + mount() wiring are exercised deterministically. esc stays real.
import { viewGraph } from "../../public_html/views/graph.js";
import * as api from "../../public_html/lib/core/api.js";
import * as forceGraphMod from "../../public_html/lib/organisms/force-graph.js";
import * as quickview from "../../public_html/lib/organisms/quickview.js";
import * as signals from "../../public_html/lib/core/signals.js";

vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, backendGetJson: vi.fn() };
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
		nodes: [
			{ id: "a", projects: ["Wikipedia"], languages: ["en"] },
			{ id: "b", projects: ["Commons"], languages: ["fr"] }
		],
		edges: [],
		truncated: true,
		communityMeta: [
			{ id: 1, label: "Alpha", size: 5 },
			{ id: 2, label: "Beta", size: 3 }
		]
	};
	api.backendGetJson.mockResolvedValue(g);
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
	assert.match(view.html, /Preparing the tool map/);
	assert.match(view.html, /data-graph-controls/);
	assert.match(view.html, /data-graph-action="zoom-in"/);
	assert.match(view.html, /data-graph-action="zoom-out"/);
	assert.match(view.html, /data-graph-action="fit"/);
	assert.match(view.html, /data-graph-zoom[^>]*>100%<\/span>/);

	// The router can commit the shell before the request resolves; mount hydrates it in place.
	document.body.innerHTML = view.html;
	const handle = { stop() {}, zoomIn: vi.fn(), zoomOut: vi.fn(), fitView: vi.fn(), setFilters: vi.fn() };
	forceGraphMod.forceGraph.mockReturnValue(handle);
	view.mount();
	await vi.waitFor(() => assert.equal(forceGraphMod.forceGraph.mock.calls.length, 1));
	const target = document.querySelector("#graph-canvas");
	const hydrated = document.body.innerHTML;
	assert.match(hydrated, /data-graph-filter="projects"/);
	assert.match(hydrated, /<option value="Commons">Commons<\/option>/);
	assert.match(hydrated, /data-graph-filter="languages"/);
	assert.match(hydrated, /<option value="fr">fr<\/option>/);
	assert.match(
		hydrated,
		/<span class="graph__swatch" style="background: #aaa"><\/span><span class="graph__legend-text">Alpha <span class="graph__legend-count">\(5\)<\/span><\/span>/
	);
	assert.match(
		hydrated,
		/<span class="graph__swatch" style="background: #bbb"><\/span><span class="graph__legend-text">Beta <span class="graph__legend-count">\(3\)<\/span><\/span>/
	);
	assert.match(hydrated, /graph__legend-text">Other<\/span>/);
	assert.match(hydrated, /graph__swatch--halo"><\/span><span class="graph__legend-text">Fits you<\/span>/);
	assert.match(hydrated, /<\/span><\/span><span class="graph__legend-item">/);
	assert.equal(document.querySelector("[data-graph-note]")?.textContent, "Showing the 2 best-documented tools.");
	assert.equal(document.querySelector("[data-graph-empty]")?.hidden, true);
	assert.equal(forceGraphMod.forceGraph.mock.calls.length, 1);
	assert.deepEqual(forceGraphMod.forceGraph.mock.calls[0], [
		target,
		g,
		{ onSelect: quickview.openQuickView, height: 560 }
	]);
	assert.equal(target.forceGraphHandle, handle);
	document.querySelector('[data-graph-action="zoom-in"]')?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
	document.querySelector('[data-graph-action="zoom-out"]')?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
	document.querySelector('[data-graph-action="fit"]')?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
	assert.equal(handle.zoomIn.mock.calls.length, 1);
	assert.equal(handle.zoomOut.mock.calls.length, 1);
	assert.equal(handle.fitView.mock.calls.length, 1);
	const projectFilter = document.querySelector('[data-graph-filter="projects"]');
	projectFilter.value = "Commons";
	projectFilter.dispatchEvent(new Event("change", { bubbles: true }));
	assert.deepEqual(handle.setFilters.mock.calls[0], [{ projects: "Commons", languages: "" }]);
});

test("viewGraph: an empty map shows the empty state, no truncated note, and no 'Fits you'", async () => {
	forceGraphMod.communityColors.mockReturnValue(new Map([["other", "#ccc"]]));
	signals.hasContext.mockReturnValue(false);

	api.backendGetJson.mockResolvedValue({ nodes: [], edges: [], truncated: false, communityMeta: [] });
	const view = await viewGraph();
	assert.match(view.html, /<p class="graph__note" data-graph-note hidden><\/p>/);
	assert.doesNotMatch(view.html, /Fits you/);
	document.body.innerHTML = view.html;
	view.mount();
	await vi.waitFor(() => assert.equal(document.querySelector(".graph")?.getAttribute("aria-busy"), null));
	assert.equal(document.querySelector("[data-graph-empty]")?.hidden, false);
	assert.equal(document.querySelector("[data-graph-legend]")?.hidden, true);
	assert.equal(forceGraphMod.forceGraph.mock.calls.length, 0);
});

test("viewGraph: changing node count or grouping reloads the graph payload", async () => {
	const initial = { nodes: [{ id: "a" }], edges: [], communityMeta: [], groupMeta: [], truncated: false };
	const grouped = {
		nodes: [{ id: "a", projects: ["Commons"] }],
		edges: [],
		communityMeta: [],
		groupMeta: [{ id: 0, label: "Commons", size: 1 }],
		truncated: false
	};
	api.backendGetJson.mockResolvedValueOnce(initial).mockResolvedValueOnce(grouped);
	forceGraphMod.communityColors.mockReturnValue(new Map([["other", "#ccc"]]));
	const firstHandle = { stop: vi.fn(), zoomIn: vi.fn(), zoomOut: vi.fn(), fitView: vi.fn(), setFilters: vi.fn() };
	const secondHandle = { stop: vi.fn(), zoomIn: vi.fn(), zoomOut: vi.fn(), fitView: vi.fn(), setFilters: vi.fn() };
	forceGraphMod.forceGraph.mockReturnValueOnce(firstHandle).mockReturnValueOnce(secondHandle);

	const view = await viewGraph();
	document.body.innerHTML = view.html;
	view.mount();
	await vi.waitFor(() => assert.equal(forceGraphMod.forceGraph.mock.calls.length, 1));
	const groupSelect = document.querySelector('[data-graph-option="groupBy"]');
	groupSelect.value = "language";
	groupSelect.dispatchEvent(new Event("change", { bubbles: true }));
	await vi.waitFor(() => assert.equal(forceGraphMod.forceGraph.mock.calls.length, 2));

	assert.equal(firstHandle.stop.mock.calls.length, 1);
	assert.equal(forceGraphMod.forceGraph.mock.calls.length, 2);
	assert.equal(api.backendGetJson.mock.calls[1][0], "/v1/graph/?limit=250&groupBy=language");
});

test("viewGraph: disables grouping choices without enough metadata", async () => {
	api.backendGetJson.mockResolvedValue({
		nodes: [{ id: "a" }],
		edges: [],
		communityMeta: [],
		groupMeta: [],
		groupingMeta: [
			{ id: "similarity", covered: 1, total: 1, enabled: true },
			{ id: "project", covered: 1, total: 1, enabled: false }
		],
		truncated: false
	});
	forceGraphMod.communityColors.mockReturnValue(new Map([["other", "#ccc"]]));
	forceGraphMod.forceGraph.mockReturnValue({
		stop: vi.fn(),
		zoomIn: vi.fn(),
		zoomOut: vi.fn(),
		fitView: vi.fn(),
		setFilters: vi.fn()
	});

	const view = await viewGraph();
	document.body.innerHTML = view.html;
	view.mount();
	await vi.waitFor(() => assert.equal(forceGraphMod.forceGraph.mock.calls.length, 1));

	const project = /** @type {HTMLOptionElement} */ (
		document.querySelector('[data-graph-option="groupBy"] option[value="project"]')
	);
	assert.equal(project.disabled, true);
	assert.equal(project.title, "1 of 1 tools have this metadata");
});

test("viewGraph: mount() does nothing when the canvas element is absent", async () => {
	api.backendGetJson.mockResolvedValue({ nodes: [{ id: "a" }], truncated: false, communityMeta: [] });
	forceGraphMod.communityColors.mockReturnValue(new Map([["other", "#ccc"]]));
	signals.hasContext.mockReturnValue(false);

	const view = await viewGraph();
	document.body.innerHTML = ""; // no #graph-canvas
	view.mount();
	assert.equal(forceGraphMod.forceGraph.mock.calls.length, 0);
});

test("viewGraph: a failed initial request shows an in-map retry without blanking the route", async () => {
	api.backendGetJson
		.mockRejectedValueOnce(new Error("offline"))
		.mockResolvedValueOnce({ nodes: [{ id: "recovered" }], edges: [], communityMeta: [], truncated: false });
	forceGraphMod.communityColors.mockReturnValue(new Map([["other", "#ccc"]]));
	forceGraphMod.forceGraph.mockReturnValue({
		stop: vi.fn(),
		zoomIn: vi.fn(),
		zoomOut: vi.fn(),
		fitView: vi.fn(),
		setFilters: vi.fn()
	});

	const view = await viewGraph();
	document.body.innerHTML = view.html;
	view.mount();
	await vi.waitFor(() =>
		assert.match(document.querySelector("#graph-canvas")?.textContent || "", /could not be loaded/i)
	);
	assert.equal(document.querySelector("h1")?.textContent, "Tool map");
	document.querySelector('[data-graph-action="retry"]')?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
	await vi.waitFor(() => assert.equal(forceGraphMod.forceGraph.mock.calls.length, 1));
	assert.equal(api.backendGetJson.mock.calls.length, 2);
});

test("viewGraph: a missing communityMeta yields only the 'Other' legend entry", async () => {
	// communityMeta is undefined → the `|| []` guard must produce no per-community items;
	// an injected non-empty fallback array would render a phantom "(undefined)" entry.
	api.backendGetJson.mockResolvedValue({ nodes: [{ id: "a" }], edges: [], truncated: false });
	forceGraphMod.communityColors.mockReturnValue(new Map([["other", "#ccc"]]));
	signals.hasContext.mockReturnValue(false);

	const view = await viewGraph();
	document.body.innerHTML = view.html;
	view.mount();
	await vi.waitFor(() => assert.equal(forceGraphMod.forceGraph.mock.calls.length, 1));
	assert.match(document.body.innerHTML, /graph__legend-text">Other<\/span>/);
	assert.doesNotMatch(document.body.innerHTML, /\(undefined\)/);
});
