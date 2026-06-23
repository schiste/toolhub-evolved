// SPDX-License-Identifier: GPL-3.0-or-later
import { avatar, esc } from "./dom.js";

/* ---- Experimental mode -------------------------------------------------
   "Experimental" features are ones we can't fully back with today's Toolhub
   API/data. Each is marked `class="experimental"` in the DOM and documented
   inline with what's MISSING. When the header toggle is OFF, body gets
   `.exp-off` and CSS hides every `.experimental` element, leaving only the
   genuinely shippable UI. Default: OFF. */
export const EXP_KEY = "toolhub-exp";
export function expOn() { return !document.body.classList.contains("exp-off"); }
export function applyExp(on) {
	document.body.classList.toggle("exp-off", !on);
	const btn = document.getElementById("exp-toggle");
	if (btn) btn.setAttribute("aria-checked", String(on));
}
// Default OFF (decision §8.1): first visit is the honest live read-only
// interface; the user opts into experiments via the toggle.

/* ---- Account: logged-in user fixture + profile dropdown ---------------- */
export const USER = { name: "Schiste" }; // mock demo identity (sign-in is a Lane B experiment)
export const AUTH_KEY = "toolhub-auth";
// EXPERIMENTAL — mock identity. Needs: real Wikimedia OAuth + server session.
// Signed-in state only exists while experiments are on; default is signed-in.
export function signedIn() { return expOn() && localStorage.getItem(AUTH_KEY) !== "out"; }
let authRender = () => {};
export function setAuthRender(fn) { authRender = typeof fn === "function" ? fn : () => {}; }
export function setAuth(on) {
	if (on) localStorage.removeItem(AUTH_KEY); else localStorage.setItem(AUTH_KEY, "out");
	renderAccount(); authRender(); // refresh fav buttons / gated views
}
export function renderAccount() {
	const el = document.getElementById("account");
	if (!el) return;
	if (!expOn()) { // honest read-only: real sign-in needs OAuth we don't have
		el.innerHTML = `<a class="btn btn--outline" href="#/login">Log in</a>`;
		return;
	}
	if (!signedIn()) { // experiments on but logged out → offer the demo sign-in
		el.innerHTML = `<button class="btn btn--outline" type="button" data-login>Sign in <span class="mock-tag">demo</span></button>`;
		return;
	}
	el.innerHTML = `
		<button class="acct__btn" id="acct-btn" type="button" aria-haspopup="true" aria-expanded="false" aria-controls="acct-menu">
			${avatar(USER.name, "avatar--sm")}
			<span class="acct__name">${esc(USER.name)}</span>
			<span class="acct__caret" aria-hidden="true">▾</span>
		</button>
		<div class="acct__menu" id="acct-menu" aria-labelledby="acct-btn" hidden>
			<div class="acct__head">Signed in as <strong>${esc(USER.name)}</strong> <span class="mock-tag">demo</span></div>
			<a href="#/my-lists"><span aria-hidden="true">📋</span> Your lists</a>
			<a href="#/favorites"><span aria-hidden="true">⭐</span> Favorites</a>
			<a href="#/add-or-remove-tools"><span aria-hidden="true">🧰</span> Add or remove tools</a>
			<hr />
			<button class="acct__reset" type="button" data-reset><span aria-hidden="true">🧹</span> Reset demo data</button>
			<button class="acct__logout" type="button" data-logout><span aria-hidden="true">↪</span> Log out</button>
		</div>`;
}
export function closeAcctMenu() {
	const m = document.getElementById("acct-menu"), b = document.getElementById("acct-btn");
	if (m) m.hidden = true;
	if (b) b.setAttribute("aria-expanded", "false");
}
export function toggleAcctMenu() {
	const m = document.getElementById("acct-menu"), b = document.getElementById("acct-btn");
	if (!m) return;
	const willOpen = m.hidden;
	m.hidden = !willOpen;
	b.setAttribute("aria-expanded", String(willOpen));
	if (willOpen) { const first = m.querySelector("a, button"); if (first) first.focus(); }
}

// Header "Submit a tool": in-app create form when experimenting (decision §8.3),
// else the real production link.
export function syncSubmitButton() {
	const b = document.getElementById("submit-tool"); if (!b) return;
	if (expOn()) { b.setAttribute("href", "#/tools/create"); b.removeAttribute("target"); b.removeAttribute("rel"); }
	else { b.setAttribute("href", "https://toolhub.wikimedia.org/tools/create"); b.setAttribute("target", "_blank"); b.setAttribute("rel", "noopener"); }
}
