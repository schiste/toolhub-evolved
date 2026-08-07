// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { publicActivityRows } from "../lib/core/activity-privacy.js";
import { t, timeTag } from "../lib/core/i18n.js";
import { apiGet } from "../lib/core/api.js";
import { listHref, toolHref } from "../lib/core/routing.js";
import { DEMO_KEYS, demoFeed } from "../lib/core/store.js";
import { icon } from "../lib/atoms/icon.js";

// Audit logs — live from /api/auditlogs/.
/**
 * @param {{ id?: string, type?: string } | null | undefined} target
 * @returns {string | null}
 */
export function targetHref(target) {
	if (!target || !target.id) return null;
	if (target.type === "tool") return toolHref(target.id);
	if (target.type === "list") return listHref(target.id);
	return null;
}
export async function viewAudit() {
	// Stryker disable next-line ObjectLiteral: the catch shape is unobservable — the only read is `data.results || []`, which coerces a missing `results` to the same [] as the {results:[]} fallback.
	const data = await apiGet("/auditlogs/", { page_size: "25" }).catch(() => ({ results: [] }));
	const merged = publicActivityRows(demoFeed(DEMO_KEYS.auditlogs, publicActivityRows(data.results || [])));
	const rows = merged
		.map((a) => {
			const who = esc((a.user && a.user.username) || t("parity.systemCap", "System"));
			const tgt = a.target ? t("parity.auditTarget", "$1 “$2”", esc(a.target.type), esc(a.target.label)) : "";
			const inner = `${icon("edit", "feed__ic")}
			<span class="feed__main"><span dir="auto">${who}</span> <em>${esc(a.action || t("parity.changed", "changed"))}</em> <span dir="auto">${tgt}</span></span>
			${timeTag(a.timestamp, "feed__when")}`;
			const href = targetHref(a.target);
			return href
				? `<li><a href="${href}">${inner}</a></li>`
				: `<li><div class="feed__static">${inner}</div></li>`;
		})
		.join("");
	return {
		title: t("parity.auditLogsDocTitle", "Audit logs — Toolhub"),
		html: `
		<div class="container page">
			<h1 class="page__title">${t("parity.auditLogs", "Audit logs")}</h1>
			<p class="page__intro">${t("parity.auditIntro", "A record of changes across the catalog, for patrollers and administrators.")}</p>
			<ul class="feed">${rows || `<li><div class="feed__static">${t("parity.noAuditEntries", "No audit entries.")}</div></li>`}</ul>
		</div>`
	};
}
