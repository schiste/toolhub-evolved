// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $input, dirAttrs, esc, isHttpUrl, textAttrs } from "../lib/core/dom.js";
import { fmt, t } from "../lib/core/i18n.js";
import {
	backendErrorExplanation,
	backendErrorBody,
	backendGetJson,
	clearApiCache,
	getTool,
	isNewTool,
	newToolBase
} from "../lib/core/api.js";
import { navigateTo, toolHref } from "../lib/core/routing.js";
import {
	lifecycleMeta as baseLifecycleMeta,
	officialWrite,
	officialWriteAvailable,
	serverWrite
} from "../lib/core/serversync.js";
import { getSimilarityIndex, nearestNeighbors } from "../lib/core/similarity.js";
import { fromCsv, normStr, toCsv } from "../lib/core/util.js";
import {
	DEMO_KEYS,
	SOURCE,
	SYNC_STATUS,
	clearLocalToolDraft,
	crawlerUrlAdd,
	crawlerUrlDelete,
	crawlerUrls,
	demoStore,
	ingestToolinfo,
	logActivity,
	stampSyncMeta,
	toolAnnosMap,
	toolEditsMap,
	toolNewMap
} from "../lib/core/store.js";
import { iconMeta } from "../lib/atoms/avatar.js";
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
import { mountChangeReview, shouldProceedWithFieldChanges } from "../lib/molecules/change-review.js";
import {
	fieldProvenance,
	syncBadge,
	syncState,
	syncStatusPanel,
	validationErrorMessages
} from "../lib/molecules/sync-status.js";
import { accountSection } from "../lib/organisms/account-workbench.js";
import { grid } from "../lib/organisms/grid.js";
import { toolCard } from "../lib/organisms/tool-card.js";
import { viewNotFound } from "./static.js";

/**
 * @param {string} id
 * @param {string} msg
 * @param {{ required?: boolean, httpsOnly?: boolean }} [opts]
 * @returns {HTMLElement | null}
 */
function validateHttpField(id, msg, opts = {}) {
	const value = fieldValue(id);
	clearFieldError(id);
	if ((opts.required || value) && (!isHttpUrl(value) || (opts.httpsOnly && !String(value).startsWith("https://")))) {
		setFieldError(id, msg);
		return $(`#${id}`);
	}
	return null;
}

/** @param {string} value */
function looksLikeToolinfoUrl(value) {
	try {
		return new URL(value).pathname.replace(/\/+$/, "").endsWith("/toolinfo.json");
	} catch {
		return false;
	}
}

/**
 * @param {string} id
 * @param {{ httpsOnly?: boolean }} [opts]
 */
function clearHttpErrorWhenValid(id, opts = {}) {
	const el = $input(`#${id}`);
	// Stryker disable next-line ConditionalExpression: this is only wired to fields the form always renders (tf-url/tf-repo/at-url), so `el` is never null — defensive guard.
	if (!el) return;
	el.addEventListener("input", () => {
		// Stryker disable next-line MethodExpression: these are type="url" inputs, which strip surrounding whitespace, so the value is already trimmed — equivalent.
		const value = el.value.trim();
		if (!value || (isHttpUrl(value) && (!opts.httpsOnly || value.startsWith("https://")))) clearFieldError(id);
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
 * @param {unknown} error
 * @param {string[]} fields
 * @returns {string}
 */
function backendFieldError(error, fields) {
	const body = backendErrorBody(error);
	const validationErrors = body?.validationErrors;
	if (!Array.isArray(validationErrors)) return "";
	const wanted = new Set(fields);
	for (const item of validationErrors) {
		if (!item || typeof item !== "object") continue;
		const record = /** @type {Record<string, any>} */ (item);
		const field = String(record.field || record.name || "");
		if (!wanted.has(field)) continue;
		const messages = validationErrorMessages(item);
		if (messages.length === 0) return "";
		const prefix = `${field}: `;
		return messages[0].startsWith(prefix) ? messages[0].slice(prefix.length) : messages[0];
	}
	return "";
}

/**
 * @param {unknown} error
 * @param {Record<string, string[]>} fieldMap
 */
function applyBackendFieldErrors(error, fieldMap) {
	for (const [id, fields] of Object.entries(fieldMap)) {
		const message = backendFieldError(error, fields);
		if (!message) continue;
		setFieldError(id, message);
		const el = $(`#${id}`);
		if (el) el.focus();
		return;
	}
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
	if (includeName && fields.toolinfoUrl) payload.toolinfo_url = fields.toolinfoUrl;
	if (!payload.repository) delete payload.repository;
	if (!payload.license) delete payload.license;
	if (!payload.tool_type) delete payload.tool_type;
	return payload;
}

const TOOL_LIFECYCLE_KEYS = ["officialName", "visibility", "reviewStatus"];

/** @param {any} res */
function lifecycleMeta(res) {
	return baseLifecycleMeta(res, TOOL_LIFECYCLE_KEYS);
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
		experimental: checkedValue("tf-experimental"),
		toolinfoUrl: fieldValue("tf-toolinfo-url") || null
	};
}

/** @param {Tool} current @param {Record<string, any>} fields */
function localCurationPatch(current, fields) {
	const pairs = [
		["title", current.title, fields.title],
		["description", current.description, fields.description],
		["url", current.url, fields.url],
		["repository", current.repository || "", fields.repository || ""],
		["license", current.license || "", fields.license || ""],
		["tool_type", current.toolType || "", fields.toolType || ""],
		["keywords", current.keywords || [], fields.keywords],
		["for_wikis", current.forWikis || [], fields.forWikis],
		["available_ui_languages", current.uiLanguages || [], fields.uiLanguages]
	];
	return Object.fromEntries(
		pairs
			.filter(([_key, before, after]) => JSON.stringify(before) !== JSON.stringify(after))
			.map(([key, _before, after]) => [key, after])
	);
}

/**
 * @param {Tool} current
 * @param {Record<string, any>} fields
 * @returns {import("../lib/molecules/change-review.js").ChangeDescriptor[]}
 */
function toolCoreChangeDescriptors(current, fields) {
	return /** @type {import("../lib/molecules/change-review.js").ChangeDescriptor[]} */ ([
		{ key: "title", label: t("toolforms.fieldTitle", "Title"), before: current.title, after: fields.title },
		{
			key: "description",
			label: t("toolforms.fieldDescription", "Description"),
			before: current.description,
			after: fields.description
		},
		{ key: "url", label: t("toolforms.fieldUrl", "URL"), before: current.url, after: fields.url },
		{
			key: "repository",
			label: t("toolforms.fieldRepository", "Source code repository"),
			before: current.repository,
			after: fields.repository
		},
		{
			key: "license",
			label: t("toolforms.fieldLicenseShort", "License"),
			before: current.license,
			after: fields.license
		},
		{
			key: "toolType",
			label: t("toolforms.fieldToolType", "Tool type"),
			before: current.toolType,
			after: fields.toolType
		},
		{
			key: "keywords",
			label: t("toolforms.fieldKeywordsShort", "Keywords"),
			before: current.keywords,
			after: fields.keywords,
			type: "set"
		},
		{
			key: "forWikis",
			label: t("toolforms.fieldWikisShort", "Works on wikis"),
			before: current.forWikis,
			after: fields.forWikis,
			type: "set"
		},
		{
			key: "uiLanguages",
			label: t("toolforms.fieldLangsShort", "Interface languages"),
			before: current.uiLanguages,
			after: fields.uiLanguages,
			type: "set"
		},
		{
			key: "deprecated",
			label: t("toolforms.fieldDeprecated", "Deprecated"),
			before: current.deprecated,
			after: fields.deprecated,
			type: "boolean"
		},
		{
			key: "experimental",
			label: t("toolforms.experimentalBadge", "Experimental"),
			before: current.experimental,
			after: fields.experimental,
			type: "boolean"
		}
	]);
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
 * Add catalog evidence beside an editable field without conflating it with
 * the separate official-write status shown by fieldProvenance().
 * @param {string} html
 * @param {string} label
 * @param {Record<string, any> | null} writeMeta
 * @param {Record<string, any> | null | undefined} projection
 * @param {string} field
 */
function withCatalogFieldProvenance(html, label, writeMeta, projection, field) {
	const wrapped = withFieldProvenance(html, label, writeMeta);
	const rows = Array.isArray(projection?.provenance?.[field]) ? projection.provenance[field] : [];
	if (rows.length === 0) return wrapped;
	const effective = rows.find((row) => row.effective) || rows[0];
	const sources = new Set(rows.map((row) => String(row.source || "")).filter(Boolean));
	const invalid = rows.filter((row) => row.valid === false).length;
	const reachability = projection?.validation?.[field]?.reachable;
	const sourceLabels = {
		official_toolhub: t("toolforms.sourceOfficial", "Official Toolhub"),
		official_toolinfo: t("toolforms.sourceRegisteredToolinfo", "registered toolinfo.json"),
		self_hosted_toolinfo: t("toolforms.sourceDiscoveredToolinfo", "discovered toolinfo.json"),
		repository_analysis: t("toolforms.sourceRepositoryAnalysis", "repository analysis"),
		evolved_curation: t("toolforms.sourceEvolvedCuration", "reviewed Evolved correction")
	};
	const source =
		/** @type {Record<string, string>} */ (sourceLabels)[effective.source] ||
		effective.source ||
		t("toolforms.sourceUnknown", "unknown source");
	const note = [
		t("toolforms.effectiveSource", "Effective source: $1", source),
		sources.size > 1
			? t(
					"toolforms.supportingSourceCount",
					"$1 {{PLURAL:$1|supporting source type|supporting source types}}",
					sources.size
				)
			: "",
		invalid ? t("toolforms.invalidEvidenceCount", "$1 invalid value(s) retained as evidence", invalid) : "",
		reachability === false ? t("toolforms.effectiveUrlUnreachable", "effective URL currently unreachable") : ""
	]
		.filter(Boolean)
		.join(" · ");
	return `${wrapped}<p class="field__hint catalog-field-evidence">${esc(note)}</p>`;
}

/**
 * @param {Record<string, any>} tool
 * @returns {string}
 */
function authorDisplayValue(tool) {
	const authors = Array.isArray(tool.authors) ? tool.authors : [];
	return [...new Set([...authors, tool.maintainer].filter(Boolean))].join(", ");
}

/**
 * @param {Record<string, any>} tool
 * @param {Record<string, any> | null} meta
 * @returns {string}
 */
function crawlerAuthorField(tool, meta) {
	const value = authorDisplayValue(tool) || t("toolforms.unknownMaintainer", "Unknown maintainer");
	const label = t("toolforms.fieldAuthors", "Author(s)");
	const hintId = "tf-authors-hint";
	const developerSettingsLink = `<a href="/developer-settings">${esc(t("toolforms.developerSettings", "Developer settings"))}</a>`;
	const myToolsLink = `<a href="/my-tools">${esc(t("toolforms.myTools", "My tools"))}</a>`;
	const hint = t(
		"toolforms.fieldAuthorsCrawlerHint",
		"Author data for crawled tools comes from the maintainer's toolinfo.json and official Toolhub. Update the source toolinfo.json to change it; Evolved verification is managed in $1 and $2.",
		developerSettingsLink,
		myToolsLink
	);
	const field = `<label class="le__label">${esc(label)}
		 <span class="le__hint" id="${hintId}">${hint}</span>
		<input class="le__input" id="tf-authors" type="text" value="${esc(value)}" disabled${dirAttrs(value)} aria-describedby="${hintId}" /></label>`;
	return withFieldProvenance(field, t("toolforms.fieldAuthorsShort", "Author(s)"), meta);
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
			reviewStatus: cur.reviewStatus,
			toolhubResponse: cur.toolhubResponse,
			toolhubStatus: cur.toolhubStatus,
			toolhubCode: cur.toolhubCode,
			origin: cur.origin
		};
	}
	const edit = name ? toolEditsMap()[name] : null;
	if (cur.edited || edit) {
		return {
			syncStatus: cur.editSyncStatus || edit?.syncStatus || SYNC_STATUS.localDraft,
			lastError: cur.editLastError || edit?.lastError,
			validationErrors: cur.editValidationErrors || edit?.validationErrors,
			reviewStatus: cur.editReviewStatus || edit?.reviewStatus,
			toolhubResponse: cur.editToolhubResponse || edit?.toolhubResponse,
			toolhubStatus: cur.editToolhubStatus || edit?.toolhubStatus,
			toolhubCode: cur.editToolhubCode || edit?.toolhubCode,
			origin: cur.origin
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

/** @returns {{ audiences: string[], tasks: string[], toolType: string | null, icon: string | null }} */
function readAnnotationFormFields() {
	return {
		audiences: fromCsv(fieldValue("an-aud")),
		tasks: fromCsv(fieldValue("an-tasks")),
		toolType: fieldValue("an-type") || null,
		icon: fieldValue("an-icon") || null
	};
}

/** @param {Tool} tool */
function iconProvenanceDiagnostic(tool) {
	const meta = iconMeta(tool);
	if (!meta.raw) return "";
	const isInvalid = meta.state === "invalid";
	const label =
		meta.state === "commons"
			? t("toolforms.iconSourceCommons", "Commons image")
			: meta.state === "direct"
				? t("toolforms.iconSourceDirect", "Direct image URL")
				: t("toolforms.iconSourceInvalid", "Generated avatar fallback");
	const detail =
		meta.state === "commons"
			? t("toolforms.iconSourceCommonsDetail", "Evolved normalized the supplied Commons file value.")
			: meta.state === "direct"
				? t("toolforms.iconSourceDirectDetail", "Evolved will load the supplied image URL.")
				: t(
						"toolforms.iconSourceInvalidDetail",
						"The supplied icon value is not a supported image URL; Evolved will show a generated avatar."
					);
	return `<div class="sync-field sync-field--icon" aria-label="${esc(t("toolforms.iconProvenance", "Icon provenance"))}"><span class="sync-badge sync-badge--${isInvalid ? "sync-error" : "official"}">${esc(label)}</span><span class="recent-table__muted">${esc(detail)}</span></div>`;
}

/**
 * @param {string} name
 * @param {{ audiences: string[], tasks: string[], toolType: string | null, icon: string | null }} anno
 * @param {any} res
 * @param {HTMLElement} out
 */
function saveAnnotationFallbackResult(name, anno, res, out) {
	saveLocalAnnotationDraft(name, anno, lifecycleMeta(res));
	out.className = "at__result at__result--err";
	out.textContent = t(
		"toolforms.officialWriteFailed",
		"Official Toolhub did not accept the write. Saved locally in Evolved instead: $1",
		backendErrorExplanation(res)
	);
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
					"Official Toolhub did not accept the write. Saved locally in Evolved instead: $1",
					backendErrorExplanation(res)
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
				"Official Toolhub did not accept the write: $1",
				backendErrorExplanation(error)
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
				saveAnnotationFallbackResult(name, readAnnotationFormFields(), res, out);
				return;
			}
			clearLocalAnnotationDraft(name);
			clearApiCache();
			navigateTo(toolHref(name));
		} catch (error) {
			out.className = "at__result at__result--err";
			out.textContent = t(
				"toolforms.officialWriteFailedNoDraft",
				"Official Toolhub did not accept the write: $1",
				backendErrorExplanation(error)
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

/**
 * @param {Tool} current
 * @param {{ audiences: string[], tasks: string[], toolType: string | null, icon: string | null }} anno
 * @returns {import("../lib/molecules/change-review.js").ChangeDescriptor[]}
 */
function annotationChangeDescriptors(current, anno) {
	return /** @type {import("../lib/molecules/change-review.js").ChangeDescriptor[]} */ ([
		{
			key: "audiences",
			label: t("toolforms.fieldAudiencesShort", "Audiences"),
			before: current.audiences,
			after: anno.audiences,
			type: "set"
		},
		{
			key: "tasks",
			label: t("toolforms.fieldTasksShort", "Tasks"),
			before: current.tasks,
			after: anno.tasks,
			type: "set"
		},
		{
			key: "toolType",
			label: t("toolforms.fieldToolType", "Tool type"),
			before: current.toolType,
			after: anno.toolType
		},
		{
			key: "icon",
			label: t("toolforms.fieldIconShort", "Icon"),
			before: current.icon,
			after: anno.icon
		}
	]);
}

function toolhubSignInRequiredMessage() {
	return t("toolforms.signInRequired", "Toolhub sign-in is required before saving changes.");
}

/**
 * @param {HTMLElement} out
 * @param {unknown} error
 * @param {Record<string, string[]>} [fieldMap]
 */
function showOfficialWriteFailure(out, error, fieldMap) {
	const msg = backendErrorExplanation(error);
	if (fieldMap) applyBackendFieldErrors(error, fieldMap);
	out.className = "at__result at__result--err";
	out.textContent = t("toolforms.officialWriteFailedNoDraft", "Official Toolhub did not accept the write: $1", msg);
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
			<span class="dupes__name"${textAttrs(title, tool.titleLanguage)}>${esc(title)}</span>
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

/**
 * @param {HTMLFormElement} form
 * @param {{ editing: boolean, name: string | null | undefined, current: Tool, changeReview: any }} options
 */
function setupToolCoreSubmit(form, { editing, name, current, changeReview }) {
	form.addEventListener("submit", async (e) => {
		e.preventDefault();
		const title = fieldValue("tf-title");
		const tname = editing ? /** @type {string} */ (name) : fieldValue("tf-name");
		const invalidUrl = validateHttpField("tf-url", t("toolforms.errInvalidUrl", "Enter a valid http(s) URL."), {
			required: true
		});
		const invalidRepo = validateHttpField(
			"tf-repo",
			t("toolforms.errInvalidRepoUrl", "Enter a valid http(s) repository URL.")
		);
		const invalidToolinfo = editing
			? null
			: validateHttpField(
					"tf-toolinfo-url",
					t("toolforms.errInvalidCreateToolinfoUrl", "Enter a valid https toolinfo URL."),
					{ httpsOnly: true }
				);
		const invalidWikis = validateWikiTargets("tf-wikis");
		if (!tname || !title) {
			/** @type {HTMLElement} */ ($(editing ? "#tf-title" : "#tf-name")).focus();
			return;
		}
		if (invalidUrl || invalidRepo || invalidToolinfo || invalidWikis) {
			/** @type {HTMLElement} */ (invalidUrl || invalidRepo || invalidToolinfo || invalidWikis).focus();
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
		const canOfficialWrite = officialWriteAvailable();
		if (
			editing &&
			canOfficialWrite &&
			!shouldProceedWithFieldChanges(changeReview, toolCoreChangeDescriptors(current, fields), out)
		) {
			return;
		}
		if (canOfficialWrite) {
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
						"Official Toolhub did not accept the write. Saved locally in Evolved instead: $1",
						backendErrorExplanation(res)
					);
					return;
				}
				clearLocalToolDraft(tname);
				clearApiCache();
				navigateTo(toolHref(tname));
				return;
			} catch (error) {
				showOfficialWriteFailure(out, error, {
					"tf-toolinfo-url": ["toolinfo_url", "toolinfoUrl"],
					"tf-url": ["url"]
				});
				return;
			}
		}
		out.className = "at__result at__result--err";
		out.textContent = toolhubSignInRequiredMessage();
	});
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
		editing && !crawlerOwned && coreState?.retryAvailable && officialWriteAvailable()
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
				guidance: isCrawler
					? t(
							"syncStatus.crawlerOwnedGuidance",
							"This tool is managed by a crawler. Update its public toolinfo.json source and wait for the next crawl; generic core-field edits are not accepted by official Toolhub."
						)
					: "",
				discardAttrs: coreDiscardAttrs,
				discardLabel: editing
					? t("toolforms.discardLocalCore", "Discard local core fields")
					: t("toolforms.discardLocalCopy", "Discard local copy")
			})
		: "";
	const createToolinfoField = editing
		? ""
		: `${fInput(t("toolforms.fieldToolinfoUrl", "toolinfo.json URL"), "tf-toolinfo-url", "", { type: "url", ph: "https://example.org/toolinfo.json", hint: t("toolforms.fieldCreateToolinfoUrlHint", "Optional: Evolved will fetch it now to fill missing fields and keep it registered for future crawler refreshes.") })}
			`;
	const localCurationControls = editing
		? `<fieldset class="panel catalog-curation"><legend>${t("toolforms.localCorrectionTitle", "Propose an Evolved correction")}</legend><p>${t("toolforms.localCorrectionIntro", "Submit the changed fields as a local proposal for reviewer approval. This does not modify Toolhub.")}</p>${fArea(t("toolforms.localCorrectionRationale", "Reason for the correction"), "tf-curation-rationale", "", t("toolforms.localCorrectionRationaleHint", "Explain the evidence or invalid value that this correction addresses."))}${button(t("toolforms.submitLocalCorrection", "Submit local correction"), { variant: "outline", type: "button", attrs: "data-tf-curation" })}<p class="at__result" data-curation-result aria-live="polite"></p></fieldset>`
		: "";
	const html = `
	<div class="container page le">
		<a class="back" href="${editing ? toolHref(name) : "/my-tools"}">${t("toolforms.back", "← Back")}</a>
		<h1 class="page__title">${editing ? t("toolforms.editTool", "Edit tool") : t("toolforms.submitATool", "Register a tool")} <span class="exp-badge">${t("toolforms.experimentalBadge", "Experimental")}</span></h1>
		<p class="page__intro">${t("toolforms.introSaved", "Signed-in changes are published to official Toolhub when permitted; otherwise they are saved locally in Evolved — see")} <a href="/rules-of-engagement">${t("toolforms.rulesOfEngagement", "Rules of Engagement")}</a>.
		${isCrawler ? t("toolforms.crawlerOwnedNote", "Core fields of crawler-imported tools are owned by the maintainer's toolinfo.json; only origin=api tools are core-editable in official Toolhub.") : ""}</p>
		<form data-tool-form novalidate>
			<h2 class="le__h2">${t("toolforms.coreInformation", "Core information")}</h2>
			${coreStatusPanel}
			${editing ? `<p class="le__ro">${t("toolforms.nameLabel", "Name:")} <code>${esc(name)}</code>${coreMeta ? fieldProvenance(t("toolforms.fieldNameShort", "Name"), coreMeta) : ""}</p>` : fInput(t("toolforms.fieldName", "Name (unique id)"), "tf-name", "", { req: true, ph: "my-cool-tool", max: 120, hint: t("toolforms.fieldNameHint", "Stable lowercase id used in Toolhub URLs; it cannot be changed later.") })}${isCrawler ? `\n\t\t\t${crawlerAuthorField(cur, coreMeta)}` : ""}
			${withCatalogFieldProvenance(fInput(t("toolforms.fieldTitle", "Title"), "tf-title", cur.title, { req: true, hint: t("toolforms.fieldTitleHint", "Short public name shown in search results and tool pages.") }), t("toolforms.fieldTitle", "Title"), coreMeta, cur.catalogProjection, "title")}
			${withCatalogFieldProvenance(fArea(t("toolforms.fieldDescription", "Description"), "tf-desc", cur.description, t("toolforms.fieldDescriptionHint", "One or two useful sentences: what it does, who it helps, and when to use it.")), t("toolforms.fieldDescription", "Description"), coreMeta, cur.catalogProjection, "description")}
			${withCatalogFieldProvenance(fInput(t("toolforms.fieldUrl", "URL"), "tf-url", cur.url, { req: true, type: "url", ph: "https://…", hint: t("toolforms.fieldUrlHint", "Primary place people launch the tool or read its documentation.") }), t("toolforms.fieldUrl", "URL"), coreMeta, cur.catalogProjection, "url")}
			${createToolinfoField}${withCatalogFieldProvenance(fInput(t("toolforms.fieldRepository", "Source code repository"), "tf-repo", cur.repository, { type: "url", hint: t("toolforms.fieldRepositoryHint", "Optional public repository where contributors can inspect or patch the code.") }), t("toolforms.fieldRepository", "Source code repository"), coreMeta, cur.catalogProjection, "repository")}
			${withCatalogFieldProvenance(fInput(t("toolforms.fieldLicense", "License (SPDX id)"), "tf-license", cur.license, { ph: "GPL-3.0-or-later", hint: t("toolforms.fieldLicenseHint", "Use an SPDX identifier when known; leave blank if the license is unknown.") }), t("toolforms.fieldLicenseShort", "License"), coreMeta, cur.catalogProjection, "license")}
			${withCatalogFieldProvenance(fSelect(t("toolforms.fieldToolType", "Tool type"), "tf-type", cur.toolType, TOOL_TYPES, { hint: t("toolforms.fieldToolTypeHint", "Choose the closest match; community annotations can refine discovery later.") }), t("toolforms.fieldToolType", "Tool type"), coreMeta, cur.catalogProjection, "tool_type")}
			${withCatalogFieldProvenance(fInput(t("toolforms.fieldKeywords", "Keywords (comma-separated)"), "tf-keywords", toCsv(cur.keywords), { hint: t("toolforms.fieldKeywordsHint", "Search terms people may try; avoid repeating only the title.") }), t("toolforms.fieldKeywordsShort", "Keywords"), coreMeta, cur.catalogProjection, "keywords")}
			${editing ? "" : duplicateRegion()}
			${withCatalogFieldProvenance(fInput(t("toolforms.fieldWikis", "Works on wikis (comma-separated, * for all)"), "tf-wikis", toCsv(cur.forWikis), { hint: t("toolforms.fieldWikisHint", "Use wiki hostnames such as en.wikipedia.org, commons.wikimedia.org, *.wikisource.org, or * for all wikis.") }), t("toolforms.fieldWikisShort", "Works on wikis"), coreMeta, cur.catalogProjection, "for_wikis")}
			${withCatalogFieldProvenance(fInput(t("toolforms.fieldLangs", "Available UI languages (comma-separated codes)"), "tf-langs", toCsv(cur.uiLanguages), { ph: "en, fr, de", hint: t("toolforms.fieldLangsHint", "BCP-47 / wiki language codes; saved values refresh the tool page after saving.") }), t("toolforms.fieldLangsShort", "Interface languages"), coreMeta, cur.catalogProjection, "available_ui_languages")}
			<div class="le__checks">${fCheck(t("toolforms.fieldDeprecated", "Deprecated"), "tf-deprecated", cur.deprecated)}${fCheck(t("toolforms.experimentalBadge", "Experimental"), "tf-experimental", cur.experimental)}</div>
			<div class="le__actions">
				${button(editing ? t("toolforms.saveChanges", "Save changes") : t("toolforms.submitTool", "Register tool"), { variant: "primary", type: "submit" })}
				${existingOfficialTool && officialWriteAvailable() ? button(t("toolforms.deleteOfficialTool", "Delete official tool"), { variant: "danger", cls: "le__delete", attrs: "data-tf-official-delete" }) : ""}
			</div>
			<p class="at__result" data-official-result aria-live="polite"></p>
		</form>
	</div>`;
	function mount() {
		const form = /** @type {HTMLFormElement} */ ($("[data-tool-form]"));
		if (localCurationControls) {
			$(".le__actions")?.insertAdjacentHTML("beforebegin", localCurationControls);
		}
		const changeReview = editing ? mountChangeReview(form) : null;
		const resetChangeReview = () => changeReview?.reset();
		form.addEventListener("input", resetChangeReview);
		form.addEventListener("change", resetChangeReview);
		setupToolCoreSubmit(form, { editing, name, current: cur, changeReview });
		setupToolCoreRetry(name);
		const curation = $("[data-tf-curation]");
		if (curation) {
			curation.addEventListener("click", async () => {
				const out = /** @type {HTMLElement} */ ($("[data-curation-result]"));
				const patch = localCurationPatch(cur, readToolFormFields());
				const rationale = fieldValue("tf-curation-rationale");
				if (Object.keys(patch).length === 0) {
					out.className = "at__result at__result--err";
					out.textContent = t(
						"toolforms.localCorrectionNoChanges",
						"Change at least one supported field first."
					);
					return;
				}
				if (!rationale) {
					setFieldError(
						"tf-curation-rationale",
						t("toolforms.localCorrectionRationaleRequired", "Explain why this correction is needed.")
					);
					return;
				}
				try {
					await serverWrite(
						"POST",
						`/v1/catalog/tools/${encodeURIComponent(/** @type {string} */ (name))}/curations/`,
						{ patch, rationale }
					);
					out.className = "at__result at__result--ok";
					out.textContent = t(
						"toolforms.localCorrectionSubmitted",
						"Local correction submitted for reviewer approval."
					);
				} catch (error) {
					out.className = "at__result at__result--err";
					out.textContent = backendErrorExplanation(error);
				}
			});
		}
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
				navigateTo("/my-tools");
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
					navigateTo("/my-tools");
				} catch (error) {
					out.className = "at__result at__result--err";
					out.textContent = t(
						"toolforms.officialDeleteFailed",
						"Official Toolhub did not delete the tool: $1",
						backendErrorExplanation(error)
					);
				}
			});
		}
		clearHttpErrorWhenValid("tf-url");
		clearHttpErrorWhenValid("tf-repo");
		if (!editing) clearHttpErrorWhenValid("tf-toolinfo-url", { httpsOnly: true });
		clearWikiErrorWhenValid("tf-wikis");
		if (!editing) setupDuplicateSuggestions();
	}
	return {
		title: `${editing ? t("toolforms.editTool", "Edit tool") : t("toolforms.submitATool", "Register a tool")} — Toolhub`,
		html,
		mount
	};
}

/** @param {Array<{ inputUrl: string, message: string, attempts?: Array<{ url?: string }> }>} discoveryMisses */
function addToolDiscoveryRows(discoveryMisses) {
	return discoveryMisses
		.map((miss) => {
			const checked = (miss.attempts || [])
				.map((attempt) => attempt.url)
				.filter(Boolean)
				.join(", ");
			const suffix = checked ? ` ${t("toolforms.discoveryChecked", "Checked: $1", checked)}` : "";
			return `<li class="at__url-row at__url-row--not-found"><code class="at__url">${esc(miss.inputUrl)}</code> <span class="sync-badge sync-badge--sync-error">${t("toolforms.toolinfoNotFound", "toolinfo.json not found")}</span><span class="at__url-error">${esc(miss.message)}${esc(suffix)}</span></li>`;
		})
		.join("");
}

/** @param {Array<{ inputUrl: string, message: string, attempts?: Array<{ url?: string }> }>} discoveryMisses */
function addToolUrlRows(discoveryMisses) {
	const registered = crawlerUrls()
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
		.join("");
	const misses = addToolDiscoveryRows(discoveryMisses);
	return registered || misses
		? `${registered}${misses}`
		: `<li class="le__empty">${t("toolforms.noUrls", "No URLs registered.")}</li>`;
}

function addToolSubGrid() {
	const cards = /** @type {Tool[]} */ (Object.keys(toolNewMap()).map((n) => newToolBase(n)));
	return cards.length > 0
		? grid("grid-tools", cards, (/** @type {Tool} */ t) => toolCard(t))
		: `<p class="empty">${t("toolforms.noToolsYet", "No tools yet. Submit one above, or ingest toolinfo.")}</p>`;
}

/** @param {Array<Record<string, any>>} runs */
function addToolCrawlerRunRows(runs) {
	if (runs.length === 0) {
		return `<p class="empty">${t("toolforms.noCrawlerRuns", "No local crawler runs recorded yet.")}</p>`;
	}
	return `<ol class="feed feed--compact">${runs
		.map((run) => {
			const status = run.ok ? t("toolforms.crawlerRunOk", "OK") : t("toolforms.crawlerRunErrors", "Errors");
			const errors = Array.isArray(run.errors) && run.errors.length > 0 ? ` · ${esc(run.errors[0])}` : "";
			// Without this, a run that skipped every name reads as "0 added" with no reason given.
			const skips = Array.isArray(run.skipped) ? run.skipped.length : 0;
			const skipped = skips > 0 ? ` · ${t("toolforms.crawlerRunSkipped", "$1 skipped", String(skips))}` : "";
			return `<li><span>${status} · ${t(
				"toolforms.crawlerRunCounts",
				"$1 URLs, $2 added, $3 updated",
				String(run.urlsCount || 0),
				String(run.added || 0),
				String(run.updated || 0)
			)}${skipped}${errors}</span><span class="feed__when">${esc(run.endedAt || run.startedAt || "")}</span></li>`;
		})
		.join("")}</ol>`;
}

/** @param {string} url @param {HTMLElement} out */
async function addToolRegisterCrawlerUrl(url, out) {
	out.className = "at__result";
	out.textContent = t("toolforms.publishingToToolhub", "Publishing to official Toolhub…");
	try {
		const res = await officialWrite("POST", "/v1/write/crawler/urls/", { url });
		const local = res?.local || {};
		const officialId =
			local.officialId ??
			(res?.result === SYNC_STATUS.official && typeof res?.toolhub?.id === "number" ? res.toolhub.id : undefined);
		const meta = lifecycleMeta(res);
		if (typeof local.localId === "number") meta.localId = local.localId;
		crawlerUrlAdd(local.url || url, officialId, meta);
		if (res?.result === SYNC_STATUS.localFallback) {
			out.className = "at__result at__result--err";
			out.textContent = t(
				"toolforms.officialWriteFailed",
				"Official Toolhub did not accept the write. Saved locally in Evolved instead: $1",
				backendErrorExplanation(res)
			);
		} else {
			out.className = "at__result at__result--ok";
			out.textContent = t("toolforms.officialUrlRegistered", "Registered with official Toolhub.");
		}
		return true;
	} catch (error) {
		showOfficialWriteFailure(out, error, { "at-url": ["url"] });
		return false;
	}
}

/**
 * @param {string} url
 * @param {HTMLElement} out
 * @param {Array<{ inputUrl: string, message: string, attempts?: Array<{ url?: string }> }>} discoveryMisses
 * @param {() => void} renderUrlList
 */
async function addToolDiscoverToolinfoUrl(url, out, discoveryMisses, renderUrlList) {
	if (looksLikeToolinfoUrl(url)) return url;
	out.className = "at__result";
	out.textContent = t("toolforms.discoveringToolinfo", "Looking for toolinfo.json…");
	try {
		const res = await serverWrite("POST", "/v1/crawler/toolinfo-discovery/", { url });
		if (res?.ok && res.toolinfoUrl) {
			out.textContent =
				res.method === "sitemap"
					? t(
							"toolforms.toolinfoFoundInSitemap",
							"Found toolinfo.json in sitemap.xml. Publishing to official Toolhub…"
						)
					: t(
							"toolforms.toolinfoFoundAtRoot",
							"Found toolinfo.json at the site root. Publishing to official Toolhub…"
						);
			return String(res.toolinfoUrl);
		}
		const message = res?.lastError || t("toolforms.toolinfoDiscoveryFailed", "toolinfo.json could not be found.");
		discoveryMisses.unshift({
			inputUrl: url,
			message,
			attempts: Array.isArray(res?.attempts) ? res.attempts : []
		});
		renderUrlList();
		out.className = "at__result at__result--err";
		out.textContent = message;
		return null;
	} catch (error) {
		showOfficialWriteFailure(out, error, { "at-url": ["url"] });
		return null;
	}
}

function toolinfoControlWorkspace() {
	const html = accountSection({
		id: "toolinfo-control-title",
		title: t("toolforms.toolinfoControlTitle", "Verify control of a toolinfo URL"),
		intro: t(
			"toolforms.toolinfoControlIntro",
			"Registering a URL does not prove ownership. Evolved can verify that you control the exact metadata URL by asking you to publish a short-lived challenge in its JSON."
		),
		body: `<form class="le__add" data-control-form novalidate>
			${fInput(t("toolforms.controlToolName", "Tool name"), "control-tool-name", "", { req: true, ph: "my-tool", hint: t("toolforms.controlToolNameHint", "Use the exact name field from toolinfo.json.") })}
			${fInput(t("toolforms.controlToolinfoUrl", "Exact toolinfo.json URL"), "control-toolinfo-url", "", { req: true, type: "url", ph: "https://example.org/toolinfo.json" })}
			${button(t("toolforms.issueControlChallenge", "Issue challenge"), { variant: "outline", type: "submit" })}
		</form>
		<div class="toolinfo-control__challenge" data-control-challenge hidden></div>
		<p class="at__result" data-control-result aria-live="polite"></p>`
	});
	function mount() {
		const form = /** @type {HTMLFormElement | null} */ ($("[data-control-form]"));
		const result = /** @type {HTMLElement | null} */ ($("[data-control-result]"));
		const challengeBox = /** @type {HTMLElement | null} */ ($("[data-control-challenge]"));
		if (!form || !result || !challengeBox) return;
		form.addEventListener("submit", async (event) => {
			event.preventDefault();
			const toolName = fieldValue("control-tool-name").trim();
			const toolinfoUrl = fieldValue("control-toolinfo-url").trim();
			if (!toolName || !toolinfoUrl) return;
			result.className = "at__result";
			result.textContent = t("toolforms.issuingControlChallenge", "Checking the URL and issuing a challenge…");
			try {
				const response = await serverWrite("POST", "/v1/toolinfo/ownership-challenges/", {
					toolName,
					toolinfoUrl
				});
				const challenge = response?.challenge;
				if (!challenge?.id || !challenge?.token) {
					throw new Error(
						t("toolforms.controlChallengeMissing", "The server did not return a usable challenge.")
					);
				}
				challengeBox.hidden = false;
				challengeBox.innerHTML = `<p><strong>${esc(t("toolforms.controlPublishLabel", "Publish this value in your toolinfo.json:"))}</strong></p>
					<pre><code>${esc(JSON.stringify({ x_toolhub_evolved_verification: { challenge: challenge.token } }, null, 2))}</code></pre>
					<p class="signin-note">${esc(t("toolforms.controlPublishHint", "Keep the field in the exact URL above, wait for the file to update, then verify it here. The challenge expires in 24 hours."))}</p>
					${button(t("toolforms.verifyControl", "Verify URL control"), { variant: "primary", type: "button", attrs: `data-control-verify="${esc(String(challenge.id))}"` })}`;
				result.className = "at__result at__result--ok";
				result.textContent = t(
					"toolforms.controlChallengeIssued",
					"Challenge issued. Publish it in the metadata file, then verify."
				);
			} catch (error) {
				result.className = "at__result at__result--err";
				result.textContent = backendErrorExplanation(error);
			}
		});
		challengeBox.addEventListener("click", async (event) => {
			const verify = /** @type {HTMLElement} */ (event.target).closest("[data-control-verify]");
			if (!verify) return;
			verify.setAttribute("disabled", "disabled");
			result.className = "at__result";
			result.textContent = t("toolforms.verifyingControl", "Refetching the metadata file…");
			try {
				await serverWrite(
					"POST",
					`/v1/toolinfo/ownership-challenges/${encodeURIComponent(verify.getAttribute("data-control-verify") || "")}/verify/`
				);
				result.className = "at__result at__result--ok";
				result.textContent = t(
					"toolforms.controlVerified",
					"Verified. This account now has a maintainer claim for this tool based on control of its toolinfo URL."
				);
			} catch (error) {
				verify.removeAttribute("disabled");
				result.className = "at__result at__result--err";
				result.textContent = backendErrorExplanation(error);
			}
		});
	}
	return { html, mount };
}

// Tool registration workspace: official crawler URL registration plus local toolinfo ingest.
export function toolRegistrationWorkspace() {
	/** @type {Array<{ inputUrl: string, message: string, attempts?: Array<{ url?: string }> }>} */
	const discoveryMisses = [];
	// Stryker disable next-line StringLiteral: button() defaults variant to "outline", so "" renders identical markup — equivalent.
	const registerBtn = button(t("toolforms.register", "Register"), { variant: "outline", type: "submit" });
	const control = toolinfoControlWorkspace();
	const localToolCount = Object.keys(toolNewMap()).length;
	const html = `${accountSection({
		id: "add-toolinfo-url-title",
		title: t("toolforms.findOrRegisterToolinfoTitle", "Find or register toolinfo.json"),
		intro: t(
			"toolforms.registerToolinfoNote",
			"Paste a tool homepage or direct toolinfo.json URL. Evolved checks common discovery paths before registering the crawler source."
		),
		body: `<form class="le__add" data-url-form novalidate>
					${fInput(t("toolforms.fieldToolOrToolinfoUrl", "Tool homepage or toolinfo.json URL"), "at-url", "", { type: "url", ph: "https://example.org/", hint: t("toolforms.fieldToolOrToolinfoUrlHint", "Paste the tool homepage or a direct toolinfo.json URL. Evolved tries /toolinfo.json first, then sitemap.xml.") })}
					${registerBtn}
				</form>
				<ul class="at__urls" data-url-list>${addToolUrlRows(discoveryMisses)}</ul>`
	})}
			${accountSection({
				id: "add-toolinfo-json-title",
				title: t("toolforms.ingestToolinfoTitle", "Ingest toolinfo"),
				intro: t(
					"toolforms.ingestToolinfoNote",
					"Paste one tool object or an array. Successful records stay in Evolved until they are submitted or matched with official Toolhub data."
				),
				body: `${fArea(t("toolforms.fieldToolinfoJson", "Toolinfo JSON"), "at-json", "", t("toolforms.fieldToolinfoJsonHint", "Paste one tool object or an array; successful entries appear below in Your tools."), { rows: 10, max: false, cls: "at__json", ph: '{ "name": "my-tool", "title": "My Tool", "description": "…", "url": "https://…" }' })}
				<div class="le__actions">
					${button(t("toolforms.ingest", "Ingest"), { variant: "primary", attrs: "data-ingest" })}
				</div>
				<p class="at__result" data-ingest-result aria-live="polite"></p>`
			})}
			${control.html}
			${accountSection({
				id: "add-toolinfo-submissions-title",
				title: t("toolforms.yourToolsTitle", "Your tools"),
				intro: t(
					"toolforms.yourToolsNote",
					"Local submissions and pasted toolinfo records attached to this account workspace."
				),
				body: `<p class="le__count" data-sub-count>${t("toolforms.toolCount", "$1 {{PLURAL:$2|tool|tools}}", fmt(localToolCount), localToolCount)}</p>
				<div data-sub-grid>${addToolSubGrid()}</div>`
			})}
			${accountSection({
				id: "add-toolinfo-runs-title",
				title: t("toolforms.localCrawlerRunsTitle", "Local crawler runs"),
				intro: t(
					"toolforms.localCrawlerRunsNote",
					"Recent local discovery attempts for pasted or registered toolinfo sources."
				),
				body: `<div data-crawler-runs>${addToolCrawlerRunRows([])}</div>`
			})}`;
	function mount() {
		const renderUrlList = () => {
			/** @type {HTMLElement} */ ($("[data-url-list]")).innerHTML = addToolUrlRows(discoveryMisses);
		};
		backendGetJson("/v1/crawler/runs/")
			.then((data) => {
				const box = $("[data-crawler-runs]");
				if (box) box.innerHTML = addToolCrawlerRunRows(Array.isArray(data?.results) ? data.results : []);
				return undefined;
			})
			.catch(() => undefined);
		control.mount();
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
			if (!officialWriteAvailable()) {
				out.className = "at__result at__result--err";
				out.textContent = toolhubSignInRequiredMessage();
				return;
			}
			const toolinfoUrl = await addToolDiscoverToolinfoUrl(u, out, discoveryMisses, renderUrlList);
			if (!toolinfoUrl) return;
			if (!(await addToolRegisterCrawlerUrl(toolinfoUrl, out))) return;
			/** @type {HTMLInputElement} */ ($input("#at-url")).value = "";
			clearFieldError("at-url");
			renderUrlList();
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
									"Official Toolhub did not accept the write. Saved locally in Evolved instead: $1",
									backendErrorExplanation(res)
								)
							: t("toolforms.officialUrlRegistered", "Registered with official Toolhub.");
					renderUrlList();
				} catch (error) {
					out.className = "at__result at__result--err";
					out.textContent = t(
						"toolforms.officialWriteFailedNoDraft",
						"Official Toolhub did not accept the write: $1",
						backendErrorExplanation(error)
					);
				}
				return;
			}
			const b = /** @type {EventTarget} */ (e.target).closest("[data-url-rm]");
			if (!b) return;
			const officialId = b.getAttribute("data-url-id");
			const localId = b.getAttribute("data-url-local-id");
			const out = /** @type {HTMLElement} */ ($("[data-ingest-result]"));
			if (officialWriteAvailable() && officialId) {
				try {
					await officialWrite("DELETE", `/v1/write/crawler/urls/${officialId}/`);
				} catch (error) {
					out.className = "at__result at__result--err";
					out.textContent = t(
						"toolforms.officialUrlDeleteFailed",
						"Official Toolhub could not remove the URL: $1",
						backendErrorExplanation(error)
					);
					return;
				}
			} else if (officialWriteAvailable() && localId) {
				try {
					await officialWrite("DELETE", `/v1/write/crawler/urls/${localId}/fallback/`);
				} catch (error) {
					out.className = "at__result at__result--err";
					out.textContent = t(
						"toolforms.officialUrlDeleteFailed",
						"Official Toolhub could not remove the URL: $1",
						backendErrorExplanation(error)
					);
					return;
				}
			}
			crawlerUrlDelete(/** @type {string} */ (b.getAttribute("data-url-rm")));
			renderUrlList();
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
			if (res.added) parts.push(t("toolforms.nAdded", "$1 added", res.added));
			if (res.updated) parts.push(t("toolforms.nUpdated", "$1 updated", res.updated));
			out.className = `at__result${errors.length > 0 && parts.length === 0 ? " at__result--err" : " at__result--ok"}`;
			out.textContent =
				(parts.join(", ") || t("toolforms.nothingIngested", "Nothing ingested")) +
				(errors.length > 0 ? ` · ${errors.join("; ")}` : "");
			/** @type {HTMLElement} */ ($("[data-sub-grid]")).innerHTML = addToolSubGrid();
			const c = $("[data-sub-count]");
			// Stryker disable next-line ConditionalExpression: the [data-sub-count] element is always present in this view, so the guard is always true — defensive.
			if (c) {
				c.textContent = t(
					"toolforms.toolCount",
					"$1 {{PLURAL:$2|tool|tools}}",
					fmt(Object.keys(toolNewMap()).length),
					Object.keys(toolNewMap()).length
				);
			}
		});
		clearHttpErrorWhenValid("at-url");
	}
	return { html, mount };
}

export function viewAddTools() {
	const workspace = toolRegistrationWorkspace();
	return {
		title: t("accountTools.docTitle", "My tools - Toolhub"),
		html: `<div class="container page at">${workspace.html}</div>`,
		mount: workspace.mount
	};
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
	const iconDiagnostic = iconProvenanceDiagnostic(cur);
	const annotationStatusPanel = syncStatusPanel(annotationMeta, {
		title: t("toolforms.annotationWriteStatus", "Annotation write status"),
		retryAttrs: annotationState.retryAvailable && officialWriteAvailable() ? "data-an-retry" : "",
		discardAttrs: toolAnnosMap()[name] ? "data-an-revert" : "",
		discardLabel: t("toolforms.discardLocalAnnotations", "Discard local annotations"),
		showIfOfficial: true
	});
	const html = `
	<div class="container page le">
		<a class="back" href="${toolHref(name)}">${t("toolforms.backToName", "← Back to $1", esc(cur.title))}</a>
		<h1 class="page__title">${t("toolforms.editAnnotations", "Edit annotations")} <span class="exp-badge">${t("toolforms.experimentalBadge", "Experimental")}</span></h1>
		<p class="page__intro">${t("toolforms.annoIntro", "Community annotations enrich a tool without touching its core data. Signed-in changes publish to official Toolhub when permitted; rejected writes stay local to Evolved — see")} <a href="/rules-of-engagement">${t("toolforms.rulesOfEngagement", "Rules of Engagement")}</a>.</p>
		<form data-anno-form>
			<h2 class="le__h2">${t("toolforms.annoForTitle", "Community annotations for")} <span${textAttrs(cur.title, cur.titleLanguage)}>${esc(cur.title)}</span></h2>
			${annotationStatusPanel}
			${withFieldProvenance(fInput(t("toolforms.fieldAudiences", "Audiences (comma-separated)"), "an-aud", toCsv(cur.audiences), { hint: t("toolforms.fieldAudiencesHint", "User groups this tool serves, such as editors, admins, researchers, or developers.") }), t("toolforms.fieldAudiencesShort", "Audiences"), annotationMeta)}
			${withFieldProvenance(fInput(t("toolforms.fieldTasks", "Tasks (comma-separated)"), "an-tasks", toCsv(cur.tasks), { hint: t("toolforms.fieldTasksHint", "Workflows this tool supports, such as editing, patrolling, importing, or analysis.") }), t("toolforms.fieldTasksShort", "Tasks"), annotationMeta)}
			${withFieldProvenance(fSelect(t("toolforms.fieldToolType", "Tool type"), "an-type", cur.toolType, TOOL_TYPES, { hint: t("toolforms.fieldAnnoToolTypeHint", "Community classification used for discovery when core metadata is sparse.") }), t("toolforms.fieldToolType", "Tool type"), annotationMeta)}
			${withFieldProvenance(fInput(t("toolforms.fieldIcon", "Icon (Commons File: URL)"), "an-icon", cur.icon, { type: "url", hint: t("toolforms.fieldIconHint", "Optional Commons-hosted image URL for visual identification.") }), t("toolforms.fieldIconShort", "Icon"), annotationMeta)}
${iconDiagnostic ? `\t\t\t${iconDiagnostic}\n` : ""}\t\t\t<div class="le__actions">
				${button(t("toolforms.saveAnnotations", "Save annotations"), { variant: "primary", type: "submit" })}
			</div>
			<p class="at__result" data-official-result aria-live="polite"></p>
		</form>
	</div>`;
	function mount() {
		const form = /** @type {HTMLFormElement} */ ($("[data-anno-form]"));
		const changeReview = mountChangeReview(form);
		const resetChangeReview = () => changeReview.reset();
		form.addEventListener("input", resetChangeReview);
		form.addEventListener("change", resetChangeReview);
		form.addEventListener("submit", async (e) => {
			e.preventDefault();
			const anno = readAnnotationFormFields();
			const out = /** @type {HTMLElement} */ ($("[data-official-result]"));
			const canOfficialWrite = officialWriteAvailable();
			if (canOfficialWrite) {
				if (!shouldProceedWithFieldChanges(changeReview, annotationChangeDescriptors(cur, anno), out)) {
					return;
				}
				out.className = "at__result";
				out.textContent = t("toolforms.publishingToToolhub", "Publishing to official Toolhub…");
				try {
					const res = await officialWrite(
						"PUT",
						`/v1/write/tools/${encodeURIComponent(name)}/annotations/`,
						officialAnnotationPayload(anno)
					);
					if (res?.result === SYNC_STATUS.localFallback) {
						saveAnnotationFallbackResult(name, anno, res, out);
						return;
					}
					clearLocalAnnotationDraft(name);
					clearApiCache();
					navigateTo(toolHref(name));
					return;
				} catch (error) {
					const msg = backendErrorExplanation(error);
					out.className = "at__result at__result--err";
					out.textContent = t(
						"toolforms.officialWriteFailedNoDraft",
						"Official Toolhub did not accept the write: $1",
						msg
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
