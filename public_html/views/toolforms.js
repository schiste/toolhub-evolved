// SPDX-License-Identifier: GPL-3.0-or-later
import { $, dirAttrs, esc } from "../lib/core/dom.js";
import { countLabel } from "../lib/core/i18n.js";
import { getTool, isNewTool, newToolBase } from "../lib/core/api.js";
import { toolHref } from "../lib/core/routing.js";
import { DEMO_KEYS, SAMPLE_TOOLINFO, crawlerUrlAdd, crawlerUrlDelete, crawlerUrls, demoStore, fromCsv, ingestToolinfo, logActivity, toCsv, toolAnnosMap, toolEditsMap, toolNewMap } from "../lib/core/store.js";
import { button, iconButton } from "../lib/atoms/button.js";
import { TOOL_TYPES, checkedValue, fArea, fCheck, fInput, fSelect, fieldValue } from "../lib/atoms/form-fields.js";
import { grid } from "../lib/organisms/grid.js";
import { toolCard } from "../lib/organisms/tool-card.js";
import { viewNotFound } from "./static.js";

// EXPERIMENTAL — create/edit a tool's CORE fields. name=null → create.
// Edits overload the live record; new tools live only in the browser.
export async function viewToolForm(name) {
	const editing = name != null;
	let cur = { name: "", title: "", description: "", url: "", repository: null, license: null, toolType: null, keywords: [], forWikis: [], deprecated: false, experimental: false };
	if (editing) {
		cur = await getTool(name);
		if (!cur) return viewNotFound();
	}
	const isCrawler = editing && cur.origin && cur.origin !== "api";
	const html = `
	<div class="container page le">
		<a class="back" href="${editing ? toolHref(name) : "#/add-or-remove-tools"}">← Back</a>
		<h1 class="page__title">${editing ? "Edit tool" : "Submit a tool"} <span class="exp-badge">Experimental</span></h1>
		<p class="page__intro">Changes are saved only in this browser — see <a href="#/rules-of-engagement">Rules of Engagement</a>.
		${isCrawler ? "In production, core fields of crawler-imported tools are owned by the maintainer's <code>toolinfo.json</code>; only <code>origin=api</code> tools are core-editable. This demo lets you edit anyway." : ""}</p>
		<form data-tool-form>
			<h2 class="le__h2">Core information</h2>
			${editing ? `<p class="le__ro">Name: <code>${esc(name)}</code></p>` : fInput("Name (unique id)", "tf-name", "", { req: true, ph: "my-cool-tool", max: 120, hint: "Stable id used in Toolhub URLs." })}
			${fInput("Title", "tf-title", cur.title, { req: true, hint: "Short display name shown in search results." })}
			${fArea("Description", "tf-desc", cur.description, "One or two sentences about what the tool does.")}
			${fInput("URL", "tf-url", cur.url, { req: true, type: "url", ph: "https://…", hint: "Primary homepage, documentation, or launch URL." })}
			${fInput("Source code repository", "tf-repo", cur.repository, { type: "url", hint: "Optional public repository URL." })}
			${fInput("License (SPDX id)", "tf-license", cur.license, { ph: "GPL-3.0-or-later", hint: "Use an SPDX identifier when known." })}
			${fSelect("Tool type", "tf-type", cur.toolType, TOOL_TYPES, { hint: "Choose the closest match." })}
			${fInput("Keywords (comma-separated)", "tf-keywords", toCsv(cur.keywords), { hint: "Terms people might search for." })}
			${fInput("Works on wikis (comma-separated, * for all)", "tf-wikis", toCsv(cur.forWikis), { hint: "Use wiki database names, or * for all wikis." })}
			<div class="le__checks">${fCheck("Deprecated", "tf-deprecated", cur.deprecated)}${fCheck("Experimental", "tf-experimental", cur.experimental)}</div>
			<div class="le__actions">
				${button(editing ? "Save changes" : "Submit tool", { variant: "primary", type: "submit" })}
				${editing && !isNewTool(name) ? button("Revert demo edits", { variant: "danger", cls: "le__delete", attrs: "data-tf-revert" }) : ""}
				${editing && isNewTool(name) ? button("Delete submission", { variant: "danger", cls: "le__delete", attrs: "data-tf-delete" }) : ""}
			</div>
		</form>
	</div>`;
	function mount() {
		$("[data-tool-form]").addEventListener("submit", (e) => {
			e.preventDefault();
			const title = fieldValue("tf-title"), url = fieldValue("tf-url"), desc = fieldValue("tf-desc");
			const tname = editing ? name : fieldValue("tf-name");
			if (!tname || !title || !url) { document.getElementById(editing ? "tf-title" : "tf-name").focus(); return; }
			if (!editing && (isNewTool(tname))) { alert("A demo tool with that name already exists."); return; }
			const fields = {
				title, description: desc, url,
				repository: fieldValue("tf-repo") || null, license: fieldValue("tf-license") || null,
				toolType: fieldValue("tf-type") || null, keywords: fromCsv(fieldValue("tf-keywords")),
				forWikis: fromCsv(fieldValue("tf-wikis")), deprecated: checkedValue("tf-deprecated"), experimental: checkedValue("tf-experimental"),
			};
			if (editing && !isNewTool(tname)) {
				const m = toolEditsMap(); m[tname] = fields; demoStore.set(DEMO_KEYS.toolEdits, m);
				logActivity("edited", tname, title);
			} else {
				const m = toolNewMap(); m[tname] = fields; demoStore.set(DEMO_KEYS.toolNew, m);
				logActivity(editing ? "edited" : "created", tname, title);
			}
			location.hash = toolHref(tname);
		});
		const rev = $("[data-tf-revert]");
		if (rev) rev.addEventListener("click", () => { const m = toolEditsMap(); delete m[name]; demoStore.set(DEMO_KEYS.toolEdits, m); location.hash = toolHref(name); });
		const del = $("[data-tf-delete]");
		if (del) del.addEventListener("click", () => { const m = toolNewMap(); delete m[name]; demoStore.set(DEMO_KEYS.toolNew, m); location.hash = "#/add-or-remove-tools"; });
	}
	return { title: `${editing ? "Edit tool" : "Submit a tool"} — Toolhub`, html, mount };
}

// EXPERIMENTAL — add/remove tools: submissions + crawler-URL register + JSON ingest.
export function viewAddTools() {
	function urlRows() {
		const u = crawlerUrls();
		return u.length ? u.map((x) => `<li><code class="at__url">${esc(x.url)}</code> ${iconButton("close", "Remove URL", { size: "sm", cls: "at__rm", attrs: `data-url-rm="${esc(x.url)}"` })}</li>`).join("")
			: '<li class="le__empty">No URLs registered.</li>';
	}
	function subGrid() {
		const cards = Object.keys(toolNewMap()).map((n) => newToolBase(n));
		return cards.length ? grid("grid-tools", cards, (t) => toolCard(t)) : '<p class="empty">No tools yet. Submit one above, or ingest sample toolinfo.</p>';
	}
	const html = `
	<div class="container page at">
		<div class="section-head"><h1 class="page__title">Add or remove tools <span class="exp-badge">Experimental</span></h1>
			${button("Submit a tool", { variant: "primary", href: "#/tools/create", icon: "add" })}</div>
		<p class="page__intro">Register a <code>toolinfo.json</code> URL, or paste/ingest toolinfo to add records.
		Everything stays in this browser — see <a href="#/rules-of-engagement">Rules of Engagement</a>.</p>

		<h2 class="le__h2">Register a toolinfo.json URL</h2>
		<form class="le__add" data-url-form>
			${fInput("toolinfo.json URL", "at-url", "", { type: "url", ph: "https://example.org/toolinfo.json", hint: "Public URL the crawler should re-read." })}
			${button("Register", { variant: "outline", type: "submit" })}
		</form>
		<ul class="at__urls" data-url-list>${urlRows()}</ul>

		<h2 class="le__h2">Ingest toolinfo</h2>
		${fArea("Toolinfo JSON", "at-json", "", "Paste one tool object or an array.", { rows: 10, max: false, cls: "at__json", ph: '{ "name": "my-tool", "title": "My Tool", "description": "…", "url": "https://…" }' })}
		<div class="le__actions">
			${button("Ingest", { variant: "primary", attrs: "data-ingest" })}
			${button("Load sample", { variant: "outline", attrs: "data-sample" })}
		</div>
		<p class="at__result" data-ingest-result aria-live="polite"></p>

		<h2 class="le__h2">Your tools <span class="le__count" data-sub-count></span></h2>
		<div data-sub-grid>${subGrid()}</div>
	</div>`;
	function mount() {
		$("[data-url-form]").addEventListener("submit", (e) => {
			e.preventDefault();
			const u = $("#at-url").value.trim(); if (!u) return;
			crawlerUrlAdd(u); $("#at-url").value = "";
			$("[data-url-list]").innerHTML = urlRows();
		});
		$("[data-url-list]").addEventListener("click", (e) => {
			const b = e.target.closest("[data-url-rm]"); if (!b) return;
			crawlerUrlDelete(b.getAttribute("data-url-rm")); $("[data-url-list]").innerHTML = urlRows();
		});
		$("[data-sample]").addEventListener("click", () => { $("#at-json").value = SAMPLE_TOOLINFO; });
		$("[data-ingest]").addEventListener("click", () => {
			const res = ingestToolinfo($("#at-json").value.trim());
			const out = $("[data-ingest-result]");
			if (res.error) { out.className = "at__result at__result--err"; out.textContent = res.error; return; }
			const parts = [];
			if (res.added) parts.push(res.added + " added");
			if (res.updated) parts.push(res.updated + " updated");
			out.className = "at__result" + (res.errors.length && !parts.length ? " at__result--err" : " at__result--ok");
			out.textContent = (parts.join(", ") || "Nothing ingested") + (res.errors.length ? " · " + res.errors.join("; ") : "");
			$("[data-sub-grid]").innerHTML = subGrid();
			const c = $("[data-sub-count]"); if (c) c.textContent = countLabel(Object.keys(toolNewMap()).length, "tool", "tools");
		});
	}
	return { title: "Add or remove tools — Toolhub", html, mount };
}

// EXPERIMENTAL — edit a tool's COMMUNITY ANNOTATIONS (overlay on live record).
export async function viewAnnotationsEdit(name) {
	const cur = await getTool(name);
	if (!cur) return viewNotFound();
	const html = `
	<div class="container page le">
		<a class="back" href="${toolHref(name)}">← Back to ${esc(cur.title)}</a>
		<h1 class="page__title">Edit annotations <span class="exp-badge">Experimental</span></h1>
		<p class="page__intro">Community annotations enrich a tool without touching its core data. Saved only in
		this browser — see <a href="#/rules-of-engagement">Rules of Engagement</a>.</p>
		<form data-anno-form>
			<h2 class="le__h2">Community annotations for <span${dirAttrs(cur.title)}>${esc(cur.title)}</span></h2>
			${fInput("Audiences (comma-separated)", "an-aud", toCsv(cur.audiences), { hint: "User groups this tool serves." })}
			${fInput("Tasks (comma-separated)", "an-tasks", toCsv(cur.tasks), { hint: "Workflows this tool supports." })}
			${fSelect("Tool type", "an-type", cur.toolType, TOOL_TYPES, { hint: "Community classification for discovery." })}
			${fInput("Icon (Commons File: URL)", "an-icon", cur.icon, { type: "url", hint: "Optional icon hosted on Commons." })}
			<div class="le__actions">
				${button("Save annotations", { variant: "primary", type: "submit" })}
				${toolAnnosMap()[name] ? button("Revert annotations", { variant: "danger", cls: "le__delete", attrs: "data-an-revert" }) : ""}
			</div>
		</form>
	</div>`;
	function mount() {
		$("[data-anno-form]").addEventListener("submit", (e) => {
			e.preventDefault();
			const anno = { audiences: fromCsv(fieldValue("an-aud")), tasks: fromCsv(fieldValue("an-tasks")), toolType: fieldValue("an-type") || null, icon: fieldValue("an-icon") || null };
			const m = toolAnnosMap(); m[name] = anno; demoStore.set(DEMO_KEYS.toolAnnos, m);
			logActivity("annotated", name, cur.title);
			location.hash = toolHref(name);
		});
		const rev = $("[data-an-revert]");
		if (rev) rev.addEventListener("click", () => { const m = toolAnnosMap(); delete m[name]; demoStore.set(DEMO_KEYS.toolAnnos, m); location.hash = toolHref(name); });
	}
	return { title: `Edit annotations — Toolhub`, html, mount };
}
