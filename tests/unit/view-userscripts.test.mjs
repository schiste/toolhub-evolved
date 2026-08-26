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
	currentTo: "2026-08-19T06:00:00Z",
	checkedAt: "2026-08-19T07:00:00Z",
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
	window.history.replaceState({}, "", "/userscripts?wiki=fr.wikipedia.org");
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
	assert.match(view.html, /Changes read up to/);
	assert.doesNotMatch(view.html, /counts are a floor/);
});

test("a directory rebuilt this hour still says how old the data under it is", async () => {
	// The failure this guards: an hourly job stamping a fresh timestamp over a
	// census weeks behind the wiki. All three dates have to reach the reader,
	// because only together do they say which kind of stale this is.
	const behind = { ...coverage, sweptAt: "2026-07-21T00:00:00Z", currentTo: "2026-08-06T17:22:45Z" };
	respond({
		wikiList: { count: 1, results: [behind] },
		directory: { ...listing, coverage: behind }
	});
	const view = await viewUserScripts();
	assert.match(view.html, /datetime="2026-07-21T00:00:00\.000Z"/);
	assert.match(view.html, /datetime="2026-08-06T17:22:45\.000Z"/);
});

test("a wiki with no finished sweep says its counts are a floor", async () => {
	// Keyed on the count of finished sweeps, not on a timestamp. A wiki part-way
	// through its first sweep has a `sweptAt` -- the run that is under way -- and
	// its counts are exactly the floor this notice exists to declare.
	const unswept = { ...coverage, sweepsCompleted: 0, active: 0, archive: 0 };
	respond({
		wikiList: { count: 1, results: [unswept] },
		directory: { ...listing, count: 0, total: 0, results: [], coverage: unswept }
	});
	const view = await viewUserScripts();
	assert.match(view.html, /No full sweep of this wiki has finished yet/);
	assert.match(view.html, /No scripts are filed in this tier yet/);
});

test("a wiki too large to enumerate in one pass says so alongside its counts", async () => {
	// Meta is this case: swept successfully, thousands of rows, and still only
	// part of the wiki. A finished sweep must not read as a finished census.
	const partial = { ...coverage, enumerated: false };
	respond({
		wikiList: { count: 1, results: [partial] },
		directory: { ...listing, coverage: partial }
	});
	const view = await viewUserScripts();
	assert.match(view.html, /only part of its user space has been read/);
	assert.doesNotMatch(view.html, /counts are a floor/);
	assert.match(view.html, /Script pages seen/);
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

/**
 * A roster the way the census now hands one over: alphabetical, opening on a
 * tiny wiki that holds a single archived page, with the wikis a reader actually
 * wants further down. Picking a wiki out of this shape is what broke the page.
 */
const roster = {
	count: 4,
	results: [
		{ ...coverage, wiki: "aa.wikibooks.org", pages: 3, active: 0, archive: 1 },
		{ ...coverage, wiki: "ab.wikipedia.org", pages: 9, active: 0, archive: 13 },
		{ ...coverage, wiki: "en.wikipedia.org", pages: 14331, active: 3277, archive: 4021 },
		{ ...coverage, wiki: "fr.wikipedia.org", active: 412, archive: 983 }
	]
};

/**
 * What `/v1/userscripts/directory/` answers when no wiki is named: rows from
 * different wikis ranked against each other by demand, each still carrying the
 * position it holds inside its own wiki, and no `coverage` record -- there is no
 * single sweep for a cross-wiki reading to describe.
 */
const crossWiki = {
	wiki: "",
	tier: "active",
	count: 2,
	total: 45679,
	limit: 25,
	offset: 0,
	results: [
		{
			wiki: "en.wikipedia.org",
			title: "User:Writer/navpop.js",
			owner: "Writer",
			basename: "navpop.js",
			tier: "active",
			demand: 9102,
			instances: 41,
			position: 1
		},
		{
			wiki: "fr.wikipedia.org",
			title: "Utilisateur:Zebulon84/xpatrol.js",
			owner: "Zebulon84",
			basename: "xpatrol.js",
			tier: "active",
			demand: 188,
			instances: 13,
			position: 1
		}
	],
	coverage: null
};

test("an unqualified visit reads every wiki rather than choosing one", async () => {
	// The page used to pick a wiki for you. Which one it picked was a guess about
	// what you wanted, and no guess is right across a thousand projects -- so it
	// asks for all of them and lets the ranking say where the scripts are.
	window.history.replaceState({}, "", "/userscripts");
	respond({ wikiList: roster, directory: crossWiki });
	const view = await viewUserScripts();

	const asked = h.fetchRead.mock.calls.map(([path]) => path).find((path) => path.includes("/directory/"));
	assert.doesNotMatch(asked, /wiki=/);
	assert.match(view.html, /<option value="" selected>All wikis<\/option>/);
	assert.doesNotMatch(view.html, /<option value="[^"]+" selected>/);
});

test("the cross-wiki ranking numbers its own rows and names each row's wiki", async () => {
	// Every wiki has a script at position 1, so the per-wiki rank cannot be shown
	// here: a reader would see three rows all claiming first place. The rank is
	// counted off the page instead, and continues across pages.
	window.history.replaceState({}, "", "/userscripts");
	respond({ wikiList: roster, directory: crossWiki });
	let view = await viewUserScripts();
	assert.match(view.html, /<td>1<\/td>\s*<td><a[^>]*>en\.wikipedia\.org/);
	assert.match(view.html, /<td>2<\/td>\s*<td><a[^>]*>fr\.wikipedia\.org/);
	assert.match(view.html, /<th scope="col">Wiki<\/th>/);
	// The script link carries the row's own wiki; a script page belongs to one.
	assert.match(view.html, /wiki=en\.wikipedia\.org&amp;script=User%3AWriter%2Fnavpop\.js/);

	window.history.replaceState({}, "", "/userscripts?page=2");
	respond({ wikiList: roster, directory: { ...crossWiki, offset: 25 } });
	view = await viewUserScripts();
	assert.match(view.html, /<td>26<\/td>/);
	assert.match(view.html, /<td>27<\/td>/);
});

test("one wiki keeps its own rank and drops the wiki column", async () => {
	respond();
	const view = await viewUserScripts();
	assert.doesNotMatch(view.html, /<th scope="col">Wiki<\/th>/);
	assert.match(view.html, /<option value="fr.wikipedia.org" selected>/);
	assert.match(h.fetchRead.mock.calls[1][0], /wiki=fr\.wikipedia\.org&tier=active/);
});

test("the roster summary adds up what adds up and floors what does not", async () => {
	// Counts merge; dates do not. A mean of a thousand timestamps describes no
	// wiki, so the oldest is shown and labelled as the floor it is.
	window.history.replaceState({}, "", "/userscripts");
	const stale = {
		count: 3,
		results: [
			{ ...coverage, wiki: "aa.wikibooks.org", pages: 3, active: 0, archive: 1 },
			{
				...coverage,
				wiki: "en.wikipedia.org",
				pages: 100,
				active: 20,
				archive: 30,
				currentTo: "2026-07-02T00:00:00Z"
			},
			{ ...coverage, wiki: "fr.wikipedia.org", pages: 50, active: 5, archive: 4 }
		]
	};
	respond({ wikiList: stale, directory: { ...crossWiki, coverage: null } });
	const view = await viewUserScripts();

	assert.match(view.html, /Script pages seen<\/div><div class="meta__v"[^>]*>153</);
	assert.match(view.html, /Wikis holding scripts<\/div><div class="meta__v"[^>]*>3 of 3</);
	assert.match(view.html, /Every wiki current to at least/);
	assert.match(view.html, /datetime="2026-07-02T00:00:00\.000Z"/);
	// A per-wiki sweep date is not a fact about a cross-wiki reading.
	assert.doesNotMatch(view.html, /Last full sweep/);
	assert.match(view.html, /In use \(25\)/);
	assert.match(view.html, /Archive \(35\)/);
});

test("a roster only partly swept says how much of it is provisional", async () => {
	window.history.replaceState({}, "", "/userscripts");
	respond({
		wikiList: {
			count: 3,
			results: [
				{ ...coverage, wiki: "aa.wikibooks.org", sweepsCompleted: 0 },
				{ ...coverage, wiki: "ab.wikipedia.org", sweepsCompleted: 0 },
				{ ...coverage, wiki: "en.wikipedia.org", enumerated: false }
			]
		},
		directory: { ...crossWiki, coverage: null }
	});
	const view = await viewUserScripts();
	assert.match(view.html, /2 of these wikis have no finished sweep yet/);
	assert.match(view.html, /1 hold more user-space script pages/);
});

test("choosing All wikis from the picker widens the reading", async () => {
	respond();
	const view = await viewUserScripts();
	document.body.innerHTML = view.html;
	view.mount();

	const select = /** @type {HTMLSelectElement} */ (document.querySelector('[name="wiki"]'));
	select.value = "";
	select.dispatchEvent(new Event("change"));
	assert.equal(new URLSearchParams(location.search).has("wiki"), false);
});
