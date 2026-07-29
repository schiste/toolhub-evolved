// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, safeHttpUrl, textAttrs } from "../lib/core/dom.js";
import { backendGetJson, normalizeTool } from "../lib/core/api.js";
import { countLabel, relativeTime, t, timeTag } from "../lib/core/i18n.js";
import { toolHref } from "../lib/core/routing.js";
import { USER } from "../lib/core/session.js";
import { invalidUrlNotice } from "../lib/atoms/labels.js";
import { accountEmptyState, accountWorkbenchPage } from "../lib/organisms/account-workbench.js";
import { toolRegistrationWorkspace } from "./toolforms.js";

const AUTHOR_CLAIM_TOOLFORGE_MAINTAINER = "toolforge_maintainer";
const AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS = "toolhub_write_access";
const AUTHOR_CLAIM_SIGNED_TOOLINFO = "signed_toolinfo";
const AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME = "author_display_name";

/** @param {any} claim */
function authorClaimBadge(claim) {
	const method = claim?.verificationMethod || "";
	const isVerified = Boolean(claim?.isVerified || claim?.verificationStatus === "verified");
	if (isVerified && method === AUTHOR_CLAIM_TOOLFORGE_MAINTAINER) {
		return {
			label: t("accountTools.verifiedToolforgeMaintainer", "Verified: Toolforge maintainer"),
			className: "review-approved"
		};
	}
	if (isVerified && method === AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS) {
		return {
			label: t("accountTools.verifiedToolhubWriteAccess", "Verified: Toolhub write access"),
			className: "review-approved"
		};
	}
	if (isVerified && method === AUTHOR_CLAIM_SIGNED_TOOLINFO) {
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
 * @returns {AuthorVerificationBadge}
 */
function strongestAuthorClaimBadge(claims, verified) {
	for (const claim of Array.isArray(claims) ? claims : []) {
		const badge = authorClaimBadge(claim);
		if (badge?.className === "review-approved") return badge;
	}
	if (verified) return { label: t("accountTools.verified", "Verified"), className: "review-approved" };
	for (const claim of Array.isArray(claims) ? claims : []) {
		const badge = authorClaimBadge(claim);
		if (badge) return badge;
	}
	return { label: t("accountTools.unverifiedAuthorName", "Unverified author name"), className: "review-pending" };
}

/** @param {any[]} items @param {boolean} verified @param {Record<string, ToolinfoSource>} [sourcesByTool] */
function resolvedTools(items, verified, sourcesByTool = {}) {
	return (Array.isArray(items) ? items : [])
		.map((item) => {
			if (!item || !item.tool) return null;
			const tool = normalizeTool(item.tool);
			tool.authorVerified = verified;
			tool.authorVerificationBadges = [strongestAuthorClaimBadge(item.claims, verified)];
			tool.toolinfoDiscovery = item.toolinfoDiscovery || { status: "pending" };
			tool.toolinfoSource = item.toolinfoSource || sourcesByTool[tool.name];
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

/** @param {ToolinfoDiscovery | undefined} discovery */
function toolinfoDiscoveryCell(discovery) {
	const status = discovery?.status || "pending";
	if (status === "found" && discovery?.toolinfoUrl) {
		const method =
			discovery.method === "sitemap"
				? t("accountTools.toolinfoFoundSitemap", "Found in sitemap")
				: t("accountTools.toolinfoFoundRoot", "Found at root");
		const url = safeHttpUrl(discovery.toolinfoUrl);
		return `<div class="account-tools__toolinfo">
			<span class="sync-badge sync-badge--review-approved">${esc(method)}</span>
			${url ? `<a href="${url}" target="_blank" rel="noopener nofollow">${esc(discovery.toolinfoUrl)}</a>` : invalidUrlNotice(t("accountTools.toolinfoUrlLabel", "toolinfo.json URL"), discovery.toolinfoUrl)}
		</div>`;
	}
	if (status === "not_found") {
		return `<div class="account-tools__toolinfo">
			<span class="sync-badge sync-badge--sync-error">${t("accountTools.toolinfoNotFound", "toolinfo.json not found")}</span>
			${discovery?.checkedAt ? `<span class="recent-table__muted">${timeTag(discovery.checkedAt)}</span>` : ""}
		</div>`;
	}
	if (status === "error") {
		const error = discovery?.lastError || t("accountTools.toolinfoCheckFailed", "Check failed");
		return `<div class="account-tools__toolinfo">
				<span class="sync-badge sync-badge--sync-error">${t("accountTools.toolinfoCheckFailed", "Check failed")}</span>
				<span class="recent-table__muted">${esc(error)}</span>
			</div>`;
	}
	if (status === "no_url") {
		return `<div class="account-tools__toolinfo">
				<span class="sync-badge sync-badge--review-pending">${t("accountTools.toolinfoNoUrl", "No homepage URL")}</span>
				${discovery?.lastError ? `<span class="recent-table__muted">${esc(discovery.lastError)}</span>` : ""}
			</div>`;
	}
	return `<div class="account-tools__toolinfo">
			<span class="sync-badge sync-badge--review-pending">${t("accountTools.toolinfoPending", "Queued for discovery")}</span>
		</div>`;
}

/** @param {ToolinfoDiscovery | undefined} discovery @param {{ hideFailures?: boolean }} [options] */
function selfHostedDiscoveryLine(discovery, options = {}) {
	const status = discovery?.status || "pending";
	if (status === "found" && discovery?.toolinfoUrl) {
		const method =
			discovery.method === "sitemap"
				? t("accountTools.selfHostedFoundSitemap", "Self-hosted check: found in sitemap")
				: t("accountTools.selfHostedFoundRoot", "Self-hosted check: found at root");
		return `<span class="recent-table__muted">${esc(method)}</span>`;
	}
	if (options.hideFailures) return "";
	if (status === "not_found") {
		return `<span class="recent-table__muted">${t("accountTools.selfHostedNotFound", "Self-hosted check: toolinfo.json not found")}</span>`;
	}
	if (status === "error") {
		return `<span class="recent-table__muted">${esc(discovery?.lastError || t("accountTools.selfHostedFailed", "Self-hosted check failed"))}</span>`;
	}
	if (status === "no_url") {
		return `<span class="recent-table__muted">${t("accountTools.selfHostedNoUrl", "Self-hosted check: no homepage URL")}</span>`;
	}
	return `<span class="recent-table__muted">${t("accountTools.selfHostedPending", "Self-hosted check queued")}</span>`;
}

/** @param {ToolinfoSource | undefined} source @param {ToolinfoDiscovery | undefined} discovery */
function toolinfoEvidenceCell(source, discovery) {
	if (!source?.sourceUrl) return toolinfoDiscoveryCell(discovery);
	const fetchedTime = relativeTime(source.lastFetchedAt);
	const fetched = fetchedTime ? t("accountTools.sourceFetched", "fetched {time}", { time: fetchedTime }) : "";
	const count =
		typeof source.itemCount === "number" && source.itemCount > 0
			? countLabel(
					source.itemCount,
					t("accountTools.sourceToolOne", "tool"),
					t("accountTools.sourceToolOther", "tools")
				)
			: "";
	const sourceLabel = source.sourceLabel || t("accountTools.sourceUnknown", "Official crawler feed");
	const sourceDetails = [source.sourceKind || "official", count, fetched].filter(Boolean).join(" · ");
	const tooltip = t("accountTools.sourceTooltip", "{label}: {details}", {
		label: sourceLabel,
		details: sourceDetails || t("accountTools.sourceOfficial", "official")
	});
	return `<div class="account-tools__toolinfo">
		<span class="sync-badge sync-badge--official account-tools__source-badge" title="${esc(tooltip)}" aria-label="${esc(tooltip)}">${t("accountTools.officialCrawlerSource", "Official crawler source")}</span>
		${selfHostedDiscoveryLine(discovery, { hideFailures: true })}
	</div>`;
}

/** @param {Tool} tool */
function toolRow(tool) {
	const hasType = Boolean(tool.toolType);
	const type = tool.toolType || t("accountTools.noType", "No type");
	const when =
		timeTag(tool.modified) || `<span class="recent-table__muted">${t("accountTools.notUpdated", "Unknown")}</span>`;
	const toolUrl = safeHttpUrl(tool.url);
	return `<tr>
		<td data-label="${t("accountTools.tool", "Tool")}">
			<a class="account-records__title" href="${toolHref(tool.name)}">
				<strong${textAttrs(tool.title, tool.titleLanguage)}>${esc(tool.title)}</strong>
				<span class="recent-table__id">${esc(tool.name)}</span>
			</a>
		</td>
		<td data-label="${t("accountTools.owner", "Owner")}"><span${dirAttrs(tool.maintainer)}>${esc(tool.maintainer)}</span></td>
		<td data-label="${t("accountTools.verification", "Verification")}">${toolVerificationBadges(tool)}</td>
		<td data-label="${t("accountTools.metadataSource", "Metadata source")}">${toolinfoEvidenceCell(tool.toolinfoSource, tool.toolinfoDiscovery)}</td>
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
function toolsTable(tools, actions = "") {
	if (tools.length === 0) {
		return accountEmptyState({
			iconName: "tools",
			title: t("accountTools.emptyTitle", "No maintained tools found"),
			body: t("accountTools.empty", "No Toolhub tools list this account as an author or maintainer."),
			action: actions
		});
	}
	return `<div class="account-records__table-wrap">
		<table class="account-records__table">
			<caption class="skip-label">${t("accountTools.tableCaption", "My tools")}</caption>
			<colgroup>
				<col class="account-records__col--tool" />
				<col class="account-records__col--owner" />
				<col class="account-records__col--verification" />
				<col class="account-records__col--source" />
				<col class="account-records__col--type" />
				<col class="account-records__col--updated" />
				<col class="account-records__col--actions" />
			</colgroup>
			<thead><tr>
				<th scope="col">${t("accountTools.tool", "Tool")}</th>
				<th scope="col">${t("accountTools.owner", "Owner")}</th>
				<th scope="col">${t("accountTools.verification", "Verification")}</th>
				<th scope="col">${t("accountTools.metadataSource", "Metadata source")}</th>
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
	const sourcesByTool = data.toolinfoSources && typeof data.toolinfoSources === "object" ? data.toolinfoSources : {};
	const tools = /** @type {Tool[]} */ ([]);
	const seen = new Set();
	for (const tool of resolvedTools(data.verified, true, sourcesByTool)) {
		tools.push(tool);
		seen.add(tool.name);
	}
	for (const tool of resolvedTools(data.possible, false, sourcesByTool)) {
		if (seen.has(tool.name)) continue;
		tools.push(tool);
	}
	return tools;
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
	const registration = toolRegistrationWorkspace();
	const content = error
		? accountEmptyState({
				iconName: "tools",
				title: t("accountTools.loadFailedTitle", "Tools could not be loaded"),
				body: t("accountTools.loadFailed", "Unable to load your Toolhub tools right now.")
			})
		: toolsTable(tools);
	const html = accountWorkbenchPage({
		active: "tools",
		title: t("accountTools.title", "My tools"),
		intro: t(
			"accountTools.intro",
			"Review Toolhub tools where {username} is listed as author or maintainer, register toolinfo sources, and manage local submissions.",
			{
				username: USER.name
			}
		),
		className: "account-records account-tools at",
		body: `${content}${registration.html}`
	});
	return { title: t("accountTools.docTitle", "My tools - Toolhub"), html, mount: registration.mount };
}
