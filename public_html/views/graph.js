// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { backendGetJson } from "../lib/core/api.js";
import { t } from "../lib/core/i18n.js";
import { hasContext } from "../lib/core/signals.js";
import { button, iconButton } from "../lib/atoms/button.js";
import { communityColors, forceGraph } from "../lib/organisms/force-graph.js";
import { openQuickView } from "../lib/organisms/quickview.js";

const GRAPH_LIMITS = [250, 500, 1000, 2000, 4000];
const GRAPH_GROUPINGS = [
	"similarity",
	"language",
	"project",
	"task",
	"use_case",
	"tool_type",
	"technology",
	"platform"
];

/** @returns {{ limit: number, groupBy: string }} */
function graphRequestState() {
	const params = new URLSearchParams(location.search);
	const requestedLimit = Number(params.get("limit"));
	const limit = GRAPH_LIMITS.includes(requestedLimit) ? requestedLimit : GRAPH_LIMITS[0];
	const requestedGroup = params.get("groupBy") || "";
	const groupBy = GRAPH_GROUPINGS.includes(requestedGroup) ? requestedGroup : "similarity";
	return { limit, groupBy };
}

/** @param {{ limit: number, groupBy: string }} state */
function graphRequestUrl(state) {
	return `/v1/graph/?limit=${encodeURIComponent(String(state.limit))}&groupBy=${encodeURIComponent(state.groupBy)}`;
}

/**
 * @param {{ id: string | number, label: string, size: number }[]} communityMeta
 * @returns {string}
 */
function communityLegend(communityMeta) {
	const colors = communityColors(communityMeta);
	const items = (communityMeta || []).map((community) => {
		const color = colors.get(community.id) || colors.get(String(community.id));
		return `<span class="graph__legend-item"><span class="graph__swatch" style="background: ${esc(color)}"></span><span class="graph__legend-text">${esc(community.label)} <span class="graph__legend-count">(${esc(String(community.size))})</span></span></span>`;
	});
	if (!(communityMeta || []).some((community) => community.label === "Other")) {
		items.push(
			`<span class="graph__legend-item"><span class="graph__swatch" style="background: ${esc(colors.get("other"))}"></span><span class="graph__legend-text">${t("graph.other", "Other")}</span></span>`
		);
	}
	if (hasContext()) {
		items.push(
			`<span class="graph__legend-item"><span class="graph__swatch graph__swatch--halo"></span><span class="graph__legend-text">${t("graph.fitsYou", "Fits you")}</span></span>`
		);
	}
	return items.join("");
}

/** @param {{ limit: number, groupBy: string }} state */
function graphOptions(state) {
	/** @type {Record<string, string>} */
	const groupingLabels = {
		similarity: t("graph.groupSimilarity", "Similarity only"),
		language: t("graph.groupLanguage", "Languages"),
		project: t("graph.groupProject", "Projects"),
		task: t("graph.groupTask", "Tasks"),
		use_case: t("graph.groupUseCase", "Use cases"),
		tool_type: t("graph.groupToolType", "Tool types"),
		technology: t("graph.groupTechnology", "Technology"),
		platform: t("graph.groupPlatform", "Platforms")
	};
	const limitOptions = GRAPH_LIMITS.map(
		(limit) =>
			`<option value="${limit}"${limit === state.limit ? " selected" : ""}>${limit.toLocaleString()}</option>`
	).join("");
	const groupOptions = GRAPH_GROUPINGS.map(
		(group) =>
			`<option value="${esc(group)}"${group === state.groupBy ? " selected" : ""}>${esc(groupingLabels[group])}</option>`
	).join("");
	return `<div class="graph__view-options" data-graph-view-options>
		<label class="graph__filter" for="graph-limit"><span>${esc(t("graph.nodeCount", "Tools shown"))}</span><select id="graph-limit" class="graph__select" data-graph-option="limit">${limitOptions}</select></label>
		<label class="graph__filter" for="graph-group-by"><span>${esc(t("graph.groupBy", "Pull together by"))}</span><select id="graph-group-by" class="graph__select" data-graph-option="groupBy">${groupOptions}</select></label>
	</div>`;
}

/**
 * @param {HTMLElement} graph
 * @param {Array<{ id: string, covered: number, total: number, enabled: boolean }>} metadata
 */
function updateGroupingOptions(graph, metadata) {
	const select = /** @type {HTMLSelectElement | null} */ (graph.querySelector('[data-graph-option="groupBy"]'));
	if (!select) return;
	const byId = new Map((metadata || []).map((item) => [item.id, item]));
	for (const option of select.options) {
		const item = byId.get(option.value);
		if (!item) continue;
		option.disabled = !item.enabled;
		option.title = item.enabled
			? ""
			: t("graph.groupCoverage", "{covered} of {total} tools have this metadata", {
					covered: String(item.covered),
					total: String(item.total)
				});
	}
}

function graphToolbar() {
	const zoomIn = t("graph.zoomIn", "Zoom in");
	const zoomOut = t("graph.zoomOut", "Zoom out");
	const fit = t("graph.fit", "Fit map");
	return `<div class="graph__toolbar" data-graph-controls role="toolbar" aria-label="${esc(t("graph.controls", "Map controls"))}">
		<div class="graph__toolbar-actions">
			${iconButton("add", zoomIn, { size: "sm", attrs: `data-graph-action="zoom-in" title="${esc(zoomIn)}"` })}
			${button("−", { size: "sm", cls: "graph__zoom-out", attrs: `data-graph-action="zoom-out" aria-label="${esc(zoomOut)}" title="${esc(zoomOut)}"` })}
			${button(fit, { size: "sm", icon: "convert", attrs: `data-graph-action="fit" title="${esc(fit)}"` })}
		</div>
		<span class="graph__zoom-readout" data-graph-zoom aria-live="polite">100%</span>
	</div>`;
}

/**
 * @param {Array<{ projects?: string[], languages?: string[] }>} nodes
 * @param {"projects" | "languages"} key
 * @returns {string[]}
 */
function graphFacetValues(nodes, key) {
	return [...new Set(nodes.flatMap((node) => (Array.isArray(node[key]) ? node[key] : [])))]
		.filter(Boolean)
		.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
}

/** @param {Array<{ projects?: string[], languages?: string[] }>} nodes */
function graphFilters(nodes) {
	const projectLabel = t("graph.projectFilter", "Project");
	const languageLabel = t("graph.languageFilter", "Language");
	const projectOptions = graphFacetValues(nodes, "projects")
		.map((value) => `<option value="${esc(value)}">${esc(value)}</option>`)
		.join("");
	const languageOptions = graphFacetValues(nodes, "languages")
		.map((value) => `<option value="${esc(value)}">${esc(value)}</option>`)
		.join("");
	return `<div class="graph__filters" data-graph-filters aria-label="${esc(t("graph.filters", "Map filters"))}">
		<label class="graph__filter" for="graph-project-filter"><span>${esc(projectLabel)}</span><select id="graph-project-filter" class="graph__select" data-graph-filter="projects">
			<option value="">${esc(t("graph.allProjects", "All projects"))}</option>${projectOptions}
		</select></label>
		<label class="graph__filter" for="graph-language-filter"><span>${esc(languageLabel)}</span><select id="graph-language-filter" class="graph__select" data-graph-filter="languages">
			<option value="">${esc(t("graph.allLanguages", "All languages"))}</option>${languageOptions}
		</select></label>
		<span class="graph__filter-count" data-graph-filter-count aria-live="polite">${esc(
			t("graph.filterCount", "Showing {visible} of {total} tools", {
				visible: String(nodes.length),
				total: String(nodes.length)
			})
		)}</span>
	</div>`;
}

export function viewGraph() {
	const state = graphRequestState();
	const html = `
	<div class="container page">
		<h1 class="page__title">${t("graph.toolMap", "Tool map")}</h1>
		<p class="page__intro">${t("graph.intro", "A similarity map of the most thoroughly-documented tools in the catalog. Each tool sits near others with overlapping function, scope, and audience; lines connect nearest neighbors and colors are clusters detected from those connections.")}</p>
		<div class="graph" aria-busy="true">
			${graphToolbar()}
			${graphOptions(state)}
			<div data-graph-filters hidden></div>
			<div id="graph-canvas" class="graph__canvas"><div class="graph__loading" role="status"><span class="spinner" aria-hidden="true"></span><span>${esc(t("graph.loading", "Preparing the tool map"))}</span></div></div>
			<p class="empty" data-graph-empty hidden>${t("graph.mapEmpty", "No richly documented tools are available for the map right now.")}</p>
			<p class="empty graph__filter-empty" data-graph-filter-empty hidden>${t("graph.filterEmpty", "No tools match these filters.")}</p>
			<div class="graph__legend" data-graph-legend aria-label="${t("graph.mapLegend", "Map legend")}" hidden></div>
			<p class="graph__note" data-graph-note hidden></p>
		</div>
	</div>`;
	function mount() {
		const targetNode = /** @type {HTMLElement | null} */ (document.querySelector("#graph-canvas"));
		if (!targetNode) return;
		const graphNode = targetNode.closest(".graph");
		if (!(graphNode instanceof HTMLElement)) return;
		const target = targetNode;
		const graph = graphNode;
		/** @type {ReturnType<typeof forceGraph> | null} */
		let currentHandle = null;
		let currentState = state;
		let requestId = 0;

		/** @param {any} next @param {{ limit: number, groupBy: string }} nextState @param {boolean} updateUrl */
		function showPayload(next, nextState, updateUrl) {
			if (!Array.isArray(next?.nodes) || !Array.isArray(next?.edges)) throw new Error("Invalid graph payload");
			currentHandle?.stop();
			updateGroupingOptions(graph, next.groupingMeta || []);
			const currentFilters = graph.querySelector("[data-graph-filters]");
			if (currentFilters) currentFilters.outerHTML = graphFilters(next.nodes);
			const legend = /** @type {HTMLElement | null} */ (graph.querySelector("[data-graph-legend]"));
			if (legend) {
				legend.innerHTML = communityLegend(next.groupMeta || next.communityMeta);
				legend.hidden = next.nodes.length === 0;
			}
			const note = /** @type {HTMLElement | null} */ (graph.querySelector("[data-graph-note]"));
			if (note) {
				note.textContent = next.truncated
					? t("graph.truncatedNote", "Showing the {count} best-documented tools.", {
							count: String(next.nodes.length)
						})
					: "";
				note.hidden = !next.truncated;
			}
			const empty = /** @type {HTMLElement | null} */ (graph.querySelector("[data-graph-empty]"));
			if (empty) empty.hidden = next.nodes.length > 0;
			if (next.nodes.length > 0) {
				currentHandle = forceGraph(target, next, { onSelect: openQuickView, height: 560 });
				target.forceGraphHandle = currentHandle;
			} else {
				target.innerHTML = "";
				currentHandle = null;
				target.forceGraphHandle = null;
			}
			graph.removeAttribute("aria-busy");
			if (updateUrl) {
				const url = new URL(location.href);
				url.searchParams.set("limit", String(nextState.limit));
				url.searchParams.set("groupBy", nextState.groupBy);
				history.replaceState(history.state, "", `${url.pathname}${url.search}${url.hash}`);
			}
		}

		/** @param {{ limit: number, groupBy: string }} nextState @param {boolean} updateUrl */
		async function load(nextState, updateUrl) {
			const id = ++requestId;
			graph.setAttribute("aria-busy", "true");
			try {
				const next = await backendGetJson(graphRequestUrl(nextState));
				if (id !== requestId) return;
				showPayload(next, nextState, updateUrl);
			} catch {
				if (id !== requestId) return;
				graph.removeAttribute("aria-busy");
				if (!currentHandle) {
					target.innerHTML = `<div class="graph__loading graph__loading--error" role="alert"><span>${esc(t("graph.loadError", "The tool map could not be loaded."))}</span>${button(t("graph.retry", "Try again"), { size: "sm", attrs: 'data-graph-action="retry"' })}</div>`;
				}
			}
		}

		graph.addEventListener("click", (event) => {
			const action = /** @type {HTMLElement | null} */ (
				/** @type {Element | null} */ (event.target)?.closest("[data-graph-action]")
			)?.dataset.graphAction;
			if (action === "zoom-in") currentHandle?.zoomIn();
			if (action === "zoom-out") currentHandle?.zoomOut();
			if (action === "fit") currentHandle?.fitView();
			if (action === "retry") void load(currentState, false);
		});
		graph.addEventListener("change", (event) => {
			const option = /** @type {HTMLSelectElement | null} */ (
				/** @type {Element | null} */ (event.target)?.closest("select[data-graph-option]")
			);
			if (option) {
				const nextState = {
					limit: option.dataset.graphOption === "limit" ? Number(option.value) : currentState.limit,
					groupBy: option.dataset.graphOption === "groupBy" ? option.value : currentState.groupBy
				};
				if (!GRAPH_LIMITS.includes(nextState.limit) || !GRAPH_GROUPINGS.includes(nextState.groupBy)) return;
				currentState = nextState;
				void load(nextState, true);
				return;
			}
			const filterControls = graph.querySelector("[data-graph-filters]");
			const select = /** @type {HTMLSelectElement | null} */ (
				/** @type {Element | null} */ (event.target)?.closest("select[data-graph-filter]")
			);
			if (!select || !filterControls) return;
			const projects = /** @type {HTMLSelectElement | null} */ (
				filterControls.querySelector('[data-graph-filter="projects"]')
			)?.value;
			const languages = /** @type {HTMLSelectElement | null} */ (
				filterControls.querySelector('[data-graph-filter="languages"]')
			)?.value;
			currentHandle?.setFilters({ projects: projects || "", languages: languages || "" });
		});
		void load(state, false);
	}
	return { title: t("graph.docTitle", "Tool map — Toolhub"), html, mount };
}
