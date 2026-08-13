// SPDX-License-Identifier: GPL-3.0-or-later
import { backendGetJson } from "../core/api.js";

/**
 * Mount a view that renders one backend JSON document, with a retry.
 *
 * The load cycle is identical for every such page — announce busy, fetch,
 * render or show a retryable error, clear busy — and it has three details that
 * are easy to get subtly wrong per copy: the `isConnected` guard that stops a
 * late response overwriting a route the user already left, clearing
 * `aria-busy` in `finally` so a failed load does not leave assistive tech
 * waiting, and delegating the retry click from the container that the failure
 * markup gets rendered into.
 *
 * Selectors derive from `name`, so the root and retry hooks cannot drift apart.
 *
 * @param {object} options
 * @param {string} options.name kebab-case view name, e.g. "workers"
 * @param {string} options.endpoint backend path passed to backendGetJson
 * @param {(payload: any) => string} options.render markup for a loaded document
 * @param {() => string} options.renderLoading markup shown while fetching
 * @param {() => string} options.renderError markup shown when the fetch fails
 * @returns {() => void} a mount function for the view object
 */
export function mountJsonReport({ name, endpoint, render, renderLoading, renderError }) {
	return function mount() {
		const root = document.querySelector(`[data-${name}-root]`);
		if (!(root instanceof HTMLElement)) return;
		const target = root;
		async function load() {
			target.setAttribute("aria-busy", "true");
			target.innerHTML = renderLoading();
			try {
				const payload = await backendGetJson(endpoint);
				// The route may have changed while the request was in flight.
				if (!target.isConnected) return;
				target.innerHTML = render(payload);
			} catch {
				if (!target.isConnected) return;
				target.innerHTML = renderError();
			} finally {
				target.removeAttribute("aria-busy");
			}
		}
		target.addEventListener("click", (event) => {
			if (event.target instanceof Element && event.target.closest(`[data-${name}-retry]`)) void load();
		});
		void load();
	};
}
