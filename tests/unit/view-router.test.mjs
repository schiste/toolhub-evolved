// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test, vi, beforeEach } from "vitest";
// The router is a pure dispatcher: every view module is mocked to a tagged spy so we can assert
// exactly which view a path selects and with which (decoded) argument, plus the sign-in gating.
// parseRoute stays real (driven by the real location); button stays real for errorHTML/loadingHTML.
import * as router from "../../public_html/views/router.js";
import * as home from "../../public_html/views/home.js";
import * as search from "../../public_html/views/search.js";
import * as tool from "../../public_html/views/tool.js";
import * as authors from "../../public_html/views/authors.js";
import * as lists from "../../public_html/views/lists.js";
import * as toolforms from "../../public_html/views/toolforms.js";
import * as staticViews from "../../public_html/views/static.js";
import * as styleguide from "../../public_html/views/styleguide.js";
import * as parity from "../../public_html/views/parity.js";
import * as session from "../../public_html/lib/core/session.js";
import * as store from "../../public_html/lib/core/store.js";
import * as account from "../../public_html/lib/organisms/account.js";
import * as quickview from "../../public_html/lib/organisms/quickview.js";

vi.mock("../../public_html/views/home.js", () => ({ viewHome: vi.fn(() => ({ tag: "home" })) }));
vi.mock("../../public_html/views/search.js", () => ({ viewSearch: vi.fn(() => ({ tag: "search" })) }));
vi.mock("../../public_html/views/tool.js", () => ({
	viewTool: vi.fn((n) => ({ tag: "tool", n })),
	viewToolHistory: vi.fn((n) => ({ tag: "toolhistory", n })),
	viewDiffStub: vi.fn((n) => ({ tag: "diff", n }))
}));
vi.mock("../../public_html/views/authors.js", () => ({ viewAuthor: vi.fn((n) => ({ tag: "author", n })) }));
vi.mock("../../public_html/views/lists.js", () => ({
	viewLists: vi.fn(() => ({ tag: "lists" })),
	viewList: vi.fn((n) => ({ tag: "list", n })),
	viewMyLists: vi.fn(() => ({ tag: "mylists" })),
	viewFavorites: vi.fn(() => ({ tag: "favorites" })),
	viewListEdit: vi.fn((n) => ({ tag: "listedit", n }))
}));
vi.mock("../../public_html/views/toolforms.js", () => ({
	viewToolForm: vi.fn((n) => ({ tag: "toolform", n })),
	viewAddTools: vi.fn(() => ({ tag: "addtools" })),
	viewAnnotationsEdit: vi.fn((n) => ({ tag: "annotations", n }))
}));
vi.mock("../../public_html/views/static.js", async (importOriginal) => {
	const actual = await importOriginal();
	return {
		...actual, // keep the real STATIC object so STATIC[slug] lookups work
		prosePage: vi.fn((title, body) => ({ tag: "prose", title, body })),
		signInPage: vi.fn((title, lead) => ({ tag: "signin", title, lead })),
		viewNotFound: vi.fn(() => ({ tag: "notfound" })),
		viewStatic: vi.fn((slug) => ({ tag: "static", slug })),
		viewApiDocs: vi.fn(() => ({ tag: "apidocs" })),
		viewContribute: vi.fn(() => ({ tag: "contribute" }))
	};
});
vi.mock("../../public_html/views/experiments.js", () => ({ viewExperiments: vi.fn(() => ({ tag: "experiments" })) }));
vi.mock("../../public_html/views/graph.js", () => ({ viewGraph: vi.fn(() => ({ tag: "graph" })) }));
vi.mock("../../public_html/views/styleguide.js", () => ({ viewStyleguide: vi.fn(() => ({ tag: "styleguide" })) }));
vi.mock("../../public_html/views/parity.js", () => ({
	viewAudit: vi.fn(() => ({ tag: "audit" })),
	viewCrawler: vi.fn(() => ({ tag: "crawler" })),
	viewMembers: vi.fn(() => ({ tag: "members" })),
	viewRecent: vi.fn(() => ({ tag: "recent" }))
}));
vi.mock("../../public_html/lib/core/session.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, signedIn: vi.fn() };
});
vi.mock("../../public_html/lib/core/store.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, isDemoListId: vi.fn() };
});
vi.mock("../../public_html/lib/organisms/account.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, closeAcctMenu: vi.fn() };
});
vi.mock("../../public_html/lib/organisms/quickview.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, closeQuickView: vi.fn() };
});

const at = (path) => {
	window.history.replaceState({}, "", path);
	return router.dispatch();
};

beforeEach(() => {
	vi.clearAllMocks();
	session.signedIn.mockReturnValue(false);
});

/* ---- dispatch: simple routes ------------------------------------------- */

test('dispatch "/" → viewHome', () => {
	const v = at("/");
	assert.equal(home.viewHome.mock.calls.length, 1);
	assert.deepEqual(v, { tag: "home" });
});

test("dispatch /user/login and /user/logout → signInPage with their copy", () => {
	at("/user/login");
	assert.deepEqual(staticViews.signInPage.mock.calls[0], [
		"Sign in",
		"Sign in to save favourites, build lists, and edit tool information."
	]);

	at("/user/logout");
	assert.deepEqual(staticViews.signInPage.mock.calls[1], [
		"Signed out",
		"You are signed out of this Toolhub prototype."
	]);
});

test("dispatch /user/<other> is not a sign-in route → viewNotFound", () => {
	// Guards the `seg[1] === "logout"` check from collapsing to `true`.
	const v = at("/user/profile");
	assert.deepEqual(v, { tag: "notfound" });
	assert.equal(staticViews.signInPage.mock.calls.length, 0);
});

test("dispatch /<other>/create is neither the tools nor lists create route → viewNotFound", () => {
	// Guards the `seg[0] === "lists"` checks (lines 108 & 115) from collapsing to `true`.
	const v = at("/widgets/create");
	assert.deepEqual(v, { tag: "notfound" });
	assert.equal(staticViews.signInPage.mock.calls.length, 0);
	assert.equal(lists.viewList.mock.calls.length, 0);
});

test("dispatch /search and /search/foo → viewSearch", () => {
	at("/search");
	at("/search/foo");
	assert.equal(search.viewSearch.mock.calls.length, 2);
});

test("dispatch /by/<name> → viewAuthor with the decoded name", () => {
	const v = at("/by/Ada%20Lovelace");
	assert.deepEqual(authors.viewAuthor.mock.calls[0], ["Ada Lovelace"]);
	assert.deepEqual(v, { tag: "author", n: "Ada Lovelace" });
});

/* ---- dispatch: tools --------------------------------------------------- */

test("dispatch /tools/create gates behind sign-in", () => {
	at("/tools/create"); // signedIn=false
	assert.deepEqual(staticViews.signInPage.mock.calls[0], [
		"Submit a tool",
		"Create a new tool record — title, description, URL and more."
	]);
	assert.equal(toolforms.viewToolForm.mock.calls.length, 0);

	session.signedIn.mockReturnValue(true);
	at("/tools/create");
	assert.deepEqual(toolforms.viewToolForm.mock.calls[0], [null]);
});

test("dispatch /tools/<name> → viewTool with decoded name", () => {
	const v = at("/tools/My%2FTool");
	assert.deepEqual(tool.viewTool.mock.calls[0], ["My/Tool"]);
	assert.deepEqual(v, { tag: "tool", n: "My/Tool" });
});

test("dispatch /tools/<name>/edit gates behind sign-in", () => {
	at("/tools/Foo/edit");
	assert.deepEqual(staticViews.signInPage.mock.calls[0], [
		"Edit tool",
		"Edit this tool's core information — title, description, URL and more. Only the owner or an administrator can change core data."
	]);

	session.signedIn.mockReturnValue(true);
	at("/tools/Foo%20Bar/edit");
	assert.deepEqual(toolforms.viewToolForm.mock.calls[0], ["Foo Bar"]);
});

test("dispatch /tools/<name>/edit-annotations gates behind sign-in", () => {
	at("/tools/Foo/edit-annotations");
	assert.deepEqual(staticViews.signInPage.mock.calls[0], [
		"Edit annotations",
		"Add or refine community annotations for this tool — audiences, tasks and more."
	]);

	session.signedIn.mockReturnValue(true);
	at("/tools/Bar%20Baz/edit-annotations");
	assert.deepEqual(toolforms.viewAnnotationsEdit.mock.calls[0], ["Bar Baz"]);
});

test("dispatch /tools/<name>/history → history, with a revision id → diff stub", () => {
	at("/tools/Foo/history");
	assert.deepEqual(tool.viewToolHistory.mock.calls[0], ["Foo"]);
	assert.equal(tool.viewDiffStub.mock.calls.length, 0);

	at("/tools/Foo/history/42");
	assert.deepEqual(tool.viewDiffStub.mock.calls[0], ["Foo"]);
});

/* ---- dispatch: lists --------------------------------------------------- */

test("dispatch /lists/create gates behind sign-in", () => {
	at("/lists/create");
	assert.deepEqual(staticViews.signInPage.mock.calls[0], [
		"Create a list",
		"Create a new list to group and share useful tools."
	]);

	session.signedIn.mockReturnValue(true);
	at("/lists/create");
	assert.deepEqual(lists.viewListEdit.mock.calls[0], [null]);
});

test("dispatch /lists/<id> → viewList with decoded id", () => {
	const v = at("/lists/abc%20123");
	assert.deepEqual(lists.viewList.mock.calls[0], ["abc 123"]);
	assert.deepEqual(v, { tag: "list", n: "abc 123" });
});

test("dispatch /lists/<id>/edit: signed-out → sign-in fallback", () => {
	at("/lists/abc/edit");
	assert.deepEqual(staticViews.signInPage.mock.calls[0], [
		"Edit list",
		"Edit this list's title, description and tools."
	]);
	assert.equal(lists.viewListEdit.mock.calls.length, 0);
});

test("dispatch /lists/<id>/edit: signed-in demo list → editable; non-demo → sign-in", () => {
	session.signedIn.mockReturnValue(true);

	store.isDemoListId.mockReturnValue(true);
	at("/lists/demo%201/edit");
	assert.deepEqual(store.isDemoListId.mock.calls[0], ["demo%201"]); // raw segment, not decoded
	assert.deepEqual(lists.viewListEdit.mock.calls[0], ["demo 1"]); // decoded for the editor
	assert.equal(staticViews.signInPage.mock.calls.length, 0);

	vi.clearAllMocks();
	session.signedIn.mockReturnValue(true);
	store.isDemoListId.mockReturnValue(false);
	at("/lists/real/edit");
	assert.deepEqual(staticViews.signInPage.mock.calls[0], [
		"Edit list",
		"Edit this list's title, description and tools."
	]);
	assert.equal(lists.viewListEdit.mock.calls.length, 0);
});

test("dispatch /lists/<id>/history → prosePage with the live-site note", () => {
	const v = at("/lists/abc/history");
	assert.deepEqual(staticViews.prosePage.mock.calls[0], [
		"List history",
		'<p>Revision history for this list is available on the <a href="https://toolhub.wikimedia.org/" target="_blank" rel="noopener nofollow">live site</a>.</p>'
	]);
	assert.deepEqual(v, { tag: "prose", title: "List history", body: staticViews.prosePage.mock.calls[0][1] });
});

/* ---- dispatch: ROUTES table ------------------------------------------- */

test("dispatch routes the ungated ROUTES entries to their views", async () => {
	assert.deepEqual(at("/lists"), { tag: "lists" });
	assert.deepEqual(at("/published-lists"), { tag: "lists" });
	// graph / experiments / styleguide are lazy-loaded (dynamic import), so dispatch
	// returns a Promise<View> for them — render() awaits it the same way.
	assert.deepEqual(await at("/graph"), { tag: "graph" });
	assert.deepEqual(at("/recent"), { tag: "recent" });
	assert.deepEqual(at("/members"), { tag: "members" });
	assert.deepEqual(at("/crawler-history"), { tag: "crawler" });
	assert.deepEqual(at("/audit-logs"), { tag: "audit" });
	assert.deepEqual(at("/api-docs"), { tag: "apidocs" });
	assert.deepEqual(at("/contribute"), { tag: "contribute" });
	assert.deepEqual(await at("/experiments"), { tag: "experiments" });
	assert.deepEqual(await at("/styleguide"), { tag: "styleguide" });
	assert.equal(lists.viewLists.mock.calls.length, 2); // lists + published-lists
});

test("dispatch ROUTES sign-in stubs use their exact copy", () => {
	at("/developer-settings");
	assert.deepEqual(staticViews.signInPage.mock.calls[0], [
		"Developer settings",
		"Manage your API tokens and registered OAuth applications."
	]);

	at("/login");
	assert.deepEqual(staticViews.signInPage.mock.calls[1], [
		"Sign in",
		"Sign in to save favourites, build lists, and edit tool information."
	]);
});

test("dispatch gated ROUTES entries: signed-out → sign-in copy", () => {
	at("/my-lists");
	assert.deepEqual(staticViews.signInPage.mock.calls[0], ["Your lists", "See and manage the lists you've created."]);
	assert.equal(lists.viewMyLists.mock.calls.length, 0);

	vi.clearAllMocks();
	session.signedIn.mockReturnValue(false);
	at("/favorites");
	assert.deepEqual(staticViews.signInPage.mock.calls[0], ["Favorites", "Your saved tools, all in one place."]);

	vi.clearAllMocks();
	session.signedIn.mockReturnValue(false);
	at("/add-or-remove-tools");
	assert.deepEqual(staticViews.signInPage.mock.calls[0], [
		"Add or remove tools",
		"Register a toolinfo.json URL to be crawled, or create a tool record directly."
	]);
});

test("dispatch gated ROUTES entries: signed-in → their real views", () => {
	session.signedIn.mockReturnValue(true);
	assert.deepEqual(at("/my-lists"), { tag: "mylists" });
	assert.deepEqual(at("/favorites"), { tag: "favorites" });
	assert.deepEqual(at("/add-or-remove-tools"), { tag: "addtools" });
	assert.equal(staticViews.signInPage.mock.calls.length, 0);
});

/* ---- dispatch: STATIC + fallback -------------------------------------- */

test("dispatch a STATIC slug → viewStatic; an unknown slug → viewNotFound", () => {
	const v = at("/about");
	assert.deepEqual(staticViews.viewStatic.mock.calls[0], ["about"]);
	assert.deepEqual(v, { tag: "static", slug: "about" });

	const nf = at("/this-route-does-not-exist");
	assert.deepEqual(nf, { tag: "notfound" });
	assert.equal(staticViews.viewNotFound.mock.calls.length, 1);
});

/* ---- requireSignIn / setSignInFallback -------------------------------- */

test("requireSignIn runs the view when signed in, else the fallback with title/lead", () => {
	const viewFn = vi.fn(() => ({ tag: "ok" }));

	session.signedIn.mockReturnValue(true);
	assert.deepEqual(router.requireSignIn(viewFn, "T", "L"), { tag: "ok" });
	assert.equal(viewFn.mock.calls.length, 1);
	assert.equal(staticViews.signInPage.mock.calls.length, 0);

	session.signedIn.mockReturnValue(false);
	const out = router.requireSignIn(viewFn, "T", "L");
	assert.equal(viewFn.mock.calls.length, 1); // not called again
	assert.deepEqual(staticViews.signInPage.mock.calls[0], ["T", "L"]);
	assert.deepEqual(out, { tag: "signin", title: "T", lead: "L" });
});

test("setSignInFallback swaps the gate's fallback function", () => {
	const custom = vi.fn(() => ({ tag: "custom" }));
	router.setSignInFallback(custom);
	session.signedIn.mockReturnValue(false);
	try {
		const out = router.requireSignIn(vi.fn(), "X", "Y");
		assert.deepEqual(custom.mock.calls[0], ["X", "Y"]);
		assert.deepEqual(out, { tag: "custom" });
		assert.equal(staticViews.signInPage.mock.calls.length, 0);
	} finally {
		// Restore the production fallback so later tests still gate via signInPage.
		router.setSignInFallback(staticViews.signInPage);
	}
});

/* ---- setActiveNav / navHrefMatches ------------------------------------ */

function buildNav() {
	document.body.innerHTML = `
		<nav id="nav-links">
			<a href="/">Home</a>
			<a href="/search">Search</a>
			<a href="/lists">Lists</a>
			<a href="/graph">Graph</a>
			<a href="/about" aria-current="page">About</a>
		</nav>
		<nav id="nav-mobile"><a href="/search">SearchM</a></nav>`;
}
const activeHrefs = (navSel) =>
	[...document.querySelectorAll(`${navSel} a`)]
		.filter((a) => a.classList.contains("is-active"))
		.map((a) => a.getAttribute("href"));

test("setActiveNav marks the section link active by prefix and exact match", () => {
	buildNav();
	window.history.replaceState({}, "", "/search/wikidata");
	router.setActiveNav();
	assert.deepEqual(activeHrefs("#nav-links"), ["/search"]); // prefix match /search/
	assert.equal(document.querySelector('#nav-links a[href="/search"]').getAttribute("aria-current"), "page");
	// The mobile nav is processed too (covers the "#nav-mobile" selector).
	assert.deepEqual(activeHrefs("#nav-mobile"), ["/search"]);
	// A previously aria-current link that no longer matches is cleared.
	assert.equal(document.querySelector('#nav-links a[href="/about"]').hasAttribute("aria-current"), false);

	// Exact "/search" matches via the first operand (kills `pathHash === "/search"`).
	window.history.replaceState({}, "", "/search");
	router.setActiveNav();
	assert.deepEqual(activeHrefs("#nav-links"), ["/search"]);

	window.history.replaceState({}, "", "/lists");
	router.setActiveNav();
	assert.deepEqual(activeHrefs("#nav-links"), ["/lists"]);

	// Prefix "/lists/…" needs the dedicated `/lists` branch + startsWith (kills 147).
	window.history.replaceState({}, "", "/lists/wikidata");
	router.setActiveNav();
	assert.deepEqual(activeHrefs("#nav-links"), ["/lists"]);

	window.history.replaceState({}, "", "/graph/x");
	router.setActiveNav();
	assert.deepEqual(activeHrefs("#nav-links"), ["/graph"]);

	// Exact "/graph" matches via the first operand (kills `pathHash === "/graph"`).
	window.history.replaceState({}, "", "/graph");
	router.setActiveNav();
	assert.deepEqual(activeHrefs("#nav-links"), ["/graph"]);

	window.history.replaceState({}, "", "/about");
	router.setActiveNav();
	assert.deepEqual(activeHrefs("#nav-links"), ["/about"]); // else-branch exact match
});

test("setActiveNav does not match a look-alike prefix and only marks the first match", () => {
	buildNav();
	window.history.replaceState({}, "", "/searchx");
	router.setActiveNav();
	assert.deepEqual(activeHrefs("#nav-links"), []); // "/searchx" is not "/search" nor "/search/…"

	// Two identical matching links: only the first becomes active (currentSet guard).
	document.body.innerHTML = `<nav id="nav-links"><a href="/lists">A</a><a href="/lists">B</a></nav>`;
	window.history.replaceState({}, "", "/lists");
	router.setActiveNav();
	const links = [...document.querySelectorAll("#nav-links a")];
	assert.equal(links[0].classList.contains("is-active"), true);
	assert.equal(links[1].classList.contains("is-active"), false);
});

/* ---- render / commitView / errorHTML / loadingHTML -------------------- */

test("loadingHTML and errorHTML render the exact fixed markup", () => {
	assert.equal(
		router.loadingHTML(),
		'<div class="container page loading" role="status" aria-live="polite"><span class="spinner" aria-hidden="true"></span><span class="skip-label">Loading</span></div>'
	);
	assert.equal(
		router.errorHTML(new Error("oops")),
		'<div class="container page errorpage"><h1>Couldn\'t load live data</h1>\n\t<p class="prose">The Toolhub API didn\'t respond (oops).</p>\n\t<a class="btn btn--primary btn--md" href="/">Back to home</a></div>'
	);
	// `(e && e.message) || e`: an object without message falls back to e; a nullish e → String(e).
	assert.match(router.errorHTML({ message: "hi" }), /respond \(hi\)/);
	assert.match(router.errorHTML(null), /respond \(null\)/);
});

const deferred = () => {
	let resolve;
	const promise = new Promise((r) => (resolve = r));
	return { promise, resolve };
};

test("render: first load shows the spinner, then commits, sets on-home and focuses the h1", async () => {
	// This is the first render() in the file, so lastPath is still null.
	assert.equal(router.lastPath, null);
	document.body.innerHTML = '<main id="view" aria-busy="false"></main>';
	window.history.replaceState({}, "", "/");
	const d = deferred();
	const mount = vi.fn();
	home.viewHome.mockReturnValue(d.promise);
	const scrollSpy = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
	const focusSpy = vi.spyOn(HTMLElement.prototype, "focus"); // calls through, records args
	const navBefore = router.navSeq;

	try {
		const p = router.render();
		const viewEl = document.querySelector("#view");
		// lastPath === null → loadingHTML swapped in immediately.
		assert.equal(viewEl.innerHTML, router.loadingHTML());
		assert.equal(viewEl.getAttribute("aria-busy"), "true");

		d.resolve({ title: "Home — Toolhub", html: '<div><h1 id="hh">Home</h1></div>', mount });
		await p;

		// commitView set the html, then focus added tabindex="-1" to the <h1>.
		assert.equal(viewEl.innerHTML, '<div><h1 id="hh" tabindex="-1">Home</h1></div>');
		assert.equal(viewEl.getAttribute("aria-busy"), "false");
		assert.equal(document.body.classList.contains("on-home"), true);
		assert.equal(document.title, "Home — Toolhub");
		assert.equal(mount.mock.calls.length, 1);
		assert.equal(router.lastPath, "/");
		assert.equal(router.navSeq, navBefore + 1); // ++navSeq (kills the -- mutant)
		// Focus moved to the view's <h1>, and the page scrolled to the top.
		const h1 = document.querySelector("#hh");
		assert.equal(h1.getAttribute("tabindex"), "-1");
		assert.equal(document.activeElement, h1);
		assert.deepEqual(scrollSpy.mock.calls.at(-1), [{ top: 0, behavior: "auto" }]);
		assert.deepEqual(focusSpy.mock.calls.at(-1), [{ preventScroll: true }]);
		// Navigation dismissed the quick-view and account menu.
		assert.equal(quickview.closeQuickView.mock.calls.length, 1);
		assert.equal(account.closeAcctMenu.mock.calls.length, 1);
	} finally {
		scrollSpy.mockRestore();
		focusSpy.mockRestore();
	}
});

test("render: re-rendering the same path keeps the current page (no spinner) and a missing title/mount/h1 are tolerated", async () => {
	document.body.innerHTML = '<main id="view" aria-busy="false">PREV</main>';
	window.history.replaceState({}, "", "/"); // same as lastPath "/"
	const d = deferred();
	home.viewHome.mockReturnValue(d.promise);
	const viewEl = document.querySelector("#view");

	const p = router.render();
	// path === lastPath → the busy/loading block is skipped entirely: the old content stays
	// and aria-busy is never flipped to "true" (kills `if (path !== lastPath)` → `if (true)`).
	assert.equal(viewEl.innerHTML, "PREV");
	assert.equal(viewEl.getAttribute("aria-busy"), "false");

	// title "" → falls back to "Toolhub"; no mount; no <h1> → focus falls back to the view element.
	d.resolve({ title: "", html: "<p>no heading</p>" });
	await p;
	assert.equal(viewEl.innerHTML, "<p>no heading</p>");
	assert.equal(document.title, "Toolhub");
	assert.equal(viewEl.getAttribute("tabindex"), null); // path === lastPath → no re-focus
});

test("render: a slow navigation to a new path swaps in the spinner after the delay", async () => {
	vi.useFakeTimers();
	try {
		document.body.innerHTML = '<main id="view" aria-busy="false">KEEP</main>';
		window.history.replaceState({}, "", "/search");
		const d = deferred();
		search.viewSearch.mockReturnValue(d.promise);
		const viewEl = document.querySelector("#view");

		const p = router.render();
		// lastPath !== null and slow → the current page is kept until the delay elapses.
		assert.equal(viewEl.innerHTML, "KEEP");
		assert.equal(viewEl.getAttribute("aria-busy"), "true");

		vi.advanceTimersByTime(250);
		assert.equal(viewEl.innerHTML, router.loadingHTML());

		d.resolve({ title: "Search — Toolhub", html: "<div><h1>S</h1></div>" });
		await p;
		assert.equal(viewEl.innerHTML, '<div><h1 tabindex="-1">S</h1></div>');
		assert.equal(router.lastPath, "/search");
		assert.equal(document.body.classList.contains("on-home"), false); // not "/"
	} finally {
		vi.useRealTimers();
	}
});

test("render: a superseded navigation neither flashes its spinner nor commits", async () => {
	vi.useFakeTimers();
	try {
		document.body.innerHTML = '<main id="view" aria-busy="false">START</main>';
		const viewEl = document.querySelector("#view");

		// Navigation A (slow) to /members.
		window.history.replaceState({}, "", "/members");
		const dA = deferred();
		parity.viewMembers.mockReturnValue(dA.promise);
		const pA = router.render();

		// Navigation B (also slow) to /recent supersedes A before A resolves.
		window.history.replaceState({}, "", "/recent");
		const dB = deferred();
		parity.viewRecent.mockReturnValue(dB.promise);
		const pB = router.render();

		// B resolves first and commits.
		dB.resolve({ title: "Recent — Toolhub", html: "<div>RECENT</div>" });
		await pB;
		assert.equal(viewEl.innerHTML, "<div>RECENT</div>");

		// A's spinner timer fires now, but seq !== navSeq → it must NOT replace the page.
		vi.advanceTimersByTime(250);
		assert.equal(viewEl.innerHTML, "<div>RECENT</div>");

		// A finally resolves, but being superseded it returns without committing.
		dA.resolve({ title: "Members — Toolhub", html: "<div>MEMBERS</div>" });
		await pA;
		assert.equal(viewEl.innerHTML, "<div>RECENT</div>");
	} finally {
		vi.useRealTimers();
	}
});

test("render: a dispatch failure commits the error page", async () => {
	document.body.innerHTML = '<main id="view" aria-busy="false"></main>';
	window.history.replaceState({}, "", "/styleguide");
	styleguide.viewStyleguide.mockImplementation(() => {
		throw new Error("boom");
	});
	const viewEl = document.querySelector("#view");

	await router.render();
	assert.equal(document.title, "Error — Toolhub");
	assert.match(viewEl.innerHTML, /Couldn't load live data/);
	assert.match(viewEl.innerHTML, /respond \(boom\)/);
	assert.match(viewEl.innerHTML, /Back to home/);
});
