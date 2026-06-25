// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";

/* ---- Experimental features index -------------------------------------- */
// Single source of truth for every prospective feature behind the toggle.
export const EXPERIMENTS = [
	{
		group: "Identity & account",
		items: [
			{
				name: "Demo sign-in",
				what: "Sign in as a demo identity (Ada Lovelace) and sign out.",
				sim: "A session flag stored in your browser.",
				needs: "Real Wikimedia OAuth and a server session."
			},
			{
				name: "Reset demo data",
				what: "Clear everything you've saved in this demo.",
				sim: "Wipes the demo keys in this browser's localStorage.",
				needs: "—"
			}
		]
	},
	{
		group: "Your contributions — saved only in this browser",
		items: [
			{
				name: "Favorites",
				what: "Save tools and see them collected in one place.",
				sim: "A set of tool names in localStorage; the tool data is read live.",
				needs: "POST / DELETE /api/user/favorites/",
				tryHref: "/favorites",
				tryLabel: "Open favorites"
			},
			{
				name: "Lists",
				what: "Create, edit, reorder and delete lists, and add tools to them.",
				sim: "Lists of tool names in localStorage, shown alongside the live lists.",
				needs: "POST / PUT / DELETE /api/lists/",
				tryHref: "/my-lists",
				tryLabel: "Your lists"
			},
			{
				name: "Submit a tool",
				what: "Add a brand-new tool record.",
				sim: "A local record (clearly not shown in live search).",
				needs: "POST /api/tools/",
				tryHref: "/tools/create",
				tryLabel: "Submit a tool"
			},
			{
				name: "Edit a tool",
				what: "Change a tool's core fields (title, description, links…).",
				sim: "Field overrides merged onto the live record at render time.",
				needs: "PUT /api/tools/{name}/ and edit permissions"
			},
			{
				name: "Edit annotations",
				what: "Add community annotations (audiences, tasks, type, icon).",
				sim: "Annotation overrides merged onto the live record.",
				needs: "PUT /api/tools/{name}/annotations/"
			},
			{
				name: "Add / remove tools (crawler)",
				what: "Register a toolinfo.json URL, or paste / load sample toolinfo to ingest tools.",
				sim: "URLs recorded locally; ingestion parses pasted JSON (the browser can't fetch arbitrary URLs — CORS).",
				needs: "A server-side crawler",
				tryHref: "/add-or-remove-tools",
				tryLabel: "Add or remove tools"
			},
			{
				name: "Activity feeds",
				what: "Your demo edits appear at the top of Recent changes, Audit logs and tool history.",
				sim: "Local revision/audit rows merged on top of the live feeds.",
				needs: "Server-side write side-effects",
				tryHref: "/recent",
				tryLabel: "Recent changes"
			}
		]
	},
	{
		group: "Synthetic signals — computed deterministically per tool",
		items: [
			{
				name: "Popularity",
				what: "View counts and a “Popular this week” ranking.",
				sim: "A stable pseudo-random number derived from the tool name.",
				needs: "Usage / view tracking",
				tryHref: "/search?sort=views",
				tryLabel: "Most viewed"
			},
			{
				name: "Operational health",
				what: "A Healthy / Degraded / Down status pill.",
				sim: "Deterministic per tool.",
				needs: "An uptime / health-check service"
			},
			{
				name: "Thanks",
				what: "A lightweight way to appreciate useful tools without rating maintainers' work.",
				sim: "Deterministic per tool.",
				needs: "An authenticated appreciation event model with abuse controls"
			},
			{
				name: "30-day usage",
				what: "An “editors used this in the last 30 days” figure.",
				sim: "Deterministic per tool.",
				needs: "Usage analytics"
			},
			{
				name: "Screenshots",
				what: "A preview image strip on the tool page.",
				sim: "A static placeholder — no per-tool data is possible.",
				needs: "A screenshot field in toolinfo + image storage"
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
							${it.tryHref ? `<a class="exfeat__try" href="${esc(it.tryHref)}">${esc(it.tryLabel || "Try it")} <span aria-hidden="true">→</span></a>` : ""}
						</div>
						<p class="exfeat__what">${esc(it.what)}</p>
						<dl class="exfeat__meta">
							<div><dt>Simulated with</dt><dd>${esc(it.sim)}</dd></div>
							<div><dt>Needs in production</dt><dd>${esc(it.needs)}</dd></div>
						</dl>
					</li>`
					)
					.join("")}
			</ul>
		</section>`
	).join("");
	const total = EXPERIMENTS.reduce((n, g) => n + g.items.length, 0);
	return {
		title: "Experimental features — Toolhub",
		html: `
		<div class="container page">
			<h1 class="page__title">Experimental features</h1>
			<p class="page__intro">The ${esc(String(total))} prospective features below appear only when
			<strong>“Show me prospective features”</strong> is on. Each reads the real, live catalog and
			<strong>overloads it with a feature-specific simulation</strong> — nothing here is written to the
			real Toolhub. For the live-vs-simulated model and where your data goes, see
			<a href="/rules-of-engagement">Rules of Engagement</a>.</p>
			${groups}
		</div>`
	};
}
