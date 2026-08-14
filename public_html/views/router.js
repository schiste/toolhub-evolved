// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, esc } from "../lib/core/dom.js";
import { t, tWithElements } from "../lib/core/i18n.js";
import { navigateTo, parseRoute } from "../lib/core/routing.js";
import { serverSessionResolved, signedIn } from "../lib/core/session.js";
import { button } from "../lib/atoms/button.js";
import { routeSkeletonHTML } from "../lib/molecules/skeleton.js";
import { isStaticSlug } from "./static-routes.js";

// Route modules are loaded on demand so first paint does not require every page's
// module graph. On Toolforge this also avoids a burst of static-file requests,
// where one transient 503 would otherwise blank the native ES-module app.
// render() already awaits dispatch(), so a returned Promise<View> just works.

/** @typedef {{ title: string, html: string, mount?: () => void, styles?: string[] }} View */
/** @typedef {View | Promise<View>} ViewResult */
/** @template T @typedef {Promise<T>} ModuleResult */
export const ROUTE_MODULE_TIMEOUT_MS = 10_000;

/**
 * A dynamic import can remain pending indefinitely when a static response is
 * interrupted. Turn that browser-level stall into a normal rejected load so
 * the router can retry once and ultimately render its error boundary.
 * @template T
 * @param {() => ModuleResult<T>} loader
 * @returns {ModuleResult<T>}
 */
function loadModuleAttempt(loader) {
	return new Promise((resolve, reject) => {
		const timer = setTimeout(() => reject(new Error("Route module load timed out")), ROUTE_MODULE_TIMEOUT_MS);
		loader().then(
			(module) => {
				clearTimeout(timer);
				resolve(module);
			},
			(error) => {
				clearTimeout(timer);
				reject(error);
			}
		);
	});
}

/**
 * Retry a failed dynamic import with a unique query string. Browsers may cache a
 * failed module load for the original specifier; the retry specifier forces a
 * fresh static-file request and lets render() recover into an error page if it
 * still fails.
 * @template T
 * @param {string} specifier
 * @param {() => ModuleResult<T>} loader
 * @param {(() => ModuleResult<T>) | undefined} [retryLoader]
 * @returns {ModuleResult<T>}
 */
export function loadRouteModule(specifier, loader, retryLoader = undefined) {
	return loadModuleAttempt(loader).catch(() =>
		loadModuleAttempt(retryLoader || (() => import(`${specifier}?retry=${Date.now().toString(36)}`)))
	);
}
const loadHome = () => loadRouteModule("./home.js", () => import("./home.js"));
const loadSearch = () => loadRouteModule("./search.js", () => import("./search.js"));
const loadTool = () => loadRouteModule("./tool.js", () => import("./tool.js"));
const loadAuthors = () => loadRouteModule("./authors.js", () => import("./authors.js"));
const loadAccounts = () => loadRouteModule("./accounts.js", () => import("./accounts.js"));
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
const loadChangelog = () => loadRouteModule("./changelog.js", () => import("./changelog.js"));
const loadStatistics = () => loadRouteModule("./statistics.js", () => import("./statistics.js"));
const loadWorkers = () => loadRouteModule("./workers.js", () => import("./workers.js"));
const loadDigests = () => loadRouteModule("./digests.js", () => import("./digests.js"));
// The prose pages, the sign-in page and the 404 all live in static.js — the
// largest module in the app. Loading it on demand like any other route keeps it
// out of the first paint; every use below is a render, reached only when that
// page is actually being shown.
const loadStatic = () => loadRouteModule("./static.js", () => import("./static.js"));
/** @param {string} title @param {string} [lead] @returns {Promise<View>} */
const staticSignInPage = (title, lead) => loadStatic().then((m) => m.signInPage(title, lead));

/** @type {Map<string, Promise<void>>} */
const routeStyleLoads = new Map();

/**
 * @param {string} href
 * @returns {string}
 */
function routeStyleKey(href) {
	return (
		href
			.split("/")
			.pop()
			?.replace(/\.css(?:\?.*)?$/, "")
			.replaceAll(/[^a-z0-9_-]+/gi, "-") || "route"
	);
}

/**
 * @param {string} href
 * @returns {HTMLLinkElement | null}
 */
function findRouteStyle(href) {
	return (
		/** @type {HTMLLinkElement[]} */ ([
			...document.querySelectorAll('link[rel="stylesheet"][href], link[data-route-style][href]')
		]).find((link) => link.getAttribute("href") === href) || null
	);
}

/**
 * @param {HTMLLinkElement} link
 * @returns {boolean}
 */
function styleLoaded(link) {
	try {
		return Boolean(link.sheet);
	} catch {
		return false;
	}
}

/**
 * @param {string} href
 * @returns {Promise<void>}
 */
function loadRouteStyle(href) {
	const loaded = findRouteStyle(href);
	if (loaded && styleLoaded(loaded)) return Promise.resolve();
	if (routeStyleLoads.has(href)) return /** @type {Promise<void>} */ (routeStyleLoads.get(href));

	const link = loaded || document.createElement("link");
	if (!loaded) {
		link.rel = "stylesheet";
		link.href = href;
		link.dataset.routeStyle = routeStyleKey(href);
	}

	const promise = /** @type {Promise<void>} */ (
		new Promise((resolve) => {
			let settled = false;
			/** @type {ReturnType<typeof setTimeout> | null} */
			let timer = null;
			const done = () => {
				if (settled) return;
				settled = true;
				if (timer) window.clearTimeout(timer);
				link.removeEventListener("load", done);
				link.removeEventListener("error", done);
				resolve();
			};
			timer = window.setTimeout(done, 2000);
			link.addEventListener("load", done);
			link.addEventListener("error", done);
			if (!loaded) document.head.append(link);
			if (styleLoaded(link)) done();
		})
	);
	routeStyleLoads.set(href, promise);
	return promise;
}

/**
 * @param {View} view
 * @returns {Promise<void>}
 */
function loadViewStyles(view) {
	if (!view.styles?.length) return Promise.resolve();
	return Promise.all(view.styles.map((href) => loadRouteStyle(href))).then(() => {});
}

/** @type {((title: string, lead?: string) => ViewResult) | null} */
let signInFallback = null;
/**
 * @param {(title: string, lead?: string) => ViewResult} fn
 * @returns {void}
 */
export function setSignInFallback(fn) {
	signInFallback = fn;
}
/**
 * @param {string} title
 * @param {string} [lead]
 * @returns {View}
 */
export function authLoadingPage(title, lead) {
	return {
		title: `${title} - Toolhub`,
		html: `<div class="container page route-loading route-loading--auth" role="status" aria-live="polite">
			<h1 class="page__title">${esc(title)}</h1>
			${lead ? `<p class="page__intro">${esc(lead)}</p>` : ""}
			<div class="route-loading__panel">
				<span class="spinner" aria-hidden="true"></span>
				<span class="route-loading__label">${t("router.loadingToolhubAccount", "Loading your Toolhub account")}</span>
			</div>
		</div>`
	};
}
/**
 * @param {() => ViewResult} viewFn
 * @param {string} title
 * @param {string} [lead]
 * @returns {ViewResult}
 */
export function requireSignIn(viewFn, title, lead) {
	if (!serverSessionResolved()) return authLoadingPage(title, lead);
	return signedIn()
		? viewFn()
		: /** @type {(title: string, lead?: string) => ViewResult} */ (signInFallback)(title, lead);
}
setSignInFallback(staticSignInPage);

export const ROUTES = {
	"featured-tools": () => loadHome().then((m) => m.viewFeaturedTools()),
	lists: () => loadLists().then((m) => m.viewLists()),
	graph: () => loadGraph().then((m) => m.viewGraph()),
	"published-lists": () => loadLists().then((m) => m.viewLists()),
	changelog: () => loadChangelog().then((m) => m.viewChangelog()),
	statistics: () => loadStatistics().then((m) => m.viewStatistics()),
	workers: () => loadWorkers().then((m) => m.viewWorkers()),
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
	"add-or-remove-tools": () => redirectTo("/my-tools"),
	account: () => redirectTo("/preferences"),
	preferences: () =>
		requireSignIn(
			() => loadAccountSettings().then((m) => m.viewAccountSettings()),
			t("router.preferencesTitle", "Preferences"),
			t("router.preferencesLead", "Manage Evolved-specific preferences and local account data.")
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
			t("router.devSettingsLead", "Manage Evolved developer features for this Toolhub sign-in.")
		),
	login: () =>
		staticSignInPage(
			t("router.signInTitle", "Sign in"),
			t("router.signInLead", "Sign in to save favourites, build lists, and edit tool information.")
		),
	recent: () => loadRecent().then((m) => m.viewRecent()),
	members: () => loadMembers().then((m) => m.viewMembers()),
	"crawler-history": () => loadCrawler().then((m) => m.viewCrawler()),
	"audit-logs": () => loadAudit().then((m) => m.viewAudit()),
	"api-docs": () => loadStatic().then((m) => m.viewApiDocs()),
	contribute: () => loadStatic().then((m) => m.viewContribute()),
	experiments: () => loadExperiments().then((m) => m.viewExperiments()),
	styleguide: () => loadStyleguide().then((m) => m.viewStyleguide())
};
/** Tool sub-routes (/tools/:name and its create/edit/history variants). @param {string[]} seg */
function dispatchToolRoute(seg) {
	if (seg[1] === "create") {
		return redirectTo("/my-tools");
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
		return loadStatic().then((m) =>
			m.prosePage(
				t("router.listHistoryTitle", "List history"),
				`<p>${tWithElements("router.listHistoryBody", "Revision history for this list is available on the $1.", { html: `<a href="https://toolhub.wikimedia.org/" target="_blank" rel="noopener nofollow">${esc(t("router.liveSite", "live site"))}</a>` })}</p>`
			)
		);
	}
	return loadLists().then((m) => m.viewList(decodeURIComponent(seg[1])));
}
export function dispatch() {
	const { path } = parseRoute();
	const seg = path.split("/").filter(Boolean); // e.g. ["tools","foo"]
	if (path === "/") return loadHome().then((m) => m.viewHome());
	if (seg[0] === "user" && seg[1] === "login") {
		return staticSignInPage(
			t("router.signInTitle", "Sign in"),
			t("router.signInLead", "Sign in to save favourites, build lists, and edit tool information.")
		);
	}
	if (seg[0] === "user" && seg[1] === "logout") {
		return staticSignInPage(
			t("router.signedOutTitle", "Signed out"),
			t("router.signedOutLead", "You are signed out of this Toolhub prototype.")
		);
	}
	if (seg[0] === "search") return loadSearch().then((m) => m.viewSearch());
	if (seg[0] === "by" && seg[1]) return loadAuthors().then((m) => m.viewAuthor(decodeURIComponent(seg[1])));
	if (seg[0] === "people" && !seg[1]) {
		return new URLSearchParams(location.search).has("account")
			? loadAccounts().then((m) => m.viewAccounts())
			: loadAuthors().then((m) => m.viewPeople());
	}
	if (seg[0] === "people" && seg[1]) return loadAuthors().then((m) => m.viewPerson(decodeURIComponent(seg[1])));
	if (seg[0] === "tools" && seg[1]) return dispatchToolRoute(seg);
	if (seg[0] === "lists" && seg[1]) return dispatchListRoute(seg);
	if (seg[0] === "digests") {
		const action = seg[1] === "confirm" || seg[1] === "unsubscribe" ? seg[1] : undefined;
		return loadDigests().then((module) => module.viewDigests(action ? undefined : seg[1], seg[2], action));
	}
	if (ROUTES[/** @type {keyof typeof ROUTES} */ (seg[0])]) {
		return ROUTES[/** @type {keyof typeof ROUTES} */ (seg[0])]();
	}
	if (isStaticSlug(seg[0])) return loadStatic().then((m) => m.viewStatic(seg[0]));
	return loadStatic().then((m) => m.viewNotFound());
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
	if (href === "/digests") return pathHash === "/digests" || pathHash.startsWith("/digests/");
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
/** @param {string} [path] */
export const loadingHTML = (path) =>
	routeSkeletonHTML(path) ||
	`<div class="container page route-loading" role="status" aria-live="polite">
	<div class="route-loading__panel">
		<span class="spinner" aria-hidden="true"></span>
		<span class="route-loading__label">${t("router.loadingToolhubData", "Loading Toolhub data")}</span>
		</div>
	</div>`;
/** @param {string} href */
function redirectTo(href) {
	return {
		title: t("router.redirectingTitle", "Redirecting - Toolhub"),
		html: loadingHTML(href),
		mount: () => navigateTo(href, { replace: true })
	};
}
/** @param {unknown} e */
export const errorHTML = (
	e
) => `<div class="container page errorpage"><h1>${t("router.loadErrorTitle", "Couldn't load live data")}</h1>
	<p class="prose">${t("router.loadErrorBody", "The Toolhub API didn't respond ($1).", esc(String((e && /** @type {{ message?: unknown }} */ (e).message) || e)))}</p>
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
	const openDisclosures =
		path === lastPath
			? new Set(
					$$(`[data-route-disclosure][open]`, viewEl)
						.map((element) => element.getAttribute("data-route-disclosure"))
						.filter(Boolean)
				)
			: new Set();
	viewEl.innerHTML = view.html;
	for (const disclosure of $$(`[data-route-disclosure]`, viewEl)) {
		if (openDisclosures.has(disclosure.getAttribute("data-route-disclosure"))) {
			/** @type {HTMLDetailsElement} */ (disclosure).open = true;
		}
	}
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
	document.dispatchEvent(new Event("toolhub:route-render-end"));
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
	await loadViewStyles(view);
	if (seq !== navSeq) return; // a newer navigation superseded this one
	commitView(viewEl, view, path);
}
