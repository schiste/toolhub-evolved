// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, safeUrl } from "../lib/core/dom.js";
import { timeTag, updatedTimeTag } from "../lib/core/i18n.js";
import { INDEX, apiGet, getTool, isNewTool, normalizeTool } from "../lib/core/api.js";
import { signedIn } from "../lib/core/session.js";
import { demoRevisionsFor } from "../lib/core/store.js";
import { toolHref } from "../lib/core/routing.js";
import { avatar, toolIcon } from "../lib/atoms/avatar.js";
import { healthBadge, popularityBadge, statusBadge } from "../lib/atoms/badges.js";
import { glanceChips, keywordTags, langLabel, linkOut, metaItem, wikiLabel } from "../lib/atoms/labels.js";
import { reviewsBlock, usageBlock } from "../lib/atoms/signals.js";
import { favBtn } from "../lib/molecules/favbtn.js";
import { saveToListControl } from "../lib/molecules/savemenu.js";
import { grid } from "../lib/organisms/grid.js";
import { toolCard } from "../lib/organisms/tool-card.js";
import { prosePage, viewNotFound } from "./static.js";

export const RELATED_LIMIT = 4;
// REAL — related tools derived from shared keywords (no missing data).
export async function relatedTools(t) {
	const kw = (t.keywords || [])[0];
	if (!kw) return [];
	try {
		const data = await apiGet("/search/tools/", { keywords__term: kw, page_size: "5" });
		return (data.results || []).map(normalizeTool).filter((o) => o.name !== t.name).slice(0, RELATED_LIMIT);
	} catch (e) { return []; }
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

	const related = await relatedTools(t);
	const relatedHtml = related.length
		? `<h2 class="toolpage__h2">Related tools</h2>${grid("grid-tools", related, (x) => toolCard(x))}`
		: "";

	// At-a-glance chips (real metadata).
	const glance = glanceChips(t);

	const maintList = (t.authors && t.authors.length ? t.authors : [t.maintainer])
		.map((a) => `<li>${avatar(a)}<span${dirAttrs(a)}>${esc(a)}</span></li>`).join("");

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
					<!-- EXPERIMENTAL — operational health. Needs: an uptime/health-check service. -->
					${healthBadge(t)}
					<!-- EXPERIMENTAL — popularity. Needs: usage/view tracking the API doesn't expose. -->
					${popularityBadge(t)}
					${updatedTimeTag(t.modified, "toolpage__when")}
				</div>
			</div>
			<div class="toolpage__cta">
				${t.url ? `<a class="btn btn--primary btn--lg" href="${safeUrl(t.url)}" target="_blank" rel="noopener">Open tool <span aria-hidden="true">↗</span></a>` : ""}
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
					<button class="btn btn--outline" type="button" disabled>Write a review</button>
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
		<li><span class="feed__ic" aria-hidden="true">🕓</span>
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
