// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

const h = vi.hoisted(() => ({ backendGetJson: vi.fn() }));
vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => ({
	...(await importOriginal()),
	backendGetJson: h.backendGetJson
}));

import { mountJsonReport } from "../../public_html/lib/organisms/json-report.js";

const mount = () =>
	mountJsonReport({
		name: "report",
		endpoint: "/v1/example/",
		render: (payload) => `<p class="ok">${payload.value}</p>`,
		renderLoading: () => `<p class="loading">Loading</p>`,
		renderError: () => `<p class="failed">Failed</p><button data-report-retry>Retry</button>`
	});

const root = () => document.querySelector("[data-report-root]");
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => {
	h.backendGetJson.mockReset();
	document.body.innerHTML = `<div data-report-root></div>`;
});

test("a loaded document is rendered and busy state is cleared", async () => {
	h.backendGetJson.mockResolvedValue({ value: "done" });
	mount()();
	await flush();

	assert.match(root().innerHTML, /class="ok">done/);
	assert.equal(root().hasAttribute("aria-busy"), false);
	assert.deepEqual(h.backendGetJson.mock.calls, [["/v1/example/"]]);
});

test("a failed load shows the retryable error and still clears busy state", async () => {
	h.backendGetJson.mockRejectedValue(new Error("offline"));
	mount()();
	await flush();

	assert.match(root().innerHTML, /class="failed"/);
	// Cleared in `finally`, so a failure never leaves assistive tech waiting.
	assert.equal(root().hasAttribute("aria-busy"), false);
});

test("clicking retry loads again", async () => {
	h.backendGetJson.mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ value: "second" });
	mount()();
	await flush();
	root().querySelector("[data-report-retry]").click();
	await flush();

	assert.match(root().innerHTML, /class="ok">second/);
	assert.equal(h.backendGetJson.mock.calls.length, 2);
});

test("a response arriving after the route changed does not overwrite the new one", async () => {
	let settle;
	h.backendGetJson.mockReturnValue(new Promise((resolve) => (settle = resolve)));
	mount()();
	// The user navigates away while the request is still in flight.
	const detached = root();
	document.body.innerHTML = `<div class="other-route"></div>`;
	settle({ value: "stale" });
	await flush();

	assert.doesNotMatch(detached.innerHTML, /stale/);
	assert.match(document.body.innerHTML, /other-route/);
});

test("mounting against a missing root is a no-op rather than a crash", async () => {
	document.body.innerHTML = `<div class="unrelated"></div>`;
	mount()();
	await flush();

	assert.equal(h.backendGetJson.mock.calls.length, 0);
});
