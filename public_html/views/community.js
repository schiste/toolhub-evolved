// SPDX-License-Identifier: GPL-3.0-or-later
import { t } from "../lib/core/i18n.js";

export function communityHeader() {
	return `<header class="community-directory__header">
		<h1 class="page__title">${t("community.title", "Community directory")}</h1>
		<p class="page__intro">${t("community.unifiedIntro", "Search people, usernames, and tools in one place. Official accounts and stable identifiers strengthen identity results; name-only tool metadata remains clearly unresolved.")}</p>
	</header>`;
}
