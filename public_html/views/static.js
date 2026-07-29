// SPDX-License-Identifier: GPL-3.0-or-later
import { esc, safeUrl } from "../lib/core/dom.js";
import { t } from "../lib/core/i18n.js";
import { apiGet } from "../lib/core/api.js";
import { mountApiExplorer, renderApiExplorer } from "../lib/organisms/api-explorer.js";
import {
	TOOLINFO_DATA_MODEL_URL,
	TOOLINFO_EXAMPLE_JSON,
	TOOLINFO_SCHEMA_URL,
	TOOLINFO_SCHEMA_VERSION
} from "../lib/core/toolinfo-docs.js";
import { button } from "../lib/atoms/button.js";
import { icon } from "../lib/atoms/icon.js";

/* ---- Static prose pages (T9) ------------------------------------------- */
/**
 * @param {string} title
 * @param {string} bodyHtml
 * @returns {{ title: string, html: string }}
 */
export function prosePage(title, bodyHtml) {
	return {
		title: t("static.pageTitle", "{title} — Toolhub", { title }),
		html: `<div class="container page"><article class="prose prose--page"><h1>${esc(title)}</h1>${bodyHtml}</article></div>`
	};
}
const EXTERNAL_REL = "noopener nofollow";
const REVISION_DIFF_EXAMPLE_JSON = JSON.stringify(
	{
		original: { id: 122689, content_type: "tool", content_id: "mm_wdfist" },
		operations: [
			{ op: "replace", path: "/description", value: "Updated description" },
			{ op: "remove", path: "/keywords/1" }
		],
		result: { id: 122683, content_type: "tool", content_id: "mm_wdfist" }
	},
	null,
	2
);
/** @param {string} url @param {string} label */
export const ext = (url, label) =>
	`<a href="${safeUrl(url)}" target="_blank" rel="${EXTERNAL_REL}">${esc(label)} ${icon("external")}</a>`;
// Faithful summaries of real Toolhub / Wikimedia content, rendered in our style.
// Canonical policies link out to their authoritative source (as the real site does).
export const STATIC = {
	about: {
		title: t("static.about.title", "About Toolhub"),
		body: `
		<p>Toolhub is <strong>a community-managed catalog of software tools used in the
		Wikimedia movement</strong>. Technical volunteers document the tools they build,
		and all Wikimedians can search the catalog, build lists, and share them.</p>
		<p>A "tool" is defined inclusively — user scripts, gadgets, bots, templates, Lua
		modules, web applications and mobile apps that interact with Wikimedia projects.
		The catalog aims to be <em>inclusive rather than exclusive</em>, as long as an
		entry helps people work on the projects.</p>
		<h2>${t("static.about.howToolsGetHere", "How tools get here")}</h2>
		<p>Tools enter the catalog three ways: by registering a <code>toolinfo.json</code>
		URL that Toolhub crawls roughly hourly, through the Toolhub UI, or via the API
		(<code>POST /api/tools/</code>). All paths validate against the same versioned
		schema, so the data stays consistent.</p>
		<h2>${t("static.about.coreVsAnnotations", "Core information vs. annotations")}</h2>
		<p>Each tool has authoritative <em>core</em> information, editable only by its
		owner or administrators, plus community <em>annotations</em> that any logged-in
		Wikimedian can enrich. When both are set for a field, Toolhub shows the core
		value — balancing maintainer control with community contribution.</p>
		<p>${t("static.about.cc0", "Structured data is released under CC0; attribution via links back is\n\t\tencouraged but not required. Sign in with Toolhub — no separate Evolved account\n\t\tor password is needed.")}</p>
		<p>Want to help build Toolhub itself? See ${`<a href="/contribute">${t("static.helpMaintainToolhub", "Help maintain Toolhub")}</a>`}.</p>
		<blockquote>${t("static.about.prototypeNote", "This is a companion interface for Toolhub: it reads live catalog data from the public API, publishes official writes through Toolhub OAuth when you sign in, and keeps Evolved-only additions in its local overlay database.")}</blockquote>`
	},
	help: {
		title: t("static.help.title", "Help"),
		body: `
		<p>${t("static.help.intro", "New to Toolhub? Here is the quickest path to finding and sharing tools. Sign\n\t\tin with Toolhub to save favourites, build lists, and publish permitted edits —\n\t\tno separate Evolved account is needed.")}</p>
		<h2>${t("static.help.findTool", "Find a tool")}</h2>
		<ul>
			<li><strong>Search</strong> by name, keyword, or what you want to do.</li>
			<li><strong>Filter</strong> on the Browse page by tool type and keywords.</li>
			<li><strong>Browse by need</strong> from the home-page shortcuts.</li>
		</ul>
		<h2>${t("static.help.shareTool", "Share a tool")}</h2>
		<p>Maintainers can publish a <code>toolinfo.json</code> file in their repository
		(so volunteers can submit improvements over time) or create a record directly in
		the UI or API.</p>
		<h2>${t("static.help.buildList", "Build a list")}</h2>
		<p>${t("static.help.buildListBody", "Group useful tools into a list and share it — great for onboarding new editors\n\t\tor running an event.")}</p>
		<p>${`<a href="/about">${t("static.help.learnMore", "Learn more about Toolhub →")}</a>`}</p>`
	},
	community: {
		title: t("static.community.title", "Community"),
		body: `
		<p>${t("static.community.intro", "Toolhub is developed in the open under Wikimedia Cloud Services. Everyone is\n\t\twelcome to take part — reporting bugs, suggesting tools, translating, or writing\n\t\tcode.")}</p>
		<h2>${t("static.community.whereConversationHappens", "Where the conversation happens")}</h2>
		<ul>
			<li>Discuss the project on ${ext("https://meta.wikimedia.org/wiki/Talk:Toolhub", "Talk:Toolhub")} (Meta-Wiki).</li>
			<li>File and track work on the ${ext("https://phabricator.wikimedia.org/tag/toolhub/", t("static.community.phabricatorBoard", "#toolhub Phabricator board"))}.</li>
			<li>Help translate the interface on ${ext("https://translatewiki.net/wiki/Translating:Toolhub", "translatewiki.net")}.</li>
		</ul>
		<p>Looking to contribute code or report an issue? Start at
		${`<a href="/contribute">${t("static.helpMaintainToolhub", "Help maintain Toolhub")}</a>`}.</p>`
	},
	privacy: {
		title: t("static.privacy.title", "Privacy policy"),
		body: `
		<p>Toolhub is operated by the Wikimedia Foundation and is governed by the
		${ext("https://foundation.wikimedia.org/wiki/Policy:Privacy_policy", t("static.privacy.policyLink", "Wikimedia Foundation Privacy Policy"))}.</p>
		<h2>${t("static.privacy.inPractice", "What this means in practice")}</h2>
		<ul>
			<li>You sign in with Toolhub using OAuth; Toolhub Evolved stores a local session
			and a server-side OAuth grant, never your password.</li>
			<li>Official writes are sent to Toolhub's API and follow Toolhub's attribution,
			permission, and validation rules.</li>
			<li>Evolved-only drafts and fallback data live in this site's local database and
			browser cache so your work is not lost when official Toolhub rejects a write.</li>
		</ul>
		<p>Please read the full ${ext("https://foundation.wikimedia.org/wiki/Policy:Privacy_policy", t("static.privacy.policyShort", "Privacy Policy"))} for the authoritative details.</p>`
	},
	terms: {
		title: t("static.terms.title", "Terms of Use"),
		body: `
		<p>Use of Toolhub is subject to the
		${ext("https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use", t("static.terms.termsLink", "Wikimedia Foundation Terms of Use"))}.</p>
		<p>By contributing, you agree that your edits are public and that structured
		catalog data is made available under CC0. Tools listed here are owned and operated
		by their respective maintainers; Toolhub catalogs them but does not host or endorse
		them. See the full ${ext("https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use", t("static.terms.title", "Terms of Use"))} for details.</p>`
	},
	"code-of-conduct": {
		title: t("static.codeOfConduct.title", "Code of Conduct"),
		body: `
		<p>Toolhub follows the
		${ext("https://www.mediawiki.org/wiki/Code_of_Conduct", t("static.codeOfConduct.cocLink", "Code of Conduct for Wikimedia technical spaces"))},
		which applies to MediaWiki.org, Phabricator, Gerrit, mailing lists, chat, and
		events.</p>
		<blockquote>${t("static.codeOfConduct.quote", "Technical skills and community status make no difference to the right\n\t\tto be respected and the obligation to respect others.")}</blockquote>
		<h2>${t("static.codeOfConduct.expectedBehaviour", "Expected behaviour")}</h2>
		<p>${t("static.codeOfConduct.expected", "Be welcoming and helpful, especially to newcomers. Harassment and other\n\t\tinappropriate behaviour are unacceptable in all public and private Wikimedia\n\t\ttechnical spaces.")}</p>
		<h2>${t("static.codeOfConduct.reporting", "Reporting")}</h2>
		<p>Ask the person to stop and point them to the Code of Conduct; at events, notify
		organisers; or report directly to the Code of Conduct Committee at
		<code>techconduct@wikimedia.org</code>. For threats of harm, contact local
		authorities first, then <code>emergency@wikimedia.org</code>.</p>`
	},
	api: {
		title: t("static.api.title", "API"),
		body: `
		<p>Toolhub is built <strong>API-first</strong>: everything you can do in this
		interface is also available over a documented HTTP API, so anyone can build their
		own tools on top of the catalog.</p>
		<ul>
			<li>Browse the interactive documentation at ${ext("https://toolhub.wikimedia.org/api-docs", "toolhub.wikimedia.org/api-docs")}.</li>
			<li>Use this prototype's ${`<a href="/api-docs">${t("static.api.apiDocsPage", "API explorer")}</a>`} for read-only examples, response inspection, and schema pointers.</li>
			<li>The OpenAPI schema and endpoints live under ${ext("https://toolhub.wikimedia.org/api/", "/api/")}.</li>
			<li>Read access is anonymous; creating or editing records uses your Wikimedia
			OAuth identity. For example, <code>POST /api/tools/</code> adds a tool.</li>
		</ul>`
	},
	"rules-of-engagement": {
		title: t("static.rulesOfEngagement.title", "Rules of Engagement"),
		body: `
		<p><strong>This is a companion interface on a separate domain — not the official
		Toolhub frontend.</strong> It exists to run next to Toolhub: live Toolhub data remains
		the base, while Evolved adds a local overlay for extra and fallback data.</p>
		<h2>${t("static.rulesOfEngagement.whatsReal", "What's real")}</h2>
		<p>The catalog itself is genuine: it is read live from
		${ext("https://toolhub.wikimedia.org/api/", "toolhub.wikimedia.org")} through a
		server-side cache/proxy. That means the tools, search and facets, tool detail
		pages, lists, members, recent changes, crawler history, and audit logs you see are
		<strong>the actual Toolhub data</strong>, served quickly from Evolved's shared
		cache and refreshed from Toolhub according to endpoint-specific TTLs. When you sign
		in with Toolhub, supported writes are sent back to the official Toolhub API using
		your OAuth grant.</p>
		<h2>${t("static.rulesOfEngagement.whatsEvolved", "What's Evolved-only")}</h2>
		<p>Evolved additions are visible by default. Some have real official write paths
		when you are signed in: favorites, lists, direct tool submissions, core edits
		where Toolhub permits them, community annotations, and crawler URL registration.</p>
		<p>Future Evolved-only signals such as popularity, thanks, health, usage, and
		screenshots stay hidden until they have real backend data. They do not ship as
		fixtures or generated values.</p>
		<h2>${t("static.rulesOfEngagement.verifiedClaims", "Verified author claims")}</h2>
		<p>My tools and signed-toolinfo verification are Evolved-local evidence layers.
		A verified claim is always <strong>per tool</strong>: being verified for one tool
		does not verify the same display name everywhere, and Evolved reviewer/operator
		roles never grant official Toolhub admin or write rights.</p>
		<h2>${t("static.rulesOfEngagement.whereActionsGo", "Where your actions go")}</h2>
		<ul>
			<li>Signed-in supported writes go first to official Toolhub. If Toolhub rejects
			a write, Evolved keeps it locally as a draft or overlay where the feature
			supports that.</li>
			<li>Signed-out users can read live Toolhub data, but create/update/delete
			actions require Toolhub sign-in.</li>
			<li>The site notice can be dismissed with its close button; that only hides the
			notice in this browser and does not change where data is stored.</li>
		</ul>
		<h2>${t("static.rulesOfEngagement.honestEdges", "The honest edges")}</h2>
		<p>Because search is still based on Toolhub's live search API, a locally saved draft
		may not appear in live search until it has been accepted by official Toolhub. We
		label local overlays rather than presenting them as canonical Toolhub data.</p>
		<blockquote>${t("static.rulesOfEngagement.summary", "In short: Toolhub remains the source of truth for catalog data; Evolved publishes through Toolhub when signed in and keeps local overlay data for drafts, fallback, and features Toolhub does not expose.")}</blockquote>`
	},
	rss: {
		title: t("static.rss.title", "Feeds"),
		body: `
		<p>${t("static.rss.intro", "Follow changes to the catalog without checking back. Toolhub publishes Atom/RSS\n\t\tfeeds for activity such as recently added and recently updated tools, and for the\n\t\thistory of individual tools and lists.")}</p>
		<p>Browse the latest additions on the ${ext("https://toolhub.wikimedia.org/", t("static.rss.liveSite", "live site"))},
		or sort the ${`<a href="/search?sort=recent">${t("static.rss.browsePage", "Browse page")}</a>`} by "Recently
		updated".</p>`
	}
};
/** @param {string} slug */
export function viewStatic(slug) {
	const p = STATIC[/** @type {keyof typeof STATIC} */ (slug)];
	return p ? prosePage(p.title, p.body) : viewNotFound();
}

/* ---- Help maintain Toolhub: the contribution hub ----------------------- */
/**
 * @param {string} iconHtml
 * @param {string} title
 * @param {string} desc
 * @param {string} url
 * @param {boolean} [internal]
 */
export function linkCard(iconHtml, title, desc, url, internal) {
	const href = internal ? url : safeUrl(url);
	const attrs = internal ? "" : ` target="_blank" rel="${EXTERNAL_REL}"`;
	const arrow = internal ? "" : ` ${icon("external")}`;
	return `<a class="linkcard" href="${href || "#"}"${attrs}>
		<span class="linkcard__icon" aria-hidden="true">${iconHtml}</span>
		<span class="linkcard__body"><span class="linkcard__title">${esc(title)}${arrow}</span>
		<span class="linkcard__desc">${esc(desc)}</span></span></a>`;
}
/**
 * @param {string} iconHtml
 * @param {string} title
 * @param {string} desc
 * @param {string} href
 */
function proxyCard(iconHtml, title, desc, href) {
	return `<a class="linkcard" href="${esc(href)}" target="_blank" rel="${EXTERNAL_REL}">
		<span class="linkcard__icon" aria-hidden="true">${iconHtml}</span>
		<span class="linkcard__body"><span class="linkcard__title">${esc(title)} ${icon("external")}</span>
		<span class="linkcard__desc">${esc(desc)}</span></span></a>`;
}
export function viewContribute() {
	const html = `
	<div class="container page">
		<h1 class="page__title">${t("static.helpMaintainToolhub", "Help maintain Toolhub")}</h1>
		<p class="page__intro">${t("static.contribute.intro", "Toolhub is free and open source, built by the community\n\t\tunder Wikimedia Cloud Services. Here is everything you need to report a problem,\n\t\ttranslate, or contribute code — pick a starting point.")}</p>

		<h2 class="contribute__h2">Report &amp; track work</h2>
		<div class="linkgrid">
			${linkCard(icon("report"), t("static.contribute.reportBug", "Report a bug or request a feature"), t("static.contribute.reportBugDesc", "Open a task on the #toolhub Phabricator board."), "https://phabricator.wikimedia.org/tag/toolhub/")}
			${linkCard(icon("check"), t("static.contribute.firstTask", "Find a good first task"), t("static.contribute.firstTaskDesc", "Browse open work and pick something to start with."), "https://phabricator.wikimedia.org/tag/toolhub/")}
			${linkCard(icon("discuss"), t("static.contribute.discuss", "Discuss the project"), t("static.contribute.discussDesc", "Share ideas and feedback on the Toolhub talk page."), "https://meta.wikimedia.org/wiki/Talk:Toolhub")}
		</div>

		<h2 class="contribute__h2">${t("static.contribute.writeCode", "Write code")}</h2>
		<div class="linkgrid">
			${linkCard(icon("code"), t("static.contribute.sourceCode", "Source code (Gerrit)"), t("static.contribute.sourceCodeDesc", "The canonical repository where changes are reviewed."), "https://gerrit.wikimedia.org/r/admin/repos/wikimedia/toolhub")}
			${linkCard(icon("code"), t("static.contribute.githubMirror", "GitHub mirror"), t("static.contribute.githubMirrorDesc", "Read-only mirror for browsing the code and history."), "https://github.com/wikimedia/toolhub")}
			${linkCard(icon("tools"), t("static.contribute.devEnv", "Set up a dev environment"), t("static.contribute.devEnvDesc", "The CONTRIBUTING guide: run the whole stack with Docker."), "https://github.com/wikimedia/toolhub/blob/main/docs/CONTRIBUTING.rst")}
			${linkCard(icon("key"), t("static.contribute.devAccess", "Get developer access"), t("static.contribute.devAccessDesc", "Create a Wikimedia developer account and configure Gerrit."), "https://www.mediawiki.org/wiki/Developer_access")}
		</div>

		<h2 class="contribute__h2">Translate &amp; document</h2>
		<div class="linkgrid">
			${linkCard(icon("language"), t("static.contribute.translate", "Translate Toolhub"), t("static.contribute.translateDesc", "Localise the interface into your language on translatewiki.net."), "https://translatewiki.net/wiki/Translating:Toolhub")}
			${linkCard(icon("code"), t("static.contribute.apiGuide", "API explorer"), t("static.contribute.apiGuideDesc", "Run live read-only endpoints, inspect responses, and copy integration examples."), "/api-docs", true)}
			${linkCard(icon("code"), t("static.contribute.toolinfoStandard", "The toolinfo standard"), t("static.contribute.toolinfoStandardDesc", "Learn the schema that describes a tool, and the API."), "/api-docs", true)}
			${linkCard(icon("edit"), t("static.contribute.improveListing", "Add or improve a tool listing"), t("static.contribute.improveListingDesc", "List your own tool, or enrich an existing record."), "/help", true)}
		</div>
	</div>`;
	return { title: t("static.helpMaintainToolhub", "Help maintain Toolhub"), html };
}
// API docs — the live docs cannot be framed, so link out and list same-origin endpoints.
export async function viewApiDocs() {
	const root = await apiGet("/").catch(() => ({}));
	const endpoints = Object.keys(root).sort();
	const endpointCards = endpoints
		.map((ep) => {
			const href = `/api/${ep}/`;
			return `<a class="linkcard" href="${esc(href)}" target="_blank" rel="${EXTERNAL_REL}">
			<span class="linkcard__icon" aria-hidden="true">${icon("code")}</span>
			<span class="linkcard__body"><span class="linkcard__title"><code>GET ${esc(href)}</code> ${icon("external")}</span>
			<span class="linkcard__desc">${t("static.apiDocs.endpointCardDesc", "Open the live JSON response through this app's read-only proxy.")}</span></span></a>`;
		})
		.join("");
	return {
		title: t("static.apiDocs.title", "API documentation — Toolhub"),
		html: `
		<div class="container page api-docs-page">
			<h1 class="page__title">${t("static.apiDocs.heading", "API documentation")}</h1>
			<p class="page__intro">Toolhub is API-first. Evolved reads the live catalog through a same-origin proxy and sends authenticated writes through its own <code>/v1/write/*</code> official-first lifecycle after Toolhub OAuth sign-in.</p>
			<div class="linkgrid">
				${linkCard(icon("code"), t("static.apiDocs.interactiveDocs", "Interactive API docs"), t("static.apiDocs.interactiveDocsDesc", "Open the canonical Toolhub API documentation."), "https://toolhub.wikimedia.org/api-docs")}
				${proxyCard(icon("code"), t("static.apiDocs.openApiSchema", "OpenAPI schema"), t("static.apiDocs.openApiSchemaDesc", "Machine-readable schema served at GET /api/schema/."), "/api/schema/")}
				${proxyCard(icon("tools"), t("static.apiDocs.codegenInput", "Code generation input"), t("static.apiDocs.codegenInputDesc", "Use /api/schema/ with OpenAPI Generator, Swagger Codegen, or your language's SDK tooling."), "/api/schema/")}
				${linkCard(icon("code"), t("static.apiDocs.toolinfoSchema", "toolinfo JSON Schema"), t("static.apiDocs.toolinfoSchemaDesc", "Open the official 1.2.2 schema source used for crawled toolinfo.json files."), TOOLINFO_SCHEMA_URL)}
				${linkCard(icon("tools"), t("static.apiDocs.toolinfoFieldReference", "Toolinfo field reference"), t("static.apiDocs.toolinfoFieldReferenceDesc", "Read the field meanings, core versus annotation boundary, and controlled values."), TOOLINFO_DATA_MODEL_URL)}
				${proxyCard(icon("globe"), t("static.apiDocs.apiRoot", "API root"), t("static.apiDocs.apiRootDesc", "Browse the proxied endpoint index used by this prototype."), "/api/")}
			</div>
			${renderApiExplorer()}
			<h2 class="contribute__h2">${t("static.apiDocs.toolinfoSchemaHeading", "toolinfo.json schema")}</h2>
			<div class="prose">
				<p>${t("static.apiDocs.toolinfoSchemaBodyBefore", "Toolhub validates registered")} <code>toolinfo.json</code> ${t("static.apiDocs.toolinfoSchemaBodyAfter", "files against schema version {version}. Required fields are name, title, description, and url; use _schema to identify the toolinfo schema version when you publish a file.", { version: TOOLINFO_SCHEMA_VERSION })}</p>
				<pre tabindex="0" aria-label="${t("static.apiDocs.toolinfoExampleLabel", "Minimal toolinfo JSON example")}"><code>${esc(TOOLINFO_EXAMPLE_JSON)}</code></pre>
				<p><a href="${esc(TOOLINFO_SCHEMA_URL)}" target="_blank" rel="${EXTERNAL_REL}">${t("static.apiDocs.openToolinfoSchemaSource", "Open official schema source")} ${icon("external")}</a><br>
				<a href="${esc(TOOLINFO_DATA_MODEL_URL)}" target="_blank" rel="${EXTERNAL_REL}">${t("static.apiDocs.openToolinfoFieldReference", "Open Toolhub field reference")} ${icon("external")}</a></p>
			</div>
			<h2 class="contribute__h2">${t("static.apiDocs.schemaHeading", "OpenAPI schema for code generation")}</h2>
			<div class="prose">
				<p><code>GET /api/schema/</code> returns Toolhub's OpenAPI document. Use the live
				<code>https://toolhub.wikimedia.org/api/schema/</code> URL when generating a
				production client, or this prototype's proxied <code>/api/schema/</code> when
				you want to inspect the same document without leaving this site.</p>
				<pre tabindex="0" aria-label="${t("static.apiDocs.generatorCommandLabel", "OpenAPI Generator command")}"><code>openapi-generator-cli generate -i https://toolhub.wikimedia.org/api/schema/ -g python -o toolhub-client</code></pre>
			</div>
			<h2 class="contribute__h2">${t("static.apiDocs.readOnlyBoundary", "Read-only boundary")}</h2>
			<p class="page__intro">The public proxy exposes anonymous live Toolhub <code>GET</code> responses for browsing and examples. Authenticated writes never go through that proxy; they use Evolved's CSRF-protected backend bridge so official OAuth tokens stay server-side.</p>
			<h2 class="contribute__h2">${t("static.apiDocs.revisionDiffHeading", "Revision diffs and JSON Patch operations")}</h2>
			<div class="prose">
				<p>Tool and list history endpoints expose revision rows, and their <code>diff</code>
				subresources return what older tickets may call <code>jsondiff</code> operations.
				In the live Toolhub OpenAPI schema these are standard RFC 6902
				<code>application/json-patch+json</code> operations.</p>
				<ul>
					<li><code>GET /api/tools/{name}/revisions/</code> lists tool revisions.</li>
					<li><code>GET /api/tools/{name}/revisions/{id}/diff/{other_id}/</code> compares two tool revisions.</li>
					<li><code>GET /api/lists/{id}/revisions/{revision_id}/diff/{other_id}/</code> does the same for lists.</li>
				</ul>
				<p>A diff response contains <code>original</code>, <code>operations</code>, and
				<code>result</code>. Apply the operations to <code>original</code> to obtain
				<code>result</code>; the URL order decides the direction of the comparison.</p>
				<pre tabindex="0" aria-label="${t("static.apiDocs.revisionDiffExampleLabel", "Revision diff JSON Patch example")}"><code>${esc(REVISION_DIFF_EXAMPLE_JSON)}</code></pre>
				<p>Each operation has an <code>op</code> such as <code>add</code>,
				<code>remove</code>, <code>replace</code>, <code>move</code>, <code>copy</code>,
				or <code>test</code>. The <code>path</code> field is a JSON Pointer inside the
				versioned document; <code>value</code> appears for add, replace, and test, while
				<code>from</code> appears for move and copy. These objects describe historical
				differences; they are not the payload format for creating or editing tools.</p>
			</div>
			<h2 class="contribute__h2">${t("static.apiDocs.endpointExamples", "Small endpoint examples")}</h2>
			<ul class="page__intro">
				<li><strong>${t("static.apiDocs.exampleSearchTools", "Search tools")}</strong><br><code>GET /api/search/tools/?q=wikidata&amp;page_size=5</code></li>
				<li><strong>${t("static.apiDocs.exampleReadOneTool", "Read one tool")}</strong><br><code>GET /api/tools/{name}/</code></li>
				<li><strong>${t("static.apiDocs.exampleToolRevisionDiff", "Tool revision diff")}</strong><br><code>GET /api/tools/{name}/revisions/{id}/diff/{other_id}/</code></li>
				<li><strong>${t("static.apiDocs.exampleFeaturedLists", "Featured lists")}</strong><br><code>GET /api/lists/?featured=true&amp;page_size=6</code></li>
				<li><strong>${t("static.apiDocs.exampleRecentChanges", "Recent changes")}</strong><br><code>GET /api/recent/?page_size=10</code></li>
				<li><strong>${t("static.apiDocs.exampleCrawlerRuns", "Crawler runs")}</strong><br><code>GET /api/crawler/runs/?page_size=5</code></li>
				<li><strong>${t("static.apiDocs.exampleAuditLog", "Audit log")}</strong><br><code>GET /api/auditlogs/?page_size=5</code></li>
			</ul>
			<h2 class="contribute__h2">${t("static.apiDocs.liveProxyEndpoints", "Live proxy endpoints")}</h2>
			<div class="linkgrid">${endpointCards || `<p class="empty">${t("static.apiDocs.endpointIndexUnavailable", "The live endpoint index is unavailable.")}</p>`}</div>
		</div>`,
		mount: mountApiExplorer
	};
}
/* ---- Sign-in-required stubs (auth/write features) ---------------------- */
/**
 * @param {string} title
 * @param {string} [lead]
 * @returns {{ title: string, html: string }}
 */
export function signInPage(title, lead) {
	return {
		title: t("static.pageTitle", "{title} — Toolhub", { title }),
		html: `
		<div class="container page"><article class="prose prose--page">
			<h1>${esc(title)}</h1>
			<p>${lead}</p>
			<p>${t("static.signIn.oauthNote", "Toolhub Evolved signs you in with official Toolhub OAuth, then uses Toolhub's user API to identify you locally.")}</p>
			<p>${button(t("static.signIn.continueButton", "Sign in with Toolhub"), { variant: "primary", href: "/oauth/login", icon: "external" })}</p>
			<p class="signin-note">${t("static.signIn.readOnlyNote", "Official writes still follow Toolhub's permissions. Evolved keeps supported rejected writes locally as drafts or overlays so you can revise them.")}</p>
		</article></div>`
	};
}
export function viewNotFound() {
	return {
		title: t("static.notFound.title", "Not found — Toolhub"),
		html: `
		<div class="container page errorpage">
			<h1>${t("static.notFound.heading", "Page not found")}</h1>
			<p class="prose">${t("static.notFound.body", "We couldn't find that page. It may have moved, or the link may be incomplete.")}</p>
			${button(t("static.notFound.homeButton", "Go to the home page"), { variant: "primary", href: "/" })}
		</div>`
	};
}
