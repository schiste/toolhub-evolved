// SPDX-License-Identifier: GPL-3.0-or-later
import { $, dirAttrs, esc } from "../lib/core/dom.js";
import { countLabel, updatedTimeTag } from "../lib/core/i18n.js";
import { apiGet, normalizeList, normalizeTool } from "../lib/core/api.js";
import { listHref, NEEDS, PERSONAS, STEPS, toolHref } from "../lib/core/routing.js";
import { avatar } from "../lib/atoms/avatar.js";
import { grid } from "../lib/organisms/grid.js";
import { listCard } from "../lib/organisms/list-card.js";
import { toolCard } from "../lib/organisms/tool-card.js";

export async function viewHome() {
	// Live: total count, featured curated lists (with embedded tools), recent tools.
	const [home, flists, recent] = await Promise.all([
		apiGet("/ui/home/").catch(() => ({})),
		apiGet("/lists/", { featured: "true", page_size: "6" }).catch(() => ({ results: [] })),
		apiGet("/search/tools/", { ordering: "-modified_date", page_size: "5" }).catch(() => ({ results: [] })),
	]);
	const total = home.total_tools || 0;
	const lists = (flists.results || []).map(normalizeList);
	// "Featured tools" = the curated tools drawn from the featured lists (deduped).
	const seen = new Set(), featured = [];
	for (const l of lists) for (const t of l.tools) if (!seen.has(t.name)) { seen.add(t.name); featured.push(t); }
	const popular = featured.slice().sort((a, b) => (b.weeklyViews - a.weeklyViews) || a.title.localeCompare(b.title));
	const recentTools = (recent.results || []).map(normalizeTool);

	const personas = PERSONAS.map(([ic, l, term]) => `<a class="persona" href="#/search?audiences__term=${encodeURIComponent(term)}"><span aria-hidden="true">${ic}</span> ${l}</a>`).join("");
	const needs = NEEDS.map(([ic, l, term]) => `<li><a href="#/search?tasks__term=${encodeURIComponent(term)}"><span aria-hidden="true">${ic}</span> ${l}<span class="need__chev" aria-hidden="true">›</span></a></li>`).join("");
	const steps = STEPS.map(([ic, t, d]) => `<div class="step"><div class="step__icon" aria-hidden="true">${ic}</div><div class="step__title">${t}</div><div class="step__desc">${d}</div></div>`).join("");
	const recentHtml = recentTools.map((t) => `
		<li><a href="${toolHref(t.name)}">${avatar(t.title)}
			<div><div class="recent__title"${dirAttrs(t.title)}>${esc(t.title)}</div>
			<div class="recent__meta">Maintainer: <span${dirAttrs(t.maintainer)}>${esc(t.maintainer)}</span></div></div>
			${updatedTimeTag(t.modified, "recent__when")}</a></li>`).join("");

	const html = `
	<section class="hero">
		<h1 class="hero__title">The community catalog of Wikimedia tools</h1>
		<p class="hero__lead">${esc(countLabel(total, "tool", "tools"))} built by volunteers to edit, curate, and analyze the Wikimedia projects — documented and searchable in one place.</p>
		<form class="search" role="search" data-home-search>
			<label for="home-q" class="skip-label">Search tools</label>
			<input id="home-q" class="search__input" type="search" aria-label="Search tools" placeholder="Search ${esc(countLabel(total, "tool", "tools"))}…" autocomplete="off" />
			<button class="btn btn--primary search__btn" type="submit">Search</button>
		</form>
	</section>
	<section class="personas container"><span class="personas__label">I'm looking for tools for:</span><div class="personas__row">${personas}</div></section>
	<div class="container layout">
		<div class="layout__main">
			<div class="section-head"><h2>Featured tools</h2><a class="link" href="${listHref((lists[0] || {}).id || "")}">View all</a></div>
			${grid("grid-tools", featured.slice(0, 8), (t) => toolCard(t))}
			<!-- EXPERIMENTAL — "Popular this week" ranks by weeklyViews.
			     MISSING: no popularity/usage signal in the Toolhub API; ranks shown here are synthetic. -->
			<div class="experimental">
				<div class="section-head"><h2>Popular this week <span class="exp-badge">Experimental</span></h2><a class="link" href="#/search?sort=views">View all</a></div>
				${grid("grid-tools", popular.slice(0, 8), (t, i) => toolCard(t, { rank: i + 1, popular: true }))}
			</div>
			<div class="section-head"><h2>Curated lists</h2><a class="link" href="#/lists">View all lists</a></div>
			${grid("grid-lists", lists.slice(0, 6), listCard)}
			<div class="section-head"><h2>Getting started</h2></div>
			<div class="card-grid grid-steps">${steps}</div>
		</div>
		<aside class="layout__side">
			<div class="panel"><h3 class="panel__title">Browse by need</h3><ul class="needs">${needs}</ul><a class="link panel__foot" href="#/search">View all categories</a></div>
			<div class="panel"><h3 class="panel__title">Recently updated</h3><ul class="recent">${recentHtml}</ul></div>
			<div class="panel panel--cta"><div class="cta__icon" aria-hidden="true">💡</div><h3>Built a tool for Wikimedia?</h3><p>Add a <code>toolinfo.json</code> to your repository, or register it here, so other Wikimedians can find it.</p><a class="btn btn--outline" href="https://toolhub.wikimedia.org/tools/create" target="_blank" rel="noopener">Submit a tool</a></div>
		</aside>
	</div>`;
	return {
		title: "Toolhub — discover Wikimedia tools",
		html,
		mount() {
			$("[data-home-search]").addEventListener("submit", (e) => {
				e.preventDefault();
				const q = $("#home-q").value.trim();
				location.hash = "#/search" + (q ? "?q=" + encodeURIComponent(q) : "");
			});
		},
	};
}
