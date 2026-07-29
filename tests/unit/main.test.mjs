// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test, vi, beforeAll } from "vitest";
// main.js is the app entry: importing it wires global + element listeners as a side effect.
// Every heavy dependency is mocked to a spy; the DOM shell is built BEFORE importing so the
// listeners attach. Most tests share a single import (so document/window listeners are not
// duplicated); the guard tests re-import with a missing element via a `?v=` query suffix
// (a fresh module instance that still shares the singleton mocks) and assert it never throws.
import * as session from "../../public_html/lib/core/session.js";
import { FRONTEND_TIMINGS } from "../../public_html/lib/core/diagnostics.js";
import * as i18n from "../../public_html/lib/core/i18n.js";
import * as api from "../../public_html/lib/core/api.js";
import * as theme from "../../public_html/lib/core/theme.js";
import * as store from "../../public_html/lib/core/store.js";
import * as serversync from "../../public_html/lib/core/serversync.js";
import * as routing from "../../public_html/lib/core/routing.js";
import * as favbtn from "../../public_html/lib/molecules/favbtn.js";
import * as account from "../../public_html/lib/organisms/account.js";
import * as langpicker from "../../public_html/lib/organisms/langpicker.js";
import * as quickview from "../../public_html/lib/organisms/quickview.js";
import * as router from "../../public_html/views/router.js";

vi.mock("../../public_html/lib/core/session.js", async (o) => ({
	...(await o()),
	setAuthRender: vi.fn()
}));
vi.mock("../../public_html/lib/core/api.js", async (o) => ({
	...(await o()),
	backendGetJson: vi.fn(() => Promise.resolve(null))
}));
vi.mock("../../public_html/lib/core/i18n.js", async (o) => ({
	...(await o()),
	applyLocaleAttrs: vi.fn(),
	setLocale: vi.fn(),
	setMessages: vi.fn()
}));
vi.mock("../../public_html/lib/core/theme.js", async (o) => ({
	...(await o()),
	initTheme: vi.fn(),
	setThemeChoice: vi.fn()
}));
vi.mock("../../public_html/lib/core/store.js", async (o) => ({
	...(await o()),
	demoStore: { clearAll: vi.fn() },
	listToolToggle: vi.fn(() => true),
	toggleFav: vi.fn(() => true)
}));
vi.mock("../../public_html/lib/core/serversync.js", async (o) => ({
	...(await o()),
	initServerSync: vi.fn(() => Promise.resolve(false)),
	officialWrite: vi.fn(() => Promise.resolve({ ok: true })),
	officialWriteAvailable: vi.fn(() => false)
}));
vi.mock("../../public_html/lib/core/routing.js", async (o) => ({
	...(await o()),
	navigateTo: vi.fn(),
	normalizeLegacyHashRoute: vi.fn()
}));
vi.mock("../../public_html/lib/molecules/favbtn.js", async (o) => ({ ...(await o()), syncFavButtons: vi.fn() }));
vi.mock("../../public_html/lib/organisms/account.js", async (o) => ({
	...(await o()),
	closeAcctMenu: vi.fn(),
	renderAccount: vi.fn(),
	syncSubmitButton: vi.fn(),
	toggleAcctMenu: vi.fn()
}));
vi.mock("../../public_html/lib/organisms/langpicker.js", async (o) => ({
	...(await o()),
	closeLangMenu: vi.fn(),
	renderLangPicker: vi.fn(),
	showLangNote: vi.fn(),
	toggleLangMenu: vi.fn()
}));
vi.mock("../../public_html/lib/organisms/quickview.js", async (o) => ({
	...(await o()),
	closeQuickView: vi.fn(),
	openQuickView: vi.fn(),
	qvTrap: vi.fn()
}));
vi.mock("../../public_html/views/router.js", async (o) => ({ ...(await o()), render: vi.fn() }));

const SHELL = `
	<a class="skip" href="#view">Skip to content</a>
	<div class="mockup-banner" data-sitenotice>
		<span class="mockup-banner__txt" data-i18n="shell.previewBanner">Evolved preview: live Toolhub data with Evolved additions.</span>
		<a class="mockup-banner__link" href="/experiments">status</a>
		<a class="mockup-banner__link" href="/rules-of-engagement">rules</a>
		<button type="button" data-dismiss-sitenotice>close</button>
	</div>
	<div id="theme-toggle"></div>
	<nav id="nav-links"><a href="/search">S</a><a href="/lists">L</a><a href="/graph">M</a><a href="/recent">R</a></nav>
		<nav id="nav-mobile"><a href="/search">S</a><a href="/lists">L</a><a href="/graph">M</a><a href="/recent">R</a></nav>
		<a id="submit-tool" href="/my-tools"><span class="submit-tool__label"></span></a>
	<button id="command-palette-trigger" type="button" aria-controls="command-palette" aria-expanded="false">
		<span class="command-trigger__label"></span><kbd data-command-shortcut></kbd>
	</button>
	<div class="command-palette hidden" id="command-palette" aria-hidden="true">
		<button type="button" data-command-close>close</button>
		<h2 id="command-title" data-i18n="commandPalette.title">Search Toolhub</h2>
		<p id="command-help">help</p>
		<label for="command-input">field</label>
		<input id="command-input" aria-controls="command-list" aria-activedescendant="" placeholder="Search tools or actions..." data-i18n-placeholder="commandPalette.inputPlaceholder" />
		<div id="command-status" aria-live="polite"></div>
		<ul id="command-list" role="listbox"></ul>
	</div>
	<header id="account">
		<button id="acct-btn">Account</button>
		<div id="acct-menu">
			<a href="/help">Help</a>
		</div>
	</header>
	<nav id="langpicker">
		<button id="lang-btn">Language</button>
		<button data-lang data-lang-name="Français">FR</button>
	</nav>
	<main id="view">
		<button data-fav="tool-a">fav</button>
		<button data-listadd="list-1" data-tn="tool-a"><span class="savemenu__mark"></span></button>
		<button data-listadd="list-2" data-tn="tool-c">no mark</button>
		<button data-q="wiki edits">q</button>
		<a href="/about" data-q="ignored">qlink</a>
		<article data-tool="tool-x" tabindex="0"><span class="tcard__inner">x</span><a href="/incard">deep link</a></article>
		<a href="/internal?x=1">internal</a>
		<a href="/features">feature try</a>
		<a href="/api/tools/">api</a>
		<a href="https://ext.example/">ext</a>
		<a href="#frag">frag</a>
		<a href="/dl" download>dl</a>
		<a href="/tab" target="_blank">tab</a>
		<span class="bare">no link</span>
		<div class="route-loading__label">loading</div>
	</main>
	<aside id="qv">
		<button data-fav="tool-b">qvfav</button>
		<button data-qv-close>close</button>
		<div class="qv-body">body</div>
	</aside>
	<footer>
		<nav data-footer-section="discover"><h2></h2><a href="/search"></a><a href="/lists"></a><a href="/graph"></a><a href="/members"></a><a href="/recent"></a></nav>
			<nav data-footer-section="maintain"><h2></h2><a href="/my-lists"></a><a href="/my-tools"></a><a href="/favorites"></a><a href="/developer-settings"></a><a href="/contribute"></a></nav>
		<nav data-footer-section="project"><h2></h2><a href="/api-docs" data-i18n="shell.footer.apiExplorer">API explorer</a><a href="/styleguide"></a><a href="/crawler-history"></a><a href="/audit-logs"></a><a href="https://meta.wikimedia.org/wiki/Toolhub"></a><a href="https://gerrit.wikimedia.org/r/plugins/gitiles/wikimedia/toolhub/+/refs/heads/main"></a><a href="https://phabricator.wikimedia.org/tag/toolhub/"></a></nav>
		<nav data-footer-section="about"><h2></h2><a href="/about"></a><a href="/help"></a><a href="/community"></a><a href="/privacy"></a><a href="/terms"></a><a href="/code-of-conduct"></a><a href="/rss"></a><a href="/rules-of-engagement"></a></nav>
		<a class="footer__maintain"><svg></svg><span class="footer__maintain-label"></span></a>
		<span class="footer__legal"></span>
		<span class="footer__note"></span>
	</footer>`;

let mqlChange = null; // captured matchMedia "change" listener
let authRenderCb = null; // captured setAuthRender callback
let importError = null; // any error thrown while importing main.js (a selector mutated to "" throws)

const click = (el, opts = {}) =>
	el.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true, button: 0, ...opts }));
const keydown = (el, key) =>
	el.dispatchEvent(new window.KeyboardEvent("keydown", { bubbles: true, cancelable: true, key }));
const $ = (s) => document.querySelector(s);
const settleDynamicImports = async () => {
	if (typeof vi.dynamicImportSettled === "function") await vi.dynamicImportSettled();
	await Promise.resolve();
};
const settleBootTasks = async () => {
	await new Promise((resolve) => {
		setTimeout(resolve, 0);
	});
	await new Promise((resolve) => {
		setTimeout(resolve, 0);
	});
	await Promise.resolve();
};
const loadQuickViewForTest = async () => {
	click($("#view .tcard__inner"));
	await settleDynamicImports();
	vi.clearAllMocks();
};

beforeAll(async () => {
	document.documentElement.setAttribute("data-theme", "dark");
	window.matchMedia = vi.fn((q) => ({
		matches: false,
		media: q,
		addEventListener: vi.fn((evt, cb) => {
			if (evt === "change") mqlChange = cb;
		}),
		removeEventListener: vi.fn()
	}));
	window.requestAnimationFrame = vi.fn((cb) => {
		setTimeout(() => cb(0), 0);
		return 1;
	});
	document.body.innerHTML = SHELL;
	localStorage.clear();
	// Direct (unsuffixed) import so Stryker's vitest runner associates this test file with main.js.
	// Wrapped so an import-time throw (e.g. a selector literal mutated to "") becomes an asserted
	// test failure rather than a skipped suite (which Stryker would treat as survived).
	try {
		await import("../../public_html/main.js");
	} catch (e) {
		importError = e;
	}
	authRenderCb = session.setAuthRender.mock.calls[0]?.[0];
	// Registered AFTER main's handlers: main's SPA logic runs first (so navigateTo assertions
	// hold), then this suppresses happy-dom's real anchor navigation (avoids network fetches).
	document.addEventListener("click", (e) => e.preventDefault());
});

/* ---- import-time wiring ----------------------------------------------- */

test("importing main with a complete shell raises no error (every selector literal is valid)", () => {
	assert.equal(importError, null);
});

test("importing main wires locale, theme, account, langpicker and the initial render", () => {
	assert.equal(i18n.applyLocaleAttrs.mock.calls.length, 1);
	assert.equal(theme.initTheme.mock.calls.length, 1);
	assert.equal(document.documentElement.classList.contains("sitenotice-dismissed"), false);
	assert.equal($(".mockup-banner__txt").textContent, "Evolved preview: live Toolhub data with Evolved additions.");
	assert.equal($('[data-footer-section="project"] a[href="/api-docs"]').textContent, "API explorer");
	assert.equal($("#command-title").textContent, "Search Toolhub");
	assert.equal($("#command-input").getAttribute("placeholder"), "Search tools or actions...");
	assert.equal($(".footer__legal").textContent, "Catalog content under CC0 · Toolhub Evolved v0.2.0");
	assert.equal(account.renderAccount.mock.calls.length > 0, true);
	assert.equal(account.syncSubmitButton.mock.calls.length > 0, true);
	assert.equal(langpicker.renderLangPicker.mock.calls.length, 1);
	assert.equal(routing.normalizeLegacyHashRoute.mock.calls.length, 1);
	assert.equal(router.render.mock.calls.length > 0, true);
	// The OS-preference media query is observed.
	assert.deepEqual(window.matchMedia.mock.calls.at(-1), ["(prefers-color-scheme: dark)"]);
});

test("importing main records frontend boot diagnostics", async () => {
	await Promise.resolve();
	const names = new Set(FRONTEND_TIMINGS.map((entry) => entry.name));
	assert.ok(names.has("app-boot-start"));
	assert.ok(names.has("labels-loaded"));
	assert.ok(names.has("app-boot"));
	assert.ok(
		names.has("first-content-paint") || typeof globalThis.PerformanceObserver === "function",
		"FCP is either recorded by fallback or delegated to PerformanceObserver"
	);
});

test("API cache refresh events show a toast and repaint once fresh data arrives", () => {
	vi.useFakeTimers();
	try {
		vi.clearAllMocks();
		document.dispatchEvent(
			new CustomEvent("toolhub:api-cache-refresh", { detail: { url: "/api/ui/home/", state: "start" } })
		);
		assert.equal($("#toast-region").textContent, "Refreshing live Toolhub data…");

		document.dispatchEvent(
			new CustomEvent("toolhub:api-cache-refresh", { detail: { url: "/api/ui/home/", state: "success" } })
		);
		assert.equal($("#toast-region").textContent, "Live Toolhub data updated.");
		vi.advanceTimersByTime(150);
		assert.equal(router.render.mock.calls.length, 1);
		vi.advanceTimersByTime(2400);
		assert.equal($("#toast-region").textContent, "");
	} finally {
		vi.useRealTimers();
	}
});

test("server-background cache refresh events show a brief refresh toast", () => {
	vi.useFakeTimers();
	try {
		document.dispatchEvent(
			new CustomEvent("toolhub:api-cache-refresh", {
				detail: { url: "/api/recent/", state: "server-background" }
			})
		);
		assert.equal($("#toast-region").textContent, "Refreshing live Toolhub data…");
		vi.advanceTimersByTime(1800);
		assert.equal($("#toast-region").textContent, "");
	} finally {
		vi.useRealTimers();
	}
});

test("the initial theme toggle reflects the resolved <html data-theme>", () => {
	const html = $("#theme-toggle").innerHTML;
	// data-theme="dark" → the dark option is active, light is not.
	assert.match(
		html,
		/class="theme-toggle__opt is-active" role="radio" aria-checked="true" data-theme-choice="dark" title="Dark theme" aria-label="Dark theme"/
	);
	assert.match(
		html,
		/class="theme-toggle__opt" role="radio" aria-checked="false" data-theme-choice="light" title="Light theme" aria-label="Light theme"/
	);
	// The option icons are the sun (light) and moon (dark) glyphs (matched by their path data,
	// which survives DOM re-serialization unlike the self-closing <path/> form).
	assert.match(html, /d="M10 14a4 4 0 110-8/); // sun
	assert.match(html, /d="M10 1a9 9 0 108\.66 11\.46/); // moon
	// The two options are joined with "" (adjacent, no separator text).
	assert.match(html, /<\/button><button type="button"/);
});

test("setAuthRender callback re-renders the account and the route", () => {
	vi.clearAllMocks();
	assert.equal(typeof authRenderCb, "function");
	authRenderCb();
	assert.equal(account.renderAccount.mock.calls.length, 1);
	assert.equal(router.render.mock.calls.length, 1);
});

/* ---- theme toggle ------------------------------------------------------ */

test("clicking a theme option sets the choice and re-renders; a stray click does nothing", () => {
	vi.clearAllMocks();
	const opt = $('#theme-toggle [data-theme-choice="light"]');
	click(opt);
	assert.deepEqual(theme.setThemeChoice.mock.calls[0], ["light"]);

	vi.clearAllMocks();
	click($("#theme-toggle")); // not a [data-theme-choice] target
	assert.equal(theme.setThemeChoice.mock.calls.length, 0);
});

test("the prefers-color-scheme change listener re-renders the theme toggle", () => {
	assert.equal(typeof mqlChange, "function");
	document.documentElement.setAttribute("data-theme", "light");
	mqlChange();
	assert.match(
		$("#theme-toggle").innerHTML,
		/class="theme-toggle__opt is-active" role="radio" aria-checked="true" data-theme-choice="light"/
	);
	document.documentElement.setAttribute("data-theme", "dark"); // restore
});

/* ---- skip link --------------------------------------------------------- */

test("the skip link focuses and scrolls the view without navigating", () => {
	vi.clearAllMocks();
	const viewEl = $("#view");
	viewEl.scrollIntoView = vi.fn();
	const focusSpy = vi.spyOn(viewEl, "focus");
	const ev = new window.MouseEvent("click", { bubbles: true, cancelable: true });
	$(".skip").dispatchEvent(ev);
	assert.equal(ev.defaultPrevented, true);
	assert.equal(focusSpy.mock.calls.length, 1);
	assert.equal(viewEl.scrollIntoView.mock.calls.length, 1);
	focusSpy.mockRestore();
});

/* ---- #view click ------------------------------------------------------- */

test("#view: clicking a favorite toggles it and stops propagation", () => {
	vi.clearAllMocks();
	store.toggleFav.mockReturnValue("ON");
	const ev = new window.MouseEvent("click", { bubbles: true, cancelable: true });
	$('#view [data-fav="tool-a"]').dispatchEvent(ev);
	assert.equal(ev.defaultPrevented, true);
	assert.deepEqual(store.toggleFav.mock.calls[0], ["tool-a"]);
	assert.deepEqual(favbtn.syncFavButtons.mock.calls[0], ["tool-a", "ON"]);
	// stopPropagation → the document SPA handler never sees it as a navigation.
	assert.equal(routing.navigateTo.mock.calls.length, 0);
});

test("#view: favorite add/remove writes to official Toolhub when signed in", async () => {
	vi.clearAllMocks();
	serversync.officialWriteAvailable.mockReturnValueOnce(true).mockReturnValueOnce(true);
	store.toggleFav.mockReturnValueOnce(true).mockReturnValueOnce(false);
	click($('#view [data-fav="tool-a"]'));
	click($('#view [data-fav="tool-a"]'));
	await Promise.resolve();
	assert.deepEqual(serversync.officialWrite.mock.calls[0], ["POST", "/v1/write/user/favorites/", { name: "tool-a" }]);
	assert.deepEqual(serversync.officialWrite.mock.calls[1], ["DELETE", "/v1/write/user/favorites/tool-a/", undefined]);
});

test("#view: favorite official-write rejection leaves the local favorite state intact", async () => {
	vi.clearAllMocks();
	serversync.officialWriteAvailable.mockReturnValueOnce(true);
	serversync.officialWrite.mockRejectedValueOnce(new Error("upstream refused"));
	store.toggleFav.mockReturnValueOnce(true);
	click($('#view [data-fav="tool-a"]'));
	await Promise.resolve();
	assert.deepEqual(store.toggleFav.mock.calls[0], ["tool-a"]);
	assert.deepEqual(favbtn.syncFavButtons.mock.calls[0], ["tool-a", true]);
	assert.deepEqual(serversync.officialWrite.mock.calls[0], ["POST", "/v1/write/user/favorites/", { name: "tool-a" }]);
});

test("#view: clicking add-to-list toggles state and swaps the mark icon", () => {
	vi.clearAllMocks();
	store.listToolToggle.mockReturnValue(true);
	const btn = $("#view [data-listadd]");
	click(btn);
	assert.deepEqual(store.listToolToggle.mock.calls[0], ["list-1", "tool-a"]);
	assert.equal(btn.classList.contains("is-on"), true);
	assert.equal(btn.getAttribute("aria-pressed"), "true");
	assert.match(btn.querySelector(".savemenu__mark").innerHTML, /d="M18\.154 3\.837/); // "on" → check icon

	vi.clearAllMocks();
	store.listToolToggle.mockReturnValue(false);
	click(btn);
	assert.equal(btn.classList.contains("is-on"), false);
	assert.equal(btn.getAttribute("aria-pressed"), "false");
	assert.match(btn.querySelector(".savemenu__mark").innerHTML, /d="M11\.005 9H16v2/); // "off" → add icon

	// A list button without a .savemenu__mark child must not throw (the `if (m)` guard).
	vi.clearAllMocks();
	assert.doesNotThrow(() => click($('#view [data-listadd="list-2"]')));
});

test("#view: clicking a keyword chip navigates to a search", () => {
	vi.clearAllMocks();
	click($('#view [data-q="wiki edits"]'));
	assert.deepEqual(routing.navigateTo.mock.calls[0], ["/search?q=wiki%20edits"]);
	assert.equal(quickview.openQuickView.mock.calls.length, 0);
});

test("#view: a data-q anchor is treated as a link, not a chip", () => {
	vi.clearAllMocks();
	click($('#view a[data-q="ignored"]'));
	// q-block skipped (it matches a[href]); openQuickView not called; the link routes via the SPA handler.
	assert.equal(quickview.openQuickView.mock.calls.length, 0);
	assert.deepEqual(routing.navigateTo.mock.calls.at(-1), ["/about"]);
});

test("#view: clicking a card body opens the quick view", async () => {
	vi.clearAllMocks();
	click($("#view .tcard__inner")); // inside the [data-tool] card, not a link
	await settleDynamicImports();
	assert.deepEqual(quickview.openQuickView.mock.calls[0], ["tool-x"]);
});

test("#view: clicking bare non-interactive content does nothing", () => {
	vi.clearAllMocks();
	click($("#view .bare"));
	assert.equal(quickview.openQuickView.mock.calls.length, 0);
	assert.equal(routing.navigateTo.mock.calls.length, 0);
});

test("#view: a link inside a card routes natively and never opens the quick view", () => {
	// The `if (e.target?.closest("a[href]")) return;` early-return must fire even though the
	// link sits inside a [data-tool] card (kills `if (false) return`).
	vi.clearAllMocks();
	click($('#view a[href="/incard"]'));
	assert.equal(quickview.openQuickView.mock.calls.length, 0);
	assert.deepEqual(routing.navigateTo.mock.calls.at(-1), ["/incard"]);
});

/* ---- #view keydown ----------------------------------------------------- */

test("#view: Enter/Space on a focused card opens the quick view; other keys/targets do not", async () => {
	vi.clearAllMocks();
	const card = $('#view [data-tool="tool-x"]');
	keydown(card, "Enter");
	await settleDynamicImports();
	assert.deepEqual(quickview.openQuickView.mock.calls[0], ["tool-x"]);

	vi.clearAllMocks();
	keydown(card, " ");
	await settleDynamicImports();
	assert.deepEqual(quickview.openQuickView.mock.calls[0], ["tool-x"]);

	vi.clearAllMocks();
	keydown(card, "a"); // not Enter/Space
	assert.equal(quickview.openQuickView.mock.calls.length, 0);

	vi.clearAllMocks();
	keydown($("#view .tcard__inner"), "Enter"); // target is not the card itself
	assert.equal(quickview.openQuickView.mock.calls.length, 0);
});

/* ---- #qv click --------------------------------------------------------- */

test("#qv: a favorite toggles; the backdrop and close button dismiss the modal", async () => {
	vi.clearAllMocks();
	store.toggleFav.mockReturnValue("Q");
	click($('#qv [data-fav="tool-b"]'));
	assert.deepEqual(store.toggleFav.mock.calls[0], ["tool-b"]); // read from data-fav
	assert.deepEqual(favbtn.syncFavButtons.mock.calls[0], ["tool-b", "Q"]);
	assert.equal(quickview.closeQuickView.mock.calls.length, 0); // fav path returns early

	await loadQuickViewForTest();
	vi.clearAllMocks();
	click($("#qv [data-qv-close]"));
	await settleDynamicImports();
	assert.equal(quickview.closeQuickView.mock.calls.length, 1);

	vi.clearAllMocks();
	click($("#qv")); // backdrop (target.id === "qv")
	await settleDynamicImports();
	assert.equal(quickview.closeQuickView.mock.calls.length, 1);

	vi.clearAllMocks();
	click($("#qv .qv-body")); // inside content, not close → stays open
	assert.equal(quickview.closeQuickView.mock.calls.length, 0);
});

/* ---- document keydown -------------------------------------------------- */

test("Escape closes the modal and menus; any other key feeds the focus trap", async () => {
	await loadQuickViewForTest();
	vi.clearAllMocks();
	keydown(document.body, "Escape");
	await settleDynamicImports();
	assert.equal(quickview.closeQuickView.mock.calls.length, 1);
	assert.equal(account.closeAcctMenu.mock.calls.length, 1);
	assert.equal(langpicker.closeLangMenu.mock.calls.length, 1);
	assert.equal(quickview.qvTrap.mock.calls.length, 0);

	vi.clearAllMocks();
	keydown(document.body, "Tab");
	await settleDynamicImports();
	assert.equal(quickview.qvTrap.mock.calls.length, 1);
	assert.equal(quickview.closeQuickView.mock.calls.length, 0);
});

test("route-render-start closes entrypoint-owned transient UI", async () => {
	await loadQuickViewForTest();
	vi.clearAllMocks();
	document.dispatchEvent(new window.Event("toolhub:route-render-start"));
	await settleDynamicImports();
	assert.equal(account.closeAcctMenu.mock.calls.length, 1);
	assert.equal(quickview.closeQuickView.mock.calls.length, 1);
});

/* ---- #account ---------------------------------------------------------- */

test("#account: the button toggles the menu", () => {
	vi.clearAllMocks();
	click($("#acct-btn"));
	assert.equal(account.toggleAcctMenu.mock.calls.length, 1);
});

test("#account: a menu link closes the menu (lets navigation happen natively)", () => {
	vi.clearAllMocks();
	click($("#acct-menu a"));
	assert.equal(account.closeAcctMenu.mock.calls.length > 0, true);
});

test("#account: a click matching none of the menu actions does nothing", () => {
	// Clicking the menu container itself matches no action: reset must not fire (kills the
	// reset `if (true)`), and the menu must not close (kills the menu-link `if (true)`).
	vi.clearAllMocks();
	click($("#acct-menu"));
	assert.equal(store.demoStore.clearAll.mock.calls.length, 0);
	assert.equal(account.closeAcctMenu.mock.calls.length, 0);
});

test("a document click outside the account menu closes it", () => {
	vi.clearAllMocks();
	click($("#view")); // outside #account
	assert.equal(account.closeAcctMenu.mock.calls.length > 0, true);
});

/* ---- #langpicker ------------------------------------------------------- */

test("#langpicker: the button toggles the menu; a language shows the not-yet note", () => {
	vi.clearAllMocks();
	click($("#lang-btn"));
	assert.equal(langpicker.toggleLangMenu.mock.calls.length, 1);

	vi.clearAllMocks();
	click($("#langpicker [data-lang]"));
	assert.deepEqual(langpicker.showLangNote.mock.calls[0], ["Français"]);
	// A click inside the picker must NOT trigger the outside-click closer (kills `if (true)`
	// on the document langpicker-outside handler).
	assert.equal(langpicker.closeLangMenu.mock.calls.length, 0);
});

test("#langpicker: an available language persists selection and reloads", () => {
	vi.clearAllMocks();
	const opt = $("#langpicker [data-lang]");
	opt.setAttribute("data-lang", "en");
	const reloadSpy = vi.spyOn(window.location, "reload").mockImplementation(() => {});
	try {
		click(opt);
		assert.deepEqual(i18n.setLocale.mock.calls[0], ["en"]);
		assert.equal(reloadSpy.mock.calls.length, 1);
		assert.equal(langpicker.showLangNote.mock.calls.length, 0);
	} finally {
		opt.setAttribute("data-lang", "");
		reloadSpy.mockRestore();
	}
});

test("a document click outside the language picker closes it", () => {
	vi.clearAllMocks();
	click($("#view")); // outside #langpicker
	assert.equal(langpicker.closeLangMenu.mock.calls.length > 0, true);
});

/* ---- site notice ------------------------------------------------------- */

test("the site notice close button hides the notice and persists dismissal", () => {
	vi.clearAllMocks();
	localStorage.removeItem("toolhub-sitenotice-dismissed");
	document.documentElement.classList.remove("sitenotice-dismissed");
	click($("[data-dismiss-sitenotice]"));
	assert.equal(localStorage.getItem("toolhub-sitenotice-dismissed"), "1");
	assert.equal(document.documentElement.classList.contains("sitenotice-dismissed"), true);
	assert.equal($("[data-sitenotice]").hasAttribute("hidden"), true);
});

/* ---- SPA link interception -------------------------------------------- */

test("SPA links: internal links route via navigateTo; special links are left to the browser", () => {
	vi.clearAllMocks();
	const ev = new window.MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
	$('#view a[href="/internal?x=1"]').dispatchEvent(ev);
	assert.equal(ev.defaultPrevented, true);
	assert.deepEqual(routing.navigateTo.mock.calls.at(-1), ["/internal?x=1"]);

	const cases = [
		'a[href="/api/tools/"]',
		'a[href="https://ext.example/"]',
		'a[href="#frag"]',
		"a[download]",
		'a[target="_blank"]'
	];
	for (const sel of cases) {
		vi.clearAllMocks();
		const e = new window.MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
		$(`#view ${sel}`).dispatchEvent(e);
		assert.equal(routing.navigateTo.mock.calls.length, 0, `${sel} should not navigate`);
	}
});

test("SPA links: modified clicks (ctrl/meta/shift/alt or non-left button) are ignored", () => {
	for (const mod of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }]) {
		vi.clearAllMocks();
		const e = new window.MouseEvent("click", { bubbles: true, cancelable: true, button: 0, ...mod });
		$('#view a[href="/internal?x=1"]').dispatchEvent(e);
		assert.equal(routing.navigateTo.mock.calls.length, 0, `${JSON.stringify(mod)} should be ignored`);
	}
});

test("SPA links: feature-status try links route without feature-mode side effects", () => {
	vi.clearAllMocks();
	const ev = new window.MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
	$('#view a[href="/features"]').dispatchEvent(ev);
	assert.equal(ev.defaultPrevented, true);
	assert.deepEqual(routing.navigateTo.mock.calls.at(-1), ["/features"]);
});

/* ---- history events ---------------------------------------------------- */

test("popstate and toolhub:navigate re-render the route", () => {
	vi.clearAllMocks();
	window.dispatchEvent(new window.Event("popstate"));
	assert.equal(router.render.mock.calls.length, 1);

	vi.clearAllMocks();
	window.dispatchEvent(new window.Event("toolhub:navigate"));
	assert.equal(router.render.mock.calls.length, 1);
});

/* ---- optional-chaining guards: a null event target must never throw --- */

test("handlers tolerate a null event.target (the e.target?. guards)", () => {
	// happy-dom keeps an overridden null target and re-throws listener exceptions, so removing
	// any `e.target?.` (→ `e.target.`) would make these dispatches throw. Asserting no-throw
	// across every handler kills those optional-chaining mutants.
	const fire = (el, type, key) => {
		const ev =
			type === "keydown"
				? new window.KeyboardEvent("keydown", { bubbles: true, cancelable: true, key })
				: new window.MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
		Object.defineProperty(ev, "target", { value: null, configurable: true });
		el.dispatchEvent(ev);
	};
	assert.doesNotThrow(() => fire($("#theme-toggle"), "click")); // 55
	assert.doesNotThrow(() => fire($("#view"), "click")); // view + document click handlers
	assert.doesNotThrow(() => fire($("#view"), "keydown", "Enter")); // 112
	assert.doesNotThrow(() => fire($("#qv"), "click")); // 121/127
	assert.doesNotThrow(() => fire($("#acct-btn"), "click")); // 146/151/157/162/169
	assert.doesNotThrow(() => fire($("#lang-btn"), "click")); // 186/191
});

/* ---- import-time guards (re-imported with missing elements) ----------- */

test("main re-imports cleanly with the full shell (every selector stays valid)", async () => {
	// An in-test import: if any selector literal were mutated to "" then querySelector("")
	// throws during evaluation and this test fails.
	document.body.innerHTML = SHELL;
	await import("../../public_html/main.js?v=fullshell");
});

test("with #view/#qv absent the listener wiring no-ops and the skip link tolerates a missing view", async () => {
	// $("#view")?.addEventListener / $("#qv")?.addEventListener must short-circuit (not throw),
	// and the skip handler's m?.focus()/m?.scrollIntoView() must tolerate a null view.
	document.body.innerHTML = '<a class="skip" href="#view">Skip</a>';
	try {
		await import("../../public_html/main.js?v=noview");
		const ev = new window.MouseEvent("click", { bubbles: true, cancelable: true });
		assert.doesNotThrow(() => document.querySelector(".skip").dispatchEvent(ev));
	} finally {
		document.body.innerHTML = SHELL;
	}
});

test("main imports without throwing when optional elements are absent", async () => {
	// No skip / theme-toggle / account / langpicker, and no matchMedia: every
	// `if (el)` / `if (window.matchMedia)` guard must take its false branch cleanly.
	document.body.innerHTML = '<main id="view"></main><div id="qv"></div>';
	const savedMM = window.matchMedia;
	delete window.matchMedia;
	try {
		await import("../../public_html/main.js?v=bare");
		assert.equal(router.render.mock.calls.length > 0, true); // import still completed
	} finally {
		window.matchMedia = savedMM;
		document.body.innerHTML = SHELL; // restore for any later use
	}
});

test("main boot fetches and installs a stored non-English message catalog", async () => {
	vi.clearAllMocks();
	localStorage.setItem(i18n.LOCALE_KEY, "fr");
	api.backendGetJson.mockResolvedValueOnce({ "app.title": "Catalogue" });
	document.body.innerHTML = SHELL;
	try {
		await import("../../public_html/main.js?v=frboot");
		assert.equal(router.render.mock.calls.length > 0, true);
		assert.equal(api.backendGetJson.mock.calls.length, 0);
		await settleBootTasks();
		assert.deepEqual(api.backendGetJson.mock.calls[0], ["/i18n/fr.json"]);
		assert.deepEqual(i18n.setMessages.mock.calls[0], [{ "app.title": "Catalogue" }]);
		assert.equal(account.renderAccount.mock.calls.length > 0, true);
		assert.equal(account.syncSubmitButton.mock.calls.length > 0, true);
		assert.equal(router.render.mock.calls.length > 0, true);
	} finally {
		localStorage.removeItem(i18n.LOCALE_KEY);
		document.body.innerHTML = SHELL;
	}
});

test("main boot ignores a failed stored-locale catalog fetch", async () => {
	vi.clearAllMocks();
	localStorage.setItem(i18n.LOCALE_KEY, "fr");
	api.backendGetJson.mockRejectedValueOnce(new Error("catalog down"));
	document.body.innerHTML = SHELL;
	try {
		await import("../../public_html/main.js?v=frboot-fail");
		await settleBootTasks();
		assert.deepEqual(api.backendGetJson.mock.calls[0], ["/i18n/fr.json"]);
		assert.equal(i18n.setMessages.mock.calls.length, 0);
	} finally {
		localStorage.removeItem(i18n.LOCALE_KEY);
		document.body.innerHTML = SHELL;
	}
});

test("main boot skips message install when a stored-locale catalog is empty", async () => {
	vi.clearAllMocks();
	localStorage.setItem(i18n.LOCALE_KEY, "fr");
	api.backendGetJson.mockResolvedValueOnce(null);
	document.body.innerHTML = SHELL;
	try {
		await import("../../public_html/main.js?v=frboot-empty");
		await settleBootTasks();
		assert.deepEqual(api.backendGetJson.mock.calls[0], ["/i18n/fr.json"]);
		assert.equal(i18n.setMessages.mock.calls.length, 0);
	} finally {
		localStorage.removeItem(i18n.LOCALE_KEY);
		document.body.innerHTML = SHELL;
	}
});

test("main boot treats the pseudolocale as generated fallback text", async () => {
	vi.clearAllMocks();
	localStorage.setItem(i18n.LOCALE_KEY, "en-x-pseudo");
	document.body.innerHTML = SHELL;
	try {
		await import("../../public_html/main.js?v=pseudoboot");
		await settleBootTasks();
		assert.equal(api.backendGetJson.mock.calls.length, 0);
		assert.equal(i18n.setMessages.mock.calls.length, 0);
	} finally {
		localStorage.removeItem(i18n.LOCALE_KEY);
		document.body.innerHTML = SHELL;
	}
});

test("main boot tolerates server-sync initialization failure", async () => {
	vi.clearAllMocks();
	serversync.initServerSync.mockRejectedValueOnce(new Error("session down"));
	document.body.innerHTML = SHELL;
	try {
		await import("../../public_html/main.js?v=syncfail");
		assert.equal(serversync.initServerSync.mock.calls.length, 0);
		await settleBootTasks();
		assert.equal(serversync.initServerSync.mock.calls.length, 1);
		assert.equal(router.render.mock.calls.length > 0, true);
	} finally {
		document.body.innerHTML = SHELL;
	}
});
