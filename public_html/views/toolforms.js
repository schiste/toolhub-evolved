// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $input, dirAttrs, esc } from "../lib/core/dom.js";
import { countLabel, t } from "../lib/core/i18n.js";
import {
	backendErrorMessage,
	backendGetJson,
	clearApiCache,
	getTool,
	isNewTool,
	newToolBase
} from "../lib/core/api.js";
import { navigateTo, toolHref } from "../lib/core/routing.js";
import { officialWrite, officialWriteAvailable } from "../lib/core/serversync.js";
import { getSimilarityIndex, nearestNeighbors } from "../lib/core/similarity.js";
import { normStr } from "../lib/core/util.js";
import {
	DEMO_KEYS,
	SOURCE,
	SYNC_STATUS,
	crawlerUrlAdd,
	crawlerUrlDelete,
	crawlerUrls,
	demoStore,
	fromCsv,
	ingestToolinfo,
	logActivity,
	stampSyncMeta,
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
import { fieldProvenance, syncBadge, syncState, syncStatusPanel } from "../lib/molecules/sync-status.js";
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
 * @param {any} res
 * @returns {Record<string, any>}
 */
function lifecycleMeta(res) {
	const local = res && typeof res.local === "object" ? res.local : {};
	const syncStatus =
		local.syncStatus ||
		res?.syncStatus ||
		(res?.result === SYNC_STATUS.official ? SYNC_STATUS.official : SYNC_STATUS.localFallback);
	/** @type {Record<string, any>} */
	const meta = {
		source: local.source || (syncStatus === SYNC_STATUS.official ? SOURCE.official : SOURCE.local),
		syncStatus,
		lastSyncedAt: local.lastSyncedAt || res?.lastSyncedAt,
		lastError: local.lastError || res?.lastError,
		toolhubResponse: local.toolhubResponse || res?.toolhubResponse,
		validationErrors: local.validationErrors || res?.validationErrors,
		officialId: local.officialId,
		officialName: local.officialName,
		visibility: local.visibility,
		reviewStatus: local.reviewStatus
	};
	for (const key of Object.keys(meta)) if (meta[key] === undefined) delete meta[key];
	return meta;
}

/**
 * @returns {Record<string, any>}
 */
function readToolFormFields() {
	return {
		title: fieldValue("tf-title"),
		description: fieldValue("tf-desc"),
		url: fieldValue("tf-url"),
		repository: fieldValue("tf-repo") || null,
		license: fieldValue("tf-license") || null,
		toolType: fieldValue("tf-type") || null,
		keywords: fromCsv(fieldValue("tf-keywords")),
		forWikis: fromCsv(fieldValue("tf-wikis")),
		uiLanguages: fromCsv(fieldValue("tf-langs")),
		deprecated: checkedValue("tf-deprecated"),
		experimental: checkedValue("tf-experimental")
	};
}

/**
 * @param {string} html
 * @param {string} label
 * @param {Record<string, any> | null} meta
 * @returns {string}
 */
function withFieldProvenance(html, label, meta) {
	return meta ? `<div class="sync-field-wrap">${html}${fieldProvenance(label, meta)}</div>` : html;
}

/**
 * @param {Record<string, any>} cur
 * @param {string | null} name
 * @param {boolean} editing
 * @param {boolean} existingOfficialTool
 * @returns {Record<string, any> | null}
 */
function toolCoreMeta(cur, name, editing, existingOfficialTool) {
	if (!editing) return null;
	if (name && isNewTool(name)) {
		return {
			syncStatus: cur.syncStatus || SYNC_STATUS.localDraft,
			lastError: cur.lastError,
			validationErrors: cur.validationErrors,
			reviewStatus: cur.reviewStatus
		};
	}
	const edit = name ? toolEditsMap()[name] : null;
	if (cur.edited || edit) {
		return {
			syncStatus: cur.editSyncStatus || edit?.syncStatus || SYNC_STATUS.localDraft,
			lastError: cur.editLastError || edit?.lastError,
			validationErrors: cur.editValidationErrors || edit?.validationErrors,
			reviewStatus: cur.editReviewStatus || edit?.reviewStatus
		};
	}
	return existingOfficialTool ? { syncStatus: SYNC_STATUS.official } : null;
}

/**
 * @param {string} name
 * @param {Record<string, any>} fields
 * @param {boolean} editing
 * @param {Record<string, any>} [meta]
 * @param {{ log?: boolean }} [options]
 */
function saveLocalToolDraft(name, fields, editing, meta = {}, options = {}) {
	const stamped = stampSyncMeta(
		{ ...fields, visibility: "private" },
		{ source: SOURCE.local, syncStatus: SYNC_STATUS.localFallback, ...meta }
	);
	if (editing && !isNewTool(name)) {
		const m = toolEditsMap();
		m[name] = stamped;
		demoStore.set(DEMO_KEYS.toolEdits, m);
		if (options.log !== false) logActivity("edited", name, fields.title);
		return;
	}
	const m = toolNewMap();
	m[name] = stamped;
	demoStore.set(DEMO_KEYS.toolNew, m);
	if (options.log !== false) logActivity(editing ? "edited" : "created", name, fields.title);
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
 * @param {Record<string, any>} [meta]
 */
function saveLocalAnnotationDraft(name, anno, meta = {}) {
	const m = toolAnnosMap();
	m[name] = stampSyncMeta(anno, { source: SOURCE.local, syncStatus: SYNC_STATUS.localFallback, ...meta });
	demoStore.set(DEMO_KEYS.toolAnnos, m);
}

/** @param {string} name */
function clearLocalAnnotationDraft(name) {
	const m = toolAnnosMap();
	delete m[name];
	demoStore.set(DEMO_KEYS.toolAnnos, m);
}

/** @param {string | null} name */
function setupToolCoreRetry(name) {
	const retry = $("[data-tf-retry]");
	if (!retry || !name) return;
	retry.addEventListener("click", async () => {
		const kind = retry.getAttribute("data-tf-retry") || "edit";
		const out = /** @type {HTMLElement} */ ($("[data-official-result]"));
		out.className = "at__result";
		out.textContent = t("toolforms.publishingToToolhub", "Publishing to official Toolhub…");
		try {
			const res = await officialWrite("POST", `/v1/write/tools/${encodeURIComponent(name)}/retry/`, { kind });
			if (res?.result === SYNC_STATUS.localFallback) {
				saveLocalToolDraft(name, readToolFormFields(), kind === "edit", lifecycleMeta(res), { log: false });
				out.className = "at__result at__result--err";
				out.textContent = t(
					"toolforms.officialWriteFailed",
					"Official Toolhub did not accept the write. Saved locally in Evolved instead: {msg}",
					{ msg: res.lastError || t("toolforms.unknownOfficialError", "Unknown Toolhub error") }
				);
				return;
			}
			clearLocalToolDraft(name);
			clearApiCache();
			navigateTo(toolHref(name));
		} catch (error) {
			out.className = "at__result at__result--err";
			out.textContent = t(
				"toolforms.officialWriteFailedNoDraft",
				"Official Toolhub did not accept the write: {msg}",
				{
					msg: backendErrorMessage(error)
				}
			);
		}
	});
}

/** @param {string} name */
function setupAnnotationRetry(name) {
	const retry = $("[data-an-retry]");
	if (!retry) return;
	retry.addEventListener("click", async () => {
		const out = /** @type {HTMLElement} */ ($("[data-official-result]"));
		out.className = "at__result";
		out.textContent = t("toolforms.publishingToToolhub", "Publishing to official Toolhub…");
		try {
			const res = await officialWrite("POST", `/v1/write/tools/${encodeURIComponent(name)}/retry/`, {
				kind: "annotations"
			});
			if (res?.result === SYNC_STATUS.localFallback) {
				const anno = {
					audiences: fromCsv(fieldValue("an-aud")),
					tasks: fromCsv(fieldValue("an-tasks")),
					toolType: fieldValue("an-type") || null,
					icon: fieldValue("an-icon") || null
				};
				saveLocalAnnotationDraft(name, anno, lifecycleMeta(res));
				out.className = "at__result at__result--err";
				out.textContent = t(
					"toolforms.officialWriteFailed",
					"Official Toolhub did not accept the write. Saved locally in Evolved instead: {msg}",
					{ msg: res.lastError || t("toolforms.unknownOfficialError", "Unknown Toolhub error") }
				);
				return;
			}
			clearLocalAnnotationDraft(name);
			clearApiCache();
			navigateTo(toolHref(name));
		} catch (error) {
			out.className = "at__result at__result--err";
			out.textContent = t(
				"toolforms.officialWriteFailedNoDraft",
				"Official Toolhub did not accept the write: {msg}",
				{
					msg: backendErrorMessage(error)
				}
			);
		}
	});
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

function toolhubSignInRequiredMessage() {
	return t("toolforms.signInRequired", "Toolhub sign-in is required before saving changes.");
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
	const hasLocalToolEdit = editing && name ? Boolean(toolEditsMap()[name]) || Boolean(cur.edited) : false;
	const coreMeta = toolCoreMeta(cur, name, editing, existingOfficialTool);
	const coreState = coreMeta ? syncState(coreMeta) : null;
	const coreRetryAttrs =
		editing && coreState?.retryAvailable && officialWriteAvailable()
			? `data-tf-retry="${isNewTool(/** @type {string} */ (name)) ? "new" : "edit"}"`
			: "";
	const coreDiscardAttrs =
		editing && isNewTool(/** @type {string} */ (name))
			? "data-tf-delete"
			: hasLocalToolEdit
				? "data-tf-revert"
				: "";
	const coreStatusPanel = coreMeta
		? syncStatusPanel(coreMeta, {
				title: t("toolforms.coreWriteStatus", "Core field write status"),
				retryAttrs: coreRetryAttrs,
				discardAttrs: coreDiscardAttrs,
				discardLabel: editing
					? t("toolforms.discardLocalCore", "Discard local core fields")
					: t("toolforms.discardLocalCopy", "Discard local copy")
			})
		: "";
	const html = `
	<div class="container page le">
		<a class="back" href="${editing ? toolHref(name) : "/add-or-remove-tools"}">${t("toolforms.back", "← Back")}</a>
		<h1 class="page__title">${editing ? t("toolforms.editTool", "Edit tool") : t("toolforms.submitATool", "Submit a tool")} <span class="exp-badge">${t("toolforms.experimentalBadge", "Experimental")}</span></h1>
		<p class="page__intro">${t("toolforms.introSaved", "Signed-in changes are published to official Toolhub when permitted; otherwise they are saved locally in Evolved — see")} <a href="/rules-of-engagement">${t("toolforms.rulesOfEngagement", "Rules of Engagement")}</a>.
		${isCrawler ? t("toolforms.crawlerOwnedNote", "Core fields of crawler-imported tools are owned by the maintainer's toolinfo.json; only origin=api tools are core-editable in official Toolhub.") : ""}</p>
		<form data-tool-form novalidate>
			<h2 class="le__h2">${t("toolforms.coreInformation", "Core information")}</h2>
			${coreStatusPanel}
			${editing ? `<p class="le__ro">${t("toolforms.nameLabel", "Name:")} <code>${esc(name)}</code>${coreMeta ? fieldProvenance(t("toolforms.fieldNameShort", "Name"), coreMeta) : ""}</p>` : fInput(t("toolforms.fieldName", "Name (unique id)"), "tf-name", "", { req: true, ph: "my-cool-tool", max: 120, hint: t("toolforms.fieldNameHint", "Stable lowercase id used in Toolhub URLs; it cannot be changed later.") })}
			${withFieldProvenance(fInput(t("toolforms.fieldTitle", "Title"), "tf-title", cur.title, { req: true, hint: t("toolforms.fieldTitleHint", "Short public name shown in search results and tool pages.") }), t("toolforms.fieldTitle", "Title"), coreMeta)}
			${withFieldProvenance(fArea(t("toolforms.fieldDescription", "Description"), "tf-desc", cur.description, t("toolforms.fieldDescriptionHint", "One or two useful sentences: what it does, who it helps, and when to use it.")), t("toolforms.fieldDescription", "Description"), coreMeta)}
			${withFieldProvenance(fInput(t("toolforms.fieldUrl", "URL"), "tf-url", cur.url, { req: true, type: "url", ph: "https://…", hint: t("toolforms.fieldUrlHint", "Primary place people launch the tool or read its documentation.") }), t("toolforms.fieldUrl", "URL"), coreMeta)}
			${withFieldProvenance(fInput(t("toolforms.fieldRepository", "Source code repository"), "tf-repo", cur.repository, { type: "url", hint: t("toolforms.fieldRepositoryHint", "Optional public repository where contributors can inspect or patch the code.") }), t("toolforms.fieldRepository", "Source code repository"), coreMeta)}
			${withFieldProvenance(fInput(t("toolforms.fieldLicense", "License (SPDX id)"), "tf-license", cur.license, { ph: "GPL-3.0-or-later", hint: t("toolforms.fieldLicenseHint", "Use an SPDX identifier when known; leave blank if the license is unknown.") }), t("toolforms.fieldLicenseShort", "License"), coreMeta)}
			${withFieldProvenance(fSelect(t("toolforms.fieldToolType", "Tool type"), "tf-type", cur.toolType, TOOL_TYPES, { hint: t("toolforms.fieldToolTypeHint", "Choose the closest match; community annotations can refine discovery later.") }), t("toolforms.fieldToolType", "Tool type"), coreMeta)}
			${withFieldProvenance(fInput(t("toolforms.fieldKeywords", "Keywords (comma-separated)"), "tf-keywords", toCsv(cur.keywords), { hint: t("toolforms.fieldKeywordsHint", "Search terms people may try; avoid repeating only the title.") }), t("toolforms.fieldKeywordsShort", "Keywords"), coreMeta)}
			${editing ? "" : duplicateRegion()}
			${withFieldProvenance(fInput(t("toolforms.fieldWikis", "Works on wikis (comma-separated, * for all)"), "tf-wikis", toCsv(cur.forWikis), { hint: t("toolforms.fieldWikisHint", "Use wiki hostnames such as en.wikipedia.org, commons.wikimedia.org, *.wikisource.org, or * for all wikis.") }), t("toolforms.fieldWikisShort", "Works on wikis"), coreMeta)}
			${withFieldProvenance(fInput(t("toolforms.fieldLangs", "Available UI languages (comma-separated codes)"), "tf-langs", toCsv(cur.uiLanguages), { ph: "en, fr, de", hint: t("toolforms.fieldLangsHint", "BCP-47 / wiki language codes; saved values refresh the tool page after saving.") }), t("toolforms.fieldLangsShort", "Interface languages"), coreMeta)}
			<div class="le__checks">${fCheck(t("toolforms.fieldDeprecated", "Deprecated"), "tf-deprecated", cur.deprecated)}${fCheck(t("toolforms.experimentalBadge", "Experimental"), "tf-experimental", cur.experimental)}</div>
			<div class="le__actions">
				${button(editing ? t("toolforms.saveChanges", "Save changes") : t("toolforms.submitTool", "Submit tool"), { variant: "primary", type: "submit" })}
				${existingOfficialTool && officialWriteAvailable() ? button(t("toolforms.deleteOfficialTool", "Delete official tool"), { variant: "danger", cls: "le__delete", attrs: "data-tf-official-delete" }) : ""}
			</div>
			<p class="at__result" data-official-result aria-live="polite"></p>
		</form>
	</div>`;
	function mount() {
		/** @type {HTMLElement} */ ($("[data-tool-form]")).addEventListener("submit", async (e) => {
			e.preventDefault();
			const title = fieldValue("tf-title");
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
				setFieldError(
					"tf-name",
					t("toolforms.errDuplicateName", "An Evolved-local tool with that name already exists.")
				);
				/** @type {HTMLElement} */ ($("#tf-name")).focus();
				return;
			}
			const fields = readToolFormFields();
			const out = /** @type {HTMLElement} */ ($("[data-official-result]"));
			if (officialWriteAvailable()) {
				out.className = "at__result";
				out.textContent = t("toolforms.publishingToToolhub", "Publishing to official Toolhub…");
				try {
					const res = await officialWrite(
						editing ? "PUT" : "POST",
						editing ? `/v1/write/tools/${encodeURIComponent(tname)}/` : "/v1/write/tools/",
						officialToolPayload(tname, fields, { includeName: !editing })
					);
					if (res?.result === SYNC_STATUS.localFallback) {
						saveLocalToolDraft(tname, fields, editing, lifecycleMeta(res), { log: false });
						out.className = "at__result at__result--err";
						out.textContent = t(
							"toolforms.officialWriteFailed",
							"Official Toolhub did not accept the write. Saved locally in Evolved instead: {msg}",
							{ msg: res.lastError || t("toolforms.unknownOfficialError", "Unknown Toolhub error") }
						);
						return;
					}
					clearLocalToolDraft(tname);
					clearApiCache();
					navigateTo(toolHref(tname));
					return;
				} catch (error) {
					const msg = backendErrorMessage(error);
					out.className = "at__result at__result--err";
					out.textContent = t(
						"toolforms.officialWriteFailedNoDraft",
						"Official Toolhub did not accept the write: {msg}",
						{
							msg
						}
					);
					return;
				}
			}
			out.className = "at__result at__result--err";
			out.textContent = toolhubSignInRequiredMessage();
		});
		setupToolCoreRetry(name);
		const rev = $("[data-tf-revert]");
		if (rev) {
			rev.addEventListener("click", async () => {
				if (officialWriteAvailable()) {
					await officialWrite(
						"DELETE",
						`/v1/write/tools/${encodeURIComponent(/** @type {string} */ (name))}/fallback/`,
						{
							kind: "edit"
						}
					).catch(() => undefined);
				}
				const m = toolEditsMap();
				delete m[/** @type {string} */ (name)];
				demoStore.set(DEMO_KEYS.toolEdits, m);
				navigateTo(toolHref(/** @type {string} */ (name)));
			});
		}
		const del = $("[data-tf-delete]");
		if (del) {
			del.addEventListener("click", async () => {
				if (officialWriteAvailable()) {
					await officialWrite(
						"DELETE",
						`/v1/write/tools/${encodeURIComponent(/** @type {string} */ (name))}/fallback/`,
						{
							kind: "new"
						}
					).catch(() => undefined);
				}
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
						`/v1/write/tools/${encodeURIComponent(/** @type {string} */ (name))}/`
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
							msg: backendErrorMessage(error)
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
						(
							/** @type {{ url: string, id?: number, officialId?: number, syncStatus?: string, syncLabel?: string, lastError?: string }} */ x
						) => {
							const officialId = x.officialId ?? x.id;
							const localId = /** @type {{ localId?: number }} */ (x).localId;
							const state = syncState(x);
							const retryButton =
								state.retryAvailable && localId && officialWriteAvailable()
									? button(t("toolforms.retryUrl", "Retry"), {
											size: "sm",
											icon: "upload",
											attrs: `data-url-retry="${localId}" data-url-retry-url="${esc(x.url)}"`
										})
									: "";
							return `<li><code class="at__url">${esc(x.url)}</code> ${syncBadge(x)}${state.retryAvailable ? ` <span class="sync-badge sync-badge--retry">${t("syncStatus.retryAvailable", "Retry available")}</span>` : ""}${x.lastError ? ` <span class="at__url-error">${esc(x.lastError)}</span>` : ""} ${retryButton} ${iconButton("close", t("toolforms.removeUrl", "Remove URL"), { size: "sm", cls: "at__rm", attrs: `data-url-rm="${esc(x.url)}"${officialId ? ` data-url-id="${officialId}"` : ""}${localId ? ` data-url-local-id="${localId}"` : ""}` })}</li>`;
						}
					)
					.join("")
			: `<li class="le__empty">${t("toolforms.noUrls", "No URLs registered.")}</li>`;
	}
	function subGrid() {
		const cards = /** @type {Tool[]} */ (Object.keys(toolNewMap()).map((n) => newToolBase(n)));
		return cards.length > 0
			? grid("grid-tools", cards, (/** @type {Tool} */ t) => toolCard(t))
			: `<p class="empty">${t("toolforms.noToolsYet", "No tools yet. Submit one above, or ingest toolinfo.")}</p>`;
	}
	/** @param {Array<Record<string, any>>} runs */
	function crawlerRunRows(runs) {
		if (runs.length === 0) {
			return `<p class="empty">${t("toolforms.noCrawlerRuns", "No local crawler runs recorded yet.")}</p>`;
		}
		return `<ol class="feed feed--compact">${runs
			.map((run) => {
				const status = run.ok ? t("toolforms.crawlerRunOk", "OK") : t("toolforms.crawlerRunErrors", "Errors");
				const errors = Array.isArray(run.errors) && run.errors.length > 0 ? ` · ${esc(run.errors[0])}` : "";
				return `<li><span>${status} · ${t(
					"toolforms.crawlerRunCounts",
					"{urls} URLs, {added} added, {updated} updated",
					{
						urls: String(run.urlsCount || 0),
						added: String(run.added || 0),
						updated: String(run.updated || 0)
					}
				)}${errors}</span><span class="feed__when">${esc(run.endedAt || run.startedAt || "")}</span></li>`;
			})
			.join("")}</ol>`;
	}
	// Stryker disable next-line StringLiteral: button() defaults variant to "outline", so "" renders identical markup — equivalent.
	const registerBtn = button(t("toolforms.register", "Register"), { variant: "outline", type: "submit" });
	const html = `
	<div class="container page at">
		<div class="section-head"><h1 class="page__title">${t("toolforms.addOrRemoveTools", "Add or remove tools")} <span class="exp-badge">${t("toolforms.experimentalBadge", "Experimental")}</span></h1>
			${button(t("toolforms.submitATool", "Submit a tool"), { variant: "primary", href: "/tools/create", icon: "add" })}</div>
		<p class="page__intro">${t("toolforms.ingestIntroLead", "Register a")} <code>toolinfo.json</code> ${t("toolforms.ingestIntroTail", "URL, or paste toolinfo to add records.")}
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
		</div>
		<p class="at__result" data-ingest-result aria-live="polite"></p>

		<h2 class="le__h2">${t("toolforms.yourToolsTitle", "Your tools")} <span class="le__count" data-sub-count></span></h2>
		<div data-sub-grid>${subGrid()}</div>
		<h2 class="le__h2">${t("toolforms.localCrawlerRunsTitle", "Local crawler runs")}</h2>
		<div data-crawler-runs>${crawlerRunRows([])}</div>
	</div>`;
	function mount() {
		backendGetJson("/v1/crawler/runs/")
			.then((data) => {
				const box = $("[data-crawler-runs]");
				if (box) box.innerHTML = crawlerRunRows(Array.isArray(data?.results) ? data.results : []);
				return undefined;
			})
			.catch(() => undefined);
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
			if (officialWriteAvailable()) {
				out.className = "at__result";
				out.textContent = t("toolforms.publishingToToolhub", "Publishing to official Toolhub…");
				try {
					const res = await officialWrite("POST", "/v1/write/crawler/urls/", { url: u });
					const local = res?.local || {};
					const officialId =
						local.officialId ??
						(res?.result === SYNC_STATUS.official && typeof res?.toolhub?.id === "number"
							? res.toolhub.id
							: undefined);
					const meta = lifecycleMeta(res);
					if (typeof local.localId === "number") meta.localId = local.localId;
					crawlerUrlAdd(local.url || u, officialId, meta);
					if (res?.result === SYNC_STATUS.localFallback) {
						out.className = "at__result at__result--err";
						out.textContent = t(
							"toolforms.officialWriteFailed",
							"Official Toolhub did not accept the write. Saved locally in Evolved instead: {msg}",
							{ msg: res.lastError || t("toolforms.unknownOfficialError", "Unknown Toolhub error") }
						);
					} else {
						out.className = "at__result at__result--ok";
						out.textContent = t("toolforms.officialUrlRegistered", "Registered with official Toolhub.");
					}
				} catch (error) {
					const msg = backendErrorMessage(error);
					out.className = "at__result at__result--err";
					out.textContent = t(
						"toolforms.officialWriteFailedNoDraft",
						"Official Toolhub did not accept the write: {msg}",
						{
							msg
						}
					);
					return;
				}
			} else {
				out.className = "at__result at__result--err";
				out.textContent = toolhubSignInRequiredMessage();
				return;
			}
			/** @type {HTMLInputElement} */ ($input("#at-url")).value = "";
			clearFieldError("at-url");
			/** @type {HTMLElement} */ ($("[data-url-list]")).innerHTML = urlRows();
		});
		/** @type {HTMLElement} */ ($("[data-url-list]")).addEventListener("click", async (e) => {
			const retry = /** @type {EventTarget} */ (e.target).closest("[data-url-retry]");
			if (retry) {
				const localId = retry.getAttribute("data-url-retry");
				const url = retry.getAttribute("data-url-retry-url") || "";
				const out = /** @type {HTMLElement} */ ($("[data-ingest-result]"));
				if (!localId) return;
				out.className = "at__result";
				out.textContent = t("toolforms.publishingToToolhub", "Publishing to official Toolhub…");
				try {
					const res = await officialWrite(
						"POST",
						`/v1/write/crawler/urls/${encodeURIComponent(localId)}/retry/`
					);
					const local = res?.local || {};
					const officialId =
						local.officialId ??
						(res?.result === SYNC_STATUS.official && typeof res?.toolhub?.id === "number"
							? res.toolhub.id
							: undefined);
					const meta = lifecycleMeta(res);
					const parsedLocalId = Number(localId);
					if (typeof local.localId === "number") meta.localId = local.localId;
					else if (Number.isFinite(parsedLocalId)) meta.localId = parsedLocalId;
					crawlerUrlAdd(local.url || url, officialId, meta);
					out.className =
						res?.result === SYNC_STATUS.localFallback
							? "at__result at__result--err"
							: "at__result at__result--ok";
					out.textContent =
						res?.result === SYNC_STATUS.localFallback
							? t(
									"toolforms.officialWriteFailed",
									"Official Toolhub did not accept the write. Saved locally in Evolved instead: {msg}",
									{
										msg:
											res.lastError ||
											t("toolforms.unknownOfficialError", "Unknown Toolhub error")
									}
								)
							: t("toolforms.officialUrlRegistered", "Registered with official Toolhub.");
					/** @type {HTMLElement} */ ($("[data-url-list]")).innerHTML = urlRows();
				} catch (error) {
					out.className = "at__result at__result--err";
					out.textContent = t(
						"toolforms.officialWriteFailedNoDraft",
						"Official Toolhub did not accept the write: {msg}",
						{
							msg: backendErrorMessage(error)
						}
					);
				}
				return;
			}
			const b = /** @type {EventTarget} */ (e.target).closest("[data-url-rm]");
			if (!b) return;
			const officialId = b.getAttribute("data-url-id");
			const localId = b.getAttribute("data-url-local-id");
			if (officialWriteAvailable() && officialId) {
				officialWrite("DELETE", `/v1/write/crawler/urls/${officialId}/`).catch(() => {
					// Keep local removal responsive; the user can re-register if upstream delete failed.
				});
			} else if (officialWriteAvailable() && localId) {
				officialWrite("DELETE", `/v1/write/crawler/urls/${localId}/fallback/`).catch(() => undefined);
			}
			crawlerUrlDelete(/** @type {string} */ (b.getAttribute("data-url-rm")));
			/** @type {HTMLElement} */ ($("[data-url-list]")).innerHTML = urlRows();
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
	const annotationMeta = cur.annotated
		? {
				syncStatus: cur.annotationSyncStatus || SYNC_STATUS.localDraft,
				lastError: cur.annotationLastError,
				validationErrors: cur.annotationValidationErrors,
				reviewStatus: cur.annotationReviewStatus
			}
		: { syncStatus: SYNC_STATUS.official };
	const annotationState = syncState(annotationMeta);
	const annotationStatusPanel = syncStatusPanel(annotationMeta, {
		title: t("toolforms.annotationWriteStatus", "Annotation write status"),
		retryAttrs: annotationState.retryAvailable && officialWriteAvailable() ? "data-an-retry" : "",
		discardAttrs: toolAnnosMap()[name] ? "data-an-revert" : "",
		discardLabel: t("toolforms.discardLocalAnnotations", "Discard local annotations"),
		showIfOfficial: true
	});
	const html = `
	<div class="container page le">
		<a class="back" href="${toolHref(name)}">${t("toolforms.backToName", "← Back to {title}", { title: esc(cur.title) })}</a>
		<h1 class="page__title">${t("toolforms.editAnnotations", "Edit annotations")} <span class="exp-badge">${t("toolforms.experimentalBadge", "Experimental")}</span></h1>
		<p class="page__intro">${t("toolforms.annoIntro", "Community annotations enrich a tool without touching its core data. Signed-in changes publish to official Toolhub when permitted; rejected writes stay local to Evolved — see")} <a href="/rules-of-engagement">${t("toolforms.rulesOfEngagement", "Rules of Engagement")}</a>.</p>
		<form data-anno-form>
			<h2 class="le__h2">${t("toolforms.annoForTitle", "Community annotations for")} <span${dirAttrs(cur.title)}>${esc(cur.title)}</span></h2>
			${annotationStatusPanel}
			${withFieldProvenance(fInput(t("toolforms.fieldAudiences", "Audiences (comma-separated)"), "an-aud", toCsv(cur.audiences), { hint: t("toolforms.fieldAudiencesHint", "User groups this tool serves, such as editors, admins, researchers, or developers.") }), t("toolforms.fieldAudiencesShort", "Audiences"), annotationMeta)}
			${withFieldProvenance(fInput(t("toolforms.fieldTasks", "Tasks (comma-separated)"), "an-tasks", toCsv(cur.tasks), { hint: t("toolforms.fieldTasksHint", "Workflows this tool supports, such as editing, patrolling, importing, or analysis.") }), t("toolforms.fieldTasksShort", "Tasks"), annotationMeta)}
			${withFieldProvenance(fSelect(t("toolforms.fieldToolType", "Tool type"), "an-type", cur.toolType, TOOL_TYPES, { hint: t("toolforms.fieldAnnoToolTypeHint", "Community classification used for discovery when core metadata is sparse.") }), t("toolforms.fieldToolType", "Tool type"), annotationMeta)}
			${withFieldProvenance(fInput(t("toolforms.fieldIcon", "Icon (Commons File: URL)"), "an-icon", cur.icon, { type: "url", hint: t("toolforms.fieldIconHint", "Optional Commons-hosted image URL for visual identification.") }), t("toolforms.fieldIconShort", "Icon"), annotationMeta)}
			<div class="le__actions">
				${button(t("toolforms.saveAnnotations", "Save annotations"), { variant: "primary", type: "submit" })}
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
					const res = await officialWrite(
						"PUT",
						`/v1/write/tools/${encodeURIComponent(name)}/annotations/`,
						officialAnnotationPayload(anno)
					);
					if (res?.result === SYNC_STATUS.localFallback) {
						saveLocalAnnotationDraft(name, anno, lifecycleMeta(res));
						out.className = "at__result at__result--err";
						out.textContent = t(
							"toolforms.officialWriteFailed",
							"Official Toolhub did not accept the write. Saved locally in Evolved instead: {msg}",
							{ msg: res.lastError || t("toolforms.unknownOfficialError", "Unknown Toolhub error") }
						);
						return;
					}
					clearLocalAnnotationDraft(name);
					clearApiCache();
					navigateTo(toolHref(name));
					return;
				} catch (error) {
					const msg = backendErrorMessage(error);
					out.className = "at__result at__result--err";
					out.textContent = t(
						"toolforms.officialWriteFailedNoDraft",
						"Official Toolhub did not accept the write: {msg}",
						{
							msg
						}
					);
					return;
				}
			}
			out.className = "at__result at__result--err";
			out.textContent = toolhubSignInRequiredMessage();
		});
		setupAnnotationRetry(name);
		const rev = $("[data-an-revert]");
		if (rev) {
			rev.addEventListener("click", async () => {
				if (officialWriteAvailable()) {
					await officialWrite("DELETE", `/v1/write/tools/${encodeURIComponent(name)}/fallback/`, {
						kind: "annotations"
					}).catch(() => undefined);
				}
				const m = toolAnnosMap();
				delete m[name];
				demoStore.set(DEMO_KEYS.toolAnnos, m);
				navigateTo(toolHref(name));
			});
		}
	}
	return { title: `${t("toolforms.editAnnotations", "Edit annotations")} — Toolhub`, html, mount };
}
