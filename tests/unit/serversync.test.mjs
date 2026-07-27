// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

// Each test gets a fresh module graph: serversync/session/store hold module
// state (csrf, oauthReady, the push chain, the registered hook).
async function load() {
	vi.resetModules();
	const serversync = await import("../../public_html/lib/core/serversync.js");
	const store = await import("../../public_html/lib/core/store.js");
	const session = await import("../../public_html/lib/core/session.js");
	const api = await import("../../public_html/lib/core/api.js");
	session.setAuthRender(() => {});
	return { api, serversync, store, session };
}

/** Install a fetch stub routing by URL; records every call. */
function mockFetch(routes) {
	const calls = [];
	globalThis.fetch = vi.fn(async (url, opts = {}) => {
		calls.push({ url, opts });
		const route = routes[url];
		if (!route) throw new TypeError(`network down: ${url}`);
		if (route.reject) throw new TypeError("network down");
		return { ok: route.ok !== false, json: async () => route.json };
	});
	return calls;
}

async function flush() {
	// settle the serialized push chain (two awaits per link)
	await Promise.resolve();
	await Promise.resolve();
	await Promise.resolve();
}

beforeEach(() => {
	localStorage.clear();
});

test("backend unreachable → demo mode, no server user", async () => {
	const { serversync, session } = await load();
	mockFetch({}); // every fetch throws
	assert.equal(await serversync.initServerSync(), false);
	assert.equal(serversync.oauthAvailable(), false);
	assert.equal(session.serverUserName(), null);
});

test("logged out: learns oauth availability from /v1/config/", async () => {
	const { serversync, session } = await load();
	let rendered = 0;
	session.setAuthRender(() => {
		rendered += 1;
	});
	mockFetch({
		"/v1/user/": { ok: false, json: {} },
		"/v1/config/": { json: { oauth: true } }
	});
	assert.equal(await serversync.initServerSync(), false);
	assert.equal(serversync.oauthAvailable(), true);
	assert.equal(session.serverUserName(), null);
	assert.equal(rendered, 1); // the account UI was told to re-render
});

test("logged out with config unavailable → oauth treated as unconfigured", async () => {
	const { serversync } = await load();
	mockFetch({ "/v1/user/": { json: { authenticated: false } } }); // /v1/config/ throws
	assert.equal(await serversync.initServerSync(), false);
	assert.equal(serversync.oauthAvailable(), false);
});

test("authenticated but overlay pull fails → still shows the real session", async () => {
	const { serversync, session } = await load();
	mockFetch({ "/v1/user/": { json: { authenticated: true, username: "Ada", csrf: "c" } } });
	assert.equal(await serversync.initServerSync(), true);
	assert.equal(session.serverUserName(), "Ada");
	assert.equal(serversync.oauthAvailable(), true);
	assert.equal(serversync.officialWriteAvailable(), true);
});

test("authenticated: pulls the overlay, activates identity + write-through", async () => {
	const { serversync, store, session } = await load();
	const calls = mockFetch({
		"/v1/user/": { json: { authenticated: true, username: "Grace Hopper", csrf: "tok-1" } },
		"/v1/overlay/": {
			json: { favorites: ["alpha"], lists: [], toolEdits: { t: { title: "X" } } } // partial: other keys untouched
		},
		"/v1/overlay/favorites": { json: { ok: true } }
	});
	assert.equal(await serversync.initServerSync(), true);
	// pulled server copy landed in the localStorage cache
	assert.deepEqual(store.favNames(), ["alpha"]);
	assert.deepEqual(store.toolEditsMap(), { t: { title: "X" } });
	// real identity active: username + feature mode on
	assert.equal(session.serverUserName(), "Grace Hopper");
	assert.equal(session.USER.name, "Grace Hopper");
	assert.equal(session.expOn(), true);
	assert.equal(serversync.oauthAvailable(), true);
	// the pull itself must NOT have pushed anything back
	assert.equal(calls.filter((c) => c.opts.method === "PUT").length, 0);
	// a mutation now writes through with the CSRF token
	store.toggleFav("beta");
	await flush();
	const put = calls.find((c) => c.opts.method === "PUT");
	assert.ok(put);
	assert.equal(put.url, "/v1/overlay/favorites");
	assert.equal(put.opts.headers["X-CSRF-Token"], "tok-1");
	assert.deepEqual(JSON.parse(put.opts.body), ["alpha", "beta"]);
	// cleanup: restore module-independent globals
	session.setServerUser(null);
	session.USER.name = "Ada Lovelace";
	session.applyExp(false);
});

test("officialWrite uses the authenticated session CSRF token", async () => {
	const { api, serversync, session } = await load();
	const calls = mockFetch({
		"/v1/user/": { json: { authenticated: true, username: "Ada", csrf: "tok-official" } },
		"/v1/overlay/": { json: {} },
		"/api/tools/x/": { json: { name: "x", title: "cached" } },
		"/v1/toolhub/tools/": { json: { ok: true, toolhub: { name: "x" } } }
	});
	const cached = await api.apiGet("/tools/x/");
	assert.equal(await api.apiGet("/tools/x/"), cached);
	assert.equal(serversync.officialWriteAvailable(), false);
	assert.equal(await serversync.initServerSync(), true);
	assert.equal(serversync.officialWriteAvailable(), true);
	const data = await serversync.officialWrite("POST", "/v1/toolhub/tools/", { name: "x" });
	assert.deepEqual(data, { ok: true, toolhub: { name: "x" } });
	await api.apiGet("/tools/x/");
	const call = calls.find((c) => c.url === "/v1/toolhub/tools/");
	assert.equal(call.opts.method, "POST");
	assert.equal(call.opts.headers["X-CSRF-Token"], "tok-official");
	assert.deepEqual(JSON.parse(call.opts.body), { name: "x" });
	assert.equal(calls.filter((c) => c.url === "/api/tools/x/").length, 2);
	session.setServerUser(null);
	session.USER.name = "Ada Lovelace";
	session.applyExp(false);
});

test("officialWrite rejects before a Toolhub session is established", async () => {
	const { serversync } = await load();
	assert.equal(serversync.officialWriteAvailable(), false);
	assert.throws(() => serversync.officialWrite("POST", "/v1/toolhub/tools/", { name: "x" }), /sign-in is required/);
});

test("push failures are swallowed; later pushes still run", async () => {
	const { serversync, store, session } = await load();
	const calls = mockFetch({
		"/v1/user/": { json: { authenticated: true } }, // no username / csrf → empty fallbacks
		"/v1/overlay/": { json: {} } // nothing stored server-side yet
	});
	assert.equal(await serversync.initServerSync(), true);
	store.toggleFav("one"); // PUT /v1/overlay/favorites is unrouted → rejects
	await flush();
	store.toggleFav("two");
	await flush();
	const puts = calls.filter((c) => c.opts.method === "PUT");
	assert.equal(puts.length, 2); // the chain survived the first failure
	assert.equal(puts[0].opts.headers["X-CSRF-Token"], "");
	session.setServerUser(null);
	session.USER.name = "Ada Lovelace";
	session.applyExp(false);
});
