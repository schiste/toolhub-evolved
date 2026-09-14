// SPDX-License-Identifier: GPL-3.0-or-later
import { t } from "./i18n.js";

/**
 * Build the official Toolhub payload for a core tool write.
 *
 * The form and the official API use different field names; keeping that
 * translation separate from event wiring makes create and edit submissions
 * share one contract.
 *
 * @param {string} name
 * @param {Record<string, any>} fields
 * @param {{ includeName?: boolean }} [options]
 * @returns {Record<string, any>}
 */
export function officialToolPayload(name, fields, { includeName = true } = {}) {
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

/** @param {Tool} current @param {Record<string, any>} fields */
export function localCurationPatch(current, fields) {
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
 * @returns {import("../molecules/change-review.js").ChangeDescriptor[]}
 */
export function toolCoreChangeDescriptors(current, fields) {
	return /** @type {import("../molecules/change-review.js").ChangeDescriptor[]} */ ([
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

/** @param {{ audiences: string[]; tasks: string[]; toolType: string | null; icon: string | null }} anno */
export function officialAnnotationPayload(anno) {
	/** @type {{ audiences: string[]; tasks: string[]; tool_type?: string; icon?: string; comment: string }} */
	const payload = {
		audiences: anno.audiences,
		tasks: anno.tasks,
		comment: "Annotated from Toolhub Evolved"
	};
	if (anno.toolType) payload.tool_type = anno.toolType;
	if (anno.icon) payload.icon = anno.icon;
	return payload;
}

/**
 * @param {Tool} current
 * @param {{ audiences: string[]; tasks: string[]; toolType: string | null; icon: string | null }} anno
 * @returns {import("../molecules/change-review.js").ChangeDescriptor[]}
 */
export function annotationChangeDescriptors(current, anno) {
	return /** @type {import("../molecules/change-review.js").ChangeDescriptor[]} */ ([
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
