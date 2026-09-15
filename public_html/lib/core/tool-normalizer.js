// SPDX-License-Identifier: GPL-3.0-or-later
import { hasValue } from "./util.js";
import { localizedField, t } from "./i18n.js";
import { USER } from "./session.js";
import { toolEditsMap, toolAnnosMap, toolNewMap } from "./store.js";

/* Tool domain normalization is intentionally independent from network and
   cache transport. Every caller gets the same compact shape and overlay rules. */
/** @type {Record<string, Tool>} */
export const INDEX = {};
const OVERLAY_META_KEYS = new Set([
	"source",
	"syncStatus",
	"syncLabel",
	"lastSyncedAt",
	"lastError",
	"createdByUserId",
	"created_by_user_id",
	"deletedAt",
	"deleted_at",
	"officialId",
	"officialName",
	"visibility",
	"toolhubResponse",
	"toolhubStatus",
	"toolhubCode",
	"validationErrors",
	"baseRevision",
	"fieldStatuses",
	"reviewStatus",
	"viewerOwned"
]);
const CANONICAL_TOOL_KEYS = new Set(["name", "origin"]);

/**
 * @param {Record<string, any>} patch
 * @returns {Record<string, any>}
 */
function dataPatch(patch) {
	return Object.fromEntries(
		Object.entries(patch || {}).filter(([key]) => !OVERLAY_META_KEYS.has(key) && !CANONICAL_TOOL_KEYS.has(key))
	);
}

/** @param {string} name */
export function isNewTool(name) {
	return Boolean(toolNewMap()[name]);
}

/**
 * @param {Tool} o
 * @returns {Tool}
 */
export function applyToolOverlay(o) {
	const e = toolEditsMap()[o.name];
	if (e) {
		Object.assign(o, dataPatch(e));
		// `edited`/`annotated`/`status` (object) are runtime extras the static
		// Tool interface doesn't model; cast through any for these writes.
		/** @type {any} */ (o).edited = true;
		/** @type {any} */ (o).editSyncStatus = e.syncStatus;
		/** @type {any} */ (o).editLastError = e.lastError;
		/** @type {any} */ (o).editValidationErrors = e.validationErrors;
		/** @type {any} */ (o).editReviewStatus = e.reviewStatus;
		/** @type {any} */ (o).editLastSyncedAt = e.lastSyncedAt;
		/** @type {any} */ (o).editToolhubResponse = e.toolhubResponse;
		/** @type {any} */ (o).editToolhubStatus = e.toolhubStatus;
		/** @type {any} */ (o).editToolhubCode = e.toolhubCode;
		/** @type {any} */ (o).editViewerOwned = e.viewerOwned;
	}
	const a = toolAnnosMap()[o.name];
	if (a) {
		Object.assign(o, dataPatch(a));
		/** @type {any} */ (o).annotated = true;
		/** @type {any} */ (o).annotationSyncStatus = a.syncStatus;
		/** @type {any} */ (o).annotationLastError = a.lastError;
		/** @type {any} */ (o).annotationValidationErrors = a.validationErrors;
		/** @type {any} */ (o).annotationReviewStatus = a.reviewStatus;
		/** @type {any} */ (o).annotationLastSyncedAt = a.lastSyncedAt;
		/** @type {any} */ (o).annotationToolhubResponse = a.toolhubResponse;
		/** @type {any} */ (o).annotationToolhubStatus = a.toolhubStatus;
		/** @type {any} */ (o).annotationToolhubCode = a.toolhubCode;
		/** @type {any} */ (o).annotationViewerOwned = a.viewerOwned;
	}
	if (e || a) o.status = /** @type {any} */ (statusOf(o)); // flags may have changed
	return o;
}

// Build a compact tool object from a locally-registered record (the project
// database that complements the replicated catalog), then overlay edits.
/**
 * @param {string} name
 * @param {Record<string, any>} rec
 * @returns {Tool}
 */
export function localToolBase(name, rec) {
	// The defaults + record spread produce a structurally-complete compact tool;
	// assert the Tool shape once here (same trust boundary as normalizeTool).
	const o = /** @type {Tool} */ (
		/** @type {unknown} */ (
			Object.assign(
				{
					name,
					keywords: [],
					authors: [],
					audiences: [],
					tasks: [],
					forWikis: [],
					uiLanguages: [],
					technologyUsed: [],
					urlAlternates: [],
					contentTypes: [],
					subjectDomains: [],
					userDocsUrls: [],
					devDocsUrls: [],
					feedbackUrls: [],
					privacyPolicyUrls: [],
					bugtrackerUrls: [],
					translateUrls: [],
					botUsername: null,
					openhubId: null,
					privacyPolicy: null,
					toolinfoUrl: null,
					schema: null,
					recordLanguage: null,
					catalogMetadata: publicCatalogMetadata(rec),
					skillMetadata: skillMetadata(rec),
					evolvedMetadata: rec.evolved && typeof rec.evolved === "object" ? rec.evolved : null,
					maintainer: USER.name,
					deprecated: false,
					experimental: false,
					lifecycle: "",
					origin: "api"
				},
				rec
			)
		)
	);
	o.name = name;
	o.weeklyViews = 0;
	/** @type {any} */ (o).viewerOwned = rec.viewerOwned;
	o.status = statusOf(o);
	INDEX[name] = o;
	return applyToolOverlay(o);
}

// Net-new submission from this browser's overlay cache.
/**
 * @param {string} name
 * @returns {Tool | null}
 */
export function newToolBase(name) {
	const rec = toolNewMap()[name];
	return rec ? localToolBase(name, rec) : null;
}

/**
 * Rank what is worth saying about a tool, most consequential first.
 *
 * Deprecated and experimental come first because a maintainer said them about
 * their own tool. Archived is below both because nobody said it: it is this
 * codebase's observation that nothing it can see loads the tool, and a
 * maintainer's own claim about their work outranks our reading of the traffic.
 * @param {{ deprecated: boolean; experimental: boolean; lifecycle?: string }} t
 * @returns {ToolStatus}
 */
export function statusOf(t) {
	return t.deprecated
		? { level: "red", label: "Deprecated" }
		: t.experimental
			? { level: "yellow", label: "Experimental" }
			: t.lifecycle === "archived"
				? { level: "grey", label: "Archived" }
				: { level: "green", label: "Healthy" };
}

/** @param {unknown} v */
export function firstUrl(v) {
	if (!v) return null;
	if (typeof v === "string") return v;
	if (typeof v === "object" && !Array.isArray(v)) {
		const candidate = /** @type {{ url?: unknown }} */ (v).url;
		return typeof candidate === "string" ? candidate : null;
	}
	if (Array.isArray(v) && v.length > 0) {
		const x = v[0];
		return x && typeof x === "object" ? x.url : x;
	}
	return null;
}

/**
 * Choose the first of core/annotation that has a value, else the fallback.
 * @template T
 * @param {unknown} core
 * @param {unknown} annotation
 * @param {T} fallback
 * @returns {T}
 */
export function pick(core, annotation, fallback) {
	if (hasValue(core)) return /** @type {T} */ (core);
	if (hasValue(annotation)) return /** @type {T} */ (annotation);
	return fallback;
}

/** @param {unknown} core @param {unknown} annotation @returns {any[]} */
function listValue(core, annotation) {
	const value = /** @type {unknown} */ (pick(core, annotation, []));
	return Array.isArray(value) ? value : hasValue(value) ? [value] : [];
}

const NON_CATALOG_KEYS = new Set([
	"_catalogProjection",
	"_cachedIconUrl",
	"accountRelationships",
	"accountPerson",
	"relationshipPeople",
	"toolinfoDiscovery",
	"toolinfoSource",
	"toolforgeProjects",
	"weeklyViews",
	"status",
	"canonicalRecord",
	...OVERLAY_META_KEYS
]);

/** @param {any} record */
function publicCatalogMetadata(record) {
	if (!record || typeof record !== "object") return {};
	return Object.fromEntries(Object.entries(record).filter(([key]) => !NON_CATALOG_KEYS.has(key)));
}

/** @param {any} record */
function skillMetadata(record) {
	if (!record || typeof record !== "object") return null;
	const evolved = record.evolved;
	const value = hasValue(record.skill)
		? record.skill
		: hasValue(record.skills)
			? record.skills
			: evolved && typeof evolved === "object"
				? evolved.skill
				: null;
	if (Array.isArray(value)) return value.filter((item) => item && typeof item === "object");
	return value && typeof value === "object" ? value : null;
}

/* Called lazily so a locale catalog installed at boot is picked up. */
function unknownMaintainer() {
	return t("api.unknownMaintainer", "Unknown");
}

/**
 * Raw author records from the upstream API are heterogeneous (string | object | null).
 * @param {any} a
 */
function normalizeAuthorObj(a) {
	if (!a) return null;
	if (typeof a === "string") return a ? { name: a, url: null, wikiUsername: null, developerUsername: null } : null;
	const name = a.name || "";
	if (!name) return null;
	return {
		name,
		url: a.url || null,
		wikiUsername: a.wiki_username || null,
		developerUsername: a.developer_username || null
	};
}

/**
 * Normalize a raw upstream tool record into the compact `Tool` shape.
 * @param {any} t
 * @returns {Tool}
 */
export function normalizeTool(t) {
	const ann = t.annotations && typeof t.annotations === "object" ? t.annotations : {};
	const ra = t.author;
	const titleField = localizedField(t.title, t._language);
	const descriptionField = localizedField(t.description, t._language);
	const subtitleField = localizedField(pick(t.subtitle, ann.subtitle, null), t._language);
	const authors = Array.isArray(ra)
		? ra.map((a) => (a && a.name) || (typeof a === "string" ? a : null)).filter(Boolean)
		: typeof ra === "string" && ra
			? [ra]
			: [];
	const authorObjs = /** @type {AuthorObj[]} */ (
		Array.isArray(ra)
			? ra.map((author) => normalizeAuthorObj(author)).filter(Boolean)
			: [normalizeAuthorObj(ra)].filter(Boolean)
	);
	const deprecated = Boolean(t.deprecated || ann.deprecated);
	const experimental = Boolean(t.experimental || ann.experimental);
	const lifecycle = typeof t._lifecycle === "string" ? t._lifecycle : "";
	/** @type {Tool} */
	const o = {
		name: t.name,
		title: titleField.value || t.name,
		titleLanguage: titleField.value ? titleField.lang : null,
		description: descriptionField.value || "",
		descriptionLanguage: descriptionField.value ? descriptionField.lang : null,
		url: pick(t.url, ann.url, ""),
		icon: pick(t.icon, ann.icon, null),
		keywords: listValue(t.keywords, ann.keywords),
		maintainer: authors[0] || (t.created_by && t.created_by.username) || unknownMaintainer(),
		authors,
		authorObjs,
		wikidata: pick(t.wikidata_qid, ann.wikidata_qid, null),
		subtitle: subtitleField.value || null,
		subtitleLanguage: subtitleField.value ? subtitleField.lang : null,
		sponsor: listValue(t.sponsor, ann.sponsor),
		replacedBy: pick(t.replaced_by, ann.replaced_by, null),
		toolType: pick(t.tool_type, ann.tool_type, null),
		license: pick(t.license, ann.license, null),
		repository: pick(t.repository, ann.repository, null),
		apiUrl: firstUrl(pick(t.api_url, ann.api_url, null)),
		urlAlternates: listValue(t.url_alternates, ann.url_alternates),
		botUsername: pick(t.bot_username, ann.bot_username, null),
		openhubId: pick(t.openhub_id, ann.openhub_id, null),
		privacyPolicy: firstUrl(pick(t.privacy_policy_url, ann.privacy_policy_url, [])),
		technologyUsed: listValue(t.technology_used, ann.technology_used),
		contentTypes: listValue(t.content_types, ann.content_types),
		subjectDomains: listValue(t.subject_domains, ann.subject_domains),
		audiences: listValue(t.audiences, ann.audiences),
		tasks: listValue(t.tasks, ann.tasks),
		forWikis: listValue(t.for_wikis, ann.for_wikis),
		uiLanguages: listValue(t.available_ui_languages, ann.available_ui_languages),
		userDocsUrls: listValue(t.user_docs_url, ann.user_docs_url),
		userDocs: firstUrl(listValue(t.user_docs_url, ann.user_docs_url)),
		devDocsUrls: listValue(t.developer_docs_url, ann.developer_docs_url),
		devDocs: firstUrl(listValue(t.developer_docs_url, ann.developer_docs_url)),
		feedbackUrls: listValue(t.feedback_url, ann.feedback_url),
		feedback: firstUrl(listValue(t.feedback_url, ann.feedback_url)),
		privacyPolicyUrls: listValue(t.privacy_policy_url, ann.privacy_policy_url),
		bugtrackerUrls: listValue(t.bugtracker_url, ann.bugtracker_url),
		bugtracker: firstUrl(listValue(t.bugtracker_url, ann.bugtracker_url)),
		translateUrls: listValue(t.translate_url, ann.translate_url),
		translate: firstUrl(listValue(t.translate_url, ann.translate_url)),
		deprecated,
		experimental,
		lifecycle,
		created: t.created_date || t.created || null,
		modified: t.modified_date || t.modified || null,
		origin: t.origin || "crawler",
		toolinfoUrl: firstUrl(pick(t.toolinfo_url, ann.toolinfo_url, null)),
		schema: t._schema || null,
		recordLanguage: t._language || null,
		catalogMetadata: publicCatalogMetadata(t),
		skillMetadata: skillMetadata(t),
		evolvedMetadata: t.evolved && typeof t.evolved === "object" ? t.evolved : null,
		catalogProjection: t._catalogProjection || null,
		cachedIconUrl: t._cachedIconUrl || null,
		accountRelationships: Array.isArray(t.accountRelationships) ? t.accountRelationships : [],
		accountPerson: t.accountPerson && typeof t.accountPerson.id === "string" ? { ...t.accountPerson } : undefined,
		relationshipPeople: Array.isArray(t.relationshipPeople) ? t.relationshipPeople : [],
		weeklyViews: 0,
		status: statusOf({ deprecated, experimental, lifecycle })
	};
	applyToolOverlay(o);
	INDEX[o.name] = o;
	return o;
}

/**
 * @param {any} l
 * @returns {ToolList}
 */
export function normalizeList(l) {
	const tools = /** @type {any[]} */ (l.tools || []).map((tool) => normalizeTool(tool));
	return {
		id: l.id,
		title: l.title || t("api.untitledList", "Untitled list"),
		description: l.description || "",
		toolCount: tools.length,
		tools,
		featured: Boolean(l.featured)
	};
}
