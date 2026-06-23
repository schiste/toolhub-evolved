// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$ } from "./lib/dom.js";
import { applyLocaleAttrs } from "./lib/i18n.js";
import { EXP_KEY, applyExp, closeAcctMenu, expOn, renderAccount, setAuth, setAuthRender, syncSubmitButton, toggleAcctMenu } from "./lib/account.js";
import { demoStore, listToolToggle, toggleFav } from "./lib/store.js";
import { syncFavButtons } from "./lib/cards.js";
import { closeQuickView, openQuickView, qvTrap } from "./lib/quickview.js";
import { render } from "./views/router.js";

setAuthRender(render);
applyLocaleAttrs();
applyExp(localStorage.getItem(EXP_KEY) === "on");

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
	const m = add.querySelector(".savemenu__mark"); if (m) m.textContent = on ? "✓" : "＋";
	return;
}
const q = e.target.closest("[data-q]");
if (q && !q.matches("a[href]")) { e.preventDefault(); location.hash = "#/search?q=" + encodeURIComponent(q.getAttribute("data-q")); return; }
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

/* Most links are real <a href="#/..."> and route natively via hashchange. */
window.addEventListener("hashchange", render);
render();
