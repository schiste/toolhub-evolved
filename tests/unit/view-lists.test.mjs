// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import fs from "node:fs";
import { test, vi, beforeEach } from "vitest";

const SCRATCH =
	"/private/tmp/claude-501/-Users-christophehenner-Downloads-Wikimedia-striker-toolhub-demo/bad07c6e-1967-4490-8d44-3fe4ee515e59/scratchpad";
const BAKE = process.env.BAKE === "1";

const h = vi.hoisted(() => ({
	apiGet: vi.fn(),
	getToolsByName: vi.fn(),
	paginate: vi.fn(),
	navigateTo: vi.fn(),
	demoLists: vi.fn(),
	demoListGet: vi.fn(),
	isDemoListId: vi.fn(),
	demoListNew: vi.fn(),
	demoListSave: vi.fn(),
	demoListDelete: vi.fn(),
	favNames: vi.fn()
}));

vi.mock("../../public_html/lib/core/api.js", async (orig) => {
	const actual = await orig();
	return { ...actual, apiGet: h.apiGet, getToolsByName: h.getToolsByName, paginate: h.paginate };
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
vi.mock("../../public_html/lib/core/store.js", async (orig) => {
	const actual = await orig();
	return {
		...actual,
		demoLists: h.demoLists,
		demoListGet: h.demoListGet,
		isDemoListId: h.isDemoListId,
		demoListNew: h.demoListNew,
		demoListSave: h.demoListSave,
		demoListDelete: h.demoListDelete,
		favNames: h.favNames
	};
});

const { applyExp } = await import("../../public_html/lib/core/session.js");
const { ApiError } = await import("../../public_html/lib/core/api.js");
const lists = await import("../../public_html/views/lists.js");
const { viewNotFound } = await import("../../public_html/views/static.js");

const S = {
	detail_demo: `
	<div class="container page">
		<a class="back" href="/lists">← All lists</a>
		<div class="section-head"><h1 class="page__title" dir="auto">Demo List <span class="exp-badge">Demo list</span> <span class="lcard__count">2 tools</span></h1><a class="btn btn--outline btn--md" href="/lists/demo-1/edit"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m15.765 7.875-8.483 8.484a1 1 0 01-.253.184l-4.214 2.15-1.357-1.33L3.58 13.12q.073-.145.188-.26l8.48-8.48zm3.534-3.532-2.12 2.118-3.517-3.496 2.13-2.13z"/></svg> Edit list</a></div>
		<div class="prose page__intro" dir="auto">demo desc</div>
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
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when><button class="favbtn favbtn--sm" type="button" data-fav="alpha" aria-pressed="false" aria-label="Save to favorites"><span class="favbtn__ic" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M12.744 6.793H18.5l.607 1.795-4.7 3.589 1.802 5.828-1.563 1.09L10 15.545l-4.646 3.55-1.563-1.09 1.8-5.828-4.698-3.59.607-1.794h5.756l1.789-5.788h1.91l1.79 5.788Z"/></svg></span></button></span></div>
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
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when><button class="favbtn favbtn--sm" type="button" data-fav="bravo" aria-pressed="false" aria-label="Save to favorites"><span class="favbtn__ic" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M12.744 6.793H18.5l.607 1.795-4.7 3.589 1.802 5.828-1.563 1.09L10 15.545l-4.646 3.55-1.563-1.09 1.8-5.828-4.698-3.59.607-1.794h5.756l1.789-5.788h1.91l1.79 5.788Z"/></svg></span></button></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li></ul>
	</div>`,
	detail_demo_emptytools: `
	<div class="container page">
		<a class="back" href="/lists">← All lists</a>
		<div class="section-head"><h1 class="page__title" dir="auto">Empty Demo <span class="exp-badge">Demo list</span> <span class="lcard__count">0 tools</span></h1></div>
		<div class="prose page__intro"></div>
		<p class="empty">This list has no tools yet.</p>
	</div>`,
	detail_demo_out: `
	<div class="container page">
		<a class="back" href="/lists">← All lists</a>
		<div class="section-head"><h1 class="page__title" dir="auto">Demo List <span class="exp-badge">Demo list</span> <span class="lcard__count">1 tool</span></h1></div>
		<div class="prose page__intro" dir="auto">demo desc</div>
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
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li></ul>
	</div>`,
	detail_live: `
	<div class="container page">
		<a class="back" href="/lists">← All lists</a>
		<div class="section-head"><h1 class="page__title" dir="auto">Curated One <span class="lcard__count">2 tools</span></h1></div>
		<div class="prose page__intro" dir="auto">First list</div>
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
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
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
	</div>`,
	edit_create: `
	<div class="container page le">
		<a class="back" href="/my-lists">← Back</a>
		<h1 class="page__title">Create a list <span class="exp-badge">Experimental</span></h1>
		<form data-le-form>
			<label class="le__label">Title
		
		<input class="le__input" id="le-title" type="text" required aria-describedby="le-title-err" maxlength="120" value=""  /><span class="le__error" id="le-title-err" hidden></span></label>
			<label class="le__label">Description
		<textarea class="le__input" id="le-desc" rows="3" maxlength="600"></textarea></label>
			<h2 class="le__h2">Tools <span class="le__count" data-le-count></span></h2>
			<ol class="le__tools" data-le-tools></ol>
			<div class="le__add">
				<input class="le__input" id="le-q" type="search" aria-label="Search tools to add" placeholder="Search tools to add…" autocomplete="off" />
				<button class="btn btn--outline btn--md" type="button" data-le-search>Search</button>
			</div>
			<div class="le__results" data-le-results></div>
			<div class="le__actions">
				<button class="btn btn--primary btn--md" type="submit">Create list</button>
				
			</div>
		</form>
	</div>`,
	edit_edit: `
	<div class="container page le">
		<a class="back" href="/lists/demo-1">← Back</a>
		<h1 class="page__title">Edit list <span class="exp-badge">Experimental</span></h1>
		<form data-le-form>
			<label class="le__label">Title
		
		<input class="le__input" id="le-title" type="text" required aria-describedby="le-title-err" maxlength="120" value="Edit Me"  /><span class="le__error" id="le-title-err" hidden></span></label>
			<label class="le__label">Description
		<textarea class="le__input" id="le-desc" rows="3" maxlength="600">desc</textarea></label>
			<h2 class="le__h2">Tools <span class="le__count" data-le-count></span></h2>
			<ol class="le__tools" data-le-tools></ol>
			<div class="le__add">
				<input class="le__input" id="le-q" type="search" aria-label="Search tools to add" placeholder="Search tools to add…" autocomplete="off" />
				<button class="btn btn--outline btn--md" type="button" data-le-search>Search</button>
			</div>
			<div class="le__results" data-le-results></div>
			<div class="le__actions">
				<button class="btn btn--primary btn--md" type="submit">Save changes</button>
				<button class="btn btn--danger btn--md le__delete" type="button" data-le-delete>Delete list</button>
			</div>
		</form>
	</div>`,
	favorites: `
		<div class="container page">
			<h1 class="page__title">Favorites <span class="exp-badge">Experimental</span></h1>
			<p class="page__intro">Tools you've saved. Stored only in this browser — see
			<a href="/rules-of-engagement">Rules of Engagement</a>.</p>
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
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li></ul>
		</div>`,
	favorites_empty: `
		<div class="container page">
			<h1 class="page__title">Favorites <span class="exp-badge">Experimental</span></h1>
			<p class="page__intro">Tools you've saved. Stored only in this browser — see
			<a href="/rules-of-engagement">Rules of Engagement</a>.</p>
			<p class="empty">No favorites yet. Tap the <svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M12.744 6.793H18.5l.607 1.795-4.7 3.589 1.802 5.828-1.563 1.09L10 15.545l-4.646 3.55-1.563-1.09 1.8-5.828-4.698-3.59.607-1.794h5.756l1.789-5.788h1.91l1.79 5.788Z"/></svg><span class="skip-label">star</span> on any tool card or page to save it here.</p>
		</div>`,
	le_results: `<button class="le__result is-in" type="button" data-add="a" disabled="">
						<svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"></path></svg> <span dir="auto">A</span></button><button class="le__result" type="button" data-add="c">
						<svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.005 9H16v2h-4.995v5.005h-2V11H4V9h5.005V4.005h2z"></path></svg> <span dir="auto">C</span></button>`,
	le_rows: `
				<li data-tn="a"><span class="le__tn" dir="auto">a</span>
					<span class="le__rowact">
						<button class="btn btn--icon btn--sm" aria-label="Move up" type="button" disabled="" data-move="up"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m10 7 7.5 7.5-1.41 1.41L10 9.83l-6.09 6.08L2.5 14.5z"></path></svg></button>
						<button class="btn btn--icon btn--sm" aria-label="Move down" type="button" data-move="down"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 13 2.5 5.5 3.91 4.09 10 10.17l6.09-6.08L17.5 5.5z"></path></svg></button>
						<button class="btn btn--icon btn--danger btn--sm" aria-label="Remove from list" type="button" data-rm=""><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M16.707 4.707 11.414 10l5.293 5.293-1.414 1.414L10 11.414l-5.293 5.293-1.414-1.414L8.586 10 3.293 4.707l1.414-1.414L10 8.586l5.293-5.293z"></path></svg></button>
					</span></li>
				<li data-tn="b"><span class="le__tn" dir="auto">b</span>
					<span class="le__rowact">
						<button class="btn btn--icon btn--sm" aria-label="Move up" type="button" data-move="up"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m10 7 7.5 7.5-1.41 1.41L10 9.83l-6.09 6.08L2.5 14.5z"></path></svg></button>
						<button class="btn btn--icon btn--sm" aria-label="Move down" type="button" data-move="down"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 13 2.5 5.5 3.91 4.09 10 10.17l6.09-6.08L17.5 5.5z"></path></svg></button>
						<button class="btn btn--icon btn--danger btn--sm" aria-label="Remove from list" type="button" data-rm=""><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M16.707 4.707 11.414 10l5.293 5.293-1.414 1.414L10 11.414l-5.293 5.293-1.414-1.414L8.586 10 3.293 4.707l1.414-1.414L10 8.586l5.293-5.293z"></path></svg></button>
					</span></li>
				<li data-tn="c"><span class="le__tn" dir="auto">c</span>
					<span class="le__rowact">
						<button class="btn btn--icon btn--sm" aria-label="Move up" type="button" data-move="up"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m10 7 7.5 7.5-1.41 1.41L10 9.83l-6.09 6.08L2.5 14.5z"></path></svg></button>
						<button class="btn btn--icon btn--sm" aria-label="Move down" type="button" disabled="" data-move="down"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 13 2.5 5.5 3.91 4.09 10 10.17l6.09-6.08L17.5 5.5z"></path></svg></button>
						<button class="btn btn--icon btn--danger btn--sm" aria-label="Remove from list" type="button" data-rm=""><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M16.707 4.707 11.414 10l5.293 5.293-1.414 1.414L10 11.414l-5.293 5.293-1.414-1.414L8.586 10 3.293 4.707l1.414-1.414L10 8.586l5.293-5.293z"></path></svg></button>
					</span></li>`,
	mylists: `
	<div class="container page">
		<div class="section-head"><h1 class="page__title">Your lists <span class="exp-badge">Experimental</span></h1>
			<a class="btn btn--primary btn--md" href="/lists/create"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.005 9H16v2h-4.995v5.005h-2V11H4V9h5.005V4.005h2z"/></svg> Create a list</a></div>
		<p class="page__intro">Lists you've built in this demo. Stored only in this browser — see
		<a href="/rules-of-engagement">Rules of Engagement</a>.</p>
		<ul class="card-grid grid-lists" role="list"><li>
	<a class="lcard" href="/lists/demo-1" aria-label="Mine list, 2 tools">
		<span class="avatar " style="background:var(--wmf-red-aaa)" aria-hidden="true">M</span>
		<div class="lcard__body">
			<div class="lcard__title" dir="auto">Mine <span class="lcard__count">2 tools</span> <span class="exp-badge">Demo</span></div>
			<div class="lcard__desc" dir="auto">d</div>
		</div>
	</a></li></ul>
	</div>`,
	mylists_empty: `
	<div class="container page">
		<div class="section-head"><h1 class="page__title">Your lists <span class="exp-badge">Experimental</span></h1>
			<a class="btn btn--primary btn--md" href="/lists/create"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.005 9H16v2h-4.995v5.005h-2V11H4V9h5.005V4.005h2z"/></svg> Create a list</a></div>
		<p class="page__intro">Lists you've built in this demo. Stored only in this browser — see
		<a href="/rules-of-engagement">Rules of Engagement</a>.</p>
		<p class="empty">No lists yet. <a href="/lists/create">Create your first list</a>.</p>
	</div>`,
	overview_empty: `
	<div class="container page">
		<div class="section-head"><h1 class="page__title">Curated lists</h1>
			</div>
		<p class="page__intro">Community-published collections of tools for specific tasks and communities.</p>
		<p class="empty">No lists found.</p>
	</div>`,
	overview_in: `
	<div class="container page">
		<div class="section-head"><h1 class="page__title">Curated lists</h1>
			<a class="btn btn--primary btn--md" href="/lists/create"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.005 9H16v2h-4.995v5.005h-2V11H4V9h5.005V4.005h2z"/></svg> Create a list</a></div>
		<p class="page__intro">Community-published collections of tools for specific tasks and communities.</p>
		<ul class="card-grid grid-lists" role="list"><li>
	<a class="lcard" href="/lists/demo-1" aria-label="My Demo list, 1 tool">
		<span class="avatar " style="background:var(--wmf-red-aaa)" aria-hidden="true">M</span>
		<div class="lcard__body">
			<div class="lcard__title" dir="auto">My Demo <span class="lcard__count">1 tool</span> <span class="exp-badge">Demo</span></div>
			<div class="lcard__desc" dir="auto">mine</div>
		</div>
	</a></li><li>
	<a class="lcard" href="/lists/L1" aria-label="Curated One list, 2 tools">
		<span class="avatar " style="background:var(--wmf-purple)" aria-hidden="true">C</span>
		<div class="lcard__body">
			<div class="lcard__title" dir="auto">Curated One <span class="lcard__count">2 tools</span></div>
			<div class="lcard__desc" dir="auto">First list</div>
		</div>
	</a></li></ul>
	</div>`,
	overview_out: `
	<div class="container page">
		<div class="section-head"><h1 class="page__title">Curated lists</h1>
			</div>
		<p class="page__intro">Community-published collections of tools for specific tasks and communities.</p>
		<ul class="card-grid grid-lists" role="list"><li>
	<a class="lcard" href="/lists/L1" aria-label="Curated One list, 2 tools">
		<span class="avatar " style="background:var(--wmf-purple)" aria-hidden="true">C</span>
		<div class="lcard__body">
			<div class="lcard__title" dir="auto">Curated One <span class="lcard__count">2 tools</span></div>
			<div class="lcard__desc" dir="auto">First list</div>
		</div>
	</a></li></ul>
	</div>`
};

function expect(name, actual) {
	if (BAKE) {
		fs.writeFileSync(`${SCRATCH}/lists__${name}.txt`, actual);
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
		...o
	};
}
// Already-normalized Tool (for getToolsByName results).
function tool(name, o = {}) {
	return {
		name,
		title: o.title ?? name,
		description: o.description ?? "",
		keywords: o.keywords ?? [],
		maintainer: o.maintainer ?? "Unknown",
		forWikis: o.forWikis ?? [],
		toolType: o.toolType ?? null,
		deprecated: o.deprecated ?? false,
		experimental: o.experimental ?? false,
		modified: o.modified ?? "2026-01-01T00:00:00Z",
		weeklyViews: 0,
		...o
	};
}

beforeEach(() => {
	localStorage.clear();
	applyExp(false);
	document.body.innerHTML = "";
	for (const fn of Object.values(h)) fn.mockReset();
	h.paginate.mockResolvedValue([]);
	h.demoLists.mockReturnValue([]);
	h.favNames.mockReturnValue([]);
	h.isDemoListId.mockReturnValue(false);
});

const RAW_LIST = {
	id: "L1",
	title: "Curated One",
	description: "First list",
	featured: true,
	tools: [rawTool("alpha", { title: "Alpha" }), rawTool("bravo", { title: "Bravo" })]
};

/* ---------------- viewLists ---------------- */

test("viewLists signed out: live lists only", async () => {
	h.apiGet.mockResolvedValue({ results: [RAW_LIST] });
	const r = await lists.viewLists();
	assert.equal(r.title, "Curated lists — Toolhub");
	expect("overview_out", r.html);
});

test("viewLists signed in: create button + demo lists first", async () => {
	applyExp(true);
	h.apiGet.mockResolvedValue({ results: [RAW_LIST] });
	h.demoLists.mockReturnValue([{ id: "demo-1", title: "My Demo", description: "mine", tools: [{ name: "x" }] }]);
	const r = await lists.viewLists();
	expect("overview_in", r.html);
});

test("viewLists empty", async () => {
	h.apiGet.mockResolvedValue({ results: [] });
	const r = await lists.viewLists();
	expect("overview_empty", r.html);
});

test("viewLists apiGet rejects → catch fallback empty", async () => {
	h.apiGet.mockRejectedValue(new Error("down"));
	const r = await lists.viewLists();
	assert.equal(r.html, S.overview_empty);
});

/* ---------------- viewList ---------------- */

test("viewList demo, signed in: tag + edit button + tools", async () => {
	applyExp(true);
	h.isDemoListId.mockReturnValue(true);
	h.demoListGet.mockReturnValue({
		id: "demo-1",
		title: "Demo List",
		description: "demo desc",
		tools: ["alpha", "bravo"]
	});
	h.getToolsByName.mockResolvedValue([tool("alpha", { title: "Alpha" }), tool("bravo", { title: "Bravo" })]);
	const r = await lists.viewList("demo-1");
	assert.equal(r.title, "Demo List — Toolhub");
	expect("detail_demo", r.html);
});

test("viewList demo, signed out: no edit button", async () => {
	h.isDemoListId.mockReturnValue(true);
	h.demoListGet.mockReturnValue({ id: "demo-1", title: "Demo List", description: "demo desc", tools: ["alpha"] });
	h.getToolsByName.mockResolvedValue([tool("alpha", { title: "Alpha" })]);
	const r = await lists.viewList("demo-1");
	expect("detail_demo_out", r.html);
});

test("viewList demo not found → viewNotFound", async () => {
	h.isDemoListId.mockReturnValue(true);
	h.demoListGet.mockReturnValue(null);
	const r = await lists.viewList("nope");
	assert.deepEqual(r, viewNotFound());
});

test("viewList demo empty tools", async () => {
	h.isDemoListId.mockReturnValue(true);
	h.demoListGet.mockReturnValue({ id: "demo-1", title: "Empty Demo", description: "", tools: [] });
	h.getToolsByName.mockResolvedValue([]);
	const r = await lists.viewList("demo-1");
	expect("detail_demo_emptytools", r.html);
});

test("viewList live (normalizeList)", async () => {
	h.isDemoListId.mockReturnValue(false);
	h.apiGet.mockResolvedValue(RAW_LIST);
	const r = await lists.viewList("L1");
	expect("detail_live", r.html);
});

test("viewList live 404 → viewNotFound", async () => {
	h.isDemoListId.mockReturnValue(false);
	h.apiGet.mockRejectedValue(new ApiError(404, "/api/lists/L1/"));
	const r = await lists.viewList("L1");
	assert.deepEqual(r, viewNotFound());
});

test("viewList live outage (non-404) propagates instead of faking not-found", async () => {
	h.isDemoListId.mockReturnValue(false);
	h.apiGet.mockRejectedValue(new ApiError(503, "/api/lists/L1/"));
	await assert.rejects(() => lists.viewList("L1"), /API 503 /);
});

/* ---------------- viewMyLists ---------------- */

test("viewMyLists populated", async () => {
	h.demoLists.mockReturnValue([
		{ id: "demo-1", title: "Mine", description: "d", tools: [{ name: "a" }, { name: "b" }] }
	]);
	const r = await lists.viewMyLists();
	assert.equal(r.title, "Your lists — Toolhub");
	expect("mylists", r.html);
});

test("viewMyLists empty", async () => {
	h.demoLists.mockReturnValue([]);
	const r = await lists.viewMyLists();
	expect("mylists_empty", r.html);
});

/* ---------------- viewFavorites ---------------- */

test("viewFavorites populated", async () => {
	h.favNames.mockReturnValue(["alpha"]);
	h.getToolsByName.mockResolvedValue([tool("alpha", { title: "Alpha" })]);
	const r = await lists.viewFavorites();
	assert.equal(r.title, "Favorites — Toolhub");
	expect("favorites", r.html);
});

test("viewFavorites empty", async () => {
	h.favNames.mockReturnValue([]);
	h.getToolsByName.mockResolvedValue([]);
	const r = await lists.viewFavorites();
	expect("favorites_empty", r.html);
});

/* ---------------- viewListEdit (render) ---------------- */

test("viewListEdit create", async () => {
	h.demoListNew.mockReturnValue({ id: "new-1", title: "", description: "", tools: [] });
	const r = lists.viewListEdit(null);
	assert.equal(r.title, "Create a list — Toolhub");
	expect("edit_create", r.html);
});

test("viewListEdit editing", async () => {
	h.demoListGet.mockReturnValue({ id: "demo-1", title: "Edit Me", description: "desc", tools: ["alpha", "bravo"] });
	const r = lists.viewListEdit("demo-1");
	assert.equal(r.title, "Edit list — Toolhub");
	expect("edit_edit", r.html);
});

test("viewListEdit missing source → viewNotFound", async () => {
	h.demoListGet.mockReturnValue(null);
	const r = lists.viewListEdit("gone");
	assert.deepEqual(r, viewNotFound());
});

/* ---------------- viewListEdit mount ---------------- */

function mountEdit(id, src) {
	if (id === null) h.demoListNew.mockReturnValue(src);
	else h.demoListGet.mockReturnValue(src);
	const r = lists.viewListEdit(id);
	document.body.innerHTML = r.html;
	r.mount();
	return r;
}

const tick = () => new Promise((res) => setTimeout(res, 0));

test("mount edit: renders tool rows with count and move-button disabled states", () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: ["alpha", "bravo", "charlie"] });
	const count = document.querySelector("[data-le-count]");
	assert.equal(count.textContent, "3 tools");
	const rows = document.querySelectorAll("[data-le-tools] [data-tn]");
	assert.equal(rows.length, 3);
	// first row: move-up disabled; last row: move-down disabled
	assert.ok(rows[0].querySelector('[data-move="up"]').hasAttribute("disabled"));
	assert.ok(!rows[0].querySelector('[data-move="down"]').hasAttribute("disabled"));
	assert.ok(rows[2].querySelector('[data-move="down"]').hasAttribute("disabled"));
});

test("mount edit: empty tool list shows placeholder", () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: [] });
	assert.ok(document.querySelector("[data-le-tools]").innerHTML.includes("No tools yet — search below to add some."));
});

test("mount edit: move down then up reorders", () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: ["a", "b"] });
	const tools = document.querySelector("[data-le-tools]");
	tools.querySelector('[data-tn="a"] [data-move="down"]').dispatchEvent(new MouseEvent("click", { bubbles: true }));
	let order = [...tools.querySelectorAll("[data-tn]")].map((li) => li.getAttribute("data-tn"));
	assert.deepEqual(order, ["b", "a"]);
	tools.querySelector('[data-tn="a"] [data-move="up"]').dispatchEvent(new MouseEvent("click", { bubbles: true }));
	order = [...tools.querySelectorAll("[data-tn]")].map((li) => li.getAttribute("data-tn"));
	assert.deepEqual(order, ["a", "b"]);
});

test("mount edit: remove deletes a tool", () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: ["a", "b"] });
	const tools = document.querySelector("[data-le-tools]");
	tools.querySelector('[data-tn="a"] [data-rm]').dispatchEvent(new MouseEvent("click", { bubbles: true }));
	const order = [...tools.querySelectorAll("[data-tn]")].map((li) => li.getAttribute("data-tn"));
	assert.deepEqual(order, ["b"]);
	assert.equal(document.querySelector("[data-le-count]").textContent, "1 tool");
});

test("mount edit: clicking a no-op move at the boundary does nothing", () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: ["a", "b"] });
	const tools = document.querySelector("[data-le-tools]");
	// move up on first row (i===0) → guarded no-op
	tools.querySelector('[data-tn="a"] [data-move="up"]').dispatchEvent(new MouseEvent("click", { bubbles: true }));
	const order = [...tools.querySelectorAll("[data-tn]")].map((li) => li.getAttribute("data-tn"));
	assert.deepEqual(order, ["a", "b"]);
});

test("mount edit: search renders results and add appends a tool", async () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: ["a"] });
	h.apiGet.mockResolvedValue({ results: [rawTool("a", { title: "A" }), rawTool("c", { title: "C" })] });
	document.querySelector("#le-q").value = "x";
	document.querySelector("[data-le-search]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	await tick();
	const results = document.querySelector("[data-le-results]");
	// "a" already in list → disabled result; "c" addable
	assert.ok(results.querySelector('[data-add="a"]').hasAttribute("disabled"));
	const addC = results.querySelector('[data-add="c"]');
	assert.ok(!addC.hasAttribute("disabled"));
	addC.dispatchEvent(new MouseEvent("click", { bubbles: true }));
	const order = [...document.querySelectorAll("[data-le-tools] [data-tn]")].map((li) => li.getAttribute("data-tn"));
	assert.deepEqual(order, ["a", "c"]);
	assert.ok(addC.hasAttribute("disabled"), "added button becomes disabled");
});

test("mount edit: empty search query is ignored", async () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: [] });
	document.querySelector("#le-q").value = "   ";
	document.querySelector("[data-le-search]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	await tick();
	assert.equal(document.querySelector("[data-le-results]").innerHTML, "");
});

test("mount edit: search with no matches (response {} → exercises `data.results || []`)", async () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: [] });
	h.apiGet.mockResolvedValue({});
	document.querySelector("#le-q").value = "zz";
	document.querySelector("[data-le-search]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	await tick();
	assert.ok(document.querySelector("[data-le-results]").innerHTML.includes("No matches."));
});

test("mount edit: search failure shows error", async () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: [] });
	h.apiGet.mockRejectedValue(new Error("boom"));
	document.querySelector("#le-q").value = "zz";
	document.querySelector("[data-le-search]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	await tick();
	assert.ok(document.querySelector("[data-le-results]").innerHTML.includes("Search failed."));
});

test("mount edit: Enter in search triggers search", async () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: [] });
	h.apiGet.mockResolvedValue({ results: [rawTool("c", { title: "C" })] });
	const q = document.querySelector("#le-q");
	q.value = "c";
	q.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
	await tick();
	assert.ok(document.querySelector("[data-le-results]").querySelector('[data-add="c"]'));
});

test("mount edit: non-Enter key does not search", async () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: [] });
	document.querySelector("#le-q").value = "c";
	document.querySelector("#le-q").dispatchEvent(new KeyboardEvent("keydown", { key: "a", bubbles: true }));
	await tick();
	assert.equal(h.apiGet.mock.calls.length, 0);
});

test("mount edit: submit with title saves and navigates", () => {
	mountEdit("demo-1", { id: "demo-1", title: "Orig", description: "", tools: ["a"] });
	document.querySelector("#le-title").value = "New Title";
	document.querySelector("#le-desc").value = "New Desc";
	document.querySelector("[data-le-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(h.demoListSave.mock.calls.length, 1);
	assert.deepEqual(h.demoListSave.mock.calls[0][0], {
		id: "demo-1",
		title: "New Title",
		description: "New Desc",
		tools: ["a"]
	});
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/lists/demo-1"]);
});

test("mount edit: submit with empty title focuses title and does not save", () => {
	mountEdit("demo-1", { id: "demo-1", title: "", description: "", tools: [] });
	document.querySelector("#le-title").value = "   ";
	document.querySelector("[data-le-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(h.demoListSave.mock.calls.length, 0);
	assert.equal(document.activeElement, document.querySelector("#le-title"));
});

test("mount edit: delete button removes the list and navigates", () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: [] });
	document.querySelector("[data-le-delete]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	assert.deepEqual(h.demoListDelete.mock.calls[0], ["demo-1"]);
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/my-lists"]);
});

test("mount create: no delete button", () => {
	mountEdit(null, { id: "new-1", title: "", description: "", tools: [] });
	assert.equal(document.querySelector("[data-le-delete]"), null);
});

/* ---- additional coverage: params, defaults, exact mount HTML ---- */

test("viewLists requests /lists/ with page_size 30", async () => {
	h.apiGet.mockResolvedValue({ results: [] });
	await lists.viewLists();
	assert.deepEqual(h.apiGet.mock.calls[0], ["/lists/", { page_size: "30" }]);
});

test("viewLists {} response → empty (exercises data.results || [])", async () => {
	h.apiGet.mockResolvedValue({});
	const r = await lists.viewLists();
	assert.equal(r.html, S.overview_empty);
});

test("viewList live requests the encoded list path", async () => {
	h.isDemoListId.mockReturnValue(false);
	h.apiGet.mockResolvedValue(RAW_LIST);
	await lists.viewList("a b");
	assert.deepEqual(h.apiGet.mock.calls[0], ["/lists/a%20b/"]);
});

test("viewList demo with falsy title falls back to Untitled list", async () => {
	h.isDemoListId.mockReturnValue(true);
	h.demoListGet.mockReturnValue({ id: "demo-1", title: "", description: "", tools: [] });
	h.getToolsByName.mockResolvedValue([]);
	const r = await lists.viewList("demo-1");
	assert.ok(r.html.includes(">Untitled list "), "untitled fallback rendered");
	assert.equal(r.title, "Untitled list — Toolhub");
});

test("viewListEdit(undefined) behaves as create (editing is false)", async () => {
	h.demoListNew.mockReturnValue({ id: "new-1", title: "", description: "", tools: [] });
	const r = lists.viewListEdit(undefined);
	assert.equal(r.title, "Create a list — Toolhub");
	assert.equal(h.demoListGet.mock.calls.length, 0, "demoListGet not consulted for create");
});

test("mount edit: tool rows render exact markup (icon buttons, disabled boundaries)", () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: ["a", "b", "c"] });
	expect("le_rows", document.querySelector("[data-le-tools]").innerHTML);
});

test("mount edit: search results render exact markup (in-list vs addable)", async () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: ["a"] });
	h.apiGet.mockResolvedValue({ results: [rawTool("a", { title: "A" }), rawTool("c", { title: "C" })] });
	document.querySelector("#le-q").value = "x";
	document.querySelector("[data-le-search]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	await tick();
	expect("le_results", document.querySelector("[data-le-results]").innerHTML);
});

test("mount edit: requests /search/tools/ with q + page_size 8", async () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: [] });
	h.apiGet.mockResolvedValue({ results: [] });
	document.querySelector("#le-q").value = "maps";
	document.querySelector("[data-le-search]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	await tick();
	assert.deepEqual(h.apiGet.mock.calls.at(-1), ["/search/tools/", { q: "maps", page_size: "8" }]);
});

test("mount edit: shows the Searching… placeholder synchronously", () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: [] });
	h.apiGet.mockReturnValue(new Promise(() => {})); // never resolves
	document.querySelector("#le-q").value = "maps";
	document.querySelector("[data-le-search]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	assert.equal(document.querySelector("[data-le-results]").innerHTML, '<p class="le__searching">Searching…</p>');
});

test("mount edit: added result button gets the check icon", async () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: [] });
	h.apiGet.mockResolvedValue({ results: [rawTool("c", { title: "C" })] });
	document.querySelector("#le-q").value = "c";
	document.querySelector("[data-le-search]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	await tick();
	const addC = document.querySelector('[data-add="c"]');
	addC.dispatchEvent(new MouseEvent("click", { bubbles: true }));
	// the "add" icon is swapped for the "check" icon (check path begins with M18.154)
	assert.ok(addC.querySelector(".icon path").getAttribute("d").startsWith("M18.154"), "check icon present");
	assert.ok(addC.classList.contains("is-in"));
});

test("mount edit: clicking a non-action spot in the first row is a no-op (no reorder, no re-render)", () => {
	mountEdit("demo-1", { id: "demo-1", title: "T", description: "", tools: ["a", "b"] });
	const tools = document.querySelector("[data-le-tools]");
	const firstRow = tools.querySelector('[data-tn="a"]');
	// click the tool-name span on the FIRST row: up||down is false → early return.
	// A `true` mutant would splice it down ([b,a]); dropping the early return would
	// re-render (replacing firstRow), so we also assert the original node survives.
	firstRow.querySelector(".le__tn").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	const order = [...tools.querySelectorAll("[data-tn]")].map((li) => li.getAttribute("data-tn"));
	assert.deepEqual(order, ["a", "b"]);
	assert.equal(firstRow.isConnected, true, "list was not re-rendered for a no-op click");
});
