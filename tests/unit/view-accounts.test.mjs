// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";
import { accountDirectoryHref, accountDirectoryState, viewAccounts } from "../../public_html/views/accounts.js";

const h = vi.hoisted(() => ({ backendGetJson: vi.fn() }));

vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, backendGetJson: h.backendGetJson };
});

const readyDirectory = {
	count: 2313,
	page: 1,
	pageSize: 24,
	pageCount: 97,
	results: [
		{
			id: "42",
			username: "A very long official account name that must stay fully visible",
			groups: ["user", "admin"],
			dateJoined: "2024-01-02T00:00:00Z",
			personId: "person-42",
			identityLinkStatus: "linked"
		}
	],
	sync: { status: "ready", complete: true, lastCompletedAt: "2026-08-07T00:00:00Z" }
};

beforeEach(() => {
	window.history.replaceState({}, "", "/people?view=accounts");
	document.body.innerHTML = "";
	h.backendGetJson.mockReset();
});

test("accountDirectoryState validates a shareable filter and detail state", () => {
	assert.deepEqual(
		accountDirectoryState(
			new URLSearchParams("view=accounts&q=Magnus&page=3&page_size=48&group=admin&ordering=recent&account=42")
		),
		{ q: "Magnus", page: 3, pageSize: 48, group: "admin", ordering: "recent", accountId: "42" }
	);
	assert.deepEqual(accountDirectoryState(new URLSearchParams("page=0&page_size=500&ordering=random")), {
		q: "",
		page: 1,
		pageSize: 24,
		group: "",
		ordering: "name",
		accountId: ""
	});
});

test("account directory renders all-count pagination, links, and full names from the local API", async () => {
	h.backendGetJson.mockResolvedValue(readyDirectory);
	const view = await viewAccounts();

	assert.equal(view.title, "Accounts — Toolhub");
	assert.match(h.backendGetJson.mock.calls[0][0], /^\/v1\/accounts\//);
	assert.match(view.html, /Showing 1–1 of 2313 accounts/);
	assert.match(view.html, /href="\/people\?account=42"/);
	assert.match(view.html, /A very long official account name that must stay fully visible/);
	assert.doesNotMatch(view.html, /text-overflow|title="A very long/);
	assert.match(view.html, /Linked to a public person through a stable identifier/);
});

test("account search and pagination preserve filters in browser history", async () => {
	window.history.replaceState({}, "", "/people?view=accounts&q=Ada&group=admin");
	h.backendGetJson.mockResolvedValue({ ...readyDirectory, pageCount: 3 });
	const view = await viewAccounts();
	document.body.innerHTML = view.html;
	view.mount();

	document.querySelector('[data-account-pager] [data-page="2"]').click();
	let params = new URLSearchParams(location.search);
	assert.equal(params.get("view"), null);
	assert.equal(params.get("q"), "Ada");
	assert.equal(params.get("group"), "admin");
	assert.equal(params.get("page"), "2");

	window.history.replaceState({}, "", "/people?view=accounts");
	document.querySelector('[name="q"]').value = "Manske";
	document.querySelector('[name="ordering"]').value = "recent";
	document.querySelector("[data-account-search]").dispatchEvent(new Event("submit", { cancelable: true }));
	params = new URLSearchParams(location.search);
	assert.equal(params.get("q"), "Manske");
	assert.equal(params.get("ordering"), "recent");
	assert.equal(params.has("page"), false);
});

test("account detail exposes registration facts and only a backend-approved person link", async () => {
	window.history.replaceState({}, "", "/people?view=accounts&q=Ada&account=42");
	h.backendGetJson.mockResolvedValue({
		...readyDirectory.results[0],
		wikimediaGlobalUserId: "9001",
		wikimediaRegisteredAt: "2008-04-03T00:00:00Z",
		sync: readyDirectory.sync
	});
	const view = await viewAccounts();

	assert.equal(h.backendGetJson.mock.calls[0][0], "/v1/accounts/42/");
	assert.match(view.html, /Toolhub user ID/);
	assert.match(view.html, /Wikimedia global user ID/);
	assert.match(view.html, /href="\/people\/person-42"/);
	assert.match(view.html, /href="\/people\?q=Ada"/);
});

test("conflicted stable identifiers never produce an account-to-person link", async () => {
	window.history.replaceState({}, "", "/people?view=accounts&account=42");
	h.backendGetJson.mockResolvedValue({
		...readyDirectory.results[0],
		personId: null,
		identityLinkStatus: "conflict",
		sync: readyDirectory.sync
	});
	const view = await viewAccounts();

	assert.match(view.html, /Stable identifiers point to different people/);
	assert.doesNotMatch(view.html, /href="\/people\/person-/);
});

test("failed and unavailable requests are not rendered as zero accounts", async () => {
	h.backendGetJson.mockRejectedValueOnce(new Error("offline"));
	let view = await viewAccounts();
	assert.match(view.html, /role="alert"/);
	assert.match(view.html, /This is not a zero-account result/);
	assert.match(view.html, /data-account-retry/);

	h.backendGetJson.mockResolvedValueOnce({
		count: 0,
		page: 1,
		pageSize: 24,
		pageCount: 1,
		results: [],
		sync: { status: "building", complete: false }
	});
	view = await viewAccounts();
	assert.match(view.html, /first complete official account refresh is still in progress/);
	assert.doesNotMatch(view.html, /No official accounts are present/);
});

test("stale completed projections remain browsable with an explicit warning", async () => {
	h.backendGetJson.mockResolvedValue({
		...readyDirectory,
		sync: { status: "stale", complete: true, lastCompletedAt: "2026-08-06T00:00:00Z" }
	});
	const view = await viewAccounts();
	assert.match(view.html, /Showing a stale account cache/);
	assert.match(view.html, /Official Toolhub accounts/);
});

test("accountDirectoryHref retains account filters while adding and removing detail state", () => {
	const state = { q: "Ada", page: 2, pageSize: 48, group: "admin", ordering: "recent", accountId: "" };
	assert.equal(
		accountDirectoryHref(state, { accountId: "42" }),
		"/people?q=Ada&group=admin&ordering=recent&page_size=48&page=2&account=42"
	);
	assert.equal(
		accountDirectoryHref(state, { accountId: "", page: 1 }),
		"/people?q=Ada&group=admin&ordering=recent&page_size=48"
	);
});
