// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { backendGetJson } from "../lib/core/api.js";
import { t } from "../lib/core/i18n.js";
import { hasContext } from "../lib/core/signals.js";
import { button, iconButton } from "../lib/atoms/button.js";
import { communityColors, forceGraph } from "../lib/organisms/force-graph.js";
import { openQuickView } from "../lib/organisms/quickview.js";

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
	items.push(
		`<span class="graph__legend-item"><span class="graph__swatch" style="background: ${esc(colors.get("other"))}"></span><span class="graph__legend-text">${t("graph.other", "Other")}</span></span>`
	);
	if (hasContext()) {
		items.push(
			`<span class="graph__legend-item"><span class="graph__swatch graph__swatch--halo"></span><span class="graph__legend-text">${t("graph.fitsYou", "Fits you")}</span></span>`
		);
	}
	return items.join("");
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

export async function viewGraph() {
	const g = (await backendGetJson("/v1/graph/")) || { nodes: [], edges: [], communityMeta: [], truncated: 0 };
	const truncatedNote = g.truncated
		? `<p class="graph__note">${t("graph.truncatedNote", "Showing the {count} best-documented tools.", { count: esc(g.nodes.length) })}</p>`
		: "";
	const empty =
		g.nodes.length > 0
			? ""
			: `<p class="empty">${t("graph.mapEmpty", "No richly documented tools are available for the map right now.")}</p>`;
	const html = `
	<div class="container page">
		<h1 class="page__title">${t("graph.toolMap", "Tool map")}</h1>
		<p class="page__intro">${t("graph.intro", "A similarity map of the most thoroughly-documented tools in the catalog. Each tool sits near others with overlapping function, scope, and audience; lines connect nearest neighbors and colors are clusters detected from those connections.")}</p>
		<div class="graph">
			${graphToolbar()}
			<div id="graph-canvas" class="graph__canvas"></div>
			${empty}
			<div class="graph__legend" aria-label="${t("graph.mapLegend", "Map legend")}">${communityLegend(g.communityMeta)}</div>
			${truncatedNote}
		</div>
	</div>`;
	function mount() {
		const target = /** @type {HTMLElement | null} */ (document.querySelector("#graph-canvas"));
		if (!target || g.nodes.length === 0) return;
		const handle = forceGraph(target, g, { onSelect: openQuickView, height: 560 });
		target.forceGraphHandle = handle;
		const controls = document.querySelector("[data-graph-controls]");
		controls?.addEventListener("click", (event) => {
			const action = /** @type {HTMLElement | null} */ (event.target)?.closest("[data-graph-action]")?.dataset
				.graphAction;
			if (action === "zoom-in") handle.zoomIn();
			if (action === "zoom-out") handle.zoomOut();
			if (action === "fit") handle.fitView();
		});
	}
	return { title: t("graph.docTitle", "Tool map — Toolhub"), html, mount };
}
