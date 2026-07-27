// SPDX-License-Identifier: GPL-3.0-or-later
import { $, dirAttrs, esc, safeUrl } from "../lib/core/dom.js";
import { backendErrorMessage, backendGetJson, normalizeTool, paginate } from "../lib/core/api.js";
import { countLabel, t, timeTag } from "../lib/core/i18n.js";
import { toolHref } from "../lib/core/routing.js";
import { USER } from "../lib/core/session.js";
import { serverWrite } from "../lib/core/serversync.js";
import { demoStore } from "../lib/core/store.js";
import { normStr } from "../lib/core/util.js";
import { button } from "../lib/atoms/button.js";
import { icon } from "../lib/atoms/icon.js";
import { linkCard } from "./static.js";

const TOOLHUB_BASE = "https://toolhub.wikimedia.org";
const TOOLHUB_DEVELOPER_SETTINGS_URL = `${TOOLHUB_BASE}/developer-settings`;
const TOOLHUB_API_TOKEN_URL = `${TOOLHUB_BASE}/api/user/authtoken/`;
const TOOLHUB_AUTHORIZED_APPS_URL = `${TOOLHUB_BASE}/api/oauth/authorized/`;
const MY_TOOLS_PAGE_SIZE = 100;
const MY_TOOLS_MAX_PAGES = 20;

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

function officialMyAppsUrl() {
	const username = encodeURIComponent(USER.name || "");
	return username
		? `${TOOLHUB_BASE}/api/oauth/applications/?user__username=${username}`
		: TOOLHUB_DEVELOPER_SETTINGS_URL;
}

/**
 * @param {Tool} tool
 * @param {string} username
 * @returns {boolean}
 */
function isOwnedByUser(tool, username) {
	const needle = normStr(username);
	if (!needle) return false;
	if (normStr(tool.maintainer) === needle) return true;
	if ((tool.authors || []).some((author) => normStr(author) === needle)) return true;
	return (tool.authorObjs || []).some(
		(author) =>
			normStr(author.name) === needle ||
			normStr(author.developerUsername) === needle ||
			normStr(author.wikiUsername) === needle
	);
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
				<th scope="col">${t("accountTools.type", "Type")}</th>
				<th scope="col">${t("accountTools.updated", "Updated")}</th>
				<th scope="col">${t("accountTools.actions", "Actions")}</th>
			</tr></thead>
			<tbody>${tools.map((tool) => toolRow(tool)).join("")}</tbody>
		</table>
	</div>`;
}

async function myTools() {
	const username = USER.name;
	const tools = await paginate(
		"/search/tools/",
		{ author__term: username, ordering: "-score" },
		{ pageSize: MY_TOOLS_PAGE_SIZE, maxPages: MY_TOOLS_MAX_PAGES, map: normalizeTool }
	);
	return tools.filter((tool) => isOwnedByUser(tool, username));
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
				${linkCard(icon("tools"), t("developerSettings.myTools", "My tools"), t("developerSettings.myToolsDesc", "Review official Toolhub tools where this account is listed as author or maintainer."), "/my-tools", true)}
				${linkCard(icon("code"), t("developerSettings.myApps", "My apps"), t("developerSettings.myAppsDesc", "Open OAuth client applications registered on official Toolhub by this account."), officialMyAppsUrl())}
				${linkCard(icon("key"), t("developerSettings.apiToken", "API token"), t("developerSettings.apiTokenDesc", "Create or retrieve your official Toolhub API token on Toolhub."), TOOLHUB_API_TOKEN_URL)}
				${linkCard(icon("check"), t("developerSettings.authorizedApps", "Authorized apps"), t("developerSettings.authorizedAppsDesc", "Review applications you have authorized on official Toolhub."), TOOLHUB_AUTHORIZED_APPS_URL)}
			</div>
		</section>
	</div>`;
	return { title: t("developerSettings.docTitle", "Developer settings - Toolhub"), html };
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
			</div>
			<span class="account-records__source">${t("accountTools.source", "Official Toolhub data")}</span>
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
