// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, $input, dirAttrs, esc, textAttrs } from "../lib/core/dom.js";
import { countLabel, t, tWithElements, updatedTimeTag } from "../lib/core/i18n.js";
import {
	apiGet,
	backendGetJson,
	cachedCanonicalTools,
	getToolsByName,
	normalizeList,
	normalizeTool,
	paginate
} from "../lib/core/api.js";
import {
	attachEndorsements,
	attachEvolvedSummaries,
	getUserContext,
	rankFitsFirst,
	setUserContext,
	wikiMatches
} from "../lib/core/signals.js";
import { navigateTo, NEEDS, PERSONAS, toolHref } from "../lib/core/routing.js";
import { serverUserName, signedIn } from "../lib/core/session.js";
import { favNames, personalToolsCacheGet, personalToolsCacheSet } from "../lib/core/store.js";
import { avatar } from "../lib/atoms/avatar.js";
import { button } from "../lib/atoms/button.js";
import { icon } from "../lib/atoms/icon.js";
import { cardGridSkeleton } from "../lib/molecules/skeleton.js";
import { grid } from "../lib/organisms/grid.js";
import { listCard } from "../lib/organisms/list-card.js";
import { toolCard } from "../lib/organisms/tool-card.js";

// The intent menus close on an outside click / Escape via document-level
// listeners. They are registered in mount(), so without cleanup each revisit to
// home would add another pair onto `document`. Keep the live pair here and
// remove it before re-registering, so at most one pair is ever attached.
/** @type {((e: MouseEvent) => void) | null} */
let intentDocClick = null;
/** @type {((e: KeyboardEvent) => void) | null} */
let intentDocKeydown = null;

const WIKI_OPTIONS = [
	// Stryker disable next-line StringLiteral: projectItems() overrides the label for the value="" row with "any project", so this "Any wiki" string is never rendered — equivalent.
	["", "Any wiki"],
	["wikidata.org", t("home.wikiWikidata", "Wikidata")],
	["commons.wikimedia.org", t("home.wikiCommons", "Commons")],
	["en.wikipedia.org", t("home.wikiEnglishWikipedia", "English Wikipedia")],
	["*.wikipedia.org", t("home.wikiAnyWikipedia", "Any Wikipedia")],
	["*.wikisource.org", t("home.wikiAnyWikisource", "Any Wikisource")],
	["meta.wikimedia.org", t("home.wikiMetaWiki", "Meta-Wiki")]
];
const INTENT_AXES = {
	audiences: {
		label: t("home.madeFor", "made for"),
		any: t("home.anyone", "anyone"),
		param: "audiences__term",
		options: PERSONAS.map(([, label, term]) => [term, label.toLowerCase()])
	},
	tasks: {
		label: t("home.to", "to"),
		any: t("home.doAnything", "do anything"),
		param: "tasks__term",
		options: NEEDS.map(([, label, term]) => [term, label.toLowerCase()])
	}
};

/** @typedef {{ axis: string, term: string, wiki: string }} IntentState */
/** @typedef {{ tools: Tool[], error?: boolean, loading?: boolean }} PersonalTools */
/** @typedef {{ favorites: PersonalTools, ownTools: PersonalTools }} PersonalHomeModel */
/** @typedef {{ model: PersonalHomeModel, refresh?: Promise<PersonalHomeModel> }} PersonalHomeResult */
/** @typedef {{ lists: ToolList[], featuredRanked: Tool[], mostListedRanked: Tool[], recentTools: Tool[], personal?: PersonalHomeModel, cacheFallback?: boolean }} HomeModel */
/** @typedef {Tool & { endorsement?: { count?: number } }} HomeTool */

// Account resolution is substantially more expensive than the public catalog
// reads. Keep one request per signed-in user in flight and reuse its result for
// a short window so cache-refresh repaints cannot re-run the resolver.
const PERSONAL_HOME_TTL_MS = 30_000;
/** @type {Map<string, { model: PersonalHomeModel, expiresAt: number }>} */
const personalHomeCache = new Map();
/** @type {Map<string, Promise<PersonalHomeModel>>} */
const personalHomeRequests = new Map();
const PERSONAL_TOOLS_CACHE_TTL_MS = 5 * 60 * 1000;

/**
 * Read the account-scoped browser cache. The username is part of the cache
 * record rather than an implicit global, so switching accounts cannot reuse a
 * previous user's associations.
 * @param {string} username
 * @returns {{ tools: Tool[], updatedAt: number } | null}
 */
function readPersonalToolsCache(username) {
	const cached = personalToolsCacheGet(username);
	return cached ? { tools: cached.tools.map((tool) => normalizeTool(tool)), updatedAt: cached.updatedAt } : null;
}

/** @param {string} username @param {Tool[]} tools */
function writePersonalToolsCache(username, tools) {
	personalToolsCacheSet(username, tools);
}

function intentAxisItems() {
	return Object.entries(INTENT_AXES).map(([value, cfg]) => [value, cfg.label]);
}
/** @param {string} axis */
function intentTermItems(axis) {
	const cfg = INTENT_AXES[/** @type {keyof typeof INTENT_AXES} */ (axis)] || INTENT_AXES.audiences;
	return [["", cfg.any], ...cfg.options];
}
function projectItems() {
	return WIKI_OPTIONS.map(([value, label]) => [value, value ? label : t("home.anyProject", "any project")]);
}
/**
 * @param {string[][]} items
 * @param {string} value
 */
function itemLabel(items, value) {
	// Stryker disable next-line StringLiteral: every caller passes a value present in items; when value is falsy the matching row is items[0] (the empty-string option), so the `|| ""` fallback selects the same row — equivalent.
	const hit = items.find(([v]) => v === (value || ""));
	// Stryker disable next-line ConditionalExpression,LogicalOperator,StringLiteral: callers only pass values that exist in items, so `hit` is always found and this defensive fallback is unreachable.
	return hit ? hit[1] : (items[0] && items[0][1]) || "";
}
/**
 * @param {string} kind
 * @param {string[][]} items
 * @param {string} [selected]
 */
// Stryker disable next-line StringLiteral: every caller passes `selected`, so the default value is never used — equivalent.
function intentOptionButtons(kind, items, selected = "") {
	return items
		.map(
			([value, label]) =>
				`<button class="intent__option${value === selected ? " is-active" : ""}" type="button" role="menuitemradio" aria-checked="${value === selected}" data-intent-option="${esc(kind)}" data-value="${esc(value)}">${esc(label)}</button>`
		)
		.join("");
}
/**
 * @param {string} kind
 * @param {string} label
 * @param {string[][]} items
 * @param {string} selected
 */
function intentChoice(kind, label, items, selected) {
	return `<span class="intent__choice" data-intent-choice="${esc(kind)}">
		<button class="intent__word" type="button" data-intent-trigger="${esc(kind)}" aria-haspopup="menu" aria-expanded="false"><span data-intent-label="${esc(kind)}">${esc(label)}</span></button>
		<span class="intent__menu" data-intent-menu="${esc(kind)}" role="menu" hidden>${intentOptionButtons(kind, items, selected)}</span>
	</span>`;
}
/**
 * @param {{ role?: string, wiki?: string } | null | undefined} ctx
 * @returns {IntentState}
 */
function intentStateFromContext(ctx) {
	return { axis: "audiences", term: (ctx && ctx.role) || "", wiki: (ctx && ctx.wiki) || "" };
}
/** @param {IntentState} state */
function homeFilterParams(state) {
	const params = new URLSearchParams();
	const cfg = INTENT_AXES[/** @type {keyof typeof INTENT_AXES} */ (state.axis)] || INTENT_AXES.audiences;
	if (state.term) params.set(cfg.param, state.term);
	if (state.wiki) params.set("wiki__term", state.wiki);
	return params;
}
/** @param {IntentState} state */
function hasHomeFilters(state) {
	return Boolean(state.term || state.wiki);
}
/** @param {IntentState} state */
function searchHrefForState(state) {
	const params = homeFilterParams(state);
	return `/search${params.toString() ? `?${params.toString()}` : ""}`;
}
/**
 * @param {Tool} t
 * @param {IntentState} state
 */
function toolMatchesIntent(t, state) {
	if (state.term) {
		const values = state.axis === "tasks" ? t.tasks : t.audiences;
		// Stryker disable next-line ArrayDeclaration: normalizeTool always yields arrays for tasks/audiences, so the `|| []` fallback is never taken — equivalent.
		if (!(values || []).includes(state.term)) return false;
	}
	if (state.wiki && !wikiMatches(t.forWikis, state.wiki)) return false;
	return true;
}
/**
 * @param {Tool[]} tools
 * @returns {Tool[]}
 */
function dedupeTools(tools) {
	/** @type {Set<string>} */
	const seen = new Set();
	/** @type {Tool[]} */
	const out = [];
	for (const t of tools) {
		if (!t || !t.name || seen.has(t.name)) continue;
		seen.add(t.name);
		out.push(t);
	}
	return out;
}
/**
 * @param {HomeTool[]} tools
 * @returns {HomeTool[]}
 */
function sortedByEndorsements(tools) {
	return [...tools].sort(
		(a, b) =>
			((b.endorsement && b.endorsement.count) || 0) - ((a.endorsement && a.endorsement.count) || 0) ||
			a.title.localeCompare(b.title)
	);
}
/** @param {Tool[]} recentTools */
function recentToolsHTML(recentTools) {
	const maintainerLabel = t("home.maintainer", "Maintainer:");
	return (
		recentTools
			.map(
				(t) => `
		<li><a href="${toolHref(t.name)}">${avatar(t.title)}
			<div><div class="recent__title"${textAttrs(t.title, t.titleLanguage)}>${esc(t.title)}</div>
			<div class="recent__meta">${maintainerLabel} <span${dirAttrs(t.maintainer)}>${esc(t.maintainer)}</span></div></div>
			${updatedTimeTag(t.modified, "recent__when")}</a></li>`
			)
			.join("") ||
		`<li class="recent__empty">${t("home.recentEmpty", "No recently updated tools match this sentence.")}</li>`
	);
}
/**
 * @param {Tool[]} tools
 * @param {string} empty
 * @param {(t: Tool, i: number) => string} [render]
 */
function toolsGridHTML(tools, empty, render) {
	return tools.length > 0
		? grid("grid-tools", tools, render || ((/** @type {Tool} */ t) => toolCard(t)))
		: `<p class="empty">${esc(empty)}</p>`;
}
/**
 * @param {ToolList[]} lists
 * @param {string} empty
 */
function listsGridHTML(lists, empty) {
	return lists.length > 0 ? grid("grid-lists", lists, listCard) : `<p class="empty">${esc(empty)}</p>`;
}
/**
 * Resolve favorite names from the local-first canonical cache, then fill gaps
 * from live Toolhub records. The order follows the user's saved order.
 * @returns {Promise<PersonalTools>}
 */
async function favoriteToolsForHome() {
	const names = favNames();
	if (names.length === 0) return { tools: [] };
	/** @type {Tool[]} */
	let cached = [];
	let cacheFailed = false;
	try {
		cached = await cachedCanonicalTools({ names, limit: names.length });
	} catch {
		cacheFailed = true;
	}
	const found = new Set(cached.map((tool) => tool.name));
	const missing = names.filter((name) => !found.has(name));
	/** @type {Tool[]} */
	let live = [];
	if (missing.length > 0) live = /** @type {Tool[]} */ (await getToolsByName(missing));
	const byName = new Map([...cached, ...live].map((tool) => [tool.name, tool]));
	const tools = /** @type {Tool[]} */ (names.map((name) => byName.get(name)).filter(Boolean));
	return { tools, error: cacheFailed && live.length === 0 && tools.length === 0 };
}

/** @returns {Promise<PersonalTools>} */
async function ownToolsForHome() {
	const data = await backendGetJson("/v1/me/tools/");
	if (!data || data.error || (!Array.isArray(data.verified) && !Array.isArray(data.possible))) {
		return { tools: [], error: true };
	}
	const tools = [];
	const seen = new Set();
	for (const item of [...(data.verified || []), ...(data.possible || [])]) {
		if (!item?.tool) continue;
		const tool = normalizeTool(item.tool);
		if (seen.has(tool.name)) continue;
		seen.add(tool.name);
		tools.push(tool);
	}
	return { tools };
}

/** @param {string} key @returns {Promise<PersonalHomeModel>} */
async function resolvePersonalHomeModel(key) {
	const [favorites, ownTools] = await Promise.all([
		favoriteToolsForHome().catch(() => ({ tools: [], error: true })),
		ownToolsForHome().catch(() => ({ tools: [], error: true }))
	]);
	if (!ownTools.error) writePersonalToolsCache(key, ownTools.tools);
	const allTools = [...favorites.tools, ...ownTools.tools];
	await Promise.all([attachEndorsements(allTools, { defer: true }), attachEvolvedSummaries(allTools)]);
	const model = { favorites, ownTools };
	personalHomeCache.set(key, { model, expiresAt: Date.now() + PERSONAL_HOME_TTL_MS });
	return model;
}

/** @param {string} key @returns {Promise<PersonalHomeModel>} */
function startPersonalHomeRequest(key) {
	const pending = personalHomeRequests.get(key);
	if (pending) return pending;
	const request = resolvePersonalHomeModel(key).finally(() => {
		personalHomeRequests.delete(key);
	});
	personalHomeRequests.set(key, request);
	return request;
}

/** @returns {Promise<PersonalHomeResult>} */
async function personalHomeModel() {
	const key = serverUserName() || "signed-in";
	const cached = personalHomeCache.get(key);
	if (cached && cached.expiresAt > Date.now()) return { model: cached.model };
	const stored = readPersonalToolsCache(key);
	if (!stored) return { model: await startPersonalHomeRequest(key) };

	const [favorites] = await Promise.all([favoriteToolsForHome().catch(() => ({ tools: [], error: true }))]);
	const ownTools = { tools: stored.tools };
	const allTools = [...favorites.tools, ...ownTools.tools];
	await Promise.all([attachEndorsements(allTools, { defer: true }), attachEvolvedSummaries(allTools)]);
	const model = { favorites, ownTools };
	personalHomeCache.set(key, { model, expiresAt: Date.now() + PERSONAL_HOME_TTL_MS });
	if (Date.now() - stored.updatedAt > PERSONAL_TOOLS_CACHE_TTL_MS) {
		return { model, refresh: startPersonalHomeRequest(key) };
	}
	return { model };
}

/**
 * @param {string} title
 * @param {string} href
 * @param {PersonalTools} section
 * @param {string} empty
 * @param {string} error
 */
function personalToolsSectionHTML(title, href, section, empty, error) {
	const body = section.loading
		? cardGridSkeleton("tool", 4)
		: section.error
			? `<p class="empty">${esc(error)}</p>`
			: toolsGridHTML(section.tools, empty);
	return `<div class="section-head"><h2>${esc(title)}</h2><a class="link" href="${href}">${t("home.viewAll", "View all")}</a></div>${body}`;
}
/**
 * @param {HomeModel} model
 * @param {IntentState} state
 */
function renderHomeMain(model, state) {
	if (model.personal) {
		return `${personalToolsSectionHTML(
			t("home.yourFavorites", "Your favorite tools"),
			"/favorites",
			model.personal.favorites,
			t("home.noFavorites", "You have not saved any favorite tools yet."),
			t("home.favoritesError", "Your favorites could not be loaded right now.")
		)}
		${personalToolsSectionHTML(
			t("home.yourTools", "Your tools"),
			"/my-tools",
			model.personal.ownTools,
			t("home.noOwnTools", "No Toolhub tools are currently associated with your account."),
			t("home.ownToolsError", "Your tools could not be loaded right now.")
		)}`;
	}
	const filtered = hasHomeFilters(state);
	const featuredHref = filtered ? searchHrefForState(state) : "/featured-tools";
	const fallbackNote = model.cacheFallback
		? `<p class="browse__count-note">${t("home.cachedCanonicalData", "Showing saved Toolhub data while live data refreshes.")}</p>
		`
		: "";
	return `${fallbackNote}
		<div class="section-head"><h2>${t("home.featuredTools", "Featured tools")}</h2><a class="link" href="${featuredHref}">${t("home.viewAll", "View all")}</a></div>
		${toolsGridHTML(model.featuredRanked.slice(0, 8), t("home.noToolsMatch", "No tools match this sentence."))}
		<div class="section-head"><h2>${t("home.mostListed", "Most listed")}</h2><a class="link" href="${filtered ? searchHrefForState(state) : "/lists"}">${filtered ? t("home.viewAll", "View all") : t("home.viewLists", "View lists")}</a></div>
		${toolsGridHTML(model.mostListedRanked.slice(0, 8), t("home.noListedToolsMatch", "No listed tools match this sentence."), (t, i) => toolCard(t, { rank: i + 1 }))}
		<div class="section-head"><h2>${t("home.curatedLists", "Curated lists")}</h2><a class="link" href="/lists">${t("home.viewAllLists", "View all lists")}</a></div>
		${listsGridHTML(model.lists.slice(0, 6), t("home.noCuratedListsMatch", "No curated lists match this sentence."))}`;
}

/**
 * Render every tool from every upstream administrator-featured list.
 * This is intentionally a complete aggregate view; ranking policy remains in
 * the shared context signal so the homepage and this page stay consistent.
 * @returns {Promise<{ title: string, html: string }>}
 */
export async function viewFeaturedTools() {
	const rawLists = await paginate("/lists/", { featured: "true" }, { pageSize: 30, maxPages: 10 });
	const lists = rawLists.map((/** @type {any} */ list) => normalizeList(list));
	const tools = dedupeTools(lists.flatMap((list) => list.tools || []));
	await Promise.all([attachEndorsements(tools, { defer: true }), attachEvolvedSummaries(tools)]);
	const ranked = rankFitsFirst(tools);
	return {
		title: t("home.featuredToolsDocTitle", "Featured tools — Toolhub"),
		html: `<div class="container page">
		<div class="section-head"><h1 class="page__title">${t("home.featuredTools", "Featured tools")}</h1><a class="link" href="/lists">${t("home.viewFeaturedLists", "View featured lists")}</a></div>
		<p class="page__intro">${t("home.featuredToolsIntro", "Tools included in public lists selected for the Toolhub landing page.")}</p>
		${toolsGridHTML(ranked, t("home.noFeaturedTools", "No featured tools found."))}
	</div>`
	};
}
/**
 * @param {IntentState} state
 * @returns {Promise<HomeModel>}
 */
async function homeSectionsModel(state) {
	const filters = homeFilterParams(state);
	const filtered = filters.toString() !== "";
	const listParams = { featured: "true", page_size: filtered ? "30" : "6" };
	const recentParams = new URLSearchParams(filters);
	recentParams.set("ordering", "-modified_date");
	recentParams.set("page_size", "5");
	const toolParams = new URLSearchParams(filters);
	toolParams.set("page_size", "24");
	// Each section degrades independently (one endpoint down still renders the
	// rest), but a *total* outage must not masquerade as an empty catalog — we
	// count failures and, if nothing loaded at all, rethrow to the error boundary.
	let failures = 0;
	const onFail = () => {
		failures += 1;
		// Stryker disable next-line ObjectLiteral: `{}` is equivalent to `{ results: [] }` — every consumer reads the value as `.results || []`.
		return { results: [] };
	};
	const [flists, recent, filteredToolsData] = await Promise.all([
		apiGet("/lists/", listParams).catch(onFail),
		apiGet("/search/tools/", /** @type {Record<string, string>} */ (/** @type {unknown} */ (recentParams))).catch(
			onFail
		),
		filtered
			? apiGet(
					"/search/tools/",
					/** @type {Record<string, string>} */ (/** @type {unknown} */ (toolParams))
				).catch(onFail)
			: Promise.resolve(null)
	]);
	const fallbackTools = failures > 0 ? await cachedCanonicalTools({ limit: filtered ? 24 : 18 }).catch(() => []) : [];
	/** @type {ToolList[]} */
	let lists = (flists.results || []).map((/** @type {any} */ list) => normalizeList(list));
	/** @type {Tool[]} */
	let featured;
	if (filtered) {
		featured = (filteredToolsData.results || []).map((/** @type {any} */ tool) => normalizeTool(tool));
		if (featured.length === 0 && fallbackTools.length > 0) {
			featured = fallbackTools.filter((tool) => toolMatchesIntent(tool, state));
		}
		await Promise.all([attachEndorsements(featured, { defer: true }), attachEvolvedSummaries(featured)]);
		const matchingNames = new Set(featured.map((t) => t.name));
		lists = lists.filter((l) =>
			// Stryker disable next-line ArrayDeclaration: normalizeList always sets `tools` to an array, so the `|| []` fallback is never taken — equivalent.
			(l.tools || []).some((t) => matchingNames.has(t.name) || toolMatchesIntent(t, state))
		);
	} else {
		// Stryker disable next-line ArrayDeclaration: normalizeList always sets `tools` to an array, so the `|| []` fallback is never taken — equivalent.
		featured = dedupeTools(lists.flatMap((l) => l.tools || []));
		if (featured.length === 0 && fallbackTools.length > 0) featured = fallbackTools.slice(0, 8);
		await Promise.all([attachEndorsements(featured, { defer: true }), attachEvolvedSummaries(featured)]);
	}
	let recentTools = (recent.results || []).map((/** @type {any} */ tool) => normalizeTool(tool));
	if (recentTools.length === 0 && fallbackTools.length > 0) recentTools = fallbackTools.slice(0, 5);
	await attachEvolvedSummaries(recentTools);
	// Something failed AND nothing loaded → this is an outage, not an empty
	// catalog. Rethrow so viewHome's caller (the router) shows the error page;
	// the interactive refreshHome path catches this and shows its own notice.
	if (failures > 0 && lists.length === 0 && featured.length === 0 && recentTools.length === 0) {
		throw new Error("home: live catalog unavailable");
	}
	const mostListed = sortedByEndorsements(featured);
	return {
		lists,
		featuredRanked: rankFitsFirst(featured),
		mostListedRanked: rankFitsFirst(mostListed),
		recentTools,
		cacheFallback: failures > 0 && fallbackTools.length > 0
	};
}

export async function viewHome() {
	// Live: total count, featured curated lists (with embedded tools), recent tools.
	const ctx = getUserContext();
	const initialState = intentStateFromContext(ctx);
	const authenticated = signedIn();
	const [home, initialModel] = await Promise.all([
		apiGet("/ui/home/").catch(() => ({})),
		authenticated
			? Promise.resolve({ lists: [], featuredRanked: [], mostListedRanked: [], recentTools: [] })
			: homeSectionsModel(initialState)
	]);
	initialModel.personal = authenticated
		? {
				favorites: { tools: [], loading: true },
				ownTools: { tools: [], loading: true }
			}
		: undefined;
	const total = home.total_tools || 0;
	const intentAxis = initialState.axis;
	const intentTerm = initialState.term;
	const intentWiki = initialState.wiki;

	const myToolsBtn = button(t("home.myTools", "My tools"), {
		// Stryker disable next-line StringLiteral: `button()` defaults `variant` to "outline", so mutating this explicit "outline" to "" produces identical markup — equivalent.
		variant: "outline",
		href: "/my-tools"
	});

	const html = `
	<section class="hero">
		<h1 class="hero__title">${t("home.heroTitle", "The community catalog of Wikimedia tools")}</h1>
		<div class="hero__explore">
			<form class="intent" data-intent-form data-axis="${esc(intentAxis)}" data-term="${esc(intentTerm)}" data-wiki="${esc(intentWiki)}">
				<div class="intent__sentence" aria-label="${t("home.buildAToolSearch", "Build a tool search")}">
					<span class="intent__copy">${t("home.iWantToSeeTools", "I want to see tools")}</span>
					${intentChoice("axis", itemLabel(intentAxisItems(), intentAxis), intentAxisItems(), intentAxis)}
					${intentChoice("term", itemLabel(intentTermItems(intentAxis), intentTerm), intentTermItems(intentAxis), intentTerm)}
					<span class="intent__copy">${t("home.on", "on")}</span>
					${intentChoice("wiki", itemLabel(projectItems(), intentWiki), projectItems(), intentWiki)}
					<button class="intent__go" type="submit">${t("home.seeTools", "See tools")}</button>
					<button class="intent__clear" type="button" data-intent-clear${hasHomeFilters(initialState) ? "" : " disabled"}>${t("home.clear", "clear")}</button>
				</div>
			</form>
		</div>
		<div class="hero__or" aria-hidden="true">${t("home.or", "or")}</div>
		<form class="search" role="search" data-home-search>
			<label for="home-q" class="skip-label">${t("home.searchTools", "Search tools")}</label>
			<input id="home-q" class="search__input" type="search" aria-label="${t("home.searchTools", "Search tools")}" placeholder="${t("home.searchPlaceholder", "Search {count}…", { count: esc(countLabel(total, t("home.toolOne", "tool"), t("home.toolOther", "tools"))) })}" autocomplete="off" />
			${button(t("home.search", "Search"), { variant: "primary", type: "submit", cls: "search__btn" })}
		</form>
	</section>
	<div class="container layout">
		<div class="layout__main home-results" data-home-main aria-live="polite">
			${renderHomeMain(initialModel, initialState)}
		</div>
		<aside class="layout__side">
			<div class="panel"><h3 class="panel__title">${t("home.recentlyUpdated", "Recently updated")}</h3><ul class="recent" data-home-recent aria-live="polite">${recentToolsHTML(initialModel.recentTools)}</ul></div>
			<div class="panel panel--cta"><div class="cta__icon" aria-hidden="true">${icon("idea", "icon--lg")}</div><h3>${t("home.ctaTitle", "Built a tool for Wikimedia?")}</h3><p>${tWithElements("home.ctaBody", "Add a {toolinfo} to your repository, or register it from My tools so other Wikimedians can find it.", { toolinfo: "<code>toolinfo.json</code>" })}</p>${myToolsBtn}</div>
		</aside>
	</div>`;
	return {
		title: t("home.docTitle", "Toolhub — discover Wikimedia tools"),
		html,
		mount() {
			/** @type {HTMLElement} */ ($("[data-home-search]")).addEventListener("submit", (e) => {
				e.preventDefault();
				const q = /** @type {HTMLInputElement} */ ($input("#home-q")).value.trim();
				navigateTo(`/search${q ? `?q=${encodeURIComponent(q)}` : ""}`);
			});
			const intentForm = /** @type {HTMLElement} */ ($("[data-intent-form]"));
			const homeMain = /** @type {HTMLElement} */ ($("[data-home-main]"));
			const homeRecent = /** @type {HTMLElement} */ ($("[data-home-recent]"));
			const state = {
				// Stryker disable next-line StringLiteral,LogicalOperator: intentStateFromContext always yields axis "audiences", so data-axis is never empty and the `|| "audiences"` fallback is dead — equivalent.
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
			/** @param {string | null} kind @param {boolean | string | null | undefined} on */
			const setMenu = (kind, on) => {
				closeMenus();
				if (!on) return;
				const menu = $(`[data-intent-menu="${kind}"]`, intentForm);
				const trigger = $(`[data-intent-trigger="${kind}"]`, intentForm);
				// Stryker disable next-line ConditionalExpression,LogicalOperator: setMenu is only ever called with a kind from an existing trigger, so both elements are always found — this defensive guard is unreachable.
				if (!menu || !trigger) return;
				menu.hidden = false;
				trigger.setAttribute("aria-expanded", "true");
			};
			const syncIntent = () => {
				const axisItems = intentAxisItems();
				const termItems = intentTermItems(state.axis);
				const wikiItems = projectItems();
				/** @type {HTMLElement} */ ($('[data-intent-label="axis"]', intentForm)).textContent = itemLabel(
					axisItems,
					state.axis
				);
				/** @type {HTMLElement} */ ($('[data-intent-label="term"]', intentForm)).textContent = itemLabel(
					termItems,
					state.term
				);
				/** @type {HTMLElement} */ ($('[data-intent-label="wiki"]', intentForm)).textContent = itemLabel(
					wikiItems,
					state.wiki
				);
				/** @type {HTMLElement} */ ($('[data-intent-menu="axis"]', intentForm)).innerHTML = intentOptionButtons(
					"axis",
					axisItems,
					state.axis
				);
				/** @type {HTMLElement} */ ($('[data-intent-menu="term"]', intentForm)).innerHTML = intentOptionButtons(
					"term",
					termItems,
					state.term
				);
				/** @type {HTMLElement} */ ($('[data-intent-menu="wiki"]', intentForm)).innerHTML = intentOptionButtons(
					"wiki",
					wikiItems,
					state.wiki
				);
				const clear = $input("[data-intent-clear]", intentForm);
				// Stryker disable next-line ConditionalExpression: the clear control is always present in the rendered form, so this guard is always true — equivalent.
				if (clear) clear.disabled = !hasHomeFilters(state);
			};
			const persistIntent = () => {
				setUserContext({ wiki: state.wiki, role: state.axis === "audiences" ? state.term : "" });
			};
			/** @param {HomeModel} model */
			const renderHomeModel = (model) => {
				homeMain.innerHTML = renderHomeMain(model, state);
				homeRecent.innerHTML = recentToolsHTML(model.recentTools);
			};
			const renderHomeError = () => {
				homeMain.innerHTML = `<p class="empty">${t("home.refreshError", "Unable to refresh tools right now.")}</p>`;
				homeRecent.innerHTML = `<li class="recent__empty">${t("home.recentRefreshError", "Unable to refresh recently updated tools.")}</li>`;
			};
			if (authenticated) {
				personalHomeModel().then(({ model: personal, refresh }) => {
					if (!homeMain.isConnected) return;
					initialModel.personal = personal;
					renderHomeModel(initialModel);
					if (refresh) {
						refresh.then((next) => {
							if (!homeMain.isConnected || (next.ownTools.error && personal.ownTools.tools.length > 0)) {
								return;
							}
							initialModel.personal = next;
							renderHomeModel(initialModel);
						});
					}
				});
			}
			const refreshHome = async () => {
				// Stryker disable next-line UpdateOperator: refreshSeq is only ever compared for equality to detect a superseded refresh; ++ and -- both produce a unique value per call, so the stale-guard behaves identically — equivalent.
				const seq = ++refreshSeq;
				homeMain.setAttribute("aria-busy", "true");
				homeRecent.setAttribute("aria-busy", "true");
				try {
					const model = await homeSectionsModel(state);
					if (seq !== refreshSeq) return;
					model.personal = initialModel.personal;
					renderHomeModel(model);
				} catch {
					if (seq !== refreshSeq) return;
					renderHomeError();
				} finally {
					// Stryker disable next-line ConditionalExpression: this only suppresses the busy-flag clear for a superseded refresh; the active refresh still clears it, so the final observable state is identical — equivalent.
					if (seq === refreshSeq) {
						homeMain.removeAttribute("aria-busy");
						homeRecent.removeAttribute("aria-busy");
					}
				}
			};
			intentForm.addEventListener("click", (e) => {
				const target = /** @type {EventTarget} */ (e.target);
				const trigger = target.closest("[data-intent-trigger]");
				if (trigger) {
					e.preventDefault();
					const kind = trigger.getAttribute("data-intent-trigger");
					const menu = $(`[data-intent-menu="${kind}"]`, intentForm);
					setMenu(kind, menu && menu.hidden);
					return;
				}
				const option = target.closest("[data-intent-option]");
				if (!option) return;
				e.preventDefault();
				const kind = option.getAttribute("data-intent-option");
				const value = option.getAttribute("data-value") || "";
				if (kind === "axis") {
					// Stryker disable next-line StringLiteral: axis options only carry data-value "audiences" or "tasks" (never empty), so the `|| "audiences"` fallback is dead — equivalent.
					state.axis = value || "audiences";
					state.term = "";
				} else if (kind === "term") {
					state.term = value;
				} else {
					// the only remaining option kind is "wiki"
					state.wiki = value;
				}
				syncIntent();
				persistIntent();
				refreshHome();
				closeMenus();
			});
			/** @type {HTMLElement} */ ($("[data-intent-clear]", intentForm)).addEventListener("click", () => {
				state.axis = "audiences";
				state.term = "";
				state.wiki = "";
				syncIntent();
				persistIntent();
				refreshHome();
				closeMenus();
			});
			// Remove the previous home mount's document listeners before adding this
			// one's, so navigating back to home never accumulates handlers.
			// Stryker disable next-line ConditionalExpression: forcing this guard true (on the first-ever mount, when intentDocClick is null) only calls removeEventListener with a null listener — a no-op — so it is unobservable: equivalent.
			if (intentDocClick) document.removeEventListener("click", intentDocClick);
			// Stryker disable next-line ConditionalExpression: as above — removing a null/absent keydown listener is a no-op: equivalent.
			if (intentDocKeydown) document.removeEventListener("keydown", intentDocKeydown);
			intentDocClick = (e) => {
				if (!intentForm.contains(/** @type {Node} */ (e.target))) closeMenus();
			};
			intentDocKeydown = (e) => {
				if (e.key === "Escape") closeMenus();
			};
			document.addEventListener("click", intentDocClick);
			document.addEventListener("keydown", intentDocKeydown);
			intentForm.addEventListener("submit", (e) => {
				e.preventDefault();
				persistIntent();
				navigateTo(searchHrefForState(state));
			});
		}
	};
}
