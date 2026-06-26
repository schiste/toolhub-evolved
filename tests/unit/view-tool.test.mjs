// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import fs from "node:fs";
import { test, vi, beforeEach } from "vitest";

const SCRATCH =
	"/private/tmp/claude-501/-Users-christophehenner-Downloads-Wikimedia-striker-toolhub-demo/bad07c6e-1967-4490-8d44-3fe4ee515e59/scratchpad";
const BAKE = process.env.BAKE === "1";

const h = vi.hoisted(() => ({
	getTool: vi.fn(),
	isNewTool: vi.fn(),
	apiGet: vi.fn(),
	egoGraph: vi.fn(),
	listMemberships: vi.fn(),
	getSimilarityIndex: vi.fn(),
	nearestNeighbors: vi.fn(),
	demoRevisionsFor: vi.fn(),
	forceGraph: vi.fn(),
	openQuickView: vi.fn()
}));

vi.mock("../../public_html/lib/core/api.js", async (orig) => {
	const actual = await orig();
	return { ...actual, getTool: h.getTool, isNewTool: h.isNewTool, apiGet: h.apiGet };
});
vi.mock("../../public_html/lib/core/graph.js", async (orig) => {
	const actual = await orig();
	return { ...actual, egoGraph: h.egoGraph };
});
vi.mock("../../public_html/lib/core/signals.js", async (orig) => {
	const actual = await orig();
	return { ...actual, listMemberships: h.listMemberships };
});
vi.mock("../../public_html/lib/core/similarity.js", async (orig) => {
	const actual = await orig();
	return { ...actual, getSimilarityIndex: h.getSimilarityIndex, nearestNeighbors: h.nearestNeighbors };
});
vi.mock("../../public_html/lib/core/store.js", async (orig) => {
	const actual = await orig();
	return { ...actual, demoRevisionsFor: h.demoRevisionsFor };
});
vi.mock("../../public_html/lib/organisms/force-graph.js", async (orig) => {
	const actual = await orig();
	return { ...actual, forceGraph: h.forceGraph };
});
vi.mock("../../public_html/lib/organisms/quickview.js", async (orig) => {
	const actual = await orig();
	return { ...actual, openQuickView: h.openQuickView };
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
const tool = await import("../../public_html/views/tool.js");

const S = {
	deprecated: `
	<div class="container page">
		<a class="back" href="/search">← Back to tools</a>
		<header class="toolpage__head">
			<span class="avatar avatar--lg" style="background:var(--wmf-red-aaa)" aria-hidden="true">D</span>
			<div class="toolpage__id">
				<h1 class="toolpage__title" dir="auto">Deprecated Tool</h1>
				
				<div class="toolpage__by">by <span class="author-ref"><a href="/by/Unknown" dir="auto">Unknown</a></span></div>
				
				<div class="toolpage__notice">Replaced by <a href="/tools/replacement-tool" dir="auto">replacement-tool</a></div>
				<div class="toolpage__prov"><span class="exp-badge">Demo submission</span> <span class="exp-badge">Edited · demo</span> <span class="exp-badge">Community annotations · demo</span></div>
				<div class="toolpage__glance"><span class="glance" dir="auto">Any wiki</span></div>
				<div class="toolpage__row">
					<span class="status status--green"><span class="dot dot--green"></span>Healthy</span>
					
					
					<u|2026-01-01T00:00:00Z|toolpage__when>
					<span class="signal">Maintained</span>
					<!-- EXPERIMENTAL — operational health. Needs: an uptime/health-check service. -->
					<span class="status status--green experimental"><span class="dot dot--green"></span>Healthy</span>
					<!-- EXPERIMENTAL — popularity. Needs: usage/view tracking the API doesn't expose. -->
					<span class="views experimental"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 17h16v2H1V1h2z"/><path d="M19 5v10H5v-1l4.5-5.5 3 3.5L18 5z"/></svg> 100 views</span>
				</div>
			</div>
			<div class="toolpage__cta">
				
				<button class="favbtn favbtn--btn favbtn--lg" type="button" data-fav="dep" aria-pressed="false" aria-label="Save to favorites"><span class="favbtn__ic" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M12.744 6.793H18.5l.607 1.795-4.7 3.589 1.802 5.828-1.563 1.09L10 15.545l-4.646 3.55-1.563-1.09 1.8-5.828-4.698-3.59.607-1.794h5.756l1.789-5.788h1.91l1.79 5.788Z"/></svg></span><span class="favbtn__t">Save</span></button>
				<!-- EXPERIMENTAL — Save to a list. Needs: POST/PUT /api/lists/ (Lane B). -->
				<details class="savemenu">
		<summary class="btn btn--outline"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m13 18-1.707.707L8 15.414l-3.293 3.293L3 18V5h10z"/><path d="M17 15h-2V3H6V1h11z"/></svg> Save to a list</summary>
		<div class="savemenu__pop"><p class="savemenu__empty">No lists yet.</p><a class="savemenu__new" href="/lists/create"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.005 9H16v2h-4.995v5.005h-2V11H4V9h5.005V4.005h2z"/></svg> New list…</a></div>
	</details>
			</div>
		</header>

		<div class="toolpage__grid">
			<div class="toolpage__main">
				<!-- EXPERIMENTAL — screenshots/preview. Needs: a screenshot field in the
				     toolinfo schema + image storage (no per-tool data possible here). -->
				<div class="experimental shotstrip">
					<div class="shotstrip__copy">
						<span class="exp-badge shotstrip__badge">Screenshots · prospective feature</span>
						<span class="shotstrip__note">Toolhub has no screenshot field yet; these frames are placeholders.</span>
					</div>
					<div class="shotstrip__frames" aria-hidden="true">
						<div class="shot shot--hero"><span class="avatar avatar--lg" style="background:var(--wmf-red-aaa)" aria-hidden="true">D</span></div>
						<div class="shot shot--split"><span></span><span></span></div>
						<div class="shot shot--stack"><span></span><span></span><span></span></div>
					</div>
				</div>

				<div class="prose"><em>No description provided.</em></div>
				<div class="tcard__tags toolpage__tags">—</div>

				<h2 class="toolpage__h2">Details</h2>
				<div class="detail__meta">
					<div><div class="meta__k">Type</div><div class="meta__v" dir="auto">—</div></div>
					<div><div class="meta__k">License</div><div class="meta__v" dir="auto">—</div></div>
					<div><div class="meta__k">Works on</div><div class="meta__v" dir="auto">Any wiki</div></div>
					<div><div class="meta__k">Interface languages</div><div class="meta__v" dir="auto">English (default)</div></div>
					<div><div class="meta__k">Technology</div><div class="meta__v" dir="auto">—</div></div>
					<div><div class="meta__k">Audiences</div><div class="meta__v" dir="auto">—</div></div>
				</div>

				<!-- EXPERIMENTAL — thanks. Needs: an authenticated appreciation event model with abuse controls. -->
				<div class="experimental thanks">
					<h2 class="toolpage__h2">Thanks <span class="exp-badge">Experimental</span></h2>
					<div class="thanks__agg">
						<span class="thanks__icon" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.039 3.656c2.158-2.332 5.937-2.179 7.893.318a4.99 4.99 0 01-.272 6.487L10.757 19H9.243L1.34 10.461a4.99 4.99 0 01-.272-6.487c1.956-2.497 5.735-2.65 7.893-.318L10 4.776z"/></svg></span>
						<span class="thanks__score">86</span>
						<span class="thanks__count">people thanked</span>
					</div>
					<button class="btn btn--outline btn--md" type="button" disabled>Thank maintainers</button>
				</div>

				
				
			</div>

			<aside class="toolpage__side">
				<div class="panel">
					<h2 class="panel__title">Get started</h2>
					<div class="toolpage__actions"><span class="meta__v">No links provided</span></div>
					<div class="toolpage__sub">
						<a href="/tools/dep/history">View history</a>
						<a href="/tools/dep/edit">Edit tool</a> <a href="/tools/dep/edit-annotations">Edit annotations</a>
					</div>
				</div>
				<div class="panel">
					<h2 class="panel__title">Maintainers</h2>
					<ul class="maint-list"><li><span class="avatar " style="background:var(--wmf-purple)" aria-hidden="true">U</span><span class="maint-list__name"><span class="author-ref"><a href="/by/Unknown" dir="auto">Unknown</a></span></span></li></ul>
				</div>
				<div class="panel">
					<h2 class="panel__title">Listing completeness</h2>
					<span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span>
					<ul class="complete-list"><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Description</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Tool URL</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Source repository</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>License</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Keywords</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Audience or task tagged</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Documentation</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Icon</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Issue tracker or feedback</span></li></ul>
				</div>
				<!-- EXPERIMENTAL — usage stat. Needs: usage analytics the API doesn't expose. -->
				<div class="panel experimental">
					<h2 class="panel__title">Usage <span class="exp-badge">Experimental</span></h2>
					<p class="usage"><strong>4,115</strong> editors used this in the last 30 days</p>
				</div>
			</aside>
		</div>
	</div>`,
	full: `
	<div class="container page">
		<a class="back" href="/search">← Back to tools</a>
		<header class="toolpage__head">
			<span class="avatar avatar--lg" style="background:var(--wmf-green-aaa)" aria-hidden="true">F</span>
			<div class="toolpage__id">
				<h1 class="toolpage__title" dir="auto">Full Tool</h1>
				<p class="toolpage__subtitle" dir="auto">A subtitle</p>
				<div class="toolpage__by">by <span class="author-ref"><a href="/by/Ada%20Lovelace" dir="auto">Ada Lovelace</a><a class="author-ref__external" href="https://example.org/ada" target="_blank" rel="noopener nofollow" aria-label="External profile for Ada Lovelace"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg></a></span><span class="toolpage__sep">, </span><span class="author-ref"><a href="/by/Grace%20Hopper" dir="auto">Grace Hopper</a><a class="author-ref__external" href="https://meta.wikimedia.org/wiki/User:Grace" target="_blank" rel="noopener nofollow" aria-label="External profile for Grace Hopper"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg></a></span></div>
				<div class="toolpage__sponsor"><span class="toolpage__label">Sponsor:</span> <span dir="auto">Wikimedia Foundation</span></div>
				
				<div class="toolpage__prov"><a class="glance toolpage__wikidata" href="https://www.wikidata.org/wiki/Q123" target="_blank" rel="noopener nofollow">Wikidata: <span dir="auto">Q123</span><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg></a></div>
				<div class="toolpage__glance"><span class="glance" dir="auto">web app</span><span class="glance" dir="auto">GPL-3.0-or-later</span><span class="glance" dir="auto">commons.wikimedia.org</span><span class="glance">2 languages</span></div>
				<div class="toolpage__row">
					
					<span class="signal" title="Appears in 1 curated list"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 16H1v-2h2zm16 0H5v-2h14zM3 11H1V9h2zm16 0H5V9h14zM3 6H1V4h2zm16 0H5V4h14z"/></svg> In 1 list</span>
					
					<u|2026-01-01T00:00:00Z|toolpage__when>
					<span class="signal">Maintained</span>
					<!-- EXPERIMENTAL — operational health. Needs: an uptime/health-check service. -->
					<span class="status status--green experimental"><span class="dot dot--green"></span>Healthy</span>
					<!-- EXPERIMENTAL — popularity. Needs: usage/view tracking the API doesn't expose. -->
					<span class="views experimental"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 17h16v2H1V1h2z"/><path d="M19 5v10H5v-1l4.5-5.5 3 3.5L18 5z"/></svg> 100 views</span>
				</div>
			</div>
			<div class="toolpage__cta">
				<a class="btn btn--primary btn--lg" href="https://example.org/full" target="_blank" rel="noopener nofollow"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg> Open tool</a>
				<button class="favbtn favbtn--btn favbtn--lg" type="button" data-fav="full" aria-pressed="false" aria-label="Save to favorites"><span class="favbtn__ic" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M12.744 6.793H18.5l.607 1.795-4.7 3.589 1.802 5.828-1.563 1.09L10 15.545l-4.646 3.55-1.563-1.09 1.8-5.828-4.698-3.59.607-1.794h5.756l1.789-5.788h1.91l1.79 5.788Z"/></svg></span><span class="favbtn__t">Save</span></button>
				<!-- EXPERIMENTAL — Save to a list. Needs: POST/PUT /api/lists/ (Lane B). -->
				<details class="savemenu">
		<summary class="btn btn--outline"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m13 18-1.707.707L8 15.414l-3.293 3.293L3 18V5h10z"/><path d="M17 15h-2V3H6V1h11z"/></svg> Save to a list</summary>
		<div class="savemenu__pop"><p class="savemenu__empty">No lists yet.</p><a class="savemenu__new" href="/lists/create"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.005 9H16v2h-4.995v5.005h-2V11H4V9h5.005V4.005h2z"/></svg> New list…</a></div>
	</details>
			</div>
		</header>

		<div class="toolpage__grid">
			<div class="toolpage__main">
				<!-- EXPERIMENTAL — screenshots/preview. Needs: a screenshot field in the
				     toolinfo schema + image storage (no per-tool data possible here). -->
				<div class="experimental shotstrip">
					<div class="shotstrip__copy">
						<span class="exp-badge shotstrip__badge">Screenshots · prospective feature</span>
						<span class="shotstrip__note">Toolhub has no screenshot field yet; these frames are placeholders.</span>
					</div>
					<div class="shotstrip__frames" aria-hidden="true">
						<div class="shot shot--hero"><span class="avatar avatar--lg" style="background:var(--wmf-green-aaa)" aria-hidden="true">F</span></div>
						<div class="shot shot--split"><span></span><span></span></div>
						<div class="shot shot--stack"><span></span><span></span><span></span></div>
					</div>
				</div>

				<div class="prose" dir="auto"><p>A <strong>bold</strong> description with enough length to render markdown here.</p></div>
				<div class="tcard__tags toolpage__tags"><a class="tag" href="/search?keywords__term=maps" dir="auto">maps</a><a class="tag" href="/search?keywords__term=commons" dir="auto">commons</a></div>

				<h2 class="toolpage__h2">Details</h2>
				<div class="detail__meta">
					<div><div class="meta__k">Type</div><div class="meta__v" dir="auto">web app</div></div>
					<div><div class="meta__k">License</div><div class="meta__v" dir="auto">GPL-3.0-or-later</div></div>
					<div><div class="meta__k">Works on</div><div class="meta__v" dir="auto">commons.wikimedia.org</div></div>
					<div><div class="meta__k">Interface languages</div><div class="meta__v" dir="auto">en, fr</div></div>
					<div><div class="meta__k">Technology</div><div class="meta__v" dir="auto">JavaScript, Python</div></div>
					<div><div class="meta__k">Audiences</div><div class="meta__v" dir="auto">editors</div></div>
				</div>

				<!-- EXPERIMENTAL — thanks. Needs: an authenticated appreciation event model with abuse controls. -->
				<div class="experimental thanks">
					<h2 class="toolpage__h2">Thanks <span class="exp-badge">Experimental</span></h2>
					<div class="thanks__agg">
						<span class="thanks__icon" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.039 3.656c2.158-2.332 5.937-2.179 7.893.318a4.99 4.99 0 01-.272 6.487L10.757 19H9.243L1.34 10.461a4.99 4.99 0 01-.272-6.487c1.956-2.497 5.735-2.65 7.893-.318L10 4.776z"/></svg></span>
						<span class="thanks__score">122</span>
						<span class="thanks__count">people thanked</span>
					</div>
					<button class="btn btn--outline btn--md" type="button" disabled>Thank maintainers</button>
				</div>

				<section class="related" aria-labelledby="related-title">
				<div class="section-head"><h2 id="related-title">Related tools</h2></div>
				<p class="related__subtitle">Overlapping function and scope, by shared metadata.</p>
				<div class="related__list">
		<article class="related__item" data-tool="rel-1">
			<span class="avatar " style="background:var(--wmf-red-aaa)" aria-hidden="true">R</span>
			<div class="related__body">
				<div class="related__titleline">
					<button class="related__title" type="button" data-tool="rel-1" aria-label="Quick look: Related One" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Related One</button>
					
				</div>
				<div class="related__maint">by <span dir="auto">Maint R</span></div>
				<div class="related__chips"><span class="tag">maps</span><span class="tag">commons</span></div>
			</div>
		</article>
		<article class="related__item" data-tool="rel-2">
			<span class="avatar " style="background:var(--color-progressive-hover)" aria-hidden="true">R</span>
			<div class="related__body">
				<div class="related__titleline">
					<button class="related__title" type="button" data-tool="rel-2" aria-label="Quick look: Related Two" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Related Two</button>
					<span class="related__status status status--red"><span class="dot dot--red"></span>Deprecated</span>
				</div>
				<div class="related__maint">by <span dir="auto">Unknown</span></div>
				
			</div>
		</article></div>
			</section>
				<section class="neighborhood" aria-labelledby="neighborhood-title">
				<div class="section-head"><h2 id="neighborhood-title">Neighborhood</h2></div>
				<div class="graph graph--ego"><div id="ego-canvas"></div></div>
				<p class="graph__caption">This tool and its nearest neighbors by metadata. Click a node to peek.</p>
			</section>
			</div>

			<aside class="toolpage__side">
				<div class="panel">
					<h2 class="panel__title">Get started</h2>
					<div class="toolpage__actions"><a class="btn btn--outline btn--md" href="https://example.org/full" target="_blank" rel="noopener nofollow"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg> Open tool</a><a class="btn btn--outline btn--md" href="https://github.com/example/full" target="_blank" rel="noopener nofollow"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg> Source code</a><a class="btn btn--outline btn--md" href="https://example.org/full/api" target="_blank" rel="noopener nofollow"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg> API</a><a class="btn btn--outline btn--md" href="https://example.org/full/docs" target="_blank" rel="noopener nofollow"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg> User docs</a><a class="btn btn--outline btn--md" href="https://example.org/full/dev" target="_blank" rel="noopener nofollow"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg> Developer docs</a><a class="btn btn--outline btn--md" href="https://github.com/example/full/issues" target="_blank" rel="noopener nofollow"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg> Report a bug</a><a class="btn btn--outline btn--md" href="https://example.org/full/feedback" target="_blank" rel="noopener nofollow"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg> Give feedback</a><a class="btn btn--outline btn--md" href="https://translatewiki.net/full" target="_blank" rel="noopener nofollow"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg> Translate</a></div>
					<div class="toolpage__sub">
						<a href="/tools/full/history">View history</a>
						<a href="/tools/full/edit">Edit tool</a> <a href="/tools/full/edit-annotations">Edit annotations</a>
					</div>
				</div>
				<div class="panel">
					<h2 class="panel__title">Maintainers</h2>
					<ul class="maint-list"><li><span class="avatar " style="background:var(--wmf-red-aaa)" aria-hidden="true">A</span><span class="maint-list__name"><span class="author-ref"><a href="/by/Ada%20Lovelace" dir="auto">Ada Lovelace</a><a class="author-ref__external" href="https://example.org/ada" target="_blank" rel="noopener nofollow" aria-label="External profile for Ada Lovelace"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg></a></span></span></li><li><span class="avatar " style="background:var(--wmf-purple)" aria-hidden="true">G</span><span class="maint-list__name"><span class="author-ref"><a href="/by/Grace%20Hopper" dir="auto">Grace Hopper</a><a class="author-ref__external" href="https://meta.wikimedia.org/wiki/User:Grace" target="_blank" rel="noopener nofollow" aria-label="External profile for Grace Hopper"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg></a></span></span></li></ul>
				</div>
				<div class="panel">
					<h2 class="panel__title">Listing completeness</h2>
					<span class="signal" title="Listing 8 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:89%"></span></span>8/9</span>
					<ul class="complete-list"><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>Description</span></li><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>Tool URL</span></li><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>Source repository</span></li><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>License</span></li><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>Keywords</span></li><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>Audience or task tagged</span></li><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>Documentation</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Icon</span></li><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>Issue tracker or feedback</span></li></ul>
				</div>
				<!-- EXPERIMENTAL — usage stat. Needs: usage analytics the API doesn't expose. -->
				<div class="panel experimental">
					<h2 class="panel__title">Usage <span class="exp-badge">Experimental</span></h2>
					<p class="usage"><strong>6,315</strong> editors used this in the last 30 days</p>
				</div>
			</aside>
		</div>
	</div>`,
	history: `
		<div class="container page">
			<a class="back" href="/tools/hist">← Back to Hist Tool</a>
			<h1 class="page__title">Revision history</h1>
			<ul class="feed">
		<li><svg class="icon feed__ic" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 1a9 9 0 011 17.945V16.93A7.001 7.001 0 0010 3a7 7 0 00-4 12.743V13h2.001L8 18l-1 1H2v-2l2.346-.001A8.97 8.97 0 011 10a9 9 0 019-9"/><path d="M11 10h3.5v2H9V6h2z"/></svg>
			<span class="feed__main">Revision by <strong dir="auto">Demo User</strong> · <t|2026-02-02T00:00:00Z||> — <span dir="auto">demo edit</span> <span class="tag">current</span></span>
			<span class="feed__when">#d1</span></li>
		<li><svg class="icon feed__ic" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 1a9 9 0 011 17.945V16.93A7.001 7.001 0 0010 3a7 7 0 00-4 12.743V13h2.001L8 18l-1 1H2v-2l2.346-.001A8.97 8.97 0 011 10a9 9 0 019-9"/><path d="M11 10h3.5v2H9V6h2z"/></svg>
			<span class="feed__main">Revision by <strong dir="auto">Live User</strong> · <t|2026-01-01T00:00:00Z||></span>
			<span class="feed__when">#99</span></li></ul>
		</div>`,
	minimal: `
	<div class="container page">
		<a class="back" href="/search">← Back to tools</a>
		<header class="toolpage__head">
			<span class="avatar avatar--lg" style="background:var(--color-text-muted)" aria-hidden="true">M</span>
			<div class="toolpage__id">
				<h1 class="toolpage__title" dir="auto">Minimal Tool</h1>
				
				<div class="toolpage__by">by <span class="author-ref"><a href="/by/Unknown" dir="auto">Unknown</a></span></div>
				
				
				
				<div class="toolpage__glance"><span class="glance" dir="auto">Any wiki</span></div>
				<div class="toolpage__row">
					
					
					
					<u|2026-01-01T00:00:00Z|toolpage__when>
					<span class="signal">Maintained</span>
					<!-- EXPERIMENTAL — operational health. Needs: an uptime/health-check service. -->
					<span class="status status--green experimental"><span class="dot dot--green"></span>Healthy</span>
					<!-- EXPERIMENTAL — popularity. Needs: usage/view tracking the API doesn't expose. -->
					<span class="views experimental"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 17h16v2H1V1h2z"/><path d="M19 5v10H5v-1l4.5-5.5 3 3.5L18 5z"/></svg> 100 views</span>
				</div>
			</div>
			<div class="toolpage__cta">
				
				
				<!-- EXPERIMENTAL — Save to a list. Needs: POST/PUT /api/lists/ (Lane B). -->
				
			</div>
		</header>

		<div class="toolpage__grid">
			<div class="toolpage__main">
				<!-- EXPERIMENTAL — screenshots/preview. Needs: a screenshot field in the
				     toolinfo schema + image storage (no per-tool data possible here). -->
				<div class="experimental shotstrip">
					<div class="shotstrip__copy">
						<span class="exp-badge shotstrip__badge">Screenshots · prospective feature</span>
						<span class="shotstrip__note">Toolhub has no screenshot field yet; these frames are placeholders.</span>
					</div>
					<div class="shotstrip__frames" aria-hidden="true">
						<div class="shot shot--hero"><span class="avatar avatar--lg" style="background:var(--color-text-muted)" aria-hidden="true">M</span></div>
						<div class="shot shot--split"><span></span><span></span></div>
						<div class="shot shot--stack"><span></span><span></span><span></span></div>
					</div>
				</div>

				<div class="prose"><em>No description provided.</em></div>
				<div class="tcard__tags toolpage__tags">—</div>

				<h2 class="toolpage__h2">Details</h2>
				<div class="detail__meta">
					<div><div class="meta__k">Type</div><div class="meta__v" dir="auto">—</div></div>
					<div><div class="meta__k">License</div><div class="meta__v" dir="auto">—</div></div>
					<div><div class="meta__k">Works on</div><div class="meta__v" dir="auto">Any wiki</div></div>
					<div><div class="meta__k">Interface languages</div><div class="meta__v" dir="auto">English (default)</div></div>
					<div><div class="meta__k">Technology</div><div class="meta__v" dir="auto">—</div></div>
					<div><div class="meta__k">Audiences</div><div class="meta__v" dir="auto">—</div></div>
				</div>

				<!-- EXPERIMENTAL — thanks. Needs: an authenticated appreciation event model with abuse controls. -->
				<div class="experimental thanks">
					<h2 class="toolpage__h2">Thanks <span class="exp-badge">Experimental</span></h2>
					<div class="thanks__agg">
						<span class="thanks__icon" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.039 3.656c2.158-2.332 5.937-2.179 7.893.318a4.99 4.99 0 01-.272 6.487L10.757 19H9.243L1.34 10.461a4.99 4.99 0 01-.272-6.487c1.956-2.497 5.735-2.65 7.893-.318L10 4.776z"/></svg></span>
						<span class="thanks__score">8</span>
						<span class="thanks__count">people thanked</span>
					</div>
					<button class="btn btn--outline btn--md" type="button" disabled>Thank maintainers</button>
				</div>

				
				
			</div>

			<aside class="toolpage__side">
				<div class="panel">
					<h2 class="panel__title">Get started</h2>
					<div class="toolpage__actions"><span class="meta__v">No links provided</span></div>
					<div class="toolpage__sub">
						<a href="/tools/minimal/history">View history</a>
						<a href="/tools/minimal/edit">Suggest an edit</a>
					</div>
				</div>
				<div class="panel">
					<h2 class="panel__title">Maintainers</h2>
					<ul class="maint-list"><li><span class="avatar " style="background:var(--wmf-purple)" aria-hidden="true">U</span><span class="maint-list__name"><span class="author-ref"><a href="/by/Unknown" dir="auto">Unknown</a></span></span></li></ul>
				</div>
				<div class="panel">
					<h2 class="panel__title">Listing completeness</h2>
					<span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span>
					<ul class="complete-list"><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Description</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Tool URL</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Source repository</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>License</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Keywords</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Audience or task tagged</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Documentation</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Icon</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>Issue tracker or feedback</span></li></ul>
				</div>
				<!-- EXPERIMENTAL — usage stat. Needs: usage analytics the API doesn't expose. -->
				<div class="panel experimental">
					<h2 class="panel__title">Usage <span class="exp-badge">Experimental</span></h2>
					<p class="usage"><strong>2,943</strong> editors used this in the last 30 days</p>
				</div>
			</aside>
		</div>
	</div>`,
	notfound: `
		<div class="container page">
			<a class="back" href="/search">← Back to tools</a>
			<h1 class="page__title">Tool not found</h1>
			<p class="page__intro">The record for <code dir="auto">ghost</code> may have been <strong>deleted, renamed, or never registered</strong>.</p>
			<p><a href="/search?q=ghost">Search for "ghost"</a> · <a href="/search">Browse all tools</a></p>
		</div>`
};

function expect(name, actual) {
	if (BAKE) {
		fs.writeFileSync(`${SCRATCH}/tool__${name}.txt`, actual);
		return;
	}
	assert.equal(actual, S[name], name);
}

function toolFixture(name, o = {}) {
	return {
		name,
		title: o.title ?? name,
		description: o.description ?? "",
		url: o.url ?? "",
		icon: o.icon ?? null,
		keywords: o.keywords ?? [],
		maintainer: o.maintainer ?? "Unknown",
		authors: o.authors ?? [],
		authorObjs: o.authorObjs ?? [],
		wikidata: o.wikidata ?? null,
		subtitle: o.subtitle ?? null,
		sponsor: o.sponsor ?? [],
		replacedBy: o.replacedBy ?? null,
		toolType: o.toolType ?? null,
		license: o.license ?? null,
		repository: o.repository ?? null,
		apiUrl: o.apiUrl ?? null,
		technologyUsed: o.technologyUsed ?? [],
		audiences: o.audiences ?? [],
		tasks: o.tasks ?? [],
		forWikis: o.forWikis ?? [],
		uiLanguages: o.uiLanguages ?? [],
		userDocs: o.userDocs ?? null,
		devDocs: o.devDocs ?? null,
		feedback: o.feedback ?? null,
		bugtracker: o.bugtracker ?? null,
		translate: o.translate ?? null,
		deprecated: o.deprecated ?? false,
		experimental: o.experimental ?? false,
		modified: o.modified ?? "2026-01-01T00:00:00Z",
		origin: o.origin ?? "crawler",
		weeklyViews: o.weeklyViews ?? 100,
		...o
	};
}

beforeEach(() => {
	localStorage.clear();
	applyExp(false);
	document.body.innerHTML = "";
	for (const fn of Object.values(h)) fn.mockReset();
	h.isNewTool.mockReturnValue(false);
	h.listMemberships.mockResolvedValue(new Map());
	h.nearestNeighbors.mockReturnValue([]);
	h.getSimilarityIndex.mockResolvedValue({ tools: [], byName: new Map(), vectors: new Map() });
	h.egoGraph.mockResolvedValue({ nodes: [], edges: [] });
	h.demoRevisionsFor.mockReturnValue([]);
	h.apiGet.mockResolvedValue({ results: [] });
});

/* ---------------- viewTool ---------------- */

test("viewTool not found", async () => {
	h.getTool.mockResolvedValue(null);
	const r = await tool.viewTool("ghost");
	assert.equal(r.title, "Tool not found — Toolhub");
	expect("notfound", r.html);
});

test("viewTool minimal (signed out, sparse fields, no related, no ego)", async () => {
	h.getTool.mockResolvedValue(toolFixture("minimal", { title: "Minimal Tool" }));
	const r = await tool.viewTool("minimal");
	assert.equal(r.title, "Minimal Tool — Toolhub");
	expect("minimal", r.html);
});

test("viewTool full (signed in, rich fields, related + ego graph)", async () => {
	applyExp(true);
	h.listMemberships.mockResolvedValue(new Map([["full", [{ id: "L1", title: "List One" }]]]));
	h.nearestNeighbors.mockReturnValue([
		{ tool: toolFixture("rel-1", { title: "Related One", maintainer: "Maint R" }), shared: ["maps", "commons"] },
		{ tool: toolFixture("rel-2", { title: "Related Two", deprecated: true }), shared: [] }
	]);
	h.egoGraph.mockResolvedValue({
		nodes: [{ id: "full" }, { id: "rel-1" }, { id: "rel-2" }],
		edges: [{ source: "full", target: "rel-1", weight: 0.5 }]
	});
	const t = toolFixture("full", {
		title: "Full Tool",
		subtitle: "A subtitle",
		description: "A **bold** description with enough length to render markdown here.",
		url: "https://example.org/full",
		repository: "https://github.com/example/full",
		apiUrl: "https://example.org/full/api",
		userDocs: "https://example.org/full/docs",
		devDocs: "https://example.org/full/dev",
		feedback: "https://example.org/full/feedback",
		bugtracker: "https://github.com/example/full/issues",
		translate: "https://translatewiki.net/full",
		license: "GPL-3.0-or-later",
		toolType: "web app",
		wikidata: "Q123",
		sponsor: ["Wikimedia Foundation"],
		keywords: ["maps", "commons"],
		audiences: ["editors"],
		tasks: ["editing"],
		forWikis: ["commons.wikimedia.org"],
		uiLanguages: ["en", "fr"],
		technologyUsed: ["JavaScript", "Python"],
		authors: ["Ada Lovelace", "Grace Hopper"],
		authorObjs: [
			{ name: "Ada Lovelace", url: "https://example.org/ada", wikiUsername: "Ada" },
			{ name: "Grace Hopper", url: null, wikiUsername: "Grace" }
		]
	});
	h.getTool.mockResolvedValue(t);
	const r = await tool.viewTool("full");
	assert.equal(r.title, "Full Tool — Toolhub");
	expect("full", r.html);
});

test("viewTool deprecated with replacement (string name) + new-tool/edited/annotated badges", async () => {
	applyExp(true);
	h.isNewTool.mockReturnValue(true);
	const t = toolFixture("dep", {
		title: "Deprecated Tool",
		deprecated: true,
		replacedBy: "replacement-tool",
		edited: true,
		annotated: true
	});
	h.getTool.mockResolvedValue(t);
	const r = await tool.viewTool("dep");
	expect("deprecated", r.html);
});

test("viewTool deprecated with replacement as URL", async () => {
	h.getTool.mockResolvedValue(
		toolFixture("dep2", { title: "Dep2", deprecated: true, replacedBy: "https://example.org/new" })
	);
	const r = await tool.viewTool("dep2");
	assert.ok(r.html.includes('Replaced by <a href="https://example.org/new"'), "url replacement linked externally");
});

test("viewTool deprecated with replacement as object (name)", async () => {
	h.getTool.mockResolvedValue(
		toolFixture("dep3", { title: "Dep3", deprecated: true, replacedBy: { name: "obj-replacement" } })
	);
	const r = await tool.viewTool("dep3");
	assert.ok(r.html.includes('Replaced by <a href="/tools/obj-replacement"'), "object replacement linked internally");
});

test("viewTool deprecated but no replacement → no notice", async () => {
	h.getTool.mockResolvedValue(toolFixture("dep4", { title: "Dep4", deprecated: true, replacedBy: null }));
	const r = await tool.viewTool("dep4");
	assert.ok(!r.html.includes("toolpage__notice"), "no replacement notice");
});

test("viewTool sponsor as object with url, and as plain object without url", async () => {
	h.getTool.mockResolvedValue(
		toolFixture("sp", {
			title: "Sp",
			sponsor: [{ name: "Sponsor A", url: "https://sponsor.example" }, { name: "Sponsor B" }]
		})
	);
	const r = await tool.viewTool("sp");
	assert.ok(r.html.includes('<a href="https://sponsor.example" target="_blank" rel="noopener nofollow"'));
	assert.ok(r.html.includes(">Sponsor B</span>"));
});

test("viewTool ego graph with fewer than 3 nodes → no neighborhood section", async () => {
	h.getTool.mockResolvedValue(toolFixture("eg", { title: "Eg" }));
	h.egoGraph.mockResolvedValue({ nodes: [{ id: "eg" }, { id: "x" }], edges: [] });
	const r = await tool.viewTool("eg");
	assert.ok(!r.html.includes("neighborhood-title"), "no neighborhood with <3 nodes");
});

test("viewTool ego graph throws → no neighborhood section", async () => {
	h.getTool.mockResolvedValue(toolFixture("eg2", { title: "Eg2" }));
	h.egoGraph.mockRejectedValue(new Error("graph down"));
	const r = await tool.viewTool("eg2");
	assert.ok(!r.html.includes("neighborhood-title"));
});

test("viewTool similarity index throws → no related section", async () => {
	h.getTool.mockResolvedValue(toolFixture("sim", { title: "Sim" }));
	h.getSimilarityIndex.mockRejectedValue(new Error("sim down"));
	const r = await tool.viewTool("sim");
	assert.ok(!r.html.includes("related-title"), "no related section on similarity failure");
});

/* ---------------- viewTool mount ---------------- */

test("mount: builds the force graph when an ego graph is present", async () => {
	h.getTool.mockResolvedValue(toolFixture("g", { title: "G" }));
	h.egoGraph.mockResolvedValue({ nodes: [{ id: "g" }, { id: "a" }, { id: "b" }], edges: [] });
	h.forceGraph.mockReturnValue({ handle: true });
	const r = await tool.viewTool("g");
	document.body.innerHTML = r.html;
	r.mount();
	assert.equal(h.forceGraph.mock.calls.length, 1);
	const [target, ego, opts] = h.forceGraph.mock.calls[0];
	assert.equal(target.id, "ego-canvas");
	assert.deepEqual(ego.nodes.length, 3);
	assert.equal(opts.height, 320);
	assert.equal(opts.onSelect, h.openQuickView);
	assert.deepEqual(target.forceGraphHandle, { handle: true });
});

test("mount: no ego graph → force graph not built", async () => {
	h.getTool.mockResolvedValue(toolFixture("g2", { title: "G2" }));
	h.egoGraph.mockResolvedValue({ nodes: [{ id: "g2" }], edges: [] });
	const r = await tool.viewTool("g2");
	document.body.innerHTML = r.html;
	r.mount();
	assert.equal(h.forceGraph.mock.calls.length, 0);
});

/* ---------------- viewToolHistory ---------------- */

test("viewToolHistory with live + demo revisions", async () => {
	h.getTool.mockResolvedValue(toolFixture("hist", { title: "Hist Tool" }));
	h.demoRevisionsFor.mockReturnValue([
		{ id: "d1", user: { username: "Demo User" }, timestamp: "2026-02-02T00:00:00Z", comment: "demo edit" }
	]);
	h.apiGet.mockResolvedValue({
		results: [{ id: 99, user: { username: "Live User" }, timestamp: "2026-01-01T00:00:00Z", comment: "" }]
	});
	const r = await tool.viewToolHistory("hist");
	assert.equal(r.title, "History: Hist Tool — Toolhub");
	expect("history", r.html);
});

test("viewToolHistory revisions apiGet rejects → demo only", async () => {
	h.getTool.mockResolvedValue(toolFixture("hist2", { title: "Hist2" }));
	h.demoRevisionsFor.mockReturnValue([{ id: "d1", user: null, timestamp: "2026-02-02T00:00:00Z", comment: "" }]);
	h.apiGet.mockRejectedValue(new Error("down"));
	const r = await tool.viewToolHistory("hist2");
	assert.ok(r.html.includes("system</strong>"), "null user falls back to system");
});

test("viewToolHistory no tool + no revisions → viewNotFound", async () => {
	h.getTool.mockResolvedValue(null);
	h.demoRevisionsFor.mockReturnValue([]);
	h.apiGet.mockResolvedValue({ results: [] });
	const r = await tool.viewToolHistory("ghost");
	const { viewNotFound } = await import("../../public_html/views/static.js");
	assert.deepEqual(r, viewNotFound());
});

test("viewToolHistory no tool but revisions exist → title from revision content_title", async () => {
	h.getTool.mockResolvedValue(null);
	h.demoRevisionsFor.mockReturnValue([]);
	h.apiGet.mockResolvedValue({
		results: [{ id: 1, content_title: "Recovered Title", timestamp: "2026-01-01T00:00:00Z" }]
	});
	const r = await tool.viewToolHistory("recovered");
	assert.equal(r.title, "History: Recovered Title — Toolhub");
});

test("viewToolHistory no tool, no content_title → falls back to name", async () => {
	h.getTool.mockResolvedValue(null);
	h.demoRevisionsFor.mockReturnValue([]);
	h.apiGet.mockResolvedValue({ results: [{ id: 1, timestamp: "2026-01-01T00:00:00Z" }] });
	const r = await tool.viewToolHistory("the-name");
	assert.equal(r.title, "History: the-name — Toolhub");
});

test("viewToolHistory empty rows still renders the no-revisions placeholder", async () => {
	h.getTool.mockResolvedValue(toolFixture("hist3", { title: "Hist3" }));
	h.demoRevisionsFor.mockReturnValue([]);
	h.apiGet.mockResolvedValue({ results: [] });
	const r = await tool.viewToolHistory("hist3");
	assert.ok(r.html.includes("No revisions recorded."));
});

/* ---------------- viewDiffStub ---------------- */

test("viewDiffStub with a tool in INDEX", async () => {
	const { INDEX } = await import("../../public_html/lib/core/api.js");
	INDEX["diff-tool"] = toolFixture("diff-tool", { title: "Diff Tool" });
	const r = tool.viewDiffStub("diff-tool");
	assert.equal(r.title, "Revision diff — Toolhub");
	assert.ok(r.html.includes("Revision diff"));
	assert.ok(r.html.includes("<strong>Diff Tool</strong>"));
	delete INDEX["diff-tool"];
});

test("viewDiffStub without a tool in INDEX → falls back to name", async () => {
	const r = tool.viewDiffStub("unknown-tool");
	assert.ok(r.html.includes("<strong>unknown-tool</strong>"));
});

/* ---------------- helper edge cases ---------------- */

test("viewTool(null): not-found renders an empty raw name", async () => {
	h.getTool.mockResolvedValue(null);
	const r = await tool.viewTool(null);
	assert.ok(r.html.includes("<code></code>"), "empty code element for null name");
	assert.ok(r.html.includes('Search for ""'), "empty quoted name");
	assert.ok(r.html.includes('href="/search?q="'), "empty search query");
});

test("authorEntries: reversed authorObjs use find(), and a missing author falls back to {name}", async () => {
	h.getTool.mockResolvedValue(
		toolFixture("auth", {
			title: "Auth",
			authors: ["Alpha", "Bravo", "Gamma"],
			authorObjs: [
				{ name: "Bravo", url: "https://b.example", wikiUsername: null },
				{ name: "Alpha", url: "https://a.example", wikiUsername: null }
				// Gamma intentionally absent → falls back to { name } with no profile
			]
		})
	);
	const r = await tool.viewTool("auth");
	// Alpha resolved via find() → external link to a.example
	assert.ok(
		r.html.includes('href="/by/Alpha" dir="auto">Alpha</a><a class="author-ref__external" href="https://a.example"')
	);
	// Bravo → b.example
	assert.ok(
		r.html.includes('href="/by/Bravo" dir="auto">Bravo</a><a class="author-ref__external" href="https://b.example"')
	);
	// Gamma → no authorObj → no external link
	assert.ok(r.html.includes('href="/by/Gamma" dir="auto">Gamma</a></span>'), "gamma has no external link");
});

test("authorEntries: falsy author names are filtered out", async () => {
	h.getTool.mockResolvedValue(toolFixture("af", { title: "AF", authors: ["Real", ""], authorObjs: [] }));
	const r = await tool.viewTool("af");
	// each author appears twice (by-line + maintainer list); one real author → 2 refs.
	const refs = r.html.match(/class="author-ref"/g) || [];
	assert.equal(refs.length, 2, "only the non-empty author rendered (×2 sections)");
});

test("author with a wiki username only gets a meta external link", async () => {
	h.getTool.mockResolvedValue(
		toolFixture("aw", {
			title: "AW",
			authors: ["Wiki"],
			authorObjs: [{ name: "Wiki", url: null, wikiUsername: "WikiUser" }]
		})
	);
	const r = await tool.viewTool("aw");
	assert.ok(r.html.includes('href="https://meta.wikimedia.org/wiki/User:WikiUser"'));
});

test("sponsorLine: string sponsor renders a plain span", async () => {
	h.getTool.mockResolvedValue(toolFixture("sps", { title: "Sps", sponsor: "Plain Sponsor" }));
	const r = await tool.viewTool("sps");
	assert.ok(r.html.includes('<span dir="auto">Plain Sponsor</span>'));
});

test("sponsorEntry: url-only object uses the url as its label; empty entries drop out; multiple join with ', '", async () => {
	h.getTool.mockResolvedValue(
		toolFixture("sp2", {
			title: "Sp2",
			sponsor: [{ url: "https://only.example" }, {}, "Second"]
		})
	);
	const r = await tool.viewTool("sp2");
	assert.ok(
		r.html.includes(
			'<a href="https://only.example" target="_blank" rel="noopener nofollow" dir="auto">https://only.example</a>'
		)
	);
	assert.ok(
		r.html.includes('https://only.example</a>, <span dir="auto">Second</span>'),
		"joined with ', ' and empty dropped"
	);
});

test("sponsorLine: empty sponsor list renders nothing", async () => {
	h.getTool.mockResolvedValue(toolFixture("sp3", { title: "Sp3", sponsor: [] }));
	const r = await tool.viewTool("sp3");
	assert.ok(!r.html.includes("toolpage__sponsor"));
});

test("replacementNote: object with title (no name) is used", async () => {
	h.getTool.mockResolvedValue(
		toolFixture("rt", { title: "RT", deprecated: true, replacedBy: { title: "By Title" } })
	);
	const r = await tool.viewTool("rt");
	assert.ok(r.html.includes('Replaced by <a href="/tools/By%20Title" dir="auto">By Title</a>'));
});

test("replacementNote: object with neither name nor title → no notice", async () => {
	h.getTool.mockResolvedValue(toolFixture("rt2", { title: "RT2", deprecated: true, replacedBy: { foo: 1 } }));
	const r = await tool.viewTool("rt2");
	assert.ok(!r.html.includes("toolpage__notice"));
	// replacementNote must return "" (inject nothing), not the mutated sentinel
	assert.ok(!r.html.includes("Stryker"), "no stray replacement text");
	assert.ok(!r.html.includes("Replaced by"));
});

test("replacementNote: http (not https) replacement URL is treated as an external link", async () => {
	h.getTool.mockResolvedValue(
		toolFixture("rt3", { title: "RT3", deprecated: true, replacedBy: "http://insecure.example/new" })
	);
	const r = await tool.viewTool("rt3");
	assert.ok(r.html.includes('Replaced by <a href="http://insecure.example/new" target="_blank"'));
});

test("replacementNote: embedded (non-anchored) URL is NOT treated as external", async () => {
	h.getTool.mockResolvedValue(
		toolFixture("rt4", { title: "RT4", deprecated: true, replacedBy: "see https://evil.example" })
	);
	const r = await tool.viewTool("rt4");
	// `/^https?:\/\//` requires the URL at the start; "see https://…" → internal toolHref link
	assert.ok(r.html.includes('Replaced by <a href="/tools/see%20https%3A%2F%2Fevil.example"'));
});

test("wikidataChip trims surrounding whitespace from the qid", async () => {
	h.getTool.mockResolvedValue(toolFixture("wd", { title: "WD", wikidata: "  Q9  " }));
	const r = await tool.viewTool("wd");
	assert.ok(r.html.includes("/wiki/Q9"), "qid trimmed");
	assert.ok(r.html.includes('<span dir="auto">Q9</span>'));
});

test("metaItem Audiences joins multiple values with ', '", async () => {
	h.getTool.mockResolvedValue(toolFixture("aud", { title: "Aud", audiences: ["editors", "admins"] }));
	const r = await tool.viewTool("aud");
	assert.ok(r.html.includes('<div class="meta__v" dir="auto">editors, admins</div>'));
});

test("viewTool with no links shows the no-links placeholder", async () => {
	h.getTool.mockResolvedValue(toolFixture("nolinks", { title: "No Links" }));
	const r = await tool.viewTool("nolinks");
	assert.ok(r.html.includes('<span class="meta__v">No links provided</span>'));
});

test("viewToolHistory requests the encoded revisions path with page_size 20", async () => {
	h.getTool.mockResolvedValue(toolFixture("h n", { title: "H N" }));
	h.apiGet.mockResolvedValue({ results: [] });
	await tool.viewToolHistory("h n");
	assert.deepEqual(h.apiGet.mock.calls[0], ["/tools/h%20n/revisions/", { page_size: "20" }]);
});

test("viewToolHistory {} response → uses the empty results fallback", async () => {
	h.getTool.mockResolvedValue(toolFixture("h5", { title: "H5" }));
	h.demoRevisionsFor.mockReturnValue([
		{ id: "d1", user: { username: "U" }, timestamp: "2026-01-01T00:00:00Z", comment: "" }
	]);
	h.apiGet.mockResolvedValue({}); // no results key → exercises `data.results || []`
	const r = await tool.viewToolHistory("h5");
	const rows = r.html.match(/<li>/g) || [];
	assert.equal(rows.length, 1, "only the demo revision row");
});

/* ---------------- more helper edges ---------------- */

test("authorEntries: duplicate names resolve by index, not by first match", async () => {
	h.getTool.mockResolvedValue(
		toolFixture("dupauth", {
			title: "Dup Auth",
			authors: ["Same", "Same"],
			authorObjs: [
				{ name: "Same", url: "https://first.example", wikiUsername: null },
				{ name: "Same", url: "https://second.example", wikiUsername: null }
			]
		})
	);
	const r = await tool.viewTool("dupauth");
	// the second "Same" must use its positional record (second.example), not find()'s first hit
	assert.ok(r.html.includes("https://second.example"), "positional (byIndex) record used for the duplicate");
});

test("sponsorLine: a falsy (non-array) sponsor renders nothing", async () => {
	h.getTool.mockResolvedValue({ ...toolFixture("spn", { title: "SPN" }), sponsor: null });
	const r = await tool.viewTool("spn");
	assert.ok(!r.html.includes("toolpage__sponsor"), "null sponsor → no sponsor line");
});

test("replacementNote only renders for deprecated tools", async () => {
	h.getTool.mockResolvedValue(toolFixture("nd", { title: "ND", deprecated: false, replacedBy: "something" }));
	const r = await tool.viewTool("nd");
	assert.ok(!r.html.includes("toolpage__notice"), "non-deprecated tool shows no replacement notice");
});

test("Technology/Audiences meta show the em-dash when the arrays are absent", async () => {
	h.getTool.mockResolvedValue({
		...toolFixture("undef", { title: "Undef" }),
		technologyUsed: undefined,
		audiences: undefined
	});
	const r = await tool.viewTool("undef");
	assert.ok(r.html.includes('<div class="meta__k">Technology</div><div class="meta__v" dir="auto">—</div>'));
	assert.ok(r.html.includes('<div class="meta__k">Audiences</div><div class="meta__v" dir="auto">—</div>'));
});

test("viewToolHistory rejects → only the demo revisions remain (no fallback rows)", async () => {
	h.getTool.mockResolvedValue(toolFixture("h6", { title: "H6" }));
	h.demoRevisionsFor.mockReturnValue([
		{ id: "d1", user: { username: "U" }, timestamp: "2026-01-01T00:00:00Z", comment: "" }
	]);
	h.apiGet.mockRejectedValue(new Error("down"));
	const r = await tool.viewToolHistory("h6");
	const rows = r.html.match(/<li>/g) || [];
	assert.equal(rows.length, 1, "exactly the one demo revision");
});

test("sponsorEntry: a null entry in the sponsor list contributes nothing", async () => {
	h.getTool.mockResolvedValue({ ...toolFixture("spnull", { title: "SpNull" }), sponsor: [null] });
	const r = await tool.viewTool("spnull");
	assert.ok(!r.html.includes("toolpage__sponsor"), "null entry → no sponsor line");
});
