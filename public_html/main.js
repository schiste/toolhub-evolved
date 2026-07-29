// SPDX-License-Identifier: GPL-3.0-or-later
import { $ } from "./lib/core/dom.js";
import { backendGetJson } from "./lib/core/api.js";
import {
	markAppBootStart,
	markFrontendTimingOnce,
	measureFrontendTiming,
	observeFirstContentPaint
} from "./lib/core/diagnostics.js";
import {
	appLocale,
	applyLocaleAttrs,
	AVAILABLE_LOCALES,
	DEFAULT_LOCALE,
	setLocale,
	setMessages,
	t
} from "./lib/core/i18n.js";
import { dismissSiteNotice, setAuthRender } from "./lib/core/session.js";
import { initServerSync, officialWrite, officialWriteAvailable } from "./lib/core/serversync.js";
import { initTheme, setThemeChoice } from "./lib/core/theme.js";
import { listToolToggle, toggleFav } from "./lib/core/store.js";
import { navigateTo, normalizeLegacyHashRoute } from "./lib/core/routing.js";
import { icon } from "./lib/atoms/icon.js";
import { syncFavButtons } from "./lib/molecules/favbtn.js";
import { closeAcctMenu, renderAccount, syncSubmitButton, toggleAcctMenu } from "./lib/organisms/account.js";
import { initCommandPalette } from "./lib/organisms/command-palette.js";
import { closeLangMenu, renderLangPicker, showLangNote, toggleLangMenu } from "./lib/organisms/langpicker.js";
import { render } from "./views/router.js";

markAppBootStart();
const observedFirstContentPaint = observeFirstContentPaint();
const bootLocale = appLocale();

function activateDeferredStyles() {
	for (const preload of document.querySelectorAll('link[data-deferred-style][rel="preload"]')) {
		if (!(preload instanceof HTMLLinkElement) || preload.dataset.loaded === "1") continue;
		preload.dataset.loaded = "1";
		const stylesheet = document.createElement("link");
		stylesheet.rel = "stylesheet";
		stylesheet.href = preload.href;
		document.head.append(stylesheet);
	}
}
activateDeferredStyles();

/** @type {Promise<typeof import("./lib/organisms/quickview.js")> | null} */
let quickViewModule = null;
function loadQuickView() {
	quickViewModule ||= import("./lib/organisms/quickview.js");
	return quickViewModule;
}
function closeQuickViewIfLoaded() {
	if (!quickViewModule) return;
	quickViewModule.then((m) => m.closeQuickView()).catch(() => undefined);
}
/** @param {KeyboardEvent} e */
function trapQuickViewIfLoaded(e) {
	if (!quickViewModule) return;
	quickViewModule.then((m) => m.qvTrap(e)).catch(() => undefined);
}
/** @param {string} name */
function openQuickViewFor(name) {
	loadQuickView()
		.then((m) => m.openQuickView(name))
		.catch(() => undefined);
}
/** @param {() => void} task */
function afterFirstPaint(task) {
	const run = () => {
		setTimeout(task, 0);
	};
	if (typeof window.requestAnimationFrame === "function") {
		window.requestAnimationFrame(run);
	} else {
		run();
	}
}

setAuthRender(() => {
	renderAccount();
	syncSubmitButton();
	render();
});
applyLocaleAttrs();
if (bootLocale === DEFAULT_LOCALE) {
	markFrontendTimingOnce("labels-loaded", { locale: bootLocale, source: "fallback" });
}

/** @param {string} name */
function toggleFavorite(name) {
	const on = toggleFav(name);
	syncFavButtons(name, on);
	if (officialWriteAvailable()) {
		const path = on ? "/v1/write/user/favorites/" : `/v1/write/user/favorites/${encodeURIComponent(name)}/`;
		officialWrite(on ? "POST" : "DELETE", path, on ? { name } : undefined).catch(() => {
			// Keep the local overlay as a draft if official Toolhub rejects the write.
		});
	}
}
const siteNotice = document.querySelector("[data-sitenotice]");
const siteNoticeDismiss = document.querySelector("[data-dismiss-sitenotice]");
if (siteNoticeDismiss) {
	siteNoticeDismiss.addEventListener("click", () => {
		try {
			dismissSiteNotice();
		} catch {}
		document.documentElement.classList.add("sitenotice-dismissed");
		siteNotice?.setAttribute("hidden", "");
	});
}

/* Color theme: Light/Dark toggle. The active option reflects the RESOLVED theme
   (<html data-theme>), so it shows the right state even before an explicit choice
   is made (System is the implicit default only while nothing is stored). */
initTheme();
// "System" is a default picker, not a toggle option: it is the implicit default used
// while nothing is stored in localStorage (theme.js then follows the OS preference).
// The toggle therefore exposes only Light and Dark.
const THEME_OPTS = [
	["light", "Light theme", "sun"],
	["dark", "Dark theme", "moon"]
];
function renderThemeToggle() {
	const el = $("#theme-toggle");
	if (!el) return;
	const active = document.documentElement.getAttribute("data-theme");
	el.innerHTML = THEME_OPTS.map(
		([val, label, ic]) =>
			`<button type="button" class="theme-toggle__opt${val === active ? " is-active" : ""}" role="radio" aria-checked="${val === active}" data-theme-choice="${val}" title="${label}" aria-label="${label}">${icon(ic)}</button>`
	).join("");
}
renderThemeToggle();
const themeToggle = $("#theme-toggle");
if (themeToggle) {
	themeToggle.addEventListener("click", (e) => {
		const btn = e.target?.closest("[data-theme-choice]");
		if (!btn) return;
		setThemeChoice(/** @type {string} */ (btn.getAttribute("data-theme-choice")));
		renderThemeToggle();
	});
}
// While no explicit choice is stored, keep the active highlight in sync with the OS.
if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", renderThemeToggle);

/* Public API cache refresh toast: stale cached Toolhub data can render first,
   then these events tell users the live refresh is happening in the background. */
const refreshingApiUrls = new Set();
/** @type {ReturnType<typeof setTimeout> | null} */
let apiToastTimer = null;
/** @type {ReturnType<typeof setTimeout> | null} */
let apiRefreshRenderTimer = null;
function toastRegion() {
	let region = $("#toast-region");
	if (region) return region;
	region = document.createElement("div");
	region.id = "toast-region";
	region.className = "toast-region";
	region.setAttribute("aria-live", "polite");
	region.setAttribute("aria-atomic", "true");
	document.body.append(region);
	return region;
}
/** @param {string} message @param {string} [variant] */
function showApiToast(message, variant = "") {
	const region = toastRegion();
	const cls = variant ? ` toast--${variant}` : "";
	const toast = document.createElement("div");
	toast.className = `toast${cls}`;
	toast.setAttribute("role", "status");
	toast.textContent = message;
	region.replaceChildren(toast);
	if (apiToastTimer) clearTimeout(apiToastTimer);
}
/** @param {number} [ms] */
function hideApiToastSoon(ms = 2400) {
	if (apiToastTimer) clearTimeout(apiToastTimer);
	apiToastTimer = setTimeout(() => {
		const region = $("#toast-region");
		if (region) region.innerHTML = "";
	}, ms);
}
function scheduleApiRefreshRender() {
	if (apiRefreshRenderTimer) clearTimeout(apiRefreshRenderTimer);
	apiRefreshRenderTimer = setTimeout(() => {
		apiRefreshRenderTimer = null;
		render();
	}, 150);
}
document.addEventListener("toolhub:api-cache-refresh", (e) => {
	const detail = /** @type {{ url?: string, state?: string }} */ (/** @type {CustomEvent} */ (e).detail || {});
	const url = String(detail.url || "");
	if (detail.state === "start") {
		if (url) refreshingApiUrls.add(url);
		showApiToast(t("api.refreshingLiveData", "Refreshing live Toolhub data…"));
		return;
	}
	if (detail.state === "server-background") {
		if (url) refreshingApiUrls.delete(url);
		showApiToast(t("api.refreshingLiveData", "Refreshing live Toolhub data…"));
		hideApiToastSoon(1800);
		return;
	}
	if (url) refreshingApiUrls.delete(url);
	if (refreshingApiUrls.size > 0) return;
	if (detail.state === "success") {
		showApiToast(t("api.liveDataUpdated", "Live Toolhub data updated."), "success");
		scheduleApiRefreshRender();
		hideApiToastSoon();
	} else if (detail.state === "error") {
		showApiToast(t("api.refreshFailed", "Showing saved Toolhub data; refresh failed."), "warning");
		hideApiToastSoon(3600);
	}
});

/* Skip link focuses the view without hijacking the route. */
const skip = $(".skip");
if (skip) {
	skip.addEventListener("click", (e) => {
		e.preventDefault();
		const m = $("#view");
		m?.focus();
		m?.scrollIntoView();
	});
}

/* Keyword chips inside tool cards filter search; card body clicks open peek. */
$("#view")?.addEventListener("click", (e) => {
	const fav = e.target?.closest("[data-fav]");
	if (fav) {
		e.preventDefault();
		e.stopPropagation();
		toggleFavorite(/** @type {string} */ (fav.getAttribute("data-fav")));
		return;
	}
	const add = e.target?.closest("[data-listadd]");
	if (add) {
		e.preventDefault();
		const on = listToolToggle(
			/** @type {string} */ (add.getAttribute("data-listadd")),
			/** @type {string} */ (add.getAttribute("data-tn"))
		);
		add.classList.toggle("is-on", on);
		add.setAttribute("aria-pressed", String(on));
		const m = add.querySelector(".savemenu__mark");
		if (m) m.innerHTML = on ? icon("check") : icon("add");
		return;
	}
	const q = e.target?.closest("[data-q]");
	if (q && !q.matches("a[href]")) {
		e.preventDefault();
		navigateTo(`/search?q=${encodeURIComponent(/** @type {string} */ (q.getAttribute("data-q")))}`);
		return;
	}
	if (e.target?.closest("a[href]")) return; // real links route natively
	const card = e.target?.closest("[data-tool]");
	if (card) {
		openQuickViewFor(/** @type {string} */ (card.getAttribute("data-tool")));
	} // default: peek
});
// Keyboard: Enter/Space on a focused tool card opens the quick-view.
$("#view")?.addEventListener("keydown", (e) => {
	if (e.key !== "Enter" && e.key !== " ") return;
	const card = e.target?.closest("[data-tool]");
	if (card && e.target === card) {
		e.preventDefault();
		openQuickViewFor(/** @type {string} */ (card.getAttribute("data-tool")));
	}
});

/* Quick-view modal: backdrop/close, Esc + Tab-trap */
$("#qv")?.addEventListener("click", (e) => {
	const fav = e.target?.closest("[data-fav]");
	if (fav) {
		e.preventDefault();
		toggleFavorite(/** @type {string} */ (fav.getAttribute("data-fav")));
		return;
	}
	if (e.target?.id === "qv" || e.target?.closest("[data-qv-close]")) {
		e.preventDefault();
		closeQuickViewIfLoaded();
	}
});
document.addEventListener("toolhub:route-render-start", () => {
	closeAcctMenu();
	closeQuickViewIfLoaded();
});
document.addEventListener("keydown", (e) => {
	if (e.key === "Escape") {
		closeQuickViewIfLoaded();
		closeAcctMenu();
		closeLangMenu();
	} else {
		trapQuickViewIfLoaded(e);
	}
});

/* Account dropdown: toggle and close on outside click */
const accountEl = document.querySelector("#account");
if (accountEl) {
	accountEl.addEventListener("click", (e) => {
		if (e.target?.closest("#acct-btn")) {
			e.preventDefault();
			toggleAcctMenu();
			return;
		}
		if (e.target?.closest("#acct-menu a, #acct-menu button")) {
			closeAcctMenu();
		} // links route natively
	});
}
document.addEventListener("click", (e) => {
	if (!e.target?.closest("#account")) closeAcctMenu();
});
renderAccount();
syncSubmitButton();
initCommandPalette({ beforeOpen: closeQuickViewIfLoaded });

/* Language picker: open/close the dropdown; picking a language shows the
   "not available yet" popin instead of switching locale (prototype is EN only). */
renderLangPicker();
const langEl = document.querySelector("#langpicker");
if (langEl) {
	langEl.addEventListener("click", (e) => {
		if (e.target?.closest("#lang-btn")) {
			e.preventDefault();
			toggleLangMenu();
			return;
		}
		const opt = e.target?.closest("[data-lang]");
		if (opt) {
			e.preventDefault();
			const code = opt.getAttribute("data-lang") || "";
			if (AVAILABLE_LOCALES.includes(code)) {
				// A shipped catalog: persist the choice and reload so every
				// Intl formatter and lang/dir attribute rebinds to it.
				setLocale(code);
				location.reload();
			} else {
				showLangNote(opt.getAttribute("data-lang-name"));
			}
		}
	});
}
document.addEventListener("click", (e) => {
	if (!e.target?.closest("#langpicker")) closeLangMenu();
});

/* Clean SPA links use the History API; direct loads are handled by the Flask fallback. */
document.addEventListener("click", (e) => {
	if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
	const a = /** @type {HTMLAnchorElement | null} */ (e.target?.closest("a[href]"));
	if (!a) return;
	const href = a.getAttribute("href");
	if (!href || href.startsWith("#") || a.target || a.hasAttribute("download")) return;
	const url = new URL(href, location.href);
	// /api/ and /oauth/ are server routes (proxy reads; OAuth redirects) — never SPA-routed.
	const serverRoute = url.pathname.startsWith("/api/") || url.pathname.startsWith("/oauth/");
	if (url.origin !== location.origin || serverRoute) return;
	e.preventDefault();
	navigateTo(url.pathname + url.search);
});
window.addEventListener("popstate", render);
window.addEventListener("toolhub:navigate", render);
normalizeLegacyHashRoute();
Promise.resolve(render()).finally(() => {
	if (!observedFirstContentPaint) {
		markFrontendTimingOnce("first-content-paint", { source: "route-render-fallback" });
	}
	measureFrontendTiming("app-boot", { path: location.pathname });
});
// Non-English locale: fetch its catalog, install it, repaint the chrome.
// (English needs no fetch — the t() fallbacks ARE the English catalog.)
if (bootLocale !== DEFAULT_LOCALE) {
	afterFirstPaint(() => {
		backendGetJson(`/i18n/${encodeURIComponent(bootLocale)}.json`)
			.then((catalog) => {
				if (catalog) {
					setMessages(catalog);
					markFrontendTimingOnce("labels-loaded", { locale: bootLocale, source: "catalog" });
					renderAccount();
					syncSubmitButton();
					render();
				} else {
					markFrontendTimingOnce("labels-loaded", {
						locale: DEFAULT_LOCALE,
						requestedLocale: bootLocale,
						source: "fallback-unavailable"
					});
				}
				return undefined;
			})
			.catch(() => {
				markFrontendTimingOnce("labels-loaded", {
					locale: DEFAULT_LOCALE,
					requestedLocale: bootLocale,
					source: "fallback-after-error"
				});
			});
	});
}
// Production sync: with a real Toolhub session the server overlay replaces
// the browser-local one and mutations write through (lib/core/serversync.js).
// Kicked off after first paint; a re-render follows via the auth-render hook.
afterFirstPaint(() => {
	initServerSync().catch(() => false);
});
