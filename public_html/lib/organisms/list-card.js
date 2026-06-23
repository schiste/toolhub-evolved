// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc } from "../core/dom.js";
import { countLabel } from "../core/i18n.js";
import { listHref } from "../core/routing.js";
import { avatar } from "../atoms/avatar.js";

export function listCardData(l) { return { id: l.id, title: l.title || "Untitled list", description: l.description || "", toolCount: (l.tools || []).length, demo: true }; }
export function listCard(l) {
	const count = countLabel(l.toolCount, "tool", "tools");
	return `
	<a class="lcard" href="${listHref(l.id)}" aria-label="${esc(l.title)} list, ${esc(count)}">
		${avatar(l.title)}
		<div class="lcard__body">
			<div class="lcard__title"${dirAttrs(l.title)}>${esc(l.title)} <span class="lcard__count">${esc(count)}</span>${l.demo ? ' <span class="exp-badge">Demo</span>' : ""}</div>
			<div class="lcard__desc"${dirAttrs(l.description)}>${esc(l.description)}</div>
		</div>
	</a>`;
}
