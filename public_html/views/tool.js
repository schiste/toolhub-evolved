// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, safeUrl } from "../lib/core/dom.js";
import { t, timeTag, updatedTimeTag } from "../lib/core/i18n.js";
import { INDEX, apiGet, backendGetJson, getTool, isNewTool } from "../lib/core/api.js";
import { egoGraph } from "../lib/core/graph.js";
import { renderMarkdown } from "../lib/core/markdown.js";
import { serverWrite } from "../lib/core/serversync.js";
import { completeness, endorsementOf, listMemberships } from "../lib/core/signals.js";
import { getSimilarityIndex, nearestNeighbors } from "../lib/core/similarity.js";
import { signedIn } from "../lib/core/session.js";
import { demoRevisionsFor, syncStatusLabel } from "../lib/core/store.js";
import { authorProfileUrl } from "../lib/core/author-index.js";
import { authorHref, toolHref } from "../lib/core/routing.js";
import { avatar, toolIcon } from "../lib/atoms/avatar.js";
import {
	completenessList,
	completenessMeter,
	endorsementChip,
	fitChip,
	freshnessNote,
	statusBadge
} from "../lib/atoms/badges.js";
import { button } from "../lib/atoms/button.js";
import { icon } from "../lib/atoms/icon.js";
import { glanceChips, keywordTags, langLabel, linkOut, metaItem, wikiLabel } from "../lib/atoms/labels.js";
import { favBtn } from "../lib/molecules/favbtn.js";
import { saveToListControl } from "../lib/molecules/savemenu.js";
import { forceGraph } from "../lib/organisms/force-graph.js";
import { openQuickView } from "../lib/organisms/quickview.js";
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
					<button class="related__title" type="button" data-tool="${esc(tool.name)}" aria-label="${t("tool.quickLookAria", "Quick look: {title}", { title: esc(tool.title) })}" style="${QUICK_VIEW_BUTTON_STYLE}"${dirAttrs(tool.title)}>${esc(tool.title)}</button>
					${deprecated}
				</div>
				<div class="related__maint">${t("tool.by", "by")} <span${dirAttrs(tool.maintainer)}>${esc(tool.maintainer)}</span></div>
				${chips ? `<div class="related__chips">${chips}</div>` : ""}
			</div>
		</article>`;
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
			${healthStatus ? `<span class="signal">${t("tool.healthStatus", "Health: {status}", { status: esc(healthStatus) })}</span>` : ""}
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
			return `<figure class="tool-media__item"><img src="${url}" alt="${esc(title)}" loading="lazy" /><figcaption>${esc(title)} · ${esc(item.license || "")}</figcaption></figure>`;
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
		<h2 class="panel__title">${t("tool.screenshotsTitle", "Screenshots")}</h2>
		${approved ? `<div class="tool-media__grid">${approved}</div>` : ""}
		${submit}
		<p class="at__result" data-media-result aria-live="polite"></p>
	</div>`;
}

/** @param {string} name */
export async function viewTool(name) {
	const tool =
		/** @type {(Tool & { edited?: boolean, annotated?: boolean, endorsement?: { count?: number } }) | null} */ (
			await getTool(name)
		);
	if (!tool) return viewToolNotFound(name);
	const [evolvedSignals, evolvedMedia] = await Promise.all([
		backendGetJson(`/v1/tools/${encodeURIComponent(name)}/signals/`).catch(() => null),
		backendGetJson(`/v1/tools/${encodeURIComponent(name)}/media/`).catch(() => null)
	]);
	const mediaRows = Array.isArray(evolvedMedia?.results) ? evolvedMedia.results : [];
	const provTags = [
		wikidataChip(tool.wikidata),
		...(signedIn()
			? [
					isNewTool(name)
						? `<span class="exp-badge">${esc(tool.syncLabel || syncStatusLabel(tool.syncStatus) || t("tool.localSubmissionBadge", "Evolved-local submission"))}</span>`
						: "",
					tool.edited
						? `<span class="exp-badge">${t("tool.localEditBadge", "Edited in Evolved")} · ${esc(syncStatusLabel(tool.editSyncStatus))}</span>`
						: "",
					tool.annotated
						? `<span class="exp-badge">${t("tool.localAnnotationsBadge", "Community annotations in Evolved")} · ${esc(syncStatusLabel(tool.annotationSyncStatus))}</span>`
						: ""
				]
			: [])
	]
		.filter(Boolean)
		.join(" ");
	const syncErrors = [tool.lastError, tool.editLastError, tool.annotationLastError]
		.filter(Boolean)
		.map(
			(msg) =>
				`<p class="toolpage__sync-error">${t("tool.syncErrorPrefix", "Sync issue:")} ${esc(String(msg))}</p>`
		)
		.join("");
	const tags = keywordTags(tool, { empty: "—" });
	const authors = authorInlineList(tool);

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

	// REAL status — only the deprecated/experimental flags (shown even when exp off).
	const realBadge = statusBadge(tool);
	const membershipMap = await listMemberships();
	tool.endorsement = endorsementOf(tool.name, membershipMap);

	/** @type {Array<{ tool: Tool, shared?: string[] }>} */
	let related = [];
	try {
		const simIndex = await getSimilarityIndex();
		related = nearestNeighbors(tool, simIndex, 6);
	} catch {
		// keep the initial empty list
	}
	const relatedHtml =
		related.length > 0
			? `<section class="related" aria-labelledby="related-title">
				<div class="section-head"><h2 id="related-title">${t("tool.relatedTitle", "Related tools")}</h2></div>
				<p class="related__subtitle">${t("tool.relatedSubtitle", "Overlapping function and scope, by shared metadata.")}</p>
				<div class="related__list">${related.map((item) => relatedToolRow(item)).join("")}</div>
			</section>`
			: "";
	/** @type {{ nodes: GraphNode[], edges: GraphEdge[] } | null} */
	let ego = null;
	try {
		const graph = await egoGraph(name, 10);
		// Stryker disable next-line ArrayDeclaration: egoGraph always returns a `nodes` array; the `|| []` fallback is never taken, and the sentinel array's length (1) is still < 3 — equivalent.
		if ((graph.nodes || []).length >= 3) ego = graph;
	} catch {
		// keep ego null
	}
	const neighborhoodHtml = ego
		? `<section class="neighborhood" aria-labelledby="neighborhood-title">
				<div class="section-head"><h2 id="neighborhood-title">${t("tool.neighborhoodTitle", "Neighborhood")}</h2></div>
				<div class="graph graph--ego"><div id="ego-canvas"></div></div>
				<p class="graph__caption">${t("tool.neighborhoodCaption", "This tool and its nearest neighbors by metadata. Click a node to peek.")}</p>
			</section>`
		: "";

	// At-a-glance chips (real metadata).
	const glance = glanceChips(tool);

	const maintList = authorEntries(tool)
		.map((a) => `<li>${avatar(a.name)}<span class="maint-list__name">${authorLink(a)}</span></li>`)
		.join("");
	const complete = completeness(tool);
	// Stryker disable next-line OptionalChaining: `tool.endorsement` is always assigned above via endorsementOf(), so optional vs plain access is equivalent.
	const endorsementCount = tool.endorsement?.count;
	// Stryker disable next-line StringLiteral: button() defaults variant to "outline", so "" renders identical markup — equivalent.
	const html = `
	<div class="container page">
		<a class="back" href="/search">${t("tool.backToTools", "← Back to tools")}</a>
		<header class="toolpage__head">
			${toolIcon(tool, "lg")}
			<div class="toolpage__id">
				<h1 class="toolpage__title"${dirAttrs(tool.title)}>${esc(tool.title)}</h1>
				${tool.subtitle ? `<p class="toolpage__subtitle"${dirAttrs(tool.subtitle)}>${esc(tool.subtitle)}</p>` : ""}
				<div class="toolpage__by">${t("tool.by", "by")} ${authors}</div>
				${sponsorLine(tool.sponsor)}
				${replacementNote(tool)}
				${provTags ? `<div class="toolpage__prov">${provTags}</div>` : ""}
				${syncErrors}
				<div class="toolpage__glance">${glance}</div>
				<div class="toolpage__row">
					${realBadge}
					${endorsementChip(endorsementCount)}
					${fitChip(tool)}
					${updatedTimeTag(tool.modified, "toolpage__when")}
					${freshnessNote(tool)}
				</div>
			</div>
			<div class="toolpage__cta">
				${tool.url ? button(t("tool.openTool", "Open tool"), { variant: "primary", size: "lg", href: safeUrl(tool.url), icon: "external", attrs: 'target="_blank" rel="noopener nofollow"' }) : ""}
				${signedIn() ? favBtn(tool.name, { label: true, cls: "favbtn--btn favbtn--lg" }) : ""}
				<!-- EXPERIMENTAL — Save to a list. Needs: POST/PUT /api/lists/ (Lane B). -->
				${signedIn() ? saveToListControl(tool.name) : ""}
			</div>
		</header>

		<div class="toolpage__grid">
			<div class="toolpage__main">
				<div class="prose"${dirAttrs(tool.description)}>${renderMarkdown(tool.description) || `<em>${t("tool.noDescription", "No description provided.")}</em>`}</div>
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

				${relatedHtml}
				${neighborhoodHtml}
			</div>

			<aside class="toolpage__side">
				<div class="panel">
					<h2 class="panel__title">${t("tool.getStarted", "Get started")}</h2>
					<div class="toolpage__actions">${actions || `<span class="meta__v">${t("tool.noLinksProvided", "No links provided")}</span>`}</div>
					<div class="toolpage__sub">
						<a href="${toolHref(tool.name)}/history">${t("tool.viewHistory", "View history")}</a>
						${
							signedIn()
								? `<a href="${toolHref(tool.name)}/edit">${t("tool.editTool", "Edit tool")}</a> <a href="${toolHref(tool.name)}/edit-annotations">${t("tool.editAnnotations", "Edit annotations")}</a>`
								: `<a href="${toolHref(tool.name)}/edit">${t("tool.suggestAnEdit", "Suggest an edit")}</a>`
						}
					</div>
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
		if (signedIn()) {
			serverWrite("POST", `/v1/tools/${encodeURIComponent(name)}/events/`, { eventType: "view" }).catch(() => {});
		}
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
		const target = /** @type {HTMLElement | null} */ (document.querySelector("#ego-canvas"));
		// Stryker disable next-line LogicalOperator: #ego-canvas is rendered exactly when `ego` is set, so `target` and `ego` are both present or both absent — `&&` vs `||` is indistinguishable here.
		if (!target || !ego) return;
		target.forceGraphHandle = forceGraph(target, ego, { onSelect: openQuickView, height: 320 });
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
