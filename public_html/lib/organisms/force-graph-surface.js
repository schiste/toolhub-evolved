// SPDX-License-Identifier: GPL-3.0-or-later
import { t } from "../core/i18n.js";

/** @param {HTMLElement} container */
export function createGraphSurface(container) {
	const canvas = document.createElement("canvas");
	const tooltip = document.createElement("div");
	const ctx = /** @type {CanvasRenderingContext2D} */ (canvas.getContext("2d"));
	canvas.className = "force-graph";
	canvas.setAttribute("aria-label", t("forceGraph.toolSimilarityGraph", "Tool similarity graph"));
	canvas.setAttribute("role", "img");
	canvas.setAttribute("tabindex", "0");
	tooltip.className = "graph__tip";
	tooltip.hidden = true;
	container.innerHTML = "";
	container.append(canvas, tooltip);
	return { canvas, tooltip, ctx };
}
