// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc } from "../core/dom.js";
import { fmt, t } from "../core/i18n.js";
import { listHref } from "../core/routing.js";
import { SYNC_STATUS } from "../core/store.js";
import { avatar } from "../atoms/avatar.js";
import { syncBadge } from "../molecules/sync-status.js";

/** @param {ToolList} l */
export function listCardData(l) {
	/** @type {{ id: string, title: string, description: string, toolCount: number, local: boolean, syncStatus: string, lastError?: string, reviewStatus?: string, validationErrors?: unknown[] }} */
	const out = {
		id: l.id,
		title: l.title || t("listCard.untitledList", "Untitled list"),
		description: l.description || "",
		toolCount: (l.tools || []).length,
		local: true,
		syncStatus: l.syncStatus || SYNC_STATUS.localDraft
	};
	if (l.lastError) out.lastError = l.lastError;
	if (l.reviewStatus) out.reviewStatus = l.reviewStatus;
	if (l.validationErrors) out.validationErrors = l.validationErrors;
	return out;
}
/**
 * @param {{ id: string; title: string; description: string; toolCount: number; local?: boolean; syncStatus?: string; lastError?: string; reviewStatus?: string; validationErrors?: any[] }} l
 * @returns {string}
 */
export function listCard(l) {
	const count = t("listCard.toolCount", "$1 {{PLURAL:$2|tool|tools}}", fmt(l.toolCount), l.toolCount);
	const status = l.local ? syncBadge(l) : "";
	return `
	<a class="lcard" href="${listHref(l.id)}" aria-label="${t("listCard.linkLabel", "$1 list, $2", esc(l.title), esc(count))}">
		${avatar(l.title)}
		<div class="lcard__body">
			<div class="lcard__title"${dirAttrs(l.title)}>${esc(l.title)} <span class="lcard__count">${esc(count)}</span>${status ? ` ${status}` : ""}</div>
			<div class="lcard__desc"${dirAttrs(l.description)}>${esc(l.description)}</div>
		</div>
	</a>`;
}
