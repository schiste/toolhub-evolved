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
				name: t("experiments.resetName", "Reset demo data"),
				what: t("experiments.resetWhat", "Clear everything you've saved in this demo."),
				current: t("experiments.resetCurrent", "Wipes demo keys in this browser's localStorage."),
				need: "—"
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
					"Signed-in changes write to Toolhub favorites; signed-out demo mode stores names locally."
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
				name: t("experiments.crawlerName", "Add / remove tools (crawler)"),
				what: t(
					"experiments.crawlerWhat",
					"Register a toolinfo.json URL, or paste / load sample toolinfo to ingest tools."
				),
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
					"Your demo edits appear at the top of Recent changes, Audit logs and tool history."
				),
				current: t("experiments.feedsCurrent", "Local revision/audit rows merged on top of the live feeds."),
				need: t("experiments.feedsNeed", "Server-side write side-effects"),
				tryHref: "/recent",
				tryLabel: t("experiments.feedsTry", "Recent changes")
			}
		]
	},
	{
		group: t("experiments.groupSignals", "Synthetic signals — computed deterministically per tool"),
		items: [
			{
				name: t("experiments.popularityName", "Popularity"),
				what: t("experiments.popularityWhat", "View counts and a “Popular this week” ranking."),
				current: t(
					"experiments.popularityCurrent",
					"A stable pseudo-random number derived from the tool name."
				),
				need: t("experiments.popularityNeed", "Usage / view tracking"),
				tryHref: "/search?sort=views",
				tryLabel: t("experiments.popularityTry", "Most viewed")
			},
			{
				name: t("experiments.healthName", "Operational health"),
				what: t("experiments.healthWhat", "A Healthy / Degraded / Down status pill."),
				current: t("experiments.deterministicCurrent", "Deterministic per tool."),
				need: t("experiments.healthNeed", "An uptime / health-check service")
			},
			{
				name: t("experiments.thanksName", "Thanks"),
				what: t(
					"experiments.thanksWhat",
					"A lightweight way to appreciate useful tools without rating maintainers' work."
				),
				current: t("experiments.deterministicCurrent", "Deterministic per tool."),
				need: t("experiments.thanksNeed", "An authenticated appreciation event model with abuse controls")
			},
			{
				name: t("experiments.usageName", "30-day usage"),
				what: t("experiments.usageWhat", "An “editors used this in the last 30 days” figure."),
				current: t("experiments.deterministicCurrent", "Deterministic per tool."),
				need: t("experiments.usageNeed", "Usage analytics")
			},
			{
				name: t("experiments.screenshotsName", "Screenshots"),
				what: t("experiments.screenshotsWhat", "A preview image strip on the tool page."),
				current: t("experiments.screenshotsCurrent", "A static placeholder — no per-tool data is possible."),
				need: t("experiments.screenshotsNeed", "A screenshot field in toolinfo + image storage")
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
							${it.tryHref ? `<a class="exfeat__try" href="${esc(it.tryHref)}" data-enable-evolved>${esc(it.tryLabel || t("experiments.tryIt", "Try it"))} <span aria-hidden="true">→</span></a>` : ""}
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
			<strong>${t("experiments.introOverlay", "local overlays cover drafts, fallback data, and synthetic signals")}</strong>.
			${t("experiments.introToggleLead", "Some UI is shown only when")}
			<strong>${t("experiments.introToggle", "“Show Evolved features”")}</strong> ${t("experiments.introTail", "is on. For the live-vs-local model and where your data goes, see")}
			<a href="/rules-of-engagement">${t("experiments.rulesOfEngagement", "Rules of Engagement")}</a>.</p>
			${groups}
		</div>`
	};
}
