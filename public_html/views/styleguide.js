// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc } from "../lib/core/dom.js";
import { INDEX } from "../lib/core/api.js";
import { DEMO_KEYS, DEMO_NS } from "../lib/core/store.js";
import { completeness, getUserContext, setUserContext } from "../lib/core/signals.js";
import { avatar, toolIcon } from "../lib/atoms/avatar.js";
import { completenessMeter, endorsementChip, fitChip, healthBadge, popularityBadge, statusBadge } from "../lib/atoms/badges.js";
import { button, iconButton } from "../lib/atoms/button.js";
import { TOOL_TYPES, fArea, fCheck, fInput, fSelect } from "../lib/atoms/form-fields.js";
import { ICON_NAMES, icon } from "../lib/atoms/icon.js";
import { glanceChips, keywordTags, linkOut, metaItem, wikiLabel } from "../lib/atoms/labels.js";
import { reviewsBlock, usageBlock } from "../lib/atoms/signals.js";
import { renderFacetGroup } from "../lib/molecules/facet-group.js";
import { favBtn } from "../lib/molecules/favbtn.js";
import { renderPager } from "../lib/molecules/pager.js";
import { saveToListControl } from "../lib/molecules/savemenu.js";
import { communityColors, forceGraph } from "../lib/organisms/force-graph.js";
import { grid } from "../lib/organisms/grid.js";
import { listCard } from "../lib/organisms/list-card.js";
import { quickViewBody } from "../lib/organisms/quickview.js";
import { toolCard } from "../lib/organisms/tool-card.js";
import {
	FIXTURE_FACET_GROUP,
	FIXTURE_FACETS,
	FIXTURE_LIST,
	FIXTURE_SELECTED_FACETS,
	FIXTURE_TOOL,
	FIXTURE_TOOL_DEPRECATED,
	FIXTURE_TOOL_EXPERIMENTAL,
} from "./_fixtures.js";

const STYLEGUIDE_TOOLS = [FIXTURE_TOOL, FIXTURE_TOOL_DEPRECATED, FIXTURE_TOOL_EXPERIMENTAL];
const STYLEGUIDE_ACCOUNT_NAME = "Amina Hassan";
const STYLEGUIDE_GRAPH = {
	communityMeta: [
		{ id: 0, label: "commons", size: 3 },
		{ id: 1, label: "wikidata", size: 3 },
	],
	nodes: [
		{ id: "upload", title: "Commons Upload", community: 0, weight: 8, fits: true },
		{ id: "pattypan", title: "Pattypan", community: 0, weight: 6 },
		{ id: "map", title: "WLM Map", community: 0, weight: 5 },
		{ id: "query", title: "Query Helper", community: 1, weight: 7 },
		{ id: "reconcile", title: "Reconcile Tool", community: 1, weight: 5 },
		{ id: "citations", title: "Citation Helper", community: 1, weight: 4 },
	],
	edges: [
		{ source: "upload", target: "pattypan", weight: 0.82 },
		{ source: "upload", target: "map", weight: 0.68 },
		{ source: "pattypan", target: "map", weight: 0.55 },
		{ source: "query", target: "reconcile", weight: 0.78 },
		{ source: "query", target: "citations", weight: 0.52 },
		{ source: "map", target: "query", weight: 0.22 },
	],
};

const FALLBACK_TOKENS = {
	colors: [
		"--color-surface", "--color-surface-muted", "--color-surface-pattern", "--color-row-hover",
		"--color-overlay-modal", "--color-badge-neutral", "--color-border", "--color-border-hover",
		"--color-border-accent", "--color-text", "--color-text-secondary", "--color-text-muted",
		"--color-progressive", "--color-progressive-hover", "--color-progressive-subtle",
		"--color-interactive-subtle", "--color-hero-tint", "--color-favorite", "--color-success",
		"--color-success-subtle", "--color-destructive", "--color-destructive-subtle", "--color-warning",
		"--color-warning-subtle", "--color-warning-text",
	],
	wmf: [
		"--wmf-white", "--wmf-green-aaa", "--wmf-blue-aaa", "--wmf-red-aaa", "--wmf-orange",
		"--wmf-yellow", "--wmf-purple", "--wmf-red-light", "--wmf-orange-light", "--wmf-green-light",
	],
	fs: ["--fs-micro", "--fs-small", "--fs-caption", "--fs-body", "--fs-subtitle", "--fs-title", "--fs-headline", "--fs-display"],
	layout: ["--container-wide"],
	radius: ["--radius-sm", "--radius-md", "--radius-lg", "--radius-pill"],
	shadow: ["--shadow", "--shadow-hover", "--shadow-popover", "--shadow-modal", "--shadow-sm"],
	space: ["--space-0", "--space-1", "--space-2", "--space-3", "--space-4", "--space-5", "--space-6", "--space-7", "--space-8"],
};

function seedFixtureIndex() {
	STYLEGUIDE_TOOLS.forEach((tool) => { INDEX[tool.name] = tool; });
}

function withStyleguideDemoState(render) {
	if (typeof localStorage === "undefined") return render();
	const favKey = DEMO_NS + DEMO_KEYS.favorites;
	const listsKey = DEMO_NS + DEMO_KEYS.lists;
	const prevFavs = localStorage.getItem(favKey);
	const prevLists = localStorage.getItem(listsKey);
	const lists = [
		{
			id: "demo-styleguide-campaign",
			title: FIXTURE_LIST.title,
			description: FIXTURE_LIST.description,
			tools: [FIXTURE_TOOL.name, FIXTURE_TOOL_EXPERIMENTAL.name],
		},
		{
			id: "demo-styleguide-review",
			title: "Review queue",
			description: "Tools saved for later evaluation.",
			tools: [FIXTURE_TOOL_DEPRECATED.name],
		},
	];
	try {
		localStorage.setItem(favKey, JSON.stringify([FIXTURE_TOOL_DEPRECATED.name]));
		localStorage.setItem(listsKey, JSON.stringify(lists));
		return render();
	} finally {
		if (prevFavs == null) localStorage.removeItem(favKey);
		else localStorage.setItem(favKey, prevFavs);
		if (prevLists == null) localStorage.removeItem(listsKey);
		else localStorage.setItem(listsKey, prevLists);
	}
}

function fitChipExample() {
	const prev = getUserContext();
	const fittingTool = { ...FIXTURE_TOOL, audiences: ["editor"], forWikis: ["wikidata.org"] };
	setUserContext({ wiki: "wikidata.org", role: "editor" });
	try {
		return fitChip(fittingTool) || `<span class="signal signal--fit">${icon("check")} Fits you</span>`;
	} finally {
		setUserContext(prev);
	}
}

function listingCompletenessExample() {
	const complete = completeness(FIXTURE_TOOL);
	const rows = complete.items.map((item) => `
		<li><span class="complete-list__icon${item.ok ? "" : " complete-list__icon--empty"}">${item.ok ? icon("check") : "○"}</span><span>${esc(item.label)}</span></li>`).join("");
	return `<div class="panel">
		<h3 class="panel__title">Listing completeness</h3>
		${completenessMeter(complete)}
		<ul class="complete-list">${rows}</ul>
	</div>`;
}

function fitControlExample() {
	return `<form class="intent">
		<div class="intent__sentence" aria-label="Build a tool search">
			<span class="intent__copy">I want to see tools</span>
			<span class="intent__choice"><button class="intent__word" type="button" aria-haspopup="menu" aria-expanded="false"><span>made for</span></button></span>
			<span class="intent__choice"><button class="intent__word" type="button" aria-haspopup="menu" aria-expanded="false"><span>editors</span></button></span>
			<span class="intent__copy">on</span>
			<span class="intent__choice"><button class="intent__word" type="button" aria-haspopup="menu" aria-expanded="false"><span>Wikidata</span></button></span>
			<button class="intent__go" type="submit">See tools</button>
			<button class="intent__clear" type="button">clear</button>
		</div>
	</form>`;
}

function fullHeroIntentExample() {
	return `<form class="intent">
		<div class="intent__sentence" aria-label="Build a tool search">
			<span class="intent__copy">I want to see tools</span>
			<span class="intent__choice"><button class="intent__word" type="button" aria-haspopup="menu" aria-expanded="false"><span>made for</span></button></span>
			<span class="intent__choice"><button class="intent__word" type="button" aria-haspopup="menu" aria-expanded="false"><span>anyone</span></button></span>
			<span class="intent__copy">on</span>
			<span class="intent__choice"><button class="intent__word" type="button" aria-haspopup="menu" aria-expanded="false"><span>any project</span></button></span>
			<button class="intent__go" type="submit">See tools</button>
			<button class="intent__clear" type="button" disabled>clear</button>
		</div>
	</form>`;
}

function accountButtonExample() {
	return `<div class="acct">
		<button class="acct__btn" id="sg-acct-btn" type="button" aria-haspopup="true" aria-expanded="false" aria-controls="sg-acct-menu">
			${avatar(STYLEGUIDE_ACCOUNT_NAME, "avatar--sm")}
			<span class="acct__name">${esc(STYLEGUIDE_ACCOUNT_NAME)}</span>
			${icon("chevronDown", "acct__caret")}
		</button>
	</div>`;
}

function experimentsToggleExample() {
	return `<div class="sg-inline-list">
		<button class="exp-toggle" type="button" role="switch" aria-checked="true">
			<span class="exp-toggle__track"><span class="exp-toggle__thumb"></span></span>
			<span class="exp-toggle__label">Prospective features on</span>
		</button>
		<button class="exp-toggle" type="button" role="switch" aria-checked="false">
			<span class="exp-toggle__track"><span class="exp-toggle__thumb"></span></span>
			<span class="exp-toggle__label">Prospective features off</span>
		</button>
	</div>`;
}

function quickViewCloseExample() {
	return `<div class="sg-qv-close-frame">
		<button class="qv__x" type="button" aria-label="Close quick view">${icon("close")}</button>
	</div>`;
}

function listEditorControlsExample() {
	return `<div class="sg-control-stack">
		<h2 class="le__h2">Tools <span class="le__count">2 tools</span></h2>
		<p class="le__ro">Name: <code>commons-upload-helper</code></p>
		<div class="le__add">
			<input class="le__input" type="search" placeholder="Search tools to add..." autocomplete="off" />
			${button("Add", { variant: "outline" })}
		</div>
		<div class="le__results">
			<button class="le__result" type="button">${icon("add")} <span>Wiki Loves Monuments map</span></button>
			<button class="le__result is-in" type="button" disabled>${icon("check")} <span>Commons Pattypan</span></button>
		</div>
		<p class="le__searching">Searching...</p>
		<ol class="le__tools">
			<li data-tn="citation-helper"><span class="le__tn"${dirAttrs("citation-helper")}>citation-helper</span>
				<span class="le__rowact">
					${iconButton("chevronUp", "Move up", { size: "sm", attrs: 'data-move="up"' })}
					${iconButton("chevronDown", "Move down", { size: "sm", attrs: 'data-move="down"' })}
					${iconButton("close", "Remove from list", { size: "sm", variant: "danger", attrs: "data-rm" })}
				</span>
			</li>
			<li class="le__empty">No more tools in this list.</li>
		</ol>
		<div class="le__actions">
			${button("Save list", { variant: "primary" })}
			${button("Delete list", { variant: "danger", cls: "le__delete" })}
		</div>
	</div>`;
}

function navIconButtonExample() {
	return `<a class="icon-btn" href="/search">${icon("search")} Search</a>`;
}

function relatedToolsExample() {
	const t = {
		name: "osm-commons-map",
		title: "OpenStreetMap Commons Map",
		maintainer: "Maps team",
	};
	const chips = ["maps", "OpenStreetMap", "Commons"].map((label) => `<span class="tag">${esc(label)}</span>`).join("");
	return `<div class="sg-related-frame">
		<section class="related" aria-labelledby="sg-related-title">
			<div class="section-head"><h2 id="sg-related-title">Related tools</h2></div>
			<p class="related__subtitle">Overlapping function and scope, by shared metadata.</p>
			<div class="related__list">
				<article class="related__item" data-tool="${esc(t.name)}" role="button" tabindex="0" aria-label="Quick look: ${esc(t.title)}">
					${avatar(t.title)}
					<div class="related__body">
						<div class="related__title"${dirAttrs(t.title)}>${esc(t.title)}</div>
						<div class="related__maint">by <span${dirAttrs(t.maintainer)}>${esc(t.maintainer)}</span></div>
						<div class="related__chips">${chips}</div>
					</div>
				</article>
			</div>
		</section>
	</div>`;
}

function forceGraphExample() {
	const colors = communityColors(STYLEGUIDE_GRAPH.communityMeta);
	const legend = STYLEGUIDE_GRAPH.communityMeta.map((community) => `
		<span class="graph__legend-item"><span class="graph__swatch" style="background: ${esc(colors.get(community.id))}"></span><span class="graph__legend-text">${esc(community.label)} <span class="graph__legend-count">(${esc(String(community.size))})</span></span></span>`).join("");
	return `<div class="sg-force-graph-frame">
		<div class="graph graph--sg">
			<div id="sg-force-graph" class="graph__canvas"></div>
			<div class="graph__legend" aria-label="Example graph legend">
				${legend}
				<span class="graph__legend-item"><span class="graph__swatch graph__swatch--halo"></span><span class="graph__legend-text">Fits you</span></span>
			</div>
		</div>
	</div>`;
}

function chromeNavExample() {
	return `<div class="sg-chrome-frame">
		<header class="nav">
			<div class="nav__inner">
				<a class="brand" href="/">
					<img class="brand__logo" src="img/toolhub-logo.svg?v=2" alt="" width="34" height="34" />
					<span class="brand__name">Toolhub</span>
				</a>
				<nav class="nav__links" aria-label="Primary">
					<a href="/search">Browse</a>
					<a href="/lists">Lists</a>
					<a href="/search">Categories</a>
				</nav>
				<div class="nav__actions">
					<a class="icon-btn" href="/search">${icon("search")} Search</a>
					${button("Submit a tool", { variant: "primary", href: "https://toolhub.wikimedia.org/add-or-remove-tools?tab=tool-create", icon: "add", attrs: 'target="_blank" rel="noopener nofollow"' })}
					${accountButtonExample()}
				</div>
			</div>
		</header>
	</div>`;
}

function footerExample() {
	return `<div class="sg-chrome-frame">
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
					<a href="https://phabricator.wikimedia.org/tag/toolhub/" target="_blank" rel="noopener nofollow">Report an issue ${icon("external")}</a>
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
				<a class="footer__maintain" href="/contribute">${icon("tools")} Help maintain Toolhub</a>
				<span class="footer__legal">Catalog content under <a href="https://creativecommons.org/publicdomain/zero/1.0/" target="_blank" rel="noopener nofollow">CC0</a> · <a href="https://github.com/schiste/toolhub-evolved" target="_blank" rel="noopener nofollow">Toolhub Evolved v0.1.0</a></span>
				<span class="footer__note">Prototype · live read-only data from the Toolhub API</span>
			</div>
		</footer>
	</div>`;
}

function mockupBannerExample() {
	return `<div class="sg-chrome-frame sg-chrome-frame--tight">
		<div class="mockup-banner" role="region" aria-label="Prototype notice">
			<span class="mockup-banner__txt"><span aria-hidden="true">!</span> Mockup - a prototype, not a working integration with the real Toolhub. <span class="mock-tag">Demo</span></span>
			<a class="mockup-banner__link" href="/experiments">Experimental features</a>
			<a class="mockup-banner__link" href="/rules-of-engagement">Rules of Engagement</a>
		</div>
	</div>`;
}

function experimentsBarExample() {
	return `<div class="sg-chrome-frame sg-chrome-frame--tight">
		<div class="expbar">
			<div class="container expbar__inner">
				<button class="exp-toggle" type="button" role="switch" aria-checked="false">
					<span class="exp-toggle__track"><span class="exp-toggle__thumb"></span></span>
					<span class="exp-toggle__label">Show me prospective features</span>
				</button>
			</div>
		</div>
	</div>`;
}

function fullHeroExample() {
	return `<div class="sg-hero-frame">
		<section class="hero">
			<h1 class="hero__title">The community catalog of Wikimedia tools</h1>
			<div class="hero__explore">
				${fullHeroIntentExample()}
			</div>
			<div class="hero__or" aria-hidden="true">or</div>
			<form class="search" role="search">
				<label for="sg-home-q" class="skip-label">Search tools</label>
				<input id="sg-home-q" class="search__input" type="search" aria-label="Search tools" placeholder="Search 2,474 tools..." autocomplete="off" />
				${button("Search", { variant: "primary", type: "submit", cls: "search__btn" })}
			</form>
		</section>
	</div>`;
}

function pageHeaderExample() {
	return `<div class="page sg-page-demo">
		<h1 class="page__title">Browse tools</h1>
		<p class="page__intro">Search, filter, and compare tools maintained by the Wikimedia community.</p>
		<div class="section-head"><h2>Featured tools</h2><a class="link" href="/search">View all</a></div>
	</div>`;
}

function layoutExample() {
	return `<div class="layout sg-layout-demo">
		<div class="layout__main">
			<div class="section-head"><h2>Main content</h2><a class="link" href="/search">View all</a></div>
			<div class="sg-schematic">Cards, search results, or detail content</div>
		</div>
		<aside class="layout__side">
			<div class="panel"><h3 class="panel__title">Sidebar</h3><p class="sg-note">Panels and supporting navigation.</p></div>
		</aside>
	</div>`;
}

function backAndLinkExample() {
	return `<div class="sg-control-stack">
		<a class="back" href="/search">← Back to tools</a>
		<a class="link" href="/lists">View all lists</a>
	</div>`;
}

function emptyStateExample() {
	return `<p class="empty">No tools match these filters.</p>`;
}

function loadingExample() {
	return `<div class="loading sg-loading-demo" role="status" aria-live="polite">
		<span class="spinner" aria-hidden="true"></span><span class="skip-label">Loading</span>
	</div>`;
}

function errorPageExample() {
	return `<div class="errorpage sg-error-demo">
		<h1>Couldn't load live data</h1>
		<p class="prose">The Toolhub API didn't respond. Try again from the browse page.</p>
		${button("Go to the home page", { variant: "primary", href: "/" })}
	</div>`;
}

function proseExample() {
	return `<article class="prose prose--page">
		<h1>About Toolhub</h1>
		<p>Toolhub helps Wikimedians discover software used across editing, maintenance, analysis, and community workflows.</p>
		<p><a href="/contribute">Help maintain Toolhub</a> by improving listings or reporting gaps.</p>
	</article>`;
}

function signInNoteExample() {
	return `<p class="signin-note">In this prototype these actions are read-only: they need an authenticated session and the live back-end.</p>`;
}

function metaExample() {
	return `<div class="detail__meta">
		${metaItem("License", FIXTURE_TOOL.license)}
		${metaItem("Wikis", wikiLabel(FIXTURE_TOOL.forWikis))}
		${metaItem("Maintainer", FIXTURE_TOOL.maintainer)}
		${metaItem("Tool type", FIXTURE_TOOL.toolType)}
	</div>`;
}

function sortControlExample() {
	return `<label class="sort"><span class="skip-label">Sort by</span><select>
		<option>Most relevant</option>
		<option>Recently updated</option>
		<option>Name</option>
	</select></label>`;
}

function recentListExample() {
	return `<ul class="recent">
		<li><a href="/tools/citation-helper">${avatar("Citation Helper")}
			<div><div class="recent__title">Citation Helper</div>
			<div class="recent__meta">Maintainer: <span>Editing team</span></div></div>
			<time class="recent__when" datetime="2026-06-23">${icon("history")} yesterday</time></a></li>
		<li><a href="/tools/commons-upload">${avatar("Commons Upload")}
			<div><div class="recent__title">Commons Upload</div>
			<div class="recent__meta">Maintainer: <span>Commons volunteers</span></div></div>
			<time class="recent__when" datetime="2026-06-21">${icon("history")} 3 days ago</time></a></li>
	</ul>`;
}

function panelVariantsExample() {
	return `<div class="sg-panel-pair">
		<div class="panel">
			<h3 class="panel__title">Recently updated</h3>
			<p class="sg-note">Borderless sidebar block with a ruled title.</p>
			<a class="panel__foot" href="/recent">View recent changes</a>
		</div>
		<div class="panel panel--cta">
			<div class="cta__icon" aria-hidden="true">${icon("idea", "icon--lg")}</div>
			<h3>Built a tool for Wikimedia?</h3>
			<p>Add a <code>toolinfo.json</code> to your repository so other Wikimedians can find it.</p>
			${button("Submit a tool", { variant: "outline", href: "https://toolhub.wikimedia.org/add-or-remove-tools?tab=tool-create" })}
		</div>
	</div>`;
}

function linkCardsExample() {
	return `<div class="linkgrid">
		<a class="linkcard" href="/contribute">
			<span class="linkcard__icon" aria-hidden="true">${icon("report")}</span>
			<span class="linkcard__body"><span class="linkcard__title">Report a bug</span>
			<span class="linkcard__desc">Open a task on the Toolhub board.</span></span>
		</a>
		<a class="linkcard" href="/api-docs">
			<span class="linkcard__icon" aria-hidden="true">${icon("code")}</span>
			<span class="linkcard__body"><span class="linkcard__title">API documentation</span>
			<span class="linkcard__desc">Inspect live read-only endpoints.</span></span>
		</a>
	</div>`;
}

function browseBarExample() {
	return `<div class="browse sg-browse-demo">
		<aside class="facets">
			<input class="facets__search" type="search" placeholder="Search filters" />
		</aside>
		<div class="browse__main">
			<div class="browse__bar">
				<span class="browse__count" aria-live="polite">142 tools for "Commons"</span>
				${sortControlExample()}
			</div>
			<p class="empty">Results render below this control row.</p>
		</div>
	</div>`;
}

function maintainerListExample() {
	return `<ul class="maint-list">
		<li>${avatar("Amina Hassan")} <span>Amina Hassan</span></li>
		<li>${avatar("Maps team")} <span>Maps team</span></li>
	</ul>`;
}

function annotationEditorExample() {
	return `<div class="sg-control-stack">
		<form class="le__add">
			<input class="le__input" type="url" placeholder="https://example.org/toolinfo.json" />
			${button("Register", { variant: "outline", type: "submit" })}
		</form>
		<ul class="at__urls">
			<li><code class="at__url">https://example.org/toolinfo.json</code> ${iconButton("close", "Remove URL", { size: "sm", cls: "at__rm" })}</li>
		</ul>
		<textarea class="le__input at__json" rows="4" placeholder='{ "name": "my-tool", "title": "My Tool" }'></textarea>
		<p class="at__result at__result--ok">1 added, 2 updated</p>
		<p class="at__result at__result--err">Invalid JSON: expected a tool object.</p>
	</div>`;
}

function memberGridExample() {
	return `<div class="mgrid">
		<div class="mcard">${avatar("Amina Hassan")}<div class="mcard__b">
			<div class="mcard__n">Amina Hassan</div>
			<div class="mcard__c">Maintainer · joined 2024</div></div></div>
		<div class="mcard">${avatar("Jonas Klein")}<div class="mcard__b">
			<div class="mcard__n">Jonas Klein</div>
			<div class="mcard__c">Member · joined 2023</div></div></div>
	</div>`;
}

function activityFeedExample() {
	return `<ul class="feed">
		<li><a href="/tools/citation-helper">${icon("edit", "feed__ic")}
			<span class="feed__main"><strong>Citation Helper</strong> <span class="feed__sub">tool · Amina Hassan</span></span>
			<time class="feed__when" datetime="2026-06-24">5 minutes ago</time></a></li>
		<li><div class="feed__static">${icon("edit", "feed__ic")}
			<span class="feed__main"><span>System</span> <em>changed</em> <span>list "Commons workflows"</span></span>
			<time class="feed__when" datetime="2026-06-23">yesterday</time></div></li>
	</ul>`;
}

function runsExample() {
	return `<table class="runs">
		<caption class="skip-label">Recent crawler runs, newest first</caption>
		<thead><tr><th scope="col">Run</th><th scope="col">URLs</th><th scope="col">New</th><th scope="col">Updated</th><th scope="col">Total</th></tr></thead>
		<tbody>
			<tr><td><time datetime="2026-06-24">Jun 24, 2026</time></td><td>1,284</td><td>12</td><td>48</td><td>2,474</td></tr>
			<tr><td><time datetime="2026-06-23">Jun 23, 2026</time></td><td>1,280</td><td>7</td><td>35</td><td>2,462</td></tr>
		</tbody>
	</table>`;
}

function section(title, body) {
	return `<section class="sg-section" aria-labelledby="sg-${esc(title.toLowerCase().replace(/\s+/g, "-"))}">
		<h2 class="sg-section__title" id="sg-${esc(title.toLowerCase().replace(/\s+/g, "-"))}">${esc(title)}</h2>
		${body}
	</section>`;
}

function example(name, layer, html, opts) {
	opts = opts || {};
	const shown = html || '<span class="sg-empty">No visual markup in this state.</span>';
	return `<figure class="sg-example${opts.wide ? " sg-example--wide" : ""}${opts.compact ? " sg-example--compact" : ""}">
		<div class="sg-example__demo">${shown}</div>
		<figcaption class="sg-example__caption"><code>${esc(name)}</code><span>${esc(layer)}</span></figcaption>
	</figure>`;
}

function tokenSection() {
	return section("Tokens", `
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
		</div>`);
}

function buttonsSection() {
	return section("Buttons", `
		<div class="sg-examples sg-examples--buttons">
			${example("button('Primary', { variant: 'primary' })", "atoms", button("Primary", { variant: "primary" }))}
			${example("button('Outline', { variant: 'outline' })", "atoms", button("Outline", { variant: "outline" }))}
			${example("button('Subtle', { variant: 'subtle' })", "atoms", button("Subtle", { variant: "subtle" }))}
			${example("button('Danger', { variant: 'danger' })", "atoms", button("Danger", { variant: "danger" }))}
			${example("button('Small', { variant: 'primary', size: 'sm' })", "atoms", button("Small", { variant: "primary", size: "sm" }))}
			${example("button('Medium', { variant: 'primary', size: 'md' })", "atoms", button("Medium", { variant: "primary", size: "md" }))}
			${example("button('Large', { variant: 'primary', size: 'lg' })", "atoms", button("Large", { variant: "primary", size: "lg" }))}
			${example("button('Add tool', { variant: 'primary', icon: 'add' })", "atoms", button("Add tool", { variant: "primary", icon: "add" }))}
			${example("button('Edit', { variant: 'outline', icon: 'edit' })", "atoms", button("Edit", { variant: "outline", icon: "edit" }))}
			${example("button('Browse', { variant: 'outline', href: '/search' })", "atoms", button("Browse", { variant: "outline", href: "/search" }))}
			${example("button('Disabled', { variant: 'primary', disabled: true })", "atoms", button("Disabled", { variant: "primary", disabled: true }))}
			${example("iconButton('chevronUp', 'Move up', { size: 'sm' })", "atoms", iconButton("chevronUp", "Move up", { size: "sm" }))}
			${example("iconButton('chevronDown', 'Move down', { size: 'sm' })", "atoms", iconButton("chevronDown", "Move down", { size: "sm" }))}
			${example("iconButton('close', 'Close', { size: 'sm' })", "atoms", iconButton("close", "Close", { size: "sm" }))}
			${example("iconButton('close', 'Remove', { size: 'sm', variant: 'danger' })", "atoms", iconButton("close", "Remove", { size: "sm", variant: "danger" }))}
			${example("iconButton('search', 'Search')", "atoms", iconButton("search", "Search"))}
		</div>`);
}

function iconsSection() {
	return section("Icons", `
		<div class="sg-token-grid">
			${ICON_NAMES.map((name) => `<div class="sg-token">
				${icon(name, "icon--lg")}
				<span class="sg-token__meta"><code>${esc(name)}</code></span>
			</div>`).join("")}
		</div>`);
}

function chromeSection() {
	return section("Chrome", `
		<div class="sg-examples sg-examples--organisms">
			${example("Nav + brand", "app chrome", chromeNavExample(), { wide: true })}
			${example("Footer", "app chrome", footerExample(), { wide: true })}
			${example("Mockup banner + mock tag", "app chrome", mockupBannerExample(), { wide: true, compact: true })}
			${example("Experiments bar", "app chrome", experimentsBarExample(), { wide: true, compact: true })}
			${example("Full hero block", "app chrome / organism", fullHeroExample(), { wide: true })}
		</div>`);
}

function layoutStatesSection() {
	return section("Layout & states", `
		<div class="sg-examples sg-examples--organisms">
			${example("Page header + section head", "templates", pageHeaderExample(), { wide: true })}
			${example("Two-column layout", "templates", layoutExample(), { wide: true })}
			${example("Back link + text link", "templates", backAndLinkExample())}
			${example("Empty state", "templates", emptyStateExample())}
			${example("Loading spinner", "templates", loadingExample())}
			${example("Error page", "templates", errorPageExample(), { wide: true })}
			${example("Prose page", "templates", proseExample(), { wide: true })}
			${example("Sign-in note", "molecules", signInNoteExample(), { wide: true })}
		</div>`);
}

function formControlsGroup() {
	return `<div class="sg-group">
		<h3 class="sg-group__title">Form controls</h3>
		<p class="sg-group__note">Standalone search, facet, list-editor, and intent-builder controls now share one control foundation.</p>
		<div class="sg-examples sg-examples--controls">
			${example("input.search__input", "atoms / shared control foundation", '<input class="search__input" id="sg-search-input" type="search" placeholder="Search tools..." autocomplete="off" />')}
			${example("input.facets__search", "atoms / shared control foundation", '<input class="facets__search" id="sg-facet-search" type="search" placeholder="Search tools..." autocomplete="off" />')}
			${example("input.le__input", "atoms / shared control foundation", '<input class="le__input" id="sg-list-editor-input" type="text" placeholder="List title" />')}
			${example("button.intent__word", "atoms / editable phrase", '<button class="intent__word" type="button">Wikidata</button>')}
		</div>
	</div>`;
}

function atomsSection() {
	return section("Atoms", `
		<div class="sg-examples">
			${example("avatar(title)", "atoms", avatar("Citation Helper"))}
			${example('toolIcon(tool, "lg")', "atoms", toolIcon(FIXTURE_TOOL, "lg"))}
			${example("statusBadge(healthy)", "atoms", statusBadge(FIXTURE_TOOL))}
			${example("statusBadge(deprecated)", "atoms", statusBadge(FIXTURE_TOOL_DEPRECATED))}
			${example("statusBadge(experimental)", "atoms", statusBadge(FIXTURE_TOOL_EXPERIMENTAL))}
			${example("healthBadge(tool)", "atoms", healthBadge(FIXTURE_TOOL))}
			${example("popularityBadge(tool)", "atoms", popularityBadge(FIXTURE_TOOL))}
			${example("endorsementChip(5)", "atoms", endorsementChip(5))}
			${example("completenessMeter({ filled: 7, total: 9 })", "atoms", completenessMeter({ filled: 7, total: 9 }))}
			${example("completenessMeter({ filled: 9, total: 9 })", "atoms", completenessMeter({ filled: 9, total: 9 }))}
			${example("fitChip(tool)", "atoms", fitChipExample())}
			${example("reviewsBlock(tool)", "atoms", reviewsBlock(FIXTURE_TOOL))}
			${example("usageBlock(tool)", "atoms", usageBlock(FIXTURE_TOOL))}
			${example("keywordTags(tool)", "atoms", `<div class="sg-inline-list">${keywordTags(FIXTURE_TOOL)}</div>`, { wide: true })}
			${example("glanceChips(tool)", "atoms", `<div class="sg-inline-list">${glanceChips(FIXTURE_TOOL)}</div>`, { wide: true })}
			${example("fInput / fArea / fCheck / fSelect", "atoms", `<div class="sg-form">
				${fInput("Tool title", "sg-tool-title", FIXTURE_TOOL.title, { req: true })}
				${fArea("Description", "sg-tool-description", FIXTURE_TOOL.description, "Shown in search results and detail pages.")}
				<div class="le__checks">${fCheck("Experimental", "sg-tool-experimental", true)}${fCheck("Deprecated", "sg-tool-deprecated", false)}</div>
				${fSelect("Tool type", "sg-tool-type", FIXTURE_TOOL.toolType, TOOL_TYPES)}
			</div>`, { wide: true })}
			${formControlsGroup()}
			${example("metaItem(key, value)", "atoms", `<div class="detail__meta">${metaItem("License", FIXTURE_TOOL.license)}${metaItem("Wikis", wikiLabel(FIXTURE_TOOL.forWikis))}</div>`, { wide: true })}
			${example("linkOut(label, url)", "atoms", linkOut("Repository", FIXTURE_TOOL.repository))}
		</div>`);
}

function moleculesSection() {
	return section("Molecules", `
		<div class="sg-examples">
			${example("favBtn(name)", "molecules", favBtn(FIXTURE_TOOL.name, { label: true }))}
			${example("favBtn(savedName)", "molecules", favBtn(FIXTURE_TOOL_DEPRECATED.name, { label: true }))}
			${example("saveToListControl(name)", "molecules", saveToListControl(FIXTURE_TOOL.name), { wide: true })}
			${example("renderFacetGroup(group, facets, selected)", "molecules", renderFacetGroup(FIXTURE_FACET_GROUP, FIXTURE_FACETS, FIXTURE_SELECTED_FACETS), { wide: true })}
			${example("renderPager(2, 7)", "molecules", `<nav class="pager" aria-label="Pagination">${renderPager(2, 7)}</nav>`, { wide: true })}
			${example(".acct__btn", "molecules", accountButtonExample())}
			${example(".exp-toggle", "organisms", experimentsToggleExample(), { wide: true })}
			${example(".qv__x", "organisms", quickViewCloseExample())}
			${example("Annotation editor controls", "molecules", annotationEditorExample(), { wide: true })}
			${example("List editor full row", "molecules", listEditorControlsExample(), { wide: true })}
			${example(".icon-btn", "organisms", navIconButtonExample())}
			${example(".persona navigation chip", "molecules", `<div class="sg-inline-list"><a class="persona" href="#">${icon("edit")} Editors</a><a class="persona" href="#">${icon("code")} Developers</a><a class="persona" href="#">${icon("book")} Readers</a></div>`, { wide: true })}
			${example(".intent sentence builder", "molecules", fitControlExample(), { wide: true })}
		</div>`);
}

function contentComponentsSection() {
	return section("Content components", `
		<div class="sg-examples sg-examples--organisms">
			${example(".detail__meta / .meta__k / .meta__v", "atoms / molecules", metaExample(), { wide: true })}
			${example("sort control", "molecules", sortControlExample())}
			${example("exp-badge", "atoms", `<span class="exp-badge">Experimental</span>`)}
			${example("recent list", "organisms", recentListExample(), { wide: true })}
			${example("panel + panel--cta", "organisms", panelVariantsExample(), { wide: true })}
			${example("linkgrid + linkcard", "molecules", linkCardsExample(), { wide: true })}
			${example("browse bar", "organisms", browseBarExample(), { wide: true })}
			${example("maintainer list", "organisms", maintainerListExample())}
		</div>`);
}

function organismsSection() {
	const gridHtml = grid("grid-tools", [FIXTURE_TOOL, FIXTURE_TOOL_EXPERIMENTAL, FIXTURE_TOOL_DEPRECATED], (tool, i) => toolCard(tool, i === 1 ? { popular: true, rank: 2 } : {}));
	return section("Organisms", `
		<div class="sg-examples sg-examples--organisms">
			${example("toolCard(tool)", "organisms", toolCard(FIXTURE_TOOL))}
			${example("toolCard(tool, { popular: true, rank: 1 })", "organisms", toolCard(FIXTURE_TOOL, { popular: true, rank: 1 }))}
			${example("toolCard(deprecatedTool)", "organisms", toolCard(FIXTURE_TOOL_DEPRECATED))}
			${example("listCard(list)", "organisms", listCard(FIXTURE_LIST))}
			${example("panel (sidebar)", "organisms", `<div class="panel"><h3 class="panel__title">Browse by need</h3><p class="sg-note">Borderless sidebar block: a rule under the title and content flush below, matching the main-content section heads.</p></div>`)}
			${example("Listing completeness", "organisms", listingCompletenessExample())}
			${example("grid(className, items, render)", "organisms", gridHtml, { wide: true })}
			${example("quickViewBody(tool)", "organisms", `<div class="sg-quickview">${quickViewBody(FIXTURE_TOOL)}</div>`, { wide: true })}
			${example("Related tools (similarity)", "organisms", relatedToolsExample(), { wide: true })}
			${example("Similarity graph (canvas)", "organisms", forceGraphExample(), { wide: true })}
		</div>`);
}

function activityParitySection() {
	return section("Activity & parity", `
		<div class="sg-examples sg-examples--organisms">
			${example("member card grid", "parity views", memberGridExample(), { wide: true })}
			${example("activity feed", "parity views", activityFeedExample(), { wide: true })}
			${example("crawler runs table", "parity views", runsExample(), { wide: true })}
		</div>`);
}

function collectCustomPropertyNames(prefix, fallback) {
	const names = [];
	const seen = new Set();
	const visitRules = (rules) => {
		Array.from(rules || []).forEach((rule) => {
			if (rule.cssRules) {
				try { visitRules(rule.cssRules); } catch (e) {}
			}
			if (!rule.style) return;
			Array.from(rule.style).forEach((prop) => {
				if (!prop.startsWith(prefix) || seen.has(prop)) return;
				seen.add(prop);
				names.push(prop);
			});
		});
	};
	Array.from(document.styleSheets || []).forEach((sheet) => {
		try { visitRules(sheet.cssRules); } catch (e) {}
	});
	(fallback || []).forEach((name) => {
		if (seen.has(name)) return;
		seen.add(name);
		names.push(name);
	});
	return names;
}

function resolveToken(name, cssProp) {
	const probe = document.createElement("span");
	probe.style.position = "absolute";
	probe.style.display = "block";
	probe.style.visibility = "hidden";
	probe.style.pointerEvents = "none";
	probe.style[cssProp] = `var(${name})`;
	document.body.appendChild(probe);
	const value = getComputedStyle(probe)[cssProp];
	probe.remove();
	return value || getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function renderColorTokens(targetId, names) {
	const target = document.getElementById(targetId);
	if (!target) return;
	target.innerHTML = names.map((name) => {
		const value = resolveToken(name, "backgroundColor");
		return `<div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(${esc(name)})"></span>
			<span class="sg-token__meta"><code>${esc(name)}</code><span>${esc(value)}</span></span>
		</div>`;
	}).join("");
}

function renderTypeTokens(names) {
	const target = document.getElementById("sg-type-tokens");
	if (!target) return;
	target.innerHTML = names.map((name) => {
		const value = resolveToken(name, "fontSize");
		return `<div class="sg-type-row">
			<div class="sg-type-row__specimen" style="font-size: var(${esc(name)})">Toolhub Aa 123</div>
			<div class="sg-type-row__meta"><code>${esc(name)}</code><span>${esc(value)}</span></div>
		</div>`;
	}).join("");
}

function renderRadiusTokens(names) {
	const target = document.getElementById("sg-radius-tokens");
	if (!target) return;
	target.innerHTML = names.map((name) => {
		const value = resolveToken(name, "borderRadius");
		return `<div class="sg-token">
			<span class="sg-radius-box" style="border-radius: var(${esc(name)})"></span>
			<span class="sg-token__meta"><code>${esc(name)}</code><span>${esc(value)}</span></span>
		</div>`;
	}).join("");
}

function renderShadowTokens(names) {
	const target = document.getElementById("sg-shadow-tokens");
	if (!target) return;
	target.innerHTML = names.map((name) => {
		const value = resolveToken(name, "boxShadow");
		return `<div class="sg-token">
			<span class="sg-shadow-box" style="box-shadow: var(${esc(name)})"></span>
			<span class="sg-token__meta"><code>${esc(name)}</code><span>${esc(value)}</span></span>
		</div>`;
	}).join("");
}

function renderSpaceTokens(names) {
	const target = document.getElementById("sg-space-tokens");
	if (!target) return;
	target.innerHTML = names.map((name) => {
		const value = resolveToken(name, "width");
		return `<div class="sg-space-row">
			<div class="sg-space-row__bar"><span style="width: var(${esc(name)})"></span></div>
			<div class="sg-space-row__meta"><code>${esc(name)}</code><span>${esc(value)}</span></div>
		</div>`;
	}).join("");
}

function renderLayoutTokens(names) {
	const target = document.getElementById("sg-layout-tokens");
	if (!target) return;
	target.innerHTML = names.map((name) => {
		const value = resolveToken(name, "maxWidth");
		return `<div class="sg-space-row sg-layout-row">
			<div class="sg-space-row__bar sg-space-row__bar--layout"><span style="width: min(100%, var(${esc(name)}))"></span></div>
			<div class="sg-space-row__meta"><code>${esc(name)}</code><span>${esc(value)}</span></div>
		</div>`;
	}).join("");
}

function mountStyleguide() {
	seedFixtureIndex();
	const colorTokens = collectCustomPropertyNames("--color-", FALLBACK_TOKENS.colors);
	const wmfTokens = collectCustomPropertyNames("--wmf-", FALLBACK_TOKENS.wmf);
	renderColorTokens("sg-color-tokens", colorTokens);
	renderColorTokens("sg-wmf-tokens", wmfTokens);
	renderTypeTokens(collectCustomPropertyNames("--fs-", FALLBACK_TOKENS.fs));
	renderRadiusTokens(collectCustomPropertyNames("--radius-", FALLBACK_TOKENS.radius));
	renderShadowTokens(collectCustomPropertyNames("--shadow", FALLBACK_TOKENS.shadow));
	renderSpaceTokens(collectCustomPropertyNames("--space-", FALLBACK_TOKENS.space));
	renderLayoutTokens(collectCustomPropertyNames("--container-", FALLBACK_TOKENS.layout));
	const graphTarget = document.getElementById("sg-force-graph");
	if (graphTarget) graphTarget.forceGraphHandle = forceGraph(graphTarget, STYLEGUIDE_GRAPH, { height: 220 });

	const page = document.querySelector(".sg-page");
	if (!page) return;
	page.addEventListener("click", (e) => {
		if (e.target.closest("[data-tool], [data-fav], [data-listadd], [data-q]")) {
			e.preventDefault();
			e.stopPropagation();
		}
	}, true);
	page.addEventListener("keydown", (e) => {
		if ((e.key === "Enter" || e.key === " ") && e.target.closest("[data-tool]")) {
			e.preventDefault();
			e.stopPropagation();
		}
	}, true);
	page.addEventListener("submit", (e) => {
		if (!e.target.closest(".sg-example")) return;
		e.preventDefault();
		e.stopPropagation();
	}, true);
}

export function viewStyleguide() {
	seedFixtureIndex();
	const html = withStyleguideDemoState(() => `
		<div class="container page sg-page">
			<h1 class="page__title">Design system</h1>
			<p class="page__intro">A living reference for Toolhub tokens and component functions, rendered from the same modules used by the application.</p>
			${tokenSection()}
			${chromeSection()}
			${layoutStatesSection()}
			${buttonsSection()}
			${iconsSection()}
			${atomsSection()}
			${moleculesSection()}
			${contentComponentsSection()}
			${organismsSection()}
			${activityParitySection()}
		</div>`);
	return { title: "Design system — Toolhub", html, mount: mountStyleguide };
}
