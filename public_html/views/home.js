// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, dirAttrs, esc } from "../lib/core/dom.js";
import { countLabel, updatedTimeTag } from "../lib/core/i18n.js";
import { apiGet, normalizeList, normalizeTool } from "../lib/core/api.js";
import { attachEndorsements, getUserContext, rankFitsFirst, setUserContext, wikiMatches } from "../lib/core/signals.js";
import { listHref, navigateTo, NEEDS, PERSONAS, toolHref } from "../lib/core/routing.js";
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
	["meta.wikimedia.org", "Meta-Wiki"]
];
const INTENT_AXES = {
	audiences: {
		label: "made for",
		any: "anyone",
		param: "audiences__term",
		options: PERSONAS.map(([, label, term]) => [term, label.toLowerCase()])
	},
	tasks: {
		label: "to",
		any: "do anything",
		param: "tasks__term",
		options: NEEDS.map(([, label, term]) => [term, label.toLowerCase()])
	}
};

function intentAxisItems() {
	return Object.entries(INTENT_AXES).map(([value, cfg]) => [value, cfg.label]);
}
function intentTermItems(axis) {
	const cfg = INTENT_AXES[axis] || INTENT_AXES.audiences;
	return [["", cfg.any], ...cfg.options];
}
function projectItems() {
	return WIKI_OPTIONS.map(([value, label]) => [value, value ? label : "any project"]);
}
function itemLabel(items, value) {
	const hit = items.find(([v]) => v === (value || ""));
	return hit ? hit[1] : (items[0] && items[0][1]) || "";
}
function intentOptionButtons(kind, items, selected = "") {
	return items
		.map(
			([value, label]) =>
				`<button class="intent__option${value === selected ? " is-active" : ""}" type="button" role="menuitemradio" aria-checked="${value === selected}" data-intent-option="${esc(kind)}" data-value="${esc(value)}">${esc(label)}</button>`
		)
		.join("");
}
function intentChoice(kind, label, items, selected) {
	return `<span class="intent__choice" data-intent-choice="${esc(kind)}">
		<button class="intent__word" type="button" data-intent-trigger="${esc(kind)}" aria-haspopup="menu" aria-expanded="false"><span data-intent-label="${esc(kind)}">${esc(label)}</span></button>
		<span class="intent__menu" data-intent-menu="${esc(kind)}" role="menu" hidden>${intentOptionButtons(kind, items, selected)}</span>
	</span>`;
}
function intentStateFromContext(ctx) {
	return { axis: "audiences", term: (ctx && ctx.role) || "", wiki: (ctx && ctx.wiki) || "" };
}
function homeFilterParams(state) {
	const params = new URLSearchParams();
	const cfg = INTENT_AXES[state.axis] || INTENT_AXES.audiences;
	if (state.term) params.set(cfg.param, state.term);
	if (state.wiki) params.set("wiki__term", state.wiki);
	return params;
}
function hasHomeFilters(state) {
	return Boolean(state.term || state.wiki);
}
function searchHrefForState(state) {
	const params = homeFilterParams(state);
	return `/search${params.toString() ? `?${params.toString()}` : ""}`;
}
function toolMatchesIntent(t, state) {
	if (state.term) {
		const values = state.axis === "tasks" ? t.tasks : t.audiences;
		if (!(values || []).includes(state.term)) return false;
	}
	if (state.wiki && !wikiMatches(t.forWikis, state.wiki)) return false;
	return true;
}
function dedupeTools(tools) {
	const seen = new Set(),
		out = [];
	for (const t of tools) {
		if (!t || !t.name || seen.has(t.name)) continue;
		seen.add(t.name);
		out.push(t);
	}
	return out;
}
function sortedByEndorsements(tools) {
	return [...tools].sort(
		(a, b) =>
			((b.endorsement && b.endorsement.count) || 0) - ((a.endorsement && a.endorsement.count) || 0) ||
			a.title.localeCompare(b.title)
	);
}
function recentToolsHTML(recentTools) {
	return (
		recentTools
			.map(
				(t) => `
		<li><a href="${toolHref(t.name)}">${avatar(t.title)}
			<div><div class="recent__title"${dirAttrs(t.title)}>${esc(t.title)}</div>
			<div class="recent__meta">Maintainer: <span${dirAttrs(t.maintainer)}>${esc(t.maintainer)}</span></div></div>
			${updatedTimeTag(t.modified, "recent__when")}</a></li>`
			)
			.join("") || '<li class="recent__empty">No recently updated tools match this sentence.</li>'
	);
}
function toolsGridHTML(tools, empty, render) {
	return tools.length > 0
		? grid("grid-tools", tools, render || ((t) => toolCard(t)))
		: `<p class="empty">${esc(empty)}</p>`;
}
function listsGridHTML(lists, empty) {
	return lists.length > 0 ? grid("grid-lists", lists, listCard) : `<p class="empty">${esc(empty)}</p>`;
}
function renderHomeMain(model, state) {
	const filtered = hasHomeFilters(state);
	const featuredHref = filtered
		? searchHrefForState(state)
		: model.lists[0] && model.lists[0].id
			? listHref(model.lists[0].id)
			: "/lists";
	return `
		<div class="section-head"><h2>Featured tools</h2><a class="link" href="${featuredHref}">View all</a></div>
		${toolsGridHTML(model.featuredRanked.slice(0, 8), "No tools match this sentence.")}
		<div class="section-head"><h2>Most listed</h2><a class="link" href="${filtered ? searchHrefForState(state) : "/lists"}">${filtered ? "View all" : "View lists"}</a></div>
		${toolsGridHTML(model.mostListedRanked.slice(0, 8), "No listed tools match this sentence.", (t, i) => toolCard(t, { rank: i + 1 }))}
		<div class="section-head"><h2>Curated lists</h2><a class="link" href="/lists">View all lists</a></div>
		${listsGridHTML(model.lists.slice(0, 6), "No curated lists match this sentence.")}`;
}
async function homeSectionsModel(state) {
	const filters = homeFilterParams(state);
	const filtered = filters.toString() !== "";
	const listParams = { featured: "true", page_size: filtered ? "30" : "6" };
	const recentParams = new URLSearchParams(filters);
	recentParams.set("ordering", "-modified_date");
	recentParams.set("page_size", "5");
	const toolParams = new URLSearchParams(filters);
	toolParams.set("page_size", "24");
	const [flists, recent, filteredToolsData] = await Promise.all([
		apiGet("/lists/", listParams).catch(() => ({ results: [] })),
		apiGet("/search/tools/", recentParams).catch(() => ({ results: [] })),
		filtered ? apiGet("/search/tools/", toolParams).catch(() => ({ results: [] })) : Promise.resolve(null)
	]);
	let lists = (flists.results || []).map((list) => normalizeList(list));
	let featured;
	if (filtered) {
		featured = (filteredToolsData.results || []).map((tool) => normalizeTool(tool));
		await attachEndorsements(featured);
		const matchingNames = new Set(featured.map((t) => t.name));
		lists = lists.filter((l) =>
			(l.tools || []).some((t) => matchingNames.has(t.name) || toolMatchesIntent(t, state))
		);
	} else {
		featured = dedupeTools(lists.flatMap((l) => l.tools || []));
		await attachEndorsements(featured);
	}
	const recentTools = (recent.results || []).map((tool) => normalizeTool(tool));
	const mostListed = sortedByEndorsements(featured);
	return {
		lists,
		featuredRanked: rankFitsFirst(featured),
		mostListedRanked: rankFitsFirst(mostListed),
		recentTools
	};
}

export async function viewHome() {
	// Live: total count, featured curated lists (with embedded tools), recent tools.
	const [home] = await Promise.all([apiGet("/ui/home/").catch(() => ({}))]);
	const total = home.total_tools || 0;
	const ctx = getUserContext();
	const initialState = intentStateFromContext(ctx);
	const initialModel = await homeSectionsModel(initialState);
	const intentAxis = initialState.axis;
	const intentTerm = initialState.term;
	const intentWiki = initialState.wiki;

	const html = `
	<section class="hero">
		<h1 class="hero__title">The community catalog of Wikimedia tools</h1>
		<div class="hero__explore">
			<form class="intent" data-intent-form data-axis="${esc(intentAxis)}" data-term="${esc(intentTerm)}" data-wiki="${esc(intentWiki)}">
				<div class="intent__sentence" aria-label="Build a tool search">
					<span class="intent__copy">I want to see tools</span>
					${intentChoice("axis", itemLabel(intentAxisItems(), intentAxis), intentAxisItems(), intentAxis)}
					${intentChoice("term", itemLabel(intentTermItems(intentAxis), intentTerm), intentTermItems(intentAxis), intentTerm)}
					<span class="intent__copy">on</span>
					${intentChoice("wiki", itemLabel(projectItems(), intentWiki), projectItems(), intentWiki)}
					<button class="intent__go" type="submit">See tools</button>
					<button class="intent__clear" type="button" data-intent-clear${hasHomeFilters(initialState) ? "" : " disabled"}>clear</button>
				</div>
			</form>
		</div>
		<div class="hero__or" aria-hidden="true">or</div>
		<form class="search" role="search" data-home-search>
			<label for="home-q" class="skip-label">Search tools</label>
			<input id="home-q" class="search__input" type="search" aria-label="Search tools" placeholder="Search ${esc(countLabel(total, "tool", "tools"))}…" autocomplete="off" />
			${button("Search", { variant: "primary", type: "submit", cls: "search__btn" })}
		</form>
	</section>
	<div class="container layout">
		<div class="layout__main home-results" data-home-main aria-live="polite">
			${renderHomeMain(initialModel, initialState)}
		</div>
		<aside class="layout__side">
			<div class="panel"><h3 class="panel__title">Recently updated</h3><ul class="recent" data-home-recent aria-live="polite">${recentToolsHTML(initialModel.recentTools)}</ul></div>
			<div class="panel panel--cta"><div class="cta__icon" aria-hidden="true">${icon("idea", "icon--lg")}</div><h3>Built a tool for Wikimedia?</h3><p>Add a <code>toolinfo.json</code> to your repository, or register it here, so other Wikimedians can find it.</p>${button("Submit a tool", { variant: "outline", href: "https://toolhub.wikimedia.org/add-or-remove-tools?tab=tool-create", attrs: 'target="_blank" rel="noopener nofollow"' })}</div>
		</aside>
	</div>`;
	return {
		title: "Toolhub — discover Wikimedia tools",
		html,
		mount() {
			$("[data-home-search]").addEventListener("submit", (e) => {
				e.preventDefault();
				const q = $("#home-q").value.trim();
				navigateTo(`/search${q ? `?q=${encodeURIComponent(q)}` : ""}`);
			});
			const intentForm = $("[data-intent-form]");
			const homeMain = $("[data-home-main]");
			const homeRecent = $("[data-home-recent]");
			const state = {
				axis: intentForm.dataset.axis || "audiences",
				term: intentForm.dataset.term || "",
				wiki: intentForm.dataset.wiki || ""
			};
			let refreshSeq = 0;
			const closeMenus = () => {
				$$("[data-intent-menu]", intentForm).forEach((menu) => {
					menu.hidden = true;
				});
				$$("[data-intent-trigger]", intentForm).forEach((trigger) =>
					trigger.setAttribute("aria-expanded", "false")
				);
			};
			const setMenu = (kind, on) => {
				closeMenus();
				if (!on) return;
				const menu = $(`[data-intent-menu="${kind}"]`, intentForm);
				const trigger = $(`[data-intent-trigger="${kind}"]`, intentForm);
				if (!menu || !trigger) return;
				menu.hidden = false;
				trigger.setAttribute("aria-expanded", "true");
			};
			const syncIntent = () => {
				const axisItems = intentAxisItems();
				const termItems = intentTermItems(state.axis);
				const wikiItems = projectItems();
				$('[data-intent-label="axis"]', intentForm).textContent = itemLabel(axisItems, state.axis);
				$('[data-intent-label="term"]', intentForm).textContent = itemLabel(termItems, state.term);
				$('[data-intent-label="wiki"]', intentForm).textContent = itemLabel(wikiItems, state.wiki);
				$('[data-intent-menu="axis"]', intentForm).innerHTML = intentOptionButtons(
					"axis",
					axisItems,
					state.axis
				);
				$('[data-intent-menu="term"]', intentForm).innerHTML = intentOptionButtons(
					"term",
					termItems,
					state.term
				);
				$('[data-intent-menu="wiki"]', intentForm).innerHTML = intentOptionButtons(
					"wiki",
					wikiItems,
					state.wiki
				);
				const clear = $("[data-intent-clear]", intentForm);
				if (clear) clear.disabled = !hasHomeFilters(state);
			};
			const persistIntent = () => {
				setUserContext({ wiki: state.wiki, role: state.axis === "audiences" ? state.term : "" });
			};
			const renderHomeModel = (model) => {
				homeMain.innerHTML = renderHomeMain(model, state);
				homeRecent.innerHTML = recentToolsHTML(model.recentTools);
			};
			const renderHomeError = () => {
				homeMain.innerHTML = '<p class="empty">Unable to refresh tools right now.</p>';
				homeRecent.innerHTML = '<li class="recent__empty">Unable to refresh recently updated tools.</li>';
			};
			const refreshHome = async () => {
				const seq = ++refreshSeq;
				homeMain.setAttribute("aria-busy", "true");
				homeRecent.setAttribute("aria-busy", "true");
				try {
					const model = await homeSectionsModel(state);
					if (seq !== refreshSeq) return;
					renderHomeModel(model);
				} catch {
					if (seq !== refreshSeq) return;
					renderHomeError();
				} finally {
					if (seq === refreshSeq) {
						homeMain.removeAttribute("aria-busy");
						homeRecent.removeAttribute("aria-busy");
					}
				}
			};
			intentForm.addEventListener("click", (e) => {
				const trigger = e.target.closest("[data-intent-trigger]");
				if (trigger) {
					e.preventDefault();
					const kind = trigger.getAttribute("data-intent-trigger");
					const menu = $(`[data-intent-menu="${kind}"]`, intentForm);
					setMenu(kind, menu && menu.hidden);
					return;
				}
				const option = e.target.closest("[data-intent-option]");
				if (!option) return;
				e.preventDefault();
				const kind = option.getAttribute("data-intent-option");
				const value = option.getAttribute("data-value") || "";
				if (kind === "axis") {
					state.axis = value || "audiences";
					state.term = "";
				} else if (kind === "term") {
					state.term = value;
				} else if (kind === "wiki") {
					state.wiki = value;
				}
				syncIntent();
				persistIntent();
				refreshHome();
				closeMenus();
			});
			$("[data-intent-clear]", intentForm).addEventListener("click", () => {
				state.axis = "audiences";
				state.term = "";
				state.wiki = "";
				syncIntent();
				persistIntent();
				refreshHome();
				closeMenus();
			});
			document.addEventListener("click", (e) => {
				if (!intentForm.contains(e.target)) closeMenus();
			});
			document.addEventListener("keydown", (e) => {
				if (e.key === "Escape") closeMenus();
			});
			intentForm.addEventListener("submit", (e) => {
				e.preventDefault();
				persistIntent();
				navigateTo(searchHrefForState(state));
			});
		}
	};
}
