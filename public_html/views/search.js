// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, $input, dirAttrs, esc } from "../lib/core/dom.js";
import { fmt, t } from "../lib/core/i18n.js";
import {
	apiCached,
	apiGet,
	backendGetJson,
	cachedCanonicalTools,
	localToolBase,
	normalizeTool
} from "../lib/core/api.js";
import { navigateTo } from "../lib/core/routing.js";
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS, resolvePageSize } from "../lib/core/paging.js";
import { attachEndorsements, attachEvolvedSummaries, completeness, rankFitsFirst } from "../lib/core/signals.js";
import { button } from "../lib/atoms/button.js";
import { FACET_GROUPS, renderFacetGroup } from "../lib/molecules/facet-group.js";
import { renderPager } from "../lib/molecules/pager.js";
import { toolCard } from "../lib/organisms/tool-card.js";

/*
 * Every box in the Status group reads the same way: ticked means "include these
 * in the results". Active, Deprecated and Experimental start ticked, so leaving
 * the group alone matches the unfiltered catalogue; Archived starts cleared,
 * which is the whole point of the group existing.
 *
 * Every box filters in SQL -- Archived through `include_archived`, the other
 * three through `status`. That matters for more than tidiness: a filter applied
 * in the browser trims rows out of a page the API has already counted and
 * paged, so the total and the pager describe a larger set than the one on
 * screen. Filtering server-side is what lets the count track every box.
 *
 * Active is the complement rather than a flag of its own, because toolinfo
 * never asserts "this tool is fine". The server reads it as "not deprecated,
 * not experimental, not archived" -- see STATUS_VALUES in catalog_facets.py.
 */
const STATUS_ARCHIVED = "archived";
/** The kinds carried by `status`. Archived rides `include_archived` instead. */
const STATUS_KINDS = [
	{ value: "active", label: t("search.active", "Active") },
	{ value: "deprecated", label: t("search.deprecated", "Deprecated") },
	{ value: "experimental", label: t("search.experimental", "Experimental") }
];
const STATUS_FILTERS = [...STATUS_KINDS, { value: STATUS_ARCHIVED, label: t("search.archived", "Archived") }];
const STATUS_VALUES = new Set(STATUS_FILTERS.map((s) => s.value));
/** Ticked when the reader has expressed no preference. */
const STATUS_DEFAULT = Object.freeze(STATUS_KINDS.map((s) => s.value));

/**
 * The ticked Status boxes for this request.
 *
 * An absent parameter is the default set, not the empty set: the URL carries a
 * `status` only once the reader has changed something, so a bare `/search` and
 * a shared link that kept the defaults have to agree. `?status=` with nothing
 * after it is a real answer -- every box cleared -- and stays distinct from
 * absent, which is why this reads null rather than falsy.
 * @param {string | null} value
 */
function activeStatuses(value) {
	if (value === null) return new Set(STATUS_DEFAULT);
	return new Set(
		value
			.split(",")
			.map((s) => s.trim())
			.filter((s) => STATUS_VALUES.has(s))
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
	if (ordering === "-score") return "relevance";
	return fallback;
}

/** @param {Set<string>} selectedStatuses */
function renderStatusFacetGroup(selectedStatuses) {
	const rows = STATUS_FILTERS.map((s) => {
		const checked = selectedStatuses.has(s.value) ? " checked" : "";
		return `<label class="facet"><input type="checkbox" data-status="${s.value}"${checked}> <span>${esc(s.label)}</span></label>`;
	}).join("");
	return `<div class="facet-group"><h2 class="facet-group__title">${t("search.status", "Status")}</h2>${rows}</div>`;
}

/**
 * Resolve the active sort + upstream ordering from the URL, clamped to the
 * production allow-list (out-of-list requests fall back to the default).
 * @param {URLSearchParams} usp
 * @returns {{ sort: string, ordering: string, defaultSort: string }}
 */
function resolveSort(usp) {
	const defaultSort = "relevance";
	const requestedSort = usp.get("sort") || sortFromOfficialOrdering(usp.get("ordering"), defaultSort);
	// defaultSort is referenced (not re-typed) so the allow-list entry that equals the
	// default cannot drift from it; removing the default from the list is a no-op since
	// an out-of-list request already resolves to defaultSort.
	const allowedSorts = [defaultSort, "recent", "name", "complete"];
	const sort = allowedSorts.includes(requestedSort) ? requestedSort : defaultSort;
	const ordering = sort === "name" ? "name" : sort === "recent" ? "-modified_date" : "";
	return { sort, ordering, defaultSort };
}
const LOCAL_STRIP_CAP = 12;
/** Clear the cross-render local-first state (tests; each case starts fresh). */
export function resetLocalFirstStateForTests() {
	// Kept as a compatibility hook for the deterministic view harness.
}
/**
 * @param {string} q
 * @returns {Promise<any[]>}
 */
/*
 * Tools registered directly on this site, matching the same query. Canonical
 * Toolhub results come from the local replica; this strip adds only distinct,
 * clearly-provenanced Evolved records.
 */
async function localCandidates(q) {
	try {
		const data = await backendGetJson(`/v1/search/tools/?q=${encodeURIComponent(q)}`);
		return data && Array.isArray(data.results) ? data.results : [];
	} catch {
		return [];
	}
}
/**
 * Dedupe local candidates against the live page and build the strip.
 *
 * Split from the fetch so the request can run alongside local catalog search rather
 * than after it: the dedup is the only part that needs the live results, and it
 * is pure.
 * @param {any[]} candidates
 * @param {Tool[]} live
 * @returns {Tool[]}
 */
function localStrip(candidates, live) {
	const seen = new Set(live.map((tool) => tool.name));
	return candidates
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
	const pageSize = resolvePageSize(usp.get("page_size"));
	const { sort, ordering, defaultSort } = resolveSort(usp);
	const statuses = activeStatuses(usp.get("status"));

	// Live API params: q, paging, ordering + every *__term facet filter from the URL.
	const api = new URLSearchParams();
	if (q) api.set("q", q);
	api.set("page", String(page));
	api.set("page_size", String(pageSize));
	if (ordering) api.set("ordering", ordering);
	if (statuses.has(STATUS_ARCHIVED)) api.set("include_archived", "1");
	const statusKinds = STATUS_DEFAULT.filter((kind) => statuses.has(kind));
	// Omitted while every kind is ticked: the API reads an absent `status` as
	// "no objection to any of them", so an untouched search keeps the short
	// query string the prewarmed cache is keyed on.
	if (statusKinds.length !== STATUS_DEFAULT.length) api.set("status", statusKinds.join(","));
	const selected = new Set();
	for (const [k, v] of usp.entries()) {
		if (k.endsWith("__term")) {
			api.append(k, v);
			selected.add(`${k}=${v}`);
		}
	}
	const facetApi = new URLSearchParams(api);
	facetApi.delete("page");
	facetApi.delete("page_size");
	facetApi.delete("ordering");
	const facetParams = /** @type {Record<string, string>} */ (/** @type {unknown} */ (facetApi));
	const facetsWereCached = apiCached("/search/facets/", facetParams);
	const facetsPending = apiGet("/search/facets/", facetParams).catch(() => ({ facets: {} }));
	api.set("include_facets", "false");
	api.set("view", "card");

	const apiParams = /** @type {Record<string, string>} */ (/** @type {unknown} */ (api));
	const catalog = () =>
		(async () => {
			try {
				const liveData = await apiGet("/search/tools/", apiParams);
				return {
					data: liveData,
					results: (liveData.results || []).map((/** @type {any} */ tool) => normalizeTool(tool)),
					canonicalFallback: false
				};
			} catch (error) {
				const cached = await cachedCanonicalTools({
					q,
					limit: page * pageSize,
					includeArchived: statuses.has(STATUS_ARCHIVED),
					statuses: statusKinds.length === STATUS_DEFAULT.length ? null : statusKinds
				}).catch(() => []);
				const offset = (page - 1) * pageSize;
				const cachedResults = cached.slice(offset, offset + pageSize);
				if (cachedResults.length === 0) throw error;
				return {
					data: { count: cached.length, facets: {} },
					results: cachedResults,
					canonicalFallback: true
				};
			}
		})();

	const [loaded, candidates] = await Promise.all([catalog(), page === 1 ? localCandidates(q) : Promise.resolve([])]);
	const data = loaded.data;
	const initialFacetData = facetsWereCached ? await facetsPending : null;
	/** @type {Tool[]} */
	let results = loaded.results;
	const { canonicalFallback } = loaded;
	const local = localStrip(candidates, results);
	await Promise.all([
		attachEndorsements(results, { defer: true }),
		attachEvolvedSummaries(results),
		attachEvolvedSummaries(local)
	]);
	if (sort === "complete") {
		results.sort((a, b) => completeness(b).filled - completeness(a).filled || a.title.localeCompare(b.title));
	}
	results = rankFitsFirst(results);
	const total = data.count || 0;
	const pages = Math.max(1, Math.ceil(total / pageSize));
	/** @param {any} facets */
	const renderFacets = (facets) => FACET_GROUPS.map((g) => renderFacetGroup(g, facets, selected)).join("");
	const facetHTML = initialFacetData ? renderFacets(initialFacetData.facets || {}) : "";
	const statusFacetHTML = renderStatusFacetGroup(statuses);
	const pagerHTML = renderPager(page, pages);
	// Stryker disable next-line ConditionalExpression,EqualityOperator: firstResult/lastResult are only read in the results.length>0 branch of countHTML, where this guard is already true, so the empty-case value is never observed — equivalent.
	const firstResult = results.length > 0 ? (page - 1) * pageSize + 1 : 0;
	const lastResult = firstResult + results.length - 1;
	const countHTML =
		results.length > 0
			? t(
					"search.showingRange",
					"Showing $1-$2 of $3",
					esc(fmt(firstResult)),
					esc(fmt(lastResult)),
					esc(t("search.toolCount", "$1 {{PLURAL:$2|tool|tools}}", fmt(total), total))
				)
			: esc(t("search.toolCount", "$1 {{PLURAL:$2|tool|tools}}", fmt(total), total));
	// Every filter is applied in SQL, so `total` counts exactly what is on screen
	// and there is nothing left to caveat but the offline fallback.
	const countNotes = [
		canonicalFallback ? t("search.cachedCanonicalData", "showing the last published catalog generation") : ""
	].filter(Boolean);
	const countNoteHTML = countNotes.map((note) => ` <span class="browse__count-note">${esc(note)}</span>`).join("");

	const sortOpts = `<option value="relevance">${t("search.mostRelevant", "Most relevant")}</option><option value="recent">${t("search.recentlyUpdated", "Recently updated")}</option><option value="name">${t(
		"search.nameAZ",
		"Name (A–Z)"
	)}</option><option value="complete">${t("search.mostComplete", "Most complete")}</option>`;
	const pageSizeOpts = PAGE_SIZE_OPTIONS.map(
		(size) => `<option value="${size}">${t("search.perPage", "$1 per page", size)}</option>`
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
				<div data-facet-groups${initialFacetData ? "" : ' aria-busy="true"'}>
					${facetHTML || `<p class="facet__empty">${initialFacetData ? t("search.noFiltersAvailable", "No filters available.") : t("search.loadingFilters", "Loading filters…")}</p>`}
				</div>
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
		if (!initialFacetData) {
			facetsPending.then((facetData) => {
				const holder = /** @type {HTMLElement | null} */ ($("[data-facet-groups]"));
				if (!holder) return;
				const rendered = renderFacets(facetData.facets || {});
				holder.innerHTML =
					rendered ||
					`<p class="facet__empty">${t("search.noFiltersAvailable", "No filters available.")}</p>`;
				holder.removeAttribute("aria-busy");
			});
		}
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
			const ticked = $$(".facets input[type=checkbox][data-status]:checked").map(
				(c) => /** @type {string} */ (c.getAttribute("data-status"))
			);
			// Omitted while it matches the default so an untouched search keeps a bare
			// URL; once it differs it is written in full, empty included, because an
			// absent parameter means "the defaults" rather than "nothing ticked".
			const isDefault =
				ticked.length === STATUS_DEFAULT.length && STATUS_DEFAULT.every((s) => ticked.includes(s));
			if (!isDefault) u.set("status", ticked.join(","));
			const sv = /** @type {HTMLInputElement} */ ($input("#sort")).value;
			if (sv && sv !== defaultSort) u.set("sort", sv);
			const psv = resolvePageSize(/** @type {HTMLInputElement} */ ($input("#page-size")).value);
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
		title: q ? t("search.docTitleQuery", "“$1” — Toolhub", q) : t("search.docTitle", "Browse tools — Toolhub"),
		html,
		mount
	};
}
