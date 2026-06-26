// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { renderFacetGroup, FACET_BUCKET_LIMIT, FACET_GROUPS } from "../../public_html/lib/molecules/facet-group.js";

const G = { field: "tool_type", label: "Tool type" };

test("renderFacetGroup() renders checked/unchecked rows, drops '--' and zero-count buckets", () => {
	const facets = {
		_filter_tool_type: {
			tool_type: {
				meta: { param: "tool_type" },
				buckets: [
					{ key: "web app", doc_count: 1234 },
					{ key: "bot", doc_count: 5 },
					{ key: "--", doc_count: 9 },
					{ key: "zero", doc_count: 0 }
				]
			}
		}
	};
	assert.equal(
		renderFacetGroup(G, facets, new Set(["tool_type=bot"])),
		'<div class="facet-group"><h2 class="facet-group__title">Tool type</h2><label class="facet"><input type="checkbox" data-facet="tool_type" value="web app"> <span dir="auto">web app</span> <span class="facet__n">1,234</span></label><label class="facet"><input type="checkbox" data-facet="tool_type" value="bot" checked> <span dir="auto">bot</span> <span class="facet__n">5</span></label></div>'
	);
});

test("renderFacetGroup() empty when the filter wrapper is missing", () => {
	assert.equal(renderFacetGroup(G, {}, new Set()), "");
});

test("renderFacetGroup() empty when facets is null", () => {
	assert.equal(renderFacetGroup(G, null, new Set()), "");
});

test("renderFacetGroup() empty when the inner field object is missing", () => {
	assert.equal(renderFacetGroup(G, { _filter_tool_type: {} }, new Set()), "");
});

test("renderFacetGroup() empty when param meta is missing", () => {
	const facets = { _filter_tool_type: { tool_type: { buckets: [{ key: "a", doc_count: 2 }] } } };
	assert.equal(renderFacetGroup(G, facets, new Set()), "");
});

test("renderFacetGroup() empty when all buckets are filtered out", () => {
	const facets = {
		_filter_tool_type: {
			tool_type: {
				meta: { param: "p" },
				buckets: [
					{ key: "--", doc_count: 3 },
					{ key: "z", doc_count: 0 }
				]
			}
		}
	};
	assert.equal(renderFacetGroup(G, facets, new Set()), "");
});

test("renderFacetGroup() caps the bucket list at FACET_BUCKET_LIMIT (10)", () => {
	const buckets = Array.from({ length: 13 }, (_, i) => ({ key: `k${i}`, doc_count: 20 - i }));
	const facets = { _filter_tool_type: { tool_type: { meta: { param: "p" }, buckets } } };
	const row = (key, n) =>
		`<label class="facet"><input type="checkbox" data-facet="p" value="${key}"> <span dir="auto">${key}</span> <span class="facet__n">${n}</span></label>`;
	let expected = '<div class="facet-group"><h2 class="facet-group__title">Tool type</h2>';
	for (let i = 0; i < 10; i++) expected += row(`k${i}`, 20 - i);
	expected += "</div>";
	assert.equal(renderFacetGroup(G, facets, new Set()), expected);
});

test("FACET_BUCKET_LIMIT and FACET_GROUPS exports", () => {
	assert.equal(FACET_BUCKET_LIMIT, 10);
	assert.deepEqual(FACET_GROUPS, [
		{ field: "tool_type", label: "Tool type" },
		{ field: "keywords", label: "Keywords" },
		{ field: "audiences", label: "Audience" },
		{ field: "tasks", label: "Task" },
		{ field: "ui_language", label: "Interface language" },
		{ field: "license", label: "License" },
		{ field: "wiki", label: "Works on wiki" }
	]);
});
