// SPDX-License-Identifier: GPL-3.0-or-later
//
// index.html starts a route's main read before app.js has parsed, which only
// helps while the url it guesses is the url the view goes on to request. A hint
// that stops matching does not break the page — it silently stops helping, and
// a page that is merely slower again is not something anyone reports. So rather
// than assert on the shape of the table, these tests drive the real
// path → dispatch → view → fetch chain and compare what actually goes out.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, test } from "vitest";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

/** The hint table exactly as the shell ships it. */
function routeHints() {
	const html = fs.readFileSync(path.join(ROOT, "public_html/index.html"), "utf8");
	const island = html.match(/<script type="application\/json" id="route-hints">([\s\S]*?)<\/script>/);
	assert.ok(island, "index.html no longer carries a route-hints table");
	return JSON.parse(island[1]);
}

const realFetch = globalThis.fetch;

/** Every url the app asks for while rendering `path`, in order. */
async function urlsRequestedBy(routePath) {
	const asked = [];
	globalThis.fetch = (input) => {
		asked.push(String(input));
		// Enough of a Response for the read paths; the views are free to fail
		// past this point, since only the request is under test.
		return Promise.resolve(
			new Response(JSON.stringify({ results: [], workers: [], counts: {} }), {
				status: 200,
				headers: { "Content-Type": "application/json" }
			})
		);
	};
	const { dispatch } = await import("../../public_html/views/router.js");
	globalThis.history.replaceState(null, "", routePath);

	const view = await dispatch();
	document.body.innerHTML = `<div id="view">${view.html || ""}</div>`;
	if (typeof view.mount === "function") view.mount();
	// Let the mount's reads reach the stub.
	await new Promise((resolve) => setTimeout(resolve, 0));
	return asked;
}

beforeEach(() => {
	localStorage.clear();
	sessionStorage.clear();
});

afterEach(() => {
	globalThis.fetch = realFetch;
});

test("every hinted route asks for exactly the url the shell started", async () => {
	const hints = routeHints();
	assert.ok(Object.keys(hints).length > 0, "the hint table is empty, so no route gets a head start");

	for (const [routePath, hint] of Object.entries(hints)) {
		const asked = await urlsRequestedBy(routePath);
		assert.ok(
			asked.some((url) => url === hint.api || url.endsWith(hint.api)),
			`${routePath} hints ${hint.api}, but rendering it requested ${JSON.stringify(asked)}. ` +
				`Update the route-hints table in public_html/index.html to match.`
		);
	}
});

test("every hinted route names a view module that exists", () => {
	for (const [routePath, hint] of Object.entries(routeHints())) {
		// The build resolves this to bundle urls and fails loudly if it cannot,
		// but the build only runs on deploy; catch a bad rename here instead.
		assert.ok(hint.module, `${routePath} has no module to preload`);
		assert.ok(
			fs.existsSync(path.join(ROOT, "public_html", hint.module)),
			`${routePath} preloads ${hint.module}, which does not exist`
		);
	}
});
