// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, dirAttrs, esc } from "../lib/core/dom.js";
import { countLabel } from "../lib/core/i18n.js";
import { expOn } from "../lib/core/session.js";
import { apiGet, normalizeTool } from "../lib/core/api.js";
import { FACET_GROUPS, renderFacetGroup } from "../lib/molecules/facet-group.js";
import { renderPager } from "../lib/molecules/pager.js";
import { toolCard } from "../lib/organisms/tool-card.js";

export const PAGE_SIZE = 12;
export async function viewSearch() {
	const usp = new URLSearchParams(location.hash.split("?")[1] || "");
	const q = usp.get("q") || "";
	const page = Math.max(1, parseInt(usp.get("page")) || 1);
	const exp = expOn();
	const defaultSort = exp ? "relevance" : "recent";
	const requestedSort = usp.get("sort") || defaultSort;
	const allowedSorts = exp ? ["relevance", "recent", "name", "views"] : ["recent", "name"];
	const sort = allowedSorts.includes(requestedSort) ? requestedSort : defaultSort;
	const ordering = sort === "name" ? "name" : sort === "recent" ? "-modified_date" : "";

	// Live API params: q, paging, ordering + every *__term facet filter from the URL.
	const api = new URLSearchParams();
	if (q) api.set("q", q);
	api.set("page", String(page));
	api.set("page_size", String(PAGE_SIZE));
	if (ordering) api.set("ordering", ordering);
	const selected = new Set();
	for (const [k, v] of usp.entries()) {
		if (k.endsWith("__term")) { api.append(k, v); selected.add(k + "=" + v); }
	}

	const data = await apiGet("/search/tools/", api);
	const results = (data.results || []).map(normalizeTool);
	if (sort === "views") results.sort((a, b) => (b.weeklyViews - a.weeklyViews) || a.title.localeCompare(b.title));
	const total = data.count || 0;
	const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
	const facetHTML = FACET_GROUPS.map((g) => renderFacetGroup(g, data.facets, selected)).join("");
	const pagerHTML = renderPager(page, pages);

	const sortOpts = (exp ? '<option value="relevance">Most relevant</option>' : "") +
		'<option value="recent">Recently updated</option><option value="name">Name (A–Z)</option>' +
		(exp ? '<option value="views">Popular this week</option>' : "");
	const resultsHTML = results.length ? `<ul class="card-grid grid-tools" role="list">${results.map((t, i) => `<li>${toolCard(t, sort === "views" ? { rank: ((page - 1) * PAGE_SIZE) + i + 1, popular: true } : {})}</li>`).join("")}</ul>` : '<p class="empty">No tools match these filters.</p>';

	const html = `
	<div class="container page">
		<h1 class="page__title">Browse tools</h1>
		<div class="browse">
			<aside class="facets" aria-label="Filters">
				<form data-facet-q role="search">
					<label for="facet-q" class="skip-label">Search within tools</label>
					<input id="facet-q" class="facets__search" type="search" placeholder="Search tools…" autocomplete="off" value="${esc(q)}" />
				</form>
				${facetHTML || '<p class="facet__empty">No filters available.</p>'}
				<a class="btn btn--outline facets__reset" href="#/search">Clear filters</a>
			</aside>
			<div class="browse__main">
				<div class="browse__bar">
					<span class="browse__count" aria-live="polite">${esc(countLabel(total, "tool", "tools"))}${q ? ` for &ldquo;<span${dirAttrs(q)}>${esc(q)}</span>&rdquo;` : ""}</span>
					<label class="sort"><span class="skip-label">Sort by</span><select id="sort">${sortOpts}</select></label>
				</div>
				${resultsHTML}
				<nav class="pager" aria-label="Pagination">${pagerHTML}</nav>
			</div>
		</div>`;

	function mount() {
		$("#sort").value = sort;
		const navigate = (extra) => {
			const u = new URLSearchParams();
			const qv = $("#facet-q").value.trim(); if (qv) u.set("q", qv);
			$$(".facets input[type=checkbox]:checked").forEach((c) => u.append(c.getAttribute("data-facet"), c.value));
			const sv = $("#sort").value; if (sv && sv !== defaultSort) u.set("sort", sv);
			if (extra && extra.page > 1) u.set("page", String(extra.page));
			location.hash = "#/search" + (u.toString() ? "?" + u.toString() : "");
		};
		$(".facets").addEventListener("change", () => navigate({}));
		$("#sort").addEventListener("change", () => navigate({}));
		$("[data-facet-q]").addEventListener("submit", (e) => { e.preventDefault(); navigate({}); });
		$(".pager").addEventListener("click", (e) => {
			const b = e.target.closest("[data-page]"); if (!b) return;
			navigate({ page: parseInt(b.getAttribute("data-page")) });
		});
	}
	return { title: q ? `“${q}” — Toolhub` : "Browse tools — Toolhub", html, mount };
}
