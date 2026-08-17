// SPDX-License-Identifier: GPL-3.0-or-later
// cspell:ignore openhub
import { $, $$, esc } from "../core/dom.js";
import { t } from "../core/i18n.js";
import {
	TOOLINFO_DATA_MODEL_URL,
	TOOLINFO_SCHEMA_URL,
	TOOLINFO_SCHEMA_VERSION,
	TOOLINFO_TOOL_TYPES
} from "../core/toolinfo-docs.js";
import {
	formatMultilingualUrls,
	parseMultilingualUrls,
	prefillToolinfo,
	toolinfoJson,
	validateToolinfo
} from "../core/toolinfo-generator.js";
import { fromCsv, toCsv } from "../core/util.js";
import { button } from "../atoms/button.js";
import { accountSection } from "./account-workbench.js";

/** @typedef {{ key: string, toolName: string, projectName: string, label: string, record: Record<string, any>, developerUsernames: string[], sourceKind: string, identityVerified: boolean, isAuthor: boolean }} ToolinfoGeneratorEntry */

/** @param {unknown} value */
function cleanValue(value) {
	return String(value ?? "").trim();
}

/** @param {Tool} tool */
function toolProjects(tool) {
	return Array.isArray(tool.toolforgeProjects)
		? tool.toolforgeProjects.map((project) => cleanValue(project)).filter(Boolean)
		: [];
}

/** @param {any} payload @param {string} projectName */
function projectDevelopers(payload, projectName) {
	const project = (Array.isArray(payload?.toolforgeProjects) ? payload.toolforgeProjects : []).find(
		(/** @type {any} */ item) => cleanValue(item?.name).toLowerCase() === projectName.toLowerCase()
	);
	return Array.isArray(project?.developerUsernames)
		? project.developerUsernames.map((/** @type {unknown} */ username) => cleanValue(username)).filter(Boolean)
		: [];
}

/**
 * Build one deterministic choice per Toolforge project, preferring the record
 * whose canonical name already follows Toolhub's toolforge-$project convention.
 * @param {Tool[]} tools
 * @param {any} payload
 * @returns {ToolinfoGeneratorEntry[]}
 */
export function buildToolinfoGeneratorEntries(tools, payload) {
	/** @type {Map<string, ToolinfoGeneratorEntry>} */
	const byKey = new Map();
	const orderedTools = [...tools].sort((left, right) => {
		const leftProject = toolProjects(left)[0] || "";
		const rightProject = toolProjects(right)[0] || "";
		const leftExact = leftProject && left.name.toLowerCase() === `toolforge-${leftProject}`.toLowerCase();
		const rightExact = rightProject && right.name.toLowerCase() === `toolforge-${rightProject}`.toLowerCase();
		return Number(rightExact) - Number(leftExact) || left.name.localeCompare(right.name);
	});
	for (const tool of orderedTools) {
		const projects = toolProjects(tool);
		const projectName = projects.length === 1 ? projects[0] : "";
		const key = projectName ? `project:${projectName.toLowerCase()}` : `tool:${tool.name}`;
		if (byKey.has(key)) continue;
		byKey.set(key, {
			key,
			toolName: tool.name,
			projectName,
			label: `${tool.title} (${projectName || tool.name})`,
			record: structuredClone(tool.canonicalRecord || {}),
			developerUsernames: projectName ? projectDevelopers(payload, projectName) : [],
			sourceKind: tool.toolinfoSource?.sourceKind || "",
			identityVerified: Boolean(tool.authorVerified || projectName),
			isAuthor: (tool.accountRelationships || []).some(
				(relationship) =>
					(relationship.requestedRelationship || relationship.type) === "author" &&
					(relationship.isVerified || relationship.verificationStatus === "verified")
			)
		});
	}
	for (const project of Array.isArray(payload?.toolforgeProjects) ? payload.toolforgeProjects : []) {
		const projectName = cleanValue(project?.name);
		if (!projectName) continue;
		const key = `project:${projectName.toLowerCase()}`;
		if (byKey.has(key)) continue;
		byKey.set(key, {
			key,
			toolName: "",
			projectName,
			label: t("toolinfoGenerator.unregisteredProjectOption", "$1 (not in Toolhub)", projectName),
			record: {},
			developerUsernames: projectDevelopers(payload, projectName),
			sourceKind: "unregistered",
			identityVerified: true,
			isAuthor: false
		});
	}
	return [...byKey.values()].sort((left, right) => left.label.localeCompare(right.label));
}

/** @param {string} label @param {string} field @param {unknown} value @param {{ type?: string, hint?: string, required?: boolean, readonly?: boolean, placeholder?: string, idPrefix?: string }} [options] */
function input(label, field, value, options = {}) {
	const id = `${options.idPrefix || "toolinfo"}-${field}`;
	return `<label class="le__label" for="${id}">${esc(label)}${options.required ? ' <span class="le__req">*</span>' : ""}
		${options.hint ? `<span class="le__hint" id="${id}-hint">${esc(options.hint)}</span>` : ""}
		<input class="le__input" id="${id}" data-toolinfo-field="${esc(field)}" type="${esc(options.type || "text")}" value="${esc(value)}"${options.required ? " required" : ""}${options.readonly ? " readonly" : ""}${options.placeholder ? ` placeholder="${esc(options.placeholder)}"` : ""}${options.hint ? ` aria-describedby="${id}-hint"` : ""} />
	</label>`;
}

/** @param {string} label @param {string} field @param {unknown} value @param {{ hint?: string, required?: boolean, rows?: number, placeholder?: string }} [options] */
function area(label, field, value, options = {}) {
	const id = `toolinfo-${field}`;
	return `<label class="le__label" for="${id}">${esc(label)}${options.required ? ' <span class="le__req">*</span>' : ""}
		${options.hint ? `<span class="le__hint" id="${id}-hint">${esc(options.hint)}</span>` : ""}
		<textarea class="le__input" id="${id}" data-toolinfo-field="${esc(field)}" rows="${options.rows || 3}"${options.required ? " required" : ""}${options.placeholder ? ` placeholder="${esc(options.placeholder)}"` : ""}${options.hint ? ` aria-describedby="${id}-hint"` : ""}>${esc(value)}</textarea>
	</label>`;
}

/** @param {string} label @param {string} field @param {unknown} value */
function select(label, field, value) {
	return `<label class="le__label" for="toolinfo-${field}">${esc(label)}
		<select class="le__input" id="toolinfo-${field}" data-toolinfo-field="${esc(field)}">${TOOLINFO_TOOL_TYPES.map((option) => `<option value="${esc(option)}"${option === value ? " selected" : ""}>${esc(option || t("toolinfoGenerator.notSet", "Not set"))}</option>`).join("")}</select>
	</label>`;
}

/** @param {string} label @param {string} field @param {boolean} checked */
function check(label, field, checked) {
	return `<label class="le__check"><input type="checkbox" data-toolinfo-field="${esc(field)}"${checked ? " checked" : ""} /> ${esc(label)}</label>`;
}

let authorSequence = 0;

/** @param {Record<string, any>} author */
function authorRow(author = {}) {
	const idPrefix = `toolinfo-author-${authorSequence++}`;
	return `<div class="toolinfo-generator__author" data-toolinfo-author>
		${input(t("toolinfoGenerator.authorName", "Name"), "author-name", author.name || "", { required: true, idPrefix })}
		${input(t("toolinfoGenerator.authorWikiUsername", "Wikimedia username"), "author-wiki", author.wiki_username || "", { idPrefix })}
		${input(t("toolinfoGenerator.authorDeveloperUsername", "Developer username"), "author-developer", author.developer_username || "", { idPrefix })}
		${input(t("toolinfoGenerator.authorUrl", "Profile or homepage"), "author-url", author.url || "", { type: "url", idPrefix })}
		${input(t("toolinfoGenerator.authorEmail", "Public email"), "author-email", author.email || "", { type: "email", idPrefix })}
		${button(t("toolinfoGenerator.removeAuthor", "Remove author"), { variant: "ghost", type: "button", attrs: "data-toolinfo-author-remove" })}
	</div>`;
}

/** @param {ToolinfoGeneratorEntry} entry @param {any} identity */
function initialRecord(entry, identity) {
	return prefillToolinfo(entry.record, {
		projectName: entry.projectName,
		displayName: identity.displayName,
		wikiUsername: identity.wikiUsername,
		developerUsernames: entry.developerUsernames,
		identityVerified: entry.identityVerified,
		isAuthor: entry.isAuthor
	});
}

/** @param {ToolinfoGeneratorEntry} entry @param {any} identity */
function sourceNotice(entry, identity) {
	const generated = initialRecord(entry, identity);
	const renamed = entry.toolName && generated.name !== entry.toolName;
	if (renamed) {
		return t(
			"toolinfoGenerator.renameWarning",
			"This project is currently listed as $1. Publishing $2 creates a different Toolhub identity until the old source is retired; coordinate that migration before registration.",
			entry.toolName,
			generated.name
		);
	}
	if (entry.sourceKind === "toolsadmin") {
		return t(
			"toolinfoGenerator.toolsadminNotice",
			"This record comes from Toolsadmin. Commit the generated file to the project repository and register its raw URL; future core metadata changes then happen through repository commits. Toolsadmin itself cannot be edited from here."
		);
	}
	if (entry.sourceKind === "unregistered") {
		return t(
			"toolinfoGenerator.newProjectNotice",
			"This verified Toolforge project is not yet represented in your Toolhub records. Review every field, commit toolinfo.json to its repository, then register the raw file URL."
		);
	}
	return t(
		"toolinfoGenerator.repositoryNotice",
		"Core metadata is source-owned. Commit this file to the repository that publishes the registered Toolhub feed; community annotations remain separate in Toolhub."
	);
}

/** @param {ToolinfoGeneratorEntry} entry @param {any} identity */
function formHtml(entry, identity) {
	const value = initialRecord(entry, identity);
	const authors = Array.isArray(value.author) && value.author.length > 0 ? value.author : [{}];
	return `<div class="toolinfo-generator__notice" role="note">${esc(sourceNotice(entry, identity))}</div>
	<form class="toolinfo-generator__form" data-toolinfo-form novalidate>
		<fieldset><legend>${t("toolinfoGenerator.identityLegend", "Identity and description")}</legend>
			<div class="toolinfo-generator__grid">
				${input(t("toolinfoGenerator.schema", "Schema"), "_schema", TOOLINFO_SCHEMA_VERSION, { readonly: true })}
				${input(t("toolinfoGenerator.language", "Record language"), "_language", value._language, { required: true, placeholder: "en" })}
				${input(t("toolinfoGenerator.name", "Toolhub name"), "name", value.name, { required: true, readonly: true, hint: entry.projectName ? t("toolinfoGenerator.toolforgeNameHint", "Toolforge tools use toolforge-$project so crawler feeds deduplicate correctly.") : t("toolinfoGenerator.nameHint", "The stable Toolhub identifier is preserved from the current record.") })}
				${input(t("toolinfoGenerator.title", "Title"), "title", value.title, { required: true })}
				${input(t("toolinfoGenerator.subtitle", "Subtitle"), "subtitle", value.subtitle || "")}
			</div>
			${area(t("toolinfoGenerator.description", "Description"), "description", value.description, { required: true, rows: 4, hint: t("toolinfoGenerator.descriptionHint", "Describe what the tool does, who it helps, and when to use it.") })}
		</fieldset>
		<fieldset><legend>${t("toolinfoGenerator.peopleLegend", "People and organizations")}</legend>
			<p class="le__hint">${t("toolinfoGenerator.peopleHint", "Authors are the primary developers. Structured Wikimedia and developer usernames make identity verification deterministic; only publish public contact details.")}</p>
			<div class="toolinfo-generator__authors" data-toolinfo-authors>${authors.map((author) => authorRow(author)).join("")}</div>
			${button(t("toolinfoGenerator.addAuthor", "Add author"), { variant: "outline", type: "button", attrs: "data-toolinfo-author-add" })}
			<div class="toolinfo-generator__grid">
				${input(t("toolinfoGenerator.sponsor", "Sponsors (comma-separated)"), "sponsor", toCsv(value.sponsor || []))}
				${input(t("toolinfoGenerator.botUsername", "Bot Wikimedia username"), "bot_username", value.bot_username || "")}
			</div>
		</fieldset>
		<fieldset><legend>${t("toolinfoGenerator.linksLegend", "Links and documentation")}</legend>
			<div class="toolinfo-generator__grid">
				${input(t("toolinfoGenerator.url", "Tool or installation URL"), "url", value.url, { type: "url", required: true })}
				${input(t("toolinfoGenerator.repository", "Source repository"), "repository", value.repository || "", { type: "url" })}
				${input(t("toolinfoGenerator.apiUrl", "API URL"), "api_url", value.api_url || "", { type: "url" })}
				${input(t("toolinfoGenerator.bugtrackerUrl", "Bug tracker URL"), "bugtracker_url", value.bugtracker_url || "", { type: "url" })}
				${input(t("toolinfoGenerator.translateUrl", "Translation URL"), "translate_url", value.translate_url || "", { type: "url" })}
				${input(t("toolinfoGenerator.icon", "Commons File: icon URL"), "icon", value.icon || "", { type: "url" })}
				${input(t("toolinfoGenerator.openhubId", "OpenHub project ID"), "openhub_id", value.openhub_id || "")}
			</div>
			${area(t("toolinfoGenerator.alternateUrls", "Alternate URLs"), "url_alternates", formatMultilingualUrls(value.url_alternates), { rows: 2, hint: t("toolinfoGenerator.multilingualUrlHint", "One URL per line as language | https://… . A bare URL uses English.") })}
			<div class="toolinfo-generator__grid">
				${area(t("toolinfoGenerator.userDocs", "User documentation"), "user_docs_url", formatMultilingualUrls(value.user_docs_url), { rows: 2, hint: t("toolinfoGenerator.multilingualUrlHint", "One URL per line as language | https://… . A bare URL uses English.") })}
				${area(t("toolinfoGenerator.developerDocs", "Developer documentation"), "developer_docs_url", formatMultilingualUrls(value.developer_docs_url), { rows: 2, hint: t("toolinfoGenerator.multilingualUrlHint", "One URL per line as language | https://… . A bare URL uses English.") })}
				${area(t("toolinfoGenerator.feedbackUrl", "Feedback URL"), "feedback_url", formatMultilingualUrls(value.feedback_url), { rows: 2, hint: t("toolinfoGenerator.multilingualUrlHint", "One URL per line as language | https://… . A bare URL uses English.") })}
				${area(t("toolinfoGenerator.privacyPolicy", "Privacy policy URL"), "privacy_policy_url", formatMultilingualUrls(value.privacy_policy_url), { rows: 2, hint: t("toolinfoGenerator.multilingualUrlHint", "One URL per line as language | https://… . A bare URL uses English.") })}
			</div>
		</fieldset>
		<fieldset><legend>${t("toolinfoGenerator.discoveryLegend", "Discovery and compatibility")}</legend>
			<div class="toolinfo-generator__grid">
				${select(t("toolinfoGenerator.toolType", "Tool type"), "tool_type", value.tool_type || "")}
				${input(t("toolinfoGenerator.license", "License (SPDX identifier)"), "license", value.license || "", { placeholder: "GPL-3.0-or-later" })}
				${input(t("toolinfoGenerator.wikis", "Works on wikis (comma-separated)"), "for_wikis", toCsv(value.for_wikis || []), { hint: t("toolinfoGenerator.wikisHint", "Use hostnames, wildcards such as *.wikisource.org, or * for every wiki.") })}
				${input(t("toolinfoGenerator.uiLanguages", "Interface languages (comma-separated)"), "available_ui_languages", toCsv(value.available_ui_languages || []), { placeholder: "en, fr" })}
				${input(t("toolinfoGenerator.technologies", "Technologies (comma-separated)"), "technology_used", toCsv(value.technology_used || []))}
				${input(t("toolinfoGenerator.keywords", "Legacy keywords (comma-separated)"), "keywords", value.keywords || "", { hint: t("toolinfoGenerator.keywordsHint", "Schema 1.2.2 accepts this legacy string, but Toolhub marks it deprecated.") })}
			</div>
		</fieldset>
		<fieldset><legend>${t("toolinfoGenerator.statusLegend", "Lifecycle")}</legend>
			<div class="toolinfo-generator__checks">
				${check(t("toolinfoGenerator.experimental", "Experimental"), "experimental", Boolean(value.experimental))}
				${check(t("toolinfoGenerator.deprecated", "Deprecated"), "deprecated", Boolean(value.deprecated))}
			</div>
			${input(t("toolinfoGenerator.replacedBy", "Replacement tool URL"), "replaced_by", value.replaced_by || "", { type: "url", hint: t("toolinfoGenerator.replacedByHint", "Emitted only when Deprecated is selected.") })}
		</fieldset>
		<div class="toolinfo-generator__output">
			<div>
				<h3>${t("toolinfoGenerator.preview", "Generated toolinfo.json")}</h3>
				<p class="le__hint">${t("toolinfoGenerator.previewHint", "Commit this exact filename at a stable public repository URL. Nothing is published automatically.")}</p>
			</div>
			<textarea class="le__input toolinfo-generator__preview" data-toolinfo-preview rows="24" readonly spellcheck="false" aria-label="${esc(t("toolinfoGenerator.preview", "Generated toolinfo.json"))}"></textarea>
			<div class="toolinfo-generator__validation" data-toolinfo-validation aria-live="polite"></div>
			<div class="toolinfo-generator__actions">
				${button(t("toolinfoGenerator.copy", "Copy JSON"), { variant: "primary", type: "button", attrs: "data-toolinfo-copy" })}
				${button(t("toolinfoGenerator.download", "Download toolinfo.json"), { variant: "outline", type: "button", attrs: "data-toolinfo-download" })}
				${button(t("toolinfoGenerator.reset", "Reset prefilled fields"), { variant: "ghost", type: "button", attrs: "data-toolinfo-reset" })}
			</div>
			<p class="at__result" data-toolinfo-result aria-live="polite"></p>
			<p class="le__hint">${t("toolinfoGenerator.schemaLinks", "Reference:")} <a href="${TOOLINFO_DATA_MODEL_URL}" target="_blank" rel="noopener">${t("toolinfoGenerator.dataModel", "Toolhub data model")}</a> · <a href="${TOOLINFO_SCHEMA_URL}" target="_blank" rel="noopener">${t("toolinfoGenerator.schemaDefinition", "schema 1.2.2 definition")}</a></p>
		</div>
	</form>`;
}

/** @param {HTMLFormElement} form @param {ToolinfoGeneratorEntry} entry @param {any} identity */
function collect(form, entry, identity) {
	/** @param {string} field */
	const control = (field) =>
		/** @type {HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null} */ (
			form.querySelector(`[data-toolinfo-field="${field}"]`)
		);
	/** @param {string} field */
	const value = (field) => cleanValue(control(field)?.value);
	/** @param {string} field */
	const checked = (field) => Boolean(/** @type {HTMLInputElement | null} */ (control(field))?.checked);
	const base = initialRecord(entry, identity);
	for (const field of [
		"_language",
		"name",
		"title",
		"subtitle",
		"description",
		"url",
		"repository",
		"openhub_id",
		"bot_username",
		"icon",
		"license",
		"tool_type",
		"api_url",
		"translate_url",
		"bugtracker_url",
		"replaced_by",
		"keywords"
	]) {
		base[field] = value(field);
	}
	for (const field of ["for_wikis", "sponsor", "available_ui_languages", "technology_used"]) {
		base[field] = fromCsv(value(field));
	}
	base.url_alternates = parseMultilingualUrls(value("url_alternates"), { alwaysArray: true });
	for (const field of ["developer_docs_url", "user_docs_url", "feedback_url", "privacy_policy_url"]) {
		base[field] = parseMultilingualUrls(value(field));
	}
	base.experimental = checked("experimental");
	base.deprecated = checked("deprecated");
	base.author = $$("[data-toolinfo-author]", form)
		.map((row) => ({
			name: cleanValue(
				/** @type {HTMLInputElement | null} */ (row.querySelector('[data-toolinfo-field="author-name"]'))?.value
			),
			wiki_username: cleanValue(
				/** @type {HTMLInputElement | null} */ (row.querySelector('[data-toolinfo-field="author-wiki"]'))?.value
			),
			developer_username: cleanValue(
				/** @type {HTMLInputElement | null} */ (row.querySelector('[data-toolinfo-field="author-developer"]'))
					?.value
			),
			url: cleanValue(
				/** @type {HTMLInputElement | null} */ (row.querySelector('[data-toolinfo-field="author-url"]'))?.value
			),
			email: cleanValue(
				/** @type {HTMLInputElement | null} */ (row.querySelector('[data-toolinfo-field="author-email"]'))
					?.value
			)
		}))
		.filter((author) => author.name);
	return base;
}

/** @param {HTMLElement} root @param {ToolinfoGeneratorEntry} entry @param {any} identity */
function mountForm(root, entry, identity) {
	const form = /** @type {HTMLFormElement | null} */ (root.querySelector("[data-toolinfo-form]"));
	if (!form) return;
	const refresh = () => {
		const record = collect(form, entry, identity);
		const errors = validateToolinfo(record, { projectName: entry.projectName });
		const preview = /** @type {HTMLTextAreaElement | null} */ (form.querySelector("[data-toolinfo-preview]"));
		if (preview) preview.value = toolinfoJson(record);
		const validation = form.querySelector("[data-toolinfo-validation]");
		if (validation) {
			validation.innerHTML =
				errors.length > 0
					? `<strong>${t("toolinfoGenerator.fixErrors", "Fix these fields before publishing:")}</strong><ul>${errors.map((error) => `<li>${esc(error)}</li>`).join("")}</ul>`
					: `<span class="sync-badge sync-badge--review-approved">${t("toolinfoGenerator.valid", "Valid for schema 1.2.2")}</span>`;
		}
		for (const action of $$("[data-toolinfo-copy], [data-toolinfo-download]", form)) {
			/** @type {HTMLButtonElement} */ (action).disabled = errors.length > 0;
		}
		return { record, errors };
	};
	form.addEventListener("submit", (event) => event.preventDefault());
	form.addEventListener("input", refresh);
	form.querySelector("[data-toolinfo-author-add]")?.addEventListener("click", () => {
		const authors = form.querySelector("[data-toolinfo-authors]");
		if (authors) authors.insertAdjacentHTML("beforeend", authorRow());
		refresh();
	});
	form.addEventListener("click", (event) => {
		const target = /** @type {HTMLElement} */ (event.target);
		const remove = target.closest("[data-toolinfo-author-remove]");
		if (!remove) return;
		remove.closest("[data-toolinfo-author]")?.remove();
		refresh();
	});
	form.querySelector("[data-toolinfo-copy]")?.addEventListener("click", async () => {
		const { record, errors } = refresh();
		if (errors.length > 0) return;
		await navigator.clipboard.writeText(toolinfoJson(record));
		const result = form.querySelector("[data-toolinfo-result]");
		if (result) result.textContent = t("toolinfoGenerator.copied", "toolinfo.json copied.");
	});
	form.querySelector("[data-toolinfo-download]")?.addEventListener("click", () => {
		const { record, errors } = refresh();
		if (errors.length > 0) return;
		const url = URL.createObjectURL(new Blob([toolinfoJson(record)], { type: "application/json" }));
		const link = document.createElement("a");
		link.href = url;
		link.download = "toolinfo.json";
		link.click();
		URL.revokeObjectURL(url);
	});
	form.querySelector("[data-toolinfo-reset]")?.addEventListener("click", () => {
		root.innerHTML = formHtml(entry, identity);
		mountForm(root, entry, identity);
	});
	refresh();
}

/**
 * @param {ToolinfoGeneratorEntry[]} entries
 * @param {{ displayName?: string, wikiUsername?: string }} identity
 */
export function toolinfoGeneratorWorkspace(entries, identity) {
	const options = entries.map((entry) => `<option value="${esc(entry.key)}">${esc(entry.label)}</option>`).join("");
	const body =
		entries.length > 0
			? `<label class="le__label" for="toolinfo-generator-choice">${t("toolinfoGenerator.choose", "Tool or Toolforge project")}
			<select class="le__input" id="toolinfo-generator-choice" data-toolinfo-choice><option value="">${t("toolinfoGenerator.choosePlaceholder", "Choose one to begin")}</option>${options}</select>
		</label><div data-toolinfo-editor hidden></div>`
			: `<p class="empty">${t("toolinfoGenerator.empty", "Connect a Toolforge account or add a Toolhub relationship to generate metadata.")}</p>`;
	const html = accountSection({
		id: "toolinfo-generator-title",
		title: t("toolinfoGenerator.generatorTitle", "Create repository toolinfo.json"),
		intro: t(
			"toolinfoGenerator.intro",
			"Generate the complete core metadata file from your verified identity, Toolforge projects, and current Toolhub data. Review it before committing it to a public repository."
		),
		body,
		className: "toolinfo-generator"
	});
	const entryByKey = new Map(entries.map((entry) => [entry.key, entry]));
	const entryKeyByTool = new Map(
		entries.filter((entry) => entry.toolName).map((entry) => [entry.toolName, entry.key])
	);
	return {
		html,
		entryKeyByTool,
		mount() {
			const choice = /** @type {HTMLSelectElement | null} */ ($("[data-toolinfo-choice]"));
			const editor = $("[data-toolinfo-editor]");
			if (!choice || !editor) return;
			/** @param {string} key */
			const open = (key) => {
				const entry = entryByKey.get(key);
				if (!entry) return;
				choice.value = key;
				editor.hidden = false;
				editor.innerHTML = formHtml(entry, identity);
				mountForm(editor, entry, identity);
			};
			choice.addEventListener("change", () => {
				if (choice.value) open(choice.value);
				else editor.hidden = true;
			});
			const workbench = choice.closest(".account-workbench__body") || document;
			workbench.addEventListener("click", (event) => {
				const target = /** @type {HTMLElement} */ (event.target);
				const trigger = target.closest("[data-toolinfo-open]");
				if (!trigger) return;
				open(cleanValue(trigger.getAttribute("data-toolinfo-open")));
				editor.scrollIntoView({ behavior: "smooth", block: "start" });
			});
		}
	};
}
