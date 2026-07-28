// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, esc } from "../lib/core/dom.js";
import { t } from "../lib/core/i18n.js";
import { parseRoute } from "../lib/core/routing.js";
import { signedIn } from "../lib/core/session.js";
import { button } from "../lib/atoms/button.js";
import { STATIC, prosePage, signInPage, viewApiDocs, viewContribute, viewNotFound, viewStatic } from "./static.js";

// Route modules are loaded on demand so first paint does not require every page's
// module graph. On Toolforge this also avoids a burst of static-file requests,
// where one transient 503 would otherwise blank the native ES-module app.
// render() already awaits dispatch(), so a returned Promise<View> just works.

/** @typedef {{ title: string, html: string, mount?: () => void }} View */
/** @typedef {View | Promise<View>} ViewResult */
/** @template T @typedef {Promise<T>} ModuleResult */

/**
 * Retry a failed dynamic import with a unique query string. Browsers may cache a
 * failed module load for the original specifier; the retry specifier forces a
 * fresh static-file request and lets render() recover into an error page if it
 * still fails.
 * @template T
 * @param {string} specifier
 * @param {() => ModuleResult<T>} loader
 * @returns {ModuleResult<T>}
 */
function loadRouteModule(specifier, loader) {
	return loader().catch(() => import(`${specifier}?retry=${Date.now().toString(36)}`));
}
const loadHome = () => loadRouteModule("./home.js", () => import("./home.js"));
const loadSearch = () => loadRouteModule("./search.js", () => import("./search.js"));
const loadTool = () => loadRouteModule("./tool.js", () => import("./tool.js"));
const loadAuthors = () => loadRouteModule("./authors.js", () => import("./authors.js"));
const loadLists = () => loadRouteModule("./lists.js", () => import("./lists.js"));
const loadToolForms = () => loadRouteModule("./toolforms.js", () => import("./toolforms.js"));
const loadAccountSettings = () => loadRouteModule("./account-settings.js", () => import("./account-settings.js"));
const loadDeveloperSettings = () => loadRouteModule("./developer-settings.js", () => import("./developer-settings.js"));
const loadMyTools = () => loadRouteModule("./my-tools.js", () => import("./my-tools.js"));
const loadRecent = () => loadRouteModule("./recent.js", () => import("./recent.js"));
const loadMembers = () => loadRouteModule("./members.js", () => import("./members.js"));
const loadCrawler = () => loadRouteModule("./crawler.js", () => import("./crawler.js"));
const loadAudit = () => loadRouteModule("./audit.js", () => import("./audit.js"));
const loadGraph = () => loadRouteModule("./graph.js", () => import("./graph.js"));
const loadExperiments = () => loadRouteModule("./experiments.js", () => import("./experiments.js"));
const loadStyleguide = () => loadRouteModule("./styleguide.js", () => import("./styleguide.js"));

/** @type {((title: string, lead?: string) => View) | null} */
let signInFallback = null;
/**
 * @param {(title: string, lead?: string) => View} fn
 * @returns {void}
 */
export function setSignInFallback(fn) {
	signInFallback = fn;
}
/**
 * @param {() => ViewResult} viewFn
 * @param {string} title
 * @param {string} [lead]
 * @returns {ViewResult}
 */
export function requireSignIn(viewFn, title, lead) {
	return signedIn() ? viewFn() : /** @type {(title: string, lead?: string) => View} */ (signInFallback)(title, lead);
}
setSignInFallback(signInPage);

export const ROUTES = {
	lists: () => loadLists().then((m) => m.viewLists()),
	graph: () => loadGraph().then((m) => m.viewGraph()),
	"published-lists": () => loadLists().then((m) => m.viewLists()),
	"my-lists": () =>
		requireSignIn(
			() => loadLists().then((m) => m.viewMyLists()),
			t("router.myListsTitle", "Your lists"),
			t("router.myListsLead", "See and manage the lists you've created.")
		),
	favorites: () =>
		requireSignIn(
			() => loadLists().then((m) => m.viewFavorites()),
			t("router.favoritesTitle", "Favorites"),
			t("router.favoritesLead", "Your saved tools, all in one place.")
		),
	"add-or-remove-tools": () =>
		requireSignIn(
			() => loadToolForms().then((m) => m.viewAddTools()),
			t("router.addToolsTitle", "Add or remove tools"),
			t("router.addToolsLead", "Register a toolinfo.json URL to be crawled, or create a tool record directly.")
		),
	account: () =>
		requireSignIn(
			() => loadAccountSettings().then((m) => m.viewAccountSettings()),
			t("router.accountTitle", "Evolved data settings"),
			t("router.accountLead", "Export or delete Evolved-local data for this Toolhub sign-in.")
		),
	"my-tools": () =>
		requireSignIn(
			() => loadMyTools().then((m) => m.viewMyTools()),
			t("router.myToolsTitle", "My tools"),
			t("router.myToolsLead", "View Toolhub tools maintained by this account.")
		),
	"developer-settings": () =>
		requireSignIn(
			() => loadDeveloperSettings().then((m) => m.viewDeveloperSettings()),
			t("router.devSettingsTitle", "Developer settings"),
			t("router.devSettingsLead", "Manage your API tokens and registered OAuth applications.")
		),
	login: () =>
		signInPage(
			t("router.signInTitle", "Sign in"),
			t("router.signInLead", "Sign in to save favourites, build lists, and edit tool information.")
		),
	recent: () => loadRecent().then((m) => m.viewRecent()),
	members: () => loadMembers().then((m) => m.viewMembers()),
	"crawler-history": () => loadCrawler().then((m) => m.viewCrawler()),
	"audit-logs": () => loadAudit().then((m) => m.viewAudit()),
	"api-docs": viewApiDocs,
	contribute: viewContribute,
	experiments: () => loadExperiments().then((m) => m.viewExperiments()),
	styleguide: () => loadStyleguide().then((m) => m.viewStyleguide())
};
/** Tool sub-routes (/tools/:name and its create/edit/history variants). @param {string[]} seg */
function dispatchToolRoute(seg) {
	if (seg[1] === "create") {
		return requireSignIn(
			() => loadToolForms().then((m) => m.viewToolForm(null)),
			t("router.submitToolTitle", "Submit a tool"),
			t("router.submitToolLead", "Create a new tool record — title, description, URL and more.")
		);
	}
	const nm = decodeURIComponent(seg[1]);
	if (seg[2] === "edit") {
		return requireSignIn(
			() => loadToolForms().then((m) => m.viewToolForm(nm)),
			t("router.editToolTitle", "Edit tool"),
			t(
				"router.editToolLead",
				"Edit this tool's core information — title, description, URL and more. Only the owner or an administrator can change core data."
			)
		);
	}
	if (seg[2] === "edit-annotations") {
		return requireSignIn(
			() => loadToolForms().then((m) => m.viewAnnotationsEdit(nm)),
			t("router.editAnnotationsTitle", "Edit annotations"),
			t(
				"router.editAnnotationsLead",
				"Add or refine community annotations for this tool — audiences, tasks and more."
			)
		);
	}
	if (seg[2] === "history") return loadTool().then((m) => (seg[3] ? m.viewDiffStub(nm) : m.viewToolHistory(nm)));
	return loadTool().then((m) => m.viewTool(nm));
}
/** List sub-routes (/lists/:id and its create/edit/history variants). @param {string[]} seg */
function dispatchListRoute(seg) {
	if (seg[1] === "create") {
		return requireSignIn(
			() => loadLists().then((m) => m.viewListEdit(null)),
			t("router.createListTitle", "Create a list"),
			t("router.createListLead", "Create a new list to group and share useful tools.")
		);
	}
	if (seg[2] === "edit") {
		return requireSignIn(
			() => loadLists().then((m) => m.viewListEdit(decodeURIComponent(seg[1]))),
			t("router.editListTitle", "Edit list"),
			t("router.editListLead", "Edit this list's title, description and tools.")
		);
	}
	if (seg[2] === "history") {
		return prosePage(
			t("router.listHistoryTitle", "List history"),
			`<p>Revision history for this list is available on the <a href="https://toolhub.wikimedia.org/" target="_blank" rel="noopener nofollow">${t("router.liveSite", "live site")}</a>.</p>`
		);
	}
	return loadLists().then((m) => m.viewList(decodeURIComponent(seg[1])));
}
export function dispatch() {
	const { path } = parseRoute();
	const seg = path.split("/").filter(Boolean); // e.g. ["tools","foo"]
	if (path === "/") return loadHome().then((m) => m.viewHome());
	if (seg[0] === "user" && seg[1] === "login") {
		return signInPage(
			t("router.signInTitle", "Sign in"),
			t("router.signInLead", "Sign in to save favourites, build lists, and edit tool information.")
		);
	}
	if (seg[0] === "user" && seg[1] === "logout") {
		return signInPage(
			t("router.signedOutTitle", "Signed out"),
			t("router.signedOutLead", "You are signed out of this Toolhub prototype.")
		);
	}
	if (seg[0] === "search") return loadSearch().then((m) => m.viewSearch());
	if (seg[0] === "by" && seg[1]) return loadAuthors().then((m) => m.viewAuthor(decodeURIComponent(seg[1])));
	if (seg[0] === "tools" && seg[1]) return dispatchToolRoute(seg);
	if (seg[0] === "lists" && seg[1]) return dispatchListRoute(seg);
	if (ROUTES[/** @type {keyof typeof ROUTES} */ (seg[0])]) {
		return ROUTES[/** @type {keyof typeof ROUTES} */ (seg[0])]();
	}
	if (STATIC[/** @type {keyof typeof STATIC} */ (seg[0])]) return viewStatic(seg[0]);
	return viewNotFound();
}
/**
 * @param {string} pathHash
 * @param {string | null} href
 * @returns {boolean}
 */
function navHrefMatches(pathHash, href) {
	if (href === "/search") return pathHash === "/search" || pathHash.startsWith("/search/");
	if (href === "/lists") return pathHash === "/lists" || pathHash.startsWith("/lists/");
	if (href === "/graph") return pathHash === "/graph" || pathHash.startsWith("/graph/");
	return href === pathHash;
}
export function setActiveNav() {
	const h = parseRoute().path;
	$$("#nav-links, #nav-mobile").forEach((nav) => {
		let currentSet = false;
		$$("a", nav).forEach((a) => {
			const href = a.getAttribute("href");
			const matches = navHrefMatches(h, href);
			const active = matches && !currentSet;
			if (active) currentSet = true;
			a.classList.toggle("is-active", active);
			if (active) a.setAttribute("aria-current", "page");
			else a.removeAttribute("aria-current");
		});
	});
}
/** @type {string | null} */
export let lastPath = null;
export let navSeq = 0;
/** @param {string} [_path] */
export const loadingHTML = (_path) => `<div class="container page route-loading" role="status" aria-live="polite">
	<div class="route-loading__panel">
		<span class="spinner" aria-hidden="true"></span>
		<span class="route-loading__label">${t("router.loadingToolhubData", "Loading Toolhub data")}</span>
	</div>
</div>`;
/** @param {unknown} e */
export const errorHTML = (
	e
) => `<div class="container page errorpage"><h1>${t("router.loadErrorTitle", "Couldn't load live data")}</h1>
	<p class="prose">${t("router.loadErrorBody", "The Toolhub API didn't respond ({msg}).", { msg: esc(String((e && /** @type {{ message?: unknown }} */ (e).message) || e)) })}</p>
	${button(t("router.backToHome", "Back to home"), { variant: "primary", href: "/" })}</div>`;
// How long a view may load before we replace the page with a spinner. Below this,
// the current page stays on screen — fast/cached loads never flash a spinner.
const SPINNER_DELAY = 250;
/**
 * @param {HTMLElement} viewEl
 * @param {View} view
 * @param {string} path
 * @returns {void}
 */
function commitView(viewEl, view, path) {
	viewEl.innerHTML = view.html;
	viewEl.setAttribute("aria-busy", "false");
	document.body.classList.toggle("on-home", path === "/");
	document.title = view.title || "Toolhub";
	if (typeof view.mount === "function") view.mount();
	setActiveNav();
	if (path !== lastPath) {
		window.scrollTo({ top: 0, behavior: "auto" });
		const h1 = $("#view h1") || viewEl;
		h1.setAttribute("tabindex", "-1");
		h1.focus({ preventScroll: true });
		lastPath = path;
	}
}
export async function render() {
	document.dispatchEvent(new Event("toolhub:route-render-start"));
	const seq = ++navSeq;
	const { path } = parseRoute();
	const viewEl = /** @type {HTMLElement} */ ($("#view"));
	/** @type {ReturnType<typeof setTimeout> | null} */
	let spinnerTimer = null;
	document.body.classList.toggle("on-home", path === "/");
	setActiveNav();
	if (path !== lastPath) {
		viewEl.setAttribute("aria-busy", "true"); // announce busy immediately (a11y)
		if (lastPath === null) {
			viewEl.innerHTML = loadingHTML(path); // first load: show route structure immediately
		} else {
			// Keep the current page visible; only swap in the spinner if the next
			// view is genuinely slow. Cached navigations resolve first and skip it.
			spinnerTimer = setTimeout(() => {
				if (seq === navSeq) viewEl.innerHTML = loadingHTML(path);
			}, SPINNER_DELAY);
		}
	}
	let view;
	try {
		view = await dispatch();
	} catch (e) {
		view = { title: t("router.errorTitle", "Error — Toolhub"), html: errorHTML(e) };
	}
	// Stryker disable next-line ConditionalExpression: when spinnerTimer is null the guard is skipped; forcing it true only runs clearTimeout(null), a documented no-op, so behaviour is identical.
	if (spinnerTimer) clearTimeout(spinnerTimer); // resolved (or superseded) before the delay
	if (seq !== navSeq) return; // a newer navigation superseded this one
	commitView(viewEl, view, path);
}
