// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, dirAttrs, esc } from "../lib/core/dom.js";
import { countLabel, updatedTimeTag } from "../lib/core/i18n.js";
import { apiGet, normalizeList, normalizeTool } from "../lib/core/api.js";
import { endorsementOf, fitsContext, getUserContext, hasContext, listMemberships, setUserContext } from "../lib/core/signals.js";
import { listHref, NEEDS, PERSONAS, toolHref } from "../lib/core/routing.js";
import { avatar } from "../lib/atoms/avatar.js";
import { button } from "../lib/atoms/button.js";
import { icon } from "../lib/atoms/icon.js";
import { grid } from "../lib/organisms/grid.js";
import { listCard } from "../lib/organisms/list-card.js";
import { toolCard } from "../lib/organisms/tool-card.js";

const WIKI_OPTIONS = [
	["", "Any wiki"],
	["wikidata.org", "Wikidata"],
	["commons.wikimedia.org", "Commons"],
	["en.wikipedia.org", "English Wikipedia"],
	["*.wikipedia.org", "Any Wikipedia"],
	["*.wikisource.org", "Any Wikisource"],
	["meta.wikimedia.org", "Meta-Wiki"],
];
const ROLE_OPTIONS = [
	["", "Anyone"],
	["editor", "Editor"],
	["developer", "Developer"],
	["reader", "Reader"],
	["researcher", "Researcher"],
	["admin", "Admin"],
	["organizer", "Organizer"],
];

function contextOptions(options, selected) {
	selected = selected || "";
	return options.map(([value, label]) => `<option value="${esc(value)}"${value === selected ? " selected" : ""}>${esc(label)}</option>`).join("");
}

function rankFitsFirst(tools) {
	if (!hasContext()) return tools;
	return tools.map((t, i) => [t, i])
		.sort((a, b) => ((fitsContext(b[0]).fits ? 1 : 0) - (fitsContext(a[0]).fits ? 1 : 0)) || (a[1] - b[1]))
		.map((x) => x[0]);
}

export async function viewHome() {
	// Live: total count, featured curated lists (with embedded tools), recent tools.
	const [home, flists, recent] = await Promise.all([
		apiGet("/ui/home/").catch(() => ({})),
		apiGet("/lists/", { featured: "true", page_size: "6" }).catch(() => ({ results: [] })),
		apiGet("/search/tools/", { ordering: "-modified_date", page_size: "5" }).catch(() => ({ results: [] })),
	]);
	const lm = await listMemberships();
	const total = home.total_tools || 0;
	const lists = (flists.results || []).map(normalizeList);
	// "Featured tools" = the curated tools drawn from the featured lists (deduped).
	const seen = new Set(), featured = [];
	for (const l of lists) for (const t of l.tools) if (!seen.has(t.name)) { seen.add(t.name); featured.push(t); }
	featured.forEach((t) => { t.endorsement = endorsementOf(t.name, lm); });
	const mostListed = featured.slice().sort((a, b) => ((b.endorsement && b.endorsement.count) || 0) - ((a.endorsement && a.endorsement.count) || 0) || a.title.localeCompare(b.title));
	const featuredRanked = rankFitsFirst(featured);
	const mostListedRanked = rankFitsFirst(mostListed);
	const recentTools = (recent.results || []).map(normalizeTool);
	const ctx = getUserContext();

	const personas = PERSONAS.map(([ic, l, term]) => `<a class="persona" href="#/search?audiences__term=${encodeURIComponent(term)}">${icon(ic)} ${l}</a>`).join("");
	const needs = NEEDS.map(([ic, l, term]) => `<a class="persona" href="#/search?tasks__term=${encodeURIComponent(term)}">${icon(ic)} ${l}</a>`).join("");
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
			${button("Search", { variant: "primary", type: "submit", cls: "search__btn" })}
		</form>
		<div class="hero__explore">
			<p class="hero__explore-prompt">I want to see tools
				<span class="hero__modes" role="tablist" aria-label="Choose how to browse tools">
					<button class="hero__mode is-active" type="button" role="tab" aria-selected="true" aria-controls="browse-audiences" data-mode="audiences">made for</button>
					<button class="hero__mode" type="button" role="tab" aria-selected="false" aria-controls="browse-tasks" data-mode="tasks">to</button>
				</span>
			</p>
			<div class="hero__chips" id="browse-audiences" role="tabpanel" data-mode-panel="audiences">${personas}</div>
			<div class="hero__chips" id="browse-tasks" role="tabpanel" data-mode-panel="tasks" hidden>${needs}</div>
			<a class="link hero__explore-foot" href="#/search">Browse all categories</a>
			<div class="hero__context">
				<label class="hero__context-field">I work on
					<select class="hero__context-select" data-ctx-wiki>${contextOptions(WIKI_OPTIONS, ctx.wiki)}</select>
				</label>
				<label class="hero__context-field">as
					<select class="hero__context-select" data-ctx-role>${contextOptions(ROLE_OPTIONS, ctx.role)}</select>
				</label>
			</div>
		</div>
	</section>
	<div class="container layout">
		<div class="layout__main">
			<div class="section-head"><h2>Featured tools</h2><a class="link" href="${listHref((lists[0] || {}).id || "")}">View all</a></div>
			${grid("grid-tools", featuredRanked.slice(0, 8), (t) => toolCard(t))}
			<div class="section-head"><h2>Most listed</h2><a class="link" href="#/lists">View lists</a></div>
			${grid("grid-tools", mostListedRanked.slice(0, 8), (t, i) => toolCard(t, { rank: i + 1 }))}
			<div class="section-head"><h2>Curated lists</h2><a class="link" href="#/lists">View all lists</a></div>
			${grid("grid-lists", lists.slice(0, 6), listCard)}
		</div>
		<aside class="layout__side">
			<div class="panel"><h3 class="panel__title">Recently updated</h3><ul class="recent">${recentHtml}</ul></div>
			<div class="panel panel--cta"><div class="cta__icon" aria-hidden="true">${icon("idea", "icon--lg")}</div><h3>Built a tool for Wikimedia?</h3><p>Add a <code>toolinfo.json</code> to your repository, or register it here, so other Wikimedians can find it.</p>${button("Submit a tool", { variant: "outline", href: "https://toolhub.wikimedia.org/add-or-remove-tools?tab=tool-create", attrs: 'target="_blank" rel="noopener"' })}</div>
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
			// Browse-axis toggle: switch the hero chips between audiences ("made for")
			// and tasks ("to") without leaving the page.
			const modeBtns = $$(".hero__mode"), panels = $$("[data-mode-panel]");
			modeBtns.forEach((btn) => btn.addEventListener("click", () => {
				const mode = btn.getAttribute("data-mode");
				modeBtns.forEach((b) => { const on = b === btn; b.classList.toggle("is-active", on); b.setAttribute("aria-selected", String(on)); });
				panels.forEach((p) => { p.hidden = p.getAttribute("data-mode-panel") !== mode; });
			}));
			const wikiSelect = $("[data-ctx-wiki]");
			const roleSelect = $("[data-ctx-role]");
			const updateContext = () => {
				setUserContext({ wiki: wikiSelect.value, role: roleSelect.value });
				window.dispatchEvent(new Event("hashchange"));
			};
			[wikiSelect, roleSelect].forEach((select) => select.addEventListener("change", updateContext));
		},
	};
}
