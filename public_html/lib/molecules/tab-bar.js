// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";
import { icon } from "../atoms/icon.js";

/**
 * @typedef {object} TabBarItem
 * @property {string} key
 * @property {string} href
 * @property {string} iconName
 * @property {string} label
 */

/**
 * @typedef {object} TabBarClasses
 * @property {string} [nav]
 * @property {string} [item]
 * @property {string} [icon]
 * @property {string} [copy]
 * @property {string} [label]
 */

/**
 * Route-backed tab navigation. These are links, so `aria-current` is the right
 * accessibility state instead of widget `role="tab"` semantics.
 *
 * @param {{ ariaLabel: string, active: string, items: TabBarItem[], classes?: TabBarClasses }} opts
 * @returns {string}
 */
export function tabBar(opts) {
	const classes = opts.classes || {};
	/** @param {(string | false | null | undefined)[]} parts */
	const className = (parts) => esc(parts.filter(Boolean).join(" "));
	return `<nav class="${className(["tab-bar", classes.nav])}" aria-label="${esc(opts.ariaLabel)}">
		${opts.items
			.map((item) => {
				const current = item.key === opts.active;
				return `<a class="${className(["tab-bar__item", classes.item, current && "is-active"])}" href="${esc(item.href)}"${current ? ' aria-current="page"' : ""}>
				<span class="${className(["tab-bar__icon", classes.icon])}" aria-hidden="true">${icon(item.iconName)}</span>
				<span class="${className(["tab-bar__copy", classes.copy])}">
					<span class="${className(["tab-bar__label", classes.label])}">${esc(item.label)}</span>
				</span>
			</a>`;
			})
			.join("")}
	</nav>`;
}
