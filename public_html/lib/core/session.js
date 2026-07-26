// SPDX-License-Identifier: GPL-3.0-or-later
/* ---- Evolved feature mode ----------------------------------------------
   The toggle reveals Toolhub Evolved additions: official-first write paths,
   local fallback/draft overlays, and synthetic signals that Toolhub does not
   expose. Each optional element is marked `class="experimental"` in the DOM.
   When the header toggle is OFF, body gets `.exp-off` and CSS hides those
   elements. Default: OFF. */
export const EXP_KEY = "toolhub-exp";
// Persisted opt-in flag (storage stays in core; the app layer calls these).
export function expStored() {
	return localStorage.getItem(EXP_KEY) === "on";
}
/** @param {boolean} on */
export function setExpStored(on) {
	localStorage.setItem(EXP_KEY, on ? "on" : "off");
}
// Experimental mode is held in memory here so core stays DOM-free; the app layer
// (main.js) reflects it into the DOM (body.exp-off + the toggle's aria-checked).
let expActive = false;
export function expOn() {
	return expActive;
}
/** @param {unknown} on */
export function applyExp(on) {
	expActive = Boolean(on);
}
// Default OFF (decision §8.1): first visit emphasizes the live Toolhub catalog;
// the user opts into Evolved additions via the toggle.

/* ---- Account: identity + profile dropdown ------------------------------ */
export const USER = { name: "Ada Lovelace" }; // demo identity until a real session takes over
export const AUTH_KEY = "toolhub-auth";

/* ---- Real server session (production sign-in) ---------------------------
   When the backend reports an authenticated Toolhub session (serversync.js),
   the real username replaces the demo identity and feature mode turns on —
   writes then persist server-side instead of only in this browser. */
/** @type {string | null} */
let serverUser = null;
export function serverUserName() {
	return serverUser;
}

// Signed-in state exists only while feature mode is on: a real server session
// (Toolhub OAuth) or, failing that, the browser-local demo identity.
export function signedIn() {
	return expOn() && (serverUser !== null || localStorage.getItem(AUTH_KEY) !== "out");
}
/** @type {() => void} */
let authRender = () => {};
/** @param {unknown} fn */
export function setAuthRender(fn) {
	authRender = typeof fn === "function" ? /** @type {() => void} */ (fn) : () => {};
}
/** @param {boolean} on */
export function setAuth(on) {
	if (on) localStorage.removeItem(AUTH_KEY);
	else localStorage.setItem(AUTH_KEY, "out");
	authRender(); // refresh fav buttons / gated views
}
/** @param {string | null} name */
export function setServerUser(name) {
	serverUser = name;
	if (name) {
		USER.name = name;
		// A real session means the features are real for this user: turn the
		// feature mode on (and persist the choice) so the UI renders them.
		setExpStored(true);
		applyExp(true);
	}
	authRender();
}
