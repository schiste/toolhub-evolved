// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import fs from "node:fs";
import { test, vi, beforeEach } from "vitest";

const SCRATCH =
	"/private/tmp/claude-501/-Users-christophehenner-Downloads-Wikimedia-striker-toolhub-demo/bad07c6e-1967-4490-8d44-3fe4ee515e59/scratchpad";
const BAKE = process.env.BAKE === "1";

const h = vi.hoisted(() => ({
	apiGet: vi.fn(),
	getTool: vi.fn(),
	getToolsByName: vi.fn(),
	paginate: vi.fn(),
	navigateTo: vi.fn()
}));

vi.mock("../../public_html/lib/core/api.js", async (orig) => {
	const actual = await orig();
	return { ...actual, apiGet: h.apiGet, getTool: h.getTool, getToolsByName: h.getToolsByName, paginate: h.paginate };
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
const { setUserContext } = await import("../../public_html/lib/core/signals.js");
const home = await import("../../public_html/views/home.js");

// --- expected snapshots (baked from un-mutated output) ---
const S = {
	empty: `
	<section class="hero">
		<h1 class="hero__title">The community catalog of Wikimedia tools</h1>
		<div class="hero__explore">
			<form class="intent" data-intent-form data-axis="audiences" data-term="" data-wiki="">
				<div class="intent__sentence" aria-label="Build a tool search">
					<span class="intent__copy">I want to see tools</span>
					<span class="intent__choice" data-intent-choice="axis">
		<button class="intent__word" type="button" data-intent-trigger="axis" aria-haspopup="menu" aria-expanded="false"><span data-intent-label="axis">made for</span></button>
		<span class="intent__menu" data-intent-menu="axis" role="menu" hidden><button class="intent__option is-active" type="button" role="menuitemradio" aria-checked="true" data-intent-option="axis" data-value="audiences">made for</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="axis" data-value="tasks">to</button></span>
	</span>
					<span class="intent__choice" data-intent-choice="term">
		<button class="intent__word" type="button" data-intent-trigger="term" aria-haspopup="menu" aria-expanded="false"><span data-intent-label="term">anyone</span></button>
		<span class="intent__menu" data-intent-menu="term" role="menu" hidden><button class="intent__option is-active" type="button" role="menuitemradio" aria-checked="true" data-intent-option="term" data-value="">anyone</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="editor">editors</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="developer">developers</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="reader">readers</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="researcher">researchers</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="admin">admins</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="organizer">organizers</button></span>
	</span>
					<span class="intent__copy">on</span>
					<span class="intent__choice" data-intent-choice="wiki">
		<button class="intent__word" type="button" data-intent-trigger="wiki" aria-haspopup="menu" aria-expanded="false"><span data-intent-label="wiki">any project</span></button>
		<span class="intent__menu" data-intent-menu="wiki" role="menu" hidden><button class="intent__option is-active" type="button" role="menuitemradio" aria-checked="true" data-intent-option="wiki" data-value="">any project</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="wikidata.org">Wikidata</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="commons.wikimedia.org">Commons</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="en.wikipedia.org">English Wikipedia</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="*.wikipedia.org">Any Wikipedia</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="*.wikisource.org">Any Wikisource</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="meta.wikimedia.org">Meta-Wiki</button></span>
	</span>
					<button class="intent__go" type="submit">See tools</button>
					<button class="intent__clear" type="button" data-intent-clear disabled>clear</button>
				</div>
			</form>
		</div>
		<div class="hero__or" aria-hidden="true">or</div>
		<form class="search" role="search" data-home-search>
			<label for="home-q" class="skip-label">Search tools</label>
			<input id="home-q" class="search__input" type="search" aria-label="Search tools" placeholder="Search 0 tools…" autocomplete="off" />
			<button class="btn btn--primary btn--md search__btn" type="submit">Search</button>
		</form>
	</section>
	<div class="container layout">
		<div class="layout__main home-results" data-home-main aria-live="polite">
			
		<div class="section-head"><h2>Featured tools</h2><a class="link" href="/lists">View all</a></div>
		<p class="empty">No tools match this sentence.</p>
		<div class="section-head"><h2>Most listed</h2><a class="link" href="/lists">View lists</a></div>
		<p class="empty">No listed tools match this sentence.</p>
		<div class="section-head"><h2>Curated lists</h2><a class="link" href="/lists">View all lists</a></div>
		<p class="empty">No curated lists match this sentence.</p>
		</div>
		<aside class="layout__side">
			<div class="panel"><h3 class="panel__title">Recently updated</h3><ul class="recent" data-home-recent aria-live="polite"><li class="recent__empty">No recently updated tools match this sentence.</li></ul></div>
			<div class="panel panel--cta"><div class="cta__icon" aria-hidden="true"><svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M13 20H7v-2h6zM10 0c1.938 0 3.58.556 4.745 1.644C15.918 2.738 16.5 4.27 16.5 6c0 2.22-1.15 3.732-2.04 4.727-.644.72-.96 1.633-.96 2.662V16h-7v-2.611c0-1.029-.317-1.942-.96-2.662C4.65 9.732 3.5 8.22 3.5 6c0-1.627.593-3.145 1.743-4.255C6.395.634 8.032 0 10 0"/></svg></div><h3>Built a tool for Wikimedia?</h3><p>Add a <code>toolinfo.json</code> to your repository, or register it here, so other Wikimedians can find it.</p><a class="btn btn--outline btn--md" href="https://toolhub.wikimedia.org/add-or-remove-tools?tab=tool-create" target="_blank" rel="noopener nofollow">Submit a tool</a></div>
		</aside>
	</div>`,
	filtered: `
	<section class="hero">
		<h1 class="hero__title">The community catalog of Wikimedia tools</h1>
		<div class="hero__explore">
			<form class="intent" data-intent-form data-axis="audiences" data-term="editor" data-wiki="wikidata.org">
				<div class="intent__sentence" aria-label="Build a tool search">
					<span class="intent__copy">I want to see tools</span>
					<span class="intent__choice" data-intent-choice="axis">
		<button class="intent__word" type="button" data-intent-trigger="axis" aria-haspopup="menu" aria-expanded="false"><span data-intent-label="axis">made for</span></button>
		<span class="intent__menu" data-intent-menu="axis" role="menu" hidden><button class="intent__option is-active" type="button" role="menuitemradio" aria-checked="true" data-intent-option="axis" data-value="audiences">made for</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="axis" data-value="tasks">to</button></span>
	</span>
					<span class="intent__choice" data-intent-choice="term">
		<button class="intent__word" type="button" data-intent-trigger="term" aria-haspopup="menu" aria-expanded="false"><span data-intent-label="term">editors</span></button>
		<span class="intent__menu" data-intent-menu="term" role="menu" hidden><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="">anyone</button><button class="intent__option is-active" type="button" role="menuitemradio" aria-checked="true" data-intent-option="term" data-value="editor">editors</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="developer">developers</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="reader">readers</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="researcher">researchers</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="admin">admins</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="organizer">organizers</button></span>
	</span>
					<span class="intent__copy">on</span>
					<span class="intent__choice" data-intent-choice="wiki">
		<button class="intent__word" type="button" data-intent-trigger="wiki" aria-haspopup="menu" aria-expanded="false"><span data-intent-label="wiki">Wikidata</span></button>
		<span class="intent__menu" data-intent-menu="wiki" role="menu" hidden><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="">any project</button><button class="intent__option is-active" type="button" role="menuitemradio" aria-checked="true" data-intent-option="wiki" data-value="wikidata.org">Wikidata</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="commons.wikimedia.org">Commons</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="en.wikipedia.org">English Wikipedia</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="*.wikipedia.org">Any Wikipedia</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="*.wikisource.org">Any Wikisource</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="meta.wikimedia.org">Meta-Wiki</button></span>
	</span>
					<button class="intent__go" type="submit">See tools</button>
					<button class="intent__clear" type="button" data-intent-clear>clear</button>
				</div>
			</form>
		</div>
		<div class="hero__or" aria-hidden="true">or</div>
		<form class="search" role="search" data-home-search>
			<label for="home-q" class="skip-label">Search tools</label>
			<input id="home-q" class="search__input" type="search" aria-label="Search tools" placeholder="Search 99 tools…" autocomplete="off" />
			<button class="btn btn--primary btn--md search__btn" type="submit">Search</button>
		</form>
	</section>
	<div class="container layout">
		<div class="layout__main home-results" data-home-main aria-live="polite">
			
		<div class="section-head"><h2>Featured tools</h2><a class="link" href="/search?audiences__term=editor&wiki__term=wikidata.org">View all</a></div>
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
		<div class="tcard__signals"><span class="signal" title="Appears in 1 curated list"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 16H1v-2h2zm16 0H5v-2h14zM3 11H1V9h2zm16 0H5V9h14zM3 6H1V4h2zm16 0H5V4h14z"/></svg> In 1 list</span><span class="signal" title="Listing 1 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:11%"></span></span>1/9</span><span class="signal signal--fit"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg> Fits you</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">wikidata.org</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
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
		<div class="tcard__signals"><span class="signal" title="Appears in 3 curated lists"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 16H1v-2h2zm16 0H5v-2h14zM3 11H1V9h2zm16 0H5V9h14zM3 6H1V4h2zm16 0H5V4h14z"/></svg> In 3 lists</span><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li><li>
	<article class="tcard" data-tool="charlie">
		
		<div class="tcard__head">
			<span class="avatar " style="background:var(--wmf-purple)" aria-hidden="true">C</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="charlie" aria-label="Quick look: Charlie" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Charlie</button>
				<div class="tcard__maint">by <span dir="auto">Unknown</span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Appears in 2 curated lists"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 16H1v-2h2zm16 0H5v-2h14zM3 11H1V9h2zm16 0H5V9h14zM3 6H1V4h2zm16 0H5V4h14z"/></svg> In 2 lists</span><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li></ul>
		<div class="section-head"><h2>Most listed</h2><a class="link" href="/search?audiences__term=editor&wiki__term=wikidata.org">View all</a></div>
		<ul class="card-grid grid-tools" role="list"><li>
	<article class="tcard" data-tool="alpha">
		
		<div class="tcard__head">
			<span class="rankbadge" aria-hidden="true">1</span><span class="avatar " style="background:var(--color-progressive)" aria-hidden="true">A</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="alpha" aria-label="Quick look: Alpha" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Alpha</button>
				<div class="tcard__maint">by <span dir="auto">Unknown</span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Appears in 1 curated list"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 16H1v-2h2zm16 0H5v-2h14zM3 11H1V9h2zm16 0H5V9h14zM3 6H1V4h2zm16 0H5V4h14z"/></svg> In 1 list</span><span class="signal" title="Listing 1 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:11%"></span></span>1/9</span><span class="signal signal--fit"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg> Fits you</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">wikidata.org</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li><li>
	<article class="tcard" data-tool="bravo">
		
		<div class="tcard__head">
			<span class="rankbadge" aria-hidden="true">2</span><span class="avatar " style="background:var(--color-progressive)" aria-hidden="true">B</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="bravo" aria-label="Quick look: Bravo" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Bravo</button>
				<div class="tcard__maint">by <span dir="auto">Unknown</span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Appears in 3 curated lists"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 16H1v-2h2zm16 0H5v-2h14zM3 11H1V9h2zm16 0H5V9h14zM3 6H1V4h2zm16 0H5V4h14z"/></svg> In 3 lists</span><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li><li>
	<article class="tcard" data-tool="charlie">
		
		<div class="tcard__head">
			<span class="rankbadge" aria-hidden="true">3</span><span class="avatar " style="background:var(--wmf-purple)" aria-hidden="true">C</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="charlie" aria-label="Quick look: Charlie" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Charlie</button>
				<div class="tcard__maint">by <span dir="auto">Unknown</span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Appears in 2 curated lists"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 16H1v-2h2zm16 0H5v-2h14zM3 11H1V9h2zm16 0H5V9h14zM3 6H1V4h2zm16 0H5V4h14z"/></svg> In 2 lists</span><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li></ul>
		<div class="section-head"><h2>Curated lists</h2><a class="link" href="/lists">View all lists</a></div>
		<ul class="card-grid grid-lists" role="list"><li>
	<a class="lcard" href="/lists/L1" aria-label="List One list, 3 tools">
		<span class="avatar " style="background:var(--wmf-blue-aaa)" aria-hidden="true">L</span>
		<div class="lcard__body">
			<div class="lcard__title" dir="auto">List One <span class="lcard__count">3 tools</span></div>
			<div class="lcard__desc" dir="auto">desc one</div>
		</div>
	</a></li><li>
	<a class="lcard" href="/lists/L2" aria-label="Intent Match list, 1 tool">
		<span class="avatar " style="background:var(--wmf-red-aaa)" aria-hidden="true">I</span>
		<div class="lcard__body">
			<div class="lcard__title" dir="auto">Intent Match <span class="lcard__count">1 tool</span></div>
			<div class="lcard__desc" dir="auto">kept via intent</div>
		</div>
	</a></li><li>
	<a class="lcard" href="/lists/L5" aria-label="Mixed list, 2 tools">
		<span class="avatar " style="background:var(--wmf-red-aaa)" aria-hidden="true">M</span>
		<div class="lcard__body">
			<div class="lcard__title" dir="auto">Mixed <span class="lcard__count">2 tools</span></div>
			<div class="lcard__desc" dir="auto">one matches one not</div>
		</div>
	</a></li><li>
	<a class="lcard" href="/lists/L6" aria-label="Bravo only list, 1 tool">
		<span class="avatar " style="background:var(--color-progressive)" aria-hidden="true">B</span>
		<div class="lcard__body">
			<div class="lcard__title" dir="auto">Bravo only <span class="lcard__count">1 tool</span></div>
			<div class="lcard__desc" dir="auto">by name</div>
		</div>
	</a></li></ul>
		</div>
		<aside class="layout__side">
			<div class="panel"><h3 class="panel__title">Recently updated</h3><ul class="recent" data-home-recent aria-live="polite">
		<li><a href="/tools/alpha"><span class="avatar " style="background:var(--color-progressive)" aria-hidden="true">A</span>
			<div><div class="recent__title" dir="auto">Alpha</div>
			<div class="recent__meta">Maintainer: <span dir="auto">Unknown</span></div></div>
			<u|2026-01-01T00:00:00Z|recent__when></a></li>
		<li><a href="/tools/bravo"><span class="avatar " style="background:var(--color-progressive)" aria-hidden="true">B</span>
			<div><div class="recent__title" dir="auto">Bravo</div>
			<div class="recent__meta">Maintainer: <span dir="auto">Unknown</span></div></div>
			<u|2026-01-01T00:00:00Z|recent__when></a></li>
		<li><a href="/tools/charlie"><span class="avatar " style="background:var(--wmf-purple)" aria-hidden="true">C</span>
			<div><div class="recent__title" dir="auto">Charlie</div>
			<div class="recent__meta">Maintainer: <span dir="auto">Unknown</span></div></div>
			<u|2026-01-01T00:00:00Z|recent__when></a></li></ul></div>
			<div class="panel panel--cta"><div class="cta__icon" aria-hidden="true"><svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M13 20H7v-2h6zM10 0c1.938 0 3.58.556 4.745 1.644C15.918 2.738 16.5 4.27 16.5 6c0 2.22-1.15 3.732-2.04 4.727-.644.72-.96 1.633-.96 2.662V16h-7v-2.611c0-1.029-.317-1.942-.96-2.662C4.65 9.732 3.5 8.22 3.5 6c0-1.627.593-3.145 1.743-4.255C6.395.634 8.032 0 10 0"/></svg></div><h3>Built a tool for Wikimedia?</h3><p>Add a <code>toolinfo.json</code> to your repository, or register it here, so other Wikimedians can find it.</p><a class="btn btn--outline btn--md" href="https://toolhub.wikimedia.org/add-or-remove-tools?tab=tool-create" target="_blank" rel="noopener nofollow">Submit a tool</a></div>
		</aside>
	</div>`,
	unfiltered: `
	<section class="hero">
		<h1 class="hero__title">The community catalog of Wikimedia tools</h1>
		<div class="hero__explore">
			<form class="intent" data-intent-form data-axis="audiences" data-term="" data-wiki="">
				<div class="intent__sentence" aria-label="Build a tool search">
					<span class="intent__copy">I want to see tools</span>
					<span class="intent__choice" data-intent-choice="axis">
		<button class="intent__word" type="button" data-intent-trigger="axis" aria-haspopup="menu" aria-expanded="false"><span data-intent-label="axis">made for</span></button>
		<span class="intent__menu" data-intent-menu="axis" role="menu" hidden><button class="intent__option is-active" type="button" role="menuitemradio" aria-checked="true" data-intent-option="axis" data-value="audiences">made for</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="axis" data-value="tasks">to</button></span>
	</span>
					<span class="intent__choice" data-intent-choice="term">
		<button class="intent__word" type="button" data-intent-trigger="term" aria-haspopup="menu" aria-expanded="false"><span data-intent-label="term">anyone</span></button>
		<span class="intent__menu" data-intent-menu="term" role="menu" hidden><button class="intent__option is-active" type="button" role="menuitemradio" aria-checked="true" data-intent-option="term" data-value="">anyone</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="editor">editors</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="developer">developers</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="reader">readers</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="researcher">researchers</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="admin">admins</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="term" data-value="organizer">organizers</button></span>
	</span>
					<span class="intent__copy">on</span>
					<span class="intent__choice" data-intent-choice="wiki">
		<button class="intent__word" type="button" data-intent-trigger="wiki" aria-haspopup="menu" aria-expanded="false"><span data-intent-label="wiki">any project</span></button>
		<span class="intent__menu" data-intent-menu="wiki" role="menu" hidden><button class="intent__option is-active" type="button" role="menuitemradio" aria-checked="true" data-intent-option="wiki" data-value="">any project</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="wikidata.org">Wikidata</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="commons.wikimedia.org">Commons</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="en.wikipedia.org">English Wikipedia</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="*.wikipedia.org">Any Wikipedia</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="*.wikisource.org">Any Wikisource</button><button class="intent__option" type="button" role="menuitemradio" aria-checked="false" data-intent-option="wiki" data-value="meta.wikimedia.org">Meta-Wiki</button></span>
	</span>
					<button class="intent__go" type="submit">See tools</button>
					<button class="intent__clear" type="button" data-intent-clear disabled>clear</button>
				</div>
			</form>
		</div>
		<div class="hero__or" aria-hidden="true">or</div>
		<form class="search" role="search" data-home-search>
			<label for="home-q" class="skip-label">Search tools</label>
			<input id="home-q" class="search__input" type="search" aria-label="Search tools" placeholder="Search 2,474 tools…" autocomplete="off" />
			<button class="btn btn--primary btn--md search__btn" type="submit">Search</button>
		</form>
	</section>
	<div class="container layout">
		<div class="layout__main home-results" data-home-main aria-live="polite">
			
		<div class="section-head"><h2>Featured tools</h2><a class="link" href="/lists/L1">View all</a></div>
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
		<div class="tcard__signals"><span class="signal" title="Appears in 1 curated list"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 16H1v-2h2zm16 0H5v-2h14zM3 11H1V9h2zm16 0H5V9h14zM3 6H1V4h2zm16 0H5V4h14z"/></svg> In 1 list</span><span class="signal" title="Listing 1 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:11%"></span></span>1/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">wikidata.org</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
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
		<div class="tcard__signals"><span class="signal" title="Appears in 3 curated lists"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 16H1v-2h2zm16 0H5v-2h14zM3 11H1V9h2zm16 0H5V9h14zM3 6H1V4h2zm16 0H5V4h14z"/></svg> In 3 lists</span><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li><li>
	<article class="tcard" data-tool="charlie">
		
		<div class="tcard__head">
			<span class="avatar " style="background:var(--wmf-purple)" aria-hidden="true">C</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="charlie" aria-label="Quick look: Charlie" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Charlie</button>
				<div class="tcard__maint">by <span dir="auto">Unknown</span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Appears in 2 curated lists"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 16H1v-2h2zm16 0H5v-2h14zM3 11H1V9h2zm16 0H5V9h14zM3 6H1V4h2zm16 0H5V4h14z"/></svg> In 2 lists</span><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li></ul>
		<div class="section-head"><h2>Most listed</h2><a class="link" href="/lists">View lists</a></div>
		<ul class="card-grid grid-tools" role="list"><li>
	<article class="tcard" data-tool="bravo">
		
		<div class="tcard__head">
			<span class="rankbadge" aria-hidden="true">1</span><span class="avatar " style="background:var(--color-progressive)" aria-hidden="true">B</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="bravo" aria-label="Quick look: Bravo" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Bravo</button>
				<div class="tcard__maint">by <span dir="auto">Unknown</span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Appears in 3 curated lists"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 16H1v-2h2zm16 0H5v-2h14zM3 11H1V9h2zm16 0H5V9h14zM3 6H1V4h2zm16 0H5V4h14z"/></svg> In 3 lists</span><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li><li>
	<article class="tcard" data-tool="charlie">
		
		<div class="tcard__head">
			<span class="rankbadge" aria-hidden="true">2</span><span class="avatar " style="background:var(--wmf-purple)" aria-hidden="true">C</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="charlie" aria-label="Quick look: Charlie" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Charlie</button>
				<div class="tcard__maint">by <span dir="auto">Unknown</span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Appears in 2 curated lists"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 16H1v-2h2zm16 0H5v-2h14zM3 11H1V9h2zm16 0H5V9h14zM3 6H1V4h2zm16 0H5V4h14z"/></svg> In 2 lists</span><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li><li>
	<article class="tcard" data-tool="alpha">
		
		<div class="tcard__head">
			<span class="rankbadge" aria-hidden="true">3</span><span class="avatar " style="background:var(--color-progressive)" aria-hidden="true">A</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="alpha" aria-label="Quick look: Alpha" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Alpha</button>
				<div class="tcard__maint">by <span dir="auto">Unknown</span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Appears in 1 curated list"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 16H1v-2h2zm16 0H5v-2h14zM3 11H1V9h2zm16 0H5V9h14zM3 6H1V4h2zm16 0H5V4h14z"/></svg> In 1 list</span><span class="signal" title="Listing 1 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:11%"></span></span>1/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">wikidata.org</span><span class="tcard__footr"><u|2026-01-01T00:00:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li></ul>
		<div class="section-head"><h2>Curated lists</h2><a class="link" href="/lists">View all lists</a></div>
		<ul class="card-grid grid-lists" role="list"><li>
	<a class="lcard" href="/lists/L1" aria-label="List One list, 3 tools">
		<span class="avatar " style="background:var(--wmf-blue-aaa)" aria-hidden="true">L</span>
		<div class="lcard__body">
			<div class="lcard__title" dir="auto">List One <span class="lcard__count">3 tools</span></div>
			<div class="lcard__desc" dir="auto">desc one</div>
		</div>
	</a></li></ul>
		</div>
		<aside class="layout__side">
			<div class="panel"><h3 class="panel__title">Recently updated</h3><ul class="recent" data-home-recent aria-live="polite">
		<li><a href="/tools/alpha"><span class="avatar " style="background:var(--color-progressive)" aria-hidden="true">A</span>
			<div><div class="recent__title" dir="auto">Alpha</div>
			<div class="recent__meta">Maintainer: <span dir="auto">Unknown</span></div></div>
			<u|2026-02-02T00:00:00Z|recent__when></a></li></ul></div>
			<div class="panel panel--cta"><div class="cta__icon" aria-hidden="true"><svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M13 20H7v-2h6zM10 0c1.938 0 3.58.556 4.745 1.644C15.918 2.738 16.5 4.27 16.5 6c0 2.22-1.15 3.732-2.04 4.727-.644.72-.96 1.633-.96 2.662V16h-7v-2.611c0-1.029-.317-1.942-.96-2.662C4.65 9.732 3.5 8.22 3.5 6c0-1.627.593-3.145 1.743-4.255C6.395.634 8.032 0 10 0"/></svg></div><h3>Built a tool for Wikimedia?</h3><p>Add a <code>toolinfo.json</code> to your repository, or register it here, so other Wikimedians can find it.</p><a class="btn btn--outline btn--md" href="https://toolhub.wikimedia.org/add-or-remove-tools?tab=tool-create" target="_blank" rel="noopener nofollow">Submit a tool</a></div>
		</aside>
	</div>`
};

function expect(name, actual) {
	if (BAKE) {
		fs.writeFileSync(`${SCRATCH}/home__${name}.txt`, actual);
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
		audiences: o.audiences ?? [],
		tasks: o.tasks ?? [],
		for_wikis: o.for_wikis ?? [],
		modified_date: o.modified_date ?? "2026-01-01T00:00:00Z",
		author: o.author,
		...o
	};
}

// Membership map (shared/memoized across tests via listMemberships): distinct
// endorsement counts bravo=3, charlie=2, alpha=1 so the sort order is observable.
const MEMBERSHIP_LISTS = [
	{ id: "m1", title: "M1", tools: [{ name: "alpha" }, { name: "bravo" }, { name: "charlie" }] },
	{ id: "m2", title: "M2", tools: [{ name: "bravo" }, { name: "charlie" }] },
	{ id: "m3", title: "M3", tools: [{ name: "bravo" }] }
];

beforeEach(() => {
	localStorage.clear();
	applyExp(false);
	document.body.innerHTML = "";
	h.apiGet.mockReset();
	h.paginate.mockReset();
	h.navigateTo.mockReset();
	h.paginate.mockImplementation(async (path) => (path === "/lists/" ? MEMBERSHIP_LISTS : []));
});

const LIST_ALPHA = {
	id: "L1",
	title: "List One",
	description: "desc one",
	featured: true,
	tools: [
		rawTool("alpha", { title: "Alpha", for_wikis: ["wikidata.org"], audiences: ["editor"] }),
		rawTool("bravo", { title: "Bravo" }),
		rawTool("charlie", { title: "Charlie" })
	]
};

test("home unfiltered: lists + tools populated", async () => {
	h.apiGet.mockImplementation(async (path) => {
		if (path === "/ui/home/") return { total_tools: 2474 };
		if (path === "/lists/") return { results: [LIST_ALPHA] };
		if (path === "/search/tools/") {
			return { results: [rawTool("alpha", { title: "Alpha", modified_date: "2026-02-02T00:00:00Z" })] };
		}
		return {};
	});
	const r = await home.viewHome();
	assert.equal(r.title, "Toolhub — discover Wikimedia tools");
	expect("unfiltered", r.html);
});

test("home unfiltered: first list lacks id → featured href /lists", async () => {
	h.apiGet.mockImplementation(async (path) => {
		if (path === "/ui/home/") return { total_tools: 5 };
		if (path === "/lists/") return { results: [{ ...LIST_ALPHA, id: "" }] };
		if (path === "/search/tools/") return { results: [] };
		return {};
	});
	const r = await home.viewHome();
	// lists[0] exists but its id is falsy → featured "View all" falls back to /lists.
	assert.ok(
		r.html.includes(
			'<div class="section-head"><h2>Featured tools</h2><a class="link" href="/lists">View all</a></div>'
		),
		"falsy list id falls back to /lists"
	);
});

test("home empty: nothing matches (responses lack a results key → exercises `.results || []`)", async () => {
	// Every response is `{}` (no results key) so the `X.results || []` fallbacks fire.
	h.apiGet.mockImplementation(async () => ({}));
	const r = await home.viewHome();
	expect("empty", r.html);
});

test("home filtered: context set (role + wiki)", async () => {
	setUserContext({ role: "editor", wiki: "wikidata.org" });
	h.apiGet.mockImplementation(async (path, params) => {
		if (path === "/ui/home/") return { total_tools: 99 };
		if (path === "/lists/") {
			// One list keeps a tool by name match, one only via toolMatchesIntent, one dropped.
			return {
				results: [
					LIST_ALPHA,
					{
						id: "L2",
						title: "Intent Match",
						description: "kept via intent",
						tools: [rawTool("zulu", { title: "Zulu", audiences: ["editor"], for_wikis: ["wikidata.org"] })]
					},
					// dropped: tool fails the audiences/term check (toolMatchesIntent line 117)
					{
						id: "L3",
						title: "Dropped",
						description: "no match",
						tools: [rawTool("nope", { title: "Nope" })]
					},
					// dropped: tool passes term but fails wikiMatches (toolMatchesIntent line 119)
					{
						id: "L4",
						title: "Wrong wiki",
						description: "term ok wiki wrong",
						tools: [
							rawTool("wrongwiki", {
								title: "WrongWiki",
								audiences: ["editor"],
								for_wikis: ["commons.wikimedia.org"]
							})
						]
					},
					// kept via .some (one tool matches, one does not) → distinguishes some/every
					{
						id: "L5",
						title: "Mixed",
						description: "one matches one not",
						tools: [
							rawTool("alpha", { title: "Alpha", audiences: ["editor"], for_wikis: ["wikidata.org"] }),
							rawTool("misc", { title: "Misc" })
						]
					},
					// kept ONLY via matchingNames (bravo is in the filtered results but does
					// not itself match the intent) → distinguishes the featured.map(t=>t.name).
					{
						id: "L6",
						title: "Bravo only",
						description: "by name",
						tools: [rawTool("bravo", { title: "Bravo" })]
					}
				]
			};
		}
		if (path === "/search/tools/") {
			if (params && String(params.ordering || "") === "-modified_date") {
				return { results: [rawTool("alpha", { title: "Alpha", modified_date: "2026-03-03T00:00:00Z" })] };
			}
			return {
				results: [
					rawTool("alpha", { title: "Alpha", audiences: ["editor"], for_wikis: ["wikidata.org"] }),
					rawTool("bravo", { title: "Bravo" }),
					rawTool("charlie", { title: "Charlie" })
				]
			};
		}
		return {};
	});
	const r = await home.viewHome();
	expect("filtered", r.html);
});

/* ---------------- mount() behaviours ---------------- */

async function mountHome(opts = {}) {
	h.apiGet.mockImplementation(async (path, params) => {
		if (path === "/ui/home/") return { total_tools: 10 };
		if (path === "/lists/") return { results: [LIST_ALPHA] };
		if (path === "/search/tools/") {
			if (params && String(params.ordering || "") === "-modified_date") {
				return { results: [rawTool("alpha", { title: "Alpha" })] };
			}
			return { results: opts.filteredResults || [rawTool("alpha", { title: "Alpha" })] };
		}
		return {};
	});
	const r = await home.viewHome();
	document.body.innerHTML = r.html;
	r.mount();
	return r;
}

const tick = () => new Promise((res) => setTimeout(res, 0));

test("mount: home search submit navigates with query", async () => {
	await mountHome();
	const input = document.querySelector("#home-q");
	input.value = "  maps  ";
	document.querySelector("[data-home-search]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/search?q=maps"]);
});

test("mount: home search submit empty query navigates to /search", async () => {
	await mountHome();
	document.querySelector("#home-q").value = "   ";
	document.querySelector("[data-home-search]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/search"]);
});

test("mount: intent trigger toggles menu open/closed", async () => {
	await mountHome();
	const form = document.querySelector("[data-intent-form]");
	const menu = form.querySelector('[data-intent-menu="axis"]');
	const trigger = form.querySelector('[data-intent-trigger="axis"]');
	assert.equal(menu.hidden, true);
	trigger.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
	assert.equal(menu.hidden, false);
	assert.equal(trigger.getAttribute("aria-expanded"), "true");
	trigger.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
	assert.equal(menu.hidden, true);
	assert.equal(trigger.getAttribute("aria-expanded"), "false");
});

test("mount: selecting axis=tasks resets term, syncs labels, refreshes", async () => {
	await mountHome();
	const form = document.querySelector("[data-intent-form]");
	const axisOpt = form.querySelector('[data-intent-option="axis"][data-value="tasks"]');
	axisOpt.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
	await tick();
	await tick();
	assert.equal(form.querySelector('[data-intent-label="axis"]').textContent, "to");
	// term reset to "do anything" (tasks any label)
	assert.equal(form.querySelector('[data-intent-label="term"]').textContent, "do anything");
	// clear button now enabled (axis changed implies term="" but wiki=""): term empty, wiki empty → still disabled
	const clear = form.querySelector("[data-intent-clear]");
	assert.equal(clear.disabled, true);
});

test("mount: selecting a term enables clear and refreshes main", async () => {
	await mountHome({ filteredResults: [rawTool("delta", { title: "Delta" })] });
	const form = document.querySelector("[data-intent-form]");
	const termOpt = form.querySelector('[data-intent-option="term"][data-value="editor"]');
	termOpt.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
	await tick();
	await tick();
	assert.equal(form.querySelector('[data-intent-label="term"]').textContent, "editors");
	assert.equal(form.querySelector("[data-intent-clear]").disabled, false);
	const main = document.querySelector("[data-home-main]");
	assert.equal(main.hasAttribute("aria-busy"), false);
	assert.ok(main.innerHTML.includes("Delta"), "refreshed main shows filtered tool");
});

test("mount: selecting wiki updates label", async () => {
	await mountHome();
	const form = document.querySelector("[data-intent-form]");
	const wikiOpt = form.querySelector('[data-intent-option="wiki"][data-value="commons.wikimedia.org"]');
	wikiOpt.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
	await tick();
	await tick();
	assert.equal(form.querySelector('[data-intent-label="wiki"]').textContent, "Commons");
});

test("mount: clear button resets state and disables itself", async () => {
	await mountHome();
	const form = document.querySelector("[data-intent-form]");
	form.querySelector('[data-intent-option="term"][data-value="editor"]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	await tick();
	const clear = form.querySelector("[data-intent-clear]");
	assert.equal(clear.disabled, false);
	clear.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
	await tick();
	await tick();
	assert.equal(form.querySelector('[data-intent-label="term"]').textContent, "anyone");
	assert.equal(clear.disabled, true);
});

test("mount: outside click closes open menu", async () => {
	await mountHome();
	const form = document.querySelector("[data-intent-form]");
	const menu = form.querySelector('[data-intent-menu="axis"]');
	form.querySelector('[data-intent-trigger="axis"]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	assert.equal(menu.hidden, false);
	document.body.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
	assert.equal(menu.hidden, true);
});

test("mount: Escape key closes open menu", async () => {
	await mountHome();
	const form = document.querySelector("[data-intent-form]");
	const menu = form.querySelector('[data-intent-menu="wiki"]');
	form.querySelector('[data-intent-trigger="wiki"]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	assert.equal(menu.hidden, false);
	document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
	assert.equal(menu.hidden, true);
	// non-Escape key leaves it (reopen then press other key)
	form.querySelector('[data-intent-trigger="wiki"]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	document.dispatchEvent(new KeyboardEvent("keydown", { key: "a" }));
	assert.equal(menu.hidden, false);
});

test("mount: intent form submit persists context and navigates", async () => {
	await mountHome();
	const form = document.querySelector("[data-intent-form]");
	form.querySelector('[data-intent-option="term"][data-value="editor"]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	await tick();
	form.querySelector('[data-intent-option="wiki"][data-value="wikidata.org"]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	await tick();
	form.dispatchEvent(new Event("submit", { cancelable: true }));
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/search?audiences__term=editor&wiki__term=wikidata.org"]);
	assert.equal(localStorage.getItem("toolhub-context"), JSON.stringify({ wiki: "wikidata.org", role: "editor" }));
});

test("mount: refresh error path renders error messages", async () => {
	await mountHome();
	const main = document.querySelector("[data-home-main]");
	const recent = document.querySelector("[data-home-recent]");
	// Make the next refresh throw inside homeSectionsModel: a null /lists/ result
	// is not caught by the per-call `.catch` and makes `.results` access throw.
	h.apiGet.mockResolvedValue(null);
	document
		.querySelector('[data-intent-option="term"][data-value="editor"]')
		.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
	await tick();
	await tick();
	assert.equal(main.innerHTML, '<p class="empty">Unable to refresh tools right now.</p>');
	assert.equal(recent.innerHTML, '<li class="recent__empty">Unable to refresh recently updated tools.</li>');
});

/* ---------------- params / coverage of construction & defensive paths ---------------- */

test("apiGet receives exact params (unfiltered)", async () => {
	const calls = [];
	h.apiGet.mockImplementation(async (path, params) => {
		calls.push([path, params]);
		if (path === "/ui/home/") return { total_tools: 1 };
		return { results: [] };
	});
	await home.viewHome();
	const lists = calls.find((c) => c[0] === "/lists/");
	assert.deepEqual(lists[1], { featured: "true", page_size: "6" });
	const recent = calls.find((c) => c[0] === "/search/tools/");
	assert.equal(String(recent[1]), "ordering=-modified_date&page_size=5");
	// unfiltered → no extra filtered tool fetch
	assert.equal(calls.filter((c) => c[0] === "/search/tools/").length, 1);
});

test("apiGet receives exact params (filtered)", async () => {
	setUserContext({ role: "editor", wiki: "wikidata.org" });
	const calls = [];
	h.apiGet.mockImplementation(async (path, params) => {
		calls.push([path, params && String(params) === "[object Object]" ? params : String(params)]);
		if (path === "/ui/home/") return { total_tools: 1 };
		return { results: [] };
	});
	await home.viewHome();
	const lists = calls.find((c) => c[0] === "/lists/");
	assert.deepEqual(lists[1], { featured: "true", page_size: "30" });
	const searches = new Set(calls.filter((c) => c[0] === "/search/tools/").map((c) => c[1]));
	assert.ok(searches.has("audiences__term=editor&wiki__term=wikidata.org&ordering=-modified_date&page_size=5"));
	assert.ok(searches.has("audiences__term=editor&wiki__term=wikidata.org&page_size=24"));
});

test("all sources resolve empty → the empty page renders (genuinely no data, not an outage)", async () => {
	h.apiGet.mockResolvedValue({ results: [] }); // /ui/home/ → total 0; /lists/ & recent → empty
	const r = await home.viewHome();
	assert.equal(r.html, S.empty);
});

test("total outage (every source rejects) surfaces an error, not an empty catalog", async () => {
	h.apiGet.mockRejectedValue(new Error("down"));
	// homeSectionsModel counts the failures and, with nothing loaded, rethrows so
	// the router shows the error page instead of "No tools match this sentence".
	await assert.rejects(() => home.viewHome(), /live catalog unavailable/);
});

test("partial outage but a list loaded → renders, no error (lists.length keeps it alive)", async () => {
	h.apiGet.mockImplementation(async (path) => {
		if (path === "/ui/home/") return { total_tools: 1 };
		// a tool-less list still counts as loaded content (lists.length > 0), so
		// even though recent fails and featured is empty, this is not a total outage.
		if (path === "/lists/") return { results: [{ id: "E1", title: "Loaded Listy", description: "d", tools: [] }] };
		throw new Error("recent down"); // failures = 1
	});
	const r = await home.viewHome();
	assert.ok(r.html.includes("Loaded Listy"), "the loaded list renders instead of the outage error");
});

test("partial outage but featured loaded → renders, no error (featured.length keeps it alive)", async () => {
	setUserContext({ role: "editor", wiki: "wikidata.org" });
	h.apiGet.mockImplementation(async (path, params) => {
		if (path === "/ui/home/") return { total_tools: 5 };
		if (path === "/lists/") return { results: [] }; // lists empty
		// recent fails (failures = 1); the filtered featured fetch returns content
		if (path === "/search/tools/" && String(params).includes("ordering=-modified_date")) {
			throw new Error("recent down");
		}
		return {
			results: [rawTool("feat1", { title: "Featured One", audiences: ["editor"], for_wikis: ["wikidata.org"] })]
		};
	});
	const r = await home.viewHome();
	assert.ok(r.html.includes("Featured One"), "loaded featured tools render instead of the outage error");
});

test("dedupeTools drops empty-name and duplicate tools (unfiltered featured)", async () => {
	h.apiGet.mockImplementation(async (path) => {
		if (path === "/ui/home/") return { total_tools: 3 };
		if (path === "/lists/") {
			return {
				results: [
					{
						id: "D1",
						title: "Dups",
						description: "d",
						tools: [
							rawTool("alpha", { title: "Alpha" }),
							rawTool("", { title: "Noname" }),
							rawTool("alpha", { title: "Alpha again" }),
							rawTool("bravo", { title: "Bravo" })
						]
					}
				]
			};
		}
		return { results: [] };
	});
	const r = await home.viewHome();
	const featuredGrid = r.html.split('<div class="section-head"><h2>Most listed</h2>')[0];
	const cards = featuredGrid.match(/<article class="tcard/g) || [];
	assert.equal(cards.length, 2, "alpha (once) + bravo only");
	assert.ok(featuredGrid.includes('data-tool="alpha"'));
	assert.ok(featuredGrid.includes('data-tool="bravo"'));
});

test("slice limits: featured/most-listed cap at 8, lists cap at 6", async () => {
	const tools = Array.from({ length: 9 }, (_, i) => rawTool(`t${i}`, { title: `Tool ${i}` }));
	const lists = Array.from({ length: 7 }, (_, i) => ({
		id: `g${i}`,
		title: `List ${i}`,
		description: "d",
		tools
	}));
	h.apiGet.mockImplementation(async (path) => {
		if (path === "/ui/home/") return { total_tools: 9 };
		if (path === "/lists/") return { results: lists };
		return { results: [] };
	});
	const r = await home.viewHome();
	const main = r.html.split('data-home-main aria-live="polite">')[1].split("</div>\n\t\t\t<aside")[0];
	const featuredGrid = main.split('<div class="section-head"><h2>Most listed</h2>')[0];
	const mostListed = main
		.split('<div class="section-head"><h2>Most listed</h2>')[1]
		.split('<div class="section-head"><h2>Curated lists</h2>')[0];
	const listGrid = main.split('<div class="section-head"><h2>Curated lists</h2>')[1];
	assert.equal((featuredGrid.match(/<article class="tcard/g) || []).length, 8);
	assert.equal((mostListed.match(/<article class="tcard/g) || []).length, 8);
	assert.equal((listGrid.match(/<a class="lcard"/g) || []).length, 6);
});

test("total_tools=1 renders singular placeholder", async () => {
	h.apiGet.mockImplementation(async (path) => {
		if (path === "/ui/home/") return { total_tools: 1 };
		return { results: [] };
	});
	const r = await home.viewHome();
	assert.ok(r.html.includes('placeholder="Search 1 tool…"'));
});

test("ui/home reject → total 0 placeholder (covers /ui/home/ catch arrow)", async () => {
	h.apiGet.mockImplementation(async (path) => {
		if (path === "/ui/home/") throw new Error("nope");
		return { results: [] };
	});
	const r = await home.viewHome();
	assert.ok(r.html.includes('placeholder="Search 0 tools…"'));
});

test("mount: submit with no filters navigates to bare /search", async () => {
	await mountHome();
	document.querySelector("[data-intent-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/search"]);
});

test("mount: tasks axis + task term → tasks__term submit and refreshed list filtering", async () => {
	// refresh after selecting axis=tasks/term=editing filters lists by tasks.
	h.apiGet.mockImplementation(async (path, params) => {
		if (path === "/ui/home/") return { total_tools: 10 };
		if (path === "/lists/") {
			return {
				results: [
					{
						id: "K1",
						title: "Editing kept",
						description: "kept by tasks",
						tools: [rawTool("edittool", { title: "Edit Tool", tasks: ["editing"] })]
					},
					{
						id: "K2",
						title: "Reading dropped",
						description: "no editing",
						tools: [rawTool("readtool", { title: "Read Tool", tasks: ["reading"] })]
					},
					// kept only by the tasks branch: matches via tasks but NOT via audiences,
					// so it distinguishes `state.axis === "tasks" ? t.tasks : t.audiences`.
					{
						id: "K3",
						title: "Tasks not audiences",
						description: "kept by tasks only",
						tools: [rawTool("tasktool", { title: "Task Tool", tasks: ["editing"], audiences: [] })]
					}
				]
			};
		}
		if (path === "/search/tools/") {
			if (params && String(params.ordering || "") === "-modified_date") return { results: [] };
			return { results: [rawTool("edittool", { title: "Edit Tool", tasks: ["editing"] })] };
		}
		return {};
	});
	const r = await home.viewHome();
	document.body.innerHTML = r.html;
	r.mount();
	const form = document.querySelector("[data-intent-form]");
	form.querySelector('[data-intent-option="axis"][data-value="tasks"]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	await tick();
	// syncIntent rebuilt the term menu with tasks options; labels are lower-cased
	// (kills toLowerCase) and carry data-intent-option="term" (kills the kind arg).
	const termMenu = form.querySelector('[data-intent-menu="term"]');
	assert.ok(termMenu.innerHTML.includes('data-intent-option="term" data-value="editing">edit content</button>'));
	assert.ok(
		form
			.querySelector('[data-intent-menu="axis"]')
			.innerHTML.includes('data-intent-option="axis" data-value="tasks">to</button>')
	);
	assert.ok(
		form
			.querySelector('[data-intent-menu="wiki"]')
			.innerHTML.includes('data-intent-option="wiki" data-value="wikidata.org">Wikidata</button>')
	);
	form.querySelector('[data-intent-option="term"][data-value="editing"]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	await tick();
	await tick();
	// persistIntent computes role = axis==="audiences" ? term : "". With axis=tasks
	// role is "" and wiki is "", so setUserContext clears the key (→ null). The
	// 363 mutant (true ? term) / ("" → "Stryker") would instead store role="editing".
	assert.equal(localStorage.getItem("toolhub-context"), null);
	form.dispatchEvent(new Event("submit", { cancelable: true }));
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/search?tasks__term=editing"]);
	const main = document.querySelector("[data-home-main]");
	assert.ok(main.innerHTML.includes("Editing kept"), "list kept via toolMatchesIntent tasks branch");
	assert.ok(main.innerHTML.includes("Tasks not audiences"), "kept via tasks even though audiences differ");
	assert.ok(!main.innerHTML.includes("Reading dropped"), "list dropped: tasks do not include editing");
});

test("mount: initial filtered context preserves term + wiki on submit", async () => {
	setUserContext({ role: "editor", wiki: "wikidata.org" });
	await mountHome();
	// data-term/data-wiki are non-empty here, so the `&&` mutants of state init would blank them.
	document.querySelector("[data-intent-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/search?audiences__term=editor&wiki__term=wikidata.org"]);
});

test("mount: clicking the 'anyone' (empty value) term option clears the term", async () => {
	await mountHome();
	const form = document.querySelector("[data-intent-form]");
	form.querySelector('[data-intent-option="term"][data-value="editor"]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	await tick();
	assert.equal(form.querySelector("[data-intent-clear]").disabled, false);
	// data-value="" → state.term becomes "" (kills `value || "..."`), disabling clear again.
	form.querySelector('[data-intent-option="term"][data-value=""]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	await tick();
	assert.equal(form.querySelector("[data-intent-clear]").disabled, true);
});

test("mount: clear resets axis to audiences (its option becomes active)", async () => {
	await mountHome();
	const form = document.querySelector("[data-intent-form]");
	form.querySelector('[data-intent-option="axis"][data-value="tasks"]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	await tick();
	// pick a task term so a filter is active and the clear control is enabled
	form.querySelector('[data-intent-option="term"][data-value="editing"]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	await tick();
	form.querySelector("[data-intent-clear]").dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	await tick();
	await tick();
	const axisMenu = form.querySelector('[data-intent-menu="axis"]');
	assert.ok(
		axisMenu.innerHTML.includes(
			'aria-checked="true" data-intent-option="axis" data-value="audiences">made for</button>'
		),
		"axis reset to audiences"
	);
});

test("mount: aria-busy is set during refresh and cleared after", async () => {
	await mountHome();
	const main = document.querySelector("[data-home-main]");
	const recent = document.querySelector("[data-home-recent]");
	// refreshHome sets aria-busy="true" synchronously before its first await, so it
	// is observable immediately after the click (before microtasks flush).
	document
		.querySelector('[data-intent-option="term"][data-value="editor"]')
		.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
	assert.equal(main.getAttribute("aria-busy"), "true");
	assert.equal(recent.getAttribute("aria-busy"), "true");
	await tick();
	await tick();
	assert.equal(main.hasAttribute("aria-busy"), false);
	assert.equal(recent.hasAttribute("aria-busy"), false);
});

test("mount: a stale refresh does not overwrite a newer one (seq guard)", async () => {
	await mountHome();
	const main = document.querySelector("[data-home-main]");
	const resolvers = [];
	h.apiGet.mockImplementation(
		(path, params) =>
			new Promise((res) => {
				if (path === "/ui/home/") return res({ total_tools: 1 });
				if (path === "/lists/") return res({ results: [] });
				// recent feed carries ordering=-modified_date; the filtered-tools fetch does not.
				if (path === "/search/tools/" && String(params).includes("ordering=-modified_date")) {
					return res({ results: [] });
				}
				resolvers.push((title) => res({ results: [rawTool(`t-${title}`, { title })] }));
			})
	);
	const form = document.querySelector("[data-intent-form]");
	// First refresh (stale) then second refresh (current); resolve current first, stale last.
	form.querySelector('[data-intent-option="term"][data-value="editor"]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	form.querySelector('[data-intent-option="term"][data-value="developer"]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	resolvers[1]("NEW");
	await tick();
	resolvers[0]("OLD");
	await tick();
	await tick();
	assert.ok(main.innerHTML.includes("NEW"), "current refresh rendered");
	assert.ok(!main.innerHTML.includes("OLD"), "stale refresh suppressed by seq guard");
});

test("mount: a stale failed refresh does not overwrite a newer success (catch seq guard)", async () => {
	await mountHome();
	const main = document.querySelector("[data-home-main]");
	const settlers = [];
	h.apiGet.mockImplementation(
		(path, params) =>
			new Promise((res, rej) => {
				if (path === "/ui/home/") return res({ total_tools: 1 });
				if (path === "/search/tools/" && params && String(params.ordering || "") === "-modified_date") {
					return res({ results: [] });
				}
				if (path === "/lists/") return settlers.push({ res, rej });
				res({ results: [] });
			})
	);
	const form = document.querySelector("[data-intent-form]");
	form.querySelector('[data-intent-option="term"][data-value="editor"]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	form.querySelector('[data-intent-option="term"][data-value="developer"]').dispatchEvent(
		new MouseEvent("click", { bubbles: true, cancelable: true })
	);
	// Resolve the current (2nd) refresh successfully, then make the stale (1st) one
	// throw inside homeSectionsModel (null /lists/ → `.results` access throws), which
	// drives refreshHome's catch. Its seq guard must suppress the stale error render.
	settlers[1].res({ results: [] });
	await tick();
	settlers[0].res(null);
	await tick();
	await tick();
	assert.ok(!main.innerHTML.includes("Unable to refresh tools right now."), "stale error suppressed");
});

test("home filtered by wiki only (empty term) keeps wiki-matching lists", async () => {
	setUserContext({ wiki: "wikidata.org", role: "" });
	h.apiGet.mockImplementation(async (path, params) => {
		if (path === "/ui/home/") return { total_tools: 4 };
		if (path === "/lists/") {
			return {
				results: [
					// kept via toolMatchesIntent wiki-match while state.term is "" (exercises `if (state.term)` false path)
					{
						id: "W1",
						title: "Wiki kept",
						description: "matches wiki",
						tools: [rawTool("wikitool", { title: "Wiki Tool", for_wikis: ["wikidata.org"] })]
					}
				]
			};
		}
		if (path === "/search/tools/") {
			if (String(params).includes("ordering=-modified_date")) return { results: [] };
			return { results: [rawTool("other", { title: "Other", for_wikis: ["commons.wikimedia.org"] })] };
		}
		return {};
	});
	const r = await home.viewHome();
	// W1 has no `other` so it is kept purely by the wiki branch of toolMatchesIntent.
	assert.ok(r.html.includes("Wiki kept"), "list kept via wiki match with empty term");
});

test("filtered tool fetch rejects but recent loads → empty featured, page still renders (partial)", async () => {
	setUserContext({ role: "editor", wiki: "wikidata.org" });
	h.apiGet.mockImplementation(async (path, params) => {
		if (path === "/ui/home/") return { total_tools: 1 };
		if (path === "/lists/") return { results: [] };
		// recent succeeds with content, so this is a partial failure (not a total
		// outage): the featured fetch's onFail yields empty featured, but the page
		// still renders rather than throwing.
		if (path === "/search/tools/" && String(params).includes("ordering=-modified_date")) {
			return { results: [rawTool("recentish", { title: "Recentish" })] };
		}
		throw new Error("filtered tools down");
	});
	const r = await home.viewHome();
	assert.ok(r.html.includes('<p class="empty">No tools match this sentence.</p>'), "featured empty via onFail");
	assert.ok(r.html.includes("Recentish"), "recent section still rendered");
});

test("mount: filtered context with empty {} responses → empty page (filtered `.results || []`)", async () => {
	setUserContext({ role: "editor", wiki: "wikidata.org" });
	h.apiGet.mockImplementation(async () => ({}));
	const r = await home.viewHome();
	assert.ok(r.html.includes('<p class="empty">No tools match this sentence.</p>'), "filtered featured empty");
});
