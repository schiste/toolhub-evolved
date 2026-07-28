// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, safeUrl, textAttrs } from "../lib/core/dom.js";
import { backendGetJson, normalizeTool } from "../lib/core/api.js";
import { countLabel, t, timeTag } from "../lib/core/i18n.js";
import { toolHref } from "../lib/core/routing.js";
import { USER } from "../lib/core/session.js";
import { button } from "../lib/atoms/button.js";

const TOOLHUB_BASE = "https://toolhub.wikimedia.org";
const TOOLHUB_DEVELOPER_SETTINGS_URL = `${TOOLHUB_BASE}/developer-settings`;
const AUTHOR_CLAIM_TOOLFORGE_MAINTAINER = "toolforge_maintainer";
const AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS = "toolhub_write_access";
const AUTHOR_CLAIM_SIGNED_TOOLINFO = "signed_toolinfo";
const AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME = "author_display_name";

/** @param {string} href @param {string} label */
function externalButton(href, label) {
	return button(label, {
		variant: "outline",
		href,
		icon: "external",
		attrs: 'target="_blank" rel="noopener nofollow"'
	});
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
 * @returns {AuthorVerificationBadge[]}
 */
function authorClaimBadges(claims, verified) {
	const badges = /** @type {AuthorVerificationBadge[]} */ ([]);
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
		.filter((tool) => tool !== null);
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
				<strong${textAttrs(tool.title, tool.titleLanguage)}>${esc(tool.title)}</strong>
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

export async function viewMyTools() {
	/** @type {Tool[]} */
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
