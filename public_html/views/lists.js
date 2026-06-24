// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, dirAttrs, esc } from "../lib/core/dom.js";
import { countLabel } from "../lib/core/i18n.js";
import { apiGet, getToolsByName, normalizeList, normalizeTool } from "../lib/core/api.js";
import { attachEndorsements, rankFitsFirst } from "../lib/core/signals.js";
import { signedIn } from "../lib/core/session.js";
import { listHref } from "../lib/core/routing.js";
import { demoListDelete, demoListGet, demoListNew, demoListSave, demoLists, favNames, isDemoListId } from "../lib/core/store.js";
import { button, iconButton } from "../lib/atoms/button.js";
import { fArea, fInput, fieldValue } from "../lib/atoms/form-fields.js";
import { icon } from "../lib/atoms/icon.js";
import { grid } from "../lib/organisms/grid.js";
import { listCard, listCardData } from "../lib/organisms/list-card.js";
import { toolCard } from "../lib/organisms/tool-card.js";
import { viewNotFound } from "./static.js";

/* ---- Lists overview + list detail -------------------------------------- */
export async function viewLists() {
	const data = await apiGet("/lists/", { page_size: "30" }).catch(() => ({ results: [] }));
	const live = (data.results || []).map(normalizeList);
	// When experimenting, the user's demo lists appear first (clearly tagged).
	const mine = signedIn() ? demoLists().map(listCardData) : [];
	const all = mine.concat(live);
	const html = `
	<div class="container page">
		<div class="section-head"><h1 class="page__title">Curated lists</h1>
			${signedIn() ? button("Create a list", { variant: "primary", href: "#/lists/create", icon: "add" }) : ""}</div>
		<p class="page__intro">Community-published collections of tools for specific tasks and communities.</p>
		${all.length ? grid("grid-lists", all, listCard) : '<p class="empty">No lists found.</p>'}
	</div>`;
	return { title: "Curated lists — Toolhub", html };
}
export async function viewList(id) {
	const isDemo = isDemoListId(id);
	let l, tools, demoTag = "", editBtn = "";
	if (isDemo) {
		const d = demoListGet(id);
		if (!d) return viewNotFound();
		tools = await getToolsByName(d.tools);
		l = { title: d.title || "Untitled list", description: d.description || "", toolCount: tools.length };
		demoTag = ' <span class="exp-badge">Demo list</span>';
		if (signedIn()) editBtn = button("Edit list", { variant: "outline", href: `${listHref(id)}/edit`, icon: "edit" });
	} else {
		try { l = normalizeList(await apiGet("/lists/" + encodeURIComponent(id) + "/")); tools = l.tools; }
		catch (e) { return viewNotFound(); }
	}
	await attachEndorsements(tools);
	tools = rankFitsFirst(tools);
	const html = `
	<div class="container page">
		<a class="back" href="#/lists">← All lists</a>
		<div class="section-head"><h1 class="page__title"${dirAttrs(l.title)}>${esc(l.title)}${demoTag} <span class="lcard__count">${esc(countLabel(l.toolCount, "tool", "tools"))}</span></h1>${editBtn}</div>
		<div class="prose page__intro"${dirAttrs(l.description)}>${esc(l.description)}</div>
		${tools.length ? grid("grid-tools", tools, (t) => toolCard(t)) : '<p class="empty">This list has no tools yet.</p>'}
	</div>`;
	return { title: `${l.title} — Toolhub`, html };
}
// EXPERIMENTAL — your demo lists. Needs: GET /api/lists/ scoped to the user.
export function viewMyLists() {
	const cards = demoLists().map(listCardData);
	const html = `
	<div class="container page">
		<div class="section-head"><h1 class="page__title">Your lists <span class="exp-badge">Experimental</span></h1>
			${button("Create a list", { variant: "primary", href: "#/lists/create", icon: "add" })}</div>
		<p class="page__intro">Lists you've built in this demo. Stored only in this browser — see
		<a href="#/rules-of-engagement">Rules of Engagement</a>.</p>
		${cards.length ? grid("grid-lists", cards, listCard) : '<p class="empty">No lists yet. <a href="#/lists/create">Create your first list</a>.</p>'}
	</div>`;
	return { title: "Your lists — Toolhub", html };
}
// EXPERIMENTAL — favorites view. Tools are read by name (local-first via getTool); the
// overlay only stores which names are favorited. Needs: GET /api/user/favorites/ in production.
export async function viewFavorites() {
	const tools = await getToolsByName(favNames());
	await attachEndorsements(tools);
	const body = tools.length
		? grid("grid-tools", tools, (t) => toolCard(t))
		: `<p class="empty">No favorites yet. Tap the ${icon("starOutline")}<span class="skip-label">star</span> on any tool card or page to save it here.</p>`;
	return { title: "Favorites — Toolhub", html: `
		<div class="container page">
			<h1 class="page__title">Favorites <span class="exp-badge">Experimental</span></h1>
			<p class="page__intro">Tools you've saved. Stored only in this browser — see
			<a href="#/rules-of-engagement">Rules of Engagement</a>.</p>
			${body}
		</div>` };
}
// EXPERIMENTAL — create/edit a demo list. Needs: POST/PUT /api/lists/.
export function viewListEdit(id) {
	const editing = id != null;
	const src = editing ? demoListGet(id) : demoListNew();
	if (editing && !src) return viewNotFound();
	const work = { id: src.id, title: src.title || "", description: src.description || "", tools: (src.tools || []).slice() };
	const html = `
	<div class="container page le">
		<a class="back" href="${editing ? listHref(work.id) : "#/my-lists"}">← Back</a>
		<h1 class="page__title">${editing ? "Edit list" : "Create a list"} <span class="exp-badge">Experimental</span></h1>
		<form data-le-form>
			${fInput("Title", "le-title", work.title, { req: true, max: 120, reqMark: false })}
			${fArea("Description", "le-desc", work.description, null, { max: 600 })}
			<h2 class="le__h2">Tools <span class="le__count" data-le-count></span></h2>
			<ol class="le__tools" data-le-tools></ol>
			<div class="le__add">
				<input class="le__input" id="le-q" type="search" placeholder="Search tools to add…" autocomplete="off" />
				${button("Search", { variant: "outline", attrs: "data-le-search" })}
			</div>
			<div class="le__results" data-le-results></div>
			<div class="le__actions">
				${button(editing ? "Save changes" : "Create list", { variant: "primary", type: "submit" })}
				${editing ? button("Delete list", { variant: "danger", cls: "le__delete", attrs: "data-le-delete" }) : ""}
			</div>
		</form>
	</div>`;
	function mount() {
		const toolsEl = $("[data-le-tools]"), countEl = $("[data-le-count]"), resultsEl = $("[data-le-results]");
		function renderTools() {
			countEl.textContent = countLabel(work.tools.length, "tool", "tools");
			toolsEl.innerHTML = work.tools.length ? work.tools.map((n, i) => `
				<li data-tn="${esc(n)}"><span class="le__tn"${dirAttrs(n)}>${esc(n)}</span>
					<span class="le__rowact">
						${iconButton("chevronUp", "Move up", { size: "sm", attrs: 'data-move="up"', disabled: i === 0 })}
						${iconButton("chevronDown", "Move down", { size: "sm", attrs: 'data-move="down"', disabled: i === work.tools.length - 1 })}
						${iconButton("close", "Remove from list", { size: "sm", variant: "danger", attrs: "data-rm" })}
					</span></li>`).join("") : '<li class="le__empty">No tools yet — search below to add some.</li>';
		}
		renderTools();
		toolsEl.addEventListener("click", (e) => {
			const li = e.target.closest("[data-tn]"); if (!li) return;
			const n = li.getAttribute("data-tn"), i = work.tools.indexOf(n);
			if (i === -1) return;
			if (e.target.closest("[data-rm]")) { work.tools.splice(i, 1); }
			else if (e.target.closest('[data-move="up"]') && i > 0) { work.tools.splice(i - 1, 0, work.tools.splice(i, 1)[0]); }
			else if (e.target.closest('[data-move="down"]') && i < work.tools.length - 1) { work.tools.splice(i + 1, 0, work.tools.splice(i, 1)[0]); }
			else return;
			renderTools();
		});
		async function runSearch() {
			const q = $("#le-q").value.trim(); if (!q) return;
			resultsEl.innerHTML = '<p class="le__searching">Searching…</p>';
			try {
				const data = await apiGet("/search/tools/", { q, page_size: "8" });
				const rows = (data.results || []).map(normalizeTool);
				resultsEl.innerHTML = rows.length ? rows.map((t) => {
					const inList = work.tools.indexOf(t.name) !== -1;
					return `<button class="le__result${inList ? " is-in" : ""}" type="button" data-add="${esc(t.name)}" ${inList ? "disabled" : ""}>
						${inList ? icon("check") : icon("add")} <span${dirAttrs(t.title)}>${esc(t.title)}</span></button>`;
				}).join("") : '<p class="le__empty">No matches.</p>';
			} catch (e) { resultsEl.innerHTML = '<p class="le__empty">Search failed.</p>'; }
		}
		$("[data-le-search]").addEventListener("click", runSearch);
		$("#le-q").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); runSearch(); } });
		resultsEl.addEventListener("click", (e) => {
			const b = e.target.closest("[data-add]"); if (!b) return;
			const n = b.getAttribute("data-add");
			if (work.tools.indexOf(n) === -1) { work.tools.push(n); renderTools(); b.disabled = true; b.classList.add("is-in"); const ic = b.querySelector(".icon"); if (ic) ic.outerHTML = icon("check"); }
		});
		$("[data-le-form]").addEventListener("submit", (e) => {
			e.preventDefault();
			const title = fieldValue("le-title");
			if (!title) { $("#le-title").focus(); return; }
			work.title = title; work.description = fieldValue("le-desc");
			demoListSave(work);
			location.hash = listHref(work.id);
		});
		const del = $("[data-le-delete]");
		if (del) del.addEventListener("click", () => { demoListDelete(work.id); location.hash = "#/my-lists"; });
	}
	return { title: `${editing ? "Edit list" : "Create a list"} — Toolhub`, html, mount };
}
