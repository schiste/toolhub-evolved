// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, esc } from "../lib/core/dom.js";
import { parseHash } from "../lib/core/routing.js";
import { signedIn } from "../lib/core/session.js";
import { isDemoListId } from "../lib/core/store.js";
import { button } from "../lib/atoms/button.js";
import { closeAcctMenu } from "../lib/organisms/account.js";
import { closeQuickView } from "../lib/organisms/quickview.js";
import { viewHome } from "./home.js";
import { viewSearch } from "./search.js";
import { viewTool, viewToolHistory, viewDiffStub } from "./tool.js";
import { viewAuthor } from "./authors.js";
import { viewLists, viewList, viewMyLists, viewFavorites, viewListEdit } from "./lists.js";
import { viewToolForm, viewAddTools, viewAnnotationsEdit } from "./toolforms.js";
import { STATIC, prosePage, signInPage, viewApiDocs, viewContribute, viewNotFound, viewStatic } from "./static.js";
import { viewExperiments } from "./experiments.js";
import { viewGraph } from "./graph.js";
import { viewStyleguide } from "./styleguide.js";
import { viewAudit, viewCrawler, viewMembers, viewRecent } from "./parity.js";

let signInFallback = null;
export function setSignInFallback(fn) { signInFallback = fn; }
export function requireSignIn(viewFn, title, lead) { return signedIn() ? viewFn() : signInFallback(title, lead); }
setSignInFallback(signInPage);

export const ROUTES = {
	lists: viewLists,
	graph: viewGraph,
	"published-lists": viewLists,
	"my-lists": () => requireSignIn(viewMyLists, "Your lists", "See and manage the lists you've created."),
	favorites: () => requireSignIn(viewFavorites, "Favorites", "Your saved tools, all in one place."),
	"add-or-remove-tools": () => requireSignIn(viewAddTools, "Add or remove tools", "Register a toolinfo.json URL to be crawled, or create a tool record directly."),
	"developer-settings": () => signInPage("Developer settings", "Manage your API tokens and registered OAuth applications."),
	login: () => signInPage("Sign in", "Sign in to save favourites, build lists, and edit tool information."),
	recent: viewRecent,
	members: viewMembers,
	"crawler-history": viewCrawler,
	"audit-logs": viewAudit,
	"api-docs": viewApiDocs,
	contribute: viewContribute,
	experiments: viewExperiments,
	styleguide: viewStyleguide,
};
export function dispatch() {
	const { path } = parseHash();
	const seg = path.split("/").filter(Boolean); // e.g. ["tools","foo"]
	if (path === "/") return viewHome();
	if (seg[0] === "search") return viewSearch();
	if (seg[0] === "by" && seg[1]) return viewAuthor(decodeURIComponent(seg[1]));
	// Tool + its sub-routes
	if (seg[0] === "tools" && seg[1] === "create") return requireSignIn(() => viewToolForm(null), "Submit a tool", "Create a new tool record — title, description, URL and more.");
	if (seg[0] === "tools" && seg[1]) {
		const nm = decodeURIComponent(seg[1]);
		if (seg[2] === "edit") return requireSignIn(() => viewToolForm(nm), "Edit tool", "Edit this tool's core information — title, description, URL and more. Only the owner or an administrator can change core data.");
		if (seg[2] === "edit-annotations") return requireSignIn(() => viewAnnotationsEdit(nm), "Edit annotations", "Add or refine community annotations for this tool — audiences, tasks and more.");
		if (seg[2] === "history") return seg[3] ? viewDiffStub(nm) : viewToolHistory(nm);
		return viewTool(nm);
	}
	// Lists + sub-routes
	if (seg[0] === "lists" && seg[1] === "create") return requireSignIn(() => viewListEdit(null), "Create a list", "Create a new list to group and share useful tools.");
	if (seg[0] === "lists" && seg[1]) {
		if (seg[2] === "edit") return requireSignIn(() => isDemoListId(seg[1]) ? viewListEdit(decodeURIComponent(seg[1])) : signInPage("Edit list", "Edit this list's title, description and tools."), "Edit list", "Edit this list's title, description and tools.");
		if (seg[2] === "history") return prosePage("List history", "<p>Revision history for this list is available on the <a href=\"https://toolhub.wikimedia.org/\" target=\"_blank\" rel=\"noopener nofollow\">live site</a>.</p>");
		return viewList(decodeURIComponent(seg[1]));
	}
	if (ROUTES[seg[0]]) return ROUTES[seg[0]]();
	if (STATIC[seg[0]]) return viewStatic(seg[0]);
	return viewNotFound();
}
function navHrefMatches(pathHash, href) {
	if (href === "#/search") return pathHash === "#/search" || pathHash.startsWith("#/search/");
	if (href === "#/lists") return pathHash === "#/lists" || pathHash.startsWith("#/lists/");
	if (href === "#/graph") return pathHash === "#/graph" || pathHash.startsWith("#/graph/");
	return href === pathHash;
}
export function setActiveNav() {
	const h = "#" + (parseHash().path);
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
export let lastPath = null;
export let navSeq = 0;
export const loadingHTML = () => '<div class="container page loading" role="status" aria-live="polite"><span class="spinner" aria-hidden="true"></span><span class="skip-label">Loading</span></div>';
export const errorHTML = (e) => `<div class="container page errorpage"><h1>Couldn't load live data</h1>
	<p class="prose">The Toolhub API didn't respond (${esc(String((e && e.message) || e))}).</p>
	${button("Back to home", { variant: "primary", href: "#/" })}</div>`;
// How long a view may load before we replace the page with a spinner. Below this,
// the current page stays on screen — fast/cached loads never flash a spinner.
const SPINNER_DELAY = 250;
export async function render() {
	closeQuickView(); // any navigation dismisses the peek modal
	closeAcctMenu();  // …and the account dropdown
	const seq = ++navSeq;
	const { path } = parseHash();
	const viewEl = $("#view");
	let spinnerTimer = null;
	if (path !== lastPath) {
		viewEl.setAttribute("aria-busy", "true"); // announce busy immediately (a11y)
		if (lastPath === null) {
			viewEl.innerHTML = loadingHTML(); // first load: nothing to keep on screen
		} else {
			// Keep the current page visible; only swap in the spinner if the next
			// view is genuinely slow. Cached navigations resolve first and skip it.
			spinnerTimer = setTimeout(() => { if (seq === navSeq) viewEl.innerHTML = loadingHTML(); }, SPINNER_DELAY);
		}
	}
	let view;
	try { view = await dispatch(); }
	catch (e) { view = { title: "Error — Toolhub", html: errorHTML(e) }; }
	if (spinnerTimer) clearTimeout(spinnerTimer); // resolved (or superseded) before the delay
	if (seq !== navSeq) return; // a newer navigation superseded this one
	viewEl.innerHTML = view.html;
	viewEl.setAttribute("aria-busy", "false");
	document.body.classList.toggle("on-home", path === "/"); // expbar blends with the hero on home
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
