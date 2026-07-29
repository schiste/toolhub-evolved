// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { USER } from "../core/session.js";
import { avatar } from "../atoms/avatar.js";
import { icon } from "../atoms/icon.js";

const ACCOUNT_NAV_ITEMS = [
	{
		key: "favorites",
		href: "/favorites",
		iconName: "star",
		label: () => t("accountWorkbench.navFavorites", "Favorites"),
		description: () => t("accountWorkbench.navFavoritesDesc", "Saved tools")
	},
	{
		key: "lists",
		href: "/my-lists",
		iconName: "list",
		label: () => t("accountWorkbench.navLists", "Your lists"),
		description: () => t("accountWorkbench.navListsDesc", "Drafts and collections")
	},
	{
		key: "tools",
		href: "/my-tools",
		iconName: "tools",
		label: () => t("accountWorkbench.navTools", "My tools"),
		description: () => t("accountWorkbench.navToolsDesc", "Authorship and metadata")
	},
	{
		key: "register",
		href: "/add-or-remove-tools",
		iconName: "add",
		label: () => t("accountWorkbench.navRegister", "Register tools"),
		description: () => t("accountWorkbench.navRegisterDesc", "Crawler URLs and submissions")
	},
	{
		key: "developer",
		href: "/developer-settings",
		iconName: "key",
		label: () => t("accountWorkbench.navDeveloper", "Developer"),
		description: () => t("accountWorkbench.navDeveloperDesc", "API and signatures")
	},
	{
		key: "data",
		href: "/account",
		iconName: "reset",
		label: () => t("accountWorkbench.navData", "Data settings"),
		description: () => t("accountWorkbench.navDataDesc", "Export and deletion")
	}
];

/**
 * @typedef {object} AccountMetric
 * @property {string} value
 * @property {string} label
 * @property {string} [detail]
 */

/**
 * @typedef {object} AccountWorkbenchOptions
 * @property {string} active
 * @property {string} title
 * @property {string} intro
 * @property {string} [introHtml]
 * @property {string} [source]
 * @property {string} [actions]
 * @property {AccountMetric[]} [metrics]
 * @property {string} body
 * @property {string} [className]
 */

function accountName() {
	return USER.name || t("accountWorkbench.accountFallback", "Toolhub account");
}

/** @param {string} active */
export function accountWorkbenchNav(active) {
	return `<nav class="account-workbench__nav" aria-label="${esc(t("accountWorkbench.navLabel", "Account pages"))}">
		${ACCOUNT_NAV_ITEMS.map((item) => {
			const current = item.key === active;
			return `<a class="account-workbench__nav-item${current ? " is-active" : ""}" href="${esc(item.href)}"${current ? ' aria-current="page"' : ""}>
				<span class="account-workbench__nav-icon" aria-hidden="true">${icon(item.iconName)}</span>
				<span class="account-workbench__nav-copy">
					<span class="account-workbench__nav-label">${esc(item.label())}</span>
					<span class="account-workbench__nav-desc">${esc(item.description())}</span>
				</span>
			</a>`;
		}).join("")}
	</nav>`;
}

/** @param {AccountMetric[]} metrics */
function accountMetrics(metrics) {
	if (metrics.length === 0) return "";
	return `<dl class="account-metrics">
		${metrics
			.map(
				(metric) => `<div class="account-metrics__item">
					<dt>${esc(metric.label)}</dt>
					<dd>${esc(metric.value)}</dd>
					${metric.detail ? `<span>${esc(metric.detail)}</span>` : ""}
				</div>`
			)
			.join("")}
	</dl>`;
}

/** @param {AccountWorkbenchOptions} opts */
export function accountWorkbenchPage(opts) {
	const source = opts.source ? `<span class="account-workbench__source">${esc(opts.source)}</span>` : "";
	const actions = opts.actions ? `<div class="account-workbench__actions">${opts.actions}</div>` : "";
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
			${source || actions ? `<div class="account-workbench__hero-side">${source}${actions}</div>` : ""}
		</header>
		${accountMetrics(opts.metrics || [])}
		${accountWorkbenchNav(opts.active)}
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
		<div class="account-workbench__section-head">
			<div>
				<h2 class="panel__title" id="${esc(opts.id)}">${esc(opts.title)}</h2>
				${opts.intro ? `<p class="signin-note">${esc(opts.intro)}</p>` : ""}
			</div>${actions}
		</div>
		${opts.body}
	</section>`;
}
