// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc } from "../core/dom.js";
import { fmt } from "../core/i18n.js";

/* ---- Search / Browse (T2): facets + sort + pagination ------------------ */
export const FACET_BUCKET_LIMIT = 10;
// Facet groups we surface (a subset of the API's 11), in display order.
export const FACET_GROUPS = [
	{ field: "tool_type", label: "Tool type" },
	{ field: "keywords", label: "Keywords" },
	{ field: "audiences", label: "Audience" },
	{ field: "tasks", label: "Task" },
	{ field: "ui_language", label: "Interface language" },
	{ field: "license", label: "License" },
	{ field: "wiki", label: "Works on wiki" }
];
export function renderFacetGroup(g, facets, selected) {
	const wrap = facets && facets[`_filter_${g.field}`];
	const inner = wrap && wrap[g.field];
	if (!inner) return "";
	const param = inner.meta && inner.meta.param;
	const buckets = (inner.buckets || []).filter((b) => b.key !== "--" && b.doc_count > 0).slice(0, FACET_BUCKET_LIMIT);
	if (buckets.length === 0 || !param) return "";
	const rows = buckets
		.map((b) => {
			const checked = selected.has(`${param}=${b.key}`) ? " checked" : "";
			return `<label class="facet"><input type="checkbox" data-facet="${esc(param)}" value="${esc(b.key)}"${checked}> <span${dirAttrs(b.key)}>${esc(b.key)}</span> <span class="facet__n">${fmt(b.doc_count)}</span></label>`;
		})
		.join("");
	return `<div class="facet-group"><h2 class="facet-group__title">${esc(g.label)}</h2>${rows}</div>`;
}
