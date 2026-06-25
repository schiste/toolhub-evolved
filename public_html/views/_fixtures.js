// SPDX-License-Identifier: GPL-3.0-or-later

export const FIXTURE_TOOL = {
	name: "styleguide-citation-helper",
	title: "Citation Helper",
	description:
		"Suggests reliable source templates, checks missing citations, and helps editors add references without leaving the page.",
	url: "https://example.org/tools/citation-helper",
	icon: "https://commons.wikimedia.org/wiki/File:OOjs_UI_icon_code.svg",
	keywords: ["citations", "references", "editing", "quality", "wikidata", "sources"],
	maintainer: "Ada Lovelace",
	authors: ["Ada Lovelace", "Grace Hopper"],
	toolType: "web app",
	license: "GPL-3.0-or-later",
	repository: "https://github.com/example/citation-helper",
	apiUrl: "https://example.org/tools/citation-helper/api",
	technologyUsed: ["JavaScript", "Python", "Toolforge"],
	audiences: ["editors", "organizers"],
	tasks: ["editing", "patrolling"],
	forWikis: ["*"],
	uiLanguages: ["en", "fr", "es", "ar"],
	userDocs: "https://example.org/tools/citation-helper/docs",
	devDocs: "https://example.org/tools/citation-helper/developers",
	feedback: "https://example.org/tools/citation-helper/feedback",
	bugtracker: "https://github.com/example/citation-helper/issues",
	translate: "https://translatewiki.net/wiki/Translating:Citation_Helper",
	deprecated: false,
	experimental: false,
	modified: "2026-05-12T14:30:00Z",
	origin: "crawler",
	weeklyViews: 1842,
	status: { level: "green", label: "Healthy" }
};

export const FIXTURE_TOOL_DEPRECATED = {
	...FIXTURE_TOOL,
	name: "styleguide-deprecated-citation-helper",
	title: "Legacy Citation Helper",
	description: "A retired citation workflow kept visible so maintainers can point editors to the replacement tool.",
	deprecated: true,
	experimental: false,
	modified: "2025-11-04T09:15:00Z",
	weeklyViews: 128,
	status: { level: "red", label: "Deprecated" }
};

export const FIXTURE_TOOL_EXPERIMENTAL = {
	...FIXTURE_TOOL,
	name: "styleguide-experimental-citation-helper",
	title: "Citation Helper Labs",
	description: "An early test of reference recommendations using opt-in editor feedback and limited wiki coverage.",
	deprecated: false,
	experimental: true,
	modified: "2026-06-01T16:45:00Z",
	weeklyViews: 612,
	status: { level: "yellow", label: "Experimental" }
};

export const FIXTURE_LIST = {
	id: "styleguide-campaign-toolkit",
	title: "Campaign organizer toolkit",
	description:
		"A compact set of tools for preparing edit-a-thons, checking article quality, and following up after an event.",
	toolCount: 3,
	tools: [FIXTURE_TOOL, FIXTURE_TOOL_EXPERIMENTAL, FIXTURE_TOOL_DEPRECATED],
	featured: true,
	demo: true
};

export const FIXTURE_FACET_GROUP = { field: "tool_type", label: "Tool type" };

export const FIXTURE_FACETS = {
	_filter_tool_type: {
		tool_type: {
			meta: { param: "tool_type" },
			buckets: [
				{ key: "web app", doc_count: 128 },
				{ key: "bot", doc_count: 74 },
				{ key: "user script", doc_count: 52 },
				{ key: "gadget", doc_count: 31 }
			]
		}
	}
};

export const FIXTURE_SELECTED_FACETS = new Set(["tool_type=web app"]);
