// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $input, dirAttrs, esc, safeUrl } from "../lib/core/dom.js";
import { backendErrorMessage, backendGetJson, normalizeTool } from "../lib/core/api.js";
import { countLabel, t, timeTag } from "../lib/core/i18n.js";
import { toolHref } from "../lib/core/routing.js";
import { USER } from "../lib/core/session.js";
import { serverWrite } from "../lib/core/serversync.js";
import { demoStore } from "../lib/core/store.js";
import { button } from "../lib/atoms/button.js";
import { fArea, fInput } from "../lib/atoms/form-fields.js";
import { icon } from "../lib/atoms/icon.js";
import { logoutForm } from "../lib/organisms/account.js";
import { linkCard } from "./static.js";

const TOOLHUB_BASE = "https://toolhub.wikimedia.org";
const TOOLHUB_DEVELOPER_SETTINGS_URL = `${TOOLHUB_BASE}/developer-settings`;
const TOOLHUB_API_TOKEN_URL = `${TOOLHUB_BASE}/api/user/authtoken/`;
const TOOLHUB_AUTHORIZED_APPS_URL = `${TOOLHUB_BASE}/api/oauth/authorized/`;
const AUTHOR_CLAIM_TOOLFORGE_MAINTAINER = "toolforge_maintainer";
const AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS = "toolhub_write_access";
const AUTHOR_CLAIM_SIGNED_TOOLINFO = "signed_toolinfo";
const AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME = "author_display_name";

function exportTextarea(value = "") {
	return `<textarea class="le__input account-data__export" data-export-json rows="12" aria-label="${t("accountData.exportJson", "Evolved data export JSON")}" readonly>${esc(value)}</textarea>`;
}

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

/** @param {any} claim */
function authorClaimBadge(claim) {
	const method = claim?.verificationMethod || "";
	if (claim?.isVerified && method === AUTHOR_CLAIM_TOOLFORGE_MAINTAINER) {
		return {
			label: t("accountTools.verifiedToolforgeMaintainer", "Verified: Toolforge maintainer"),
			className: "review-approved"
		};
	}
	if (claim?.isVerified && method === AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS) {
		return {
			label: t("accountTools.verifiedToolhubWriteAccess", "Verified: Toolhub write access"),
			className: "review-approved"
		};
	}
	if (claim?.isVerified && method === AUTHOR_CLAIM_SIGNED_TOOLINFO) {
		return {
			label: t("accountTools.verifiedSignedToolinfo", "Verified: signed toolinfo"),
			className: "review-approved"
		};
	}
	if (method === AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME) {
		return {
			label: t("accountTools.unverifiedAuthorName", "Unverified author name"),
			className: "review-pending"
		};
	}
	return null;
}

/**
 * @param {any[]} claims
 * @param {boolean} verified
 */
function authorClaimBadges(claims, verified) {
	const badges = [];
	const seen = new Set();
	for (const claim of Array.isArray(claims) ? claims : []) {
		const badge = authorClaimBadge(claim);
		if (!badge || seen.has(badge.label)) continue;
		badges.push(badge);
		seen.add(badge.label);
	}
	if (badges.length > 0) return badges;
	return [
		verified
			? { label: t("accountTools.verified", "Verified"), className: "review-approved" }
			: { label: t("accountTools.unverifiedAuthorName", "Unverified author name"), className: "review-pending" }
	];
}

/** @param {any[]} items @param {boolean} verified */
function resolvedTools(items, verified) {
	return (Array.isArray(items) ? items : [])
		.map((item) => {
			if (!item || !item.tool) return null;
			const tool = normalizeTool(item.tool);
			tool.authorVerified = verified;
			tool.authorVerificationBadges = authorClaimBadges(item.claims, verified);
			return tool;
		})
		.filter(Boolean);
}

/** @param {Tool} tool */
function toolVerificationBadges(tool) {
	const badges = Array.isArray(tool.authorVerificationBadges)
		? tool.authorVerificationBadges
		: [
				{
					label:
						tool.authorVerificationLabel ||
						t("accountTools.unverifiedAuthorName", "Unverified author name"),
					className: tool.authorVerified ? "review-approved" : "review-pending"
				}
			];
	return `<div class="account-tools__badges">${badges
		.map((badge) => `<span class="sync-badge sync-badge--${esc(badge.className)}">${esc(badge.label)}</span>`)
		.join("")}</div>`;
}

/** @param {Tool} tool */
function toolRow(tool) {
	const hasType = Boolean(tool.toolType);
	const type = tool.toolType || t("accountTools.noType", "No type");
	const when =
		timeTag(tool.modified) || `<span class="recent-table__muted">${t("accountTools.notUpdated", "Unknown")}</span>`;
	const toolUrl = safeUrl(tool.url);
	return `<tr>
		<td data-label="${t("accountTools.tool", "Tool")}">
			<a class="account-records__title" href="${toolHref(tool.name)}">
				<strong${dirAttrs(tool.title)}>${esc(tool.title)}</strong>
				<span class="recent-table__id">${esc(tool.name)}</span>
			</a>
		</td>
		<td data-label="${t("accountTools.owner", "Owner")}"><span${dirAttrs(tool.maintainer)}>${esc(tool.maintainer)}</span></td>
		<td data-label="${t("accountTools.verification", "Verification")}">${toolVerificationBadges(tool)}</td>
		<td data-label="${t("accountTools.type", "Type")}">${hasType ? esc(type) : `<span class="recent-table__muted">${esc(type)}</span>`}</td>
		<td data-label="${t("accountTools.updated", "Updated")}">${when}</td>
		<td data-label="${t("accountTools.actions", "Actions")}">
			<div class="account-records__actions">
				<a href="${toolHref(tool.name)}">${t("accountTools.view", "View")}</a>
				${toolUrl ? `<a href="${toolUrl}" target="_blank" rel="noopener nofollow">${t("accountTools.open", "Open")}</a>` : ""}
			</div>
		</td>
	</tr>`;
}

/** @param {Tool[]} tools */
function toolsTable(tools) {
	if (tools.length === 0) {
		return `<p class="empty">${t("accountTools.empty", "No Toolhub tools list this account as an author or maintainer.")}</p>`;
	}
	return `<div class="account-records__table-wrap">
		<table class="account-records__table">
			<caption class="skip-label">${t("accountTools.tableCaption", "My tools")}</caption>
			<thead><tr>
				<th scope="col">${t("accountTools.tool", "Tool")}</th>
				<th scope="col">${t("accountTools.owner", "Owner")}</th>
				<th scope="col">${t("accountTools.verification", "Verification")}</th>
				<th scope="col">${t("accountTools.type", "Type")}</th>
				<th scope="col">${t("accountTools.updated", "Updated")}</th>
				<th scope="col">${t("accountTools.actions", "Actions")}</th>
			</tr></thead>
			<tbody>${tools.map((tool) => toolRow(tool)).join("")}</tbody>
		</table>
	</div>`;
}

async function myTools() {
	const data = await backendGetJson("/v1/me/tools/");
	if (!data) throw new Error("resolver unavailable");
	return [...resolvedTools(data.verified, true), ...resolvedTools(data.possible, false)];
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
				${linkCard(icon("code"), t("developerSettings.myApps", "My apps"), t("developerSettings.myAppsDesc", "Open OAuth client applications registered on official Toolhub by this account."), officialMyAppsUrl())}
				${linkCard(icon("key"), t("developerSettings.apiToken", "API token"), t("developerSettings.apiTokenDesc", "Create or retrieve your official Toolhub API token on Toolhub."), TOOLHUB_API_TOKEN_URL)}
				${linkCard(icon("check"), t("developerSettings.authorizedApps", "Authorized apps"), t("developerSettings.authorizedAppsDesc", "Review applications you have authorized on official Toolhub."), TOOLHUB_AUTHORIZED_APPS_URL)}
			</div>
		</section>

		<section class="panel account-data__section account-keys" aria-labelledby="developer-signed-toolinfo-title">
			<h2 class="panel__title" id="developer-signed-toolinfo-title">${t("developerSettings.signedToolinfoTitle", "Signed toolinfo authorship")}</h2>
			<p class="signin-note">${t("developerSettings.signedToolinfoNote", "Register Ed25519 public keys for Evolved-only signed toolinfo verification. Private keys stay outside Evolved.")}</p>
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

export async function viewMyTools() {
	let tools = [];
	let error = null;
	try {
		tools = await myTools();
	} catch (e) {
		error = e;
	}
	const count = countLabel(tools.length, t("accountTools.toolOne", "tool"), t("accountTools.toolOther", "tools"));
	const content = error
		? `<p class="empty">${t("accountTools.loadFailed", "Unable to load your Toolhub tools right now.")}</p>`
		: toolsTable(tools);
	const html = `
	<div class="container page account-data account-records account-tools">
		<a class="back" href="/developer-settings">${t("accountTools.back", "← Developer settings")}</a>
		<div class="section-head account-records__head">
			<div>
				<h1 class="page__title">${t("accountTools.title", "My tools")}</h1>
				<p class="page__intro">${t("accountTools.intro", "Official Toolhub tools where {username} is listed as author or maintainer.", { username: esc(USER.name) })}</p>
				<p class="signin-note">${t("accountTools.verificationPolicy", "Verification is per tool: a verified author claim on one tool does not verify the same author name everywhere.")}</p>
			</div>
			<span class="account-records__source">${t("accountTools.source", "Official Toolhub data + Evolved verification")}</span>
		</div>
		<div class="account-records__summary">
			<strong>${esc(count)}</strong>
			${externalButton(TOOLHUB_DEVELOPER_SETTINGS_URL, t("accountTools.manageOnToolhub", "Manage on Toolhub"))}
		</div>
		${content}
	</div>`;
	return { title: t("accountTools.docTitle", "My tools - Toolhub"), html };
}

export function viewAccountSettings() {
	const html = `
	<div class="container page account-data">
		<h1 class="page__title">${t("accountData.title", "Evolved data settings")}</h1>
		<p class="page__intro">${t("accountData.intro", "Export or delete the local Evolved data attached to this Toolhub sign-in. Official Toolhub records, lists, favorites, and crawler registrations are not deleted here.")}</p>

		<section class="panel account-data__section" aria-labelledby="account-export-title">
			<h2 class="panel__title" id="account-export-title">${t("accountData.exportTitle", "Export Evolved data")}</h2>
			<div class="le__actions">${button(t("accountData.exportButton", "Generate export"), { variant: "outline", attrs: "data-export" })}</div>
			<div data-export-box>${exportTextarea()}</div>
		</section>

		<section class="panel account-data__section" aria-labelledby="account-delete-title">
			<h2 class="panel__title" id="account-delete-title">${t("accountData.deleteTitle", "Delete Evolved-local data")}</h2>
			<p class="signin-note">${t("accountData.deleteNote", "This removes local drafts, fallbacks, overlays, local favorites cache, crawler URLs, and local activity rows stored by Toolhub Evolved.")}</p>
			<div class="le__actions">${button(t("accountData.deleteButton", "Delete Evolved-local data"), { variant: "danger", attrs: "data-delete-evolved" })}</div>
		</section>

		<section class="panel account-data__section" aria-labelledby="account-oauth-title">
			<h2 class="panel__title" id="account-oauth-title">${t("accountData.oauthTitle", "Toolhub connection")}</h2>
			<div class="toolpage__actions">
				${button(t("accountData.reconnect", "Reconnect Toolhub OAuth"), { variant: "outline", href: "/oauth/login" })}
				${logoutForm(button(t("accountData.logout", "Log out"), { variant: "outline", type: "submit" }))}
			</div>
		</section>
		<p class="at__result" data-account-result aria-live="polite"></p>
	</div>`;
	function mount() {
		const out = /** @type {HTMLElement} */ ($("[data-account-result]"));
		$("[data-export]")?.addEventListener("click", async () => {
			out.className = "at__result";
			out.textContent = t("accountData.exporting", "Generating export...");
			try {
				const data = await backendGetJson("/v1/user/export/");
				/** @type {HTMLElement} */ ($("[data-export-box]")).innerHTML = exportTextarea(
					JSON.stringify(data, null, 2)
				);
				out.className = "at__result at__result--ok";
				out.textContent = t("accountData.exportReady", "Export generated.");
			} catch (error) {
				out.className = "at__result at__result--err";
				out.textContent = t("accountData.exportFailed", "Export failed: {msg}", {
					msg: backendErrorMessage(error)
				});
			}
		});
		$("[data-delete-evolved]")?.addEventListener("click", async () => {
			// eslint-disable-next-line no-alert -- destructive local-data deletion requires explicit user confirmation.
			if (!window.confirm(t("accountData.confirmDelete", "Delete Evolved-local data for this account?"))) return;
			out.className = "at__result";
			out.textContent = t("accountData.deleting", "Deleting Evolved-local data...");
			try {
				const data = await serverWrite("DELETE", "/v1/user/evolved-data/");
				demoStore.clearAll();
				out.className = "at__result at__result--ok";
				out.textContent = t("accountData.deleted", "Deleted Evolved-local data: {count} rows.", {
					count: String(Object.values(data?.deleted || {}).reduce((sum, n) => sum + Number(n || 0), 0))
				});
			} catch (error) {
				out.className = "at__result at__result--err";
				out.textContent = t("accountData.deleteFailed", "Delete failed: {msg}", {
					msg: backendErrorMessage(error)
				});
			}
		});
	}
	return { title: t("accountData.docTitle", "Evolved data settings - Toolhub"), html, mount };
}
