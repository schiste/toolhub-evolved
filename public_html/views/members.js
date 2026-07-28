// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc } from "../lib/core/dom.js";
import { countLabel, t, timeTag } from "../lib/core/i18n.js";
import { apiGet } from "../lib/core/api.js";
import { avatar } from "../lib/atoms/avatar.js";

// Members — live from /api/users/.
export async function viewMembers() {
	// Stryker disable next-line ObjectLiteral: the catch shape is unobservable — the only reads are `data.results || []` and `data.count || 0`, which coerce missing fields to the same [] / 0 as the explicit fallback object.
	const data = await apiGet("/users/", { page_size: "60" }).catch(() => ({ results: [], count: 0 }));
	const cards = (data.results || [])
		.map((/** @type {{ username: string, groups?: string[], date_joined?: string }} */ u) => {
			const meta = u.groups && u.groups.length > 0 ? esc(u.groups.join(", ")) : t("parity.member", "Member");
			return `<div class="mcard">${avatar(u.username)}<div class="mcard__b">
			<div class="mcard__n"${dirAttrs(u.username)}>${esc(u.username)}</div>
			<div class="mcard__c">${meta} · ${t("parity.joined", "joined")} ${timeTag(u.date_joined)}</div></div></div>`;
		})
		.join("");
	return {
		title: t("parity.membersDocTitle", "Members — Toolhub"),
		html: `
		<div class="container page">
			<h1 class="page__title">${t("parity.members", "Members")}</h1>
			<p class="page__intro">${t("parity.membersCount", "{count} contribute to the catalog.", { count: esc(countLabel(data.count || 0, t("parity.registeredWikimedianOne", "registered Wikimedian"), t("parity.registeredWikimedianOther", "registered Wikimedians"))) })}</p>
			<div class="mgrid">${cards}</div>
		</div>`
	};
}
