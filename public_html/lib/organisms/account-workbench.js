// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { USER } from "../core/session.js";
import { avatar } from "../atoms/avatar.js";
import { icon } from "../atoms/icon.js";
import { tabBar } from "../molecules/tab-bar.js";

export const ACCOUNT_NAV_ITEMS = [
	{
		key: "lists",
		href: "/my-lists",
		iconName: "list",
		label: () => t("account.yourLists", "Your lists")
	},
	{
		key: "tools",
		href: "/my-tools",
		iconName: "tools",
		label: () => t("account.myTools", "My tools")
	},
	{
		key: "favorites",
		href: "/favorites",
		iconName: "star",
		label: () => t("account.favorites", "Favorites")
	},
	{
		key: "developer",
		href: "/developer-settings",
		iconName: "key",
		label: () => t("account.developerSettings", "Developer settings")
	},
	{
		key: "preferences",
		href: "/preferences",
		iconName: "system",
		label: () => t("account.preferences", "Preferences")
	}
];

/**
 * @typedef {object} AccountWorkbenchOptions
 * @property {string} active
 * @property {string} title
 * @property {string} intro
 * @property {string} [introHtml]
 * @property {string} [actions]
 * @property {string} body
 * @property {string} [className]
 */

function accountName() {
	return USER.name || t("accountWorkbench.accountFallback", "Toolhub account");
}

/** @param {string} active */
export function accountWorkbenchNav(active) {
	return tabBar({
		active,
		ariaLabel: t("accountWorkbench.navLabel", "Account pages"),
		classes: {
			nav: "account-workbench__nav",
			item: "account-workbench__nav-item",
			icon: "account-workbench__nav-icon",
			copy: "account-workbench__nav-copy",
			label: "account-workbench__nav-label"
		},
		items: ACCOUNT_NAV_ITEMS.map((item) => ({
			key: item.key,
			href: item.href,
			iconName: item.iconName,
			label: item.label()
		}))
	});
}

/** @param {AccountWorkbenchOptions} opts */
export function accountWorkbenchPage(opts) {
	const actions = opts.actions ? `<div class="account-workbench__actions">${opts.actions}</div>` : "";
	const toolbar = actions ? `\n\t\t<div class="account-workbench__toolbar">${actions}</div>` : "";
	const cls = opts.className ? ` ${opts.className}` : "";
	const user = accountName();
	const intro = opts.introHtml || esc(opts.intro);
	return `<div class="container page account-data account-workbench${cls}">
		<header class="account-workbench__hero">
			<div class="account-workbench__identity">
				${avatar(user, "avatar--lg account-workbench__avatar")}
				<div class="account-workbench__copy">
					<p class="account-workbench__eyebrow">${t("accountWorkbench.eyebrow", "Signed in as")} <span${dirAttrs(user)}>${esc(user)}</span></p>
					<h1 class="page__title">${esc(opts.title)}</h1>
					<p class="page__intro">${intro}</p>
				</div>
			</div>
		</header>
		${accountWorkbenchNav(opts.active)}${toolbar}
		<div class="account-workbench__body">${opts.body}</div>
	</div>`;
}

/**
 * @param {{ iconName: string, title: string, body: string, action?: string }} opts
 * @returns {string}
 */
export function accountEmptyState(opts) {
	return `<div class="account-empty">
		<span class="account-empty__icon" aria-hidden="true">${icon(opts.iconName)}</span>
		<div class="account-empty__copy">
			<h2>${esc(opts.title)}</h2>
			<p>${esc(opts.body)}</p>
			${opts.action ? `<div class="account-empty__actions">${opts.action}</div>` : ""}
		</div>
	</div>`;
}

/**
 * @param {{ id: string, title: string, intro?: string, actions?: string, body: string, className?: string }} opts
 * @returns {string}
 */
export function accountSection(opts) {
	const cls = opts.className ? ` ${opts.className}` : "";
	const actions = opts.actions
		? `
			<div class="account-workbench__section-actions">${opts.actions}</div>`
		: "";
	return `<section class="panel account-data__section account-workbench__section${cls}" aria-labelledby="${esc(opts.id)}">
		<div>
			<div>
				<h2 class="panel__title" id="${esc(opts.id)}">${esc(opts.title)}</h2>
				${opts.intro ? `<p class="signin-note">${esc(opts.intro)}</p>` : ""}
			</div>${actions}
		</div>
		${opts.body}
	</section>`;
}
