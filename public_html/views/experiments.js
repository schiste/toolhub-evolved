// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { t } from "../lib/core/i18n.js";

/* ---- Experimental features index -------------------------------------- */
// Single source of truth for every prospective feature behind the toggle.
export const EXPERIMENTS = [
	{
		group: t("experiments.groupIdentity", "Identity & account"),
		items: [
			{
				name: t("experiments.signinName", "Demo sign-in"),
				what: t("experiments.signinWhat", "Sign in as a demo identity (Ada Lovelace) and sign out."),
				sim: t("experiments.signinSim", "A session flag stored in your browser."),
				needs: t("experiments.signinNeeds", "Real Wikimedia OAuth and a server session.")
			},
			{
				name: t("experiments.resetName", "Reset demo data"),
				what: t("experiments.resetWhat", "Clear everything you've saved in this demo."),
				sim: t("experiments.resetSim", "Wipes the demo keys in this browser's localStorage."),
				needs: "—"
			}
		]
	},
	{
		group: t("experiments.groupContributions", "Your contributions — saved only in this browser"),
		items: [
			{
				name: t("experiments.favoritesName", "Favorites"),
				what: t("experiments.favoritesWhat", "Save tools and see them collected in one place."),
				sim: t("experiments.favoritesSim", "A set of tool names in localStorage; the tool data is read live."),
				needs: "POST / DELETE /api/user/favorites/",
				tryHref: "/favorites",
				tryLabel: t("experiments.favoritesTry", "Open favorites")
			},
			{
				name: t("experiments.listsName", "Lists"),
				what: t("experiments.listsWhat", "Create, edit, reorder and delete lists, and add tools to them."),
				sim: t("experiments.listsSim", "Lists of tool names in localStorage, shown alongside the live lists."),
				needs: "POST / PUT / DELETE /api/lists/",
				tryHref: "/my-lists",
				tryLabel: t("experiments.listsTry", "Your lists")
			},
			{
				name: t("experiments.submitName", "Submit a tool"),
				what: t("experiments.submitWhat", "Add a brand-new tool record."),
				sim: t("experiments.submitSim", "A local record (clearly not shown in live search)."),
				needs: "POST /api/tools/",
				tryHref: "/tools/create",
				tryLabel: t("experiments.submitName", "Submit a tool")
			},
			{
				name: t("experiments.editToolName", "Edit a tool"),
				what: t("experiments.editToolWhat", "Change a tool's core fields (title, description, links…)."),
				sim: t("experiments.editToolSim", "Field overrides merged onto the live record at render time."),
				needs: "PUT /api/tools/{name}/ and edit permissions"
			},
			{
				name: t("experiments.editAnnosName", "Edit annotations"),
				what: t("experiments.editAnnosWhat", "Add community annotations (audiences, tasks, type, icon)."),
				sim: t("experiments.editAnnosSim", "Annotation overrides merged onto the live record."),
				needs: "PUT /api/tools/{name}/annotations/"
			},
			{
				name: t("experiments.crawlerName", "Add / remove tools (crawler)"),
				what: t(
					"experiments.crawlerWhat",
					"Register a toolinfo.json URL, or paste / load sample toolinfo to ingest tools."
				),
				sim: t(
					"experiments.crawlerSim",
					"URLs recorded locally; ingestion parses pasted JSON (the browser can't fetch arbitrary URLs — CORS)."
				),
				needs: t("experiments.crawlerNeeds", "A server-side crawler"),
				tryHref: "/add-or-remove-tools",
				tryLabel: t("experiments.crawlerTry", "Add or remove tools")
			},
			{
				name: t("experiments.feedsName", "Activity feeds"),
				what: t(
					"experiments.feedsWhat",
					"Your demo edits appear at the top of Recent changes, Audit logs and tool history."
				),
				sim: t("experiments.feedsSim", "Local revision/audit rows merged on top of the live feeds."),
				needs: t("experiments.feedsNeeds", "Server-side write side-effects"),
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
				sim: t("experiments.popularitySim", "A stable pseudo-random number derived from the tool name."),
				needs: t("experiments.popularityNeeds", "Usage / view tracking"),
				tryHref: "/search?sort=views",
				tryLabel: t("experiments.popularityTry", "Most viewed")
			},
			{
				name: t("experiments.healthName", "Operational health"),
				what: t("experiments.healthWhat", "A Healthy / Degraded / Down status pill."),
				sim: t("experiments.deterministicSim", "Deterministic per tool."),
				needs: t("experiments.healthNeeds", "An uptime / health-check service")
			},
			{
				name: t("experiments.thanksName", "Thanks"),
				what: t(
					"experiments.thanksWhat",
					"A lightweight way to appreciate useful tools without rating maintainers' work."
				),
				sim: t("experiments.deterministicSim", "Deterministic per tool."),
				needs: t("experiments.thanksNeeds", "An authenticated appreciation event model with abuse controls")
			},
			{
				name: t("experiments.usageName", "30-day usage"),
				what: t("experiments.usageWhat", "An “editors used this in the last 30 days” figure."),
				sim: t("experiments.deterministicSim", "Deterministic per tool."),
				needs: t("experiments.usageNeeds", "Usage analytics")
			},
			{
				name: t("experiments.screenshotsName", "Screenshots"),
				what: t("experiments.screenshotsWhat", "A preview image strip on the tool page."),
				sim: t("experiments.screenshotsSim", "A static placeholder — no per-tool data is possible."),
				needs: t("experiments.screenshotsNeeds", "A screenshot field in toolinfo + image storage")
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
							<div><dt>${t("experiments.simulatedWith", "Simulated with")}</dt><dd>${esc(it.sim)}</dd></div>
							<div><dt>${t("experiments.needsInProduction", "Needs in production")}</dt><dd>${esc(it.needs)}</dd></div>
						</dl>
					</li>`
					)
					.join("")}
			</ul>
		</section>`
	).join("");
	const total = EXPERIMENTS.reduce((n, g) => n + g.items.length, 0);
	return {
		title: t("experiments.docTitle", "Experimental features — Toolhub"),
		html: `
		<div class="container page">
			<h1 class="page__title">${t("experiments.title", "Experimental features")}</h1>
			<p class="page__intro">${t("experiments.introLead", "The {total} prospective features below appear only when", { total: esc(String(total)) })}
			<strong>${t("experiments.introToggle", "“Show me prospective features”")}</strong> ${t("experiments.introReads", "is on. Each reads the real, live catalog and")}
			<strong>${t("experiments.introOverloads", "overloads it with a feature-specific simulation")}</strong> ${t("experiments.introTail", "— nothing here is written to the\n\t\t\treal Toolhub. For the live-vs-simulated model and where your data goes, see")}
			<a href="/rules-of-engagement">${t("experiments.rulesOfEngagement", "Rules of Engagement")}</a>.</p>
			${groups}
		</div>`
	};
}
