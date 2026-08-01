// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import fs from "node:fs";
import { test, vi, beforeEach } from "vitest";
import { legacyToolCardSnapshot } from "./tool-card-snapshot.mjs";

const SCRATCH =
	"/private/tmp/claude-501/-Users-christophehenner-Downloads-Wikimedia-striker-toolhub-demo/bad07c6e-1967-4490-8d44-3fe4ee515e59/scratchpad";
const BAKE = process.env.BAKE === "1";

const h = vi.hoisted(() => ({
	apiGet: vi.fn(),
	paginate: vi.fn(),
	navigateTo: vi.fn(),
	backendGetJson: vi.fn(),
	cachedCanonicalTools: vi.fn(),
	// Mocked apiGet never populates the real cache, so the cold/warm signal the
	// local-first path reads has to be controllable here.
	apiCached: vi.fn(() => false)
}));

vi.mock("../../public_html/lib/core/api.js", async (orig) => {
	const actual = await orig();
	return {
		...actual,
		apiGet: h.apiGet,
		paginate: h.paginate,
		backendGetJson: h.backendGetJson,
		cachedCanonicalTools: h.cachedCanonicalTools,
		apiCached: h.apiCached
	};
});
vi.mock("../../public_html/lib/core/routing.js", async (orig) => {
	const actual = await orig();
	return { ...actual, navigateTo: h.navigateTo };
});
vi.mock("../../public_html/lib/core/i18n.js", async (orig) => {
	const actual = await orig();
	return {
		...actual,
		updatedTimeTag: (iso, cls) => `<u|${iso ?? ""}|${cls ?? ""}>`,
		timeTag: (iso, cls, text) => `<t|${iso ?? ""}|${cls ?? ""}|${text ?? ""}>`
	};
});

const { applyExp } = await import("../../public_html/lib/core/session.js");
const search = await import("../../public_html/views/search.js");

const S = {
	default: `
	<div class="container page">
		<h1 class="page__title">Browse tools</h1>
		<div class="browse">
			<aside class="facets" aria-label="Filters">
				<form data-facet-q role="search">
					<label for="facet-q" class="skip-label">Search within tools</label>
					<input id="facet-q" class="facets__search" type="search" placeholder="Search tools…" autocomplete="off" value="" />
				</form>
				<div class="facet-group"><h2 class="facet-group__title">Status</h2><label class="facet"><input type="checkbox" data-client-status="deprecated"> <span>Deprecated</span></label><label class="facet"><input type="checkbox" data-client-status="experimental"> <span>Experimental</span></label></div>
				<div class="facet-group"><h2 class="facet-group__title">Tool type</h2><label class="facet"><input type="checkbox" data-facet="tool_type" value="web app"> <span dir="auto">web app</span> <span class="facet__n">12</span></label></div>
				<a class="btn btn--outline btn--md facets__reset" href="/search">Clear filters</a>
			</aside>
			<div class="browse__main">
				<div class="browse__bar">
					<span class="browse__count" aria-live="polite">Showing 1-2 of 2 tools</span>
					<span class="browse__controls">
						<label class="sort"><span class="skip-label">Results per page</span><select id="page-size"><option value="12">12 per page</option><option value="24">24 per page</option><option value="48">48 per page</option></select></label>
						<label class="sort"><span class="skip-label">Sort by</span><select id="sort"><option value="relevance">Most relevant</option><option value="recent">Recently updated</option><option value="name">Name (A–Z)</option><option value="complete">Most complete</option></select></label>
					</span>
				</div>
				<ul class="card-grid grid-tools" role="list"><li>
	<article class="tcard tcard--health-unknown" data-tool="alpha">
		<div class="tcard__topline"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__topmeta"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<div class="tcard__head">
			<span class="avatar " style="background:var(--color-progressive)" aria-hidden="true">A</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="alpha" aria-label="Quick look: Alpha" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Alpha</button>
				<div class="tcard__maint">by <span class="tcard__maint-name" title="Unknown, maintainer not confirmed yet" aria-label="Unknown, maintainer not confirmed yet"><span class="tcard__maint-text" dir="auto">Unknown</span></span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"><span class="tag" data-q="a" dir="auto">a</span></div>
		<div class="tcard__signals"><div class="tcard__signal-row tcard__signal-row--metrics"><span class="signal" title="Listing 1 of 9 fields complete
Missing: Description
Missing: Tool URL
Missing: Source repository
Missing: License
Done: Keywords
Missing: Audience or task tagged
Missing: Documentation
Missing: Icon
Missing: Issue tracker or feedback" aria-label="Listing 1 of 9 fields complete
Missing: Description
Missing: Tool URL
Missing: Source repository
Missing: License
Done: Keywords
Missing: Audience or task tagged
Missing: Documentation
Missing: Icon
Missing: Issue tracker or feedback"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:11%"></span></span>1/9</span><span class="tcard__health-dash" title="Health score unknown" aria-label="Health score unknown">—</span></div></div>
	</article></li><li>
	<article class="tcard tcard--health-unknown" data-tool="bravo">
		<div class="tcard__topline"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__topmeta"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<div class="tcard__head">
			<span class="avatar " style="background:var(--color-progressive)" aria-hidden="true">B</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="bravo" aria-label="Quick look: Bravo" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Bravo</button>
				<div class="tcard__maint">by <span class="tcard__maint-name" title="Unknown, maintainer not confirmed yet" aria-label="Unknown, maintainer not confirmed yet"><span class="tcard__maint-text" dir="auto">Unknown</span></span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><div class="tcard__signal-row tcard__signal-row--metrics"><span class="signal" title="Listing 0 of 9 fields complete
Missing: Description
Missing: Tool URL
Missing: Source repository
Missing: License
Missing: Keywords
Missing: Audience or task tagged
Missing: Documentation
Missing: Icon
Missing: Issue tracker or feedback" aria-label="Listing 0 of 9 fields complete
Missing: Description
Missing: Tool URL
Missing: Source repository
Missing: License
Missing: Keywords
Missing: Audience or task tagged
Missing: Documentation
Missing: Icon
Missing: Issue tracker or feedback"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span><span class="tcard__health-dash" title="Health score unknown" aria-label="Health score unknown">—</span></div></div>
	</article></li></ul>
				<nav class="pager" aria-label="Pagination"></nav>
			</div>
		</div>
	</div>`,
	empty: `
	<div class="container page">
		<h1 class="page__title">Browse tools</h1>
		<div class="browse">
			<aside class="facets" aria-label="Filters">
				<form data-facet-q role="search">
					<label for="facet-q" class="skip-label">Search within tools</label>
					<input id="facet-q" class="facets__search" type="search" placeholder="Search tools…" autocomplete="off" value="" />
				</form>
				<div class="facet-group"><h2 class="facet-group__title">Status</h2><label class="facet"><input type="checkbox" data-client-status="deprecated"> <span>Deprecated</span></label><label class="facet"><input type="checkbox" data-client-status="experimental"> <span>Experimental</span></label></div>
				<p class="facet__empty">No filters available.</p>
				<a class="btn btn--outline btn--md facets__reset" href="/search">Clear filters</a>
			</aside>
			<div class="browse__main">
				<div class="browse__bar">
					<span class="browse__count" aria-live="polite">0 tools</span>
					<span class="browse__controls">
						<label class="sort"><span class="skip-label">Results per page</span><select id="page-size"><option value="12">12 per page</option><option value="24">24 per page</option><option value="48">48 per page</option></select></label>
						<label class="sort"><span class="skip-label">Sort by</span><select id="sort"><option value="relevance">Most relevant</option><option value="recent">Recently updated</option><option value="name">Name (A–Z)</option><option value="complete">Most complete</option></select></label>
					</span>
				</div>
				<p class="empty">No tools match these filters.</p>
				<nav class="pager" aria-label="Pagination"></nav>
			</div>
		</div>
	</div>`,
	status: `
	<div class="container page">
		<h1 class="page__title">Browse tools</h1>
		<div class="browse">
			<aside class="facets" aria-label="Filters">
				<form data-facet-q role="search">
					<label for="facet-q" class="skip-label">Search within tools</label>
					<input id="facet-q" class="facets__search" type="search" placeholder="Search tools…" autocomplete="off" value="" />
				</form>
				<div class="facet-group"><h2 class="facet-group__title">Status</h2><label class="facet"><input type="checkbox" data-client-status="deprecated" checked> <span>Deprecated</span></label><label class="facet"><input type="checkbox" data-client-status="experimental" checked> <span>Experimental</span></label></div>
				<div class="facet-group"><h2 class="facet-group__title">Tool type</h2><label class="facet"><input type="checkbox" data-facet="tool_type" value="web app"> <span dir="auto">web app</span> <span class="facet__n">12</span></label></div>
				<a class="btn btn--outline btn--md facets__reset" href="/search">Clear filters</a>
			</aside>
			<div class="browse__main">
				<div class="browse__bar">
					<span class="browse__count" aria-live="polite">Showing 2 on this page of 3 tools <span class="browse__count-note">filtered in your browser</span></span>
					<span class="browse__controls">
						<label class="sort"><span class="skip-label">Results per page</span><select id="page-size"><option value="12">12 per page</option><option value="24">24 per page</option><option value="48">48 per page</option></select></label>
						<label class="sort"><span class="skip-label">Sort by</span><select id="sort"><option value="relevance">Most relevant</option><option value="recent">Recently updated</option><option value="name">Name (A–Z)</option><option value="complete">Most complete</option></select></label>
					</span>
				</div>
				<ul class="card-grid grid-tools" role="list"><li>
	<article class="tcard tcard--health-unknown" data-tool="dep">
		<div class="tcard__topline"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__topmeta"><span class="tcard__flag status status--red"><span class="dot dot--red"></span>Deprecated</span><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<div class="tcard__head">
			<span class="avatar " style="background:var(--wmf-green-aaa)" aria-hidden="true">D</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="dep" aria-label="Quick look: Dep" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Dep</button>
				<div class="tcard__maint">by <span class="tcard__maint-name" title="Unknown, maintainer not confirmed yet" aria-label="Unknown, maintainer not confirmed yet"><span class="tcard__maint-text" dir="auto">Unknown</span></span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><div class="tcard__signal-row tcard__signal-row--metrics"><span class="signal" title="Listing 0 of 9 fields complete
Missing: Description
Missing: Tool URL
Missing: Source repository
Missing: License
Missing: Keywords
Missing: Audience or task tagged
Missing: Documentation
Missing: Icon
Missing: Issue tracker or feedback" aria-label="Listing 0 of 9 fields complete
Missing: Description
Missing: Tool URL
Missing: Source repository
Missing: License
Missing: Keywords
Missing: Audience or task tagged
Missing: Documentation
Missing: Icon
Missing: Issue tracker or feedback"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span><span class="tcard__health-dash" title="Health score unknown" aria-label="Health score unknown">—</span></div></div>
	</article></li><li>
	<article class="tcard tcard--health-unknown" data-tool="exp">
		<div class="tcard__topline"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__topmeta"><span class="tcard__flag status status--yellow"><span class="dot dot--yellow"></span>Experimental</span><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<div class="tcard__head">
			<span class="avatar " style="background:var(--wmf-green-aaa)" aria-hidden="true">E</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="exp" aria-label="Quick look: Exp" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Exp</button>
				<div class="tcard__maint">by <span class="tcard__maint-name" title="Unknown, maintainer not confirmed yet" aria-label="Unknown, maintainer not confirmed yet"><span class="tcard__maint-text" dir="auto">Unknown</span></span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><div class="tcard__signal-row tcard__signal-row--metrics"><span class="signal" title="Listing 0 of 9 fields complete
Missing: Description
Missing: Tool URL
Missing: Source repository
Missing: License
Missing: Keywords
Missing: Audience or task tagged
Missing: Documentation
Missing: Icon
Missing: Issue tracker or feedback" aria-label="Listing 0 of 9 fields complete
Missing: Description
Missing: Tool URL
Missing: Source repository
Missing: License
Missing: Keywords
Missing: Audience or task tagged
Missing: Documentation
Missing: Icon
Missing: Issue tracker or feedback"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span><span class="tcard__health-dash" title="Health score unknown" aria-label="Health score unknown">—</span></div></div>
	</article></li></ul>
				<nav class="pager" aria-label="Pagination"></nav>
			</div>
		</div>
	</div>`,
	status_none: `
	<div class="container page">
		<h1 class="page__title">Browse tools</h1>
		<div class="browse">
			<aside class="facets" aria-label="Filters">
				<form data-facet-q role="search">
					<label for="facet-q" class="skip-label">Search within tools</label>
					<input id="facet-q" class="facets__search" type="search" placeholder="Search tools…" autocomplete="off" value="" />
				</form>
				<div class="facet-group"><h2 class="facet-group__title">Status</h2><label class="facet"><input type="checkbox" data-client-status="deprecated" checked> <span>Deprecated</span></label><label class="facet"><input type="checkbox" data-client-status="experimental"> <span>Experimental</span></label></div>
				<div class="facet-group"><h2 class="facet-group__title">Tool type</h2><label class="facet"><input type="checkbox" data-facet="tool_type" value="web app"> <span dir="auto">web app</span> <span class="facet__n">12</span></label></div>
				<a class="btn btn--outline btn--md facets__reset" href="/search">Clear filters</a>
			</aside>
			<div class="browse__main">
				<div class="browse__bar">
					<span class="browse__count" aria-live="polite">No visible tools on this page of 1 tool <span class="browse__count-note">filtered in your browser</span></span>
					<span class="browse__controls">
						<label class="sort"><span class="skip-label">Results per page</span><select id="page-size"><option value="12">12 per page</option><option value="24">24 per page</option><option value="48">48 per page</option></select></label>
						<label class="sort"><span class="skip-label">Sort by</span><select id="sort"><option value="relevance">Most relevant</option><option value="recent">Recently updated</option><option value="name">Name (A–Z)</option><option value="complete">Most complete</option></select></label>
					</span>
				</div>
				<p class="empty">No tools match these filters.</p>
				<nav class="pager" aria-label="Pagination"></nav>
			</div>
		</div>
	</div>`
};

function expect(name, actual) {
	const comparable = legacyToolCardSnapshot(actual);
	if (BAKE) {
		fs.writeFileSync(`${SCRATCH}/search__${name}.txt`, comparable);
		return;
	}
	assert.equal(comparable, S[name], name);
}

function rawTool(name, o = {}) {
	return {
		name,
		title: o.title ?? name,
		description: o.description ?? "",
		keywords: o.keywords ?? [],
		for_wikis: o.for_wikis ?? [],
		modified_date: o.modified_date ?? "2026-01-01T00:00:00Z",
		deprecated: o.deprecated ?? false,
		experimental: o.experimental ?? false,
		...o
	};
}

function cachedTool(name, o = {}) {
	return {
		name,
		title: o.title ?? name,
		description: o.description ?? "",
		keywords: o.keywords ?? [],
		maintainer: o.maintainer ?? "Cached maintainer",
		forWikis: o.forWikis ?? [],
		toolType: o.toolType ?? null,
		modified: o.modified ?? "2026-01-01T00:00:00Z",
		deprecated: o.deprecated ?? false,
		experimental: o.experimental ?? false,
		weeklyViews: 0,
		...o
	};
}

const FACETS = {
	_filter_tool_type: {
		tool_type: { meta: { param: "tool_type" }, buckets: [{ key: "web app", doc_count: 12 }] }
	}
};

function setUrl(qs) {
	window.history.replaceState(null, "", qs ? `/search?${qs}` : "/search");
}

beforeEach(() => {
	localStorage.clear();
	applyExp(false);
	document.body.innerHTML = "";
	h.apiGet.mockReset();
	h.paginate.mockReset();
	h.navigateTo.mockReset();
	h.backendGetJson.mockReset();
	h.cachedCanonicalTools.mockReset();
	h.apiCached.mockReset();
	h.paginate.mockResolvedValue([]);
	h.backendGetJson.mockRejectedValue(new Error("backend offline")); // default: no local strip
	h.cachedCanonicalTools.mockResolvedValue([]);
	// Default to a warm live cache so existing tests exercise the live path;
	// the local-first tests opt in by leaving the canonical cache populated.
	h.apiCached.mockReturnValue(true);
	search.resetLocalFirstStateForTests();
	setUrl("");
});

test("search default (no query, populated results)", async () => {
	setUrl("");
	h.apiGet.mockResolvedValue({
		results: [rawTool("alpha", { title: "Alpha", keywords: ["a"] }), rawTool("bravo", { title: "Bravo" })],
		count: 2,
		facets: FACETS
	});
	const r = await search.viewSearch();
	assert.equal(r.title, "Browse tools — Toolhub");
	expect("default", r.html);
});

test("search ignores removed popularity sort and renders normal cards", async () => {
	setUrl("q=maps&sort=views&page=2&page_size=12");
	h.apiGet.mockResolvedValue({
		results: [
			rawTool("alpha", { title: "Alpha", keywords: ["maps"] }),
			rawTool("bravo", { title: "Bravo", keywords: ["maps"] })
		],
		count: 50,
		facets: FACETS
	});
	const r = await search.viewSearch();
	assert.equal(r.title, "“maps” — Toolhub");
	assert.ok(r.html.includes('<option value="relevance">Most relevant</option>'));
	assert.ok(!r.html.includes('<option value="views">Popular this week</option>'));
	assert.ok(!r.html.includes("views experimental"));
	assert.ok(!r.html.includes("tcard--popular"));
});

test("search client status filter (deprecated + experimental), some visible", async () => {
	setUrl("status=deprecated,experimental");
	h.apiGet.mockResolvedValue({
		results: [
			rawTool("dep", { title: "Dep", deprecated: true }),
			rawTool("exp", { title: "Exp", experimental: true }),
			rawTool("plain", { title: "Plain" })
		],
		count: 3,
		facets: FACETS
	});
	const r = await search.viewSearch();
	expect("status", r.html);
});

test("search client status filter hides everything on this page", async () => {
	setUrl("status=deprecated");
	h.apiGet.mockResolvedValue({ results: [rawTool("plain", { title: "Plain" })], count: 1, facets: FACETS });
	const r = await search.viewSearch();
	expect("status_none", r.html);
});

test("search empty results, no facets (response is {} → exercises `data.results || []`)", async () => {
	setUrl("");
	h.apiGet.mockResolvedValue({});
	const r = await search.viewSearch();
	expect("empty", r.html);
});

test("search serves local canonical results first on a cold query, then upgrades to live", async () => {
	setUrl("q=cite");
	h.apiCached.mockReturnValue(false); // cold: nothing cached for this query
	h.cachedCanonicalTools.mockResolvedValue([cachedTool("cached-cite", { title: "Cached Cite" })]);
	// Live is slow; the local answer must not wait for it.
	let resolveLive;
	h.apiGet.mockReturnValue(
		new Promise((resolve) => {
			resolveLive = resolve;
		})
	);

	const first = await search.viewSearch();
	assert.ok(first.html.includes('data-tool="cached-cite"'), "local results paint before Toolhub answers");
	assert.ok(first.html.includes("showing saved results while Toolhub loads"));

	// Once live lands it is served instead, without the interim note.
	resolveLive({ results: [rawTool("live-cite", { title: "Live Cite" })], count: 1, facets: FACETS });
	await new Promise((resolve) => setTimeout(resolve, 0));
	h.apiGet.mockResolvedValue({ results: [rawTool("live-cite", { title: "Live Cite" })], count: 1, facets: FACETS });
	h.apiCached.mockReturnValue(true); // the live response is cached now
	const second = await search.viewSearch();
	assert.ok(second.html.includes('data-tool="live-cite"'));
	assert.ok(!second.html.includes("showing saved results while Toolhub loads"));
});

test("search falls back to cached canonical tools when live Toolhub search fails", async () => {
	setUrl("q=cite");
	h.apiCached.mockReturnValue(false); // cold: nothing cached for this query
	h.apiGet.mockRejectedValue(new Error("down"));
	h.cachedCanonicalTools.mockResolvedValue([cachedTool("cached-cite", { title: "Cached Cite" })]);

	// Cold query: local paints first, optimistically.
	const first = await search.viewSearch();
	assert.deepEqual(h.cachedCanonicalTools.mock.calls[0], [{ q: "cite", limit: 24 }]);
	assert.ok(first.html.includes('data-tool="cached-cite"'));

	// The live failure settles, and the re-render states it plainly rather than
	// leaving a "loading" note that will never resolve.
	await new Promise((resolve) => setTimeout(resolve, 0));
	const second = await search.viewSearch();
	assert.ok(second.html.includes("showing saved Toolhub data"));
	assert.ok(!second.html.includes("showing saved results while Toolhub loads"));
	assert.ok(second.html.includes('data-tool="cached-cite"'));
});

test("a failed live search does not loop back into the local-first path", async () => {
	setUrl("q=loopcheck");
	h.apiCached.mockReturnValue(false); // cold: nothing cached for this query
	h.apiGet.mockRejectedValue(new Error("down"));
	h.cachedCanonicalTools.mockResolvedValue([cachedTool("cached-loop", { title: "Cached Loop" })]);

	await search.viewSearch();
	await new Promise((resolve) => setTimeout(resolve, 0));
	// Every later render takes the normal path and reports the failure, rather
	// than optimistically repainting local results forever.
	for (let i = 0; i < 3; i += 1) {
		const again = await search.viewSearch();
		assert.ok(again.html.includes("showing saved Toolhub data"), `render ${i} must report the failure`);
	}
});

test("search sort=complete orders by completeness with title tiebreak", async () => {
	setUrl("sort=complete");
	h.apiGet.mockResolvedValue({
		results: [
			// zeta and alpha both fully empty (completeness tie) → title tiebreak alpha before zeta
			rawTool("zeta", { title: "Zeta" }),
			rawTool("alpha", { title: "Alpha" }),
			// rich has more complete fields → leads
			rawTool("rich", {
				title: "Rich",
				description: "A sufficiently long description well over thirty characters in length.",
				url: "https://x.example",
				repository: "https://r.example",
				license: "MIT",
				keywords: ["k"]
			})
		],
		count: 3,
		facets: FACETS
	});
	const r = await search.viewSearch();
	const order = [...r.html.matchAll(/<article class="tcard[^"]*" data-tool="([^"]+)"/g)].map((m) => m[1]);
	assert.deepEqual(order, ["rich", "alpha", "zeta"]);
});

/* ---- sort resolution branches ---- */

async function sortValueFor(qs) {
	setUrl(qs);
	h.apiGet.mockResolvedValue({ results: [], count: 0, facets: {} });
	const r = await search.viewSearch();
	document.body.innerHTML = r.html;
	r.mount();
	return document.querySelector("#sort").value;
}

test("ordering=-modified_date maps to recent", async () =>
	assert.equal(await sortValueFor("ordering=-modified_date"), "recent"));
test("ordering=name maps to name", async () => assert.equal(await sortValueFor("ordering=name"), "name"));
test("ordering=-score maps to relevance", async () => assert.equal(await sortValueFor("ordering=-score"), "relevance"));
test("unknown ordering falls back to default relevance", async () =>
	assert.equal(await sortValueFor("ordering=zzz"), "relevance"));
test("default sort is relevance", async () => assert.equal(await sortValueFor(""), "relevance"));
test("disallowed sort (views) falls back to relevance", async () =>
	assert.equal(await sortValueFor("sort=views"), "relevance"));
test("page_size invalid falls back to default", async () => {
	applyExp(false);
	setUrl("page_size=999");
	h.apiGet.mockResolvedValue({ results: [], count: 0, facets: {} });
	const r = await search.viewSearch();
	document.body.innerHTML = r.html;
	r.mount();
	assert.equal(document.querySelector("#page-size").value, "24");
});

/* ---- mount() behaviours ---- */

async function mountSearch(qs, data, exp = false) {
	applyExp(exp);
	setUrl(qs);
	h.apiGet.mockResolvedValue(data || { results: [rawTool("alpha", { title: "Alpha" })], count: 1, facets: FACETS });
	const r = await search.viewSearch();
	document.body.innerHTML = r.html;
	r.mount();
	return r;
}

test("mount: sort change navigates with sort param", async () => {
	await mountSearch("");
	const sortEl = document.querySelector("#sort");
	sortEl.value = "name";
	sortEl.dispatchEvent(new Event("change", { bubbles: true }));
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/search?sort=name"]);
});

test("mount: default sort is omitted from the URL", async () => {
	await mountSearch("");
	const sortEl = document.querySelector("#sort");
	sortEl.value = "relevance";
	sortEl.dispatchEvent(new Event("change", { bubbles: true }));
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/search"]);
});

test("mount: page-size change adds page_size unless default", async () => {
	await mountSearch("");
	const ps = document.querySelector("#page-size");
	ps.value = "48";
	ps.dispatchEvent(new Event("change", { bubbles: true }));
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/search?page_size=48"]);
});

test("mount: facet-q submit sets q", async () => {
	await mountSearch("");
	document.querySelector("#facet-q").value = "  bots ";
	document.querySelector("[data-facet-q]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/search?q=bots"]);
});

test("mount: checking a facet + status navigates with both", async () => {
	await mountSearch("");
	const facet = document.querySelector("input[type=checkbox][data-facet]");
	facet.checked = true;
	const status = document.querySelector("input[type=checkbox][data-client-status]");
	status.checked = true;
	document.querySelector(".facets").dispatchEvent(new Event("change", { bubbles: true }));
	const url = h.navigateTo.mock.calls.at(-1)[0];
	assert.ok(url.includes("tool_type=web+app"), url);
	assert.ok(url.includes("status=deprecated"), url);
});

test("mount: pager click navigates with page", async () => {
	await mountSearch("", { results: [rawTool("a", { title: "A" })], count: 200, facets: FACETS });
	document
		.querySelector('.pager [data-page="2"]')
		.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/search?page=2"]);
});

test("mount: clicking pager gap/non-button does nothing", async () => {
	await mountSearch("", { results: [rawTool("a", { title: "A" })], count: 200, facets: FACETS });
	h.navigateTo.mockReset();
	document.querySelector(".pager").dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
	assert.equal(h.navigateTo.mock.calls.length, 0);
});

test("attachEndorsements is awaited (apiGet called once for results)", async () => {
	await mountSearch("");
	assert.ok(h.apiGet.mock.calls.some((c) => c[0] === "/search/tools/"));
});

/* ---- api param construction (mock captures the URLSearchParams) ---- */

async function apiParamsFor(qs) {
	setUrl(qs);
	let captured;
	h.apiGet.mockImplementation(async (path, params) => {
		if (path === "/search/tools/") captured = String(params);
		return { results: [], count: 0, facets: {} };
	});
	await search.viewSearch();
	return captured;
}

test("api params: default (no query) → relevance default with no ordering", async () => {
	assert.equal(await apiParamsFor(""), "page=1&page_size=24");
});
test("api params: q + sort=name + paging", async () => {
	assert.equal(
		await apiParamsFor("q=maps&sort=name&page=3&page_size=12"),
		"q=maps&page=3&page_size=12&ordering=name"
	);
});
test("api params: sort=complete → no ordering param", async () => {
	assert.equal(await apiParamsFor("sort=complete"), "page=1&page_size=24");
});
test("api params: sort=recent stays allowed (ordering kept)", async () => {
	assert.equal(await apiParamsFor("sort=recent"), "page=1&page_size=24&ordering=-modified_date");
});
test("api params: sort=name stays allowed (ordering=name)", async () => {
	assert.equal(await apiParamsFor("sort=name"), "page=1&page_size=24&ordering=name");
});
test("api params: only *__term filters are forwarded (others dropped)", async () => {
	assert.equal(await apiParamsFor("audiences__term=editor&extra=x"), "page=1&page_size=24&audiences__term=editor");
});

test("selected *__term marks the matching facet checkbox checked", async () => {
	setUrl("audiences__term=editor");
	h.apiGet.mockResolvedValue({
		results: [],
		count: 0,
		facets: {
			_filter_audiences: {
				audiences: { meta: { param: "audiences__term" }, buckets: [{ key: "editor", doc_count: 5 }] }
			}
		}
	});
	const r = await search.viewSearch();
	assert.ok(
		r.html.includes('<input type="checkbox" data-facet="audiences__term" value="editor" checked>'),
		"facet pre-checked from selected set"
	);
});

/* ---- count message variants (singular "tool" needs total === 1) ---- */

function countText(html) {
	return html.match(/<span class="browse__count" aria-live="polite">([\S\s]*?)<\/span>/)[1];
}

test("count: normal results, total 1 → singular", async () => {
	setUrl("");
	h.apiGet.mockResolvedValue({ results: [rawTool("a", { title: "A" })], count: 1, facets: {} });
	const r = await search.viewSearch();
	assert.equal(countText(r.html), "Showing 1-1 of 1 tool");
});
test("count: no results, total 1 → bare singular", async () => {
	setUrl("");
	h.apiGet.mockResolvedValue({ results: [], count: 1, facets: {} });
	const r = await search.viewSearch();
	assert.equal(countText(r.html), "1 tool");
});
test("count: status filter visible, total 1 → singular", async () => {
	setUrl("status=deprecated");
	h.apiGet.mockResolvedValue({ results: [rawTool("d", { title: "D", deprecated: true })], count: 1, facets: {} });
	const r = await search.viewSearch();
	assert.equal(
		countText(r.html),
		'Showing 1 on this page of 1 tool <span class="browse__count-note">filtered in your browser'
	);
});
test("count: status filter none visible, total 1 → singular", async () => {
	setUrl("status=deprecated");
	h.apiGet.mockResolvedValue({ results: [rawTool("p", { title: "P" })], count: 1, facets: {} });
	const r = await search.viewSearch();
	assert.equal(
		countText(r.html),
		'No visible tools on this page of 1 tool <span class="browse__count-note">filtered in your browser'
	);
});
test("count: status filter none visible, total 5 → plural", async () => {
	setUrl("status=deprecated");
	h.apiGet.mockResolvedValue({ results: [rawTool("p", { title: "P" })], count: 5, facets: {} });
	const r = await search.viewSearch();
	assert.equal(
		countText(r.html),
		'No visible tools on this page of 5 tools <span class="browse__count-note">filtered in your browser'
	);
});

test("status values are trimmed before validation", async () => {
	setUrl("status=%20deprecated%20"); // " deprecated " with surrounding spaces
	h.apiGet.mockResolvedValue({
		results: [rawTool("d", { title: "D", deprecated: true }), rawTool("p", { title: "P" })],
		count: 2,
		facets: {}
	});
	const r = await search.viewSearch();
	// Trimmed → "deprecated" is a valid client status → filtering active (note shown, plain hidden).
	assert.ok(r.html.includes('class="browse__count-note">filtered in your browser'), "trimmed status filters");
	assert.ok(!r.html.includes('data-tool="p"'), "plain tool filtered out");
});

test("mount: exp-on sort=complete keeps complete selected in #sort", async () => {
	await mountSearch("sort=complete", { results: [], count: 0, facets: {} }, true);
	assert.equal(document.querySelector("#sort").value, "complete");
});

test("mount: two statuses join with comma in the URL", async () => {
	await mountSearch("");
	const boxes = document.querySelectorAll("input[type=checkbox][data-client-status]");
	boxes[0].checked = true;
	boxes[1].checked = true;
	document.querySelector(".facets").dispatchEvent(new Event("change", { bubbles: true }));
	// URLSearchParams encodes the comma → %2C; the join("",) mutant would drop the separator entirely.
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/search?status=deprecated%2Cexperimental"]);
});

test("mount: clicking the current page button does not add a page param", async () => {
	await mountSearch("", { results: [rawTool("a", { title: "A" })], count: 200, facets: FACETS });
	document
		.querySelector('.pager [data-page="1"]')
		.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/search"]);
});

/* ---- federated local strip (docs/PRODUCTION.md P5, phase 1) ------------- */

test("local strip: matching registered tools render above live results, deduped", async () => {
	setUrl("q=cite");
	h.apiGet.mockResolvedValue({ results: [rawTool("alpha", { title: "Alpha" })], count: 1, facets: {} });
	h.backendGetJson.mockResolvedValue({
		count: 2,
		results: [
			{ name: "alpha", title: "Echo of live", description: "d", url: "https://dupe.example" }, // deduped by name
			{ name: "local-cite", title: "Local Cite", description: "Cites things", url: "https://l.example" }
		]
	});
	const r = await search.viewSearch();
	assert.ok(h.backendGetJson.mock.calls.some((call) => call[0] === "/v1/search/tools/?q=cite"));
	assert.ok(r.html.includes("Registered on this site"), "strip heading renders");
	assert.ok(r.html.includes('data-tool="local-cite"'), "local tool card renders");
	// the live "alpha" card renders exactly once (strip deduped it)
	assert.equal(r.html.split('data-tool="alpha"').length - 1, 1, "alpha only in the live grid");
});

test("local strip: absent when the backend fails, has no matches, or page > 1", async () => {
	h.apiGet.mockResolvedValue({ results: [], count: 0, facets: {} });
	let r = await search.viewSearch(); // default mock rejects → strip suppressed
	assert.ok(!r.html.includes("Registered on this site"));
	h.backendGetJson.mockResolvedValue({ count: 0, results: [] });
	r = await search.viewSearch();
	assert.ok(!r.html.includes("Registered on this site"));
	h.backendGetJson.mockResolvedValue(null); // non-ok response body
	r = await search.viewSearch();
	assert.ok(!r.html.includes("Registered on this site"));
	setUrl("page=2");
	h.backendGetJson.mockClear(); // count only the page-2 render below
	h.backendGetJson.mockResolvedValue({
		count: 1,
		results: [{ name: "x", title: "X", description: "d", url: "https://x.example" }]
	});
	h.apiGet.mockResolvedValue({ results: [], count: 60, facets: {} });
	await search.viewSearch();
	assert.equal(h.backendGetJson.mock.calls.length, 0, "no local fetch beyond page 1");
});
