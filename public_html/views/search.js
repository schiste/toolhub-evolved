// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, $input, dirAttrs, esc } from "../lib/core/dom.js";
import { fmt, t } from "../lib/core/i18n.js";
import { apiGet, backendGetJson, cachedCanonicalTools, localToolBase, normalizeTool } from "../lib/core/api.js";
import { navigateTo } from "../lib/core/routing.js";
import {
	attachEndorsements,
	attachEvolvedSummaries,
	completeness,
	EVOLVED_SUMMARY_GRACE_MS,
	rankFitsFirst
} from "../lib/core/signals.js";
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

/**
 * Keep Toolhub search-index lag from publishing records that are absent from
 * the last complete canonical catalog snapshot. If the local projection is
 * unavailable, preserve the live response: an outage is not evidence that
 * every tool was deleted.
 * @param {Tool[]} results
 * @returns {Promise<{ results: Tool[], retiredOnPage: number }>}
 */
async function retainCanonicalResults(results) {
	if (results.length === 0) return { results, retiredOnPage: 0 };
	try {
		const canonical = await cachedCanonicalTools({
			names: results.map((tool) => tool.name),
			limit: results.length
		});
		const active = new Set(canonical.map((tool) => tool.name));
		const visible = results.filter((tool) => active.has(tool.name));
		return { results: visible, retiredOnPage: results.length - visible.length };
	} catch {
		return { results, retiredOnPage: 0 };
	}
}

export async function viewSearch() {
	// Stryker disable next-line StringLiteral: when location.search is empty the fallback feeds URLSearchParams; "" yields no params and any sentinel yields a single unread key, so reads (q, page, *__term, …) are unaffected — equivalent.
	const usp = new URLSearchParams(location.search || "");
	const q = usp.get("q") || "";
	// Stryker disable next-line StringLiteral: when the page param is absent the fallback is parsed; "" and any sentinel both yield NaN (→ page 1) — equivalent.
	const page = Math.max(1, Number.parseInt(usp.get("page") ?? "", 10) || 1);
	const pageSize = activePageSize(usp.get("page_size"));
	const { sort, ordering, defaultSort } = resolveSort(usp);
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

	const apiParams = /** @type {Record<string, string>} */ (/** @type {unknown} */ (api));
	const catalog = () =>
		(async () => {
			try {
				const liveData = await apiGet("/search/tools/", apiParams);
				const canonical = await retainCanonicalResults(
					(liveData.results || []).map((/** @type {any} */ tool) => normalizeTool(tool))
				);
				return {
					data: {
						...liveData,
						count: Math.max(0, Number(liveData.count || 0) - canonical.retiredOnPage)
					},
					results: canonical.results,
					canonicalFallback: false
				};
			} catch (error) {
				const cached = await cachedCanonicalTools({ q, limit: page * pageSize }).catch(() => []);
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
	/** @type {Tool[]} */
	let results = loaded.results;
	const { canonicalFallback } = loaded;
	const local = localStrip(candidates, results);
	await Promise.all([
		attachEndorsements(results, { defer: true }),
		attachEvolvedSummaries(results, { graceMs: EVOLVED_SUMMARY_GRACE_MS }),
		attachEvolvedSummaries(local, { graceMs: EVOLVED_SUMMARY_GRACE_MS })
	]);
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
				? t(
						"search.showingOnPage",
						"Showing $1 on this page of $2",
						esc(fmt(results.length)),
						esc(t("search.toolCount", "$1 {{PLURAL:$2|tool|tools}}", fmt(total), total))
					)
				: t(
						"search.noVisibleOnPage",
						"No visible tools on this page of $1",
						esc(t("search.toolCount", "$1 {{PLURAL:$2|tool|tools}}", fmt(total), total))
					)
			: results.length > 0
				? t(
						"search.showingRange",
						"Showing $1-$2 of $3",
						esc(fmt(firstResult)),
						esc(fmt(lastResult)),
						esc(t("search.toolCount", "$1 {{PLURAL:$2|tool|tools}}", fmt(total), total))
					)
				: esc(t("search.toolCount", "$1 {{PLURAL:$2|tool|tools}}", fmt(total), total));
	const countNotes = [
		clientStatuses.size > 0 ? t("search.filteredInBrowser", "filtered in your browser") : "",
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
		title: q ? t("search.docTitleQuery", "“$1” — Toolhub", q) : t("search.docTitle", "Browse tools — Toolhub"),
		html,
		mount
	};
}
