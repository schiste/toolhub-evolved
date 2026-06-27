// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, $input, dirAttrs, esc } from "../lib/core/dom.js";
import { countLabel, fmt } from "../lib/core/i18n.js";
import { expOn } from "../lib/core/session.js";
import { apiGet, normalizeTool } from "../lib/core/api.js";
import { navigateTo } from "../lib/core/routing.js";
import { attachEndorsements, completeness, rankFitsFirst } from "../lib/core/signals.js";
import { button } from "../lib/atoms/button.js";
import { FACET_GROUPS, renderFacetGroup } from "../lib/molecules/facet-group.js";
import { renderPager } from "../lib/molecules/pager.js";
import { toolCard } from "../lib/organisms/tool-card.js";

export const PAGE_SIZE_OPTIONS = [12, 24, 48];
export const DEFAULT_PAGE_SIZE = 24;
const CLIENT_STATUS_FILTERS = [
	{ value: "deprecated", label: "Deprecated", match: (/** @type {Tool} */ t) => t.deprecated },
	{ value: "experimental", label: "Experimental", match: (/** @type {Tool} */ t) => t.experimental }
];
const CLIENT_STATUS_VALUES = new Set(CLIENT_STATUS_FILTERS.map((s) => s.value));

/** @param {string | null} value */
function activePageSize(value) {
	// Stryker disable next-line StringLiteral: when value is null the fallback is parsed by Number.parseInt; "" and any non-numeric sentinel both yield NaN (→ default page size) — equivalent.
	const parsed = Number.parseInt(value ?? "", 10);
	return PAGE_SIZE_OPTIONS.includes(parsed) ? parsed : DEFAULT_PAGE_SIZE;
}

/** @param {string | null} value */
function activeClientStatuses(value) {
	return new Set(
		// Stryker disable next-line StringLiteral: when value is null the fallback string is split/filtered; "" and any sentinel both produce no valid status tokens — equivalent.
		String(value || "")
			.split(",")
			.map((s) => s.trim())
			.filter((s) => CLIENT_STATUS_VALUES.has(s))
	);
}

/**
 * @param {string | null} ordering
 * @param {string} fallback
 * @returns {string}
 */
function sortFromOfficialOrdering(ordering, fallback) {
	if (ordering === "-modified_date") return "recent";
	if (ordering === "name") return "name";
	// Stryker disable next-line ConditionalExpression,EqualityOperator,StringLiteral: "relevance" is only ever in the allow-list when experiments are on, where it is also the default sort, so mapping -score→relevance is indistinguishable from the fallback through viewSearch — equivalent.
	if (ordering === "-score") return "relevance";
	return fallback;
}

/** @param {Set<string>} selectedStatuses */
function renderStatusFacetGroup(selectedStatuses) {
	const rows = CLIENT_STATUS_FILTERS.map((s) => {
		const checked = selectedStatuses.has(s.value) ? " checked" : "";
		return `<label class="facet"><input type="checkbox" data-client-status="${s.value}"${checked}> <span>${esc(s.label)}</span></label>`;
	}).join("");
	return `<div class="facet-group"><h2 class="facet-group__title">Status</h2>${rows}</div>`;
}

/**
 * Resolve the active sort + upstream ordering from the URL, clamped to the
 * experiment-gated allow-list (out-of-list requests fall back to the default).
 * @param {URLSearchParams} usp
 * @param {boolean} exp
 * @returns {{ sort: string, ordering: string, defaultSort: string }}
 */
function resolveSort(usp, exp) {
	const defaultSort = exp ? "relevance" : "recent";
	const requestedSort = usp.get("sort") || sortFromOfficialOrdering(usp.get("ordering"), defaultSort);
	// defaultSort is referenced (not re-typed) so the allow-list entry that equals the
	// default cannot drift from it; removing the default from the list is a no-op since
	// an out-of-list request already resolves to defaultSort.
	const allowedSorts = exp ? [defaultSort, "recent", "name", "views", "complete"] : [defaultSort, "name", "complete"];
	const sort = allowedSorts.includes(requestedSort) ? requestedSort : defaultSort;
	const ordering = sort === "name" ? "name" : sort === "recent" ? "-modified_date" : "";
	return { sort, ordering, defaultSort };
}
export async function viewSearch() {
	// Stryker disable next-line StringLiteral: when location.search is empty the fallback feeds URLSearchParams; "" yields no params and any sentinel yields a single unread key, so reads (q, page, *__term, …) are unaffected — equivalent.
	const usp = new URLSearchParams(location.search || "");
	const q = usp.get("q") || "";
	// Stryker disable next-line StringLiteral: when the page param is absent the fallback is parsed; "" and any sentinel both yield NaN (→ page 1) — equivalent.
	const page = Math.max(1, Number.parseInt(usp.get("page") ?? "", 10) || 1);
	const pageSize = activePageSize(usp.get("page_size"));
	const exp = expOn();
	const { sort, ordering, defaultSort } = resolveSort(usp, exp);
	const clientStatuses = activeClientStatuses(usp.get("status"));

	// Live API params: q, paging, ordering + every *__term facet filter from the URL.
	const api = new URLSearchParams();
	if (q) api.set("q", q);
	api.set("page", String(page));
	api.set("page_size", String(pageSize));
	if (ordering) api.set("ordering", ordering);
	const selected = new Set();
	for (const [k, v] of usp.entries()) {
		if (k.endsWith("__term")) {
			api.append(k, v);
			selected.add(`${k}=${v}`);
		}
	}

	const data = await apiGet("/search/tools/", /** @type {Record<string, string>} */ (/** @type {unknown} */ (api)));
	/** @type {Tool[]} */
	let results = (data.results || []).map((/** @type {any} */ tool) => normalizeTool(tool));
	await attachEndorsements(results);
	// Client-side prototype until backend status faceting + result counts exist (#57/#58).
	if (clientStatuses.size > 0) {
		results = results.filter((t) => CLIENT_STATUS_FILTERS.some((s) => clientStatuses.has(s.value) && s.match(t)));
	}
	if (sort === "views") results.sort((a, b) => b.weeklyViews - a.weeklyViews || a.title.localeCompare(b.title));
	if (sort === "complete") {
		results.sort((a, b) => completeness(b).filled - completeness(a).filled || a.title.localeCompare(b.title));
	}
	results = rankFitsFirst(results);
	const total = data.count || 0;
	const pages = Math.max(1, Math.ceil(total / pageSize));
	const facetHTML = FACET_GROUPS.map((g) => renderFacetGroup(g, data.facets, selected)).join("");
	const statusFacetHTML = renderStatusFacetGroup(clientStatuses);
	const pagerHTML = renderPager(page, pages);
	// Stryker disable next-line ConditionalExpression,EqualityOperator: firstResult/lastResult are only read in the results.length>0 branch of countHTML, where this guard is already true, so the empty-case value is never observed — equivalent.
	const firstResult = results.length > 0 ? (page - 1) * pageSize + 1 : 0;
	const lastResult = firstResult + results.length - 1;
	const countHTML =
		clientStatuses.size > 0
			? results.length > 0
				? `Showing ${esc(fmt(results.length))} on this page of ${esc(countLabel(total, "tool", "tools"))}`
				: `No visible tools on this page of ${esc(countLabel(total, "tool", "tools"))}`
			: results.length > 0
				? `Showing ${esc(fmt(firstResult))}-${esc(fmt(lastResult))} of ${esc(countLabel(total, "tool", "tools"))}`
				: esc(countLabel(total, "tool", "tools"));
	const countNoteHTML =
		clientStatuses.size > 0 ? ' <span class="browse__count-note">filtered in your browser</span>' : "";

	const sortOpts = `${
		exp ? '<option value="relevance">Most relevant</option>' : ""
	}<option value="recent">Recently updated</option><option value="name">Name (A–Z)</option>${
		exp ? '<option value="views">Popular this week</option>' : ""
	}<option value="complete">Most complete</option>`;
	const pageSizeOpts = PAGE_SIZE_OPTIONS.map((size) => `<option value="${size}">${size} per page</option>`).join("");
	const resultsHTML =
		results.length > 0
			? `<ul class="card-grid grid-tools" role="list">${results.map((t, i) => `<li>${toolCard(t, sort === "views" ? { rank: (page - 1) * pageSize + i + 1, popular: true } : {})}</li>`).join("")}</ul>`
			: '<p class="empty">No tools match these filters.</p>';

	// Stryker disable next-line StringLiteral: button() defaults variant to "outline", so mutating this explicit "outline" to "" yields identical markup — equivalent.
	const clearFiltersBtn = button("Clear filters", { variant: "outline", href: "/search", cls: "facets__reset" });
	const html = `
	<div class="container page">
		<h1 class="page__title">Browse tools</h1>
		<div class="browse">
			<aside class="facets" aria-label="Filters">
				<form data-facet-q role="search">
					<label for="facet-q" class="skip-label">Search within tools</label>
					<input id="facet-q" class="facets__search" type="search" placeholder="Search tools…" autocomplete="off" value="${esc(q)}" />
				</form>
				${statusFacetHTML}
				${facetHTML || '<p class="facet__empty">No filters available.</p>'}
				${clearFiltersBtn}
			</aside>
			<div class="browse__main">
				<div class="browse__bar">
					<span class="browse__count" aria-live="polite">${countHTML}${q ? ` for &ldquo;<span${dirAttrs(q)}>${esc(q)}</span>&rdquo;` : ""}${countNoteHTML}</span>
					<span class="browse__controls">
						<label class="sort"><span class="skip-label">Results per page</span><select id="page-size">${pageSizeOpts}</select></label>
						<label class="sort"><span class="skip-label">Sort by</span><select id="sort">${sortOpts}</select></label>
					</span>
				</div>
				${resultsHTML}
				<nav class="pager" aria-label="Pagination">${pagerHTML}</nav>
			</div>
		</div>
	</div>`;

	function mount() {
		/** @type {HTMLInputElement} */ ($input("#sort")).value = sort;
		/** @type {HTMLInputElement} */ ($input("#page-size")).value = String(pageSize);
		/** @param {{ page?: number }} extra */
		const navigate = (extra) => {
			const u = new URLSearchParams();
			const qv = /** @type {HTMLInputElement} */ ($input("#facet-q")).value.trim();
			if (qv) u.set("q", qv);
			$$(".facets input[type=checkbox][data-facet]:checked").forEach((c) =>
				u.append(
					/** @type {string} */ (c.getAttribute("data-facet")),
					/** @type {HTMLInputElement} */ (c).value
				)
			);
			const statuses = $$(".facets input[type=checkbox][data-client-status]:checked").map((c) =>
				c.getAttribute("data-client-status")
			);
			if (statuses.length > 0) u.set("status", statuses.join(","));
			const sv = /** @type {HTMLInputElement} */ ($input("#sort")).value;
			if (sv && sv !== defaultSort) u.set("sort", sv);
			const psv = activePageSize(/** @type {HTMLInputElement} */ ($input("#page-size")).value);
			if (psv !== DEFAULT_PAGE_SIZE) u.set("page_size", String(psv));
			if (extra.page && extra.page > 1) u.set("page", String(extra.page));
			navigateTo(`/search${u.toString() ? `?${u.toString()}` : ""}`);
		};
		/** @type {HTMLElement} */ ($(".facets")).addEventListener("change", () => navigate({}));
		/** @type {HTMLInputElement} */ ($input("#sort")).addEventListener("change", () => navigate({}));
		/** @type {HTMLInputElement} */ ($input("#page-size")).addEventListener("change", () => navigate({}));
		/** @type {HTMLElement} */ ($("[data-facet-q]")).addEventListener("submit", (e) => {
			e.preventDefault();
			navigate({});
		});
		/** @type {HTMLElement} */ ($(".pager")).addEventListener("click", (e) => {
			const b = /** @type {EventTarget} */ (e.target).closest("[data-page]");
			if (!b) return;
			navigate({ page: Number.parseInt(/** @type {string} */ (b.getAttribute("data-page")), 10) });
		});
	}
	return { title: q ? `“${q}” — Toolhub` : "Browse tools — Toolhub", html, mount };
}
