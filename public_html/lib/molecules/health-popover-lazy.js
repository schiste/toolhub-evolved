// SPDX-License-Identifier: GPL-3.0-or-later
// Fills in score-popover breakdowns after the route has rendered.
//
// Cards are served a summary without the breakdown: it is most of the payload
// and the popover starts collapsed, so shipping it with the page that renders
// the card made the landing payload several times larger for content most
// readers never open. This fetches it once the route is on screen and patches
// each panel in place — deliberately not through a route repaint, which would
// redraw every card to change the inside of a closed disclosure.
import { attachEvolvedSummaries, SUMMARY_VIEW_FULL } from "../core/signals.js";
import { hasHealthPopoverDetail, healthScorePanel } from "./tool-health-summary.js";

const PENDING_SELECTOR = '[data-health-panel="pending"]';
/* One request per route render, and only for what is on screen. The endpoint
   batches, so this is a single round trip for a full grid of cards. */
const MAX_PANELS_PER_PASS = 50;
const IDLE_TIMEOUT_MS = 2000;
const IDLE_FALLBACK_MS = 800;

/** @param {() => void} callback */
function whenIdle(callback) {
	if (typeof requestIdleCallback === "function") requestIdleCallback(callback, { timeout: IDLE_TIMEOUT_MS });
	else setTimeout(callback, IDLE_FALLBACK_MS);
}

/**
 * Map each pending panel to the tool it belongs to.
 * @param {ParentNode} root
 * @returns {Array<{ name: string, panel: Element }>}
 */
function pendingPanels(root) {
	/** @type {Array<{ name: string, panel: Element }>} */
	const found = [];
	for (const panel of root.querySelectorAll(PENDING_SELECTOR)) {
		const owner = panel.closest("[data-tool]");
		const name = owner instanceof HTMLElement ? owner.dataset.tool : "";
		if (name) found.push({ name, panel });
		if (found.length >= MAX_PANELS_PER_PASS) break;
	}
	return found;
}

/**
 * Fetch the breakdown for every pending panel on screen and render it in place.
 * @param {ParentNode} [root]
 * @returns {Promise<number>} how many panels were filled in
 */
export async function hydrateHealthPopovers(root = document) {
	const panels = pendingPanels(root);
	if (panels.length === 0) return 0;
	const names = [...new Set(panels.map((entry) => entry.name))];
	/** @type {Array<{ name: string, evolvedSummary?: any }>} */
	const carriers = names.map((name) => ({ name }));
	// waitForFresh, not the deferred default: this already runs after the route
	// painted and at idle, so there is nothing left to keep off the critical
	// path, and the panels can only be patched once the answer is actually here.
	//
	// The full view is a superset of the card view, so this also upgrades the
	// stored summaries: a later visit renders the breakdown from cache with no
	// request at all.
	await attachEvolvedSummaries(carriers, { view: SUMMARY_VIEW_FULL, waitForFresh: true });
	const byName = new Map(carriers.map((carrier) => [carrier.name, carrier.evolvedSummary]));
	let filled = 0;
	for (const { name, panel } of panels) {
		const summary = byName.get(name);
		// Leave the pending marker on anything that did not arrive, so a later
		// pass can retry it rather than freezing on "loading".
		if (!hasHealthPopoverDetail(summary) || !panel.isConnected) continue;
		// Every value healthScorePanel() interpolates goes through esc() or a
		// fixed label, the same contract the router relies on when it writes a
		// whole view. Parse and swap the node rather than assigning outerHTML.
		const parsed = document.createElement("template");
		parsed.innerHTML = healthScorePanel(summary);
		const next = parsed.content.firstElementChild;
		if (!next) continue;
		panel.replaceWith(next);
		filled += 1;
	}
	return filled;
}

let started = false;

/**
 * Hydrate popovers after every route render, once the page is otherwise idle.
 * @returns {void}
 */
export function initLazyHealthPopovers() {
	if (started || typeof document === "undefined") return;
	started = true;
	document.addEventListener("toolhub:route-render-end", () => {
		whenIdle(() => {
			hydrateHealthPopovers().catch(() => {
				// The breakdown is additive; a card without it still shows its score.
			});
		});
	});
}
