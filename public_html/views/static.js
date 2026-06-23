// SPDX-License-Identifier: GPL-3.0-or-later
import { esc, safeUrl } from "../lib/dom.js";
import { apiGet } from "../lib/api.js";

/* ---- Static prose pages (T9) ------------------------------------------- */
export function prosePage(title, bodyHtml) {
	return { title: `${title} — Toolhub`, html: `<div class="container page"><article class="prose prose--page"><h1>${esc(title)}</h1>${bodyHtml}</article></div>` };
}
export const ext = (url, label) => `<a href="${safeUrl(url)}" target="_blank" rel="noopener">${esc(label)} <span aria-hidden="true">↗</span></a>`;
// Faithful summaries of real Toolhub / Wikimedia content, rendered in our style.
// Canonical policies link out to their authoritative source (as the real site does).
export const STATIC = {
	about: { title: "About Toolhub", body: `
		<p>Toolhub is <strong>a community-managed catalog of software tools used in the
		Wikimedia movement</strong>. Technical volunteers document the tools they build,
		and all Wikimedians can search the catalog, build lists, and share them.</p>
		<p>A "tool" is defined inclusively — user scripts, gadgets, bots, templates, Lua
		modules, web applications and mobile apps that interact with Wikimedia projects.
		The catalog aims to be <em>inclusive rather than exclusive</em>, as long as an
		entry helps people work on the projects.</p>
		<h2>How tools get here</h2>
		<p>Tools enter the catalog three ways: by registering a <code>toolinfo.json</code>
		URL that Toolhub crawls roughly hourly, through the Toolhub UI, or via the API
		(<code>POST /api/tools/</code>). All paths validate against the same versioned
		schema, so the data stays consistent.</p>
		<h2>Core information vs. annotations</h2>
		<p>Each tool has authoritative <em>core</em> information, editable only by its
		owner or administrators, plus community <em>annotations</em> that any logged-in
		Wikimedian can enrich. When both are set for a field, Toolhub shows the core
		value — balancing maintainer control with community contribution.</p>
		<p>Structured data is released under CC0; attribution via links back is
		encouraged but not required. Sign in with your existing Wikimedia account — no
		new account or password is needed.</p>
		<p>Want to help build Toolhub itself? See ${"<a href=\"#/contribute\">Help maintain Toolhub</a>"}.</p>
		<blockquote>This is a design prototype that reads live, read-only data from the
		public Toolhub API — not the production site.</blockquote>` },
	help: { title: "Help", body: `
		<p>New to Toolhub? Here is the quickest path to finding and sharing tools. Sign
		in with your Wikimedia account (via OAuth) to save favourites and edit listings —
		no new account needed.</p>
		<h2>Find a tool</h2>
		<ul>
			<li><strong>Search</strong> by name, keyword, or what you want to do.</li>
			<li><strong>Filter</strong> on the Browse page by tool type and keywords.</li>
			<li><strong>Browse by need</strong> from the home-page shortcuts.</li>
		</ul>
		<h2>Share a tool</h2>
		<p>Maintainers can publish a <code>toolinfo.json</code> file in their repository
		(so volunteers can submit improvements over time) or create a record directly in
		the UI or API.</p>
		<h2>Build a list</h2>
		<p>Group useful tools into a list and share it — great for onboarding new editors
		or running an event.</p>
		<p>${"<a href=\"#/about\">Learn more about Toolhub →</a>"}</p>` },
	community: { title: "Community", body: `
		<p>Toolhub is developed in the open under Wikimedia Cloud Services. Everyone is
		welcome to take part — reporting bugs, suggesting tools, translating, or writing
		code.</p>
		<h2>Where the conversation happens</h2>
		<ul>
			<li>Discuss the project on ${ext("https://meta.wikimedia.org/wiki/Talk:Toolhub", "Talk:Toolhub")} (Meta-Wiki).</li>
			<li>File and track work on the ${ext("https://phabricator.wikimedia.org/tag/toolhub/", "#toolhub Phabricator board")}.</li>
			<li>Help translate the interface on ${ext("https://translatewiki.net/wiki/Translating:Toolhub", "translatewiki.net")}.</li>
		</ul>
		<p>Looking to contribute code or report an issue? Start at
		${"<a href=\"#/contribute\">Help maintain Toolhub</a>"}.</p>` },
	privacy: { title: "Privacy policy", body: `
		<p>Toolhub is operated by the Wikimedia Foundation and is governed by the
		${ext("https://foundation.wikimedia.org/wiki/Policy:Privacy_policy", "Wikimedia Foundation Privacy Policy")}.</p>
		<h2>What this means in practice</h2>
		<ul>
			<li>You sign in with your Wikimedia account using OAuth; Toolhub does not store
			a separate password.</li>
			<li>Like a wiki, your contributions (tool edits, annotations, lists, comments)
			are <strong>public</strong> and attributed to your username.</li>
			<li>Catalog data is released under CC0.</li>
		</ul>
		<p>Please read the full ${ext("https://foundation.wikimedia.org/wiki/Policy:Privacy_policy", "Privacy Policy")} for the authoritative details.</p>` },
	terms: { title: "Terms of Use", body: `
		<p>Use of Toolhub is subject to the
		${ext("https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use", "Wikimedia Foundation Terms of Use")}.</p>
		<p>By contributing, you agree that your edits are public and that structured
		catalog data is made available under CC0. Tools listed here are owned and operated
		by their respective maintainers; Toolhub catalogs them but does not host or endorse
		them. See the full ${ext("https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use", "Terms of Use")} for details.</p>` },
	"code-of-conduct": { title: "Code of Conduct", body: `
		<p>Toolhub follows the
		${ext("https://www.mediawiki.org/wiki/Code_of_Conduct", "Code of Conduct for Wikimedia technical spaces")},
		which applies to MediaWiki.org, Phabricator, Gerrit, mailing lists, chat, and
		events.</p>
		<blockquote>Technical skills and community status make no difference to the right
		to be respected and the obligation to respect others.</blockquote>
		<h2>Expected behaviour</h2>
		<p>Be welcoming and helpful, especially to newcomers. Harassment and other
		inappropriate behaviour are unacceptable in all public and private Wikimedia
		technical spaces.</p>
		<h2>Reporting</h2>
		<p>Ask the person to stop and point them to the Code of Conduct; at events, notify
		organisers; or report directly to the Code of Conduct Committee at
		<code>techconduct@wikimedia.org</code>. For threats of harm, contact local
		authorities first, then <code>emergency@wikimedia.org</code>.</p>` },
	api: { title: "API", body: `
		<p>Toolhub is built <strong>API-first</strong>: everything you can do in this
		interface is also available over a documented HTTP API, so anyone can build their
		own tools on top of the catalog.</p>
		<ul>
			<li>Browse the interactive documentation at ${ext("https://toolhub.wikimedia.org/api-docs", "toolhub.wikimedia.org/api-docs")}.</li>
			<li>The OpenAPI schema and endpoints live under ${ext("https://toolhub.wikimedia.org/api/", "/api/")}.</li>
			<li>Read access is anonymous; creating or editing records uses your Wikimedia
			OAuth identity. For example, <code>POST /api/tools/</code> adds a tool.</li>
		</ul>` },
	"rules-of-engagement": { title: "Rules of Engagement", body: `
		<p><strong>This is a design prototype on a separate domain — not the production
		Toolhub.</strong> It exists to explore how tool discovery could look and feel. Here's
		exactly what is real and what is simulated, so nothing is misleading.</p>
		<h2>What's real (live, read-only)</h2>
		<p>The catalog itself is genuine: it is read live from
		${ext("https://toolhub.wikimedia.org/api/", "toolhub.wikimedia.org")} through a
		read-only proxy. That means the tools, search and facets, tool detail pages, lists,
		members, recent changes, crawler history, and audit logs you see are <strong>the
		actual Toolhub data</strong>, refreshed every time you load a page. Nothing here is
		ever written back to Toolhub.</p>
		<h2>What's simulated (prospective features)</h2>
		<p>When you switch on <em>"Show me prospective features"</em>, the app turns on a
		set of experiments that the read-only API can't actually back: signing in,
		favoriting tools, creating and editing lists, submitting and editing tools,
		community annotations, and signals like popularity, reviews, health, and usage.</p>
		<p>These don't replace the real data — each one <strong>overloads a real record with
		a feature-specific fixture</strong> (for example, a real tool decorated with a
		synthetic "popular this week" count, or your favorite flag layered on top of the
		live tool).</p>
		<h2>Where your actions go</h2>
		<ul>
			<li>Everything you "save" — favorites, lists, edits — is stored
			<strong>only in this browser</strong> (in <code>localStorage</code>), on this
			device. It is never sent to Toolhub or shared with anyone else.</li>
			<li><strong>"Reset demo data"</strong> (in the account menu) clears all of it.</li>
			<li>Turning the toggle <strong>off</strong> strips every overlay and returns the
			app to the honest, live, read-only experience.</li>
		</ul>
		<h2>The honest edges</h2>
		<p>Because search is real and read-only, a tool you "create" or "edit" in the demo
		won't appear in live search — it lives only as your local overlay, shown on its own
		page and in your "my…" views. We label these rather than fake them.</p>
		<blockquote>In short: the data is real and read-only; your contributions are a local,
		in-browser simulation. Nothing you do here touches the real Toolhub.</blockquote>` },
	rss: { title: "Feeds", body: `
		<p>Follow changes to the catalog without checking back. Toolhub publishes Atom/RSS
		feeds for activity such as recently added and recently updated tools, and for the
		history of individual tools and lists.</p>
		<p>Browse the latest additions on the ${ext("https://toolhub.wikimedia.org/", "live site")},
		or sort the ${"<a href=\"#/search?sort=recent\">Browse page</a>"} by "Recently
		updated".</p>` },
};
export function viewStatic(slug) {
	const p = STATIC[slug];
	return p ? prosePage(p.title, p.body) : viewNotFound();
}

/* ---- Help maintain Toolhub: the contribution hub ----------------------- */
export function linkCard(icon, title, desc, url, internal) {
	const href = internal ? url : safeUrl(url);
	const attrs = internal ? "" : ` target="_blank" rel="noopener"`;
	const arrow = internal ? "" : ' <span aria-hidden="true">↗</span>';
	return `<a class="linkcard" href="${href || "#"}"${attrs}>
		<span class="linkcard__icon" aria-hidden="true">${icon}</span>
		<span class="linkcard__body"><span class="linkcard__title">${esc(title)}${arrow}</span>
		<span class="linkcard__desc">${esc(desc)}</span></span></a>`;
}
export function viewContribute() {
	const html = `
	<div class="container page">
		<h1 class="page__title">Help maintain Toolhub</h1>
		<p class="page__intro">Toolhub is free and open source, built by the community
		under Wikimedia Cloud Services. Here is everything you need to report a problem,
		translate, or contribute code — pick a starting point.</p>

		<h2 class="contribute__h2">Report &amp; track work</h2>
		<div class="linkgrid">
			${linkCard("🐞", "Report a bug or request a feature", "Open a task on the #toolhub Phabricator board.", "https://phabricator.wikimedia.org/tag/toolhub/")}
			${linkCard("✅", "Find a good first task", "Browse open work and pick something to start with.", "https://phabricator.wikimedia.org/tag/toolhub/")}
			${linkCard("💬", "Discuss the project", "Share ideas and feedback on the Toolhub talk page.", "https://meta.wikimedia.org/wiki/Talk:Toolhub")}
		</div>

		<h2 class="contribute__h2">Write code</h2>
		<div class="linkgrid">
			${linkCard("🧩", "Source code (Gerrit)", "The canonical repository where changes are reviewed.", "https://gerrit.wikimedia.org/r/admin/repos/wikimedia/toolhub")}
			${linkCard("🐙", "GitHub mirror", "Read-only mirror for browsing the code and history.", "https://github.com/wikimedia/toolhub")}
			${linkCard("🛠️", "Set up a dev environment", "The CONTRIBUTING guide: run the whole stack with Docker.", "https://github.com/wikimedia/toolhub/blob/main/docs/CONTRIBUTING.rst")}
			${linkCard("🔑", "Get developer access", "Create a Wikimedia developer account and configure Gerrit.", "https://www.mediawiki.org/wiki/Developer_access")}
		</div>

		<h2 class="contribute__h2">Translate &amp; document</h2>
		<div class="linkgrid">
			${linkCard("🌐", "Translate Toolhub", "Localise the interface into your language on translatewiki.net.", "https://translatewiki.net/wiki/Translating:Toolhub")}
			${linkCard("📦", "The toolinfo standard", "Learn the schema that describes a tool, and the API.", "https://toolhub.wikimedia.org/api-docs")}
			${linkCard("📝", "Add or improve a tool listing", "List your own tool, or enrich an existing record.", "#/help", true)}
		</div>
	</div>`;
	return { title: "Help maintain Toolhub", html };
}
// API docs — the live docs cannot be framed, so link out and list same-origin endpoints.
export async function viewApiDocs() {
	const root = await apiGet("/").catch(() => ({}));
	const endpoints = Object.keys(root).sort();
	const endpointCards = endpoints.map((ep) => {
		const href = "/api/" + ep + "/";
		return `<a class="linkcard" href="${esc(href)}" target="_blank" rel="noopener">
			<span class="linkcard__icon" aria-hidden="true">{ }</span>
			<span class="linkcard__body"><span class="linkcard__title"><code>GET ${esc(href)}</code> ↗</span>
			<span class="linkcard__desc">Open the live JSON response through this app's read-only proxy.</span></span></a>`;
	}).join("");
	return { title: "API documentation — Toolhub", html: `
		<div class="container page">
			<h1 class="page__title">API documentation</h1>
			<p class="page__intro">Toolhub is API-first — everything in this interface is available over HTTP. The live interactive documentation blocks embedding, so open it directly or inspect the same-origin read-only endpoints below.</p>
			<div class="linkgrid">
				${linkCard("📦", "Interactive API docs", "Open the canonical Toolhub API documentation.", "https://toolhub.wikimedia.org/api-docs")}
				${linkCard("🧭", "API root", "Browse the upstream API endpoint index.", "https://toolhub.wikimedia.org/api/")}
			</div>
			<h2 class="contribute__h2">Live proxy endpoints</h2>
			<div class="linkgrid">${endpointCards || '<p class="empty">The live endpoint index is unavailable.</p>'}</div>
		</div>` };
}
/* ---- Sign-in-required stubs (auth/write features) ---------------------- */
export function signInPage(title, lead) {
	return { title: `${title} — Toolhub`, html: `
		<div class="container page"><article class="prose prose--page">
			<h1>${esc(title)}</h1>
			<p>${lead}</p>
			<p>Toolhub uses your existing Wikimedia account via OAuth — no new account or
			password is needed.</p>
			<p><a class="btn btn--primary" href="https://toolhub.wikimedia.org/" target="_blank" rel="noopener">Continue on toolhub.wikimedia.org <span aria-hidden="true">↗</span></a></p>
			<p class="signin-note">In this prototype these actions are read-only: they need an
			authenticated session and the live back-end. See
			<a href="#/contribute">Help maintain Toolhub</a> to contribute.</p>
		</article></div>` };
}
export function viewNotFound() {
	return { title: "Not found — Toolhub", html: `
		<div class="container page errorpage">
			<h1>Page not found</h1>
			<p class="prose">We couldn't find that page. It may have moved, or the link may be incomplete.</p>
			<a class="btn btn--primary" href="#/">Go to the home page</a>
		</div>` };
}
