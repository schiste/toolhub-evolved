// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $input, dirAttrs, esc } from "../lib/core/dom.js";
import { countLabel } from "../lib/core/i18n.js";
import { getTool, isNewTool, newToolBase } from "../lib/core/api.js";
import { navigateTo, toolHref } from "../lib/core/routing.js";
import { getSimilarityIndex, nearestNeighbors } from "../lib/core/similarity.js";
import { normStr } from "../lib/core/util.js";
import {
	DEMO_KEYS,
	SAMPLE_TOOLINFO,
	crawlerUrlAdd,
	crawlerUrlDelete,
	crawlerUrls,
	demoStore,
	fromCsv,
	ingestToolinfo,
	logActivity,
	toCsv,
	toolAnnosMap,
	toolEditsMap,
	toolNewMap
} from "../lib/core/store.js";
import { button, iconButton } from "../lib/atoms/button.js";
import {
	TOOL_TYPES,
	checkedValue,
	clearFieldError,
	fArea,
	fCheck,
	fInput,
	fSelect,
	fieldValue,
	setFieldError
} from "../lib/atoms/form-fields.js";
import { grid } from "../lib/organisms/grid.js";
import { toolCard } from "../lib/organisms/tool-card.js";
import { viewNotFound } from "./static.js";

/** @param {string} value */
function isHttpUrl(value) {
	let u;
	try {
		// Stryker disable next-line StringLiteral,MethodExpression: callers pass already-trimmed field values; an empty string and any sentinel both fail `new URL`, and the redundant .trim() has nothing to strip — equivalent.
		u = new URL(String(value || "").trim());
	} catch {
		return false;
	}
	return u.protocol === "http:" || u.protocol === "https:";
}

/**
 * @param {string} id
 * @param {string} msg
 * @param {{ required?: boolean }} [opts]
 * @returns {HTMLElement | null}
 */
function validateHttpField(id, msg, opts = {}) {
	const value = fieldValue(id);
	clearFieldError(id);
	if ((opts.required || value) && !isHttpUrl(value)) {
		setFieldError(id, msg);
		return $(`#${id}`);
	}
	return null;
}

/** @param {string} id */
function clearHttpErrorWhenValid(id) {
	const el = $input(`#${id}`);
	// Stryker disable next-line ConditionalExpression: this is only wired to fields the form always renders (tf-url/tf-repo/at-url), so `el` is never null — defensive guard.
	if (!el) return;
	el.addEventListener("input", () => {
		// Stryker disable next-line MethodExpression: these are type="url" inputs, which strip surrounding whitespace, so the value is already trimmed — equivalent.
		const value = el.value.trim();
		if (!value || isHttpUrl(value)) clearFieldError(id);
	});
}

function duplicateRegion() {
	return `<section class="dupes" data-dupes aria-labelledby="dupes-title" aria-live="polite" hidden>
		<h3 class="dupes__title" id="dupes-title">Possible duplicates</h3>
		<p class="dupes__note">These existing tools look similar — check before creating a duplicate.</p>
		<ul class="dupes__list" data-dupes-list></ul>
	</section>`;
}

/** @param {Tool} t */
function renderDuplicateItem(t) {
	const title = t.title || t.name;
	const maintainer = t.maintainer || (t.authors && t.authors[0]) || "Unknown maintainer";
	return `<li class="dupes__item">
		<a href="${esc(toolHref(t.name))}">
			<span class="dupes__name"${dirAttrs(title)}>${esc(title)}</span>
			<span class="dupes__meta">by <span${dirAttrs(maintainer)}>${esc(maintainer)}</span></span>
		</a>
	</li>`;
}

/** @param {Tool[]} tools */
function renderDuplicates(tools) {
	const box = $("[data-dupes]");
	const list = $("[data-dupes-list]");
	// Stryker disable next-line ConditionalExpression,LogicalOperator: the duplicate region (with both elements) is always present on the create form where suggestions run — defensive guard.
	if (!box || !list) return;
	if (tools.length === 0) {
		list.innerHTML = "";
		box.hidden = true;
		return;
	}
	list.innerHTML = tools.map((tool) => renderDuplicateItem(tool)).join("");
	box.hidden = false;
}

/**
 * @param {() => void} fn
 * @param {number} wait
 * @returns {() => void}
 */
function debounce(fn, wait) {
	let timer = 0;
	return () => {
		window.clearTimeout(timer);
		timer = window.setTimeout(fn, wait);
	};
}

function setupDuplicateSuggestions() {
	const titleEl = document.querySelector("#tf-title");
	const keywordsEl = document.querySelector("#tf-keywords");
	// Stryker disable next-line ConditionalExpression,LogicalOperator: setupDuplicateSuggestions runs only on the create form, which always renders both fields — defensive guard.
	if (!titleEl || !keywordsEl) return;
	/** @type {Promise<any> | null} */
	let indexPromise = null;
	const loadIndex = () => {
		if (!indexPromise) indexPromise = getSimilarityIndex();
		return indexPromise;
	};
	const update = debounce(async () => {
		const typedTitle = fieldValue("tf-title");
		const typedName = normStr(fieldValue("tf-name"));
		const keywords = fromCsv(fieldValue("tf-keywords"));
		const toolType = fieldValue("tf-type");
		if (!typedTitle && keywords.length === 0 && !toolType) {
			renderDuplicates([]);
			return;
		}
		let index;
		try {
			index = await loadIndex();
		} catch {
			// Swallow: a failed load leaves `index` undefined and the guard below renders empty duplicates.
		}
		if (!index || !Array.isArray(index.tools)) {
			renderDuplicates([]);
			return;
		}
		/** @type {Set<string>} */
		const seen = new Set();
		/** @type {Tool[]} */
		const candidates = [];
		const add = (/** @type {Tool} */ tool) => {
			// Stryker disable next-line ConditionalExpression,LogicalOperator: candidates come from the similarity index / nearestNeighbors, which only yield real tools with names — defensive guard.
			if (!tool || !tool.name) return;
			if (typedName && normStr(tool.name) === typedName) return;
			if (seen.has(tool.name)) return;
			seen.add(tool.name);
			candidates.push(tool);
		};
		const titleNeedle = normStr(typedTitle);
		if (titleNeedle) {
			for (const tool of index.tools) {
				const titleText = normStr(tool.title);
				const nameText = normStr(tool.name);
				if (titleText.includes(titleNeedle) || nameText.includes(titleNeedle)) add(tool);
			}
		}
		const partial = { keywords, forWikis: [], audiences: [], tasks: [], toolType };
		for (const item of nearestNeighbors(/** @type {Tool} */ (/** @type {unknown} */ (partial)), index, 5)) {
			add(item.tool);
		}
		renderDuplicates(candidates.slice(0, 5));
	}, 300);
	titleEl.addEventListener("input", update);
	keywordsEl.addEventListener("input", update);
	const typeEl = document.querySelector("#tf-type");
	// Stryker disable next-line ConditionalExpression: the create form always renders the #tf-type select, so this guard is always true — defensive.
	if (typeEl) typeEl.addEventListener("change", update);
}

// EXPERIMENTAL — create/edit a tool's CORE fields. name=null → create.
// Edits overload the live record; new tools live only in the browser.
/** @param {string | null} name */
export async function viewToolForm(name) {
	const editing = name !== null && name !== undefined;
	let cur = /** @type {Tool} */ (
		// Stryker disable next-line ObjectLiteral: this blank draft is only used in create mode, where every field renders as an empty control, so `{}` yields an identical form — equivalent.
		/** @type {unknown} */ ({
			// Stryker disable next-line StringLiteral: in create mode the name field is rendered from its own literal, so this `name` value is never read — equivalent.
			name: "",
			title: "",
			description: "",
			url: "",
			repository: null,
			license: null,
			toolType: null,
			keywords: [],
			forWikis: [],
			uiLanguages: [],
			deprecated: false,
			experimental: false
		})
	);
	if (editing) {
		const fetched = await getTool(name);
		if (!fetched) return viewNotFound();
		cur = fetched;
	}
	const crawlerOwned = Boolean(cur.origin) && cur.origin !== "api";
	const isCrawler = editing && crawlerOwned;
	const html = `
	<div class="container page le">
		<a class="back" href="${editing ? toolHref(name) : "/add-or-remove-tools"}">← Back</a>
		<h1 class="page__title">${editing ? "Edit tool" : "Submit a tool"} <span class="exp-badge">Experimental</span></h1>
		<p class="page__intro">Changes are saved only in this browser — see <a href="/rules-of-engagement">Rules of Engagement</a>.
		${isCrawler ? "In production, core fields of crawler-imported tools are owned by the maintainer's <code>toolinfo.json</code>; only <code>origin=api</code> tools are core-editable. This demo lets you edit anyway." : ""}</p>
		<form data-tool-form novalidate>
			<h2 class="le__h2">Core information</h2>
			${editing ? `<p class="le__ro">Name: <code>${esc(name)}</code></p>` : fInput("Name (unique id)", "tf-name", "", { req: true, ph: "my-cool-tool", max: 120, hint: "Stable lowercase id used in Toolhub URLs; it cannot be changed later." })}
			${fInput("Title", "tf-title", cur.title, { req: true, hint: "Short public name shown in search results and tool pages." })}
			${fArea("Description", "tf-desc", cur.description, "One or two useful sentences: what it does, who it helps, and when to use it.")}
			${fInput("URL", "tf-url", cur.url, { req: true, type: "url", ph: "https://…", hint: "Primary place people launch the tool or read its documentation." })}
			${fInput("Source code repository", "tf-repo", cur.repository, { type: "url", hint: "Optional public repository where contributors can inspect or patch the code." })}
			${fInput("License (SPDX id)", "tf-license", cur.license, { ph: "GPL-3.0-or-later", hint: "Use an SPDX identifier when known; leave blank if the license is unknown." })}
			${fSelect("Tool type", "tf-type", cur.toolType, TOOL_TYPES, { hint: "Choose the closest match; community annotations can refine discovery later." })}
			${fInput("Keywords (comma-separated)", "tf-keywords", toCsv(cur.keywords), { hint: "Search terms people may try; avoid repeating only the title." })}
			${editing ? "" : duplicateRegion()}
			${fInput("Works on wikis (comma-separated, * for all)", "tf-wikis", toCsv(cur.forWikis), { hint: "Use wiki database names such as enwiki or commonswiki, or * for all wikis." })}
			${fInput("Available UI languages (comma-separated codes)", "tf-langs", toCsv(cur.uiLanguages), { ph: "en, fr, de", hint: "BCP-47 / wiki language codes; saved values refresh the tool page immediately in this demo." })}
			<div class="le__checks">${fCheck("Deprecated", "tf-deprecated", cur.deprecated)}${fCheck("Experimental", "tf-experimental", cur.experimental)}</div>
			<div class="le__actions">
				${button(editing ? "Save changes" : "Submit tool", { variant: "primary", type: "submit" })}
				${editing && !isNewTool(name) ? button("Revert demo edits", { variant: "danger", cls: "le__delete", attrs: "data-tf-revert" }) : ""}
				${editing && isNewTool(name) ? button("Delete submission", { variant: "danger", cls: "le__delete", attrs: "data-tf-delete" }) : ""}
			</div>
		</form>
	</div>`;
	function mount() {
		/** @type {HTMLElement} */ ($("[data-tool-form]")).addEventListener("submit", (e) => {
			e.preventDefault();
			const title = fieldValue("tf-title"),
				url = fieldValue("tf-url"),
				desc = fieldValue("tf-desc");
			const tname = editing ? name : fieldValue("tf-name");
			const invalidUrl = validateHttpField("tf-url", "Enter a valid http(s) URL.", { required: true });
			const invalidRepo = validateHttpField("tf-repo", "Enter a valid http(s) repository URL.");
			if (!tname || !title) {
				/** @type {HTMLElement} */ ($(editing ? "#tf-title" : "#tf-name")).focus();
				return;
			}
			if (invalidUrl || invalidRepo) {
				/** @type {HTMLElement} */ (invalidUrl || invalidRepo).focus();
				return;
			}
			if (!editing && isNewTool(tname)) {
				setFieldError("tf-name", "A demo tool with that name already exists.");
				/** @type {HTMLElement} */ ($("#tf-name")).focus();
				return;
			}
			const fields = {
				title,
				description: desc,
				url,
				repository: fieldValue("tf-repo") || null,
				license: fieldValue("tf-license") || null,
				toolType: fieldValue("tf-type") || null,
				keywords: fromCsv(fieldValue("tf-keywords")),
				forWikis: fromCsv(fieldValue("tf-wikis")),
				uiLanguages: fromCsv(fieldValue("tf-langs")),
				deprecated: checkedValue("tf-deprecated"),
				experimental: checkedValue("tf-experimental")
			};
			if (editing && !isNewTool(tname)) {
				const m = toolEditsMap();
				m[tname] = fields;
				demoStore.set(DEMO_KEYS.toolEdits, m);
				logActivity("edited", tname, title);
			} else {
				const m = toolNewMap();
				m[tname] = fields;
				demoStore.set(DEMO_KEYS.toolNew, m);
				logActivity(editing ? "edited" : "created", tname, title);
			}
			navigateTo(toolHref(tname));
		});
		const rev = $("[data-tf-revert]");
		if (rev) {
			rev.addEventListener("click", () => {
				const m = toolEditsMap();
				delete m[/** @type {string} */ (name)];
				demoStore.set(DEMO_KEYS.toolEdits, m);
				navigateTo(toolHref(/** @type {string} */ (name)));
			});
		}
		const del = $("[data-tf-delete]");
		if (del) {
			del.addEventListener("click", () => {
				const m = toolNewMap();
				delete m[/** @type {string} */ (name)];
				demoStore.set(DEMO_KEYS.toolNew, m);
				navigateTo("/add-or-remove-tools");
			});
		}
		clearHttpErrorWhenValid("tf-url");
		clearHttpErrorWhenValid("tf-repo");
		if (!editing) setupDuplicateSuggestions();
	}
	return { title: `${editing ? "Edit tool" : "Submit a tool"} — Toolhub`, html, mount };
}

// EXPERIMENTAL — add/remove tools: submissions + crawler-URL register + JSON ingest.
export function viewAddTools() {
	function urlRows() {
		const u = crawlerUrls();
		return u.length > 0
			? u
					.map(
						(/** @type {{ url: string }} */ x) =>
							`<li><code class="at__url">${esc(x.url)}</code> ${iconButton("close", "Remove URL", { size: "sm", cls: "at__rm", attrs: `data-url-rm="${esc(x.url)}"` })}</li>`
					)
					.join("")
			: '<li class="le__empty">No URLs registered.</li>';
	}
	function subGrid() {
		const cards = /** @type {Tool[]} */ (Object.keys(toolNewMap()).map((n) => newToolBase(n)));
		return cards.length > 0
			? grid("grid-tools", cards, (/** @type {Tool} */ t) => toolCard(t))
			: '<p class="empty">No tools yet. Submit one above, or ingest sample toolinfo.</p>';
	}
	// Stryker disable next-line StringLiteral: button() defaults variant to "outline", so "" renders identical markup — equivalent.
	const registerBtn = button("Register", { variant: "outline", type: "submit" });
	// Stryker disable next-line StringLiteral: button() defaults variant to "outline", so "" renders identical markup — equivalent.
	const loadSampleBtn = button("Load sample", { variant: "outline", attrs: "data-sample" });
	const html = `
	<div class="container page at">
		<div class="section-head"><h1 class="page__title">Add or remove tools <span class="exp-badge">Experimental</span></h1>
			${button("Submit a tool", { variant: "primary", href: "/tools/create", icon: "add" })}</div>
		<p class="page__intro">Register a <code>toolinfo.json</code> URL, or paste/ingest toolinfo to add records.
		Everything stays in this browser — see <a href="/rules-of-engagement">Rules of Engagement</a>.</p>

		<h2 class="le__h2">Register a toolinfo.json URL</h2>
		<form class="le__add" data-url-form novalidate>
			${fInput("toolinfo.json URL", "at-url", "", { type: "url", ph: "https://example.org/toolinfo.json", hint: "Full public URL the crawler should re-read, usually ending in toolinfo.json." })}
			${registerBtn}
		</form>
		<ul class="at__urls" data-url-list>${urlRows()}</ul>

		<h2 class="le__h2">Ingest toolinfo</h2>
		${fArea("Toolinfo JSON", "at-json", "", "Paste one tool object or an array; successful entries appear below in Your tools.", { rows: 10, max: false, cls: "at__json", ph: '{ "name": "my-tool", "title": "My Tool", "description": "…", "url": "https://…" }' })}
		<div class="le__actions">
			${button("Ingest", { variant: "primary", attrs: "data-ingest" })}
			${loadSampleBtn}
		</div>
		<p class="at__result" data-ingest-result aria-live="polite"></p>

		<h2 class="le__h2">Your tools <span class="le__count" data-sub-count></span></h2>
		<div data-sub-grid>${subGrid()}</div>
	</div>`;
	function mount() {
		/** @type {HTMLElement} */ ($("[data-url-form]")).addEventListener("submit", (e) => {
			e.preventDefault();
			// Stryker disable next-line MethodExpression: #at-url is a type="url" input, which strips surrounding whitespace, so the value is already trimmed — equivalent.
			const u = /** @type {HTMLInputElement} */ ($input("#at-url")).value.trim();
			const invalidUrl = validateHttpField("at-url", "Enter a valid http(s) toolinfo URL.");
			if (invalidUrl) {
				invalidUrl.focus();
				return;
			}
			if (!u) return;
			crawlerUrlAdd(u);
			/** @type {HTMLInputElement} */ ($input("#at-url")).value = "";
			clearFieldError("at-url");
			/** @type {HTMLElement} */ ($("[data-url-list]")).innerHTML = urlRows();
		});
		/** @type {HTMLElement} */ ($("[data-url-list]")).addEventListener("click", (e) => {
			const b = /** @type {EventTarget} */ (e.target).closest("[data-url-rm]");
			if (!b) return;
			crawlerUrlDelete(/** @type {string} */ (b.getAttribute("data-url-rm")));
			/** @type {HTMLElement} */ ($("[data-url-list]")).innerHTML = urlRows();
		});
		/** @type {HTMLElement} */ ($("[data-sample]")).addEventListener("click", () => {
			/** @type {HTMLInputElement} */ ($input("#at-json")).value = SAMPLE_TOOLINFO;
		});
		/** @type {HTMLElement} */ ($("[data-ingest]")).addEventListener("click", () => {
			const res = ingestToolinfo(/** @type {HTMLInputElement} */ ($input("#at-json")).value.trim());
			const out = /** @type {HTMLElement} */ ($("[data-ingest-result]"));
			if (res.error) {
				out.className = "at__result at__result--err";
				out.textContent = res.error;
				return;
			}
			const errors = res.errors || [];
			const parts = [];
			if (res.added) parts.push(`${res.added} added`);
			if (res.updated) parts.push(`${res.updated} updated`);
			out.className = `at__result${errors.length > 0 && parts.length === 0 ? " at__result--err" : " at__result--ok"}`;
			out.textContent =
				(parts.join(", ") || "Nothing ingested") + (errors.length > 0 ? ` · ${errors.join("; ")}` : "");
			/** @type {HTMLElement} */ ($("[data-sub-grid]")).innerHTML = subGrid();
			const c = $("[data-sub-count]");
			// Stryker disable next-line ConditionalExpression: the [data-sub-count] element is always present in this view, so the guard is always true — defensive.
			if (c) c.textContent = countLabel(Object.keys(toolNewMap()).length, "tool", "tools");
		});
		clearHttpErrorWhenValid("at-url");
	}
	return { title: "Add or remove tools — Toolhub", html, mount };
}

// EXPERIMENTAL — edit a tool's COMMUNITY ANNOTATIONS (overlay on live record).
/** @param {string} name */
export async function viewAnnotationsEdit(name) {
	const fetched = await getTool(name);
	if (!fetched) return viewNotFound();
	const cur = fetched;
	const html = `
	<div class="container page le">
		<a class="back" href="${toolHref(name)}">← Back to ${esc(cur.title)}</a>
		<h1 class="page__title">Edit annotations <span class="exp-badge">Experimental</span></h1>
		<p class="page__intro">Community annotations enrich a tool without touching its core data. Saved only in
		this browser — see <a href="/rules-of-engagement">Rules of Engagement</a>.</p>
		<form data-anno-form>
			<h2 class="le__h2">Community annotations for <span${dirAttrs(cur.title)}>${esc(cur.title)}</span></h2>
			${fInput("Audiences (comma-separated)", "an-aud", toCsv(cur.audiences), { hint: "User groups this tool serves, such as editors, admins, researchers, or developers." })}
			${fInput("Tasks (comma-separated)", "an-tasks", toCsv(cur.tasks), { hint: "Workflows this tool supports, such as editing, patrolling, importing, or analysis." })}
			${fSelect("Tool type", "an-type", cur.toolType, TOOL_TYPES, { hint: "Community classification used for discovery when core metadata is sparse." })}
			${fInput("Icon (Commons File: URL)", "an-icon", cur.icon, { type: "url", hint: "Optional Commons-hosted image URL for visual identification." })}
			<div class="le__actions">
				${button("Save annotations", { variant: "primary", type: "submit" })}
				${toolAnnosMap()[name] ? button("Revert annotations", { variant: "danger", cls: "le__delete", attrs: "data-an-revert" }) : ""}
			</div>
		</form>
	</div>`;
	function mount() {
		/** @type {HTMLElement} */ ($("[data-anno-form]")).addEventListener("submit", (e) => {
			e.preventDefault();
			const anno = {
				audiences: fromCsv(fieldValue("an-aud")),
				tasks: fromCsv(fieldValue("an-tasks")),
				toolType: fieldValue("an-type") || null,
				icon: fieldValue("an-icon") || null
			};
			const m = toolAnnosMap();
			m[name] = anno;
			demoStore.set(DEMO_KEYS.toolAnnos, m);
			logActivity("annotated", name, cur.title);
			navigateTo(toolHref(name));
		});
		const rev = $("[data-an-revert]");
		if (rev) {
			rev.addEventListener("click", () => {
				const m = toolAnnosMap();
				delete m[name];
				demoStore.set(DEMO_KEYS.toolAnnos, m);
				navigateTo(toolHref(name));
			});
		}
	}
	return { title: `Edit annotations — Toolhub`, html, mount };
}
