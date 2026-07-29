// SPDX-License-Identifier: GPL-3.0-or-later
/* ---- Evolved feature mode ----------------------------------------------
   Evolved additions are now part of the production surface: official-first
   write paths, local fallback/draft overlays, and Evolved-only backend data.
   The legacy storage key/exported helpers remain as compatibility shims for
   older tests and modules, but there is no user-facing feature toggle. */
export const EXP_KEY = "toolhub-exp";
export function expStored() {
	return true;
}
/** @param {boolean} _on */
export function setExpStored(_on) {
	localStorage.removeItem(EXP_KEY);
}
export function expOn() {
	return true;
}
/** @param {unknown} _on */
export function applyExp(_on) {
	localStorage.removeItem(EXP_KEY);
}

export const SITENOTICE_KEY = "toolhub-sitenotice-dismissed";
export function dismissSiteNotice() {
	localStorage.setItem(SITENOTICE_KEY, "1");
}

/* ---- Account: identity + profile dropdown ------------------------------ */
export const USER = { name: "" };
export const AUTH_KEY = "toolhub-auth";

/* ---- Real server session (production sign-in) ---------------------------
   When the backend reports an authenticated Toolhub session (serversync.js),
   the real username replaces the signed-out state; writes then persist
   server-side instead of only in this browser. */
/** @type {string | null} */
let serverUser = null;
let serverSessionChecked = false;
export function serverUserName() {
	return serverUser;
}
export function serverSessionResolved() {
	return serverSessionChecked;
}

// Signed-in state is production-only: a real Toolhub OAuth-backed server
// session. Browser-local demo identity is not allowed in clean production.
export function signedIn() {
	return serverUser !== null;
}
/** @type {() => void} */
let authRender = () => {};
/** @param {unknown} fn */
export function setAuthRender(fn) {
	authRender = typeof fn === "function" ? /** @type {() => void} */ (fn) : () => {};
}
export function setServerSessionPending() {
	serverSessionChecked = false;
	serverUser = null;
	USER.name = "";
	authRender();
}
/** @param {boolean} _on */
export function setAuth(_on) {
	localStorage.removeItem(AUTH_KEY);
	authRender(); // refresh fav buttons / gated views
}
/** @param {string | null} name */
export function setServerUser(name) {
	serverSessionChecked = true;
	serverUser = name;
	if (name) {
		USER.name = name;
	} else {
		USER.name = "";
	}
	authRender();
}
