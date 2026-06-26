// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import fs from "node:fs";
import { test, vi, beforeEach, afterEach } from "vitest";

const SCRATCH =
	"/private/tmp/claude-501/-Users-christophehenner-Downloads-Wikimedia-striker-toolhub-demo/bad07c6e-1967-4490-8d44-3fe4ee515e59/scratchpad";
const BAKE = process.env.BAKE === "1";

const h = vi.hoisted(() => ({ forceGraph: vi.fn() }));

vi.mock("../../public_html/lib/organisms/force-graph.js", async (orig) => {
	const actual = await orig();
	return { ...actual, forceGraph: h.forceGraph };
});
vi.mock("../../public_html/lib/core/i18n.js", async (orig) => {
	const actual = await orig();
	return {
		...actual,
		updatedTimeTag: (iso, cls) => `<u|${iso ?? ""}|${cls ?? ""}>`,
		timeTag: (iso, cls, text) => `<t|${iso ?? ""}|${cls ?? ""}|${text ?? ""}>`
	};
});

const sg = await import("../../public_html/views/styleguide.js");

const S = {
	page: `
		<div class="container page sg-page">
			<h1 class="page__title">Design system</h1>
			<p class="page__intro">A living reference for Toolhub tokens and component functions, rendered from the same modules used by the application.</p>
			<section class="sg-section" aria-labelledby="sg-tokens">
		<h2 class="sg-section__title" id="sg-tokens">Tokens</h2>
		
		<div class="sg-token-block">
			<h3 class="sg-token-block__title">Semantic colors</h3>
			<div class="sg-token-grid sg-token-grid--colors" id="sg-color-tokens" aria-live="polite"></div>
		</div>
		<div class="sg-token-block">
			<h3 class="sg-token-block__title">Raw Wikimedia palette</h3>
			<div class="sg-token-grid sg-token-grid--colors" id="sg-wmf-tokens" aria-live="polite"></div>
		</div>
		<div class="sg-token-block">
			<h3 class="sg-token-block__title">Type scale</h3>
			<div class="sg-token-stack" id="sg-type-tokens" aria-live="polite"></div>
		</div>
		<div class="sg-token-split">
			<div class="sg-token-block">
				<h3 class="sg-token-block__title">Radii</h3>
				<div class="sg-token-grid" id="sg-radius-tokens" aria-live="polite"></div>
			</div>
			<div class="sg-token-block">
				<h3 class="sg-token-block__title">Shadows</h3>
				<div class="sg-token-grid" id="sg-shadow-tokens" aria-live="polite"></div>
			</div>
		</div>
		<div class="sg-token-block">
			<h3 class="sg-token-block__title">Spacing</h3>
			<div class="sg-token-stack" id="sg-space-tokens" aria-live="polite"></div>
		</div>
		<div class="sg-token-block">
			<h3 class="sg-token-block__title">Layout</h3>
			<div class="sg-token-stack" id="sg-layout-tokens" aria-live="polite"></div>
		</div>
	</section>
			<section class="sg-section" aria-labelledby="sg-chrome">
		<h2 class="sg-section__title" id="sg-chrome">Chrome</h2>
		
		<div class="sg-examples sg-examples--organisms">
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="sg-chrome-frame">
		<header class="nav">
			<div class="nav__inner">
				<a class="brand" href="/">
					<img class="brand__logo" src="img/toolhub-logo.svg?v=2" alt="" width="34" height="34" />
					<span class="brand__name">Toolhub</span>
				</a>
				<nav class="nav__links" aria-label="Primary">
					<a href="/search">Tools</a>
					<a href="/lists">Lists</a>
					<a href="/graph">Map</a>
					<a href="/recent">Recent</a>
				</nav>
				<div class="nav__actions">
					<a class="icon-btn" href="/search"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg> Search</a>
					<a class="btn btn--primary btn--md" href="https://toolhub.wikimedia.org/add-or-remove-tools?tab=tool-create" target="_blank" rel="noopener nofollow"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.005 9H16v2h-4.995v5.005h-2V11H4V9h5.005V4.005h2z"/></svg> Submit a tool</a>
					<div class="acct">
		<button class="acct__btn" id="sg-acct-btn" type="button" aria-haspopup="true" aria-expanded="false" aria-controls="sg-acct-menu">
			<span class="avatar avatar--sm" style="background:var(--wmf-blue-aaa)" aria-hidden="true">A</span>
			<span class="acct__name">Amina Hassan</span>
			<svg class="icon acct__caret" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 13 2.5 5.5 3.91 4.09 10 10.17l6.09-6.08L17.5 5.5z"/></svg>
		</button>
	</div>
				</div>
			</div>
		</header>
	</div></div>
		<figcaption class="sg-example__caption"><code>Nav + brand</code><span>app chrome</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="sg-chrome-frame">
		<footer class="footer">
			<div class="footer__cols">
				<nav class="footer__col" aria-label="Discover">
					<h2>Discover</h2>
					<a href="/search">Browse tools</a>
					<a href="/lists">Lists</a>
					<a href="/members">Members</a>
					<a href="/recent">Recent changes</a>
				</nav>
				<nav class="footer__col" aria-label="Maintain">
					<h2>Maintain</h2>
					<a href="/add-or-remove-tools">Add or remove tools</a>
					<a href="/my-lists">Your lists</a>
					<a href="/favorites">Favorites</a>
					<a href="/contribute">Help maintain Toolhub</a>
				</nav>
				<nav class="footer__col" aria-label="Project">
					<h2>Project</h2>
					<a href="/api-docs">API docs</a>
					<a href="/styleguide">Design system</a>
					<a href="https://phabricator.wikimedia.org/tag/toolhub/" target="_blank" rel="noopener nofollow">Report an issue <svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg></a>
				</nav>
				<nav class="footer__col" aria-label="About">
					<h2>About</h2>
					<a href="/about">About Toolhub</a>
					<a href="/help">Help</a>
					<a href="/privacy">Privacy policy</a>
					<a href="/rules-of-engagement">Rules of Engagement</a>
				</nav>
			</div>
			<div class="footer__bottom">
				<a class="footer__maintain" href="/contribute"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 8.5a1.5 1.5 0 110 3 1.5 1.5 0 010-3"/><path d="M11.74 3.218a7 7 0 011.822.757l2.095-1.046 1.414 1.414-1.047 2.094c.334.562.591 1.174.757 1.823L19 9v2l-2.219.74a7 7 0 01-.757 1.822l1.047 2.095-1.414 1.414-2.095-1.047a7 7 0 01-1.823.757L11 19H9l-.74-2.219a7 7 0 01-1.823-.757l-2.094 1.047-1.414-1.414 1.046-2.095a7 7 0 01-.757-1.823L1 11V9l2.218-.74a7 7 0 01.757-1.823L2.929 4.343l1.414-1.414 2.094 1.046a7 7 0 011.823-.757L9 1h2zM10 5a5 5 0 100 10 5 5 0 000-10"/></svg> Help maintain Toolhub</a>
				<span class="footer__legal">Catalog content under <a href="https://creativecommons.org/publicdomain/zero/1.0/" target="_blank" rel="noopener nofollow">CC0</a> · <a href="https://github.com/schiste/toolhub-evolved" target="_blank" rel="noopener nofollow">Toolhub Evolved v0.1.0</a></span>
				<span class="footer__note">Prototype · live read-only data from the Toolhub API</span>
			</div>
		</footer>
	</div></div>
		<figcaption class="sg-example__caption"><code>Footer</code><span>app chrome</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide sg-example--compact">
		<div class="sg-example__demo"><div class="sg-chrome-frame sg-chrome-frame--tight">
		<div class="mockup-banner" role="region" aria-label="Prototype notice">
			<span class="mockup-banner__txt"><span aria-hidden="true">!</span> Mockup - a prototype, not a working integration with the real Toolhub. <span class="mock-tag">Demo</span></span>
			<a class="mockup-banner__link" href="/experiments">Experimental features</a>
			<a class="mockup-banner__link" href="/rules-of-engagement">Rules of Engagement</a>
		</div>
	</div></div>
		<figcaption class="sg-example__caption"><code>Mockup banner + mock tag</code><span>app chrome</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide sg-example--compact">
		<div class="sg-example__demo"><div class="sg-chrome-frame sg-chrome-frame--tight">
		<section class="expbar" aria-label="Experimental feature controls">
			<div class="container expbar__inner">
				<button class="exp-toggle" type="button" role="switch" aria-checked="false">
					<span class="exp-toggle__track"><span class="exp-toggle__thumb"></span></span>
					<span class="exp-toggle__label">Show me prospective features</span>
				</button>
			</div>
		</section>
	</div></div>
		<figcaption class="sg-example__caption"><code>Experiments bar</code><span>app chrome</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="sg-hero-frame">
		<section class="hero">
			<h1 class="hero__title">The community catalog of Wikimedia tools</h1>
			<div class="hero__explore">
				<form class="intent">
		<div class="intent__sentence" aria-label="Build a tool search">
			<span class="intent__copy">I want to see tools</span>
			<span class="intent__choice"><button class="intent__word" type="button" aria-haspopup="menu" aria-expanded="false"><span>made for</span></button></span>
			<span class="intent__choice"><button class="intent__word" type="button" aria-haspopup="menu" aria-expanded="false"><span>anyone</span></button></span>
			<span class="intent__copy">on</span>
			<span class="intent__choice"><button class="intent__word" type="button" aria-haspopup="menu" aria-expanded="false"><span>any project</span></button></span>
			<button class="intent__go" type="submit">See tools</button>
			<button class="intent__clear" type="button" disabled>clear</button>
		</div>
	</form>
			</div>
			<div class="hero__or" aria-hidden="true">or</div>
			<form class="search" role="search">
				<label for="sg-home-q" class="skip-label">Search tools</label>
				<input id="sg-home-q" class="search__input" type="search" aria-label="Search tools" placeholder="Search 2,474 tools..." autocomplete="off" />
				<button class="btn btn--primary btn--md search__btn" type="submit">Search</button>
			</form>
		</section>
	</div></div>
		<figcaption class="sg-example__caption"><code>Full hero block</code><span>app chrome / organism</span></figcaption>
	</figure>
		</div>
	</section>
			<section class="sg-section" aria-labelledby="sg-layout-&amp;-states">
		<h2 class="sg-section__title" id="sg-layout-&amp;-states">Layout &amp; states</h2>
		
		<div class="sg-examples sg-examples--organisms">
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="page sg-page-demo">
		<h1 class="page__title">Browse tools</h1>
		<p class="page__intro">Search, filter, and compare tools maintained by the Wikimedia community.</p>
		<div class="section-head"><h2>Featured tools</h2><a class="link" href="/search">View all</a></div>
	</div></div>
		<figcaption class="sg-example__caption"><code>Page header + section head</code><span>templates</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="layout sg-layout-demo">
		<div class="layout__main">
			<div class="section-head"><h2>Main content</h2><a class="link" href="/search">View all</a></div>
			<div class="sg-schematic">Cards, search results, or detail content</div>
		</div>
		<aside class="layout__side">
			<div class="panel"><h3 class="panel__title">Sidebar</h3><p class="sg-note">Panels and supporting navigation.</p></div>
		</aside>
	</div></div>
		<figcaption class="sg-example__caption"><code>Two-column layout</code><span>templates</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><div class="sg-control-stack">
		<a class="back" href="/search">← Back to tools</a>
		<a class="link" href="/lists">View all lists</a>
	</div></div>
		<figcaption class="sg-example__caption"><code>Back link + text link</code><span>templates</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><p class="empty">No tools match these filters.</p></div>
		<figcaption class="sg-example__caption"><code>Empty state</code><span>templates</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><div class="loading sg-loading-demo" role="status" aria-live="polite">
		<span class="spinner" aria-hidden="true"></span><span class="skip-label">Loading</span>
	</div></div>
		<figcaption class="sg-example__caption"><code>Loading spinner</code><span>templates</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="errorpage sg-error-demo">
		<h1>Couldn't load live data</h1>
		<p class="prose">The Toolhub API didn't respond. Try again from the browse page.</p>
		<a class="btn btn--primary btn--md" href="/">Go to the home page</a>
	</div></div>
		<figcaption class="sg-example__caption"><code>Error page</code><span>templates</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><article class="prose prose--page">
		<h1>About Toolhub</h1>
		<p>Toolhub helps Wikimedians discover software used across editing, maintenance, analysis, and community workflows.</p>
		<p><a href="/contribute">Help maintain Toolhub</a> by improving listings or reporting gaps.</p>
	</article></div>
		<figcaption class="sg-example__caption"><code>Prose page</code><span>templates</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><p class="signin-note">In this prototype these actions are read-only: they need an authenticated session and the live back-end.</p></div>
		<figcaption class="sg-example__caption"><code>Sign-in note</code><span>molecules</span></figcaption>
	</figure>
		</div>
	</section>
			<section class="sg-section" aria-labelledby="sg-buttons">
		<h2 class="sg-section__title" id="sg-buttons">Buttons</h2>
		
		<div class="sg-examples sg-examples--buttons">
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="btn btn--primary btn--md" type="button">Primary</button></div>
		<figcaption class="sg-example__caption"><code>button(&#39;Primary&#39;, { variant: &#39;primary&#39; })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="btn btn--outline btn--md" type="button">Outline</button></div>
		<figcaption class="sg-example__caption"><code>button(&#39;Outline&#39;, { variant: &#39;outline&#39; })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="btn btn--subtle btn--md" type="button">Subtle</button></div>
		<figcaption class="sg-example__caption"><code>button(&#39;Subtle&#39;, { variant: &#39;subtle&#39; })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="btn btn--danger btn--md" type="button">Danger</button></div>
		<figcaption class="sg-example__caption"><code>button(&#39;Danger&#39;, { variant: &#39;danger&#39; })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="btn btn--primary btn--sm" type="button">Small</button></div>
		<figcaption class="sg-example__caption"><code>button(&#39;Small&#39;, { variant: &#39;primary&#39;, size: &#39;sm&#39; })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="btn btn--primary btn--md" type="button">Medium</button></div>
		<figcaption class="sg-example__caption"><code>button(&#39;Medium&#39;, { variant: &#39;primary&#39;, size: &#39;md&#39; })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="btn btn--primary btn--lg" type="button">Large</button></div>
		<figcaption class="sg-example__caption"><code>button(&#39;Large&#39;, { variant: &#39;primary&#39;, size: &#39;lg&#39; })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="btn btn--primary btn--md" type="button"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.005 9H16v2h-4.995v5.005h-2V11H4V9h5.005V4.005h2z"/></svg> Add tool</button></div>
		<figcaption class="sg-example__caption"><code>button(&#39;Add tool&#39;, { variant: &#39;primary&#39;, icon: &#39;add&#39; })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="btn btn--outline btn--md" type="button"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m15.765 7.875-8.483 8.484a1 1 0 01-.253.184l-4.214 2.15-1.357-1.33L3.58 13.12q.073-.145.188-.26l8.48-8.48zm3.534-3.532-2.12 2.118-3.517-3.496 2.13-2.13z"/></svg> Edit</button></div>
		<figcaption class="sg-example__caption"><code>button(&#39;Edit&#39;, { variant: &#39;outline&#39;, icon: &#39;edit&#39; })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><a class="btn btn--outline btn--md" href="/search">Browse</a></div>
		<figcaption class="sg-example__caption"><code>button(&#39;Browse&#39;, { variant: &#39;outline&#39;, href: &#39;/search&#39; })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="btn btn--primary btn--md" type="button" disabled>Disabled</button></div>
		<figcaption class="sg-example__caption"><code>button(&#39;Disabled&#39;, { variant: &#39;primary&#39;, disabled: true })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="btn btn--icon btn--sm" aria-label="Move up" type="button"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m10 7 7.5 7.5-1.41 1.41L10 9.83l-6.09 6.08L2.5 14.5z"/></svg></button></div>
		<figcaption class="sg-example__caption"><code>iconButton(&#39;chevronUp&#39;, &#39;Move up&#39;, { size: &#39;sm&#39; })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="btn btn--icon btn--sm" aria-label="Move down" type="button"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 13 2.5 5.5 3.91 4.09 10 10.17l6.09-6.08L17.5 5.5z"/></svg></button></div>
		<figcaption class="sg-example__caption"><code>iconButton(&#39;chevronDown&#39;, &#39;Move down&#39;, { size: &#39;sm&#39; })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="btn btn--icon btn--sm" aria-label="Close" type="button"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M16.707 4.707 11.414 10l5.293 5.293-1.414 1.414L10 11.414l-5.293 5.293-1.414-1.414L8.586 10 3.293 4.707l1.414-1.414L10 8.586l5.293-5.293z"/></svg></button></div>
		<figcaption class="sg-example__caption"><code>iconButton(&#39;close&#39;, &#39;Close&#39;, { size: &#39;sm&#39; })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="btn btn--icon btn--danger btn--sm" aria-label="Remove" type="button"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M16.707 4.707 11.414 10l5.293 5.293-1.414 1.414L10 11.414l-5.293 5.293-1.414-1.414L8.586 10 3.293 4.707l1.414-1.414L10 8.586l5.293-5.293z"/></svg></button></div>
		<figcaption class="sg-example__caption"><code>iconButton(&#39;close&#39;, &#39;Remove&#39;, { size: &#39;sm&#39;, variant: &#39;danger&#39; })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="btn btn--icon btn--md" aria-label="Search" type="button"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg></button></div>
		<figcaption class="sg-example__caption"><code>iconButton(&#39;search&#39;, &#39;Search&#39;)</code><span>atoms</span></figcaption>
	</figure>
		</div>
	</section>
			<section class="sg-section" aria-labelledby="sg-icons">
		<h2 class="sg-section__title" id="sg-icons">Icons</h2>
		
		<div class="sg-token-grid">
			<div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
				<span class="sg-token__meta"><code>search</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 13 2.5 5.5 3.91 4.09 10 10.17l6.09-6.08L17.5 5.5z"/></svg>
				<span class="sg-token__meta"><code>chevronDown</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m10 7 7.5 7.5-1.41 1.41L10 9.83l-6.09 6.08L2.5 14.5z"/></svg>
				<span class="sg-token__meta"><code>chevronUp</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 17h16v2H1V1h2z"/><path d="M19 5v10H5v-1l4.5-5.5 3 3.5L18 5z"/></svg>
				<span class="sg-token__meta"><code>popular</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 17h16v2H1V1h2z"/><path d="M19 5v10H5v-1l4.5-5.5 3 3.5L18 5z"/></svg>
				<span class="sg-token__meta"><code>analyze</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M12.744 6.793H18.5l.607 1.795-4.7 3.589 1.802 5.828-1.563 1.09L10 15.545l-4.646 3.55-1.563-1.09 1.8-5.828-4.698-3.59.607-1.794h5.756l1.789-5.788h1.91l1.79 5.788Zm-4.013 2H4.456l3.459 2.643-1.289 4.17L10 13.027l3.373 2.577-1.288-4.17 3.459-2.642h-4.275L10 4.687z"/></svg>
				<span class="sg-token__meta"><code>star</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M12.744 6.793H18.5l.607 1.795-4.7 3.589 1.802 5.828-1.563 1.09L10 15.545l-4.646 3.55-1.563-1.09 1.8-5.828-4.698-3.59.607-1.794h5.756l1.789-5.788h1.91l1.79 5.788Z"/></svg>
				<span class="sg-token__meta"><code>starOutline</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m13 18-1.707.707L8 15.414l-3.293 3.293L3 18V5h10z"/><path d="M17 15h-2V3H6V1h11z"/></svg>
				<span class="sg-token__meta"><code>bookmark</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m15.765 7.875-8.483 8.484a1 1 0 01-.253.184l-4.214 2.15-1.357-1.33L3.58 13.12q.073-.145.188-.26l8.48-8.48zm3.534-3.532-2.12 2.118-3.517-3.496 2.13-2.13z"/></svg>
				<span class="sg-token__meta"><code>edit</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8.5 3H6a1 1 0 00-1 1v2.488c0 1.19-.525 2.273-1.371 3.012A4 4 0 015 12.512V16a1 1 0 001 1h2.5v2H6a3 3 0 01-3-3v-3.488a2 2 0 00-1.648-1.969L1 10.484V8.516l.352-.059A2 2 0 003 6.488V4a3 3 0 013-3h2.5zM14 1a3 3 0 013 3v2.488a2 2 0 001.648 1.969l.352.059v1.968l-.352.059A2 2 0 0017 12.512V16a3 3 0 01-3 3h-2.5v-2H14a1 1 0 001-1v-3.488c0-1.19.525-2.273 1.371-3.012A4 4 0 0115 6.488V4a1 1 0 00-1-1h-2.5V1z"/></svg>
				<span class="sg-token__meta"><code>code</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M4.876 1C6.781 1 8.602 1.71 10 2.966A7.67 7.67 0 0115.124 1H19v16h-3.876a5.67 5.67 0 00-4.355 2.04H9.23A5.67 5.67 0 004.876 17H1V1zM3 15h1.876A7.66 7.66 0 019 16.207V4.779A5.67 5.67 0 004.876 3H3zM15.124 3A5.67 5.67 0 0011 4.78v11.427A7.66 7.66 0 0115.124 15H17V3z"/></svg>
				<span class="sg-token__meta"><code>book</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M14.5 4H13v4.667l5.8 7.733L18 18H2l-.8-1.6L7 8.667V4H5.5V2h9zm-8.251 9-2.25 3h12.002l-2.25-3zM9 9.333 7.75 11h4.5L11 9.333V4H9z"/></svg>
				<span class="sg-token__meta"><code>research</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 11v8H2v-2a6 6 0 016-6zm7.05 1.733 1.844-1.105 1.028 1.716-1.929 1.156 1.929 1.157-1.03 1.715-1.842-1.106V18.5h-2v-2.235l-1.844 1.107-1.027-1.715 1.926-1.157-1.927-1.156 1.028-1.716 1.844 1.105V10.5h2zM10 1a4 4 0 110 8 4 4 0 010-8"/></svg>
				<span class="sg-token__meta"><code>admin</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M7 10c.91 0 1.764.244 2.5.67A5 5 0 0112 10h3a5 5 0 015 5v2H0v-2a5 5 0 015-5zm5 2q-.473.002-.901.138c.567.81.901 1.797.901 2.862h6a3 3 0 00-3-3zM6 3a3 3 0 110 6 3 3 0 010-6M13.5 3a3 3 0 110 6 3 3 0 010-6m0 2a1 1 0 100 2 1 1 0 000-2"/></svg>
				<span class="sg-token__meta"><code>group</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.005 9H16v2h-4.995v5.005h-2V11H4V9h5.005V4.005h2z"/></svg>
				<span class="sg-token__meta"><code>add</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M5.5 4.003a1.5 1.5 0 110 3 1.5 1.5 0 010-3"/><path d="m19.914 11.503-8.413 8.414L.004 8.414.003 1l1-1h7.415zM2.003 7.587l9.497 9.502 5.585-5.587-9.496-9.501L2.003 2z"/></svg>
				<span class="sg-token__meta"><code>tag</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M19 19H1v-2h18zM10.703 1l5.211 5.117-1.406 1.422L11 4v11H9V4L5.492 7.54 4.086 6.116 9.296 1z"/></svg>
				<span class="sg-token__meta"><code>upload</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 1a8.98 8.98 0 016.999 3.343L17 2h2v5l-1 1h-5l-.001-2h2.746a7 7 0 101.184 5h2.016A9 9 0 1110 1"/></svg>
				<span class="sg-token__meta"><code>convert</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M15 16h-4.685l-4.742 3.32L4 18.5V16H1V5h14zM3 14h3v2.58L9.685 14H13V7H3z"/><path d="M19 13h-2V3H5V1h14z"/></svg>
				<span class="sg-token__meta"><code>discuss</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.039 3.656c2.158-2.332 5.937-2.179 7.893.318a4.99 4.99 0 01-.272 6.487L10.757 19H9.243L1.34 10.461a4.99 4.99 0 01-.272-6.487c1.956-2.497 5.735-2.65 7.893-.318L10 4.776z"/></svg>
				<span class="sg-token__meta"><code>heart</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M13 20H7v-2h6zM10 0c1.938 0 3.58.556 4.745 1.644C15.918 2.738 16.5 4.27 16.5 6c0 2.22-1.15 3.732-2.04 4.727-.644.72-.96 1.633-.96 2.662V16h-7v-2.611c0-1.029-.317-1.942-.96-2.662C4.65 9.732 3.5 8.22 3.5 6c0-1.627.593-3.145 1.743-4.255C6.395.634 8.032 0 10 0"/></svg>
				<span class="sg-token__meta"><code>idea</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 16H1v-2h2zm16 0H5v-2h14zM3 11H1V9h2zm16 0H5V9h14zM3 6H1V4h2zm16 0H5V4h14z"/></svg>
				<span class="sg-token__meta"><code>list</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 8.5a1.5 1.5 0 110 3 1.5 1.5 0 010-3"/><path d="M11.74 3.218a7 7 0 011.822.757l2.095-1.046 1.414 1.414-1.047 2.094c.334.562.591 1.174.757 1.823L19 9v2l-2.219.74a7 7 0 01-.757 1.822l1.047 2.095-1.414 1.414-2.095-1.047a7 7 0 01-1.823.757L11 19H9l-.74-2.219a7 7 0 01-1.823-.757l-2.094 1.047-1.414-1.414 1.046-2.095a7 7 0 01-.757-1.823L1 11V9l2.218-.74a7 7 0 01.757-1.823L2.929 4.343l1.414-1.414 2.094 1.046a7 7 0 011.823-.757L9 1h2zM10 5a5 5 0 100 10 5 5 0 000-10"/></svg>
				<span class="sg-token__meta"><code>tools</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m16 8-1.087 12H5.087L4 8h2l.913 10h6.174L14 8zM13 4h5v2H2V4h5V0h6zM9 4h2V2H9z"/></svg>
				<span class="sg-token__meta"><code>reset</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M17 3H3v14h14v2H1V1h16z"/><path d="M19 9.293v1.414l-4.69 4.707L12.895 14l3-3H6V9h9.896l-3-3 1.414-1.414z"/></svg>
				<span class="sg-token__meta"><code>logout</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M5 2h12v10H5v8H3V0h2zm0 8h10V4H5z"/></svg>
				<span class="sg-token__meta"><code>report</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg>
				<span class="sg-token__meta"><code>check</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M13.75 6a1.5 1.5 0 110 3 1.5 1.5 0 010-3"/><path d="M13.706 1.5C17.128 1.5 20 4.133 20 7.5s-2.872 6-6.294 6c-.65 0-1.28-.095-1.873-.27q-.007-.004-.016-.006L9.855 15H9v2H7v1.5H1l-1-1v-2.435L7.446 8.13a6 6 0 01-.034-.631c0-3.367 2.872-6 6.294-6Zm0 2c-2.426 0-4.294 1.844-4.294 4q0 .407.083.79l.12.555L2 15.935v.565h3V15h2v-2h2.086l2.3-2.081.584.24a4.5 4.5 0 001.736.341c2.426 0 4.294-1.844 4.294-4s-1.868-4-4.294-4"/></svg>
				<span class="sg-token__meta"><code>key</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m17.835 19-1.248-3h-4.174l-1.248 3.001H9l4.577-11.005h1.846L20 19zm-4.59-5h2.51L14.5 10.982zM7.618 3H12v2H9.991a8.5 8.5 0 01-1.423 4.02q-.24.358-.528.707.634.367 1.379.711l.908.42-.839 1.816-.907-.42a18 18 0 01-2.026-1.09c-1.255.979-2.912 1.8-5.076 2.31l-.973.228-.458-1.946.973-.23c1.631-.383 2.885-.954 3.85-1.608C3.29 8.527 2.317 6.884 2.065 5H0V3h5.382l-.724-1.447 1.79-.895L7.617 3ZM4.094 5c.243 1.282.974 2.489 2.29 3.586A6.54 6.54 0 007.98 5z"/></svg>
				<span class="sg-token__meta"><code>language</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 1a9 9 0 110 18 9 9 0 010-18M8.028 11c.1 1.846.473 3.431.97 4.552.295.661.594 1.073.824 1.292.081.077.14.117.178.138a1 1 0 00.178-.138c.23-.22.529-.63.823-1.292.498-1.12.87-2.706.97-4.552zm-4.956 0a7 7 0 004.122 5.413C6.557 15.001 6.13 13.11 6.025 11zm10.903 0c-.104 2.11-.533 4-1.17 5.413A7 7 0 0016.928 11zm-6.78-7.414A7 7 0 003.071 9h2.953c.104-2.11.531-4.001 1.17-5.414ZM10 3.016a1 1 0 00-.178.14c-.23.22-.53.63-.823 1.292-.498 1.12-.87 2.706-.97 4.552h3.943c-.101-1.846-.473-3.431-.971-4.552-.294-.661-.593-1.073-.823-1.292a1 1 0 00-.178-.14m2.805.57c.638 1.413 1.066 3.303 1.17 5.414h2.953a7 7 0 00-4.123-5.414"/></svg>
				<span class="sg-token__meta"><code>globe</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 1a9 9 0 011 17.945V16.93A7.001 7.001 0 0010 3a7 7 0 00-4 12.743V13h2.001L8 18l-1 1H2v-2l2.346-.001A8.97 8.97 0 011 10a9 9 0 019-9"/><path d="M11 10h3.5v2H9V6h2z"/></svg>
				<span class="sg-token__meta"><code>history</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg>
				<span class="sg-token__meta"><code>external</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M16.707 4.707 11.414 10l5.293 5.293-1.414 1.414L10 11.414l-5.293 5.293-1.414-1.414L8.586 10 3.293 4.707l1.414-1.414L10 8.586l5.293-5.293z"/></svg>
				<span class="sg-token__meta"><code>close</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 14a4 4 0 110-8 4 4 0 010 8m0-2a2 2 0 100-4 2 2 0 000 4M9 0h2v3H9zM9 17h2v3H9zM0 9h3v2H0zM17 9h3v2h-3zM2.05 3.46 3.46 2.05l2.12 2.12-1.41 1.41zM14.42 15.83l1.41-1.41 2.12 2.12-1.41 1.41zM3.46 17.95l-1.41-1.41 2.12-2.12 1.41 1.41zM15.83 5.58l-1.41-1.41 2.12-2.12 1.41 1.41z"/></svg>
				<span class="sg-token__meta"><code>sun</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 1a9 9 0 108.66 11.46A7 7 0 1110.54 1.34 9 9 0 0010 1"/></svg>
				<span class="sg-token__meta"><code>moon</code></span>
			</div><div class="sg-token">
				<svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18 2a1 1 0 011 1v10a1 1 0 01-1 1h-5v2h2a1 1 0 010 2H6a1 1 0 010-2h2v-2H2a1 1 0 01-1-1V3a1 1 0 011-1zm-1 2H3v8h14z"/></svg>
				<span class="sg-token__meta"><code>system</code></span>
			</div>
		</div>
	</section>
			<section class="sg-section" aria-labelledby="sg-atoms">
		<h2 class="sg-section__title" id="sg-atoms">Atoms</h2>
		
		<div class="sg-examples">
			<figure class="sg-example">
		<div class="sg-example__demo"><span class="avatar " style="background:var(--wmf-green-aaa)" aria-hidden="true">C</span></div>
		<figcaption class="sg-example__caption"><code>avatar(title)</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><img class="avatar avatar--lg avatar--img" src="https://commons.wikimedia.org/wiki/Special:FilePath/OOjs_UI_icon_code.svg?width=144" alt="" width="72" height="72" loading="lazy" /></div>
		<figcaption class="sg-example__caption"><code>toolIcon(tool, &quot;lg&quot;)</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><span class="sg-empty">No visual markup in this state.</span></div>
		<figcaption class="sg-example__caption"><code>statusBadge(healthy)</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><span class="status status--red"><span class="dot dot--red"></span>Deprecated</span></div>
		<figcaption class="sg-example__caption"><code>statusBadge(deprecated)</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><span class="status status--yellow"><span class="dot dot--yellow"></span>Experimental</span></div>
		<figcaption class="sg-example__caption"><code>statusBadge(experimental)</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><span class="status status--green experimental"><span class="dot dot--green"></span>Healthy</span></div>
		<figcaption class="sg-example__caption"><code>healthBadge(tool)</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><span class="views experimental"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 17h16v2H1V1h2z"/><path d="M19 5v10H5v-1l4.5-5.5 3 3.5L18 5z"/></svg> 1.8K views</span></div>
		<figcaption class="sg-example__caption"><code>popularityBadge(tool)</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><span class="signal" title="Appears in 5 curated lists"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 16H1v-2h2zm16 0H5v-2h14zM3 11H1V9h2zm16 0H5V9h14zM3 6H1V4h2zm16 0H5V4h14z"/></svg> In 5 lists</span></div>
		<figcaption class="sg-example__caption"><code>endorsementChip(5)</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><span class="signal" title="Listing 7 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:78%"></span></span>7/9</span></div>
		<figcaption class="sg-example__caption"><code>completenessMeter({ filled: 7, total: 9 })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><span class="signal signal--complete" title="Listing 9 of 9 fields complete"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg> Well documented</span></div>
		<figcaption class="sg-example__caption"><code>completenessMeter({ filled: 9, total: 9 })</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><span class="signal signal--fit"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg> Fits you</span></div>
		<figcaption class="sg-example__caption"><code>fitChip(tool)</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><div class="thanks__agg">
						<span class="thanks__icon" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.039 3.656c2.158-2.332 5.937-2.179 7.893.318a4.99 4.99 0 01-.272 6.487L10.757 19H9.243L1.34 10.461a4.99 4.99 0 01-.272-6.487c1.956-2.497 5.735-2.65 7.893-.318L10 4.776z"/></svg></span>
						<span class="thanks__score">73</span>
						<span class="thanks__count">people thanked</span>
					</div></div>
		<figcaption class="sg-example__caption"><code>thanksBlock(tool)</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><p class="usage"><strong>8,470</strong> editors used this in the last 30 days</p></div>
		<figcaption class="sg-example__caption"><code>usageBlock(tool)</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="sg-inline-list"><a class="tag" href="/search?keywords__term=citations" dir="auto">citations</a><a class="tag" href="/search?keywords__term=references" dir="auto">references</a><a class="tag" href="/search?keywords__term=editing" dir="auto">editing</a><a class="tag" href="/search?keywords__term=quality" dir="auto">quality</a><a class="tag" href="/search?keywords__term=wikidata" dir="auto">wikidata</a><a class="tag" href="/search?keywords__term=sources" dir="auto">sources</a></div></div>
		<figcaption class="sg-example__caption"><code>keywordTags(tool)</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="sg-inline-list"><span class="glance" dir="auto">web app</span><span class="glance" dir="auto">GPL-3.0-or-later</span><span class="glance" dir="auto">All wikis</span><span class="glance">4 languages</span></div></div>
		<figcaption class="sg-example__caption"><code>glanceChips(tool)</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="sg-form">
				<label class="le__label">Tool title <span class="le__req">*</span>
		
		<input class="le__input" id="sg-tool-title" type="text" required aria-describedby="sg-tool-title-err" maxlength="300" value="Citation Helper"  /><span class="le__error" id="sg-tool-title-err" hidden></span></label>
				<label class="le__label">Description <span class="le__hint" id="sg-tool-description-hint">Shown in search results and detail pages.</span>
		<textarea class="le__input" id="sg-tool-description" rows="3" aria-describedby="sg-tool-description-hint" maxlength="2000">Suggests reliable source templates, checks missing citations, and helps editors add references without leaving the page.</textarea></label>
				<div class="le__checks"><label class="le__check"><input type="checkbox" id="sg-tool-experimental" checked /> Experimental</label><label class="le__check"><input type="checkbox" id="sg-tool-deprecated" /> Deprecated</label></div>
				<label class="le__label">Tool type
		<select class="le__input" id="sg-tool-type"><option value="">—</option><option value="web app" selected>web app</option><option value="desktop app">desktop app</option><option value="bot">bot</option><option value="gadget">gadget</option><option value="user script">user script</option><option value="command line tool">command line tool</option><option value="coding framework">coding framework</option><option value="lua module">lua module</option><option value="template">template</option><option value="other">other</option></select></label>
			</div></div>
		<figcaption class="sg-example__caption"><code>fInput / fArea / fCheck / fSelect</code><span>atoms</span></figcaption>
	</figure>
			<div class="sg-group">
		<h3 class="sg-group__title">Form controls</h3>
		<p class="sg-group__note">Standalone search, facet, list-editor, and intent-builder controls now share one control foundation.</p>
		<div class="sg-examples sg-examples--controls">
			<figure class="sg-example">
		<div class="sg-example__demo"><input class="search__input" id="sg-search-input" type="search" aria-label="Search tools" placeholder="Search tools..." autocomplete="off" /></div>
		<figcaption class="sg-example__caption"><code>input.search__input</code><span>atoms / shared control foundation</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><input class="facets__search" id="sg-facet-search" type="search" aria-label="Search tools" placeholder="Search tools..." autocomplete="off" /></div>
		<figcaption class="sg-example__caption"><code>input.facets__search</code><span>atoms / shared control foundation</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><input class="le__input" id="sg-list-editor-input" type="text" aria-label="List title" placeholder="List title" /></div>
		<figcaption class="sg-example__caption"><code>input.le__input</code><span>atoms / shared control foundation</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="intent__word" type="button">Wikidata</button></div>
		<figcaption class="sg-example__caption"><code>button.intent__word</code><span>atoms / editable phrase</span></figcaption>
	</figure>
		</div>
	</div>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="detail__meta"><div><div class="meta__k">License</div><div class="meta__v" dir="auto">GPL-3.0-or-later</div></div><div><div class="meta__k">Wikis</div><div class="meta__v" dir="auto">All wikis</div></div></div></div>
		<figcaption class="sg-example__caption"><code>metaItem(key, value)</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><a class="btn btn--outline btn--md" href="https://github.com/example/citation-helper" target="_blank" rel="noopener nofollow"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg> Repository</a></div>
		<figcaption class="sg-example__caption"><code>linkOut(label, url)</code><span>atoms</span></figcaption>
	</figure>
		</div>
	</section>
			<section class="sg-section" aria-labelledby="sg-molecules">
		<h2 class="sg-section__title" id="sg-molecules">Molecules</h2>
		
		<div class="sg-examples">
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="favbtn" type="button" data-fav="styleguide-citation-helper" aria-pressed="false" aria-label="Save to favorites"><span class="favbtn__ic" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M12.744 6.793H18.5l.607 1.795-4.7 3.589 1.802 5.828-1.563 1.09L10 15.545l-4.646 3.55-1.563-1.09 1.8-5.828-4.698-3.59.607-1.794h5.756l1.789-5.788h1.91l1.79 5.788Z"/></svg></span><span class="favbtn__t">Save</span></button></div>
		<figcaption class="sg-example__caption"><code>favBtn(name)</code><span>molecules</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><button class="favbtn is-on" type="button" data-fav="styleguide-deprecated-citation-helper" aria-pressed="true" aria-label="Remove from favorites"><span class="favbtn__ic" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M12.744 6.793H18.5l.607 1.795-4.7 3.589 1.802 5.828-1.563 1.09L10 15.545l-4.646 3.55-1.563-1.09 1.8-5.828-4.698-3.59.607-1.794h5.756l1.789-5.788h1.91l1.79 5.788Zm-4.013 2H4.456l3.459 2.643-1.289 4.17L10 13.027l3.373 2.577-1.288-4.17 3.459-2.642h-4.275L10 4.687z"/></svg></span><span class="favbtn__t">Saved</span></button></div>
		<figcaption class="sg-example__caption"><code>favBtn(savedName)</code><span>molecules</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><details class="savemenu">
		<summary class="btn btn--outline"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m13 18-1.707.707L8 15.414l-3.293 3.293L3 18V5h10z"/><path d="M17 15h-2V3H6V1h11z"/></svg> Save to a list</summary>
		<div class="savemenu__pop"><button class="savemenu__item is-on" type="button" data-listadd="demo-styleguide-campaign" data-tn="styleguide-citation-helper" aria-pressed="true"><span class="savemenu__mark" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span> <span dir="auto">Campaign organizer toolkit</span></button><button class="savemenu__item" type="button" data-listadd="demo-styleguide-thanks" data-tn="styleguide-citation-helper" aria-pressed="false"><span class="savemenu__mark" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.005 9H16v2h-4.995v5.005h-2V11H4V9h5.005V4.005h2z"/></svg></span> <span dir="auto">Tools to thank</span></button><a class="savemenu__new" href="/lists/create"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.005 9H16v2h-4.995v5.005h-2V11H4V9h5.005V4.005h2z"/></svg> New list…</a></div>
	</details></div>
		<figcaption class="sg-example__caption"><code>saveToListControl(name)</code><span>molecules</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="facet-group"><h2 class="facet-group__title">Tool type</h2><label class="facet"><input type="checkbox" data-facet="tool_type" value="web app" checked> <span dir="auto">web app</span> <span class="facet__n">128</span></label><label class="facet"><input type="checkbox" data-facet="tool_type" value="bot"> <span dir="auto">bot</span> <span class="facet__n">74</span></label><label class="facet"><input type="checkbox" data-facet="tool_type" value="user script"> <span dir="auto">user script</span> <span class="facet__n">52</span></label><label class="facet"><input type="checkbox" data-facet="tool_type" value="gadget"> <span dir="auto">gadget</span> <span class="facet__n">31</span></label></div></div>
		<figcaption class="sg-example__caption"><code>renderFacetGroup(group, facets, selected)</code><span>molecules</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><nav class="pager" aria-label="Pagination"><button class="pager__btn" type="button"  data-page="1">‹ Prev</button><button class="pager__btn" type="button"  data-page="1">1</button><button class="pager__btn is-current" type="button"  data-page="2" aria-current="page">2</button><button class="pager__btn" type="button"  data-page="3">3</button><button class="pager__btn" type="button"  data-page="4">4</button><span class="pager__gap">…</span><button class="pager__btn" type="button"  data-page="7">7</button><button class="pager__btn" type="button"  data-page="3">Next ›</button></nav></div>
		<figcaption class="sg-example__caption"><code>renderPager(2, 7)</code><span>molecules</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><div class="acct">
		<button class="acct__btn" id="sg-acct-btn" type="button" aria-haspopup="true" aria-expanded="false" aria-controls="sg-acct-menu">
			<span class="avatar avatar--sm" style="background:var(--wmf-blue-aaa)" aria-hidden="true">A</span>
			<span class="acct__name">Amina Hassan</span>
			<svg class="icon acct__caret" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 13 2.5 5.5 3.91 4.09 10 10.17l6.09-6.08L17.5 5.5z"/></svg>
		</button>
	</div></div>
		<figcaption class="sg-example__caption"><code>.acct__btn</code><span>molecules</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="sg-inline-list">
		<button class="exp-toggle" type="button" role="switch" aria-checked="true">
			<span class="exp-toggle__track"><span class="exp-toggle__thumb"></span></span>
			<span class="exp-toggle__label">Prospective features on</span>
		</button>
		<button class="exp-toggle" type="button" role="switch" aria-checked="false">
			<span class="exp-toggle__track"><span class="exp-toggle__thumb"></span></span>
			<span class="exp-toggle__label">Prospective features off</span>
		</button>
	</div></div>
		<figcaption class="sg-example__caption"><code>.exp-toggle</code><span>organisms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><div class="sg-qv-close-frame">
		<button class="qv__x" type="button" aria-label="Close quick view"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M16.707 4.707 11.414 10l5.293 5.293-1.414 1.414L10 11.414l-5.293 5.293-1.414-1.414L8.586 10 3.293 4.707l1.414-1.414L10 8.586l5.293-5.293z"/></svg></button>
	</div></div>
		<figcaption class="sg-example__caption"><code>.qv__x</code><span>organisms</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="sg-control-stack">
		<form class="le__add">
			<input class="le__input" type="url" aria-label="Tool info URL" placeholder="https://example.org/toolinfo.json" />
			<button class="btn btn--outline btn--md" type="submit">Register</button>
		</form>
		<ul class="at__urls">
			<li><code class="at__url">https://example.org/toolinfo.json</code> <button class="btn btn--icon btn--sm at__rm" aria-label="Remove URL" type="button"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M16.707 4.707 11.414 10l5.293 5.293-1.414 1.414L10 11.414l-5.293 5.293-1.414-1.414L8.586 10 3.293 4.707l1.414-1.414L10 8.586l5.293-5.293z"/></svg></button></li>
		</ul>
		<textarea class="le__input at__json" rows="4" aria-label="Tool info JSON" placeholder='{ "name": "my-tool", "title": "My Tool" }'></textarea>
		<p class="at__result at__result--ok">1 added, 2 updated</p>
		<p class="at__result at__result--err">Invalid JSON: expected a tool object.</p>
	</div></div>
		<figcaption class="sg-example__caption"><code>Annotation editor controls</code><span>molecules</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="sg-control-stack">
		<h2 class="le__h2">Tools <span class="le__count">2 tools</span></h2>
		<p class="le__ro">Name: <code>commons-upload-helper</code></p>
		<div class="le__add">
			<input class="le__input" type="search" aria-label="Search tools to add" placeholder="Search tools to add..." autocomplete="off" />
			<button class="btn btn--outline btn--md" type="button">Add</button>
		</div>
		<div class="le__results">
			<button class="le__result" type="button"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.005 9H16v2h-4.995v5.005h-2V11H4V9h5.005V4.005h2z"/></svg> <span>Wiki Loves Monuments map</span></button>
			<button class="le__result is-in" type="button" disabled><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg> <span>Commons Pattypan</span></button>
		</div>
		<p class="le__searching">Searching...</p>
		<ol class="le__tools">
			<li data-tn="citation-helper"><span class="le__tn" dir="auto">citation-helper</span>
				<span class="le__rowact">
					<button class="btn btn--icon btn--sm" aria-label="Move up" type="button" data-move="up"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m10 7 7.5 7.5-1.41 1.41L10 9.83l-6.09 6.08L2.5 14.5z"/></svg></button>
					<button class="btn btn--icon btn--sm" aria-label="Move down" type="button" data-move="down"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 13 2.5 5.5 3.91 4.09 10 10.17l6.09-6.08L17.5 5.5z"/></svg></button>
					<button class="btn btn--icon btn--danger btn--sm" aria-label="Remove from list" type="button" data-rm><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M16.707 4.707 11.414 10l5.293 5.293-1.414 1.414L10 11.414l-5.293 5.293-1.414-1.414L8.586 10 3.293 4.707l1.414-1.414L10 8.586l5.293-5.293z"/></svg></button>
				</span>
			</li>
			<li class="le__empty">No more tools in this list.</li>
		</ol>
		<div class="le__actions">
			<button class="btn btn--primary btn--md" type="button">Save list</button>
			<button class="btn btn--danger btn--md le__delete" type="button">Delete list</button>
		</div>
	</div></div>
		<figcaption class="sg-example__caption"><code>List editor full row</code><span>molecules</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><a class="icon-btn" href="/search"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg> Search</a></div>
		<figcaption class="sg-example__caption"><code>.icon-btn</code><span>organisms</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="sg-inline-list"><a class="persona" href="/search?q=editors"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m15.765 7.875-8.483 8.484a1 1 0 01-.253.184l-4.214 2.15-1.357-1.33L3.58 13.12q.073-.145.188-.26l8.48-8.48zm3.534-3.532-2.12 2.118-3.517-3.496 2.13-2.13z"/></svg> Editors</a><a class="persona" href="/search?q=developers"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8.5 3H6a1 1 0 00-1 1v2.488c0 1.19-.525 2.273-1.371 3.012A4 4 0 015 12.512V16a1 1 0 001 1h2.5v2H6a3 3 0 01-3-3v-3.488a2 2 0 00-1.648-1.969L1 10.484V8.516l.352-.059A2 2 0 003 6.488V4a3 3 0 013-3h2.5zM14 1a3 3 0 013 3v2.488a2 2 0 001.648 1.969l.352.059v1.968l-.352.059A2 2 0 0017 12.512V16a3 3 0 01-3 3h-2.5v-2H14a1 1 0 001-1v-3.488c0-1.19.525-2.273 1.371-3.012A4 4 0 0115 6.488V4a1 1 0 00-1-1h-2.5V1z"/></svg> Developers</a><a class="persona" href="/search?q=readers"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M4.876 1C6.781 1 8.602 1.71 10 2.966A7.67 7.67 0 0115.124 1H19v16h-3.876a5.67 5.67 0 00-4.355 2.04H9.23A5.67 5.67 0 004.876 17H1V1zM3 15h1.876A7.66 7.66 0 019 16.207V4.779A5.67 5.67 0 004.876 3H3zM15.124 3A5.67 5.67 0 0011 4.78v11.427A7.66 7.66 0 0115.124 15H17V3z"/></svg> Readers</a></div></div>
		<figcaption class="sg-example__caption"><code>.persona navigation chip</code><span>molecules</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><form class="intent">
		<div class="intent__sentence" aria-label="Build a tool search">
			<span class="intent__copy">I want to see tools</span>
			<span class="intent__choice"><button class="intent__word" type="button" aria-haspopup="menu" aria-expanded="false"><span>made for</span></button></span>
			<span class="intent__choice"><button class="intent__word" type="button" aria-haspopup="menu" aria-expanded="false"><span>editors</span></button></span>
			<span class="intent__copy">on</span>
			<span class="intent__choice"><button class="intent__word" type="button" aria-haspopup="menu" aria-expanded="false"><span>Wikidata</span></button></span>
			<button class="intent__go" type="submit">See tools</button>
			<button class="intent__clear" type="button">clear</button>
		</div>
	</form></div>
		<figcaption class="sg-example__caption"><code>.intent sentence builder</code><span>molecules</span></figcaption>
	</figure>
		</div>
	</section>
			<section class="sg-section" aria-labelledby="sg-content-components">
		<h2 class="sg-section__title" id="sg-content-components">Content components</h2>
		
		<div class="sg-examples sg-examples--organisms">
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="detail__meta">
		<div><div class="meta__k">License</div><div class="meta__v" dir="auto">GPL-3.0-or-later</div></div>
		<div><div class="meta__k">Wikis</div><div class="meta__v" dir="auto">All wikis</div></div>
		<div><div class="meta__k">Maintainer</div><div class="meta__v" dir="auto">Ada Lovelace</div></div>
		<div><div class="meta__k">Tool type</div><div class="meta__v" dir="auto">web app</div></div>
	</div></div>
		<figcaption class="sg-example__caption"><code>.detail__meta / .meta__k / .meta__v</code><span>atoms / molecules</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><label class="sort"><span class="skip-label">Sort by</span><select>
		<option>Most relevant</option>
		<option>Recently updated</option>
		<option>Name</option>
	</select></label></div>
		<figcaption class="sg-example__caption"><code>sort control</code><span>molecules</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><span class="exp-badge">Experimental</span></div>
		<figcaption class="sg-example__caption"><code>exp-badge</code><span>atoms</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><ul class="recent">
		<li><a href="/tools/citation-helper"><span class="avatar " style="background:var(--wmf-green-aaa)" aria-hidden="true">C</span>
			<div><div class="recent__title">Citation Helper</div>
			<div class="recent__meta">Maintainer: <span>Editing team</span></div></div>
			<time class="recent__when" datetime="2026-06-23"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 1a9 9 0 011 17.945V16.93A7.001 7.001 0 0010 3a7 7 0 00-4 12.743V13h2.001L8 18l-1 1H2v-2l2.346-.001A8.97 8.97 0 011 10a9 9 0 019-9"/><path d="M11 10h3.5v2H9V6h2z"/></svg> yesterday</time></a></li>
		<li><a href="/tools/commons-upload"><span class="avatar " style="background:var(--color-success)" aria-hidden="true">C</span>
			<div><div class="recent__title">Commons Upload</div>
			<div class="recent__meta">Maintainer: <span>Commons volunteers</span></div></div>
			<time class="recent__when" datetime="2026-06-21"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M10 1a9 9 0 011 17.945V16.93A7.001 7.001 0 0010 3a7 7 0 00-4 12.743V13h2.001L8 18l-1 1H2v-2l2.346-.001A8.97 8.97 0 011 10a9 9 0 019-9"/><path d="M11 10h3.5v2H9V6h2z"/></svg> 3 days ago</time></a></li>
	</ul></div>
		<figcaption class="sg-example__caption"><code>recent list</code><span>organisms</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="sg-panel-pair">
		<div class="panel">
			<h3 class="panel__title">Recently updated</h3>
			<p class="sg-note">Borderless sidebar block with a ruled title.</p>
			<a class="panel__foot" href="/recent">View recent changes</a>
		</div>
		<div class="panel panel--cta">
			<div class="cta__icon" aria-hidden="true"><svg class="icon icon--lg" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M13 20H7v-2h6zM10 0c1.938 0 3.58.556 4.745 1.644C15.918 2.738 16.5 4.27 16.5 6c0 2.22-1.15 3.732-2.04 4.727-.644.72-.96 1.633-.96 2.662V16h-7v-2.611c0-1.029-.317-1.942-.96-2.662C4.65 9.732 3.5 8.22 3.5 6c0-1.627.593-3.145 1.743-4.255C6.395.634 8.032 0 10 0"/></svg></div>
			<h3>Built a tool for Wikimedia?</h3>
			<p>Add a <code>toolinfo.json</code> to your repository so other Wikimedians can find it.</p>
			<a class="btn btn--outline btn--md" href="https://toolhub.wikimedia.org/add-or-remove-tools?tab=tool-create" rel="nofollow">Submit a tool</a>
		</div>
	</div></div>
		<figcaption class="sg-example__caption"><code>panel + panel--cta</code><span>organisms</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="linkgrid">
		<a class="linkcard" href="/contribute">
			<span class="linkcard__icon" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M5 2h12v10H5v8H3V0h2zm0 8h10V4H5z"/></svg></span>
			<span class="linkcard__body"><span class="linkcard__title">Report a bug</span>
			<span class="linkcard__desc">Open a task on the Toolhub board.</span></span>
		</a>
		<a class="linkcard" href="/api-docs">
			<span class="linkcard__icon" aria-hidden="true"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8.5 3H6a1 1 0 00-1 1v2.488c0 1.19-.525 2.273-1.371 3.012A4 4 0 015 12.512V16a1 1 0 001 1h2.5v2H6a3 3 0 01-3-3v-3.488a2 2 0 00-1.648-1.969L1 10.484V8.516l.352-.059A2 2 0 003 6.488V4a3 3 0 013-3h2.5zM14 1a3 3 0 013 3v2.488a2 2 0 001.648 1.969l.352.059v1.968l-.352.059A2 2 0 0017 12.512V16a3 3 0 01-3 3h-2.5v-2H14a1 1 0 001-1v-3.488c0-1.19.525-2.273 1.371-3.012A4 4 0 0115 6.488V4a1 1 0 00-1-1h-2.5V1z"/></svg></span>
			<span class="linkcard__body"><span class="linkcard__title">API documentation</span>
			<span class="linkcard__desc">Inspect live read-only endpoints.</span></span>
		</a>
	</div></div>
		<figcaption class="sg-example__caption"><code>linkgrid + linkcard</code><span>molecules</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="browse sg-browse-demo">
		<aside class="facets">
			<input class="facets__search" type="search" aria-label="Search filters" placeholder="Search filters" />
		</aside>
		<div class="browse__main">
			<div class="browse__bar">
				<span class="browse__count" aria-live="polite">142 tools for "Commons"</span>
				<label class="sort"><span class="skip-label">Sort by</span><select>
		<option>Most relevant</option>
		<option>Recently updated</option>
		<option>Name</option>
	</select></label>
			</div>
			<p class="empty">Results render below this control row.</p>
		</div>
	</div></div>
		<figcaption class="sg-example__caption"><code>browse bar</code><span>organisms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><ul class="maint-list">
		<li><span class="avatar " style="background:var(--wmf-blue-aaa)" aria-hidden="true">A</span> <span>Amina Hassan</span></li>
		<li><span class="avatar " style="background:var(--wmf-blue-aaa)" aria-hidden="true">M</span> <span>Maps team</span></li>
	</ul></div>
		<figcaption class="sg-example__caption"><code>maintainer list</code><span>organisms</span></figcaption>
	</figure>
		</div>
	</section>
			<section class="sg-section" aria-labelledby="sg-organisms">
		<h2 class="sg-section__title" id="sg-organisms">Organisms</h2>
		
		<div class="sg-examples sg-examples--organisms">
			<figure class="sg-example">
		<div class="sg-example__demo">
	<article class="tcard tcard--complete" data-tool="styleguide-citation-helper">
		
		<div class="tcard__head">
			<img class="avatar avatar--img" src="https://commons.wikimedia.org/wiki/Special:FilePath/OOjs_UI_icon_code.svg?width=96" alt="" width="48" height="48" loading="lazy" />
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="styleguide-citation-helper" aria-label="Quick look: Citation Helper" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Citation Helper</button>
				<div class="tcard__maint">by <span dir="auto">Ada Lovelace</span></div>
			</div>
		</div>
		<p class="tcard__desc" dir="auto">Suggests reliable source templates, checks missing citations, and helps editors add references without leaving the page.</p>
		<div class="tcard__tags"><span class="tag" data-q="citations" dir="auto">citations</span><span class="tag" data-q="references" dir="auto">references</span><span class="tag tag--more">+4</span></div>
		<div class="tcard__signals"><span class="signal signal--complete" title="Listing 9 of 9 fields complete"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg> Well documented</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">web app · All wikis</span><span class="tcard__footr"><u|2026-05-12T14:30:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></div>
		<figcaption class="sg-example__caption"><code>toolCard(tool)</code><span>organisms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo">
	<article class="tcard tcard--popular tcard--complete" data-tool="styleguide-citation-helper">
		
		<div class="tcard__head">
			<span class="rankbadge" aria-hidden="true">1</span><img class="avatar avatar--img" src="https://commons.wikimedia.org/wiki/Special:FilePath/OOjs_UI_icon_code.svg?width=96" alt="" width="48" height="48" loading="lazy" />
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="styleguide-citation-helper" aria-label="Quick look: Citation Helper" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Citation Helper</button>
				<div class="tcard__maint">by <span dir="auto">Ada Lovelace</span></div>
			</div>
		</div>
		<p class="tcard__desc" dir="auto">Suggests reliable source templates, checks missing citations, and helps editors add references without leaving the page.</p>
		<div class="tcard__tags"><span class="tag" data-q="citations" dir="auto">citations</span><span class="tag" data-q="references" dir="auto">references</span><span class="tag tag--more">+4</span></div>
		<div class="tcard__signals"><span class="signal signal--complete" title="Listing 9 of 9 fields complete"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg> Well documented</span></div>
		<div class="tcard__foot"><span class="views experimental"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 17h16v2H1V1h2z"/><path d="M19 5v10H5v-1l4.5-5.5 3 3.5L18 5z"/></svg> 1.8K views</span><span class="tcard__footr"><u|2026-05-12T14:30:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></div>
		<figcaption class="sg-example__caption"><code>toolCard(tool, { popular: true, rank: 1 })</code><span>organisms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo">
	<article class="tcard tcard--complete" data-tool="styleguide-deprecated-citation-helper">
		<span class="tcard__flag status status--red"><span class="dot dot--red"></span>Deprecated</span>
		<div class="tcard__head">
			<img class="avatar avatar--img" src="https://commons.wikimedia.org/wiki/Special:FilePath/OOjs_UI_icon_code.svg?width=96" alt="" width="48" height="48" loading="lazy" />
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="styleguide-deprecated-citation-helper" aria-label="Quick look: Legacy Citation Helper" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Legacy Citation Helper</button>
				<div class="tcard__maint">by <span dir="auto">Ada Lovelace</span></div>
			</div>
		</div>
		<p class="tcard__desc" dir="auto">A retired citation workflow kept visible so maintainers can point editors to the replacement tool.</p>
		<div class="tcard__tags"><span class="tag" data-q="citations" dir="auto">citations</span><span class="tag" data-q="references" dir="auto">references</span><span class="tag tag--more">+4</span></div>
		<div class="tcard__signals"><span class="signal signal--complete" title="Listing 9 of 9 fields complete"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg> Well documented</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">web app · All wikis</span><span class="tcard__footr"><u|2025-11-04T09:15:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></div>
		<figcaption class="sg-example__caption"><code>toolCard(deprecatedTool)</code><span>organisms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo">
	<a class="lcard" href="/lists/styleguide-campaign-toolkit" aria-label="Campaign organizer toolkit list, 3 tools">
		<span class="avatar " style="background:var(--color-progressive-hover)" aria-hidden="true">C</span>
		<div class="lcard__body">
			<div class="lcard__title" dir="auto">Campaign organizer toolkit <span class="lcard__count">3 tools</span> <span class="exp-badge">Demo</span></div>
			<div class="lcard__desc" dir="auto">A compact set of tools for preparing edit-a-thons, checking article quality, and following up after an event.</div>
		</div>
	</a></div>
		<figcaption class="sg-example__caption"><code>listCard(list)</code><span>organisms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><div class="panel"><h3 class="panel__title">Browse by need</h3><p class="sg-note">Borderless sidebar block: a rule under the title and content flush below, matching the main-content section heads.</p></div></div>
		<figcaption class="sg-example__caption"><code>panel (sidebar)</code><span>organisms</span></figcaption>
	</figure>
			<figure class="sg-example">
		<div class="sg-example__demo"><div class="panel">
		<h3 class="panel__title">Listing completeness</h3>
		<span class="signal signal--complete" title="Listing 9 of 9 fields complete"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg> Well documented</span>
		<ul class="complete-list"><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>Description</span></li><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>Tool URL</span></li><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>Source repository</span></li><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>License</span></li><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>Keywords</span></li><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>Audience or task tagged</span></li><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>Documentation</span></li><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>Icon</span></li><li><span class="complete-list__icon"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg></span><span>Issue tracker or feedback</span></li></ul>
	</div></div>
		<figcaption class="sg-example__caption"><code>Listing completeness</code><span>organisms</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><ul class="card-grid grid-tools" role="list"><li>
	<article class="tcard tcard--complete" data-tool="styleguide-citation-helper">
		
		<div class="tcard__head">
			<img class="avatar avatar--img" src="https://commons.wikimedia.org/wiki/Special:FilePath/OOjs_UI_icon_code.svg?width=96" alt="" width="48" height="48" loading="lazy" />
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="styleguide-citation-helper" aria-label="Quick look: Citation Helper" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Citation Helper</button>
				<div class="tcard__maint">by <span dir="auto">Ada Lovelace</span></div>
			</div>
		</div>
		<p class="tcard__desc" dir="auto">Suggests reliable source templates, checks missing citations, and helps editors add references without leaving the page.</p>
		<div class="tcard__tags"><span class="tag" data-q="citations" dir="auto">citations</span><span class="tag" data-q="references" dir="auto">references</span><span class="tag tag--more">+4</span></div>
		<div class="tcard__signals"><span class="signal signal--complete" title="Listing 9 of 9 fields complete"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg> Well documented</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">web app · All wikis</span><span class="tcard__footr"><u|2026-05-12T14:30:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li><li>
	<article class="tcard tcard--popular tcard--complete" data-tool="styleguide-experimental-citation-helper">
		<span class="tcard__flag status status--yellow"><span class="dot dot--yellow"></span>Experimental</span>
		<div class="tcard__head">
			<span class="rankbadge" aria-hidden="true">2</span><img class="avatar avatar--img" src="https://commons.wikimedia.org/wiki/Special:FilePath/OOjs_UI_icon_code.svg?width=96" alt="" width="48" height="48" loading="lazy" />
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="styleguide-experimental-citation-helper" aria-label="Quick look: Citation Helper Labs" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Citation Helper Labs</button>
				<div class="tcard__maint">by <span dir="auto">Ada Lovelace</span></div>
			</div>
		</div>
		<p class="tcard__desc" dir="auto">An early test of reference recommendations using opt-in editor feedback and limited wiki coverage.</p>
		<div class="tcard__tags"><span class="tag" data-q="citations" dir="auto">citations</span><span class="tag" data-q="references" dir="auto">references</span><span class="tag tag--more">+4</span></div>
		<div class="tcard__signals"><span class="signal signal--complete" title="Listing 9 of 9 fields complete"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg> Well documented</span></div>
		<div class="tcard__foot"><span class="views experimental"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 17h16v2H1V1h2z"/><path d="M19 5v10H5v-1l4.5-5.5 3 3.5L18 5z"/></svg> 612 views</span><span class="tcard__footr"><u|2026-06-01T16:45:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li><li>
	<article class="tcard tcard--complete" data-tool="styleguide-deprecated-citation-helper">
		<span class="tcard__flag status status--red"><span class="dot dot--red"></span>Deprecated</span>
		<div class="tcard__head">
			<img class="avatar avatar--img" src="https://commons.wikimedia.org/wiki/Special:FilePath/OOjs_UI_icon_code.svg?width=96" alt="" width="48" height="48" loading="lazy" />
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="styleguide-deprecated-citation-helper" aria-label="Quick look: Legacy Citation Helper" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Legacy Citation Helper</button>
				<div class="tcard__maint">by <span dir="auto">Ada Lovelace</span></div>
			</div>
		</div>
		<p class="tcard__desc" dir="auto">A retired citation workflow kept visible so maintainers can point editors to the replacement tool.</p>
		<div class="tcard__tags"><span class="tag" data-q="citations" dir="auto">citations</span><span class="tag" data-q="references" dir="auto">references</span><span class="tag tag--more">+4</span></div>
		<div class="tcard__signals"><span class="signal signal--complete" title="Listing 9 of 9 fields complete"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M18.154 3.837 8.034 16.62l-1.384.18-4.8-3.6 1.2-1.6 4.02 3.015 9.517-12.02z"/></svg> Well documented</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">web app · All wikis</span><span class="tcard__footr"><u|2025-11-04T09:15:00Z|tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li></ul></div>
		<figcaption class="sg-example__caption"><code>grid(className, items, render)</code><span>organisms</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="sg-quickview">
		<div class="qv__head"><img class="avatar avatar--lg avatar--img" src="https://commons.wikimedia.org/wiki/Special:FilePath/OOjs_UI_icon_code.svg?width=144" alt="" width="72" height="72" loading="lazy" />
			<div class="qv__id"><h2 class="qv__title" id="qv-title" dir="auto">Citation Helper</h2>
			<div class="qv__by">by <span dir="auto">Ada Lovelace, Grace Hopper</span></div></div>
		</div>
		<div class="qv__status">
			
			
			
			<!-- EXPERIMENTAL — operational health. Needs: an uptime/health-check service. -->
			<span class="status status--green experimental"><span class="dot dot--green"></span>Healthy</span>
			<!-- EXPERIMENTAL — popularity. Needs: usage/view tracking. -->
			<span class="views experimental"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M3 17h16v2H1V1h2z"/><path d="M19 5v10H5v-1l4.5-5.5 3 3.5L18 5z"/></svg> 1.8K views</span>
			<u|2026-05-12T14:30:00Z|toolpage__when>
		</div>
		<div class="qv__desc" dir="auto"><p>Suggests reliable source templates, checks missing citations, and helps editors add references without leaving the page.</p></div>
		<div class="toolpage__glance"><span class="glance" dir="auto">web app</span><span class="glance" dir="auto">GPL-3.0-or-later</span><span class="glance" dir="auto">All wikis</span><span class="glance">4 languages</span></div>
		<div class="tcard__tags qv__tags"><a class="tag" href="/search?keywords__term=citations" dir="auto">citations</a><a class="tag" href="/search?keywords__term=references" dir="auto">references</a><a class="tag" href="/search?keywords__term=editing" dir="auto">editing</a><a class="tag" href="/search?keywords__term=quality" dir="auto">quality</a><a class="tag" href="/search?keywords__term=wikidata" dir="auto">wikidata</a><a class="tag" href="/search?keywords__term=sources" dir="auto">sources</a></div>
		<div class="qv__actions">
			<a class="btn btn--primary btn--md" href="https://example.org/tools/citation-helper" target="_blank" rel="noopener nofollow"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 7H3v10h10v-5h2v7H1V5h7z"/><path d="M19.001 2 19 8h-2V4.415l-9 9L6.586 12l9-8.999L12 3V1h6.001z"/></svg> Open tool</a>
			<a class="btn btn--outline btn--md" href="/tools/styleguide-citation-helper">View full page</a>
			
		</div></div></div>
		<figcaption class="sg-example__caption"><code>quickViewBody(tool)</code><span>organisms</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="sg-related-frame">
		<section class="related" aria-labelledby="sg-related-title">
			<div class="section-head"><h2 id="sg-related-title">Related tools</h2></div>
			<p class="related__subtitle">Overlapping function and scope, by shared metadata.</p>
			<div class="related__list">
				<article class="related__item" data-tool="osm-commons-map">
					<span class="avatar " style="background:var(--wmf-green-aaa)" aria-hidden="true">O</span>
					<div class="related__body">
						<button class="related__title" type="button" data-tool="osm-commons-map" aria-label="Quick look: OpenStreetMap Commons Map" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">OpenStreetMap Commons Map</button>
						<div class="related__maint">by <span dir="auto">Maps team</span></div>
						<div class="related__chips"><span class="tag">maps</span><span class="tag">OpenStreetMap</span><span class="tag">Commons</span></div>
					</div>
				</article>
			</div>
		</section>
	</div></div>
		<figcaption class="sg-example__caption"><code>Related tools (similarity)</code><span>organisms</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="sg-force-graph-frame">
		<div class="graph graph--sg">
			<div id="sg-force-graph" class="graph__canvas"></div>
			<div class="graph__legend" aria-label="Example graph legend">
				
		<span class="graph__legend-item"><span class="graph__swatch" style="background: LinkText"></span><span class="graph__legend-text">commons <span class="graph__legend-count">(3)</span></span></span>
		<span class="graph__legend-item"><span class="graph__swatch" style="background: LinkText"></span><span class="graph__legend-text">wikidata <span class="graph__legend-count">(3)</span></span></span>
				<span class="graph__legend-item"><span class="graph__swatch graph__swatch--halo"></span><span class="graph__legend-text">Fits you</span></span>
			</div>
		</div>
	</div></div>
		<figcaption class="sg-example__caption"><code>Similarity graph (canvas)</code><span>organisms</span></figcaption>
	</figure>
		</div>
	</section>
			<section class="sg-section" aria-labelledby="sg-activity-&amp;-parity">
		<h2 class="sg-section__title" id="sg-activity-&amp;-parity">Activity &amp; parity</h2>
		
		<div class="sg-examples sg-examples--organisms">
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><div class="mgrid">
		<div class="mcard"><span class="avatar " style="background:var(--wmf-blue-aaa)" aria-hidden="true">A</span><div class="mcard__b">
			<div class="mcard__n">Amina Hassan</div>
			<div class="mcard__c">Maintainer · joined 2024</div></div></div>
		<div class="mcard"><span class="avatar " style="background:var(--wmf-purple)" aria-hidden="true">J</span><div class="mcard__b">
			<div class="mcard__n">Jonas Klein</div>
			<div class="mcard__c">Member · joined 2023</div></div></div>
	</div></div>
		<figcaption class="sg-example__caption"><code>member card grid</code><span>parity views</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><ul class="feed">
		<li><a href="/tools/citation-helper"><svg class="icon feed__ic" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m15.765 7.875-8.483 8.484a1 1 0 01-.253.184l-4.214 2.15-1.357-1.33L3.58 13.12q.073-.145.188-.26l8.48-8.48zm3.534-3.532-2.12 2.118-3.517-3.496 2.13-2.13z"/></svg>
			<span class="feed__main"><strong>Citation Helper</strong> <span class="feed__sub">tool · Amina Hassan</span></span>
			<time class="feed__when" datetime="2026-06-24">5 minutes ago</time></a></li>
		<li><div class="feed__static"><svg class="icon feed__ic" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="m15.765 7.875-8.483 8.484a1 1 0 01-.253.184l-4.214 2.15-1.357-1.33L3.58 13.12q.073-.145.188-.26l8.48-8.48zm3.534-3.532-2.12 2.118-3.517-3.496 2.13-2.13z"/></svg>
			<span class="feed__main"><span>System</span> <em>changed</em> <span>list "Commons workflows"</span></span>
			<time class="feed__when" datetime="2026-06-23">yesterday</time></div></li>
	</ul></div>
		<figcaption class="sg-example__caption"><code>activity feed</code><span>parity views</span></figcaption>
	</figure>
			<figure class="sg-example sg-example--wide">
		<div class="sg-example__demo"><table class="runs">
		<caption class="skip-label">Recent crawler runs, newest first</caption>
		<thead><tr><th scope="col">Run</th><th scope="col">URLs</th><th scope="col">New</th><th scope="col">Updated</th><th scope="col">Total</th></tr></thead>
		<tbody>
			<tr><td><time datetime="2026-06-24">Jun 24, 2026</time></td><td>1,284</td><td>12</td><td>48</td><td>2,474</td></tr>
			<tr><td><time datetime="2026-06-23">Jun 23, 2026</time></td><td>1,280</td><td>7</td><td>35</td><td>2,462</td></tr>
		</tbody>
	</table></div>
		<figcaption class="sg-example__caption"><code>crawler runs table</code><span>parity views</span></figcaption>
	</figure>
		</div>
	</section>
		</div>`,
	tok_color: `<div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-surface)"></span>
			<span class="sg-token__meta"><code>--color-surface</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-surface-muted)"></span>
			<span class="sg-token__meta"><code>--color-surface-muted</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-surface-pattern)"></span>
			<span class="sg-token__meta"><code>--color-surface-pattern</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-row-hover)"></span>
			<span class="sg-token__meta"><code>--color-row-hover</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-overlay-modal)"></span>
			<span class="sg-token__meta"><code>--color-overlay-modal</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-badge-neutral)"></span>
			<span class="sg-token__meta"><code>--color-badge-neutral</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-border)"></span>
			<span class="sg-token__meta"><code>--color-border</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-border-hover)"></span>
			<span class="sg-token__meta"><code>--color-border-hover</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-border-accent)"></span>
			<span class="sg-token__meta"><code>--color-border-accent</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-text)"></span>
			<span class="sg-token__meta"><code>--color-text</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-text-secondary)"></span>
			<span class="sg-token__meta"><code>--color-text-secondary</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-text-muted)"></span>
			<span class="sg-token__meta"><code>--color-text-muted</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-progressive)"></span>
			<span class="sg-token__meta"><code>--color-progressive</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-progressive-hover)"></span>
			<span class="sg-token__meta"><code>--color-progressive-hover</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-progressive-subtle)"></span>
			<span class="sg-token__meta"><code>--color-progressive-subtle</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-interactive-subtle)"></span>
			<span class="sg-token__meta"><code>--color-interactive-subtle</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-hero-tint)"></span>
			<span class="sg-token__meta"><code>--color-hero-tint</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-favorite)"></span>
			<span class="sg-token__meta"><code>--color-favorite</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-success)"></span>
			<span class="sg-token__meta"><code>--color-success</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-success-subtle)"></span>
			<span class="sg-token__meta"><code>--color-success-subtle</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-destructive)"></span>
			<span class="sg-token__meta"><code>--color-destructive</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-destructive-subtle)"></span>
			<span class="sg-token__meta"><code>--color-destructive-subtle</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-warning)"></span>
			<span class="sg-token__meta"><code>--color-warning</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-warning-subtle)"></span>
			<span class="sg-token__meta"><code>--color-warning-subtle</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--color-warning-text)"></span>
			<span class="sg-token__meta"><code>--color-warning-text</code><span>v(backgroundColor)</span></span>
		</div>`,
	tok_layout: `<div class="sg-space-row sg-layout-row">
			<div class="sg-space-row__bar sg-space-row__bar--layout"><span style="width: min(100%, var(--container-wide))"></span></div>
			<div class="sg-space-row__meta"><code>--container-wide</code><span>v(maxWidth)</span></div>
		</div>`,
	tok_radius: `<div class="sg-token">
			<span class="sg-radius-box" style="border-radius: var(--radius-sm)"></span>
			<span class="sg-token__meta"><code>--radius-sm</code><span>v(borderRadius)</span></span>
		</div><div class="sg-token">
			<span class="sg-radius-box" style="border-radius: var(--radius-md)"></span>
			<span class="sg-token__meta"><code>--radius-md</code><span>v(borderRadius)</span></span>
		</div><div class="sg-token">
			<span class="sg-radius-box" style="border-radius: var(--radius-lg)"></span>
			<span class="sg-token__meta"><code>--radius-lg</code><span>v(borderRadius)</span></span>
		</div><div class="sg-token">
			<span class="sg-radius-box" style="border-radius: var(--radius-pill)"></span>
			<span class="sg-token__meta"><code>--radius-pill</code><span>v(borderRadius)</span></span>
		</div>`,
	tok_shadow: `<div class="sg-token">
			<span class="sg-shadow-box" style="box-shadow: var(--shadow)"></span>
			<span class="sg-token__meta"><code>--shadow</code><span>v(boxShadow)</span></span>
		</div><div class="sg-token">
			<span class="sg-shadow-box" style="box-shadow: var(--shadow-hover)"></span>
			<span class="sg-token__meta"><code>--shadow-hover</code><span>v(boxShadow)</span></span>
		</div><div class="sg-token">
			<span class="sg-shadow-box" style="box-shadow: var(--shadow-popover)"></span>
			<span class="sg-token__meta"><code>--shadow-popover</code><span>v(boxShadow)</span></span>
		</div><div class="sg-token">
			<span class="sg-shadow-box" style="box-shadow: var(--shadow-modal)"></span>
			<span class="sg-token__meta"><code>--shadow-modal</code><span>v(boxShadow)</span></span>
		</div><div class="sg-token">
			<span class="sg-shadow-box" style="box-shadow: var(--shadow-sm)"></span>
			<span class="sg-token__meta"><code>--shadow-sm</code><span>v(boxShadow)</span></span>
		</div>`,
	tok_space: `<div class="sg-space-row">
			<div class="sg-space-row__bar"><span style="width: var(--space-0)"></span></div>
			<div class="sg-space-row__meta"><code>--space-0</code><span>v(width)</span></div>
		</div><div class="sg-space-row">
			<div class="sg-space-row__bar"><span style="width: var(--space-1)"></span></div>
			<div class="sg-space-row__meta"><code>--space-1</code><span>v(width)</span></div>
		</div><div class="sg-space-row">
			<div class="sg-space-row__bar"><span style="width: var(--space-2)"></span></div>
			<div class="sg-space-row__meta"><code>--space-2</code><span>v(width)</span></div>
		</div><div class="sg-space-row">
			<div class="sg-space-row__bar"><span style="width: var(--space-3)"></span></div>
			<div class="sg-space-row__meta"><code>--space-3</code><span>v(width)</span></div>
		</div><div class="sg-space-row">
			<div class="sg-space-row__bar"><span style="width: var(--space-4)"></span></div>
			<div class="sg-space-row__meta"><code>--space-4</code><span>v(width)</span></div>
		</div><div class="sg-space-row">
			<div class="sg-space-row__bar"><span style="width: var(--space-5)"></span></div>
			<div class="sg-space-row__meta"><code>--space-5</code><span>v(width)</span></div>
		</div><div class="sg-space-row">
			<div class="sg-space-row__bar"><span style="width: var(--space-6)"></span></div>
			<div class="sg-space-row__meta"><code>--space-6</code><span>v(width)</span></div>
		</div><div class="sg-space-row">
			<div class="sg-space-row__bar"><span style="width: var(--space-7)"></span></div>
			<div class="sg-space-row__meta"><code>--space-7</code><span>v(width)</span></div>
		</div><div class="sg-space-row">
			<div class="sg-space-row__bar"><span style="width: var(--space-8)"></span></div>
			<div class="sg-space-row__meta"><code>--space-8</code><span>v(width)</span></div>
		</div>`,
	tok_type: `<div class="sg-type-row">
			<div class="sg-type-row__specimen" style="font-size: var(--fs-micro)">Toolhub Aa 123</div>
			<div class="sg-type-row__meta"><code>--fs-micro</code><span>v(fontSize)</span></div>
		</div><div class="sg-type-row">
			<div class="sg-type-row__specimen" style="font-size: var(--fs-small)">Toolhub Aa 123</div>
			<div class="sg-type-row__meta"><code>--fs-small</code><span>v(fontSize)</span></div>
		</div><div class="sg-type-row">
			<div class="sg-type-row__specimen" style="font-size: var(--fs-caption)">Toolhub Aa 123</div>
			<div class="sg-type-row__meta"><code>--fs-caption</code><span>v(fontSize)</span></div>
		</div><div class="sg-type-row">
			<div class="sg-type-row__specimen" style="font-size: var(--fs-body)">Toolhub Aa 123</div>
			<div class="sg-type-row__meta"><code>--fs-body</code><span>v(fontSize)</span></div>
		</div><div class="sg-type-row">
			<div class="sg-type-row__specimen" style="font-size: var(--fs-subtitle)">Toolhub Aa 123</div>
			<div class="sg-type-row__meta"><code>--fs-subtitle</code><span>v(fontSize)</span></div>
		</div><div class="sg-type-row">
			<div class="sg-type-row__specimen" style="font-size: var(--fs-title)">Toolhub Aa 123</div>
			<div class="sg-type-row__meta"><code>--fs-title</code><span>v(fontSize)</span></div>
		</div><div class="sg-type-row">
			<div class="sg-type-row__specimen" style="font-size: var(--fs-headline)">Toolhub Aa 123</div>
			<div class="sg-type-row__meta"><code>--fs-headline</code><span>v(fontSize)</span></div>
		</div><div class="sg-type-row">
			<div class="sg-type-row__specimen" style="font-size: var(--fs-display)">Toolhub Aa 123</div>
			<div class="sg-type-row__meta"><code>--fs-display</code><span>v(fontSize)</span></div>
		</div>`,
	tok_wmf: `<div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--wmf-white)"></span>
			<span class="sg-token__meta"><code>--wmf-white</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--wmf-green-aaa)"></span>
			<span class="sg-token__meta"><code>--wmf-green-aaa</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--wmf-blue-aaa)"></span>
			<span class="sg-token__meta"><code>--wmf-blue-aaa</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--wmf-red-aaa)"></span>
			<span class="sg-token__meta"><code>--wmf-red-aaa</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--wmf-orange)"></span>
			<span class="sg-token__meta"><code>--wmf-orange</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--wmf-yellow)"></span>
			<span class="sg-token__meta"><code>--wmf-yellow</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--wmf-purple)"></span>
			<span class="sg-token__meta"><code>--wmf-purple</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--wmf-red-light)"></span>
			<span class="sg-token__meta"><code>--wmf-red-light</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--wmf-orange-light)"></span>
			<span class="sg-token__meta"><code>--wmf-orange-light</code><span>v(backgroundColor)</span></span>
		</div><div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(--wmf-green-light)"></span>
			<span class="sg-token__meta"><code>--wmf-green-light</code><span>v(backgroundColor)</span></span>
		</div>`
};

function expect(name, actual) {
	if (BAKE) {
		fs.writeFileSync(`${SCRATCH}/styleguide__${name}.txt`, actual);
		return;
	}
	assert.equal(actual, S[name], name);
}

// resolveToken reads getComputedStyle(probe)[cssProp]; happy-dom returns "" for
// every property, which would make the per-family `prop` argument unobservable.
// Stub it to echo the requested property so token values reflect `prop`.
const realGetComputedStyle = globalThis.getComputedStyle;
const styleSheetsDescriptor = Object.getOwnPropertyDescriptor(document, "styleSheets");

beforeEach(() => {
	localStorage.clear();
	document.body.innerHTML = "";
	h.forceGraph.mockReset();
	globalThis.getComputedStyle = () =>
		new Proxy({}, { get: (_t, p) => (p === "getPropertyValue" ? () => "" : `v(${String(p)})`) });
});

afterEach(() => {
	globalThis.getComputedStyle = realGetComputedStyle;
	if (styleSheetsDescriptor) Object.defineProperty(document, "styleSheets", styleSheetsDescriptor);
});

test("viewStyleguide renders the full page", () => {
	const r = sg.viewStyleguide();
	assert.equal(r.title, "Design system — Toolhub");
	expect("page", r.html);
});

test("viewStyleguide output is deterministic", () => {
	assert.equal(sg.viewStyleguide().html, sg.viewStyleguide().html);
});

/* ---------------- mount ---------------- */

function mountStyleguide() {
	const r = sg.viewStyleguide();
	document.body.innerHTML = r.html;
	r.mount();
	return r;
}

test("mount renders all token galleries", () => {
	mountStyleguide();
	expect("tok_color", document.querySelector("#sg-color-tokens").innerHTML);
	expect("tok_wmf", document.querySelector("#sg-wmf-tokens").innerHTML);
	expect("tok_type", document.querySelector("#sg-type-tokens").innerHTML);
	expect("tok_radius", document.querySelector("#sg-radius-tokens").innerHTML);
	expect("tok_shadow", document.querySelector("#sg-shadow-tokens").innerHTML);
	expect("tok_space", document.querySelector("#sg-space-tokens").innerHTML);
	expect("tok_layout", document.querySelector("#sg-layout-tokens").innerHTML);
});

test("mount builds the example force graph with the exact fixture data", () => {
	h.forceGraph.mockReturnValue({ handle: 1 });
	mountStyleguide();
	assert.equal(h.forceGraph.mock.calls.length, 1);
	const [target, graph, opts] = h.forceGraph.mock.calls[0];
	assert.equal(target.id, "sg-force-graph");
	assert.deepEqual(opts, { height: 220 });
	assert.deepEqual(graph, {
		communityMeta: [
			{ id: 0, label: "commons", size: 3 },
			{ id: 1, label: "wikidata", size: 3 }
		],
		nodes: [
			{ id: "upload", title: "Commons Upload", community: 0, weight: 8, fits: true },
			{ id: "pattypan", title: "Pattypan", community: 0, weight: 6 },
			{ id: "map", title: "WLM Map", community: 0, weight: 5 },
			{ id: "query", title: "Query Helper", community: 1, weight: 7 },
			{ id: "reconcile", title: "Reconcile Tool", community: 1, weight: 5 },
			{ id: "citations", title: "Citation Helper", community: 1, weight: 4 }
		],
		edges: [
			{ source: "upload", target: "pattypan", weight: 0.82 },
			{ source: "upload", target: "map", weight: 0.68 },
			{ source: "pattypan", target: "map", weight: 0.55 },
			{ source: "query", target: "reconcile", weight: 0.78 },
			{ source: "query", target: "citations", weight: 0.52 },
			{ source: "map", target: "query", weight: 0.22 }
		]
	});
	assert.deepEqual(target.forceGraphHandle, { handle: 1 });
});

test("viewStyleguide seeds the fixture tools into INDEX", async () => {
	const { INDEX } = await import("../../public_html/lib/core/api.js");
	delete INDEX["styleguide-citation-helper"];
	sg.viewStyleguide();
	assert.ok(INDEX["styleguide-citation-helper"], "fixture tool seeded into INDEX");
	assert.equal(INDEX["styleguide-citation-helper"].title, "Citation Helper");
});

test("mount discovers custom properties from stylesheets (visitRules)", () => {
	// happy-dom's CSSStyleDeclaration is not iterable, so feed fake, iterable rules
	// (a top-level style rule + a nested @media-style rule) to exercise visitRules.
	Object.defineProperty(document, "styleSheets", {
		configurable: true,
		value: [
			{
				cssRules: [
					{ style: ["--color-from-sheet", "--other-ignored", "--color-surface"] },
					{ cssRules: [{ style: ["--color-nested"] }] },
					// processed after the at-rule: `if (!rule.style) return` must let the
					// nested rule fall through without aborting this later style rule.
					{ style: ["--color-after-nested"] }
				]
			}
		]
	});
	mountStyleguide();
	const colorHTML = document.querySelector("#sg-color-tokens").innerHTML;
	assert.ok(colorHTML.includes("--color-from-sheet"), "top-level rule property discovered");
	assert.ok(colorHTML.includes("--color-nested"), "nested rule property discovered (recursion)");
	assert.ok(colorHTML.includes("--color-after-nested"), "rule after the at-rule still processed");
	assert.ok(!colorHTML.includes("--other-ignored"), "non-matching prefix excluded");
	// --color-surface is in both the sheet and the fallback list → must appear once
	assert.equal(colorHTML.split("--color-surface<").length - 1, 1, "deduplicated across sheet + fallback");
	// every OTHER gallery uses a different prefix, so the --color-* sheet props must
	// NOT leak into them (this pins each collectCustomPropertyNames(prefix) argument)
	for (const id of [
		"#sg-wmf-tokens",
		"#sg-type-tokens",
		"#sg-radius-tokens",
		"#sg-shadow-tokens",
		"#sg-space-tokens",
		"#sg-layout-tokens"
	]) {
		assert.ok(!document.querySelector(id).innerHTML.includes("--color-from-sheet"), `${id} keeps its own prefix`);
	}
});

test("mount uses capture phase so demo widgets never see the intercepted events", () => {
	mountStyleguide();
	const toolEl = document.querySelector("[data-tool]");
	let toolHandlerRan = false;
	toolEl.addEventListener("click", () => {
		toolHandlerRan = true;
	});
	toolEl.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
	assert.equal(toolHandlerRan, false, "capture-phase stopPropagation blocks the element's own click handler");

	let keyHandlerRan = false;
	toolEl.addEventListener("keydown", () => {
		keyHandlerRan = true;
	});
	toolEl.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
	assert.equal(keyHandlerRan, false, "capture-phase stopPropagation blocks the element's own keydown handler");
});

test("mount: capture phase blocks an example form's own submit handler", () => {
	mountStyleguide();
	const form = document.querySelector(".sg-example form");
	let formHandlerRan = false;
	form.addEventListener("submit", () => {
		formHandlerRan = true;
	});
	form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
	assert.equal(formHandlerRan, false, "capture-phase stopPropagation blocks the form's own submit handler");
});

test("mount: a submit OUTSIDE any example is not intercepted", () => {
	mountStyleguide();
	const page = document.querySelector(".sg-page");
	const form = document.createElement("form");
	page.appendChild(form); // inside .sg-page but not inside a .sg-example
	const ev = new Event("submit", { bubbles: true, cancelable: true });
	form.dispatchEvent(ev);
	assert.equal(ev.defaultPrevented, false, "submit outside an example is left alone");
});

test("mount intercepts clicks on interactive demo elements", () => {
	mountStyleguide();
	const toolEl = document.querySelector("[data-tool]");
	const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
	toolEl.dispatchEvent(ev);
	assert.equal(ev.defaultPrevented, true, "data-tool click is prevented");
});

test("mount does not intercept clicks on inert elements", () => {
	mountStyleguide();
	const inert = document.querySelector(".sg-section__title");
	const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
	inert.dispatchEvent(ev);
	assert.equal(ev.defaultPrevented, false, "non-interactive click is not prevented");
});

test("mount intercepts Enter and Space on data-tool, but not other keys", () => {
	mountStyleguide();
	const toolEl = document.querySelector("[data-tool]");
	for (const key of ["Enter", " "]) {
		const ev = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
		toolEl.dispatchEvent(ev);
		assert.equal(ev.defaultPrevented, true, `${key} prevented`);
	}
	const other = new KeyboardEvent("keydown", { key: "a", bubbles: true, cancelable: true });
	toolEl.dispatchEvent(other);
	assert.equal(other.defaultPrevented, false, "other key not prevented");
});

test("mount intercepts form submits inside an example", () => {
	mountStyleguide();
	const form = document.querySelector(".sg-example form");
	const ev = new Event("submit", { bubbles: true, cancelable: true });
	form.dispatchEvent(ev);
	assert.equal(ev.defaultPrevented, true, "example form submit prevented");
});

test("mount is a no-op (no throw) when the styleguide page is absent", () => {
	document.body.innerHTML = "";
	const r = sg.viewStyleguide();
	// render nothing into the DOM, then call mount — the `if (!page) return` guard must hold
	assert.doesNotThrow(() => r.mount());
	assert.equal(h.forceGraph.mock.calls.length, 0, "no force graph without the page");
});
