// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { backendGetJson } from "../lib/core/api.js";
import { t } from "../lib/core/i18n.js";
import { releaseNotesHTML } from "../lib/molecules/release-notes.js";

/* Split out of organisms.css; the router preloads it alongside this module. */
const STYLESHEET = "/styles/changelog.css";

/** @param {string | undefined} value */
function dateLabel(value) {
	const date = new Date(value || "");
	return Number.isNaN(date.getTime())
		? t("changelog.unknownDate", "Date unavailable")
		: new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

export async function viewChangelog() {
	const data = await backendGetJson("/data/deployments.json");
	const deployments = Array.isArray(data?.deployments) ? data.deployments : [];
	const rows = deployments
		.map((/** @type {any} */ deployment) => {
			const title = deployment.title || t("changelog.releaseFallback", "Product update");
			const buildId = deployment.sha?.slice(0, 12) || t("changelog.unknownBuild", "unavailable");
			const build = deployment.sha
				? `<a href="https://github.com/schiste/toolhub-evolved/commit/${encodeURIComponent(deployment.sha)}" target="_blank" rel="noopener nofollow">${esc(buildId)}</a>`
				: `<span>${esc(buildId)}</span>`;
			const userNotes = releaseNotesHTML(deployment.marketing?.user, "changelog__notes");
			return `<section class="changelog__release">
				<header class="changelog__release-head"><div><h2>${esc(title)}</h2>
				<p>${esc(t("changelog.released", "Released $1", dateLabel(deployment.releasedAt || deployment.deployedAt)))}</p></div>
				<span class="changelog__commit">${esc(t("changelog.servingBuild", "Serving build"))} ${build}</span></header>
				${userNotes ? `<div class="changelog__audience"><h3>${esc(t("changelog.forUsers", "For users"))}</h3>${userNotes}</div>` : ""}
				${deployment.marketing?.technical ? `<details class="changelog__technical"><summary class="changelog__technical-summary">${esc(t("changelog.technicalDetails", "Technical details"))}</summary>${releaseNotesHTML(deployment.marketing.technical, "changelog__notes")}</details>` : ""}
			</section>`;
		})
		.join("");
	return {
		title: t("changelog.title", "Changelog"),
		html: `<div class="container page"><article class="prose prose--page changelog">
		<h1>${esc(t("changelog.title", "Changelog"))}</h1>
		<p>${esc(t("changelog.intro", "Product changes are grouped into curated releases. Maintenance deployments update the serving build without creating another version."))}</p>
		${rows || `<p class="empty">${esc(t("changelog.empty", "No changelog entries are available yet."))}</p>`}
	</article></div>`,
		styles: [STYLESHEET]
	};
}
