// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { t } from "../lib/core/i18n.js";

/* ---- Feature status index --------------------------------------------- */
// Single source of truth for every Evolved feature and hybrid integration path.
export const EXPERIMENTS = [
	{
		group: t("experiments.groupLiveReads", "Live Toolhub read surfaces"),
		items: [
			{
				name: t("experiments.homeDiscoveryName", "Home and discovery"),
				what: t(
					"experiments.homeDiscoveryWhat",
					"Land on a useful catalog overview with intent filters, featured lists, recent tools, and most-listed tools."
				),
				current: t(
					"experiments.homeDiscoveryCurrent",
					"Home sections read live Toolhub lists/search data and degrade each panel independently if one upstream call fails."
				),
				need: t(
					"experiments.homeDiscoveryNeed",
					"Live /api/lists/ and /api/search/tools/ reads through the shared proxy cache"
				),
				tryHref: "/",
				tryLabel: t("experiments.homeDiscoveryTry", "Open home")
			},
			{
				name: t("experiments.searchBrowseName", "Search and browse"),
				what: t("experiments.searchBrowseWhat", "Search, facet, sort, paginate, and filter Toolhub tools."),
				current: t(
					"experiments.searchBrowseCurrent",
					"Official Toolhub search remains primary; approved Evolved-local public tools appear only in a clearly labeled local strip."
				),
				need: t(
					"experiments.searchBrowseNeed",
					"GET /api/search/tools/ plus Evolved /v1/search/tools/ federation"
				),
				tryHref: "/search",
				tryLabel: t("experiments.searchBrowseTry", "Browse tools")
			},
			{
				name: t("experiments.toolDetailsName", "Tool detail and history"),
				what: t(
					"experiments.toolDetailsWhat",
					"Inspect tool metadata, links, authors, revisions, related tools, completeness, and a local neighborhood map."
				),
				current: t(
					"experiments.toolDetailsCurrent",
					"Detail and revision data stay live from Toolhub; Evolved overlays add provenance, signals, media, and related-tool UI without replacing canonical records."
				),
				need: t(
					"experiments.toolDetailsNeed",
					"GET /api/tools/{name}/, revisions, local signal/media endpoints, and graph helpers"
				)
			},
			{
				name: t("experiments.listReadName", "Lists and collections"),
				what: t("experiments.listReadWhat", "Browse published lists and inspect the tools inside a list."),
				current: t(
					"experiments.listReadCurrent",
					"Official Toolhub lists are read live; signed-in local drafts and fallbacks are merged only where clearly labeled."
				),
				need: t(
					"experiments.listReadNeed",
					"GET /api/lists/ and /api/lists/{id}/ plus local list overlay merge"
				),
				tryHref: "/lists",
				tryLabel: t("experiments.listReadTry", "Open lists")
			},
			{
				name: t("experiments.recentTableName", "Recent changes table"),
				what: t(
					"experiments.recentTableWhat",
					"Scan recent activity in a sortable/filterable table with owner, last-updated-by, action, review state, and expandable comments."
				),
				current: t(
					"experiments.recentTableCurrent",
					"Official /api/recent/ rows render first; Evolved-local activity rows are merged in, and tool owners are enriched progressively through a shared owner cache."
				),
				need: t("experiments.recentTableNeed", "GET /api/recent/, /v1/recent/owners/, and local activity rows"),
				tryHref: "/recent",
				tryLabel: t("experiments.recentTableTry", "Recent changes")
			},
			{
				name: t("experiments.operationalViewsName", "Members, crawler history, and audit logs"),
				what: t(
					"experiments.operationalViewsWhat",
					"Read projected official Toolhub accounts, crawler run history, and catalog audit activity."
				),
				current: t(
					"experiments.operationalViewsCurrent",
					"These parity views read official Toolhub endpoints and merge Evolved activity only for local write history where relevant."
				),
				need: t("experiments.operationalViewsNeed", "GET /api/users/, /api/crawler/runs/, and /api/auditlogs/"),
				tryHref: "/people",
				tryLabel: t("experiments.operationalViewsTry", "Open community directory")
			},
			{
				name: t("experiments.toolMapName", "Tool map and related tools"),
				what: t(
					"experiments.toolMapWhat",
					"Explore similar tools visually and open quick views from graph nodes or related-tool rows."
				),
				current: t(
					"experiments.toolMapCurrent",
					"The map defaults to 250 tools, paints its shell before data arrives, and reads a server-derived payload from the local canonical Toolhub cache; larger views remain explicit user choices."
				),
				need: t(
					"experiments.toolMapNeed",
					"Shared ToolsDB graph payload cache with stale background refresh and client-side canvas rendering"
				),
				tryHref: "/graph",
				tryLabel: t("experiments.toolMapTry", "Open map")
			},
			{
				name: t("experiments.docsPagesName", "API explorer, toolinfo, and project docs"),
				what: t(
					"experiments.docsPagesWhat",
					"Run curated read-only API requests, inspect responses, copy examples, and read toolinfo/project documentation."
				),
				current: t(
					"experiments.docsPagesCurrent",
					"The /api-docs page includes same-origin endpoint forms, formatted JSON output, schema links, and official Toolhub/Wikimedia documentation links."
				),
				need: t("experiments.docsPagesNeed", "Curated GET /api/... explorer plus static documentation pages"),
				tryHref: "/api-docs",
				tryLabel: t("experiments.docsPagesTry", "API explorer")
			}
		]
	},
	{
		group: t("experiments.groupIdentity", "Identity & account"),
		items: [
			{
				name: t("experiments.signinName", "Toolhub sign-in"),
				what: t("experiments.signinWhat", "Sign in through Toolhub OAuth and sign out."),
				current: t("experiments.signinCurrent", "Official Toolhub OAuth plus an Evolved server session."),
				need: t("experiments.signinNeed", "An approved Toolhub OAuth application.")
			},
			{
				name: t("experiments.permissionsName", "Evolved roles and permissions"),
				what: t(
					"experiments.permissionsWhat",
					"Use Toolhub identity for local permissions without implying official Toolhub admin rights."
				),
				current: t(
					"experiments.permissionsCurrent",
					"Local baseline, reviewer/moderator, and admin/operator roles flow through one backend can(user, action, resource) policy entrypoint."
				),
				need: t(
					"experiments.permissionsNeed",
					"Toolhub /api/user/ mapping, Evolved role env vars, and backend authz policy"
				)
			},
			{
				name: t("experiments.developerSettingsName", "Developer settings"),
				what: t(
					"experiments.developerSettingsWhat",
					"Open official Toolhub developer links and manage Evolved signed-toolinfo public keys."
				),
				current: t(
					"experiments.developerSettingsCurrent",
					"Official OAuth app/token tasks link back to Toolhub; Evolved stores local Ed25519 public keys and signing payload helpers."
				),
				need: t(
					"experiments.developerSettingsNeed",
					"Local author-key API plus official Toolhub developer settings"
				),
				tryHref: "/developer-settings",
				tryLabel: t("experiments.developerSettingsTry", "Developer settings")
			},
			{
				name: t("experiments.myToolsName", "My tools workspace"),
				what: t(
					"experiments.myToolsWhat",
					"Review tools associated with your signed-in Toolhub identity, register toolinfo sources, and analyze source metadata from one place."
				),
				current: t(
					"experiments.myToolsCurrent",
					"Official Toolhub search provides tool candidates; Evolved adds per-tool evidence, indexed crawler feed sources, root/sitemap discovery, and source-analysis reports."
				),
				need: t(
					"experiments.myToolsNeed",
					"Author-claim table, resolver endpoint, verification providers, official crawler source index, registration workflow, source-analysis reports, and discovery cache"
				),
				tryHref: "/my-tools",
				tryLabel: t("experiments.myToolsTry", "My tools")
			},
			{
				name: t("experiments.maintainerSummaryName", "Maintainer summary and activity"),
				what: t(
					"experiments.maintainerSummaryWhat",
					"Distinguish tools with active maintainers from tools whose source and maintainers both appear stale."
				),
				current: t(
					"experiments.maintainerSummaryCurrent",
					"Evolved derives public-safe people summaries from official Toolhub metadata, verified evidence, and person-keyed public contribution activity without creating a competing canonical catalog."
				),
				need: t(
					"experiments.maintainerSummaryNeed",
					"`tool_relationship_evidence`, `person_tool_relationships`, `person_activity_summaries`, and public GET /v1/people/tools/{name}/"
				),
				tryHref: "/api-docs",
				tryLabel: t("experiments.docsPagesTry", "API explorer")
			},
			{
				name: t("experiments.publicProfilesName", "People, profiles, and relationship claims"),
				what: t(
					"experiments.publicProfilesWhat",
					"Discover people, publish an Evolved profile, and prove author, maintainer, or Toolhub record-authority relationships."
				),
				current: t(
					"experiments.publicProfilesCurrent",
					"Public profiles use immutable person ids and role-grouped Toolhub tools. Signed-in users can claim through listed-author association, Toolforge membership, URL control, signed toolinfo, or automatic official-write evidence."
				),
				need: t(
					"experiments.publicProfilesNeed",
					"Person-centric APIs, Evolved profile storage, unified claim workflow, evidence reconciliation, and canonical Toolhub reads"
				),
				tryHref: "/people",
				tryLabel: t("experiments.publicProfilesTry", "Browse people")
			},
			{
				name: t("experiments.sourceAnalysisName", "Source code analysis"),
				what: t(
					"experiments.sourceAnalysisWhat",
					"Extract project, API, access-right, dependency, repository-context, OAuth-scope, technology, assessment, and warning signals from maintainer-submitted source bundles."
				),
				current: t(
					"experiments.sourceAnalysisCurrent",
					"My tools accepts selected source files, repository context JSON, or a JSON file bundle, stores redacted evidence reports, and returns toolinfo plus Evolved dependency and assessment metadata suggestions for maintainer review."
				),
				need: t(
					"experiments.sourceAnalysisNeed",
					"Deterministic analyzer, manifest and lockfile dependency extractors, repository context builder, source_analysis_reports table, private /v1/source-analysis/ endpoints, CLI, and account-workbench UI"
				),
				tryHref: "/my-tools",
				tryLabel: t("experiments.myToolsTry", "My tools")
			},
			{
				name: t("experiments.accountDataName", "Preferences"),
				what: t(
					"experiments.accountDataWhat",
					"Manage Evolved-specific preferences and local data tied to your Toolhub sign-in."
				),
				current: t(
					"experiments.accountDataCurrent",
					"Users can edit Evolved-owned public profile content, review relationship-claim history, export local data, and delete it without touching official Toolhub."
				),
				need: t(
					"experiments.accountDataNeed",
					"GET/PUT /v1/me/profile/, GET /v1/me/claims/, GET /v1/user/export/, and DELETE /v1/user/evolved-data/"
				),
				tryHref: "/preferences",
				tryLabel: t("experiments.accountDataTry", "Preferences")
			},
			{
				name: t("experiments.transparencyName", "Hybrid transparency notice"),
				what: t(
					"experiments.transparencyWhat",
					"Understand when data is live Toolhub data, Evolved-local data, or an official-first write fallback."
				),
				current: t(
					"experiments.transparencyCurrent",
					"A compact dismissible site notice links to Feature status and Rules of Engagement; dismissal is stored only in localStorage."
				),
				need: t(
					"experiments.transparencyNeed",
					"Default-visible site notice, field labels, and Rules of Engagement page"
				),
				tryHref: "/rules-of-engagement",
				tryLabel: t("experiments.transparencyTry", "Rules")
			},
			{
				name: t("experiments.issueReportingName", "Authenticated issue reporting"),
				what: t(
					"experiments.issueReportingWhat",
					"Open a prefilled report drawer, review page diagnostics, add details, and publish an approved issue to GitHub."
				),
				current: t(
					"experiments.issueReportingCurrent",
					"All visitors can open a right-side pushed support drawer; signed-in users get route-scoped diagnostics, an editable review step, server-side publishing, and an issue-number receipt."
				),
				need: t(
					"experiments.issueReportingNeed",
					"Authenticated /v1/issue-reports/ write endpoint, server-only GitHub token, bounded diagnostics collector, and issue idempotency ledger"
				)
			}
		]
	},
	{
		group: t("experiments.groupContributions", "Your contributions — official when possible, local when needed"),
		items: [
			{
				name: t("experiments.favoritesName", "Favorites"),
				what: t("experiments.favoritesWhat", "Save tools and see them collected in one place."),
				current: t(
					"experiments.favoritesCurrent",
					"Signed-in changes write to Toolhub favorites; Evolved keeps a local cache/fallback."
				),
				need: "POST / DELETE /api/user/favorites/",
				tryHref: "/favorites",
				tryLabel: t("experiments.favoritesTry", "Open favorites")
			},
			{
				name: t("experiments.listsName", "Lists"),
				what: t("experiments.listsWhat", "Create, edit, reorder and delete lists, and add tools to them."),
				current: t(
					"experiments.listsCurrent",
					"Official list create/edit/delete when permitted; local draft lists remain as fallback."
				),
				need: "POST / PUT / DELETE /api/lists/",
				tryHref: "/my-lists",
				tryLabel: t("experiments.listsTry", "Your lists")
			},
			{
				name: t("experiments.toolRegistrationName", "Tool registration workspace"),
				what: t(
					"experiments.toolRegistrationWhat",
					"Register toolinfo sources and manage local tool records from My tools."
				),
				current: t(
					"experiments.toolRegistrationCurrent",
					"Toolinfo discovery and official crawler registration now live inside the My tools workspace."
				),
				need: "POST /v1/crawler/toolinfo-discovery/ and official crawler source registration",
				tryHref: "/my-tools",
				tryLabel: t("experiments.myToolsTry", "My tools")
			},
			{
				name: t("experiments.editToolName", "Edit a tool"),
				what: t("experiments.editToolWhat", "Change a tool's core fields (title, description, links…)."),
				current: t(
					"experiments.editToolCurrent",
					"Official PUT when Toolhub permits; rejected edits remain local overlays."
				),
				need: "PUT /api/tools/{name}/ and edit permissions"
			},
			{
				name: t("experiments.editAnnosName", "Edit annotations"),
				what: t("experiments.editAnnosWhat", "Add community annotations (audiences, tasks, type, icon)."),
				current: t(
					"experiments.editAnnosCurrent",
					"Official annotation PUT first; rejected annotations remain local overlays."
				),
				need: "PUT /api/tools/{name}/annotations/"
			},
			{
				name: t("experiments.writeReviewName", "Review changes and delete"),
				what: t(
					"experiments.writeReviewWhat",
					"Preview field-level changes before saving and delete tools/lists from the relevant detail or edit page."
				),
				current: t(
					"experiments.writeReviewCurrent",
					"Forms show diffs before official-first writes; supported deletes call Toolhub and report rejection details without losing local state."
				),
				need: t("experiments.writeReviewNeed", "Shared write lifecycle, field validation, and delete adapters")
			},
			{
				name: t("experiments.syncControlsName", "Provenance and sync controls"),
				what: t(
					"experiments.syncControlsWhat",
					"See whether each local change is published to Toolhub, saved locally, rejected by Toolhub, pending review, retryable, or discardable."
				),
				current: t(
					"experiments.syncControlsCurrent",
					"Common badges, field-level provenance labels, validation-error lists, retry buttons, and discard buttons are shared across tool/list write flows."
				),
				need: t("experiments.syncControlsNeed", "Shared sync-status UI plus retry/discard backend endpoints")
			},
			{
				name: t("experiments.toolinfoEnrichmentName", "Create-time toolinfo enrichment"),
				what: t(
					"experiments.toolinfoEnrichmentWhat",
					"Fetch a submitted toolinfo.json during tool creation to fill available fields and store Evolved evidence."
				),
				current: t(
					"experiments.toolinfoEnrichmentCurrent",
					"The write pipeline can safely fetch a declared toolinfo URL once, merge missing optional fields, and record crawler evidence before fallback or official publish."
				),
				need: t(
					"experiments.toolinfoEnrichmentNeed",
					"Crawler-safe fetch validation, size limits, and local evidence metadata"
				)
			},
			{
				name: t("experiments.crawlerName", "Toolinfo registration"),
				what: t(
					"experiments.crawlerWhat",
					"Paste a tool homepage or direct toolinfo.json URL, or paste toolinfo to ingest tools."
				),
				current: t(
					"experiments.crawlerCurrent",
					"My tools discovers root/sitemap toolinfo.json URLs before official-first Toolhub registration, and a scheduled source index maps official crawler feeds back to tools."
				),
				need: t(
					"experiments.crawlerNeed",
					"Toolhub crawler permissions, official crawler source index, safe toolinfo discovery, and local fallback storage"
				),
				tryHref: "/my-tools",
				tryLabel: t("experiments.crawlerTry", "My tools")
			},
			{
				name: t("experiments.feedsName", "Activity feeds"),
				what: t(
					"experiments.feedsWhat",
					"Evolved edits appear at the top of Recent changes, Audit logs and tool history."
				),
				current: t("experiments.feedsCurrent", "Local revision/audit rows merged on top of the live feeds."),
				need: t("experiments.feedsNeed", "Server-side write side-effects"),
				tryHref: "/recent",
				tryLabel: t("experiments.feedsTry", "Recent changes")
			}
		]
	},
	{
		group: t("experiments.groupSignals", "Evolved-only signals — real Evolved data only"),
		items: [
			{
				name: t("experiments.popularityName", "Popularity"),
				what: t("experiments.popularityWhat", "View counts and a popularity ranking."),
				current: t(
					"experiments.popularityCurrent",
					"Public popularity ranking remains hidden; signed-in tool views now feed real Evolved aggregate events."
				),
				need: t("experiments.popularityNeed", "Daily aggregate rollups and privacy thresholds")
			},
			{
				name: t("experiments.healthName", "Operational health"),
				what: t("experiments.healthWhat", "A Healthy / Degraded / Down status pill."),
				current: t(
					"experiments.healthCurrent",
					"Signed-in users can submit health targets; approved Evolved health records show only real checked status."
				),
				need: t("experiments.healthNeed", "Scheduled health-check job and daily rollups")
			},
			{
				name: t("experiments.thanksName", "Thanks"),
				what: t(
					"experiments.thanksWhat",
					"A lightweight way to appreciate useful tools without rating maintainers' work."
				),
				current: t(
					"experiments.thanksCurrent",
					"Signed-in users can thank a tool; approved counts are stored in Evolved and labeled as Evolved data."
				),
				need: t("experiments.thanksNeed", "Burst detection and aggregate daily rollups")
			},
			{
				name: t("experiments.usageName", "30-day usage"),
				what: t("experiments.usageWhat", "An “editors used this in the last 30 days” figure."),
				current: t(
					"experiments.usageCurrent",
					"Signed-in tool-page interactions are counted as privacy-limited 30-day Evolved usage."
				),
				need: t("experiments.usageNeed", "Daily aggregate rollups and minimum-count suppression")
			},
			{
				name: t("experiments.screenshotsName", "Screenshots"),
				what: t("experiments.screenshotsWhat", "A preview image strip on the tool page."),
				current: t(
					"experiments.screenshotsCurrent",
					"Signed-in users can submit URL-based screenshots with license/source metadata; approved Evolved media renders on tool pages."
				),
				need: t("experiments.screenshotsNeed", "Durable upload/storage pipeline")
			},
			{
				name: t("experiments.localPublicToolsName", "Public local tools and toolinfo feed"),
				what: t(
					"experiments.localPublicToolsWhat",
					"Expose approved Evolved-local tool records to search and to Toolhub-compatible crawler ingestion."
				),
				current: t(
					"experiments.localPublicToolsCurrent",
					"Approved public local records appear in /v1/search/tools/ and the Evolved /toolinfo.json feed, always labeled as Evolved data."
				),
				need: t(
					"experiments.localPublicToolsNeed",
					"Moderated local tool records plus public toolinfo.json feed"
				)
			},
			{
				name: t("experiments.moderationName", "Moderation and review queue"),
				what: t(
					"experiments.moderationWhat",
					"Review public Evolved-owned records before they appear as public Evolved data."
				),
				current: t(
					"experiments.moderationCurrent",
					"Reviewer/operator roles can list and update pending public local tools, health targets, media, and thanks through moderation endpoints."
				),
				need: t(
					"experiments.moderationNeed",
					"Evolved-only reviewer policy and /v1/moderation/public-data/ endpoints"
				)
			}
		]
	},
	{
		group: t("experiments.groupPerformance", "Performance, resilience, and platform"),
		items: [
			{
				name: t("experiments.appShellName", "Immediate app shell"),
				what: t(
					"experiments.appShellWhat",
					"Show the header, site notice, clean loading panel, and footer before live Toolhub data finishes loading."
				),
				current: t(
					"experiments.appShellCurrent",
					"Critical shell CSS is inline, route modules are lazy-loaded, and failed dynamic imports retry once instead of blanking the page."
				),
				need: t("experiments.appShellNeed", "Critical CSS, route splitting, and resilient router loading")
			},
			{
				name: t("experiments.apiCacheName", "Shared Toolhub API cache"),
				what: t("experiments.apiCacheWhat", "Make anonymous Toolhub reads fast and resilient for all users."),
				current: t(
					"experiments.apiCacheCurrent",
					"Server-side ToolsDB cache stores anonymous GET /api/* responses with endpoint-specific TTLs, stale-if-error, ETag/Last-Modified, and browser stale-while-refresh support."
				),
				need: t(
					"experiments.apiCacheNeed",
					"api_cache table, proxy cache policy, and no caching for auth/session/write endpoints"
				)
			},
			{
				name: t("experiments.cacheJobsName", "Cache invalidation and prewarming"),
				what: t(
					"experiments.cacheJobsWhat",
					"Keep hot Toolhub endpoints warm so the first user after deploy does not pay the cold-cache cost."
				),
				current: t(
					"experiments.cacheJobsCurrent",
					"Scheduled jobs poll official recent changes, invalidate affected tool/list/search caches, prewarm important endpoints, and warm recent owner rows."
				),
				need: t("experiments.cacheJobsNeed", "Toolforge jobs for cache_invalidation.py and cache_prewarm.py")
			},
			{
				name: t("experiments.diagnosticsName", "Performance diagnostics"),
				what: t(
					"experiments.diagnosticsWhat",
					"See whether responses came from cache, upstream, stale data, or background refresh."
				),
				current: t(
					"experiments.diagnosticsCurrent",
					"Responses include X-Toolhub-Evolved-Cache, X-Toolhub-Evolved-Upstream, and Server-Timing; the frontend records boot, labels, API, stale-cache, and refresh timings."
				),
				need: t("experiments.diagnosticsNeed", "Proxy diagnostic headers and frontend timing marks")
			},
			{
				name: t("experiments.i18nA11yName", "Language, theme, and accessibility"),
				what: t(
					"experiments.i18nA11yWhat",
					"Use the app with stable labels, per-field language attributes, RTL-safe CSS, keyboard-accessible navigation, and light/dark themes."
				),
				current: t(
					"experiments.i18nA11yCurrent",
					"A tiny English label fallback prevents labels.js failures from blanking the app, while tests cover RTL CSS, link routing, and accessible static markup."
				),
				need: t(
					"experiments.i18nA11yNeed",
					"Locale catalog, built-in fallbacks, theme bootstrap, and accessibility checks"
				)
			},
			{
				name: t("experiments.designSystemName", "Design system and styleguide"),
				what: t("experiments.designSystemWhat", "Keep UI components consistent across Toolhub Evolved pages."),
				current: t(
					"experiments.designSystemCurrent",
					"The in-app styleguide documents the current atoms, molecules, organisms, layout patterns, and color tokens used by production pages."
				),
				need: t("experiments.designSystemNeed", "Shared CSS/components plus /styleguide route"),
				tryHref: "/styleguide",
				tryLabel: t("experiments.designSystemTry", "Styleguide")
			}
		]
	}
];
export function viewExperiments() {
	const groups = EXPERIMENTS.map(
		(g) => `
		<section class="exlist__group">
			<h2 class="exlist__gtitle">${esc(g.group)}</h2>
			<ul class="exlist" role="list">
				${g.items
					.map(
						(it) => `
					<li class="exfeat">
						<div class="exfeat__head">
							<h3 class="exfeat__name">${esc(it.name)}</h3>
							${it.tryHref ? `<a class="exfeat__try" href="${esc(it.tryHref)}">${esc(it.tryLabel || t("experiments.tryIt", "Try it"))} <span aria-hidden="true">→</span></a>` : ""}
						</div>
						<p class="exfeat__what">${esc(it.what)}</p>
						<dl class="exfeat__meta">
							<div><dt>${t("experiments.currentBehavior", "Current behavior")}</dt><dd>${esc(it.current)}</dd></div>
							<div><dt>${t("experiments.productionNeed", "Production need")}</dt><dd>${esc(it.need)}</dd></div>
						</dl>
					</li>`
					)
					.join("")}
			</ul>
		</section>`
	).join("");
	const total = EXPERIMENTS.reduce((n, g) => n + g.items.length, 0);
	return {
		title: t("experiments.docTitle", "Feature status — Toolhub Evolved"),
		html: `
		<div class="container page">
			<h1 class="page__title">${t("experiments.title", "Feature status")}</h1>
			<p class="page__intro">${t("experiments.introLead", "The $1 features below describe Toolhub Evolved's hybrid model:", esc(String(total)))}
			<strong>${t("experiments.introLive", "live Toolhub data stays the base")}</strong>, ${t("experiments.introWrites", "supported signed-in writes publish to official Toolhub first, and")}
			<strong>${t("experiments.introOverlay", "local overlays cover drafts, fallback data, and Evolved-owned data")}</strong>.
			${t("experiments.introTail", "These features are visible by default; for the live-vs-local model and where your data goes, see")}
			<a href="/rules-of-engagement">${t("experiments.rulesOfEngagement", "Rules of Engagement")}</a>.</p>
			${groups}
		</div>`
	};
}
