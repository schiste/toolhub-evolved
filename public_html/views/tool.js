// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, safeUrl } from "../lib/core/dom.js";
import { timeTag, updatedTimeTag } from "../lib/core/i18n.js";
import { INDEX, apiGet, getTool, isNewTool } from "../lib/core/api.js";
import { completeness, endorsementOf, listMemberships } from "../lib/core/signals.js";
import { getSimilarityIndex, nearestNeighbors } from "../lib/core/similarity.js";
import { signedIn } from "../lib/core/session.js";
import { demoRevisionsFor } from "../lib/core/store.js";
import { toolHref } from "../lib/core/routing.js";
import { avatar, toolIcon } from "../lib/atoms/avatar.js";
import { completenessMeter, endorsementChip, fitChip, freshnessNote, healthBadge, popularityBadge, statusBadge } from "../lib/atoms/badges.js";
import { button } from "../lib/atoms/button.js";
import { icon } from "../lib/atoms/icon.js";
import { glanceChips, keywordTags, langLabel, linkOut, metaItem, wikiLabel } from "../lib/atoms/labels.js";
import { reviewsBlock, usageBlock } from "../lib/atoms/signals.js";
import { favBtn } from "../lib/molecules/favbtn.js";
import { saveToListControl } from "../lib/molecules/savemenu.js";
import { prosePage, viewNotFound } from "./static.js";

function relatedToolRow(item) {
	const t = item.tool;
	const chips = (item.shared || []).map((label) => `<span class="tag">${esc(label)}</span>`).join("");
	return `
		<article class="related__item" data-tool="${esc(t.name)}" role="button" tabindex="0" aria-label="Quick look: ${esc(t.title)}">
			${avatar(t.title)}
			<div class="related__body">
				<div class="related__title"${dirAttrs(t.title)}>${esc(t.title)}</div>
				<div class="related__maint">by <span${dirAttrs(t.maintainer)}>${esc(t.maintainer)}</span></div>
				${chips ? `<div class="related__chips">${chips}</div>` : ""}
			</div>
		</article>`;
}

export async function viewTool(name) {
	const t = await getTool(name);
	if (!t) return viewNotFound();
	const provTags = !signedIn() ? "" : [
		isNewTool(name) ? '<span class="exp-badge">Demo submission</span>' : "",
		t.edited ? '<span class="exp-badge">Edited · demo</span>' : "",
		t.annotated ? '<span class="exp-badge">Community annotations · demo</span>' : "",
	].filter(Boolean).join(" ");
	const tags = keywordTags(t, { empty: "—" });
	const authors = (t.authors || []).map(esc).join(", ") || esc(t.maintainer);

	// REAL links — render only the ones present on the record.
	const actions = [
		linkOut("Open tool", t.url), linkOut("Source code", t.repository),
		linkOut("API", t.apiUrl), linkOut("User docs", t.userDocs),
		linkOut("Developer docs", t.devDocs), linkOut("Report a bug", t.bugtracker),
		linkOut("Give feedback", t.feedback), linkOut("Translate", t.translate),
	].filter(Boolean).join("");

	// REAL status — only the deprecated/experimental flags (shown even when exp off).
	const realBadge = statusBadge(t);
	const membershipMap = await listMemberships();
	t.endorsement = endorsementOf(t.name, membershipMap);

	let related = [];
	try {
		const simIndex = await getSimilarityIndex();
		related = nearestNeighbors(t, simIndex, 6);
	} catch (e) {
		related = [];
	}
	const relatedHtml = related.length
		? `<section class="related" aria-labelledby="related-title">
				<div class="section-head"><h2 id="related-title">Related tools</h2></div>
				<p class="related__subtitle">Overlapping function and scope, by shared metadata.</p>
				<div class="related__list">${related.map(relatedToolRow).join("")}</div>
			</section>`
		: "";

	// At-a-glance chips (real metadata).
	const glance = glanceChips(t);

	const maintList = (t.authors && t.authors.length ? t.authors : [t.maintainer])
		.map((a) => `<li>${avatar(a)}<span${dirAttrs(a)}>${esc(a)}</span></li>`).join("");
	const complete = completeness(t);
	const completeRows = complete.items.map((item) => `
		<li><span class="complete-list__icon${item.ok ? "" : " complete-list__icon--empty"}">${item.ok ? icon("check") : "○"}</span><span>${esc(item.label)}</span></li>`).join("");

	const html = `
	<div class="container page">
		<a class="back" href="#/search">← Back to tools</a>
		<header class="toolpage__head">
			${toolIcon(t, "lg")}
			<div class="toolpage__id">
				<h1 class="toolpage__title"${dirAttrs(t.title)}>${esc(t.title)}</h1>
				<div class="toolpage__by">by <span dir="auto">${authors}</span></div>
				${provTags ? `<div class="toolpage__prov">${provTags}</div>` : ""}
				<div class="toolpage__glance">${glance}</div>
				<div class="toolpage__row">
					${realBadge}
					${endorsementChip(t.endorsement.count)}
					${fitChip(t)}
					${updatedTimeTag(t.modified, "toolpage__when")}
					${freshnessNote(t)}
					<!-- EXPERIMENTAL — operational health. Needs: an uptime/health-check service. -->
					${healthBadge(t)}
					<!-- EXPERIMENTAL — popularity. Needs: usage/view tracking the API doesn't expose. -->
					${popularityBadge(t)}
				</div>
			</div>
			<div class="toolpage__cta">
				${t.url ? button("Open tool", { variant: "primary", size: "lg", href: safeUrl(t.url), icon: "external", attrs: 'target="_blank" rel="noopener"' }) : ""}
				${signedIn() ? favBtn(t.name, { label: true, cls: "favbtn--btn favbtn--lg" }) : ""}
				<!-- EXPERIMENTAL — Save to a list. Needs: POST/PUT /api/lists/ (Lane B). -->
				${signedIn() ? saveToListControl(t.name) : ""}
			</div>
		</header>

		<div class="toolpage__grid">
			<div class="toolpage__main">
				<!-- EXPERIMENTAL — screenshots/preview. Needs: a screenshot field in the
				     toolinfo schema + image storage (no per-tool data possible here). -->
				<div class="experimental shotstrip">
					<div class="shot"></div><div class="shot"></div><div class="shot"></div>
					<span class="exp-badge shotstrip__badge">Experimental · screenshots</span>
				</div>

				<div class="prose"${dirAttrs(t.description)}>${esc(t.description) || "<em>No description provided.</em>"}</div>
				<div class="tcard__tags toolpage__tags">${tags}</div>

				<h2 class="toolpage__h2">Details</h2>
				<div class="detail__meta">
					${metaItem("Type", esc(t.toolType))}
					${metaItem("License", esc(t.license))}
					${metaItem("Works on", wikiLabel(t.forWikis))}
					${metaItem("Interface languages", langLabel(t.uiLanguages))}
					${metaItem("Technology", (t.technologyUsed || []).map(esc).join(", "))}
					${metaItem("Audiences", (t.audiences || []).map(esc).join(", "))}
				</div>

				<!-- EXPERIMENTAL — ratings & reviews. Needs: a reviews data model + authenticated submissions. -->
				<div class="experimental reviews">
					<h2 class="toolpage__h2">Reviews <span class="exp-badge">Experimental</span></h2>
					${reviewsBlock(t)}
					${button("Write a review", { variant: "outline", disabled: true })}
				</div>

				${relatedHtml}
			</div>

			<aside class="toolpage__side">
				<div class="panel">
					<h2 class="panel__title">Get started</h2>
					<div class="toolpage__actions">${actions || '<span class="meta__v">No links provided</span>'}</div>
					<div class="toolpage__sub">
						<a href="${toolHref(t.name)}/history">View history</a>
						${signedIn()
							? `<a href="${toolHref(t.name)}/edit">Edit tool</a> <a href="${toolHref(t.name)}/edit-annotations">Edit annotations</a>`
							: `<a href="${toolHref(t.name)}/edit">Suggest an edit</a>`}
					</div>
				</div>
				<div class="panel">
					<h2 class="panel__title">Maintainers</h2>
					<ul class="maint-list">${maintList}</ul>
				</div>
				<div class="panel">
					<h2 class="panel__title">Listing completeness</h2>
					${completenessMeter(complete)}
					<ul class="complete-list">${completeRows}</ul>
				</div>
				<!-- EXPERIMENTAL — usage stat. Needs: usage analytics the API doesn't expose. -->
				<div class="panel experimental">
					<h2 class="panel__title">Usage <span class="exp-badge">Experimental</span></h2>
					${usageBlock(t)}
				</div>
			</aside>
		</div>
	</div>`;
	return { title: `${t.title} — Toolhub`, html };
}

// Tool revision history — live from /api/tools/{name}/revisions/.
export async function viewToolHistory(name) {
	const [liveT, data] = await Promise.all([
		getTool(name),
		apiGet("/tools/" + encodeURIComponent(name) + "/revisions/", { page_size: "20" }).catch(() => ({ results: [] })),
	]);
	// Lane B: your demo edits show as the most recent revisions.
	const revs = demoRevisionsFor(name).concat(data.results || []);
	const t = liveT;
	if (!t && !revs.length) return viewNotFound();
	const title = t ? t.title : (revs[0] && revs[0].content_title) || name;
	const rows = revs.map((r, i) => `
		<li>${icon("history", "feed__ic")}
			<span class="feed__main">Revision by <strong${dirAttrs((r.user && r.user.username) || "system")}>${esc((r.user && r.user.username) || "system")}</strong> · ${timeTag(r.timestamp)}${r.comment ? " — <span dir=\"auto\">" + esc(r.comment) + "</span>" : ""}${i === 0 ? ' <span class="tag">current</span>' : ""}</span>
			<span class="feed__when">#${esc(String(r.id))}</span></li>`).join("");
	return { title: `History: ${title} — Toolhub`, html: `
		<div class="container page">
			<a class="back" href="${toolHref(name)}">← Back to ${esc(title)}</a>
			<h1 class="page__title">Revision history</h1>
			<ul class="feed">${rows || '<li><div class="feed__static">No revisions recorded.</div></li>'}</ul>
		</div>` };
}
export function viewDiffStub(name) {
	const t = INDEX[name];
	return prosePage("Revision diff", `
		<p>Compare two revisions of <strong>${esc(t ? t.title : name)}</strong> side by side.</p>
		<p>Revision diffs are served from Toolhub's versioning API. In this prototype the
		diff viewer is not wired up — see it on the
		<a href="https://toolhub.wikimedia.org/" target="_blank" rel="noopener">live site</a>.</p>
		<p><a href="${toolHref(name)}/history">← Back to history</a></p>`);
}
