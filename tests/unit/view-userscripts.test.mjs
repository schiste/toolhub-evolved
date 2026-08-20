// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";
import { userScriptHref, userScriptState, viewUserScripts } from "../../public_html/views/userscripts.js";

const h = vi.hoisted(() => ({ fetchRead: vi.fn() }));

vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, fetchRead: h.fetchRead };
});

/** @param {any} data @param {boolean} [ok] */
const json = (data, ok = true) => Promise.resolve({ ok, json: () => Promise.resolve(data) });

const coverage = {
	wiki: "fr.wikipedia.org",
	pages: 2051,
	sweepsCompleted: 3,
	sweptAt: "2026-08-19T00:00:00Z",
	computedAt: "2026-08-19T01:00:00Z",
	active: 603,
	archive: 661
};

const wikis = { count: 1, results: [coverage] };

const listing = {
	wiki: "fr.wikipedia.org",
	tier: "active",
	count: 2,
	total: 603,
	limit: 25,
	offset: 0,
	results: [
		{
			wiki: "fr.wikipedia.org",
			title: "Utilisateur:Zebulon84/xpatrol.js",
			owner: "Zebulon84",
			basename: "xpatrol.js",
			tier: "active",
			demand: 188,
			instances: 13,
			position: 1
		},
		{
			wiki: "fr.wikipedia.org",
			title: "Utilisateur:Od1n/DrapeauJaune.js",
			owner: "Od1n",
			basename: "DrapeauJaune.js",
			tier: "active",
			demand: 150,
			instances: 1,
			position: 2
		}
	],
	coverage
};

/** Route every request this view can make to its own fixture. */
function respond({ script = null, directory = listing, wikiList = wikis } = {}) {
	h.fetchRead.mockImplementation((path) => {
		if (path.startsWith("/v1/userscripts/wikis/")) return json(wikiList);
		if (path.startsWith("/v1/userscripts/script/")) return json(script?.body, script?.ok !== false);
		return json(directory);
	});
}

beforeEach(() => {
	window.history.replaceState({}, "", "/userscripts");
	document.body.innerHTML = "";
	h.fetchRead.mockReset();
});

test("userScriptState keeps a shareable filter and rejects nonsense", () => {
	assert.deepEqual(
		userScriptState(new URLSearchParams("wiki=fr.wikipedia.org&tier=archive&owner=Od1n&page=3&script=A.js")),
		{ wiki: "fr.wikipedia.org", tier: "archive", owner: "Od1n", page: 3, script: "A.js" }
	);
	assert.deepEqual(userScriptState(new URLSearchParams("tier=everything&page=-2")), {
		wiki: "",
		tier: "active",
		owner: "",
		page: 1,
		script: ""
	});
});

test("userScriptHref writes only the state that differs from the default", () => {
	const state = { wiki: "fr.wikipedia.org", tier: "active", owner: "", page: 1, script: "" };
	assert.equal(userScriptHref(state), "/userscripts?wiki=fr.wikipedia.org");
	assert.equal(
		userScriptHref(state, { tier: "archive", owner: "Od1n", page: 2 }),
		"/userscripts?wiki=fr.wikipedia.org&tier=archive&owner=Od1n&page=2"
	);
	assert.equal(
		userScriptHref(state, { script: "Utilisateur:Od1n/a.js" }),
		"/userscripts?wiki=fr.wikipedia.org&script=Utilisateur%3AOd1n%2Fa.js"
	);
});

test("the directory ranks scripts by the people loading them and links each one", async () => {
	respond();
	const view = await viewUserScripts();

	assert.equal(view.title, "User scripts — Toolhub");
	assert.deepEqual(view.styles, ["/styles/userscripts.css"]);
	assert.match(h.fetchRead.mock.calls[1][0], /wiki=fr\.wikipedia\.org&tier=active&owner=&limit=25&offset=0/);
	assert.match(view.html, /Showing 2 of 603 scripts/);
	assert.match(view.html, /xpatrol\.js/);
	assert.match(view.html, /script=Utilisateur%3AZebulon84%2Fxpatrol\.js/);
	assert.match(view.html, /owner=Zebulon84/);
	assert.match(view.html, /In use \(603\)/);
	assert.match(view.html, /Archive \(661\)/);
	assert.match(view.html, /Script pages seen/);
	assert.doesNotMatch(view.html, /counts are a floor/);
});

test("a wiki with no finished sweep says its counts are a floor", async () => {
	const unswept = { ...coverage, sweptAt: "", active: 0, archive: 0 };
	respond({
		wikiList: { count: 1, results: [unswept] },
		directory: { ...listing, count: 0, total: 0, results: [], coverage: unswept }
	});
	const view = await viewUserScripts();
	assert.match(view.html, /No full sweep of this wiki has finished yet/);
	assert.match(view.html, /No scripts are filed in this tier yet/);
});

test("no swept wiki at all is stated rather than shown as an empty ranking", async () => {
	respond({ wikiList: { count: 0, results: [] } });
	const view = await viewUserScripts();
	assert.match(view.html, /No wiki has been swept for user scripts yet/);
	assert.doesNotMatch(view.html, /<table/);
	assert.equal(h.fetchRead.mock.calls.length, 1);
});

test("an empty tier and an empty owner filter say different things", async () => {
	respond({ directory: { ...listing, count: 0, total: 0, results: [] } });
	let view = await viewUserScripts();
	assert.match(view.html, /No scripts are filed in this tier yet/);

	window.history.replaceState({}, "", "/userscripts?wiki=fr.wikipedia.org&owner=Nobody");
	view = await viewUserScripts();
	assert.match(view.html, /No scripts in this tier belong to Nobody/);
});

test("one script lists the pages folded under it and where to read the source", async () => {
	window.history.replaceState(
		{},
		"",
		"/userscripts?wiki=fr.wikipedia.org&script=Utilisateur%3AZebulon84%2Fxpatrol.js"
	);
	respond({
		script: {
			body: {
				...listing.results[0],
				members: [
					{ title: "Utilisateur:Ada/xpatrol.js", relation: "copy" },
					{ title: "Utilisateur:Grace/xpatrol.js", relation: "variant" }
				],
				coverage
			}
		}
	});
	const view = await viewUserScripts();

	assert.match(h.fetchRead.mock.calls[1][0], /title=Utilisateur%3AZebulon84%2Fxpatrol\.js/);
	assert.match(view.html, /Utilisateur:Ada\/xpatrol\.js/);
	assert.match(view.html, /Identical copy/);
	assert.match(view.html, /Same name, different code/);
	assert.match(view.html, /href="https:\/\/fr\.wikipedia\.org\/wiki\/Utilisateur%3AZebulon84%2Fxpatrol\.js"/);
	assert.match(view.html, /Back to the directory/);
});

test("a script nothing was folded into says so", async () => {
	window.history.replaceState({}, "", "/userscripts?wiki=fr.wikipedia.org&script=A.js");
	respond({ script: { body: { ...listing.results[1], members: [], coverage } } });
	const view = await viewUserScripts();
	assert.match(view.html, /No other page was folded into this script/);
});

test("a folded page is pointed at the entry it was filed under", async () => {
	window.history.replaceState({}, "", "/userscripts?wiki=fr.wikipedia.org&script=Utilisateur%3AAda%2Fxpatrol.js");
	respond({
		script: { ok: false, body: { error: "not an original", filedUnder: "Utilisateur:Zebulon84/xpatrol.js" } }
	});
	const view = await viewUserScripts();
	assert.match(view.html, /This page was filed under another script/);
	assert.match(view.html, /script=Utilisateur%3AZebulon84%2Fxpatrol\.js/);
});

test("a title the directory never saw is a plain miss", async () => {
	window.history.replaceState({}, "", "/userscripts?wiki=fr.wikipedia.org&script=Nope.js");
	respond({ script: { ok: false, body: { error: "no such script in this wiki's directory" } } });
	const view = await viewUserScripts();
	assert.match(view.html, /has no such script/);
});

test("failed requests are never rendered as an empty directory", async () => {
	h.fetchRead.mockRejectedValue(new Error("offline"));
	let view = await viewUserScripts();
	assert.match(view.html, /role="alert"/);
	assert.match(view.html, /This is not an empty directory/);

	h.fetchRead.mockReset();
	h.fetchRead.mockImplementation((path) =>
		path.startsWith("/v1/userscripts/wikis/") ? json(wikis) : Promise.reject(new Error("offline"))
	);
	view = await viewUserScripts();
	assert.match(view.html, /This is not an empty directory/);

	h.fetchRead.mockReset();
	h.fetchRead.mockImplementation((path) =>
		path.startsWith("/v1/userscripts/wikis/") ? json(wikis) : json({ error: "wiki is required" }, false)
	);
	view = await viewUserScripts();
	assert.match(view.html, /This is not an empty directory/);

	window.history.replaceState({}, "", "/userscripts?wiki=fr.wikipedia.org&script=A.js");
	h.fetchRead.mockReset();
	h.fetchRead.mockImplementation((path) =>
		path.startsWith("/v1/userscripts/wikis/") ? json(wikis) : Promise.reject(new Error("offline"))
	);
	view = await viewUserScripts();
	assert.match(view.html, /This is not an empty directory/);
});

test("a retry re-runs the route rather than leaving the error on screen", async () => {
	h.fetchRead.mockRejectedValue(new Error("offline"));
	const view = await viewUserScripts();
	document.body.innerHTML = view.html;
	view.mount();
	let navigations = 0;
	const count = () => {
		navigations += 1;
	};
	window.addEventListener("toolhub:navigate", count);
	try {
		document.querySelector("[data-userscript-retry]").click();
		assert.equal(navigations, 1);
	} finally {
		window.removeEventListener("toolhub:navigate", count);
	}
});

test("filters and paging are shareable URLs, and mark the results busy", async () => {
	window.history.replaceState({}, "", "/userscripts?wiki=fr.wikipedia.org");
	respond();
	const view = await viewUserScripts();
	document.body.innerHTML = view.html;
	view.mount();

	document.querySelector('[name="owner"]').value = "Od1n";
	document.querySelector("[data-userscript-search]").dispatchEvent(new Event("submit", { cancelable: true }));
	let params = new URLSearchParams(location.search);
	assert.equal(params.get("owner"), "Od1n");
	assert.equal(params.get("wiki"), "fr.wikipedia.org");
	assert.equal(document.querySelector("[data-userscript-results]").getAttribute("aria-busy"), "true");

	window.history.replaceState({}, "", "/userscripts?wiki=fr.wikipedia.org");
	document.querySelector('[data-userscript-pager] [data-page="2"]').click();
	params = new URLSearchParams(location.search);
	assert.equal(params.get("page"), "2");
});

test("choosing another wiki drops the previous wiki's filters", async () => {
	window.history.replaceState({}, "", "/userscripts?wiki=fr.wikipedia.org&owner=Od1n&page=4");
	respond({ wikiList: { count: 2, results: [coverage, { ...coverage, wiki: "en.wikipedia.org" }] } });
	const view = await viewUserScripts();
	document.body.innerHTML = view.html;
	view.mount();

	const select = document.querySelector('[name="wiki"]');
	select.value = "en.wikipedia.org";
	select.dispatchEvent(new Event("change"));
	const params = new URLSearchParams(location.search);
	assert.equal(params.get("wiki"), "en.wikipedia.org");
	assert.equal(params.has("page"), false);
	assert.equal(params.get("owner"), "Od1n");
});

test("the default wiki is one that has actually been projected", async () => {
	respond({
		wikiList: {
			count: 2,
			results: [
				{ ...coverage, wiki: "es.wikipedia.org", active: 0, archive: 0 },
				{ ...coverage, wiki: "fr.wikipedia.org" }
			]
		}
	});
	const view = await viewUserScripts();
	assert.match(h.fetchRead.mock.calls[1][0], /wiki=fr\.wikipedia\.org/);
	assert.match(view.html, /<option value="fr.wikipedia.org" selected>/);
});
