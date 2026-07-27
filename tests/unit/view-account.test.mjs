// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

const h = vi.hoisted(() => ({
	backendGetJson: vi.fn(),
	paginate: vi.fn(),
	serverWrite: vi.fn(),
	clearAll: vi.fn()
}));

vi.mock("../../public_html/lib/core/api.js", async (orig) => {
	const actual = await orig();
	return { ...actual, backendGetJson: h.backendGetJson, paginate: h.paginate };
});
vi.mock("../../public_html/lib/core/serversync.js", async (orig) => {
	const actual = await orig();
	return { ...actual, serverWrite: h.serverWrite };
});
vi.mock("../../public_html/lib/core/store.js", async (orig) => {
	const actual = await orig();
	return { ...actual, demoStore: { ...actual.demoStore, clearAll: h.clearAll } };
});

const { setServerUser } = await import("../../public_html/lib/core/session.js");
const { viewAccountSettings, viewDeveloperSettings, viewMyApps } = await import("../../public_html/views/account.js");

beforeEach(() => {
	vi.clearAllMocks();
	document.body.innerHTML = "";
	window.confirm = vi.fn(() => true);
	setServerUser("Ada Lovelace");
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

test("viewDeveloperSettings renders the Toolhub developer hub and profile links", () => {
	const r = viewDeveloperSettings();
	assert.equal(r.title, "Developer settings - Toolhub");
	assert.ok(r.html.includes("Official Toolhub developer settings"));
	assert.ok(r.html.includes('href="/my-apps"'));
	assert.ok(r.html.includes("API token"));
	assert.ok(r.html.includes("Authorized apps"));
	assert.ok(r.html.includes('href="https://toolhub.wikimedia.org/developer-settings"'));
});

test("viewMyApps lists official Toolhub OAuth applications for the signed-in user", async () => {
	h.paginate.mockResolvedValue([
		{
			name: "Evolved client",
			redirectUrl: "https://toolhub-evolved.toolforge.org/oauth/callback",
			clientId: "abc123",
			username: "Ada Lovelace"
		},
		{
			name: "Someone else's client",
			redirectUrl: "https://example.org/callback",
			clientId: "def456",
			username: "Other User"
		}
	]);
	const r = await viewMyApps();
	assert.equal(r.title, "My apps - Toolhub");
	const [path, params, options] = h.paginate.mock.calls[0];
	assert.equal(path, "/oauth/applications/");
	assert.deepEqual(params, { user__username: "Ada Lovelace", ordering: "name" });
	assert.equal(options.pageSize, 100);
	assert.equal(options.maxPages, 20);
	assert.equal(typeof options.map, "function");
	assert.ok(r.html.includes("Evolved client"));
	assert.ok(r.html.includes("abc123"));
	assert.ok(r.html.includes("https://toolhub-evolved.toolforge.org/oauth/callback"));
	assert.ok(r.html.includes("1 app"));
	assert.ok(!r.html.includes("Someone else"));
});

test("viewMyApps renders an empty state", async () => {
	h.paginate.mockResolvedValue([]);
	const r = await viewMyApps();
	assert.ok(r.html.includes("No Toolhub OAuth applications are registered for this account."));
	assert.ok(r.html.includes("0 apps"));
});

test("viewMyApps reports load failures", async () => {
	h.paginate.mockRejectedValue(new Error("offline"));
	const r = await viewMyApps();
	assert.ok(r.html.includes("Unable to load your Toolhub OAuth applications right now."));
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

test("export action reports backend failures", async () => {
	h.backendGetJson.mockRejectedValue(new Error("offline"));
	const r = viewAccountSettings();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-export]").click();
	await tick();
	const out = document.querySelector("[data-account-result]");
	assert.equal(out.className, "at__result at__result--err");
	assert.equal(out.textContent, "Export failed: offline");
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

test("delete action handles an empty deletion summary", async () => {
	h.serverWrite.mockResolvedValue({});
	const r = viewAccountSettings();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-delete-evolved]").click();
	await tick();
	assert.equal(h.clearAll.mock.calls.length, 1);
	assert.ok(document.querySelector("[data-account-result]").textContent.includes("0 rows"));
});

test("delete action treats null row counts as zero", async () => {
	h.serverWrite.mockResolvedValue({ deleted: { favorites: null } });
	const r = viewAccountSettings();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-delete-evolved]").click();
	await tick();
	assert.equal(h.clearAll.mock.calls.length, 1);
	assert.ok(document.querySelector("[data-account-result]").textContent.includes("0 rows"));
});

test("delete action reports backend failures without clearing local cache", async () => {
	h.serverWrite.mockRejectedValue(new Error("permission denied"));
	const r = viewAccountSettings();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-delete-evolved]").click();
	await tick();
	const out = document.querySelector("[data-account-result]");
	assert.equal(out.className, "at__result at__result--err");
	assert.equal(out.textContent, "Delete failed: permission denied");
	assert.equal(h.clearAll.mock.calls.length, 0);
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
