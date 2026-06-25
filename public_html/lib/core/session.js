// SPDX-License-Identifier: GPL-3.0-or-later
/* ---- Experimental mode -------------------------------------------------
   "Experimental" features are ones we can't fully back with today's Toolhub
   API/data. Each is marked `class="experimental"` in the DOM and documented
   inline with what's MISSING. When the header toggle is OFF, body gets
   `.exp-off` and CSS hides every `.experimental` element, leaving only the
   genuinely shippable UI. Default: OFF. */
export const EXP_KEY = "toolhub-exp";
// Persisted opt-in flag (storage stays in core; the app layer calls these).
export function expStored() {
	return localStorage.getItem(EXP_KEY) === "on";
}
export function setExpStored(on) {
	localStorage.setItem(EXP_KEY, on ? "on" : "off");
}
// Experimental mode is held in memory here so core stays DOM-free; the app layer
// (main.js) reflects it into the DOM (body.exp-off + the toggle's aria-checked).
let expActive = false;
export function expOn() {
	return expActive;
}
export function applyExp(on) {
	expActive = Boolean(on);
}
// Default OFF (decision §8.1): first visit is the honest live read-only
// interface; the user opts into experiments via the toggle.

/* ---- Account: logged-in user fixture + profile dropdown ---------------- */
export const USER = { name: "Ada Lovelace" }; // mock demo identity (sign-in is a Lane B experiment)
export const AUTH_KEY = "toolhub-auth";
// EXPERIMENTAL — mock identity. Needs: real Wikimedia OAuth + server session.
// Signed-in state only exists while experiments are on; default is signed-in.
export function signedIn() {
	return expOn() && localStorage.getItem(AUTH_KEY) !== "out";
}
let authRender = () => {};
export function setAuthRender(fn) {
	authRender = typeof fn === "function" ? fn : () => {};
}
export function setAuth(on) {
	if (on) localStorage.removeItem(AUTH_KEY);
	else localStorage.setItem(AUTH_KEY, "out");
	authRender(); // refresh fav buttons / gated views
}
