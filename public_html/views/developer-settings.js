// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $input, esc } from "../lib/core/dom.js";
import { backendErrorMessage, backendGetJson } from "../lib/core/api.js";
import { t } from "../lib/core/i18n.js";
import { USER } from "../lib/core/session.js";
import { serverWrite } from "../lib/core/serversync.js";
import {
	TOOLINFO_DATA_MODEL_URL,
	TOOLINFO_EXAMPLE_JSON,
	TOOLINFO_SCHEMA_URL,
	TOOLINFO_SCHEMA_VERSION
} from "../lib/core/toolinfo-docs.js";
import { button } from "../lib/atoms/button.js";
import { fArea, fInput } from "../lib/atoms/form-fields.js";
import { icon } from "../lib/atoms/icon.js";
import { linkCard } from "./static.js";

const TOOLHUB_BASE = "https://toolhub.wikimedia.org";
const TOOLHUB_DEVELOPER_SETTINGS_URL = `${TOOLHUB_BASE}/developer-settings`;
const TOOLHUB_API_TOKEN_URL = `${TOOLHUB_BASE}/api/user/authtoken/`;
const TOOLHUB_AUTHORIZED_APPS_URL = `${TOOLHUB_BASE}/api/oauth/authorized/`;

/** @param {string} label @param {string} id @param {number} rows */
function outputArea(label, id, rows) {
	return `<label class="le__label">${esc(label)}
		<textarea class="le__input account-keys__output" id="${esc(id)}" rows="${rows}" readonly></textarea></label>`;
}

/** @param {string} href @param {string} label */
function externalButton(href, label) {
	return button(label, {
		variant: "outline",
		href,
		icon: "external",
		attrs: 'target="_blank" rel="noopener nofollow"'
	});
}

function officialMyAppsUrl() {
	const username = encodeURIComponent(USER.name || "");
	return username
		? `${TOOLHUB_BASE}/api/oauth/applications/?user__username=${username}`
		: TOOLHUB_DEVELOPER_SETTINGS_URL;
}

/** @param {unknown} value */
function areaValue(value) {
	return String(value || "").trim();
}

/** @param {string} id */
function textAreaValue(id) {
	const el = /** @type {HTMLTextAreaElement | null} */ ($(`#${id}`));
	return areaValue(el?.value);
}

/** @param {string} id @param {string} value */
function setTextAreaValue(id, value) {
	const el = /** @type {HTMLTextAreaElement | null} */ ($(`#${id}`));
	if (el) el.value = value;
}

/** @param {string} message @param {"ok" | "err" | ""} [kind] */
function setDeveloperResult(message, kind = "") {
	const out = $("[data-developer-result]");
	if (!out) return;
	out.className = `at__result${kind ? ` at__result--${kind}` : ""}`;
	out.textContent = message;
}

/** @param {any[]} keys */
function activeKeys(keys) {
	return (Array.isArray(keys) ? keys : []).filter((key) => key && !key.revokedAt);
}

/** @param {any} key */
function authorKeyRow(key) {
	const revoked = Boolean(key.revokedAt);
	const statusClass = revoked ? "review-rejected" : "review-approved";
	const status = revoked ? t("developerSettings.keyRevoked", "Revoked") : t("developerSettings.keyActive", "Active");
	return `<tr>
		<td data-label="${t("developerSettings.keyIdColumn", "Key id")}"><code>${esc(key.keyId)}</code></td>
		<td data-label="${t("developerSettings.keyAlgorithm", "Algorithm")}">${esc(key.algorithm || "ed25519")}</td>
		<td data-label="${t("developerSettings.keyFingerprint", "Fingerprint")}"><code>${esc(key.fingerprint || "")}</code></td>
		<td data-label="${t("developerSettings.keyStatus", "Status")}"><span class="sync-badge sync-badge--${statusClass}">${esc(status)}</span></td>
		<td data-label="${t("developerSettings.keyActions", "Actions")}">
			${revoked ? "" : button(t("developerSettings.revokeKey", "Revoke"), { variant: "danger", size: "sm", attrs: `data-author-key-revoke="${esc(key.keyId)}"` })}
		</td>
	</tr>`;
}

/** @param {any[]} keys */
function authorKeysTable(keys) {
	if (!Array.isArray(keys) || keys.length === 0) {
		return `<p class="empty">${t("developerSettings.noAuthorKeys", "No public keys registered yet.")}</p>`;
	}
	return `<div class="account-records__table-wrap">
		<table class="account-records__table account-keys__table">
			<caption class="skip-label">${t("developerSettings.authorKeysCaption", "Registered signed-toolinfo public keys")}</caption>
			<thead><tr>
				<th scope="col">${t("developerSettings.keyIdColumn", "Key id")}</th>
				<th scope="col">${t("developerSettings.keyAlgorithm", "Algorithm")}</th>
				<th scope="col">${t("developerSettings.keyFingerprint", "Fingerprint")}</th>
				<th scope="col">${t("developerSettings.keyStatus", "Status")}</th>
				<th scope="col">${t("developerSettings.keyActions", "Actions")}</th>
			</tr></thead>
			<tbody>${keys.map((key) => authorKeyRow(key)).join("")}</tbody>
		</table>
	</div>`;
}

/** @param {any[]} keys */
function authorKeyOptions(keys) {
	const active = activeKeys(keys);
	if (active.length === 0) {
		return `<option value="">${t("developerSettings.noActiveKeys", "No active keys")}</option>`;
	}
	return active.map((key) => `<option value="${esc(key.keyId)}">${esc(key.keyId)}</option>`).join("");
}

/** @param {any[]} keys */
function renderAuthorKeys(keys) {
	const list = $("[data-author-keys-list]");
	const select = /** @type {HTMLSelectElement | null} */ ($("[data-sign-key]"));
	if (list) list.innerHTML = authorKeysTable(keys);
	if (select) {
		select.innerHTML = authorKeyOptions(keys);
		select.disabled = activeKeys(keys).length === 0;
	}
}

export function viewDeveloperSettings() {
	const html = `
	<div class="container page account-data">
		<h1 class="page__title">${t("developerSettings.title", "Developer settings")}</h1>
		<p class="page__intro">${t("developerSettings.intro", "Manage Toolhub developer features connected to this sign-in. OAuth applications and API tokens remain official Toolhub data.")}</p>

		<section class="panel account-data__section" aria-labelledby="developer-toolhub-title">
			<h2 class="panel__title" id="developer-toolhub-title">${t("developerSettings.toolhubTitle", "Official Toolhub developer settings")}</h2>
			<p class="signin-note">${t("developerSettings.toolhubNote", "Toolhub remains the source of truth for OAuth applications, authorized applications, and API tokens. Evolved lists what it can read through the public API and sends sensitive management tasks back to Toolhub.")}</p>
			<div class="toolpage__actions">
				${externalButton(TOOLHUB_DEVELOPER_SETTINGS_URL, t("developerSettings.openToolhub", "Open Toolhub developer settings"))}
				${button(t("developerSettings.reconnect", "Reconnect Toolhub OAuth"), { variant: "outline", href: "/oauth/login" })}
			</div>
		</section>

		<section class="panel account-data__section" aria-labelledby="developer-pages-title">
			<h2 class="panel__title" id="developer-pages-title">${t("developerSettings.pagesTitle", "Developer pages")}</h2>
			<div class="linkgrid account-data__links">
				${linkCard(icon("tools"), t("developerSettings.myTools", "My tools"), t("developerSettings.myToolsDesc", "Review official Toolhub tools and Evolved authorship verification for this account."), "/my-tools", true)}
				${linkCard(icon("code"), t("developerSettings.toolinfoSchema", "API explorer and toolinfo schema"), t("developerSettings.toolinfoSchemaDesc", "Run read-only endpoints, inspect the schema, and copy integration examples."), "/api-docs", true)}
				${linkCard(icon("code"), t("developerSettings.myApps", "My apps"), t("developerSettings.myAppsDesc", "Open OAuth client applications registered on official Toolhub by this account."), officialMyAppsUrl())}
				${linkCard(icon("key"), t("developerSettings.apiToken", "API token"), t("developerSettings.apiTokenDesc", "Create or retrieve your official Toolhub API token on Toolhub."), TOOLHUB_API_TOKEN_URL)}
				${linkCard(icon("check"), t("developerSettings.authorizedApps", "Authorized apps"), t("developerSettings.authorizedAppsDesc", "Review applications you have authorized on official Toolhub."), TOOLHUB_AUTHORIZED_APPS_URL)}
			</div>
		</section>

		<section class="panel account-data__section account-keys" aria-labelledby="developer-signed-toolinfo-title">
			<h2 class="panel__title" id="developer-signed-toolinfo-title">${t("developerSettings.signedToolinfoTitle", "Signed toolinfo authorship")}</h2>
			<p class="signin-note">${t("developerSettings.signedToolinfoNote", "Register Ed25519 public keys for Evolved-only signed toolinfo verification. Private keys stay outside Evolved.")}</p>
			<div class="prose account-keys__schema-note">
				<h3>${t("developerSettings.toolinfoSchemaHeading", "toolinfo.json reference")}</h3>
				<p>${t("developerSettings.toolinfoSchemaBodyBefore", "Toolhub validates crawler input against")} <code>${esc(TOOLINFO_SCHEMA_VERSION)}</code>. ${t("developerSettings.toolinfoSchemaBodyAfter", "Start with the required fields, add _schema for the version marker, then build a signing payload from the exact object you publish.")}</p>
				<pre tabindex="0" aria-label="${t("developerSettings.toolinfoExampleLabel", "Minimal toolinfo JSON example")}"><code>${esc(TOOLINFO_EXAMPLE_JSON)}</code></pre>
				<p><a href="${esc(TOOLINFO_SCHEMA_URL)}" target="_blank" rel="noopener nofollow">${t("developerSettings.openToolinfoSchema", "Open official schema source")} ${icon("external")}</a><br>
				<a href="${esc(TOOLINFO_DATA_MODEL_URL)}" target="_blank" rel="noopener nofollow">${t("developerSettings.openToolinfoFieldReference", "Open Toolhub field reference")} ${icon("external")}</a></p>
			</div>
			<div class="account-keys__layout">
				<form class="account-keys__form" data-author-key-form novalidate>
					${fInput(t("developerSettings.keyId", "Key id"), "author-key-id", "", { req: true, ph: "release-2026", hint: t("developerSettings.keyIdHint", "Stable id used in the toolinfo signature metadata."), max: 128 })}
					${fArea(t("developerSettings.publicKey", "Ed25519 public key"), "author-public-key", "", t("developerSettings.publicKeyHint", "PEM public key or base64 raw 32-byte Ed25519 public key."), { rows: 4, max: false })}
					<div class="account-keys__actions">${button(t("developerSettings.registerKey", "Register key"), { variant: "primary", type: "submit" })}</div>
				</form>
				<div class="account-keys__list" data-author-keys-list>${t("developerSettings.keysLoading", "Loading keys...")}</div>
			</div>
			<form class="account-keys__signer" data-signing-form novalidate>
				<label class="le__label">${t("developerSettings.signingKey", "Signing key")}
					<select class="le__input" id="signature-key" data-sign-key></select>
				</label>
				${fArea(t("developerSettings.toolinfoItem", "Toolinfo item"), "signature-toolinfo", "", t("developerSettings.toolinfoItemHint", "Use the exact toolinfo object the crawler will read."), { rows: 8, max: false })}
				<div class="account-keys__actions">${button(t("developerSettings.buildPayload", "Build payload"), { variant: "outline", type: "submit" })}</div>
			</form>
			<div class="account-keys__payloads" data-signature-output hidden>
				${outputArea(t("developerSettings.canonicalPayload", "Canonical payload"), "signature-canonical", 6)}
				${outputArea(t("developerSettings.canonicalPayloadBase64", "Canonical payload, base64"), "signature-canonical-base64", 2)}
				${outputArea(t("developerSettings.signatureMetadata", "Signature metadata"), "signature-metadata", 5)}
				${outputArea(t("developerSettings.signedToolinfoPreview", "Signed toolinfo preview"), "signature-preview", 8)}
			</div>
			<p class="at__result" data-developer-result aria-live="polite"></p>
		</section>
	</div>`;
	function mount() {
		async function loadKeys() {
			const data = await backendGetJson("/v1/author-keys/");
			if (!data) throw new Error(t("developerSettings.keysUnavailable", "Unable to load public keys."));
			renderAuthorKeys(data.keys || []);
		}
		loadKeys().catch((error) => {
			renderAuthorKeys([]);
			setDeveloperResult(backendErrorMessage(error), "err");
		});
		$("[data-author-key-form]")?.addEventListener("submit", async (event) => {
			event.preventDefault();
			setDeveloperResult(t("developerSettings.registeringKey", "Registering key..."));
			try {
				await serverWrite("POST", "/v1/author-keys/", {
					keyId: $input("#author-key-id")?.value.trim() || "",
					publicKey: textAreaValue("author-public-key")
				});
				/** @type {HTMLFormElement | null} */ ($("[data-author-key-form]"))?.reset();
				await loadKeys();
				setDeveloperResult(t("developerSettings.keyRegistered", "Public key registered."), "ok");
			} catch (error) {
				setDeveloperResult(
					t("developerSettings.keyRegisterFailed", "Key registration failed: {msg}", {
						msg: backendErrorMessage(error)
					}),
					"err"
				);
			}
		});
		$("[data-author-keys-list]")?.addEventListener("click", async (event) => {
			const target =
				event.target instanceof HTMLElement ? event.target.closest("[data-author-key-revoke]") : null;
			const keyId = target?.getAttribute("data-author-key-revoke") || "";
			if (!keyId) return;
			setDeveloperResult(t("developerSettings.revokingKey", "Revoking key..."));
			try {
				await serverWrite("DELETE", `/v1/author-keys/${encodeURIComponent(keyId)}/`);
				await loadKeys();
				setDeveloperResult(t("developerSettings.keyRevokedOk", "Public key revoked."), "ok");
			} catch (error) {
				setDeveloperResult(
					t("developerSettings.keyRevokeFailed", "Key revocation failed: {msg}", {
						msg: backendErrorMessage(error)
					}),
					"err"
				);
			}
		});
		$("[data-signing-form]")?.addEventListener("submit", async (event) => {
			event.preventDefault();
			const keyId = /** @type {HTMLSelectElement | null} */ ($("[data-sign-key]"))?.value || "";
			let toolinfo;
			try {
				toolinfo = JSON.parse(textAreaValue("signature-toolinfo"));
			} catch {
				setDeveloperResult(t("developerSettings.invalidToolinfoJson", "Toolinfo must be valid JSON."), "err");
				return;
			}
			setDeveloperResult(t("developerSettings.buildingPayload", "Building canonical payload..."));
			try {
				const data = await serverWrite("POST", "/v1/toolinfo/signing-payload/", { keyId, toolinfo });
				setTextAreaValue("signature-canonical", data.canonicalPayload || "");
				setTextAreaValue("signature-canonical-base64", data.canonicalPayloadBase64 || "");
				setTextAreaValue("signature-metadata", JSON.stringify(data.signatureMetadata || {}, null, 2));
				setTextAreaValue("signature-preview", JSON.stringify(data.signedToolinfoPreview || {}, null, 2));
				const output = $("[data-signature-output]");
				if (output) output.hidden = false;
				setDeveloperResult(t("developerSettings.payloadReady", "Canonical payload ready."), "ok");
			} catch (error) {
				setDeveloperResult(
					t("developerSettings.payloadFailed", "Payload generation failed: {msg}", {
						msg: backendErrorMessage(error)
					}),
					"err"
				);
			}
		});
	}
	return { title: t("developerSettings.docTitle", "Developer settings - Toolhub"), html, mount };
}
