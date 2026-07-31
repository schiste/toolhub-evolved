// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, safeHttpUrl, safeUrl, textAttrs } from "../lib/core/dom.js";
import { relativeTime, t, timeTag } from "../lib/core/i18n.js";
import {
	INDEX,
	apiGet,
	backendErrorMessage,
	backendGetJson,
	clearApiCache,
	getTool,
	isNewTool
} from "../lib/core/api.js";
import { renderMarkdown } from "../lib/core/markdown.js";
import { officialWrite, officialWriteAvailable, serverWrite } from "../lib/core/serversync.js";
import { attachEvolvedSummaries, completeness, endorsementOf, listMemberships } from "../lib/core/signals.js";
import { signedIn } from "../lib/core/session.js";
import { clearLocalToolDraft, demoRevisionsFor } from "../lib/core/store.js";
import { authorProfileUrl } from "../lib/core/author-index.js";
import { authorHref, navigateTo, toolHref } from "../lib/core/routing.js";
import { avatar, toolIcon } from "../lib/atoms/avatar.js";
import { completenessList, completenessMeter, endorsementChip, fitChip, statusBadge } from "../lib/atoms/badges.js";
import { button } from "../lib/atoms/button.js";
import { icon } from "../lib/atoms/icon.js";
import { glanceChips, keywordTags, langLabel, linkOut, metaItem, wikiLabel } from "../lib/atoms/labels.js";
import { favBtn } from "../lib/molecules/favbtn.js";
import { saveToListControl } from "../lib/molecules/savemenu.js";
import { fieldProvenance, syncStatusPanel } from "../lib/molecules/sync-status.js";
import { healthScoreChip, maintainerDisclosure } from "../lib/molecules/tool-health-summary.js";
import { prosePage, viewNotFound } from "./static.js";

const QUICK_VIEW_BUTTON_STYLE =
	"appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;";

/** @typedef {{ name: string, profile: { url?: string | null, wikiUsername?: string | null } }} AuthorEntry */

/** @param {{ tool: Tool, shared?: string[] }} item */
function relatedToolRow(item) {
	const tool = item.tool;
	// Stryker disable next-line ArrayDeclaration: nearestNeighbors() always provides a `shared` array; the `|| []` fallback is never taken — equivalent.
	const chips = (item.shared || []).map((label) => `<span class="tag">${esc(label)}</span>`).join("");
	const deprecated = tool.deprecated
		? `<span class="related__status status status--red"><span class="dot dot--red"></span>${t("tool.deprecated", "Deprecated")}</span>`
		: "";
	return `
		<article class="related__item" data-tool="${esc(tool.name)}">
			${avatar(tool.title)}
			<div class="related__body">
				<div class="related__titleline">
					<button class="related__title" type="button" data-tool="${esc(tool.name)}" aria-label="${t("tool.quickLookAria", "Quick look: {title}", { title: esc(tool.title) })}" style="${QUICK_VIEW_BUTTON_STYLE}"${textAttrs(tool.title, tool.titleLanguage)}>${esc(tool.title)}</button>
					${deprecated}
				</div>
				<div class="related__maint">${t("tool.by", "by")} <span${dirAttrs(tool.maintainer)}>${esc(tool.maintainer)}</span></div>
				${chips ? `<div class="related__chips">${chips}</div>` : ""}
			</div>
	</article>`;
}

/**
 * @param {Array<{ tool: Tool, shared?: string[] }>} related
 */
function relatedToolsSection(related) {
	return related.length > 0
		? `<section class="related" aria-labelledby="related-title">
			<div class="section-head"><h2 id="related-title">${t("tool.relatedTitle", "Related tools")}</h2></div>
			<p class="related__subtitle">${t("tool.relatedSubtitle", "Overlapping function and scope, by shared metadata.")}</p>
			<div class="related__list">${related.map((item) => relatedToolRow(item)).join("")}</div>
		</section>`
		: "";
}

/** @param {any | null} ego */
function neighborhoodSection(ego) {
	return ego
		? `<section class="neighborhood" aria-labelledby="neighborhood-title">
			<div class="section-head"><h2 id="neighborhood-title">${t("tool.neighborhoodTitle", "Neighborhood")}</h2></div>
			<div class="graph graph--ego"><div id="ego-canvas"></div></div>
			<p class="graph__caption">${t("tool.neighborhoodCaption", "This tool and its nearest neighbors by metadata. Click a node to peek.")}</p>
		</section>`
		: "";
}

/**
 * @param {() => void} task
 * @param {number} [delayMs]
 */
function afterDetailPrimaryPaint(task, delayMs = 0) {
	const runTask = () => {
		if (delayMs > 0) setTimeout(task, delayMs);
		else task();
	};
	const scheduleIdle = () => {
		if ("requestIdleCallback" in window) {
			/** @type {any} */ (window).requestIdleCallback(runTask, { timeout: 1500 + delayMs });
		} else {
			setTimeout(runTask, 600);
		}
	};
	if (typeof window.requestAnimationFrame === "function") {
		window.requestAnimationFrame(() => setTimeout(scheduleIdle, 0));
	} else {
		scheduleIdle();
	}
}

/**
 * @param {string | null | undefined} iso
 * @param {string} label
 * @param {string} title
 * @param {string} iconName
 */
function freshnessSignal(iso, label, title, iconName) {
	if (!iso) return "";
	const date = new Date(iso);
	const rel = relativeTime(iso);
	if (Number.isNaN(date.getTime()) || !rel) return "";
	return `<span class="signal toolpage__freshness">${icon(iconName)}
		<time class="toolpage__when" datetime="${esc(date.toISOString())}" title="${esc(title)}" aria-label="${esc(title)}">${esc(label)}</time>
	</span>`;
}

/** @param {Tool} tool */
function catalogUpdatedSignal(tool) {
	const rel = relativeTime(tool.modified);
	if (!rel) return "";
	const date = new Date(tool.modified || "");
	const iso = Number.isNaN(date.getTime()) ? "" : date.toISOString();
	return freshnessSignal(
		tool.modified,
		t("tool.toolhubListingUpdated", "Toolhub listing updated {rel}", { rel }),
		t("tool.toolhubListingUpdatedTooltip", "Toolhub catalog listing last modified: {date}", {
			date: iso || String(tool.modified || "")
		}),
		"history"
	);
}

/** @param {any} evolvedSummary */
function repositoryUpdatedSignal(evolvedSummary) {
	const repository = evolvedSummary?.health?.sourceHealth?.repository;
	if (!repository || typeof repository !== "object") return "";
	const lastCommitAt = String(repository.lastCommitAt || "").trim();
	const commitSha = String(repository.commitSha || "").trim();
	const rel = relativeTime(lastCommitAt);
	const date = new Date(lastCommitAt);
	if (!rel || Number.isNaN(date.getTime())) return "";
	const tooltipLines = [
		commitSha
			? t("tool.repositoryLastCommit", "Last known repository commit: {commit}", { commit: commitSha })
			: t("tool.repositoryLastCommitUnknown", "Last known repository commit id unavailable."),
		repository.branch ? t("tool.repositoryBranch", "Branch: {branch}", { branch: String(repository.branch) }) : "",
		t("tool.repositoryUpdatedAt", "Repository updated at: {date}", { date: date.toISOString() })
	].filter(Boolean);
	return freshnessSignal(
		lastCommitAt,
		t("tool.repositoryUpdated", "Repository updated {rel}", { rel }),
		tooltipLines.join("\n"),
		"code"
	);
}

/** @param {string} name */
function viewToolNotFound(name) {
	const rawName = String(name ?? "");
	const searchHref = `/search?q=${encodeURIComponent(rawName)}`;
	return {
		title: t("tool.notFoundDocTitle", "Tool not found — Toolhub"),
		html: `
		<div class="container page">
			<a class="back" href="/search">${t("tool.backToTools", "← Back to tools")}</a>
			<h1 class="page__title">${t("tool.notFoundTitle", "Tool not found")}</h1>
			<p class="page__intro">${t("tool.notFoundIntroLead", "The record for")} <code${dirAttrs(rawName)}>${esc(rawName)}</code> ${t("tool.notFoundIntroMid", "may have been")} <strong>${t("tool.notFoundIntroFates", "deleted, renamed, or never registered")}</strong>.</p>
			<p><a href="${searchHref}">${t("tool.searchForName", 'Search for "{name}"', { name: esc(rawName) })}</a> · <a href="/search">${t("tool.browseAllTools", "Browse all tools")}</a></p>
		</div>`
	};
}

/**
 * @param {Tool} t
 * @returns {AuthorEntry[]}
 */
function authorEntries(t) {
	const names = (t.authors && t.authors.length > 0 ? t.authors : [t.maintainer]).filter(Boolean);
	/** @type {Array<{ name?: string, url?: string | null, wikiUsername?: string | null }>} */
	// Stryker disable next-line ArrayDeclaration: normalizeTool always provides an `authorObjs` array; the `|| []` fallback is never taken — equivalent.
	const records = t.authorObjs || [];
	return names.map((name, i) => {
		const byIndex = records[i];
		const found = byIndex && byIndex.name === name ? byIndex : records.find((a) => a && a.name === name);
		// Stryker disable next-line ObjectLiteral: only `record.url`/`record.wikiUsername` are read below (both undefined here), so `{ name }` and `{}` are indistinguishable — equivalent.
		const record = found || /** @type {{ name: string, url?: string | null, wikiUsername?: string }} */ ({ name });
		return { name, profile: { url: record.url, wikiUsername: record.wikiUsername } };
	});
}

/** @param {AuthorEntry} entry */
function authorExternalLink(entry) {
	const url = safeUrl(authorProfileUrl(entry.profile));
	if (!url) return "";
	return `<a class="author-ref__external" href="${url}" target="_blank" rel="noopener nofollow" aria-label="${t("tool.externalProfileAria", "External profile for {name}", { name: esc(entry.name) })}">${icon("external")}</a>`;
}

/** @param {AuthorEntry} entry */
function authorLink(entry) {
	return `<span class="author-ref"><a href="${esc(authorHref(entry.name))}"${dirAttrs(entry.name)}>${esc(entry.name)}</a>${authorExternalLink(entry)}</span>`;
}

/** @param {Tool} t */
function authorInlineList(t) {
	return authorEntries(t)
		.map((entry) => authorLink(entry))
		.join('<span class="toolpage__sep">, </span>');
}

/** @param {any} evolvedSummary */
function maintainerPeople(evolvedSummary) {
	const people = evolvedSummary?.maintainer?.people;
	if (!Array.isArray(people)) return null;
	return people
		.filter(
			(person) =>
				Array.isArray(person.relationships) &&
				person.relationships.some((relationship) => relationship.type === "maintainer")
		)
		.map((person) => ({
			name: person.displayName || t("tool.unknownMaintainer", "Unknown"),
			profile: { wikiUsername: person.identifiers?.find((item) => item.namespace === "wiki")?.value }
		}));
}

/** @param {Tool} tool @param {any} evolvedSummary */
function maintainerListMarkup(tool, evolvedSummary) {
	const entries = maintainerPeople(evolvedSummary) || authorEntries(tool);
	const list = entries
		.map((entry) => `<li>${avatar(entry.name)}<span class="maint-list__name">${authorLink(entry)}</span></li>`)
		.join("");
	return (
		list ||
		`<li class="maint-list__empty">${t("tool.noMaintainerRelationship", "No maintainer relationship has been verified for this tool yet.")}</li>`
	);
}

/** @param {string | null} qid */
function wikidataChip(qid) {
	const id = String(qid || "").trim();
	if (!id) return "";
	const url = safeUrl(`https://www.wikidata.org/wiki/${encodeURIComponent(id)}`);
	return `<a class="glance toolpage__wikidata" href="${url}" target="_blank" rel="noopener nofollow">${t("tool.wikidataLabel", "Wikidata:")} <span dir="auto">${esc(id)}</span>${icon("external")}</a>`;
}

/** @param {string | { name?: string, url?: string } | null | undefined} entry */
function sponsorEntry(entry) {
	let name = "";
	// Stryker disable next-line StringLiteral: `url` is only ever read through safeUrl(); a non-http(s) sentinel is rejected to "" just like the empty default — equivalent.
	let url = "";
	if (typeof entry === "string") {
		name = entry;
	} else if (entry) {
		name = entry.name || entry.url || "";
		// Stryker disable next-line StringLiteral: safeUrl() rejects any non-http(s) sentinel to "", so the empty fallback is indistinguishable — equivalent.
		url = entry.url || "";
	}
	if (!name) return "";
	const body = esc(name);
	const href = safeUrl(url);
	return href
		? `<a href="${href}" target="_blank" rel="noopener nofollow"${dirAttrs(name)}>${body}</a>`
		: `<span${dirAttrs(name)}>${body}</span>`;
}

/** @param {string[] | string | null | undefined} sponsor */
function sponsorLine(sponsor) {
	const entries = Array.isArray(sponsor) ? sponsor : sponsor ? [sponsor] : [];
	const html = entries
		.map((entry) => sponsorEntry(entry))
		.filter(Boolean)
		.join(", ");
	return html
		? `<div class="toolpage__sponsor"><span class="toolpage__label">${t("tool.sponsorLabel", "Sponsor:")}</span> ${html}</div>`
		: "";
}

/** @param {Tool} tool */
function replacementNote(tool) {
	if (!tool.deprecated || !tool.replacedBy) return "";
	const value = /** @type {string | { name?: string, title?: string } | null} */ (tool.replacedBy);
	const name = typeof value === "string" ? value : (value && (value.name || value.title)) || "";
	if (!name) return "";
	const label = esc(name);
	const linked = /^https?:\/\//i.test(name)
		? `<a href="${safeUrl(name)}" target="_blank" rel="noopener nofollow">${label}</a>`
		: `<a href="${esc(toolHref(name))}"${dirAttrs(name)}>${label}</a>`;
	return `<div class="toolpage__notice">${t("tool.replacedBy", "Replaced by")} ${linked}</div>`;
}

/** @param {Record<string, any> | null} signals */
function evolvedSignalsPanel(signals) {
	const thanks = signals?.thanks || {};
	const usage = signals?.usage30d || {};
	const health = signals?.health || {};
	const thanksCount = Number(thanks.count || 0);
	const usageCount = Number(usage.count || 0);
	const healthStatus = health.status && health.status !== "unknown" ? String(health.status) : "";
	if (!signedIn() && !thanksCount && !usageCount && !healthStatus) return "";
	return `<div class="panel" data-evolved-signals>
		<h2 class="panel__title">${t("tool.evolvedSignals", "Evolved signals")}</h2>
		<div class="toolpage__signal-list">
			${thanksCount ? `<span class="signal">${t("tool.thanksCount", "{count} thanks on Evolved", { count: String(thanksCount) })}</span>` : ""}
			${usageCount ? `<span class="signal">${t("tool.usageCount", "{count} Evolved interactions in 30 days", { count: String(usageCount) })}</span>` : ""}
			${healthStatus ? `<span class="signal">${t("tool.healthStatus", "Evolved health: {status}", { status: esc(healthStatus) })}</span>` : ""}
		</div>
		${
			signedIn()
				? button(
						thanks.userThanked ? t("tool.thanked", "Thanks sent") : t("tool.thankTool", "Thank this tool"),
						{
							variant: "outline",
							attrs: `data-thanks${thanks.userThanked ? ' data-thanked="1"' : ""}`
						}
					)
				: ""
		}
		<p class="at__result" data-signals-result aria-live="polite"></p>
	</div>`;
}

/** @param {Array<Record<string, any>>} media */
function mediaPanel(media) {
	const approved = media
		.map((item) => {
			const url = safeUrl(item.url);
			if (!url) return "";
			const title = item.title || t("tool.screenshot", "Screenshot");
			const license = item.license ? ` · ${esc(item.license)}` : "";
			const label = item.syncLabel || t("tool.evolvedDataLabel", "Evolved data");
			return `<figure class="tool-media__item"><img src="${url}" alt="${esc(title)}" loading="lazy" /><figcaption>${esc(title)}${license} · ${esc(label)}</figcaption></figure>`;
		})
		.filter(Boolean)
		.join("");
	const submit = signedIn()
		? `<form class="tool-media__form" data-media-form>
			<input class="le__input" data-media-url type="url" placeholder="${t("tool.mediaUrl", "Screenshot URL")}" aria-label="${t("tool.mediaUrl", "Screenshot URL")}" />
			<input class="le__input" data-media-license placeholder="${t("tool.mediaLicense", "License")}" aria-label="${t("tool.mediaLicense", "License")}" />
			<input class="le__input" data-media-source placeholder="${t("tool.mediaSource", "Source")}" aria-label="${t("tool.mediaSource", "Source")}" />
			${button(t("tool.submitMedia", "Submit screenshot"), { variant: "outline", type: "submit" })}
		</form>`
		: "";
	if (!approved && !submit) return "";
	return `<div class="panel tool-media">
		<h2 class="panel__title">${t("tool.screenshotsTitle", "Screenshots · Evolved data")}</h2>
		${approved ? `<div class="tool-media__grid">${approved}</div>` : ""}
		${submit}
		<p class="at__result" data-media-result aria-live="polite"></p>
	</div>`;
}

/**
 * @param {Tool & { edited?: boolean, annotated?: boolean }} tool
 * @param {string} name
 */
function toolSyncUi(tool, name) {
	const coreMeta = {
		syncStatus: tool.syncStatus,
		lastError: tool.lastError,
		validationErrors: tool.validationErrors,
		reviewStatus: tool.reviewStatus
	};
	const editMeta = {
		syncStatus: tool.editSyncStatus,
		lastError: tool.editLastError,
		validationErrors: tool.editValidationErrors,
		reviewStatus: tool.editReviewStatus
	};
	const annotationMeta = {
		syncStatus: tool.annotationSyncStatus,
		lastError: tool.annotationLastError,
		validationErrors: tool.annotationValidationErrors,
		reviewStatus: tool.annotationReviewStatus
	};
	const hasCoreSyncPanel =
		isNewTool(name) || Boolean(tool.lastError || tool.validationErrors?.length || tool.reviewStatus);
	const hasEditSyncPanel =
		Boolean(tool.edited) ||
		Boolean(tool.editLastError || tool.editValidationErrors?.length || tool.editReviewStatus);
	const hasAnnotationSyncPanel =
		Boolean(tool.annotated) ||
		Boolean(tool.annotationLastError || tool.annotationValidationErrors?.length || tool.annotationReviewStatus);
	const provTags = [
		wikidataChip(tool.wikidata),
		...(signedIn()
			? [
					isNewTool(name) ? fieldProvenance(t("tool.coreFields", "Core fields"), coreMeta) : "",
					tool.edited ? fieldProvenance(t("tool.coreFields", "Core fields"), editMeta) : "",
					tool.annotated
						? fieldProvenance(t("tool.communityAnnotations", "Community annotations"), annotationMeta)
						: ""
				]
			: [])
	]
		.filter(Boolean)
		.join(" ");
	const syncPanels = [
		hasCoreSyncPanel
			? syncStatusPanel(coreMeta, { title: t("tool.coreWriteStatus", "Core field write status") })
			: "",
		hasEditSyncPanel
			? syncStatusPanel(editMeta, { title: t("tool.coreWriteStatus", "Core field write status") })
			: "",
		hasAnnotationSyncPanel
			? syncStatusPanel(annotationMeta, { title: t("tool.annotationWriteStatus", "Annotation write status") })
			: ""
	]
		.filter(Boolean)
		.join("");
	return { provTags, syncPanels };
}

/** @param {string} name */
export async function viewTool(name) {
	const tool =
		/** @type {(Tool & { edited?: boolean, annotated?: boolean, endorsement?: { count?: number } }) | null} */ (
			await getTool(name)
		);
	if (!tool) return viewToolNotFound(name);
	const resolvedTool = tool;
	const [evolvedSignals, evolvedMedia] = await Promise.all([
		backendGetJson(`/v1/tools/${encodeURIComponent(name)}/signals/`).catch(() => null),
		backendGetJson(`/v1/tools/${encodeURIComponent(name)}/media/`).catch(() => null)
	]);
	await attachEvolvedSummaries([tool], { waitForFresh: true });
	const evolvedSummary = /** @type {{ evolvedSummary?: any }} */ (tool).evolvedSummary;
	const mediaRows = Array.isArray(evolvedMedia?.results) ? evolvedMedia.results : [];
	const { provTags, syncPanels } = toolSyncUi(tool, name);
	const tags = keywordTags(tool, { empty: "—" });
	const authors = authorInlineList(tool);
	const openToolUrl = safeHttpUrl(tool.url);

	// REAL links — render only the ones present on the record.
	const actions = [
		linkOut(t("tool.openTool", "Open tool"), tool.url),
		linkOut(t("tool.sourceCode", "Source code"), tool.repository),
		linkOut(t("tool.apiLabel", "API"), tool.apiUrl),
		linkOut(t("tool.userDocs", "User docs"), tool.userDocs),
		linkOut(t("tool.developerDocs", "Developer docs"), tool.devDocs),
		linkOut(t("tool.reportABug", "Report a bug"), tool.bugtracker),
		linkOut(t("tool.giveFeedback", "Give feedback"), tool.feedback),
		linkOut(t("tool.translate", "Translate"), tool.translate)
	].join("");

	// Official Toolhub status flags stay visible alongside Evolved-local panels.
	const realBadge = statusBadge(tool);
	const canDeleteOfficialTool = signedIn() && officialWriteAvailable() && !isNewTool(tool.name);
	const managementLinks = signedIn()
		? [
				`<a href="${toolHref(tool.name)}/edit">${t("tool.editTool", "Edit tool")}</a>`,
				`<a href="${toolHref(tool.name)}/edit-annotations">${t("tool.editAnnotations", "Edit annotations")}</a>`,
				canDeleteOfficialTool
					? button(t("tool.deleteOfficialTool", "Delete official tool"), {
							variant: "danger",
							size: "sm",
							attrs: "data-tool-delete"
						})
					: ""
			]
				.filter(Boolean)
				.join(" ")
		: `<a href="${toolHref(tool.name)}/edit">${t("tool.suggestAnEdit", "Suggest an edit")}</a>`;
	const deleteResult = canDeleteOfficialTool
		? `<p class="at__result" data-tool-delete-result aria-live="polite"></p>`
		: "";
	// At-a-glance chips (real metadata).
	const glance = glanceChips(tool);

	const maintList = maintainerListMarkup(tool, evolvedSummary);
	const complete = completeness(tool);
	// Stryker disable next-line StringLiteral: button() defaults variant to "outline", so "" renders identical markup — equivalent.
	const html = `
	<div class="container page">
		<a class="back" href="/search">${t("tool.backToTools", "← Back to tools")}</a>
		<header class="toolpage__head">
			${toolIcon(tool, "lg")}
			<div class="toolpage__id">
				<h1 class="toolpage__title"${textAttrs(tool.title, tool.titleLanguage)}>${esc(tool.title)}</h1>
				${tool.subtitle ? `<p class="toolpage__subtitle"${textAttrs(tool.subtitle, tool.subtitleLanguage)}>${esc(tool.subtitle)}</p>` : ""}
				<div class="toolpage__by">${t("tool.by", "by")} ${authors}</div>
				${sponsorLine(tool.sponsor)}
				${replacementNote(tool)}
				${provTags ? `<div class="toolpage__prov">${provTags}</div>` : ""}
				${syncPanels}
				<div class="toolpage__glance">${glance}</div>
				<div class="toolpage__row">
					${realBadge}
					${healthScoreChip(evolvedSummary)}
					${maintainerDisclosure(evolvedSummary)}
					<span data-tool-endorsement-slot></span>
					${fitChip(tool)}
					${catalogUpdatedSignal(tool)}
					${repositoryUpdatedSignal(evolvedSummary)}
				</div>
			</div>
			<div class="toolpage__cta">
				${openToolUrl ? button(t("tool.openTool", "Open tool"), { variant: "primary", size: "lg", href: openToolUrl, icon: "external", attrs: 'target="_blank" rel="noopener nofollow"' }) : ""}
				${signedIn() ? favBtn(tool.name, { label: true, cls: "favbtn--btn favbtn--lg" }) : ""}
				<!-- EXPERIMENTAL — Save to a list. Needs: POST/PUT /api/lists/ (Lane B). -->
				${signedIn() ? saveToListControl(tool.name) : ""}
			</div>
		</header>

		<div class="toolpage__grid">
			<div class="toolpage__main">
				<div class="prose"${textAttrs(tool.description, tool.descriptionLanguage)}>${renderMarkdown(tool.description) || `<em>${t("tool.noDescription", "No description provided.")}</em>`}</div>
				<div class="tcard__tags toolpage__tags">${tags}</div>

				<h2 class="toolpage__h2">${t("tool.detailsTitle", "Details")}</h2>
				<div class="detail__meta">
					${metaItem(t("tool.metaType", "Type"), esc(tool.toolType))}
					${metaItem(t("tool.metaLicense", "License"), esc(tool.license))}
					${metaItem(t("tool.metaWorksOn", "Works on"), wikiLabel(tool.forWikis))}
					${metaItem(t("tool.metaInterfaceLanguages", "Interface languages"), langLabel(tool.uiLanguages))}
					${metaItem(t("tool.metaTechnology", "Technology"), (tool.technologyUsed || []).map((/** @type {string} */ item) => esc(item)).join(", "))}
					${metaItem(t("tool.metaAudiences", "Audiences"), (tool.audiences || []).map((/** @type {string} */ item) => esc(item)).join(", "))}
				</div>

				<div data-related-tools-slot></div>
				<div data-neighborhood-slot></div>
			</div>

			<aside class="toolpage__side">
				<div class="panel">
					<h2 class="panel__title">${t("tool.getStarted", "Get started")}</h2>
					<div class="toolpage__actions">${actions || `<span class="meta__v">${t("tool.noLinksProvided", "No links provided")}</span>`}</div>
					<div class="toolpage__sub">
						<a href="${toolHref(tool.name)}/history">${t("tool.viewHistory", "View history")}</a>
						${managementLinks}
					</div>
					${deleteResult}
				</div>
				<div class="panel">
					<h2 class="panel__title">${t("tool.maintainersTitle", "Maintainers")}</h2>
					<ul class="maint-list">${maintList}</ul>
				</div>
				<div class="panel">
					<h2 class="panel__title">${t("tool.listingCompleteness", "Listing completeness")}</h2>
					${completenessMeter(complete)}
					${completenessList(complete)}
				</div>
				${evolvedSignalsPanel(evolvedSignals)}
				${mediaPanel(mediaRows)}
			</aside>
		</div>
	</div>`;
	function mount() {
		const mountedPath = window.location.pathname;
		const stillCurrentTool = () => window.location.pathname === mountedPath;
		if (signedIn()) {
			serverWrite("POST", `/v1/tools/${encodeURIComponent(name)}/events/`, { eventType: "view" }).catch(() => {});
		}
		afterDetailPrimaryPaint(() => {
			Promise.all([
				listMemberships().catch(() => new Map()),
				import("../lib/core/similarity.js")
					.then(({ getSimilarityIndex, nearestNeighbors }) =>
						getSimilarityIndex().then((simIndex) => nearestNeighbors(resolvedTool, simIndex, 6))
					)
					.catch(() => []),
				import("../lib/core/graph.js")
					.then(({ egoGraph }) =>
						egoGraph(name, 10).then((graph) =>
							// Stryker disable next-line ArrayDeclaration: egoGraph always returns a `nodes` array; the `|| []` fallback is never taken, and the sentinel array's length (1) is still < 3 — equivalent.
							(graph.nodes || []).length >= 3 ? graph : null
						)
					)
					.catch(() => null)
			]).then(([membershipMap, related, ego]) => {
				if (!stillCurrentTool()) return;
				const endorsement = endorsementOf(resolvedTool.name, membershipMap);
				/** @type {any} */ (resolvedTool).endorsement = endorsement;
				const endorsementSlot = document.querySelector("[data-tool-endorsement-slot]");
				if (endorsementSlot) endorsementSlot.innerHTML = endorsementChip(endorsement.count);
				const relatedSlot = document.querySelector("[data-related-tools-slot]");
				if (relatedSlot) relatedSlot.innerHTML = relatedToolsSection(related || []);
				const neighborhoodSlot = document.querySelector("[data-neighborhood-slot]");
				if (neighborhoodSlot) neighborhoodSlot.innerHTML = neighborhoodSection(ego);
				const target = /** @type {HTMLElement | null} */ (document.querySelector("#ego-canvas"));
				if (!target || !ego) return;
				Promise.all([import("../lib/organisms/force-graph.js"), import("../lib/organisms/quickview.js")])
					.then(([{ forceGraph }, { openQuickView }]) => {
						if (!stillCurrentTool() || !target.isConnected) return;
						target.forceGraphHandle = forceGraph(target, ego, { onSelect: openQuickView, height: 320 });
					})
					.catch(() => undefined);
			});
		}, 2200);
		document.querySelector("[data-tool-delete]")?.addEventListener("click", async () => {
			const out = /** @type {HTMLElement | null} */ (document.querySelector("[data-tool-delete-result]"));
			if (out) {
				out.className = "at__result";
				out.textContent = t("tool.publishingToToolhub", "Publishing to official Toolhub…");
			}
			try {
				await officialWrite("DELETE", `/v1/write/tools/${encodeURIComponent(name)}/`);
				clearLocalToolDraft(name);
				clearApiCache();
				navigateTo("/my-tools");
			} catch (error) {
				if (out) {
					out.className = "at__result at__result--err";
					out.textContent = t(
						"tool.officialDeleteFailed",
						"Official Toolhub did not delete the tool: {msg}",
						{
							msg: backendErrorMessage(error)
						}
					);
				}
			}
		});
		document.querySelector("[data-thanks]")?.addEventListener("click", async (event) => {
			const btn = /** @type {HTMLElement} */ (event.currentTarget);
			const out = /** @type {HTMLElement | null} */ (document.querySelector("[data-signals-result]"));
			const thanked = btn.getAttribute("data-thanked") === "1";
			try {
				await serverWrite(thanked ? "DELETE" : "POST", `/v1/tools/${encodeURIComponent(name)}/thanks/`);
				btn.setAttribute("data-thanked", thanked ? "0" : "1");
				btn.textContent = thanked ? t("tool.thankTool", "Thank this tool") : t("tool.thanked", "Thanks sent");
				if (out) {
					out.className = "at__result at__result--ok";
					out.textContent = thanked
						? t("tool.thanksRemoved", "Thanks removed.")
						: t("tool.thanksSaved", "Thanks saved.");
				}
			} catch {
				if (out) {
					out.className = "at__result at__result--err";
					out.textContent = t("tool.thanksFailed", "Could not update thanks.");
				}
			}
		});
		document.querySelector("[data-media-form]")?.addEventListener("submit", async (event) => {
			event.preventDefault();
			const form = /** @type {HTMLElement} */ (event.currentTarget);
			/** @param {string} selector */
			const value = (selector) =>
				/** @type {HTMLInputElement | null} */ (form.querySelector(selector))?.value.trim() || "";
			const out = /** @type {HTMLElement | null} */ (document.querySelector("[data-media-result]"));
			try {
				await serverWrite("POST", `/v1/tools/${encodeURIComponent(name)}/media/`, {
					url: value("[data-media-url]"),
					license: value("[data-media-license]"),
					source: value("[data-media-source]")
				});
				if (out) {
					out.className = "at__result at__result--ok";
					out.textContent = t("tool.mediaSubmitted", "Screenshot submitted for review.");
				}
				form.querySelectorAll("input").forEach((input) => {
					/** @type {HTMLInputElement} */ (input).value = "";
				});
			} catch {
				if (out) {
					out.className = "at__result at__result--err";
					out.textContent = t("tool.mediaFailed", "Could not submit screenshot.");
				}
			}
		});
	}
	return { title: t("tool.docTitle", "{title} — Toolhub", { title: tool.title }), html, mount };
}

// Tool revision history — live from /api/tools/{name}/revisions/.
/** @param {string} name */
export async function viewToolHistory(name) {
	const [liveT, data] = await Promise.all([
		getTool(name),
		// Stryker disable next-line ObjectLiteral: `{}` is equivalent to `{ results: [] }` because the value is read as `data.results || []`.
		apiGet(`/tools/${encodeURIComponent(name)}/revisions/`, { page_size: "20" }).catch(() => ({ results: [] }))
	]);
	// Local Evolved edits show as the most recent revisions.
	const revs = [...demoRevisionsFor(name), ...(data.results || [])];
	const tool = liveT;
	if (!tool && revs.length === 0) return viewNotFound();
	const title = tool ? tool.title : (revs[0] && revs[0].content_title) || name;
	const rows = revs
		.map((r, i) => {
			const username = (r.user && r.user.username) || "system";
			return `
		<li>${icon("history", "feed__ic")}
			<span class="feed__main">${t("tool.revisionBy", "Revision by")} <strong${dirAttrs(username)}>${esc(username)}</strong> · ${timeTag(r.timestamp)}${r.comment ? ` — <span dir="auto">${esc(r.comment)}</span>` : ""}${i === 0 ? ` <span class="tag">${t("tool.currentTag", "current")}</span>` : ""}</span>
			<span class="feed__when">#${esc(String(r.id))}</span></li>`;
		})
		.join("");
	return {
		title: t("tool.historyDocTitle", "History: {title} — Toolhub", { title }),
		html: `
		<div class="container page">
			<a class="back" href="${toolHref(name)}">${t("tool.backToName", "← Back to {title}", { title: esc(title) })}</a>
			<h1 class="page__title">${t("tool.revisionHistoryTitle", "Revision history")}</h1>
			<ul class="feed">${rows || `<li><div class="feed__static">${t("tool.noRevisions", "No revisions recorded.")}</div></li>`}</ul>
		</div>`
	};
}
/** @param {string} name */
export function viewDiffStub(name) {
	const tool = /** @type {Record<string, Tool>} */ (INDEX)[name];
	return prosePage(
		t("tool.revisionDiffTitle", "Revision diff"),
		`
		<p>${t("tool.diffCompareLead", "Compare two revisions of")} <strong>${esc(tool ? tool.title : name)}</strong> ${t("tool.diffCompareTail", "side by side.")}</p>
		<p>${t("tool.diffIntro", "Revision diffs are served from Toolhub's versioning API. In this prototype the\n\t\tdiff viewer is not wired up — see it on the")}
		<a href="https://toolhub.wikimedia.org/" target="_blank" rel="noopener nofollow">${t("tool.liveSite", "live site")}</a>.</p>
		<p><a href="${toolHref(name)}/history">${t("tool.backToHistory", "← Back to history")}</a></p>`
	);
}
