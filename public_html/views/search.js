// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, $input, dirAttrs, esc } from "../lib/core/dom.js";
import { countLabel, fmt, t } from "../lib/core/i18n.js";
import { expOn } from "../lib/core/session.js";
import { apiGet, backendGetJson, localToolBase, normalizeTool } from "../lib/core/api.js";
import { navigateTo } from "../lib/core/routing.js";
import { attachEndorsements, completeness, rankFitsFirst } from "../lib/core/signals.js";
import { button } from "../lib/atoms/button.js";
import { FACET_GROUPS, renderFacetGroup } from "../lib/molecules/facet-group.js";
import { renderPager } from "../lib/molecules/pager.js";
import { toolCard } from "../lib/organisms/tool-card.js";

export const PAGE_SIZE_OPTIONS = [12, 24, 48];
export const DEFAULT_PAGE_SIZE = 24;
const CLIENT_STATUS_FILTERS = [
	{
		value: "deprecated",
		label: t("search.deprecated", "Deprecated"),
		match: (/** @type {Tool} */ t) => t.deprecated
	},
	{
		value: "experimental",
		label: t("search.experimental", "Experimental"),
		match: (/** @type {Tool} */ t) => t.experimental
	}
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
	return `<div class="facet-group"><h2 class="facet-group__title">${t("search.status", "Status")}</h2>${rows}</div>`;
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
	const allowedSorts = exp ? [defaultSort, "recent", "name", "complete"] : [defaultSort, "name", "complete"];
	const sort = allowedSorts.includes(requestedSort) ? requestedSort : defaultSort;
	const ordering = sort === "name" ? "name" : sort === "recent" ? "-modified_date" : "";
	return { sort, ordering, defaultSort };
}
const LOCAL_STRIP_CAP = 12;
/**
 * Federated search, phase 1 (docs/PRODUCTION.md P5): tools registered on this
 * site, matching the same query, deduped by name against the live page. The
 * live Toolhub results always come straight from the upstream API; this strip
 * only ever adds clearly-provenanced local records. Any backend failure yields
 * an empty strip — local records never block live search.
 * @param {string} q
 * @param {Tool[]} live
 * @returns {Promise<Tool[]>}
 */
async function localResults(q, live) {
	let data;
	try {
		data = await backendGetJson(`/v1/search/tools/?q=${encodeURIComponent(q)}`);
	} catch {
		return [];
	}
	const seen = new Set(live.map((tool) => tool.name));
	return (data && Array.isArray(data.results) ? data.results : [])
		.filter((/** @type {any} */ rec) => rec && rec.name && !seen.has(rec.name))
		.slice(0, LOCAL_STRIP_CAP)
		.map((/** @type {any} */ rec) => localToolBase(rec.name, rec));
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
	// Federated strip (page 1 only — the strip is additive, never paginated).
	const local = page === 1 ? await localResults(q, results) : [];
	await attachEndorsements(results);
	// Client-side prototype until backend status faceting + result counts exist (#57/#58).
	if (clientStatuses.size > 0) {
		results = results.filter((t) => CLIENT_STATUS_FILTERS.some((s) => clientStatuses.has(s.value) && s.match(t)));
	}
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
				? t("search.showingOnPage", "Showing {count} on this page of {total}", {
						count: esc(fmt(results.length)),
						total: esc(countLabel(total, t("search.toolOne", "tool"), t("search.toolOther", "tools")))
					})
				: t("search.noVisibleOnPage", "No visible tools on this page of {total}", {
						total: esc(countLabel(total, t("search.toolOne", "tool"), t("search.toolOther", "tools")))
					})
			: results.length > 0
				? t("search.showingRange", "Showing {first}-{last} of {total}", {
						first: esc(fmt(firstResult)),
						last: esc(fmt(lastResult)),
						total: esc(countLabel(total, t("search.toolOne", "tool"), t("search.toolOther", "tools")))
					})
				: esc(countLabel(total, t("search.toolOne", "tool"), t("search.toolOther", "tools")));
	const countNoteHTML =
		clientStatuses.size > 0
			? ` <span class="browse__count-note">${t("search.filteredInBrowser", "filtered in your browser")}</span>`
			: "";

	const sortOpts = `${
		exp ? `<option value="relevance">${t("search.mostRelevant", "Most relevant")}</option>` : ""
	}<option value="recent">${t("search.recentlyUpdated", "Recently updated")}</option><option value="name">${t(
		"search.nameAZ",
		"Name (A–Z)"
	)}</option><option value="complete">${t("search.mostComplete", "Most complete")}</option>`;
	const pageSizeOpts = PAGE_SIZE_OPTIONS.map(
		(size) => `<option value="${size}">${t("search.perPage", "{size} per page", { size })}</option>`
	).join("");
	const resultsHTML =
		results.length > 0
			? `<ul class="card-grid grid-tools" role="list">${results.map((t) => `<li>${toolCard(t)}</li>`).join("")}</ul>`
			: `<p class="empty">${t("search.noToolsMatch", "No tools match these filters.")}</p>`;
	const localHTML =
		local.length > 0
			? `<div class="panel browse__local"><h3 class="panel__title">${t("search.registeredHere", "Registered on this site")}</h3><ul class="card-grid grid-tools" role="list">${local.map((tool) => `<li>${toolCard(tool)}</li>`).join("")}</ul></div>`
			: "";

	// Stryker disable next-line StringLiteral: button() defaults variant to "outline", so mutating this explicit "outline" to "" yields identical markup — equivalent.
	const clearFiltersBtn = button(t("search.clearFilters", "Clear filters"), {
		variant: "outline",
		href: "/search",
		cls: "facets__reset"
	});
	const html = `
	<div class="container page">
		<h1 class="page__title">${t("search.browseTools", "Browse tools")}</h1>
		<div class="browse">
			<aside class="facets" aria-label="${t("search.filters", "Filters")}">
				<form data-facet-q role="search">
					<label for="facet-q" class="skip-label">${t("search.searchWithinTools", "Search within tools")}</label>
					<input id="facet-q" class="facets__search" type="search" placeholder="${t("search.searchToolsPlaceholder", "Search tools…")}" autocomplete="off" value="${esc(q)}" />
				</form>
				${statusFacetHTML}
				${facetHTML || `<p class="facet__empty">${t("search.noFiltersAvailable", "No filters available.")}</p>`}
				${clearFiltersBtn}
			</aside>
			<div class="browse__main">
				<div class="browse__bar">
					<span class="browse__count" aria-live="polite">${countHTML}${q ? ` for &ldquo;<span${dirAttrs(q)}>${esc(q)}</span>&rdquo;` : ""}${countNoteHTML}</span>
					<span class="browse__controls">
						<label class="sort"><span class="skip-label">${t("search.resultsPerPage", "Results per page")}</span><select id="page-size">${pageSizeOpts}</select></label>
						<label class="sort"><span class="skip-label">${t("search.sortBy", "Sort by")}</span><select id="sort">${sortOpts}</select></label>
					</span>
				</div>
				${localHTML}${resultsHTML}
				<nav class="pager" aria-label="${t("search.pagination", "Pagination")}">${pagerHTML}</nav>
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
	return {
		title: q ? t("search.docTitleQuery", "“{q}” — Toolhub", { q }) : t("search.docTitle", "Browse tools — Toolhub"),
		html,
		mount
	};
}
