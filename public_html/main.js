// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$ } from "./lib/core/dom.js";
import { applyLocaleAttrs } from "./lib/core/i18n.js";
import { EXP_KEY, applyExp, expOn, setAuth, setAuthRender } from "./lib/core/session.js";
import { getThemeChoice, initTheme, setThemeChoice } from "./lib/core/theme.js";
import { demoStore, listToolToggle, toggleFav } from "./lib/core/store.js";
import { navigateTo, normalizeLegacyHashRoute } from "./lib/core/routing.js";
import { icon } from "./lib/atoms/icon.js";
import { syncFavButtons } from "./lib/molecules/favbtn.js";
import { closeAcctMenu, renderAccount, syncSubmitButton, toggleAcctMenu } from "./lib/organisms/account.js";
import { closeQuickView, openQuickView, qvTrap } from "./lib/organisms/quickview.js";
import { render } from "./views/router.js";

setAuthRender(render);
applyLocaleAttrs();
applyExp(localStorage.getItem(EXP_KEY) === "on");

/* Color theme: Light/Dark toggle. The active option reflects the RESOLVED theme
   (<html data-theme>), so it shows the right state even before an explicit choice
   is made (System is the implicit default only while nothing is stored). */
initTheme();
const THEME_OPTS = [["system", "System theme", "system"], ["light", "Light theme", "sun"], ["dark", "Dark theme", "moon"]];
function renderThemeToggle() {
	const el = $("#theme-toggle"); if (!el) return;
	const active = getThemeChoice();
	el.innerHTML = THEME_OPTS.map(([val, label, ic]) =>
		`<button type="button" class="theme-toggle__opt${val === active ? " is-active" : ""}" role="radio" aria-checked="${val === active}" data-theme-choice="${val}" title="${label}" aria-label="${label}">${icon(ic)}</button>`).join("");
}
renderThemeToggle();
const themeToggle = $("#theme-toggle");
if (themeToggle) themeToggle.addEventListener("click", (e) => {
	const btn = e.target.closest("[data-theme-choice]"); if (!btn) return;
	setThemeChoice(btn.getAttribute("data-theme-choice"));
	renderThemeToggle();
});
// While no explicit choice is stored, keep the active highlight in sync with the OS.
if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", renderThemeToggle);

/* Skip link focuses the view without hijacking the route. */
const skip = $(".skip");
if (skip) skip.addEventListener("click", (e) => { e.preventDefault(); const m = $("#view"); m.focus(); m.scrollIntoView(); });

/* Keyword chips inside tool cards filter search; card body clicks open peek. */
$("#view").addEventListener("click", (e) => {
const fav = e.target.closest("[data-fav]");
if (fav) { e.preventDefault(); e.stopPropagation(); syncFavButtons(fav.getAttribute("data-fav"), toggleFav(fav.getAttribute("data-fav"))); return; }
const add = e.target.closest("[data-listadd]");
if (add) {
	e.preventDefault();
	const on = listToolToggle(add.getAttribute("data-listadd"), add.getAttribute("data-tn"));
	add.classList.toggle("is-on", on);
	add.setAttribute("aria-pressed", String(on));
	const m = add.querySelector(".savemenu__mark"); if (m) m.innerHTML = on ? icon("check") : icon("add");
	return;
}
const q = e.target.closest("[data-q]");
if (q && !q.matches("a[href]")) { e.preventDefault(); navigateTo("/search?q=" + encodeURIComponent(q.getAttribute("data-q"))); return; }
if (e.target.closest("a[href]")) return; // real links route natively
const card = e.target.closest("[data-tool]");
if (card) { openQuickView(card.getAttribute("data-tool")); } // default: peek
});
// Keyboard: Enter/Space on a focused tool card opens the quick-view.
$("#view").addEventListener("keydown", (e) => {
if (e.key !== "Enter" && e.key !== " ") return;
const card = e.target.closest("[data-tool]");
if (card && e.target === card) { e.preventDefault(); openQuickView(card.getAttribute("data-tool")); }
});

/* Quick-view modal: backdrop/close, Esc + Tab-trap */
$("#qv").addEventListener("click", (e) => {
const fav = e.target.closest("[data-fav]");
if (fav) { e.preventDefault(); syncFavButtons(fav.getAttribute("data-fav"), toggleFav(fav.getAttribute("data-fav"))); return; }
if (e.target.id === "qv" || e.target.closest("[data-qv-close]")) { e.preventDefault(); closeQuickView(); return; }
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeQuickView(); closeAcctMenu(); } else { qvTrap(e); } });

/* Account dropdown: toggle, log out / log in, close on outside click */
const accountEl = document.getElementById("account");
if (accountEl) accountEl.addEventListener("click", (e) => {
if (e.target.closest("#acct-btn")) { e.preventDefault(); toggleAcctMenu(); return; }
if (e.target.closest("[data-logout]")) { e.preventDefault(); closeAcctMenu(); setAuth(false); return; }
if (e.target.closest("[data-login]")) { e.preventDefault(); setAuth(true); return; }
if (e.target.closest("[data-reset]")) { e.preventDefault(); closeAcctMenu(); demoStore.clearAll(); render(); return; }
if (e.target.closest("#acct-menu a, #acct-menu button")) { closeAcctMenu(); } // links route natively
});
document.addEventListener("click", (e) => { if (!e.target.closest("#account")) closeAcctMenu(); });
renderAccount();
syncSubmitButton();

/* Experimental toggle: persist, flip body state, re-render so JS-conditional
   experimental logic (e.g. the sort options) updates too. */
const expBtn = $("#exp-toggle");
if (expBtn) expBtn.addEventListener("click", () => {
const on = !expOn();
localStorage.setItem(EXP_KEY, on ? "on" : "off");
applyExp(on);
renderAccount(); // identity is experimental — reflect the new state
syncSubmitButton();
render();
});

/* Clean SPA links use the History API; direct loads are handled by the Flask fallback. */
document.addEventListener("click", (e) => {
	if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
	const a = e.target.closest("a[href]");
	if (!a) return;
	const href = a.getAttribute("href");
	if (!href || href.startsWith("#") || a.target || a.hasAttribute("download")) return;
	const url = new URL(href, location.href);
	if (url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
	e.preventDefault();
	navigateTo(url.pathname + url.search);
});
window.addEventListener("popstate", render);
window.addEventListener("toolhub:navigate", render);
normalizeLegacyHashRoute();
render();
