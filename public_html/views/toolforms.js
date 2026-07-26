// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $input, dirAttrs, esc } from "../lib/core/dom.js";
import { countLabel, t } from "../lib/core/i18n.js";
import { BackendError, clearApiCache, getTool, isNewTool, newToolBase } from "../lib/core/api.js";
import { navigateTo, toolHref } from "../lib/core/routing.js";
import { officialWrite, officialWriteAvailable } from "../lib/core/serversync.js";
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

/** @param {string} value */
function isOfficialWikiTarget(value) {
	return /^(\*|(.*)?\.?(mediawiki|wikibooks|wikidata|wikimedia|wikinews|wikipedia|wikiquote|wikisource|wiktionary|wikiversity|wikivoyage)\.org)$/i.test(
		value
	);
}

/**
 * @param {string} id
 * @returns {HTMLElement | null}
 */
function validateWikiTargets(id) {
	clearFieldError(id);
	const bad = fromCsv(fieldValue(id)).find((value) => !isOfficialWikiTarget(value));
	if (bad) {
		setFieldError(
			id,
			t(
				"toolforms.errInvalidWikiTarget",
				"Use wiki hostnames such as en.wikipedia.org, commons.wikimedia.org, *.wikisource.org, or *."
			)
		);
		return $(`#${id}`);
	}
	return null;
}

/** @param {string} id */
function clearWikiErrorWhenValid(id) {
	const el = $input(`#${id}`);
	if (!el) return;
	el.addEventListener("input", () => {
		const bad = fromCsv(fieldValue(id)).find((value) => !isOfficialWikiTarget(value));
		if (!bad) clearFieldError(id);
	});
}

/** @param {unknown} error */
function officialErrorMessage(error) {
	if (error instanceof BackendError) {
		const body = error.body || {};
		const details = body.details || body;
		if (typeof details.message === "string") return details.message;
		if (typeof body.error === "string") return body.error;
		return JSON.stringify(details);
	}
	return error instanceof Error ? error.message : String(error);
}

/**
 * @param {string} name
 * @param {Record<string, any>} fields
 * @param {{ includeName?: boolean }} [options]
 * @returns {Record<string, any>}
 */
function officialToolPayload(name, fields, { includeName = true } = {}) {
	/** @type {Record<string, any>} */
	const payload = {
		title: fields.title,
		description: fields.description,
		url: fields.url,
		repository: fields.repository,
		license: fields.license,
		tool_type: fields.toolType,
		keywords: fields.keywords,
		for_wikis: fields.forWikis,
		available_ui_languages: fields.uiLanguages,
		deprecated: fields.deprecated,
		experimental: fields.experimental,
		comment: fields.comment || "Published from Toolhub Evolved"
	};
	if (includeName) payload.name = name;
	if (!payload.repository) delete payload.repository;
	if (!payload.license) delete payload.license;
	if (!payload.tool_type) delete payload.tool_type;
	return payload;
}

/**
 * @param {string} name
 * @param {Record<string, any>} fields
 * @param {boolean} editing
 */
function saveLocalToolDraft(name, fields, editing) {
	if (editing && !isNewTool(name)) {
		const m = toolEditsMap();
		m[name] = fields;
		demoStore.set(DEMO_KEYS.toolEdits, m);
		logActivity("edited", name, fields.title);
		return;
	}
	const m = toolNewMap();
	m[name] = fields;
	demoStore.set(DEMO_KEYS.toolNew, m);
	logActivity(editing ? "edited" : "created", name, fields.title);
}

/** @param {string} name */
function clearLocalToolDraft(name) {
	const edits = toolEditsMap();
	delete edits[name];
	demoStore.set(DEMO_KEYS.toolEdits, edits);
	const created = toolNewMap();
	delete created[name];
	demoStore.set(DEMO_KEYS.toolNew, created);
}

/**
 * @param {string} name
 * @param {Record<string, any>} anno
 */
function saveLocalAnnotationDraft(name, anno) {
	const m = toolAnnosMap();
	m[name] = anno;
	demoStore.set(DEMO_KEYS.toolAnnos, m);
}

/** @param {string} name */
function clearLocalAnnotationDraft(name) {
	const m = toolAnnosMap();
	delete m[name];
	demoStore.set(DEMO_KEYS.toolAnnos, m);
}

/** @param {Record<string, any>} anno */
function officialAnnotationPayload(anno) {
	const payload = {
		audiences: anno.audiences,
		tasks: anno.tasks,
		tool_type: anno.toolType,
		icon: anno.icon,
		comment: "Annotated from Toolhub Evolved"
	};
	if (!payload.tool_type) delete payload.tool_type;
	if (!payload.icon) delete payload.icon;
	return payload;
}

function duplicateRegion() {
	return `<section class="dupes" data-dupes aria-labelledby="dupes-title" aria-live="polite" hidden>
		<h3 class="dupes__title" id="dupes-title">${t("toolforms.dupesTitle", "Possible duplicates")}</h3>
		<p class="dupes__note">${t("toolforms.dupesNote", "These existing tools look similar — check before creating a duplicate.")}</p>
		<ul class="dupes__list" data-dupes-list></ul>
	</section>`;
}

/** @param {Tool} tool */
function renderDuplicateItem(tool) {
	const title = tool.title || tool.name;
	const maintainer =
		tool.maintainer || (tool.authors && tool.authors[0]) || t("toolforms.unknownMaintainer", "Unknown maintainer");
	return `<li class="dupes__item">
		<a href="${esc(toolHref(tool.name))}">
			<span class="dupes__name"${dirAttrs(title)}>${esc(title)}</span>
			<span class="dupes__meta">${t("toolforms.by", "by")} <span${dirAttrs(maintainer)}>${esc(maintainer)}</span></span>
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

// Create/edit a tool's CORE fields. With a Toolhub session this publishes to
// official Toolhub first; a rejected write is kept as an Evolved-local draft.
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
	const existingOfficialTool = editing && !isNewTool(name);
	const html = `
	<div class="container page le">
		<a class="back" href="${editing ? toolHref(name) : "/add-or-remove-tools"}">${t("toolforms.back", "← Back")}</a>
		<h1 class="page__title">${editing ? t("toolforms.editTool", "Edit tool") : t("toolforms.submitATool", "Submit a tool")} <span class="exp-badge">${t("toolforms.experimentalBadge", "Experimental")}</span></h1>
		<p class="page__intro">${t("toolforms.introSaved", "Signed-in changes are published to official Toolhub when permitted; otherwise they are saved locally in Evolved — see")} <a href="/rules-of-engagement">${t("toolforms.rulesOfEngagement", "Rules of Engagement")}</a>.
		${isCrawler ? "In production, core fields of crawler-imported tools are owned by the maintainer's <code>toolinfo.json</code>; only <code>origin=api</code> tools are core-editable. This demo lets you edit anyway." : ""}</p>
		<form data-tool-form novalidate>
			<h2 class="le__h2">${t("toolforms.coreInformation", "Core information")}</h2>
			${editing ? `<p class="le__ro">${t("toolforms.nameLabel", "Name:")} <code>${esc(name)}</code></p>` : fInput(t("toolforms.fieldName", "Name (unique id)"), "tf-name", "", { req: true, ph: "my-cool-tool", max: 120, hint: t("toolforms.fieldNameHint", "Stable lowercase id used in Toolhub URLs; it cannot be changed later.") })}
			${fInput(t("toolforms.fieldTitle", "Title"), "tf-title", cur.title, { req: true, hint: t("toolforms.fieldTitleHint", "Short public name shown in search results and tool pages.") })}
			${fArea(t("toolforms.fieldDescription", "Description"), "tf-desc", cur.description, t("toolforms.fieldDescriptionHint", "One or two useful sentences: what it does, who it helps, and when to use it."))}
			${fInput(t("toolforms.fieldUrl", "URL"), "tf-url", cur.url, { req: true, type: "url", ph: "https://…", hint: t("toolforms.fieldUrlHint", "Primary place people launch the tool or read its documentation.") })}
			${fInput(t("toolforms.fieldRepository", "Source code repository"), "tf-repo", cur.repository, { type: "url", hint: t("toolforms.fieldRepositoryHint", "Optional public repository where contributors can inspect or patch the code.") })}
			${fInput(t("toolforms.fieldLicense", "License (SPDX id)"), "tf-license", cur.license, { ph: "GPL-3.0-or-later", hint: t("toolforms.fieldLicenseHint", "Use an SPDX identifier when known; leave blank if the license is unknown.") })}
			${fSelect(t("toolforms.fieldToolType", "Tool type"), "tf-type", cur.toolType, TOOL_TYPES, { hint: t("toolforms.fieldToolTypeHint", "Choose the closest match; community annotations can refine discovery later.") })}
			${fInput(t("toolforms.fieldKeywords", "Keywords (comma-separated)"), "tf-keywords", toCsv(cur.keywords), { hint: t("toolforms.fieldKeywordsHint", "Search terms people may try; avoid repeating only the title.") })}
			${editing ? "" : duplicateRegion()}
			${fInput(t("toolforms.fieldWikis", "Works on wikis (comma-separated, * for all)"), "tf-wikis", toCsv(cur.forWikis), { hint: t("toolforms.fieldWikisHint", "Use wiki hostnames such as en.wikipedia.org, commons.wikimedia.org, *.wikisource.org, or * for all wikis.") })}
			${fInput(t("toolforms.fieldLangs", "Available UI languages (comma-separated codes)"), "tf-langs", toCsv(cur.uiLanguages), { ph: "en, fr, de", hint: t("toolforms.fieldLangsHint", "BCP-47 / wiki language codes; saved values refresh the tool page immediately in this demo.") })}
			<div class="le__checks">${fCheck(t("toolforms.fieldDeprecated", "Deprecated"), "tf-deprecated", cur.deprecated)}${fCheck(t("toolforms.experimentalBadge", "Experimental"), "tf-experimental", cur.experimental)}</div>
			<div class="le__actions">
				${button(editing ? t("toolforms.saveChanges", "Save changes") : t("toolforms.submitTool", "Submit tool"), { variant: "primary", type: "submit" })}
				${existingOfficialTool ? button(t("toolforms.revertDemoEdits", "Revert demo edits"), { variant: "danger", cls: "le__delete", attrs: "data-tf-revert" }) + (officialWriteAvailable() ? button(t("toolforms.deleteOfficialTool", "Delete official tool"), { variant: "danger", cls: "le__delete", attrs: "data-tf-official-delete" }) : "") : ""}
				${editing && isNewTool(name) ? button(t("toolforms.deleteSubmission", "Delete submission"), { variant: "danger", cls: "le__delete", attrs: "data-tf-delete" }) : ""}
			</div>
			<p class="at__result" data-official-result aria-live="polite"></p>
		</form>
	</div>`;
	function mount() {
		/** @type {HTMLElement} */ ($("[data-tool-form]")).addEventListener("submit", async (e) => {
			e.preventDefault();
			const title = fieldValue("tf-title"),
				url = fieldValue("tf-url"),
				desc = fieldValue("tf-desc");
			const tname = editing ? name : fieldValue("tf-name");
			const invalidUrl = validateHttpField("tf-url", t("toolforms.errInvalidUrl", "Enter a valid http(s) URL."), {
				required: true
			});
			const invalidRepo = validateHttpField(
				"tf-repo",
				t("toolforms.errInvalidRepoUrl", "Enter a valid http(s) repository URL.")
			);
			const invalidWikis = validateWikiTargets("tf-wikis");
			if (!tname || !title) {
				/** @type {HTMLElement} */ ($(editing ? "#tf-title" : "#tf-name")).focus();
				return;
			}
			if (invalidUrl || invalidRepo || invalidWikis) {
				/** @type {HTMLElement} */ (invalidUrl || invalidRepo || invalidWikis).focus();
				return;
			}
			if (!editing && isNewTool(tname)) {
				setFieldError("tf-name", t("toolforms.errDuplicateName", "A demo tool with that name already exists."));
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
			const out = /** @type {HTMLElement} */ ($("[data-official-result]"));
			if (officialWriteAvailable()) {
				out.className = "at__result";
				out.textContent = t("toolforms.publishingToToolhub", "Publishing to official Toolhub…");
				try {
					await officialWrite(
						editing ? "PUT" : "POST",
						editing ? `/v1/toolhub/tools/${encodeURIComponent(tname)}/` : "/v1/toolhub/tools/",
						officialToolPayload(tname, fields, { includeName: !editing })
					);
					clearLocalToolDraft(tname);
					clearApiCache();
					navigateTo(toolHref(tname));
					return;
				} catch (error) {
					saveLocalToolDraft(tname, fields, editing);
					out.className = "at__result at__result--err";
					out.textContent = t(
						"toolforms.officialWriteFailed",
						"Official Toolhub did not accept the write. Saved locally in Evolved instead: {msg}",
						{ msg: officialErrorMessage(error) }
					);
					return;
				}
			}
			saveLocalToolDraft(tname, fields, editing);
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
		const officialDel = $("[data-tf-official-delete]");
		if (officialDel) {
			officialDel.addEventListener("click", async () => {
				const out = /** @type {HTMLElement} */ ($("[data-official-result]"));
				out.className = "at__result";
				out.textContent = t("toolforms.publishingToToolhub", "Publishing to official Toolhub…");
				try {
					await officialWrite(
						"DELETE",
						`/v1/toolhub/tools/${encodeURIComponent(/** @type {string} */ (name))}/`
					);
					clearLocalToolDraft(/** @type {string} */ (name));
					clearApiCache();
					navigateTo("/add-or-remove-tools");
				} catch (error) {
					out.className = "at__result at__result--err";
					out.textContent = t(
						"toolforms.officialDeleteFailed",
						"Official Toolhub did not delete the tool: {msg}",
						{
							msg: officialErrorMessage(error)
						}
					);
				}
			});
		}
		clearHttpErrorWhenValid("tf-url");
		clearHttpErrorWhenValid("tf-repo");
		clearWikiErrorWhenValid("tf-wikis");
		if (!editing) setupDuplicateSuggestions();
	}
	return {
		title: `${editing ? t("toolforms.editTool", "Edit tool") : t("toolforms.submitATool", "Submit a tool")} — Toolhub`,
		html,
		mount
	};
}

// Add/remove tools: official crawler URL registration plus local toolinfo ingest.
export function viewAddTools() {
	function urlRows() {
		const u = crawlerUrls();
		return u.length > 0
			? u
					.map(
						(/** @type {{ url: string, id?: number }} */ x) =>
							`<li><code class="at__url">${esc(x.url)}</code> ${iconButton("close", t("toolforms.removeUrl", "Remove URL"), { size: "sm", cls: "at__rm", attrs: `data-url-rm="${esc(x.url)}"${x.id ? ` data-url-id="${x.id}"` : ""}` })}</li>`
					)
					.join("")
			: `<li class="le__empty">${t("toolforms.noUrls", "No URLs registered.")}</li>`;
	}
	function subGrid() {
		const cards = /** @type {Tool[]} */ (Object.keys(toolNewMap()).map((n) => newToolBase(n)));
		return cards.length > 0
			? grid("grid-tools", cards, (/** @type {Tool} */ t) => toolCard(t))
			: `<p class="empty">${t("toolforms.noToolsYet", "No tools yet. Submit one above, or ingest sample toolinfo.")}</p>`;
	}
	// Stryker disable next-line StringLiteral: button() defaults variant to "outline", so "" renders identical markup — equivalent.
	const registerBtn = button(t("toolforms.register", "Register"), { variant: "outline", type: "submit" });
	// Stryker disable next-line StringLiteral: button() defaults variant to "outline", so "" renders identical markup — equivalent.
	const loadSampleBtn = button(t("toolforms.loadSample", "Load sample"), {
		variant: "outline",
		attrs: "data-sample"
	});
	const html = `
	<div class="container page at">
		<div class="section-head"><h1 class="page__title">${t("toolforms.addOrRemoveTools", "Add or remove tools")} <span class="exp-badge">${t("toolforms.experimentalBadge", "Experimental")}</span></h1>
			${button(t("toolforms.submitATool", "Submit a tool"), { variant: "primary", href: "/tools/create", icon: "add" })}</div>
		<p class="page__intro">${t("toolforms.ingestIntroLead", "Register a")} <code>toolinfo.json</code> ${t("toolforms.ingestIntroTail", "URL, or paste/ingest toolinfo to add records.")}
		${t("toolforms.introEverything", "Signed-in URL registrations go to official Toolhub; pasted toolinfo stays local to Evolved — see")} <a href="/rules-of-engagement">${t("toolforms.rulesOfEngagement", "Rules of Engagement")}</a>.</p>

		<h2 class="le__h2">${t("toolforms.registerUrlTitle", "Register a toolinfo.json URL")}</h2>
		<form class="le__add" data-url-form novalidate>
			${fInput(t("toolforms.fieldToolinfoUrl", "toolinfo.json URL"), "at-url", "", { type: "url", ph: "https://example.org/toolinfo.json", hint: t("toolforms.fieldToolinfoUrlHint", "Full public URL the crawler should re-read, usually ending in toolinfo.json.") })}
			${registerBtn}
		</form>
		<ul class="at__urls" data-url-list>${urlRows()}</ul>

		<h2 class="le__h2">${t("toolforms.ingestToolinfoTitle", "Ingest toolinfo")}</h2>
		${fArea(t("toolforms.fieldToolinfoJson", "Toolinfo JSON"), "at-json", "", t("toolforms.fieldToolinfoJsonHint", "Paste one tool object or an array; successful entries appear below in Your tools."), { rows: 10, max: false, cls: "at__json", ph: '{ "name": "my-tool", "title": "My Tool", "description": "…", "url": "https://…" }' })}
		<div class="le__actions">
			${button(t("toolforms.ingest", "Ingest"), { variant: "primary", attrs: "data-ingest" })}
			${loadSampleBtn}
		</div>
		<p class="at__result" data-ingest-result aria-live="polite"></p>

		<h2 class="le__h2">${t("toolforms.yourToolsTitle", "Your tools")} <span class="le__count" data-sub-count></span></h2>
		<div data-sub-grid>${subGrid()}</div>
	</div>`;
	function mount() {
		/** @type {HTMLElement} */ ($("[data-url-form]")).addEventListener("submit", async (e) => {
			e.preventDefault();
			// Stryker disable next-line MethodExpression: #at-url is a type="url" input, which strips surrounding whitespace, so the value is already trimmed — equivalent.
			const u = /** @type {HTMLInputElement} */ ($input("#at-url")).value.trim();
			const invalidUrl = validateHttpField(
				"at-url",
				t("toolforms.errInvalidToolinfoUrl", "Enter a valid http(s) toolinfo URL.")
			);
			if (invalidUrl) {
				invalidUrl.focus();
				return;
			}
			if (!u) return;
			const out = /** @type {HTMLElement} */ ($("[data-ingest-result]"));
			let officialId;
			if (officialWriteAvailable()) {
				out.className = "at__result";
				out.textContent = t("toolforms.publishingToToolhub", "Publishing to official Toolhub…");
				try {
					const res = await officialWrite("POST", "/v1/toolhub/crawler/urls/", { url: u });
					officialId = res?.toolhub?.id;
					out.className = "at__result at__result--ok";
					out.textContent = t("toolforms.officialUrlRegistered", "Registered with official Toolhub.");
				} catch (error) {
					out.className = "at__result at__result--err";
					out.textContent = t(
						"toolforms.officialWriteFailed",
						"Official Toolhub did not accept the write. Saved locally in Evolved instead: {msg}",
						{ msg: officialErrorMessage(error) }
					);
				}
			}
			if (typeof officialId === "number") crawlerUrlAdd(u, officialId);
			else crawlerUrlAdd(u);
			/** @type {HTMLInputElement} */ ($input("#at-url")).value = "";
			clearFieldError("at-url");
			/** @type {HTMLElement} */ ($("[data-url-list]")).innerHTML = urlRows();
		});
		/** @type {HTMLElement} */ ($("[data-url-list]")).addEventListener("click", async (e) => {
			const b = /** @type {EventTarget} */ (e.target).closest("[data-url-rm]");
			if (!b) return;
			const officialId = b.getAttribute("data-url-id");
			if (officialWriteAvailable() && officialId) {
				officialWrite("DELETE", `/v1/toolhub/crawler/urls/${officialId}/`).catch(() => {
					// Keep local removal responsive; the user can re-register if upstream delete failed.
				});
			}
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
			if (res.added) parts.push(t("toolforms.nAdded", "{n} added", { n: res.added }));
			if (res.updated) parts.push(t("toolforms.nUpdated", "{n} updated", { n: res.updated }));
			out.className = `at__result${errors.length > 0 && parts.length === 0 ? " at__result--err" : " at__result--ok"}`;
			out.textContent =
				(parts.join(", ") || t("toolforms.nothingIngested", "Nothing ingested")) +
				(errors.length > 0 ? ` · ${errors.join("; ")}` : "");
			/** @type {HTMLElement} */ ($("[data-sub-grid]")).innerHTML = subGrid();
			const c = $("[data-sub-count]");
			// Stryker disable next-line ConditionalExpression: the [data-sub-count] element is always present in this view, so the guard is always true — defensive.
			if (c) {
				c.textContent = countLabel(
					Object.keys(toolNewMap()).length,
					t("toolforms.toolOne", "tool"),
					t("toolforms.toolOther", "tools")
				);
			}
		});
		clearHttpErrorWhenValid("at-url");
	}
	return { title: t("toolforms.addOrRemoveToolsDocTitle", "Add or remove tools — Toolhub"), html, mount };
}

// Edit a tool's COMMUNITY ANNOTATIONS. With a Toolhub session this writes
// official annotations first and falls back to the Evolved overlay if rejected.
/** @param {string} name */
export async function viewAnnotationsEdit(name) {
	const fetched = await getTool(name);
	if (!fetched) return viewNotFound();
	const cur = fetched;
	const html = `
	<div class="container page le">
		<a class="back" href="${toolHref(name)}">${t("toolforms.backToName", "← Back to {title}", { title: esc(cur.title) })}</a>
		<h1 class="page__title">${t("toolforms.editAnnotations", "Edit annotations")} <span class="exp-badge">${t("toolforms.experimentalBadge", "Experimental")}</span></h1>
		<p class="page__intro">${t("toolforms.annoIntro", "Community annotations enrich a tool without touching its core data. Signed-in changes publish to official Toolhub when permitted; rejected writes stay local to Evolved — see")} <a href="/rules-of-engagement">${t("toolforms.rulesOfEngagement", "Rules of Engagement")}</a>.</p>
		<form data-anno-form>
			<h2 class="le__h2">${t("toolforms.annoForTitle", "Community annotations for")} <span${dirAttrs(cur.title)}>${esc(cur.title)}</span></h2>
			${fInput(t("toolforms.fieldAudiences", "Audiences (comma-separated)"), "an-aud", toCsv(cur.audiences), { hint: t("toolforms.fieldAudiencesHint", "User groups this tool serves, such as editors, admins, researchers, or developers.") })}
			${fInput(t("toolforms.fieldTasks", "Tasks (comma-separated)"), "an-tasks", toCsv(cur.tasks), { hint: t("toolforms.fieldTasksHint", "Workflows this tool supports, such as editing, patrolling, importing, or analysis.") })}
			${fSelect(t("toolforms.fieldToolType", "Tool type"), "an-type", cur.toolType, TOOL_TYPES, { hint: t("toolforms.fieldAnnoToolTypeHint", "Community classification used for discovery when core metadata is sparse.") })}
			${fInput(t("toolforms.fieldIcon", "Icon (Commons File: URL)"), "an-icon", cur.icon, { type: "url", hint: t("toolforms.fieldIconHint", "Optional Commons-hosted image URL for visual identification.") })}
			<div class="le__actions">
				${button(t("toolforms.saveAnnotations", "Save annotations"), { variant: "primary", type: "submit" })}
				${toolAnnosMap()[name] ? button(t("toolforms.revertAnnotations", "Revert annotations"), { variant: "danger", cls: "le__delete", attrs: "data-an-revert" }) : ""}
			</div>
			<p class="at__result" data-official-result aria-live="polite"></p>
		</form>
	</div>`;
	function mount() {
		/** @type {HTMLElement} */ ($("[data-anno-form]")).addEventListener("submit", async (e) => {
			e.preventDefault();
			const anno = {
				audiences: fromCsv(fieldValue("an-aud")),
				tasks: fromCsv(fieldValue("an-tasks")),
				toolType: fieldValue("an-type") || null,
				icon: fieldValue("an-icon") || null
			};
			const out = /** @type {HTMLElement} */ ($("[data-official-result]"));
			if (officialWriteAvailable()) {
				out.className = "at__result";
				out.textContent = t("toolforms.publishingToToolhub", "Publishing to official Toolhub…");
				try {
					await officialWrite(
						"PUT",
						`/v1/toolhub/tools/${encodeURIComponent(name)}/annotations/`,
						officialAnnotationPayload(anno)
					);
					clearLocalAnnotationDraft(name);
					clearApiCache();
					navigateTo(toolHref(name));
					return;
				} catch (error) {
					saveLocalAnnotationDraft(name, anno);
					logActivity("annotated", name, cur.title);
					out.className = "at__result at__result--err";
					out.textContent = t(
						"toolforms.officialWriteFailed",
						"Official Toolhub did not accept the write. Saved locally in Evolved instead: {msg}",
						{ msg: officialErrorMessage(error) }
					);
					return;
				}
			}
			saveLocalAnnotationDraft(name, anno);
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
	return { title: `${t("toolforms.editAnnotations", "Edit annotations")} — Toolhub`, html, mount };
}
