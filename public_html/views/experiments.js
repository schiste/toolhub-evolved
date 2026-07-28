// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { t } from "../lib/core/i18n.js";

/* ---- Feature status index --------------------------------------------- */
// Single source of truth for every Evolved feature and hybrid integration path.
export const EXPERIMENTS = [
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
				name: t("experiments.myToolsName", "My tools and author claims"),
				what: t(
					"experiments.myToolsWhat",
					"See tools associated with your signed-in Toolhub identity, split into verified and possible matches."
				),
				current: t(
					"experiments.myToolsCurrent",
					"Official Toolhub search provides candidates; Evolved verifies claims per tool with Toolforge maintainer, Toolhub write, signed toolinfo, or display-name evidence."
				),
				need: t("experiments.myToolsNeed", "Author-claim table, resolver endpoint, and verification providers"),
				tryHref: "/my-tools",
				tryLabel: t("experiments.myToolsTry", "My tools")
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
				name: t("experiments.submitName", "Submit a tool"),
				what: t("experiments.submitWhat", "Add a brand-new tool record."),
				current: t(
					"experiments.submitCurrent",
					"Official POST /api/tools/ first; rejected submissions become local Evolved drafts."
				),
				need: "POST /api/tools/",
				tryHref: "/tools/create",
				tryLabel: t("experiments.submitName", "Submit a tool")
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
				name: t("experiments.crawlerName", "Add / remove tools (crawler)"),
				what: t("experiments.crawlerWhat", "Register a toolinfo.json URL, or paste toolinfo to ingest tools."),
				current: t(
					"experiments.crawlerCurrent",
					"Signed-in URL registrations write to Toolhub; pasted JSON ingestion remains local to Evolved."
				),
				need: t("experiments.crawlerNeed", "Toolhub crawler permissions and local fallback storage"),
				tryHref: "/add-or-remove-tools",
				tryLabel: t("experiments.crawlerTry", "Add or remove tools")
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
			<p class="page__intro">${t("experiments.introLead", "The {total} features below describe Toolhub Evolved's hybrid model:", { total: esc(String(total)) })}
			<strong>${t("experiments.introLive", "live Toolhub data stays the base")}</strong>, ${t("experiments.introWrites", "supported signed-in writes publish to official Toolhub first, and")}
			<strong>${t("experiments.introOverlay", "local overlays cover drafts, fallback data, and Evolved-owned data")}</strong>.
			${t("experiments.introTail", "These features are visible by default; for the live-vs-local model and where your data goes, see")}
			<a href="/rules-of-engagement">${t("experiments.rulesOfEngagement", "Rules of Engagement")}</a>.</p>
			${groups}
		</div>`
	};
}
