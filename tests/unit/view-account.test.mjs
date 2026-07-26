// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

const h = vi.hoisted(() => ({
	backendGetJson: vi.fn(),
	serverWrite: vi.fn(),
	clearAll: vi.fn()
}));

vi.mock("../../public_html/lib/core/api.js", async (orig) => {
	const actual = await orig();
	return { ...actual, backendGetJson: h.backendGetJson };
});
vi.mock("../../public_html/lib/core/serversync.js", async (orig) => {
	const actual = await orig();
	return { ...actual, serverWrite: h.serverWrite };
});
vi.mock("../../public_html/lib/core/store.js", async (orig) => {
	const actual = await orig();
	return { ...actual, demoStore: { ...actual.demoStore, clearAll: h.clearAll } };
});

const { viewAccountSettings } = await import("../../public_html/views/account.js");

beforeEach(() => {
	vi.clearAllMocks();
	document.body.innerHTML = "";
	window.confirm = vi.fn(() => true);
});

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test("viewAccountSettings renders export, delete, and OAuth controls", () => {
	const r = viewAccountSettings();
	assert.equal(r.title, "Evolved data settings - Toolhub");
	assert.ok(r.html.includes("Generate export"));
	assert.ok(r.html.includes("Delete Evolved-local data"));
	assert.ok(r.html.includes('href="/oauth/login"'));
	assert.ok(r.html.includes('href="/oauth/logout"'));
});

test("export action renders the JSON export", async () => {
	h.backendGetJson.mockResolvedValue({ user: { username: "Ada" }, overlay: { favorites: ["tool-a"] } });
	const r = viewAccountSettings();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-export]").click();
	await tick();
	assert.deepEqual(h.backendGetJson.mock.calls[0], ["/v1/user/export/"]);
	const text = document.querySelector("[data-export-json]").value;
	assert.ok(text.includes('"favorites": ['));
	assert.ok(document.querySelector("[data-account-result]").textContent.includes("Export generated"));
});

test("delete action calls the server and clears the local cache", async () => {
	h.serverWrite.mockResolvedValue({ deleted: { favorites: 1, lists: 2 } });
	const r = viewAccountSettings();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-delete-evolved]").click();
	await tick();
	assert.deepEqual(h.serverWrite.mock.calls[0], ["DELETE", "/v1/user/evolved-data/"]);
	assert.equal(h.clearAll.mock.calls.length, 1);
	assert.ok(document.querySelector("[data-account-result]").textContent.includes("3 rows"));
});

test("delete action can be cancelled", async () => {
	window.confirm = vi.fn(() => false);
	const r = viewAccountSettings();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-delete-evolved]").click();
	await tick();
	assert.equal(h.serverWrite.mock.calls.length, 0);
	assert.equal(h.clearAll.mock.calls.length, 0);
});
