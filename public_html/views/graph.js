// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { globalGraph } from "../lib/core/graph.js";
import { hasContext } from "../lib/core/signals.js";
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
		`<span class="graph__legend-item"><span class="graph__swatch" style="background: ${esc(colors.get("other"))}"></span><span class="graph__legend-text">Other</span></span>`
	);
	if (hasContext()) {
		items.push(
			'<span class="graph__legend-item"><span class="graph__swatch graph__swatch--halo"></span><span class="graph__legend-text">Fits you</span></span>'
		);
	}
	return items.join("");
}

export async function viewGraph() {
	const g = await globalGraph();
	const truncatedNote = g.truncated
		? `<p class="graph__note">Showing the ${esc(g.nodes.length)} best-documented tools.</p>`
		: "";
	const empty =
		g.nodes.length > 0
			? ""
			: '<p class="empty">No richly documented tools are available for the map right now.</p>';
	const html = `
	<div class="container page">
		<h1 class="page__title">Tool map</h1>
		<p class="page__intro">A similarity map of the most thoroughly-documented tools in the catalog. Each tool sits near others with overlapping function, scope, and audience; lines connect nearest neighbors and colors are clusters detected from those connections.</p>
		<div class="graph">
			<div id="graph-canvas" class="graph__canvas"></div>
			${empty}
			<div class="graph__legend" aria-label="Map legend">${communityLegend(g.communityMeta)}</div>
			${truncatedNote}
		</div>
	</div>`;
	function mount() {
		const target = /** @type {HTMLElement | null} */ (document.querySelector("#graph-canvas"));
		if (!target || g.nodes.length === 0) return;
		target.forceGraphHandle = forceGraph(target, g, { onSelect: openQuickView, height: 560 });
	}
	return { title: "Tool map — Toolhub", html, mount };
}
