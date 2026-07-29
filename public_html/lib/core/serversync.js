// SPDX-License-Identifier: GPL-3.0-or-later
/* Production server sync — the client half of the /v1 overlay API.
   On boot, ask the backend who we are. With a real Toolhub session, pull the
   server-side overlay into the localStorage cache (store.js) and register the
   write-through hook so every later mutation is pushed back. Logged out, the
   app stays read-only for write features; we only remember whether OAuth is
   configured so the UI can offer the real sign-in. */
import { backendGetJson, backendPutJson, backendWriteJson, invalidateApiCacheForOfficialWrite } from "./api.js";
import { setServerUser } from "./session.js";
import { DEMO_KEYS, SOURCE, SYNC_STATUS, demoStore, setStoreSync, withSyncMuted } from "./store.js";

let csrf = "";
let oauthReady = false;
let devLoginReady = false;
let officialWriteReady = false;
// Pushes are serialized on one chain so overlay writes reach the server in
// mutation order (each key's PUT replaces that key's server copy wholesale).
let chain = Promise.resolve();

export function oauthAvailable() {
	return oauthReady;
}

export function devLoginAvailable() {
	return devLoginReady;
}

export function officialWriteAvailable() {
	return officialWriteReady;
}

/** Session CSRF token, for the sign-out form (every other write sends it as a header). */
export function csrfToken() {
	return csrf;
}

/**
 * Perform a CSRF-protected backend write that may call official Toolhub.
 * @param {string} method
 * @param {string} path
 * @param {any} [body]
 * @returns {Promise<any>}
 */
export function serverWrite(method, path, body) {
	if (!csrf) throw new Error("Toolhub sign-in is required");
	return backendWriteJson(method, path, body, csrf);
}

/**
 * Perform a CSRF-protected backend write that may call official Toolhub.
 * @param {string} method
 * @param {string} path
 * @param {any} [body]
 * @returns {Promise<any>}
 */
export function officialWrite(method, path, body) {
	if (!officialWriteReady) {
		throw new Error(csrf ? "Toolhub OAuth grant is required" : "Toolhub sign-in is required");
	}
	return serverWrite(method, path, body).then((data) => {
		invalidateApiCacheForOfficialWrite(method, path, body, data);
		return data;
	});
}

/**
 * Normalize the local metadata block returned by official-first write endpoints.
 * @param {any} res
 * @param {string[]} [extraLocalKeys]
 * @returns {Record<string, any>}
 */
export function lifecycleMeta(res, extraLocalKeys = []) {
	const local = res?.local && typeof res.local === "object" && !Array.isArray(res.local) ? res.local : {};
	const syncStatus =
		local.syncStatus ||
		res?.syncStatus ||
		(res?.result === SYNC_STATUS.official ? SYNC_STATUS.official : SYNC_STATUS.localFallback);
	/** @type {Record<string, any>} */
	const meta = {
		source: local.source || (syncStatus === SYNC_STATUS.official ? SOURCE.official : SOURCE.local),
		syncStatus,
		lastSyncedAt: local.lastSyncedAt || res?.lastSyncedAt,
		lastError: local.lastError || res?.lastError,
		toolhubResponse: local.toolhubResponse || res?.toolhubResponse,
		validationErrors: local.validationErrors || res?.validationErrors,
		officialId: local.officialId
	};
	for (const key of extraLocalKeys) meta[key] = local[key];
	for (const key of Object.keys(meta)) if (meta[key] === undefined) delete meta[key];
	return meta;
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
		csrf = "";
		oauthReady = false;
		devLoginReady = false;
		officialWriteReady = false;
		setServerUser(null);
		return false; // backend unreachable -> read-only write features
	}
	if (!me || !me.authenticated) {
		csrf = "";
		officialWriteReady = false;
		// Logged out: learn whether real sign-in is configured, then let the
		// account UI re-render with (or without) the Toolhub OAuth button.
		try {
			const cfg = await backendGetJson("/v1/config/");
			oauthReady = Boolean(cfg && cfg.oauth);
			devLoginReady = Boolean(cfg && cfg.devLogin);
		} catch {
			oauthReady = false;
			devLoginReady = false;
		}
		setServerUser(null);
		return false;
	}
	csrf = String(me.csrf || "");
	oauthReady = true;
	devLoginReady = false;
	officialWriteReady = me.officialWrites === false ? false : Boolean(csrf);
	let overlay;
	try {
		overlay = await backendGetJson("/v1/overlay/");
	} catch {
		overlay = null;
	}
	if (overlay) {
		withSyncMuted(() => {
			for (const key of Object.values(DEMO_KEYS)) {
				if (overlay[key] !== undefined) demoStore.set(key, overlay[key]);
			}
		});
		setStoreSync(push);
	}
	setServerUser(String(me.username || ""));
	return true;
}
