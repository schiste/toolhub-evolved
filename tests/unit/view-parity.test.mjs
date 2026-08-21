// SPDX-License-Identifier: GPL-3.0-or-later
// cspell:words Wikitools
import assert from "node:assert/strict";
import { test, vi, beforeEach } from "vitest";
// apiGet hits the network and demoFeed reads localStorage; both are made deterministic.
// demoFeed is a pass-through so the live results render verbatim (and we assert the key
// it is called with). Everything else (esc, i18n, routing hrefs, avatar, metaItem) is real.
import { viewRecent, viewMembers, viewCrawler, viewAudit, targetHref } from "../../public_html/views/parity.js";
import * as api from "../../public_html/lib/core/api.js";
import { DEMO_KEYS } from "../../public_html/lib/core/store.js";

vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, apiGet: vi.fn(), backendGetJson: vi.fn() };
});
vi.mock("../../public_html/lib/core/store.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, demoFeed: vi.fn((_key, live) => live) };
});

// Clear call history (but keep the demoFeed pass-through impl) so each test inspects
// only its own apiGet/demoFeed calls.
beforeEach(() => {
	vi.clearAllMocks();
	api.backendGetJson.mockReset();
	localStorage.clear();
	document.body.innerHTML = "";
});

const setSearch = (search) => window.history.replaceState({}, "", `/recent${search}`);
const ISO = "2019-01-01T00:00:00Z";
const tick = () =>
	new Promise((resolve) => {
		setTimeout(resolve, 0);
	});

async function mountedHtml(view) {
	document.body.innerHTML = view.html;
	view.mount?.();
	await tick();
	await tick();
	return document.body.innerHTML;
}

/* ---- viewRecent -------------------------------------------------------- */

test("viewRecent: a tool change renders as a table row with owner and updater columns", async () => {
	setSearch("");
	api.apiGet.mockImplementation((path) => {
		if (path === "/recent/") {
			return Promise.resolve({
				results: [
					{
						content_type: "tool",
						content_id: "my-tool",
						content_title: "My Tool",
						user: { username: "alice" },
						timestamp: ISO,
						comment: "Initial listing"
					}
				]
			});
		}
		return Promise.reject(new Error(`unexpected ${path}`));
	});
	api.backendGetJson.mockResolvedValue({ owners: { "my-tool": "Ada Maintainer" } });
	const view = await viewRecent();

	assert.equal(view.title, "Recent changes — Toolhub");
	assert.deepEqual(api.apiGet.mock.calls[0], ["/recent/", { page_size: "30" }]);
	assert.equal(api.apiGet.mock.calls.length, 1);
	// demoFeed merges under the revisions key.
	const store = await import("../../public_html/lib/core/store.js");
	assert.equal(store.demoFeed.mock.calls[0][0], DEMO_KEYS.revisions);

	assert.match(view.html, /<table class="recent-table">/);
	assert.match(view.html, /<div class="recent-controls__filters">/);
	assert.match(view.html, /<div class="recent-controls__sortbar">/);
	assert.match(
		view.html,
		/<col class="recent-table__col recent-table__col--updated">\s*<col class="recent-table__col recent-table__col--item">/
	);
	assert.match(view.html, /<col class="recent-table__col recent-table__col--owner">/);
	assert.match(view.html, /<col class="recent-table__col recent-table__col--updated-by">/);
	assert.match(
		view.html,
		/<a class="recent-table__item" href="\/tools\/my-tool"><strong dir="auto">My Tool<\/strong>/
	);
	assert.match(view.html, /<span class="recent-table__id" dir="auto">my-tool<\/span>/);
	assert.match(view.html, /<span class="recent-chip recent-chip--tools">Tool<\/span>/);
	assert.match(
		view.html,
		/<td data-label="Tool owner" data-recent-owner-tool="my-tool"><span class="recent-table__muted">—<\/span><\/td>/
	);
	assert.match(
		view.html,
		/<td data-label="Last updated by"><a class="recent-table__person" href="\/by\/alice" dir="auto">alice<\/a><\/td>/
	);
	assert.match(view.html, /<td data-label="Action">Created<\/td>/);
	assert.match(view.html, /<span class="recent-chip recent-chip--unknown">Review unknown<\/span>/);
	assert.match(view.html, /<td data-label="Updated"><time datetime="2019-01-01T00:00:00\.000Z"/);
	assert.match(
		view.html,
		/<td data-label="Comment" class="recent-table__comment"><button class="recent-comment" type="button" aria-expanded="false"><span class="recent-comment__text" dir="auto">Initial listing<\/span><\/button><\/td>/
	);
	assert.match(view.html, /<th scope="col"><a href="\/recent\?sort=owner">Tool owner<\/a><\/th>/);
	assert.match(
		view.html,
		/<th scope="col" aria-sort="descending"><a href="\/recent\?dir=asc">Updated<span class="recent-table__sort recent-table__sort--desc" aria-hidden="true"><\/span>/
	);
	assert.doesNotMatch(view.html, /recent-summary|recent-stat__/);
	assert.doesNotMatch(view.html, /feed__ic recent-row__ic/);

	document.body.innerHTML = view.html;
	view.mount?.();
	await tick();
	assert.deepEqual(api.backendGetJson.mock.calls[0], ["/v1/recent/owners/?tool=my-tool"]);
	assert.equal(api.apiGet.mock.calls.filter((call) => call[0].startsWith("/tools/")).length, 0);
	assert.match(
		document.body.innerHTML,
		/<td data-label="Tool owner" data-recent-owner-tool="my-tool"><a class="recent-table__person" href="\/by\/Ada%20Maintainer" dir="auto">Ada Maintainer<\/a><\/td>/
	);
});

test("viewRecent: private favorite activity is removed from live and local rows", async () => {
	api.apiGet.mockResolvedValue({
		results: [
			{ content_type: "favorite", content_id: "private-live", content_title: "Private live favorite" },
			{ content_type: "tool", content_id: "public-tool", content_title: "Public tool" }
		]
	});
	const store = await import("../../public_html/lib/core/store.js");
	store.demoFeed.mockImplementationOnce((_key, live) => [
		{ action: "favorite-removed", target: { type: "favorite" }, content_title: "Private local favorite" },
		...live
	]);

	const view = await viewRecent();

	assert.match(view.html, /Public tool/);
	assert.doesNotMatch(view.html, /Private live favorite|Private local favorite/);
});

test("viewRecent: an unpublished Evolved list is removed while an officially synced one stays", async () => {
	setSearch("");
	api.apiGet.mockResolvedValue({ results: [] });
	const store = await import("../../public_html/lib/core/store.js");
	// Evolved always writes lists upstream as published, so an officially synced
	// row is public; a local fallback names a list that was never published.
	store.demoFeed.mockImplementationOnce((_key, live) => [
		{
			content_type: "list",
			content_id: "w-private",
			content_title: "Never published list",
			_evolved: true,
			officialStatus: "local_fallback"
		},
		{
			content_type: "list",
			content_id: "w-public",
			content_title: "Published list",
			_evolved: true,
			officialStatus: "official"
		},
		...live
	]);

	const view = await viewRecent();

	assert.match(view.html, /Published list/);
	assert.doesNotMatch(view.html, /Never published list/);
});

test("viewRecent: an upstream toollist row renders as a List with a list link", async () => {
	setSearch("");
	// Upstream Toolhub spells the list content type "toollist"; these rows have
	// already been vetted against the published-list replica by the backend.
	api.apiGet.mockResolvedValue({
		results: [{ content_type: "toollist", content_id: 861, content_title: "My Favorite Wikitools" }]
	});

	const view = await viewRecent();

	assert.match(view.html, /href="\/lists\/861"/);
	// The "lists" chip modifier proves the row also lands in the Lists filter bucket.
	assert.match(view.html, /recent-chip--lists">List</);
});

test("viewRecent: a cold list replica is explained instead of silently emptying the Lists filter", async () => {
	setSearch("");
	api.apiGet.mockResolvedValue({ listActivityAvailable: false, results: [] });

	const view = await viewRecent();

	assert.match(view.html, /role="status">List activity is hidden while the catalog replica/);
});

test("viewRecent: a warm replica and an unreachable feed both render without the notice", async () => {
	setSearch("");
	api.apiGet.mockResolvedValue({ listActivityAvailable: true, results: [] });
	const warm = await viewRecent();
	assert.doesNotMatch(warm.html, /List activity is hidden/);

	// A failed fetch says nothing about the replica, so it must not blame it.
	api.apiGet.mockRejectedValue(new Error("offline"));
	const offline = await viewRecent();
	assert.doesNotMatch(offline.html, /List activity is hidden/);
});

test("viewRecent: a deferred owner is not written to the client cache", async () => {
	setSearch("");
	api.apiGet.mockImplementation((path) => {
		if (path === "/recent/") {
			return Promise.resolve({
				results: [
					{ content_type: "tool", content_id: "warm-tool", content_title: "Warm", timestamp: ISO },
					{ content_type: "tool", content_id: "cold-tool", content_title: "Cold", timestamp: ISO }
				]
			});
		}
		return Promise.reject(new Error(`unexpected ${path}`));
	});
	// The server resolved one name and ran out of fetch budget on the other.
	api.backendGetJson.mockResolvedValue({
		owners: { "warm-tool": "Ada Maintainer", "cold-tool": "" },
		meta: { "warm-tool": { source: "toolhub_detail" }, "cold-tool": { source: "deferred" } }
	});
	const view = await viewRecent();
	document.body.innerHTML = view.html;
	view.mount?.();
	await tick();

	const store = await import("../../public_html/lib/core/store.js");
	assert.equal(store.recentOwnerCacheGet("warm-tool"), "Ada Maintainer");
	// Undefined, not "": missingOwnerNames() must ask for this one again next load.
	assert.equal(store.recentOwnerCacheGet("cold-tool"), undefined);
});

test("viewRecent: cached owner enrichment renders synchronously and skips repeated detail fetches", async () => {
	setSearch("");
	api.apiGet.mockImplementation((path) => {
		if (path === "/recent/") {
			return Promise.resolve({
				results: [
					{
						content_type: "tool",
						content_id: "my-tool",
						content_title: "My Tool",
						timestamp: ISO
					}
				]
			});
		}
		return Promise.reject(new Error(`unexpected ${path}`));
	});
	api.backendGetJson.mockResolvedValue({ owners: { "my-tool": "Ada Maintainer" } });
	const first = await viewRecent();
	document.body.innerHTML = first.html;
	first.mount?.();
	await tick();
	assert.equal(api.backendGetJson.mock.calls.length, 1);

	vi.clearAllMocks();
	api.apiGet.mockImplementation((path) => {
		if (path === "/recent/") {
			return Promise.resolve({
				results: [
					{
						content_type: "tool",
						content_id: "my-tool",
						content_title: "My Tool",
						timestamp: ISO
					}
				]
			});
		}
		return Promise.reject(new Error(`unexpected ${path}`));
	});
	const second = await viewRecent();
	assert.match(
		second.html,
		/<td data-label="Tool owner" data-recent-owner-tool="my-tool"><a class="recent-table__person" href="\/by\/Ada%20Maintainer" dir="auto">Ada Maintainer<\/a><\/td>/
	);
	assert.deepEqual(api.apiGet.mock.calls, [["/recent/", { page_size: "30" }]]);
	assert.equal(api.backendGetJson.mock.calls.length, 0);
});

test("viewRecent: progressive owner enrichment dedupes repeated tools", async () => {
	setSearch("");
	api.apiGet.mockImplementation((path) => {
		if (path === "/recent/") {
			return Promise.resolve({
				results: [
					{ content_type: "tool", content_id: "same-tool", content_title: "One", timestamp: ISO },
					{ content_type: "tool", content_id: "same-tool", content_title: "Two", timestamp: ISO }
				]
			});
		}
		return Promise.reject(new Error(`unexpected ${path}`));
	});
	api.backendGetJson.mockResolvedValue({ owners: { "same-tool": "One Owner" } });
	const view = await viewRecent();
	document.body.innerHTML = view.html;
	view.mount?.();
	await tick();

	assert.deepEqual(api.backendGetJson.mock.calls, [["/v1/recent/owners/?tool=same-tool"]]);
	assert.equal(api.apiGet.mock.calls.filter((call) => call[0].startsWith("/tools/")).length, 0);
	assert.equal(document.querySelectorAll('[data-recent-owner-tool="same-tool"] a.recent-table__person').length, 2);
	assert.match(document.body.innerHTML, /One Owner/);
});

test("viewRecent: a list change uses content_id when title is absent and links via listHref", async () => {
	setSearch("");
	api.apiGet.mockResolvedValue({ results: [{ content_type: "list", content_id: "42", user: {}, timestamp: ISO }] });
	const view = await viewRecent();
	assert.match(view.html, /<a class="recent-table__item" href="\/lists\/42"><strong dir="auto">42<\/strong>/);
	assert.match(view.html, /<span class="recent-table__id" dir="auto">42<\/span>/);
	assert.match(view.html, /<span class="recent-chip recent-chip--lists">List<\/span>/);
	// user:{} (present but no username) still falls back to "system".
	assert.match(
		view.html,
		/<td data-label="Last updated by"><a class="recent-table__person" href="\/crawler-history" dir="auto">system<\/a><\/td>/
	);
});

test("viewRecent: untyped change renders static with dash/item/system defaults", async () => {
	setSearch("");
	api.apiGet.mockResolvedValue({ results: [{ timestamp: ISO }] });
	const view = await viewRecent();
	assert.match(view.html, /<span class="recent-table__item"><strong dir="auto">—<\/strong><\/span>/);
	assert.match(view.html, /<span class="recent-chip recent-chip--other">Other<\/span>/);
	assert.match(
		view.html,
		/<td data-label="Last updated by"><a class="recent-table__person" href="\/crawler-history" dir="auto">system<\/a><\/td>/
	);
	assert.match(view.html, /<td data-label="Tool owner"><span class="recent-table__muted">—<\/span><\/td>/);
	assert.doesNotMatch(view.html, /<a href="\/tools/);
});

test("viewRecent: Toolhub owner and updater link to crawler history", async () => {
	setSearch("");
	api.apiGet.mockResolvedValue({
		results: [
			{
				content_type: "tool",
				content_id: "crawler-tool",
				content_title: "Crawler Tool",
				owner: "Toolhub",
				user: { username: "Toolhub" },
				timestamp: ISO
			}
		]
	});
	const view = await viewRecent();
	assert.match(
		view.html,
		/<td data-label="Tool owner" data-recent-owner-tool="crawler-tool"><a class="recent-table__person" href="\/crawler-history" dir="auto">Toolhub<\/a><\/td>/
	);
	assert.match(
		view.html,
		/<td data-label="Last updated by"><a class="recent-table__person" href="\/crawler-history" dir="auto">Toolhub<\/a><\/td>/
	);
});

test("viewRecent: typed changes without an id never become links", async () => {
	setSearch("");
	api.apiGet.mockResolvedValue({
		results: [
			{ content_type: "tool", content_title: "NoId Tool" },
			{ content_type: "list", content_title: "NoId List" }
		]
	});
	const view = await viewRecent();
	assert.doesNotMatch(view.html, /<a href="\/tools/);
	assert.doesNotMatch(view.html, /<a href="\/lists/);
	assert.match(view.html, /<strong dir="auto">NoId Tool<\/strong>/);
	assert.match(view.html, /<strong dir="auto">NoId List<\/strong>/);
});

test("viewRecent: each filter keeps only its own content type", async () => {
	const results = [
		{ content_type: "tool", content_id: "t", content_title: "T", timestamp: ISO },
		{ content_type: "list", content_id: "l", content_title: "L", timestamp: ISO },
		{ content_type: "category", content_id: "c", content_title: "C", timestamp: ISO }
	];
	api.apiGet.mockResolvedValue({ results });

	setSearch("?show=tools");
	let view = await viewRecent();
	assert.match(view.html, />T</);
	assert.doesNotMatch(view.html, />L</);
	assert.doesNotMatch(view.html, />C</);
	assert.match(
		view.html,
		/<select id="recent-show"><option value="all">All<\/option><option value="tools" selected>Tools<\/option>/
	);

	setSearch("?show=lists");
	view = await viewRecent();
	assert.match(view.html, />L</);
	assert.doesNotMatch(view.html, />T</);

	setSearch("?show=other");
	view = await viewRecent();
	assert.match(view.html, />C</);
	assert.doesNotMatch(view.html, />T</);

	setSearch("?show=all");
	view = await viewRecent();
	assert.match(view.html, />T</);
	assert.match(view.html, />L</);
	assert.match(view.html, />C</);
	// Three rows joined with "" → adjacent <tr>s (kills the rows .join("") separator).
	assert.match(view.html, /<\/tr><tr>/);
	// A "category" change has an id but is neither tool nor list → static, never a list link
	// (kills `r.content_type === "list"` → `true`).
	assert.doesNotMatch(view.html, /href="\/lists\/c"/);
	// The Lists/Other filter labels render (kills their label string literals).
	assert.match(view.html, /<option value="lists">Lists<\/option>/);
	assert.match(view.html, /<option value="other">Other<\/option>/);
});

test("viewRecent: an unknown show falls back to all", async () => {
	setSearch("?show=banana");
	api.apiGet.mockResolvedValue({
		results: [{ content_type: "tool", content_id: "t", content_title: "Kept", timestamp: ISO }]
	});
	const view = await viewRecent();
	assert.match(view.html, />Kept</);
	assert.match(view.html, /<select id="recent-show"><option value="all" selected>All<\/option>/);
	assert.doesNotMatch(view.html, /Patrolled and unpatrolled/);
});

test("viewRecent: legacy patrol show params map to real review-state filters", async () => {
	api.apiGet.mockResolvedValue({
		results: [
			{ content_type: "tool", content_id: "yes", content_title: "Reviewed", patrolled: true, timestamp: ISO },
			{ content_type: "tool", content_id: "no", content_title: "Needs Work", patrolled: false, timestamp: ISO }
		]
	});

	setSearch("?show=patrolled");
	let view = await viewRecent();
	assert.match(view.html, />Reviewed</);
	assert.doesNotMatch(view.html, />Needs Work</);
	assert.match(view.html, /<option value="patrolled" selected>Patrolled<\/option>/);
	assert.match(view.html, /<select id="recent-show"><option value="all" selected>All<\/option>/);

	// "unpatrolled" is the second legacy patrol value.
	setSearch("?show=unpatrolled");
	view = await viewRecent();
	assert.match(view.html, />Needs Work</);
	assert.doesNotMatch(view.html, />Reviewed</);
	assert.match(view.html, /<option value="unpatrolled" selected>Needs review<\/option>/);
});

test("viewRecent: sort=oldest maps to updated ascending and marks the direction select", async () => {
	setSearch("?sort=oldest");
	api.apiGet.mockResolvedValue({
		results: [
			{ content_type: "tool", content_id: "new", content_title: "Newer", timestamp: "2020-01-01T00:00:00Z" },
			{ content_type: "tool", content_id: "old", content_title: "Older", timestamp: "2018-01-01T00:00:00Z" }
		]
	});
	const view = await viewRecent();
	assert.ok(view.html.indexOf(">Older<") < view.html.indexOf(">Newer<"));
	assert.match(view.html, /<option value="updated" selected>Updated<\/option>/);
	assert.match(view.html, /<option value="asc" selected>Ascending<\/option>/);
	assert.match(view.html, /aria-sort="ascending"><a href="\/recent">Updated/);
});

test("viewRecent: text filters can narrow by owner, updater and free text", async () => {
	setSearch("?owner=ada&user=alice&q=fixed&sort=owner&dir=desc");
	api.apiGet.mockImplementation((path) => {
		if (path === "/recent/") {
			return Promise.resolve({
				results: [
					{
						content_type: "tool",
						content_id: "alpha",
						content_title: "Alpha",
						user: { username: "alice" },
						comment: "Fixed docs",
						timestamp: "2020-01-01T00:00:00Z"
					},
					{
						content_type: "tool",
						content_id: "beta",
						content_title: "Beta",
						user: { username: "bob" },
						comment: "Fixed docs",
						timestamp: "2020-01-02T00:00:00Z"
					}
				]
			});
		}
		return Promise.reject(new Error(`unexpected ${path}`));
	});
	api.backendGetJson.mockResolvedValue({ owners: { alpha: "Ada Maintainer", beta: "Bob Maintainer" } });
	const view = await viewRecent();
	assert.doesNotMatch(view.html, />Alpha</);
	document.body.innerHTML = view.html;
	view.mount?.();
	await tick();
	assert.equal(api.apiGet.mock.calls.filter((call) => call[0].startsWith("/tools/")).length, 0);
	assert.deepEqual(api.backendGetJson.mock.calls, [["/v1/recent/owners/?tool=alpha&tool=beta"]]);
	assert.match(document.body.innerHTML, />Alpha</);
	assert.doesNotMatch(document.body.innerHTML, />Beta</);
	assert.match(view.html, /id="recent-owner" type="search" value="ada"/);
	assert.match(view.html, /id="recent-user" type="search" value="alice"/);
	assert.match(view.html, /id="recent-q" type="search" value="fixed"/);
	assert.match(view.html, /<option value="owner" selected>Tool owner<\/option>/);
	assert.match(view.html, /<option value="desc" selected>Descending<\/option>/);
});

test("viewRecent mount: changing sort and review state updates the route", async () => {
	setSearch("?show=tools");
	api.apiGet.mockResolvedValue({ results: [] });
	const view = await viewRecent();
	document.body.innerHTML = view.html;
	view.mount?.();

	const sort = document.querySelector("#recent-sort");
	assert.ok(sort);
	sort.value = "updated_by";
	sort.dispatchEvent(new Event("change", { bubbles: true }));
	assert.equal(location.pathname + location.search, "/recent?show=tools&sort=updated_by&dir=desc");

	const status = document.querySelector("#recent-status");
	assert.ok(status);
	status.value = "unpatrolled";
	status.dispatchEvent(new Event("change", { bubbles: true }));
	assert.equal(location.pathname + location.search, "/recent?show=tools&status=unpatrolled&sort=updated_by&dir=desc");

	const form = document.querySelector("#recent-filter-form");
	assert.ok(form);
	/** @type {HTMLInputElement} */ (document.querySelector("#recent-status")).value = "all";
	/** @type {HTMLInputElement} */ (document.querySelector("#recent-sort")).value = "updated";
	/** @type {HTMLInputElement} */ (document.querySelector("#recent-dir")).value = "desc";
	/** @type {HTMLInputElement} */ (document.querySelector("#recent-owner")).value = "Ada";
	form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
	assert.equal(location.pathname + location.search, "/recent?show=tools&owner=Ada");
});

test("viewRecent mount: clicking a comment expands only that row", async () => {
	setSearch("");
	api.apiGet.mockResolvedValue({
		results: [
			{ content_type: "list", content_id: "1", comment: "First long import comment", timestamp: ISO },
			{ content_type: "list", content_id: "2", comment: "Second long import comment", timestamp: ISO }
		]
	});
	const view = await viewRecent();
	document.body.innerHTML = view.html;
	view.mount?.();

	const comments = [...document.querySelectorAll(".recent-comment")];
	assert.equal(comments.length, 2);
	assert.equal(comments[0].getAttribute("aria-expanded"), "false");
	assert.equal(comments[1].getAttribute("aria-expanded"), "false");

	comments[0].click();
	assert.equal(comments[0].getAttribute("aria-expanded"), "true");
	assert.equal(comments[1].getAttribute("aria-expanded"), "false");

	comments[0].click();
	assert.equal(comments[0].getAttribute("aria-expanded"), "false");
});

test("viewRecent: an API failure yields the empty placeholder", async () => {
	setSearch("");
	api.apiGet.mockRejectedValue(new Error("down"));
	const view = await viewRecent();
	assert.match(
		view.html,
		/<tbody data-recent-body><tr><td class="recent-empty" colspan="8">No recent changes\.<\/td><\/tr><\/tbody>/
	);
});

test("viewRecent: a response with no results array also shows the placeholder", async () => {
	setSearch("");
	api.apiGet.mockResolvedValue({});
	const view = await viewRecent();
	assert.match(view.html, /No recent changes\./);
});

/* ---- legacy viewMembers alias ----------------------------------------- */

test("viewMembers renders the unified directory and replaces the legacy URL", async () => {
	window.history.replaceState({}, "", "/members");
	api.backendGetJson.mockResolvedValue({
		count: 0,
		page: 1,
		pageSize: 24,
		pageCount: 1,
		results: [],
		counts: { people: 0, accounts: 0, unresolvedAttributions: 0 },
		accountSync: { status: "ready", complete: true }
	});
	const view = await viewMembers();
	assert.equal(view.title, "Community directory — Toolhub");
	assert.deepEqual(api.backendGetJson.mock.calls[0], ["/v1/community/?page_size=24&ordering=relevance"]);
	assert.match(view.html, /Community directory/);
	assert.match(view.html, /Search people, usernames, and tools in one place/);
	view.mount();
	assert.equal(location.pathname, "/people");
	assert.equal(new URLSearchParams(location.search).get("view"), null);
});

/* ---- viewCrawler ------------------------------------------------------- */

test("viewCrawler: renders meta from the first run and a row per run", async () => {
	api.apiGet.mockResolvedValue({
		results: [
			{ start_date: ISO, crawled_urls: 10, new_tools: 2, updated_tools: 3, total_tools: 100 },
			{} // missing fields → fmt(0) everywhere
		]
	});
	const view = await viewCrawler();
	assert.equal(view.title, "Crawler history — Toolhub");
	assert.equal(api.apiGet.mock.calls.length, 0);
	assert.match(view.html, /data-crawler-history-content aria-live="polite" aria-busy="true"/);
	const html = await mountedHtml(view);
	assert.deepEqual(api.apiGet.mock.calls[0], ["/crawler/runs/", { page_size: "12" }]);
	// Header meta uses runs[0].
	assert.match(html, /<div class="meta__k">URLs crawled<\/div><div class="meta__v" dir="auto">10<\/div>/);
	assert.match(html, /<div class="meta__k">Updated in last run<\/div><div class="meta__v" dir="auto">3<\/div>/);
	assert.match(html, /<div class="meta__k">Last crawl<\/div><div class="meta__v" dir="auto"><time/);
	assert.match(html, /<section class="crawler-graph" aria-labelledby="crawler-graph-title">/);
	assert.match(html, /<polyline class="crawler-graph__line" points="/);
	assert.match(html, /<rect class="crawler-graph__bar-updated"/);
	assert.match(html, /<rect class="crawler-graph__bar-new"/);
	// First data row.
	assert.match(html, /<td>10<\/td>\s*<td>2<\/td><td>3<\/td><td>100<\/td>/);
	// Second (empty) row → zeros.
	assert.match(html, /<td>0<\/td>\s*(?:<td>0<\/td>){3}/);
	// Two rows joined with "" → first row's </tr> meets the second row (kills the .join("")).
	assert.match(html, /<\/tr>\s*<tr>/);
});

test("viewCrawler: a response with no results array renders an empty state", async () => {
	// data.results undefined → the `|| []` fallback must stay empty (no phantom row).
	api.apiGet.mockResolvedValue({});
	const view = await viewCrawler();
	const html = await mountedHtml(view);
	assert.match(html, /<section class="crawler-graph crawler-graph--empty" aria-label="Crawler run graph">/);
	assert.match(html, /No crawler runs are available right now\./);
});

test("viewCrawler: no runs → dash meta, zero urls and an empty state", async () => {
	api.apiGet.mockRejectedValue(new Error("x"));
	const view = await viewCrawler();
	const html = await mountedHtml(view);
	assert.match(html, /<div class="meta__k">Last crawl<\/div><div class="meta__v" dir="auto">—<\/div>/);
	assert.match(html, /<div class="meta__k">URLs crawled<\/div><div class="meta__v" dir="auto">0<\/div>/);
	assert.match(html, /No crawler run data to graph yet\./);
	assert.match(html, /No crawler runs are available right now\./);
});

/* ---- targetHref -------------------------------------------------------- */

test("targetHref maps tool/list targets and returns null for everything else", () => {
	assert.equal(targetHref({ id: "x", type: "tool" }), "/tools/x");
	assert.equal(targetHref({ id: "y", type: "list" }), "/lists/y");
	assert.equal(targetHref({ id: "z", type: "other" }), null);
	assert.equal(targetHref({ type: "tool" }), null); // no id
	assert.equal(targetHref(null), null);
	assert.equal(targetHref(undefined), null);
});

/* ---- viewAudit --------------------------------------------------------- */

test("viewAudit: a linked tool entry and a static entry render who/action/target", async () => {
	api.apiGet.mockResolvedValue({
		results: [
			{
				user: { username: "mod" },
				action: "deleted",
				target: { id: "t1", type: "tool", label: "Tool 1" },
				timestamp: ISO
			},
			// user:{} (present, no username) → "System"; no target/action → "changed" + empty target.
			{ user: {}, timestamp: ISO }
		]
	});
	const view = await viewAudit();
	assert.equal(view.title, "Audit logs — Toolhub");
	assert.deepEqual(api.apiGet.mock.calls[0], ["/auditlogs/", { page_size: "25" }]);
	const store = await import("../../public_html/lib/core/store.js");
	assert.equal(store.demoFeed.mock.calls.at(-1)[0], DEMO_KEYS.auditlogs);
	assert.match(view.html, /<li><a href="\/tools\/t1"><svg class="icon feed__ic"/);
	assert.match(view.html, /<span dir="auto">mod<\/span> <em>deleted<\/em> <span dir="auto">tool “Tool 1”<\/span>/);
	assert.match(view.html, /<time class="feed__when" datetime="2019-01-01T00:00:00\.000Z"/);
	// Static (target-less) row with System/changed defaults.
	assert.match(view.html, /<li><div class="feed__static"><svg/);
	assert.match(view.html, /<span dir="auto">System<\/span> <em>changed<\/em> <span dir="auto"><\/span>/);
	// Two rows joined with "" → adjacent <li>s (kills the rows .join("") separator).
	assert.match(view.html, /<\/li><li>/);
});

test("viewAudit: no entries → the empty placeholder", async () => {
	api.apiGet.mockRejectedValue(new Error("x"));
	const view = await viewAudit();
	assert.match(view.html, /<ul class="feed"><li><div class="feed__static">No audit entries\.<\/div><\/li><\/ul>/);
});

test("viewAudit: private favorite actions are not rendered", async () => {
	api.apiGet.mockResolvedValue({
		results: [
			{ action: "favorited", target: { type: "favorite", id: "private-tool", label: "Private tool" } },
			{ action: "updated", target: { type: "tool", id: "public-tool", label: "Public tool" } }
		]
	});

	const view = await viewAudit();

	assert.match(view.html, /Public tool/);
	assert.doesNotMatch(view.html, /Private tool|favorited/);
});

test("viewAudit: a response with no results array also shows the placeholder", async () => {
	// data.results undefined → the `|| []` fallback must stay empty (no phantom entry).
	api.apiGet.mockResolvedValue({});
	const view = await viewAudit();
	assert.match(view.html, /No audit entries\./);
});
