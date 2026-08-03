// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { backendGetJson } from "../lib/core/api.js";
import { t } from "../lib/core/i18n.js";

/** @param {string | undefined} value */
function dateLabel(value) {
	const date = new Date(value || "");
	return Number.isNaN(date.getTime())
		? t("changelog.unknownDate", "Date unavailable")
		: new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

export async function viewChangelog() {
	const data = await backendGetJson("/data/changelog.json");
	const commits = Array.isArray(data?.commits) ? data.commits : [];
	const rows = commits
		.map(
			(commit) => `<li class="changelog__item">
				<div><strong>${esc(commit.summary || commit.subject || t("changelog.unnamed", "Unlabelled change"))}</strong>
				<span>${esc(dateLabel(commit.authoredAt))} · ${esc(commit.author || t("changelog.unknownAuthor", "Unknown author"))}</span></div>
				<a href="https://github.com/schiste/toolhub-evolved/commit/${encodeURIComponent(commit.sha || "")}" target="_blank" rel="noopener nofollow">${esc(commit.shortSha || t("changelog.commit", "commit"))}</a>
			</li>`
		)
		.join("");
	return {
		title: t("changelog.title", "Changelog"),
		html: `<div class="container page"><article class="prose prose--page changelog">
		<h1>${esc(t("changelog.title", "Changelog"))}</h1>
		<p>${esc(t("changelog.intro", "This public changelog is generated from the Git history of the commit serving Toolhub Evolved. Deploy announcements show the two most recent deploys; this page keeps the recent commit trail visible."))}</p>
		${rows ? `<ol class="changelog__list">${rows}</ol>` : `<p class="empty">${esc(t("changelog.empty", "No changelog entries are available yet."))}</p>`}
	</article></div>`
	};
}
