// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc } from "../core/dom.js";
import { countLabel, t } from "../core/i18n.js";
import { listHref } from "../core/routing.js";
import { syncStatusLabel } from "../core/store.js";
import { avatar } from "../atoms/avatar.js";

/** @param {ToolList} l */
export function listCardData(l) {
	return {
		id: l.id,
		title: l.title || t("listCard.untitledList", "Untitled list"),
		description: l.description || "",
		toolCount: (l.tools || []).length,
		local: true,
		syncStatus: l.syncStatus || "local_draft",
		syncLabel: l.syncLabel || syncStatusLabel(l.syncStatus)
	};
}
/**
 * @param {{ id: string; title: string; description: string; toolCount: number; local?: boolean; syncStatus?: string; syncLabel?: string }} l
 * @returns {string}
 */
export function listCard(l) {
	const count = countLabel(l.toolCount, t("listCard.toolOne", "tool"), t("listCard.toolOther", "tools"));
	const status = l.local ? l.syncLabel || syncStatusLabel(l.syncStatus) : "";
	return `
	<a class="lcard" href="${listHref(l.id)}" aria-label="${t("listCard.linkLabel", "{title} list, {count}", { title: esc(l.title), count: esc(count) })}">
		${avatar(l.title)}
		<div class="lcard__body">
			<div class="lcard__title"${dirAttrs(l.title)}>${esc(l.title)} <span class="lcard__count">${esc(count)}</span>${status ? ` <span class="exp-badge">${esc(status)}</span>` : ""}</div>
			<div class="lcard__desc"${dirAttrs(l.description)}>${esc(l.description)}</div>
		</div>
	</a>`;
}
