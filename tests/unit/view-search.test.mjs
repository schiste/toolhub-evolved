// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import fs from "node:fs";
import { test, vi, beforeEach } from "vitest";

const SCRATCH =
	"/private/tmp/claude-501/-Users-christophehenner-Downloads-Wikimedia-striker-toolhub-demo/bad07c6e-1967-4490-8d44-3fe4ee515e59/scratchpad";
const BAKE = process.env.BAKE === "1";

const h = vi.hoisted(() => ({ apiGet: vi.fn(), paginate: vi.fn(), navigateTo: vi.fn() }));

vi.mock("../../public_html/lib/core/api.js", async (orig) => {
	const actual = await orig();
	return { ...actual, apiGet: h.apiGet, paginate: h.paginate };
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
						<label class="sort"><span class="skip-label">Sort by</span><select id="sort"><option value="recent">Recently updated</option><option value="name">Name (A–Z)</option><option value="complete">Most complete</option></select></label>
					</span>
				</div>
				<ul class="card-grid grid-tools" role="list"><li>
	<article class="tcard" data-tool="alpha">
		
		<div class="tcard__head">
			<span class="avatar " style="background:var(--color-progressive)" aria-hidden="true">A</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="alpha" aria-label="Quick look: Alpha" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Alpha</button>
				<div class="tcard__maint">by <span dir="auto">Unknown</span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"><span class="tag" data-q="a" dir="auto">a</span></div>
		<div class="tcard__signals"><span class="signal" title="Listing 1 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:11%"></span></span>1/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li><li>
	<article class="tcard" data-tool="bravo">
		
		<div class="tcard__head">
			<span class="avatar " style="background:var(--color-progressive)" aria-hidden="true">B</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="bravo" aria-label="Quick look: Bravo" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Bravo</button>
				<div class="tcard__maint">by <span dir="auto">Unknown</span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
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
						<label class="sort"><span class="skip-label">Sort by</span><select id="sort"><option value="recent">Recently updated</option><option value="name">Name (A–Z)</option><option value="complete">Most complete</option></select></label>
					</span>
				</div>
				<p class="empty">No tools match these filters.</p>
				<nav class="pager" aria-label="Pagination"></nav>
			</div>
		</div>
	</div>`,
	exp_views: `
	<div class="container page">
		<h1 class="page__title">Browse tools</h1>
		<div class="browse">
			<aside class="facets" aria-label="Filters">
				<form data-facet-q role="search">
					<label for="facet-q" class="skip-label">Search within tools</label>
					<input id="facet-q" class="facets__search" type="search" placeholder="Search tools…" autocomplete="off" value="maps" />
				</form>
				<div class="facet-group"><h2 class="facet-group__title">Status</h2><label class="facet"><input type="checkbox" data-client-status="deprecated"> <span>Deprecated</span></label><label class="facet"><input type="checkbox" data-client-status="experimental"> <span>Experimental</span></label></div>
				<div class="facet-group"><h2 class="facet-group__title">Tool type</h2><label class="facet"><input type="checkbox" data-facet="tool_type" value="web app"> <span dir="auto">web app</span> <span class="facet__n">12</span></label></div>
				<a class="btn btn--outline btn--md facets__reset" href="/search">Clear filters</a>
			</aside>
			<div class="browse__main">
				<div class="browse__bar">
					<span class="browse__count" aria-live="polite">Showing 13-14 of 50 tools for &ldquo;<span dir="auto">maps</span>&rdquo;</span>
					<span class="browse__controls">
						<label class="sort"><span class="skip-label">Results per page</span><select id="page-size"><option value="12">12 per page</option><option value="24">24 per page</option><option value="48">48 per page</option></select></label>
						<label class="sort"><span class="skip-label">Sort by</span><select id="sort"><option value="relevance">Most relevant</option><option value="recent">Recently updated</option><option value="name">Name (A–Z)</option><option value="views">Popular this week</option><option value="complete">Most complete</option></select></label>
					</span>
				</div>
				<ul class="card-grid grid-tools" role="list"><li>
	<article class="tcard tcard--popular" data-tool="bravo">
		
		<div class="tcard__head">
			<span class="rankbadge" aria-hidden="true">13</span><span class="avatar " style="background:var(--color-progressive)" aria-hidden="true">B</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="bravo" aria-label="Quick look: Bravo" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Bravo</button>
				<div class="tcard__maint">by <span dir="auto">Unknown</span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"><span class="tag" data-q="maps" dir="auto">maps</span></div>
		<div class="tcard__signals"><span class="signal" title="Listing 1 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:11%"></span></span>1/9</span></div>
		<div class="tcard__foot"><span class="views experimental"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 17h16v2H1V1h2z"/><path d="M19 5v10H5v-1l4.5-5.5 3 3.5L18 5z"/></svg> 228 views</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when><button class="favbtn favbtn--sm" type="button" data-fav="bravo" aria-pressed="false" aria-label="Save to favorites"><span class="favbtn__ic" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M12.744 6.793H18.5l.607 1.795-4.7 3.589 1.802 5.828-1.563 1.09L10 15.545l-4.646 3.55-1.563-1.09 1.8-5.828-4.698-3.59.607-1.794h5.756l1.789-5.788h1.91l1.79 5.788Z"/></svg></span></button></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li><li>
	<article class="tcard tcard--popular" data-tool="alpha">
		
		<div class="tcard__head">
			<span class="rankbadge" aria-hidden="true">14</span><span class="avatar " style="background:var(--color-progressive)" aria-hidden="true">A</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="alpha" aria-label="Quick look: Alpha" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Alpha</button>
				<div class="tcard__maint">by <span dir="auto">Unknown</span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"><span class="tag" data-q="maps" dir="auto">maps</span></div>
		<div class="tcard__signals"><span class="signal" title="Listing 1 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:11%"></span></span>1/9</span></div>
		<div class="tcard__foot"><span class="views experimental"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 17h16v2H1V1h2z"/><path d="M19 5v10H5v-1l4.5-5.5 3 3.5L18 5z"/></svg> 58 views</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when><button class="favbtn favbtn--sm" type="button" data-fav="alpha" aria-pressed="false" aria-label="Save to favorites"><span class="favbtn__ic" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M12.744 6.793H18.5l.607 1.795-4.7 3.589 1.802 5.828-1.563 1.09L10 15.545l-4.646 3.55-1.563-1.09 1.8-5.828-4.698-3.59.607-1.794h5.756l1.789-5.788h1.91l1.79 5.788Z"/></svg></span></button></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li></ul>
				<nav class="pager" aria-label="Pagination"><button class="pager__btn" type="button"  data-page="1">‹ Prev</button><button class="pager__btn" type="button"  data-page="1">1</button><button class="pager__btn is-current" type="button"  data-page="2" aria-current="page">2</button><button class="pager__btn" type="button"  data-page="3">3</button><button class="pager__btn" type="button"  data-page="4">4</button><button class="pager__btn" type="button"  data-page="5">5</button><button class="pager__btn" type="button"  data-page="3">Next ›</button></nav>
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
						<label class="sort"><span class="skip-label">Sort by</span><select id="sort"><option value="recent">Recently updated</option><option value="name">Name (A–Z)</option><option value="complete">Most complete</option></select></label>
					</span>
				</div>
				<ul class="card-grid grid-tools" role="list"><li>
	<article class="tcard" data-tool="dep">
		<span class="tcard__flag status status--red"><span class="dot dot--red"></span>Deprecated</span>
		<div class="tcard__head">
			<span class="avatar " style="background:var(--wmf-green-aaa)" aria-hidden="true">D</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="dep" aria-label="Quick look: Dep" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Dep</button>
				<div class="tcard__maint">by <span dir="auto">Unknown</span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li><li>
	<article class="tcard" data-tool="exp">
		<span class="tcard__flag status status--yellow"><span class="dot dot--yellow"></span>Experimental</span>
		<div class="tcard__head">
			<span class="avatar " style="background:var(--wmf-green-aaa)" aria-hidden="true">E</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="exp" aria-label="Quick look: Exp" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Exp</button>
				<div class="tcard__maint">by <span dir="auto">Unknown</span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
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
						<label class="sort"><span class="skip-label">Sort by</span><select id="sort"><option value="recent">Recently updated</option><option value="name">Name (A–Z)</option><option value="complete">Most complete</option></select></label>
					</span>
				</div>
				<p class="empty">No tools match these filters.</p>
				<nav class="pager" aria-label="Pagination"></nav>
			</div>
		</div>
	</div>`
};

function expect(name, actual) {
	if (BAKE) {
		fs.writeFileSync(`${SCRATCH}/search__${name}.txt`, actual);
		return;
	}
	assert.equal(actual, S[name], name);
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
	h.paginate.mockResolvedValue([]);
	setUrl("");
});

test("search default (exp off, no query, populated results)", async () => {
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

test("search exp on, query, sort=views, page=2, popular cards", async () => {
	applyExp(true);
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
	expect("exp_views", r.html);
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

async function sortValueFor(qs, exp = false) {
	applyExp(exp);
	setUrl(qs);
	h.apiGet.mockResolvedValue({ results: [], count: 0, facets: {} });
	const r = await search.viewSearch();
	document.body.innerHTML = r.html;
	r.mount();
	return document.querySelector("#sort").value;
}

test("ordering=-modified_date maps to recent (exp on so it differs from the relevance default)", async () =>
	assert.equal(await sortValueFor("ordering=-modified_date", true), "recent"));
test("ordering=name maps to name", async () => assert.equal(await sortValueFor("ordering=name"), "name"));
test("ordering=-score maps to relevance (exp on)", async () =>
	assert.equal(await sortValueFor("ordering=-score", true), "relevance"));
test("unknown ordering falls back to default recent (exp off)", async () =>
	assert.equal(await sortValueFor("ordering=zzz"), "recent"));
test("exp on default sort is relevance", async () => assert.equal(await sortValueFor("", true), "relevance"));
test("disallowed sort (views, exp off) falls back to recent", async () =>
	assert.equal(await sortValueFor("sort=views"), "recent"));
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
	sortEl.value = "recent"; // === defaultSort (exp off)
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

async function apiParamsFor(qs, exp = false) {
	applyExp(exp);
	setUrl(qs);
	let captured;
	h.apiGet.mockImplementation(async (path, params) => {
		if (path === "/search/tools/") captured = String(params);
		return { results: [], count: 0, facets: {} };
	});
	await search.viewSearch();
	return captured;
}

test("api params: default (no query, exp off) → recent ordering", async () => {
	assert.equal(await apiParamsFor(""), "page=1&page_size=24&ordering=-modified_date");
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
test("api params: exp on sort=recent → recent stays allowed (ordering kept)", async () => {
	assert.equal(await apiParamsFor("sort=recent", true), "page=1&page_size=24&ordering=-modified_date");
});
test("api params: exp off sort=name stays allowed (ordering=name)", async () => {
	assert.equal(await apiParamsFor("sort=name"), "page=1&page_size=24&ordering=name");
});
test("api params: exp on sort=name stays allowed (ordering=name)", async () => {
	assert.equal(await apiParamsFor("sort=name", true), "page=1&page_size=24&ordering=name");
});
test("api params: only *__term filters are forwarded (others dropped)", async () => {
	assert.equal(
		await apiParamsFor("audiences__term=editor&extra=x"),
		"page=1&page_size=24&ordering=-modified_date&audiences__term=editor"
	);
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
