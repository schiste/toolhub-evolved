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
const { viewAccountSettings, viewDeveloperSettings, viewMyTools } = await import("../../public_html/views/account.js");

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
	assert.ok(r.html.includes('href="/my-tools"'));
	assert.ok(r.html.includes("My apps"));
	assert.ok(
		r.html.includes('href="https://toolhub.wikimedia.org/api/oauth/applications/?user__username=Ada%20Lovelace"')
	);
	assert.ok(!r.html.includes('href="/my-apps"'));
	assert.ok(r.html.includes("API token"));
	assert.ok(r.html.includes("Authorized apps"));
	assert.ok(r.html.includes('href="https://toolhub.wikimedia.org/developer-settings"'));
});

test("viewMyTools lists official Toolhub tools owned by the signed-in user", async () => {
	h.paginate.mockResolvedValue([
		{
			name: "ada-tool",
			title: "Ada Tool",
			url: "https://example.org/ada",
			maintainer: "Ada Lovelace",
			authors: ["Ada Lovelace"],
			authorObjs: [],
			toolType: "web app",
			modified: "2026-01-01T00:00:00Z"
		},
		{
			name: "ada-developer-tool",
			title: "Ada Developer Tool",
			url: "",
			maintainer: "Different Display Name",
			authors: [],
			authorObjs: [
				{ name: "Different Display Name", url: null, wikiUsername: null, developerUsername: "Ada Lovelace" }
			],
			toolType: null,
			modified: null
		},
		{
			name: "other-tool",
			title: "Other Tool",
			url: "https://example.org/other",
			maintainer: "Other User",
			authors: ["Other User"],
			authorObjs: [],
			toolType: "bot",
			modified: "2026-01-01T00:00:00Z"
		}
	]);
	const r = await viewMyTools();
	assert.equal(r.title, "My tools - Toolhub");
	const [path, params, options] = h.paginate.mock.calls[0];
	assert.equal(path, "/search/tools/");
	assert.deepEqual(params, { author__term: "Ada Lovelace", ordering: "-score" });
	assert.equal(options.pageSize, 100);
	assert.equal(options.maxPages, 20);
	assert.equal(typeof options.map, "function");
	assert.ok(r.html.includes("Ada Tool"));
	assert.ok(r.html.includes("Ada Developer Tool"));
	assert.ok(r.html.includes("ada-tool"));
	assert.ok(r.html.includes("web app"));
	assert.ok(r.html.includes("https://example.org/ada"));
	assert.ok(r.html.includes("2 tools"));
	assert.ok(!r.html.includes("Other Tool"));
});

test("viewMyTools renders an empty state", async () => {
	h.paginate.mockResolvedValue([]);
	const r = await viewMyTools();
	assert.ok(r.html.includes("No Toolhub tools list this account as an author or maintainer."));
	assert.ok(r.html.includes("0 tools"));
});

test("viewMyTools reports load failures", async () => {
	h.paginate.mockRejectedValue(new Error("offline"));
	const r = await viewMyTools();
	assert.ok(r.html.includes("Unable to load your Toolhub tools right now."));
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
