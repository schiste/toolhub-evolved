// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { t } from "../lib/core/i18n.js";

export const COMMUNITY_PEOPLE = "people";
export const COMMUNITY_ACCOUNTS = "accounts";
export const COMMUNITY_CONTRIBUTORS = "contributors";
const COMMUNITY_VIEWS = new Set([COMMUNITY_PEOPLE, COMMUNITY_ACCOUNTS, COMMUNITY_CONTRIBUTORS]);

/** @param {URLSearchParams} [params] */
export function communityView(params = new URLSearchParams(globalThis.location?.search || "")) {
	const requested = String(params.get("view") || COMMUNITY_PEOPLE);
	return COMMUNITY_VIEWS.has(requested) ? requested : COMMUNITY_PEOPLE;
}

/** @param {string} view */
export function communityRootHref(view) {
	return view === COMMUNITY_PEOPLE ? "/people" : `/people?view=${encodeURIComponent(view)}`;
}

/** @param {string} active */
export function communityHeader(active) {
	const definitions = [
		[
			COMMUNITY_PEOPLE,
			t("community.people", "People"),
			t(
				"community.peopleDefinition",
				"Public identities backed by stable evidence and connected to a tool relationship or public profile."
			)
		],
		[
			COMMUNITY_ACCOUNTS,
			t("community.accounts", "Accounts"),
			t(
				"community.accountsDefinition",
				"Accounts registered with official Toolhub. Registration alone does not demonstrate catalog contribution."
			)
		],
		[
			COMMUNITY_CONTRIBUTORS,
			t("community.contributors", "Contributors"),
			t(
				"community.contributorsDefinition",
				"People with observed canonical Toolhub catalog activity or approved public contributions."
			)
		]
	];
	return `<header class="community-directory__header">
		<h1 class="page__title">${t("community.title", "Community directory")}</h1>
		<p class="page__intro">${t("community.intro", "Explore public identities, official accounts, and evidence-backed catalog contributors without treating them as the same thing.")}</p>
		<dl class="community-directory__definitions">${definitions
			.map(([view, label, description]) => `<div><dt>${esc(label)}</dt><dd>${esc(description)}</dd></div>`)
			.join("")}</dl>
		<nav class="community-tabs" aria-label="${esc(t("community.views", "Community directory views"))}">${definitions
			.map(
				([view, label]) =>
					`<a class="community-tabs__tab${view === active ? " is-active" : ""}" href="${communityRootHref(view)}"${view === active ? ' aria-current="page"' : ""}>${esc(label)}</a>`
			)
			.join("")}</nav>
	</header>`;
}
