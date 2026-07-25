// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc } from "../core/dom.js";
import { fmt, t } from "../core/i18n.js";

/* ---- Search / Browse (T2): facets + sort + pagination ------------------ */
export const FACET_BUCKET_LIMIT = 10;
// Facet groups we surface (a subset of the API's 11), in display order.
export const FACET_GROUPS = [
	{ field: "tool_type", label: t("facetGroup.toolType", "Tool type") },
	{ field: "keywords", label: t("facetGroup.keywords", "Keywords") },
	{ field: "audiences", label: t("facetGroup.audience", "Audience") },
	{ field: "tasks", label: t("facetGroup.task", "Task") },
	{ field: "ui_language", label: t("facetGroup.interfaceLanguage", "Interface language") },
	{ field: "license", label: t("facetGroup.license", "License") },
	{ field: "wiki", label: t("facetGroup.worksOnWiki", "Works on wiki") }
];
/**
 * @typedef {object} FacetInner
 * @property {{ param?: string }} [meta]
 * @property {{ key: string; doc_count: number }[]} [buckets]
 */
/**
 * @param {{ field: string; label: string }} g
 * @param {Record<string, Record<string, FacetInner>> | null | undefined} facets
 * @param {Set<string>} selected
 * @returns {string}
 */
export function renderFacetGroup(g, facets, selected) {
	const wrap = facets && facets[`_filter_${g.field}`];
	const inner = wrap && wrap[g.field];
	if (!inner) return "";
	const param = inner.meta && inner.meta.param;
	// Stryker disable next-line ArrayDeclaration: the `|| []` fallback only fires when inner.buckets is missing; a non-empty fallback's sentinel string has no `.key`/`.doc_count`, so `.filter(...)` drops it and the result is the same empty list — equivalent.
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
