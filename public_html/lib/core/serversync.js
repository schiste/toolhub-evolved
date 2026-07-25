// SPDX-License-Identifier: GPL-3.0-or-later
/* Production server sync — the client half of the /v1 overlay API.
   On boot, ask the backend who we are. With a real Wikimedia session, pull the
   server-side overlay into the localStorage cache (store.js) and register the
   write-through hook so every later mutation is pushed back. Logged out, the
   app stays in browser-local demo mode; we only remember whether OAuth is
   configured so the UI can offer the real sign-in. */
import { backendGetJson, backendPutJson } from "./api.js";
import { setServerUser } from "./session.js";
import { DEMO_KEYS, demoStore, setStoreSync, withSyncMuted } from "./store.js";

let csrf = "";
let oauthReady = false;
// Pushes are serialized on one chain so overlay writes reach the server in
// mutation order (each key's PUT replaces that key's server copy wholesale).
let chain = Promise.resolve();

export function oauthAvailable() {
	return oauthReady;
}

/**
 * @param {string} key
 * @param {any} value
 */
function push(key, value) {
	chain = chain.then(() => backendPutJson(`/v1/overlay/${encodeURIComponent(key)}`, value, csrf));
}

/** @returns {Promise<boolean>} true when a real server session is active */
export async function initServerSync() {
	let me;
	try {
		me = await backendGetJson("/v1/user/");
	} catch {
		return false; // backend unreachable → plain demo mode
	}
	if (!me || !me.authenticated) {
		// Logged out: learn whether real sign-in is even configured, then let
		// the account UI re-render with (or without) the Wikimedia button.
		try {
			const cfg = await backendGetJson("/v1/config/");
			oauthReady = Boolean(cfg && cfg.oauth);
		} catch {
			oauthReady = false;
		}
		setServerUser(null);
		return false;
	}
	let overlay;
	try {
		overlay = await backendGetJson("/v1/overlay/");
	} catch {
		overlay = null;
	}
	if (!overlay) return false; // don't go write-through without the server copy
	csrf = String(me.csrf || "");
	withSyncMuted(() => {
		for (const key of Object.values(DEMO_KEYS)) {
			if (overlay[key] !== undefined) demoStore.set(key, overlay[key]);
		}
	});
	oauthReady = true;
	setStoreSync(push);
	setServerUser(String(me.username || ""));
	return true;
}
