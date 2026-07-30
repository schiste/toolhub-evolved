// SPDX-License-Identifier: GPL-3.0-or-later
import { t } from "./i18n.js";

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
