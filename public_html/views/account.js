// SPDX-License-Identifier: GPL-3.0-or-later
import { $, dirAttrs, esc, safeUrl } from "../lib/core/dom.js";
import { backendErrorMessage, backendGetJson, paginate } from "../lib/core/api.js";
import { countLabel, t } from "../lib/core/i18n.js";
import { USER } from "../lib/core/session.js";
import { serverWrite } from "../lib/core/serversync.js";
import { demoStore } from "../lib/core/store.js";
import { button } from "../lib/atoms/button.js";
import { icon } from "../lib/atoms/icon.js";
import { linkCard } from "./static.js";

const TOOLHUB_BASE = "https://toolhub.wikimedia.org";
const TOOLHUB_DEVELOPER_SETTINGS_URL = `${TOOLHUB_BASE}/developer-settings`;
const TOOLHUB_API_TOKEN_URL = `${TOOLHUB_BASE}/api/user/authtoken/`;
const TOOLHUB_AUTHORIZED_APPS_URL = `${TOOLHUB_BASE}/api/oauth/authorized/`;
const MY_APPS_PAGE_SIZE = 100;
const MY_APPS_MAX_PAGES = 20;

function exportTextarea(value = "") {
	return `<textarea class="le__input account-data__export" data-export-json rows="12" aria-label="${t("accountData.exportJson", "Evolved data export JSON")}" readonly>${esc(value)}</textarea>`;
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

/** @param {unknown} raw */
function normalizeApp(raw) {
	const app = raw && typeof raw === "object" ? /** @type {Record<string, any>} */ (raw) : {};
	const user = app.user && typeof app.user === "object" ? app.user : {};
	return {
		name: String(app.name || ""),
		redirectUrl: String(app.redirect_url || ""),
		clientId: String(app.client_id || ""),
		username: String(user.username || "")
	};
}

/** @param {ReturnType<typeof normalizeApp>} app */
function appRow(app) {
	const redirect = safeUrl(app.redirectUrl);
	return `<tr>
		<td data-label="${t("accountApps.name", "Name")}"><strong${dirAttrs(app.name)}>${esc(app.name || t("accountApps.unnamed", "Unnamed app"))}</strong></td>
		<td data-label="${t("accountApps.callback", "Callback URL")}">${
			redirect
				? `<a href="${redirect}" target="_blank" rel="noopener nofollow"${dirAttrs(app.redirectUrl)}>${esc(app.redirectUrl)}</a>`
				: `<span class="recent-table__muted">${t("accountApps.noCallback", "No callback URL")}</span>`
		}</td>
		<td data-label="${t("accountApps.clientId", "Client ID")}"><code>${esc(app.clientId)}</code></td>
	</tr>`;
}

/** @param {ReturnType<typeof normalizeApp>[]} apps */
function appsTable(apps) {
	if (apps.length === 0) {
		return `<p class="empty">${t("accountApps.empty", "No Toolhub OAuth applications are registered for this account.")}</p>`;
	}
	return `<div class="account-apps__table-wrap">
		<table class="account-apps__table">
			<caption class="skip-label">${t("accountApps.tableCaption", "My OAuth applications")}</caption>
			<thead><tr>
				<th scope="col">${t("accountApps.name", "Name")}</th>
				<th scope="col">${t("accountApps.callback", "Callback URL")}</th>
				<th scope="col">${t("accountApps.clientId", "Client ID")}</th>
			</tr></thead>
			<tbody>${apps.map((app) => appRow(app)).join("")}</tbody>
		</table>
	</div>`;
}

async function myApps() {
	const username = USER.name;
	const apps = await paginate(
		"/oauth/applications/",
		{ user__username: username, ordering: "name" },
		{ pageSize: MY_APPS_PAGE_SIZE, maxPages: MY_APPS_MAX_PAGES, map: normalizeApp }
	);
	return apps.filter((app) => app.username === username);
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
				${linkCard(icon("code"), t("developerSettings.myApps", "My apps"), t("developerSettings.myAppsDesc", "List OAuth client applications registered on Toolhub by this account."), "/my-apps", true)}
				${linkCard(icon("key"), t("developerSettings.apiToken", "API token"), t("developerSettings.apiTokenDesc", "Create or retrieve your official Toolhub API token on Toolhub."), TOOLHUB_API_TOKEN_URL)}
				${linkCard(icon("check"), t("developerSettings.authorizedApps", "Authorized apps"), t("developerSettings.authorizedAppsDesc", "Review applications you have authorized on official Toolhub."), TOOLHUB_AUTHORIZED_APPS_URL)}
			</div>
		</section>
	</div>`;
	return { title: t("developerSettings.docTitle", "Developer settings - Toolhub"), html };
}

export async function viewMyApps() {
	let apps = [];
	let error = null;
	try {
		apps = await myApps();
	} catch (e) {
		error = e;
	}
	const count = countLabel(apps.length, t("accountApps.appOne", "app"), t("accountApps.appOther", "apps"));
	const content = error
		? `<p class="empty">${t("accountApps.loadFailed", "Unable to load your Toolhub OAuth applications right now.")}</p>`
		: appsTable(apps);
	const html = `
	<div class="container page account-data account-apps">
		<a class="back" href="/developer-settings">${t("accountApps.back", "← Developer settings")}</a>
		<div class="section-head account-apps__head">
			<div>
				<h1 class="page__title">${t("accountApps.title", "My apps")}</h1>
				<p class="page__intro">${t("accountApps.intro", "OAuth client applications registered on official Toolhub by {username}.", { username: esc(USER.name) })}</p>
			</div>
			<span class="account-apps__source">${t("accountApps.source", "Official Toolhub data")}</span>
		</div>
		<div class="account-apps__summary">
			<strong>${esc(count)}</strong>
			${externalButton(TOOLHUB_DEVELOPER_SETTINGS_URL, t("accountApps.manageOnToolhub", "Manage on Toolhub"))}
		</div>
		${content}
	</div>`;
	return { title: t("accountApps.docTitle", "My apps - Toolhub"), html };
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
				${button(t("accountData.logout", "Log out"), { variant: "outline", href: "/oauth/logout" })}
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
