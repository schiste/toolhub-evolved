// SPDX-License-Identifier: GPL-3.0-or-later
import { esc, safeUrl } from "../lib/core/dom.js";
import { t, tWithElements } from "../lib/core/i18n.js";
import { devLoginAvailable } from "../lib/core/serversync.js";
import { button } from "../lib/atoms/button.js";
import { icon } from "../lib/atoms/icon.js";

/* ---- Static prose pages (T9) ------------------------------------------- */
/**
 * @param {string} title
 * @param {string} bodyHtml
 * @param {string} [modifier] CSS modifier without the `prose--` prefix
 * @returns {{ title: string, html: string }}
 */
export function prosePage(title, bodyHtml, modifier = "") {
	const className = modifier ? ` prose--${modifier}` : "";
	return {
		title: t("static.pageTitle", "$1 — Toolhub", title),
		html: `<div class="container page"><article class="prose prose--page${className}"><h1>${esc(title)}</h1>${bodyHtml}</article></div>`
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
/** @param {string} value */
const code = (value) => `<code>${esc(value)}</code>`;
/** @param {string} value */
const blockCode = (value) => `<pre><code>${esc(value)}</code></pre>`;
/**
 * @param {string} caption
 * @param {string[]} headers
 * @param {string[][]} rows
 */
const proseTable = (caption, headers, rows) => `<div class="prose__table-wrap"><table>
	<caption>${esc(caption)}</caption>
	<thead><tr>${headers.map((header) => `<th scope="col">${esc(header)}</th>`).join("")}</tr></thead>
	<tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody>
</table></div>`;
/**
 * @param {string} href
 * @param {string} title
 * @param {string} description
 * @param {string} iconName
 */
const rssFeedItem = (href, title, description, iconName) => `<li><a href="${esc(href)}">
	${icon(iconName, "feed__ic")}
	<span class="feed__main"><strong>${esc(title)}</strong><span class="feed__sub">${esc(description)}</span></span>
	<span class="feed__when">${esc(t("static.rss.rssFormat", "RSS"))}</span>
</a></li>`;

function healthPublicFormula() {
	return blockCode(`included = [dimension for dimension in health.dimensions
            if dimension.includedInScore and dimension.score is not None]

public_score = round(
    sum(dimension.score * dimension.weight for dimension in included)
    / sum(dimension.weight for dimension in included)
)`);
}

function healthSourceFormula() {
	return blockCode(`component_dimension_score = round(
    sum(component.score for component in included_components)
    / len(included_components)
)

source_health_score = round(
    sum(dimension.score * dimension.weight for dimension in included_dimensions)
    / sum(dimension.weight for dimension in included_dimensions)
)`);
}

function healthWorkedExample() {
	return blockCode(`source-health:      88 * 1.50 = 132.00
maintainer-status: 100 * 1.25 = 125.00

public_score = round((132.00 + 125.00) / (1.50 + 1.25))
public_score = round(93.45)
public_score = 93`);
}

function healthPublicDimensionsTable() {
	return proseTable(
		t("static.healthScore.publicDimensionsCaption", "Public health dimensions"),
		[
			t("static.healthScore.dimensionHeader", "Dimension"),
			t("static.healthScore.weightHeader", "Weight"),
			t("static.healthScore.includedHeader", "Included when"),
			t("static.healthScore.sourceHeader", "Score source")
		],
		[
			[
				code("source-health"),
				code("1.5"),
				esc(
					t(
						"static.healthScore.sourceHealthIncluded",
						"The latest approved source-analysis report has a numeric healthCore score."
					)
				),
				tWithElements(
					"static.healthScore.sourceHealthSource",
					"Uses $1 from the latest approved $2 report.",
					{ html: code("healthCore.score") },
					{ html: code("SourceAnalysisReport") }
				)
			],
			[
				code("maintainer-status"),
				code("1.25"),
				esc(
					t(
						"static.healthScore.maintainerStatusIncluded",
						"At least one resolved person relationship exists and bestConfidence is numeric."
					)
				),
				tWithElements(
					"static.healthScore.maintainerStatusSource",
					"Starts from $1, then applies the activity and verification adjustments below.",
					{ html: code("bestConfidence") }
				)
			],
			[
				code("runtime-health"),
				code("1.0"),
				esc(
					t(
						"static.healthScore.runtimeHealthIncluded",
						"An enabled, approved Evolved health target exists and its latest status maps to a numeric score."
					)
				),
				tWithElements(
					"static.healthScore.runtimeHealthSource",
					"Uses the stored $1 for the approved health-check target.",
					{ html: code("last_status") }
				)
			]
		]
	);
}

function healthRuntimeScoresTable() {
	return proseTable(
		t("static.healthScore.runtimeScoresCaption", "Runtime health status mapping"),
		[t("static.healthScore.statusHeader", "Status"), t("static.healthScore.scoreHeader", "Score")],
		[
			[code("healthy"), code("95")],
			[code("ok"), code("90")],
			[code("degraded"), code("55")],
			[code("down"), code("15")],
			[code("error"), code("20")]
		]
	);
}

function healthMaintainerFormulaTable() {
	return proseTable(
		t("static.healthScore.maintainerFormulaCaption", "Public maintainer-status score"),
		[t("static.healthScore.stepHeader", "Step"), t("static.healthScore.ruleHeader", "Rule")],
		[
			[
				esc(t("static.healthScore.maintainerBaseStep", "Base")),
				tWithElements(
					"static.healthScore.maintainerBaseRule",
					"Start with $1, the highest resolved relationship confidence for the tool.",
					{ html: code("bestConfidence") }
				)
			],
			[
				esc(t("static.healthScore.maintainerActivityStep", "Activity adjustment")),
				tWithElements(
					"static.healthScore.maintainerActivityRule",
					"$1: +5; $2: -5; $3: -25; $4: -40; $5: 0.",
					{ html: code("active") },
					{ html: code("quiet") },
					{ html: code("stale") },
					{ html: code("dormant") },
					{ html: code("unknown") }
				)
			],
			[
				esc(t("static.healthScore.maintainerVerificationStep", "Verification adjustment")),
				tWithElements(
					"static.healthScore.maintainerVerificationRule",
					"If $1 is greater than 0, add 5 points.",
					{ html: code("healthCounts.verifiedPeople") }
				)
			],
			[
				esc(t("static.healthScore.maintainerEmptyStep", "Empty people set")),
				tWithElements(
					"static.healthScore.maintainerEmptyRule",
					"If $1 is 0, the dimension has no score and is excluded.",
					{ html: code("healthCounts.people") }
				)
			],
			[
				esc(t("static.healthScore.maintainerClampStep", "Clamp")),
				tWithElements("static.healthScore.maintainerClampRule", "The final value is clamped to $1.", {
					html: code("0..100")
				})
			]
		]
	);
}

function healthSourceDimensionsTable() {
	return proseTable(
		t("static.healthScore.sourceDimensionsCaption", "Source-analysis health dimensions"),
		[
			t("static.healthScore.dimensionHeader", "Dimension"),
			t("static.healthScore.weightHeader", "Weight"),
			t("static.healthScore.componentsHeader", "Component scores")
		],
		[
			[
				code("tool-health"),
				code("1.25"),
				tWithElements("static.healthScore.toolHealthComponents", "$1", { html: code("operational-readiness") })
			],
			[
				code("source-maintenance"),
				code("1.0"),
				tWithElements("static.healthScore.sourceMaintenanceComponents", "$1", {
					html: code("maintenance-activity")
				})
			],
			[
				code("maintainer-activity"),
				code("1.2"),
				tWithElements(
					"static.healthScore.sourceMaintainerActivityComponents",
					"Computed directly from trusted $1 context; excluded when the status is $2.",
					{ html: code("maintainerActivity") },
					{ html: code("unknown") }
				)
			],
			[
				code("maintainability"),
				code("1.0"),
				tWithElements(
					"static.healthScore.maintainabilityComponents",
					"Mean of $1 and $2.",
					{ html: code("maintenance-readiness") },
					{ html: code("dependency-health") }
				)
			],
			[
				code("safety"),
				code("1.15"),
				tWithElements(
					"static.healthScore.safetyComponents",
					"Mean of $1 and $2.",
					{ html: code("security-review") },
					{ html: code("permission-clarity") }
				)
			],
			[
				code("metadata-quality"),
				code("0.65"),
				tWithElements("static.healthScore.metadataQualityComponents", "$1", {
					html: code("metadata-completeness")
				})
			],
			[
				code("accessibility"),
				code("0.6"),
				tWithElements(
					"static.healthScore.accessibilityComponents",
					"$1; not applicable when no web-facing frontend technology is detected.",
					{ html: code("frontend-accessibility") }
				)
			]
		]
	);
}

function healthComponentRulesTable() {
	return proseTable(
		t("static.healthScore.componentRulesCaption", "Component point rules"),
		[
			t("static.healthScore.componentHeader", "Component"),
			t("static.healthScore.startHeader", "Starts at"),
			t("static.healthScore.adjustmentsHeader", "Adjustments before clamping")
		],
		[
			[
				code("metadata-completeness"),
				code("20"),
				esc(
					t(
						"static.healthScore.metadataCompletenessRules",
						"+15 each for publishable projects, APIs, technology, and dependencies; +10 for README documentation; +10 for license documentation."
					)
				)
			],
			[
				code("permission-clarity"),
				code("55"),
				esc(
					t(
						"static.healthScore.permissionClarityRules",
						"If no publishable access evidence exists, keep 55. If write-capable access exists, set 65, then +15 for authentication, -25 without authentication, +10 for inferred OAuth scopes, and -20 for administrator access. If only read-oriented access exists, set 90. Declared OAuth scopes add +5; inferred scopes missing from declarations subtract 15."
					)
				)
			],
			[
				code("dependency-health"),
				code("40"),
				esc(
					t(
						"static.healthScore.dependencyHealthRules",
						"+20 for a dependency manifest; +15 for publishable dependency findings, otherwise -20; +15 for a lockfile or locked dependency evidence; -10 when dependencies are inferred only from imports and no manifest exists."
					)
				)
			],
			[
				code("security-review"),
				code("85"),
				tWithElements(
					"static.healthScore.securityReviewRules",
					"Warnings subtract points: $1: -35, $2: -20, $3: -20. Authentication evidence adds +5; security documentation adds +5.",
					{ html: code("credential-like-source") },
					{ html: code("administrator-actions") },
					{ html: code("write-without-auth-signal") }
				)
			],
			[
				code("maintenance-readiness"),
				code("25"),
				esc(
					t(
						"static.healthScore.maintenanceReadinessRules",
						"+20 for README; +10 for license; +15 for tests; +15 for CI; +10 for changelog, contributing, security, or owners documentation; +10 for repository metadata."
					)
				)
			],
			[
				code("maintenance-activity"),
				code("50"),
				tWithElements(
					"static.healthScore.maintenanceActivityRules",
					"Repository status from last commit age: $1 <= 90 days adds 30, $2 <= 365 days adds 10, $3 <= 730 days subtracts 20, $4 > 730 days subtracts 35. Contributor count >= 2 adds 10; contributor count = 1 subtracts 10; commit count < 5 subtracts 10.",
					{ html: code("active") },
					{ html: code("quiet") },
					{ html: code("stale") },
					{ html: code("dormant") }
				)
			],
			[
				code("operational-readiness"),
				code("35"),
				esc(
					t(
						"static.healthScore.operationalReadinessRules",
						"+20 for runtime or deployment configuration; +20 when Toolforge context is detected; +15 for a health-check signal or declared health URL; +10 for CI."
					)
				)
			],
			[
				code("frontend-accessibility"),
				code("45"),
				esc(
					t(
						"static.healthScore.frontendAccessibilityRules",
						"Only created for JavaScript, TypeScript, React, Vue, or MediaWiki gadget tools. +20 for accessibility markup or tests; +20 for an axe dependency; +10 for tests."
					)
				)
			],
			[
				code("maintainer-activity"),
				esc(t("static.healthScore.statusMapStart", "status map")),
				tWithElements(
					"static.healthScore.sourceMaintainerActivityRules",
					"$1: 85, $2: 70, $3: 40, $4: 20, $5: no score. Active maintainer count >= 2 adds 10; active maintainer count = 0 subtracts 15; maintainer count >= 2 adds 5; maintainer count = 0 subtracts 25; recent activity count > 0 adds 5.",
					{ html: code("active") },
					{ html: code("quiet") },
					{ html: code("stale") },
					{ html: code("dormant") },
					{ html: code("unknown") }
				)
			]
		]
	);
}

function healthThresholdsTable() {
	return proseTable(
		t("static.healthScore.thresholdsCaption", "Shared thresholds and filters"),
		[t("static.healthScore.nameHeader", "Name"), t("static.healthScore.valueHeader", "Value")],
		[
			[
				esc(t("static.healthScore.publishableFindingName", "Publishable source finding")),
				tWithElements(
					"static.healthScore.publishableFindingValue",
					"$1 >= 0.55 and $2 >= 0.55.",
					{ html: code("confidence") },
					{ html: code("maxSourceWeight") }
				)
			],
			[
				esc(t("static.healthScore.repositoryStatusName", "Repository and maintainer activity status")),
				tWithElements(
					"static.healthScore.repositoryStatusValue",
					"$1: age <= 90 days; $2: age <= 365 days; $3: age <= 730 days; $4: age > 730 days; $5: no age.",
					{ html: code("active") },
					{ html: code("quiet") },
					{ html: code("stale") },
					{ html: code("dormant") },
					{ html: code("unknown") }
				)
			],
			[
				esc(t("static.healthScore.gradeName", "Grade")),
				tWithElements(
					"static.healthScore.gradeValue",
					"Legendary ($1) >= 85; Great ($2) >= 70; Needs attention ($3) >= 50; Needs attention ($4) < 50; Unknown ($5) when no score exists.",
					{ html: code("strong") },
					{ html: code("good") },
					{ html: code("needs-attention") },
					{ html: code("high-risk") },
					{ html: code("unknown") }
				)
			],
			[
				esc(t("static.healthScore.publicStatusName", "Public status")),
				tWithElements(
					"static.healthScore.publicStatusValue",
					"$1 >= 85; $2 >= 50; $3 < 50; $4 when no score exists.",
					{ html: code("healthy") },
					{ html: code("watch") },
					{ html: code("at-risk") },
					{ html: code("unknown") }
				)
			],
			[
				esc(t("static.healthScore.roundingName", "Rounding")),
				tWithElements(
					"static.healthScore.roundingValue",
					"The backend uses Python $1; exact .5 ties follow Python's nearest-even behavior.",
					{ html: code("round()") }
				)
			],
			[
				esc(t("static.healthScore.clampName", "Score bounds")),
				tWithElements("static.healthScore.clampValue", "Each component and dimension score is clamped to $1.", {
					html: code("0..100")
				})
			]
		]
	);
}

function healthSourceWeightsTable() {
	return proseTable(
		t("static.healthScore.sourceWeightsCaption", "Source class weights used by publishable finding filters"),
		[t("static.healthScore.sourceClassHeader", "Source class"), t("static.healthScore.weightHeader", "Weight")],
		[
			[code("runtime"), code("1.0")],
			[code("manifest"), code("1.0")],
			[code("frontend"), code("0.95")],
			[code("lockfile"), code("0.95")],
			[code("config"), code("0.85")],
			[code("docs"), code("0.75")],
			[code("ci"), code("0.75")],
			[code("unknown"), code("0.55")],
			[code("test"), code("0.35")],
			[code("example"), code("0.25")],
			[code("analysis-tooling"), code("0.15")],
			[code("fixture"), code("0.15")]
		]
	);
}

function viewHealthScoreStaticPage() {
	return {
		title: t("static.healthScore.title", "Health score system"),
		body: `
		<p>${t("static.healthScore.intro", "This page is the reproducibility spec for Evolved health scores. A user should be able to take the public summary JSON for a tool, apply the formulas below, and arrive at the same score shown in the interface.")}</p>
		<blockquote>${tWithElements("static.healthScore.summaryEndpoint", "Use $1 to inspect the public calculation payload. The visible tooltip on each health score exposes the same dimensions.", { html: code("/v1/tools/summaries/?name=TOOL_NAME") })}</blockquote>
		<h2>${t("static.healthScore.publicScoreTitle", "1. Public score")}</h2>
		<p>${tWithElements(
			"static.healthScore.publicScoreBody",
			"The public score is calculated from $1. Only dimensions where $2 is true and $3 is numeric are used in the numerator and denominator.",
			{ html: code("health.dimensions") },
			{ html: code("includedInScore") },
			{ html: code("score") }
		)}</p>
		${healthPublicFormula()}
		${healthPublicDimensionsTable()}
		${healthRuntimeScoresTable()}
		${healthMaintainerFormulaTable()}
		<h2>${t("static.healthScore.sourceScoreTitle", "2. Source-health score")}</h2>
		<p>${tWithElements(
			"static.healthScore.sourceScoreBody",
			"$1 is itself a weighted score from the latest approved deterministic source-analysis report. Component dimensions with more than one component first take the rounded mean of their component scores.",
			{ html: code("source-health") }
		)}</p>
		${healthSourceFormula()}
		${healthSourceDimensionsTable()}
		<h2>${t("static.healthScore.componentRulesTitle", "3. Component point rules")}</h2>
		<p>${t("static.healthScore.componentRulesBody", "The source analyzer starts each component from a fixed base value, applies the deterministic adjustments below, then clamps the result to the 0 to 100 range.")}</p>
		${healthComponentRulesTable()}
		<h2>${t("static.healthScore.filtersTitle", "4. Filters, thresholds, and rounding")}</h2>
		<p>${t("static.healthScore.filtersBody", "Source findings only affect scoring when they pass the publishable evidence filter. This prevents weak examples, fixtures, and low-confidence strings from counting the same as runtime or manifest evidence.")}</p>
		${healthThresholdsTable()}
		${healthSourceWeightsTable()}
		<h2>${t("static.healthScore.variablesTitle", "5. Variables used")}</h2>
		<ul>
			<li>${tWithElements("static.healthScore.catalogVariablesItem", "Cached official Toolhub catalog data supplies tool identity and maintainer metadata such as $1, authors, maintainers, tool type, repository URL, documentation URLs, keywords, license, deprecation state, and listing modified timestamp.", { html: code("tool.name") })}</li>
			<li>${t("static.healthScore.maintainerVariablesItem", "Evolved people indexing supplies person count, verified person count, active person count, relationship evidence count, best confidence, last public contribution age, recent contribution count, related tool count, and verified tool count.")}</li>
			<li>${t("static.healthScore.sourceVariablesItem", "Source analysis supplies detected Wikimedia projects, API actions, OAuth scopes, access-right classes, credential warnings, dependencies, lockfiles, manifests, CI evidence, tests, docs, frontend accessibility evidence, source file classes, and suggested toolinfo metadata.")}</li>
			<li>${t("static.healthScore.repositoryVariablesItem", "Trusted repository context supplies repository URL, provider, branch, default branch, last commit timestamp, commit id, commit count, contributor count, tag, dirty state, and analysis timestamp.")}</li>
			<li>${t("static.healthScore.runtimeVariablesItem", "Evolved runtime checks supply target URL, latest status, last checked timestamp, and last stored error when an approved health target exists.")}</li>
		</ul>
		<h2>${t("static.healthScore.exampleTitle", "6. Worked example")}</h2>
		<p>${t("static.healthScore.exampleBody", "If a tool has source-health 88 and maintainer-status 100, with no included runtime-health dimension, the public score is reproduced as follows.")}</p>
		${healthWorkedExample()}
		<h2>${t("static.healthScore.notUsedTitle", "7. What is not used")}</h2>
		<ul>
			<li>${t("static.healthScore.noPopularityItem", "Popularity, page views, thanks, subjective ratings, and manual editorial preference are not part of the score.")}</li>
			<li>${t("static.healthScore.noLiveCallsItem", "Page load does not call GitHub, Gerrit, Toolforge, package registries, or a live tool endpoint to calculate a score. It reads stored Evolved summaries.")}</li>
			<li>${t("static.healthScore.noSecretsItem", "Raw source files and secrets are not stored in the public summary. The analyzer stores bounded, redacted findings and evidence excerpts.")}</li>
			<li>${t("static.healthScore.noLlmItem", "No large language model output is used to calculate the score.")}</li>
		</ul>
		<h2>${t("static.healthScore.codeReferenceTitle", "8. Code references")}</h2>
		<p>${tWithElements(
			"static.healthScore.codeReferenceBody",
			"The public score is assembled in $1. Source-analysis health core and component scoring are implemented in $2.",
			{ html: code("proxy/backend/v1.py") },
			{ html: code("proxy/backend/source_analyzer.py") }
		)}</p>`
	};
}
// Faithful summaries of real Toolhub / Wikimedia content, rendered in our style.
// Canonical policies link out to their authoritative source (as the real site does).
const rssPage = () => ({
	title: t("static.rss.title", "Feeds"),
	body: `
		<p>${t("static.rss.intro", "Subscribe to Toolhub activity without opening the app. These feeds are public RSS 2.0 XML generated server-side from Toolhub's official read APIs through Evolved's shared cache.")}</p>
		<h2>${t("static.rss.catalogFeedsTitle", "Catalog feeds")}</h2>
		<ul class="feed">
			${rssFeedItem("/feeds/recent.xml", t("static.rss.recentFeedTitle", "Recent changes"), t("static.rss.recentFeedDesc", "Official Toolhub catalog activity across tools and lists."), "history")}
			${rssFeedItem("/feeds/tools/recently-updated.xml", t("static.rss.recentToolsFeedTitle", "Recently updated tools"), t("static.rss.recentToolsFeedDesc", "Tools ordered by the official Toolhub modified date."), "tools")}
			${rssFeedItem("/feeds/lists.xml", t("static.rss.listsFeedTitle", "Lists"), t("static.rss.listsFeedDesc", "Public Toolhub lists from the official lists endpoint."), "list")}
		</ul>
		<h2>${t("static.rss.historyFeedsTitle", "History feeds")}</h2>
		<p>${t("static.rss.historyFeedsIntro", "Tool and list revision feeds are available by URL pattern. Replace the identifier with the encoded Toolhub tool name or list id.")}</p>
		<ul>
			<li>${tWithElements("static.rss.toolHistoryPattern", "Tool revisions: $1", { html: code("/feeds/tools/TOOL_NAME/revisions.xml") })}</li>
			<li>${tWithElements("static.rss.listHistoryPattern", "List revisions: $1", { html: code("/feeds/lists/LIST_ID/revisions.xml") })}</li>
		</ul>
		<h2>${t("static.rss.relatedPagesTitle", "Related pages")}</h2>
		<p>${tWithElements(
			"static.rss.relatedPagesBody",
			"Browse the same data in the app on $1, $2, or $3.",
			{ html: `<a href="/recent">${esc(t("static.rss.recentPage", "Recent changes"))}</a>` },
			{
				html: `<a href="/search?sort=recent">${esc(t("static.rss.recentToolsPage", "recently updated tools"))}</a>`
			},
			{ html: `<a href="/lists">${esc(t("static.rss.listsPage", "lists"))}</a>` }
		)}</p>`
});

export const STATIC = {
	about: () => ({
		title: t("static.about.title", "About Toolhub"),
		body: `
		<p>${t("static.about.catalogIntro", "Toolhub is a community-managed catalog of software tools used in the Wikimedia movement. Technical volunteers document the tools they build, and all Wikimedians can search the catalog, build lists, and share them.")}</p>
		<p>${t("static.about.toolDefinition", 'A "tool" is defined inclusively: user scripts, gadgets, bots, templates, Lua modules, web applications and mobile apps that interact with Wikimedia projects. The catalog aims to be inclusive rather than exclusive, as long as an entry helps people work on the projects.')}</p>
		<h2>${t("static.about.howToolsGetHere", "How tools get here")}</h2>
		<p>${tWithElements("static.about.howToolsGetHereBody", "Tools enter the catalog three ways: by registering a $1 URL that Toolhub crawls roughly hourly, through the Toolhub UI, or via the API ($2). All paths validate against the same versioned schema, so the data stays consistent.", { html: code("toolinfo.json") }, { html: code("POST /api/tools/") })}</p>
		<h2>${t("static.about.coreVsAnnotations", "Core information vs. annotations")}</h2>
		<p>${t("static.about.coreVsAnnotationsBody", "Each tool has authoritative core information, editable only by its owner or administrators, plus community annotations that any logged-in Wikimedian can enrich. When both are set for a field, Toolhub shows the core value, balancing maintainer control with community contribution.")}</p>
		<p>${t("static.about.cc0", "Structured data is released under CC0; attribution via links back is\n\t\tencouraged but not required. Sign in with Toolhub — no separate Evolved account\n\t\tor password is needed.")}</p>
		<p>${tWithElements("static.about.helpBuildBody", "Want to help improve this beta or coordinate with upstream Toolhub? See $1.", { html: `<a href="/contribute">${esc(t("static.community.contributeLink", "Help maintain Toolhub Evolved"))}</a>` })}</p>
		<blockquote>${t("static.about.prototypeNote", "This is a companion interface for Toolhub: it reads live catalog data from the public API, publishes official writes through Toolhub OAuth when you sign in, and keeps Evolved-only additions in its local overlay database.")}</blockquote>`
	}),
	help: () => ({
		title: t("static.help.title", "Help"),
		body: `
		<p>${t("static.help.intro", "New to Toolhub? Here is the quickest path to finding and sharing tools. Sign\n\t\tin with Toolhub to save favourites, build lists, and publish permitted edits —\n\t\tno separate Evolved account is needed.")}</p>
		<h2>${t("static.help.findTool", "Find a tool")}</h2>
		<ul>
			<li>${t("static.help.searchItem", "Search by name, keyword, or what you want to do.")}</li>
			<li>${t("static.help.filterItem", "Filter on the Browse page by tool type and keywords.")}</li>
			<li>${t("static.help.browseByNeedItem", "Browse by need from the home-page shortcuts.")}</li>
		</ul>
		<h2>${t("static.help.shareTool", "Share a tool")}</h2>
		<p>${tWithElements("static.help.shareToolBody", "Maintainers can publish a $1 file in their repository so volunteers can submit improvements over time, or create a record directly in the UI or API.", { html: code("toolinfo.json") })}</p>
		<h2>${t("static.help.buildList", "Build a list")}</h2>
		<p>${t("static.help.buildListBody", "Group useful tools into a list and share it — great for onboarding new editors\n\t\tor running an event.")}</p>
		<p>${`<a href="/about">${esc(t("static.help.learnMore", "Learn more about Toolhub →"))}</a>`}</p>`
	}),
	community: () => ({
		title: t("static.community.title", "Community"),
		body: `
		<p>${t("static.community.intro", "Toolhub Evolved is an experimental companion interface for the Toolhub catalog. It is run as an individual beta project on Toolforge, built in the open, and designed to stay compatible with the Wikimedia Toolhub ecosystem rather than replace it.")}</p>
		<h2>${t("static.community.evolvedChannels", "Evolved project channels")}</h2>
		<ul>
			<li>${tWithElements("static.community.evolvedIssuesItem", "Use $1 for Evolved-specific bugs, interface feedback, and feature proposals.", { html: ext("https://github.com/schiste/toolhub-evolved/issues", t("static.community.evolvedIssues", "Toolhub Evolved issues")) })}</li>
			<li>${tWithElements("static.community.evolvedSourceItem", "Read the prototype source in $1; changes should preserve the design system, accessibility expectations, deterministic scoring, and i18n-ready message boundaries.", { html: ext("https://github.com/schiste/toolhub-evolved", t("static.community.evolvedSource", "the Toolhub Evolved repository")) })}</li>
			<li>${tWithElements("static.community.evolvedFeedsItem", "Follow local activity through $1 and the in-app feature status page.", { html: `<a href="/feeds">${esc(t("static.community.feeds", "RSS feeds"))}</a>` })}</li>
		</ul>
		<h2>${t("static.community.upstreamChannels", "Official Toolhub channels")}</h2>
		<p>${t("static.community.upstreamIntro", "For official Toolhub policy, production catalog behavior, or upstream bugs that are not specific to this beta interface, use Wikimedia's canonical Toolhub channels.")}</p>
		<ul>
			<li>${tWithElements("static.community.talkItem", "Discuss official Toolhub on $1 (Meta-Wiki).", { html: ext("https://meta.wikimedia.org/wiki/Talk:Toolhub", "Talk:Toolhub") })}</li>
			<li>${tWithElements("static.community.phabricatorItem", "File official Toolhub work on the $1.", { html: ext("https://phabricator.wikimedia.org/tag/toolhub/", t("static.community.phabricatorBoard", "#toolhub Phabricator board")) })}</li>
			<li>${tWithElements("static.community.translateItem", "Translate the official Toolhub interface on $1. Evolved keeps strings i18n-ready, but full translatewiki integration is intentionally later.", { html: ext("https://translatewiki.net/wiki/Translating:Toolhub", "translatewiki.net") })}</li>
		</ul>
		<p>${tWithElements("static.community.contributeBody", "For practical next steps on this beta, start at $1.", { html: `<a href="/contribute">${esc(t("static.community.contributeLink", "Help maintain Toolhub Evolved"))}</a>` })}</p>`
	}),
	privacy: () => ({
		title: t("static.privacy.title", "Privacy policy"),
		body: `
		<p>${tWithElements("static.privacy.betaDisclaimer", "Toolhub Evolved is an individual-run beta on Toolforge. It is not operated, endorsed, or maintained by the Wikimedia Foundation. The project tries to stay aligned with the $1, and official Toolhub/Wikimedia interactions remain governed by Wikimedia's authoritative policy.", { html: ext("https://foundation.wikimedia.org/wiki/Policy:Privacy_policy", t("static.privacy.policyLink", "Wikimedia Foundation Privacy Policy")) })}</p>
		<h2>${t("static.privacy.localDataTitle", "What this beta handles locally")}</h2>
		<ul>
			<li>${t("static.privacy.oauthItem", "If you sign in, the beta uses official Toolhub OAuth and stores a local session plus a server-side OAuth grant. It never asks for or stores your Wikimedia password.")}</li>
			<li>${t("static.privacy.evolvedDraftsItem", "Evolved-only drafts, fallback writes, signed-toolinfo public keys, local author claims, activity rows, preferences, and health/source-analysis review data may be stored in this site's local database.")}</li>
			<li>${t("static.privacy.browserCacheItem", "The browser may cache live catalog responses, local UI state, theme/language choices, dismissed notices, and local fallback data so pages can load quickly and recover after failed writes.")}</li>
			<li>${t("static.privacy.officialWritesItem", "When an action is sent to official Toolhub, Toolhub's own API receives the request and applies Toolhub attribution, permissions, validation, logging, and retention rules.")}</li>
		</ul>
		<h2>${t("static.privacy.boundariesTitle", "Boundaries")}</h2>
		<p>${t("static.privacy.boundariesBody", "Do not paste secrets, private credentials, or non-public personal data into Evolved-only forms. Source-analysis and tool metadata features are intended for public tool information.")}</p>
		<p>${tWithElements("static.privacy.readFullPolicy", "For Wikimedia account, Toolhub, and Wikimedia project data, read the full $1.", { html: ext("https://foundation.wikimedia.org/wiki/Policy:Privacy_policy", t("static.privacy.policyShort", "Privacy Policy")) })}</p>`
	}),
	terms: () => ({
		title: t("static.terms.title", "Terms of Use"),
		body: `
		<p>${tWithElements("static.terms.betaDisclaimer", "Toolhub Evolved is an individual-run beta on Toolforge, not a Wikimedia Foundation-operated service. It aims to behave consistently with the $1, but the Wikimedia Foundation Terms of Use are the authoritative terms for official Toolhub, Wikimedia accounts, and Wikimedia project activity.", { html: ext("https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use", t("static.terms.termsLink", "Wikimedia Foundation Terms of Use")) })}</p>
		<h2>${t("static.terms.betaUseTitle", "Using this beta")}</h2>
		<ul>
			<li>${t("static.terms.experimentalItem", "The interface is experimental and may change, fail, or remove Evolved-only data while features are being developed.")}</li>
			<li>${t("static.terms.noSecretsItem", "Do not submit secrets, private credentials, or confidential data. Tool metadata, source-analysis input, and community annotations should describe public tools.")}</li>
			<li>${t("static.terms.officialActionsItem", "Actions that publish to official Toolhub are still subject to Toolhub permissions, audit history, validation, and Wikimedia account rules.")}</li>
		</ul>
		<h2>${t("static.terms.contentTitle", "Content and responsibility")}</h2>
		<p>${tWithElements("static.terms.contributionTerms", "Structured Toolhub catalog data is made available under CC0. Evolved source code is published separately in $1. Tools listed here are owned and operated by their respective maintainers; this beta catalogs and enriches metadata but does not host or endorse the tools.", { html: ext("https://github.com/schiste/toolhub-evolved", t("static.terms.evolvedSource", "the Toolhub Evolved repository")) })}</p>
		<p>${tWithElements("static.terms.readFullTerms", "For authoritative Wikimedia legal terms, read the full $1.", { html: ext("https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use", t("static.terms.title", "Terms of Use")) })}</p>`
	}),
	"code-of-conduct": () => ({
		title: t("static.codeOfConduct.title", "Code of Conduct"),
		body: `
		<p>${tWithElements("static.codeOfConduct.intro", "Toolhub Evolved expects participation to follow the spirit of the $1. This beta is not an official Wikimedia Foundation venue, but it is built for Wikimedia contributors and should stay compatible with Wikimedia technical-space norms.", { html: ext("https://www.mediawiki.org/wiki/Code_of_Conduct", t("static.codeOfConduct.cocLink", "Code of Conduct for Wikimedia technical spaces")) })}</p>
		<h2>${t("static.codeOfConduct.expectedBehaviour", "Expected behaviour")}</h2>
		<ul>
			<li>${t("static.codeOfConduct.expectedGoodFaithItem", "Assume good faith, be specific in feedback, and separate critique of the interface from critique of contributors.")}</li>
			<li>${t("static.codeOfConduct.expectedA11yItem", "Treat accessibility, localization, privacy, and newcomer usability as core project quality concerns.")}</li>
			<li>${t("static.codeOfConduct.expectedNoHarassmentItem", "Harassment, personal attacks, discriminatory language, and pressure to expose private information are not acceptable.")}</li>
		</ul>
		<h2>${t("static.codeOfConduct.reporting", "Reporting")}</h2>
		<p>${tWithElements("static.codeOfConduct.reportingBody", "For Evolved-specific project conduct in the GitHub repository, use $1 when public reporting is appropriate. For Wikimedia technical spaces, follow the official reporting paths in the Code of Conduct. For threats of harm, contact local authorities first, then $2.", { html: ext("https://github.com/schiste/toolhub-evolved/issues", t("static.community.evolvedIssues", "Toolhub Evolved issues")) }, { html: code("emergency@wikimedia.org") })}</p>`
	}),
	api: () => ({
		title: t("static.api.title", "API"),
		body: `
		<p>${t("static.api.intro", "Toolhub is built API-first: everything you can do in this interface is also available over a documented HTTP API, so anyone can build their own tools on top of the catalog.")}</p>
		<ul>
			<li>${tWithElements("static.api.interactiveDocsItem", "Browse the interactive documentation at $1.", { html: ext("https://toolhub.wikimedia.org/api-docs", "toolhub.wikimedia.org/api-docs") })}</li>
			<li>${tWithElements("static.api.evolvedApiDocsItem", "Use this prototype's $1 for read-only examples, response inspection, and schema pointers.", { html: `<a href="/api-docs">${esc(t("static.api.apiDocsPage", "API explorer"))}</a>` })}</li>
			<li>${tWithElements("static.api.openApiItem", "The OpenAPI schema and endpoints live under $1.", { html: ext("https://toolhub.wikimedia.org/api/", "/api/") })}</li>
			<li>${tWithElements("static.api.writeAccessItem", "Read access is anonymous; creating or editing records uses your Wikimedia OAuth identity. For example, $1 adds a tool.", { html: code("POST /api/tools/") })}</li>
		</ul>`
	}),
	"rules-of-engagement": () => ({
		title: t("static.rulesOfEngagement.title", "Rules of Engagement"),
		body: `
		<p>${t("static.rulesOfEngagement.intro", "This is a companion interface on a separate domain, not the official Toolhub frontend. It exists to run next to Toolhub: live Toolhub data remains the base, while Evolved adds a local overlay for extra and fallback data.")}</p>
		<h2>${t("static.rulesOfEngagement.whatsReal", "What's real")}</h2>
		<p>${tWithElements("static.rulesOfEngagement.whatsRealBody", "The catalog itself is genuine: user-facing tools, search, facets, tool details, lists, members, recent changes, crawler history, and audit logs come from $1 through the read proxy. Evolved also keeps a server-side canonical cache of official tool records for background enrichment and resilience; that cache is rebuildable, is not the source of truth, and never replaces live Toolhub authority. When you sign in with Toolhub, supported writes are sent back to the official Toolhub API using your OAuth grant.", { html: ext("https://toolhub.wikimedia.org/api/", "toolhub.wikimedia.org") })}</p>
		<h2>${t("static.rulesOfEngagement.catalogSync", "How the catalog cache is maintained")}</h2>
		<ul>
			<li>${t("static.rulesOfEngagement.catalogSyncBackfill", "The initial backfill processes at most five pages of 100 records every 15 minutes, with at least three seconds between upstream requests. A persistent cursor resumes after interruptions and advances until the first complete catalog cycle finishes.")}</li>
			<li>${t("static.rulesOfEngagement.catalogSyncSteady", "After that first cycle, Evolved checks the newest Toolhub recent-change page every 15 minutes and fetches only changed tool details. It processes at most 20 changed details per run; failed details remain in a retry queue.")}</li>
			<li>${t("static.rulesOfEngagement.catalogSyncReconcile", "As a safety net, one catalog page is reconciled every 12 hours. This spreads a full reconciliation across roughly a month for a catalog of several thousand tools instead of repeatedly reingesting the whole catalog.")}</li>
		</ul>
		<h2>${t("static.rulesOfEngagement.repositoryAnalysis", "Repository and health analysis")}</h2>
		<p>${t("static.rulesOfEngagement.repositoryAnalysisBody", "Repository analysis is deterministic and runs only for canonical tools with an eligible public HTTPS repository URL. Evolved allows GitHub, GitLab, Wikimedia GitLab, Wikimedia Gerrit, Codeberg, and Bitbucket hosts; it performs shallow non-recursive Git checkouts, does not execute repository code, removes symlinks before traversal, caps checkout size, and stores redacted findings tied to the observed commit. The scheduled worker checks at most 100 repository candidates per hour and skips unchanged commits.")}</p>
		<h2>${t("static.rulesOfEngagement.whatsEvolved", "What's Evolved-only")}</h2>
		<p>${t("static.rulesOfEngagement.whatsEvolvedBody", "Evolved additions are visible by default. Some have real official write paths when you are signed in: favorites, lists, direct tool submissions, core edits where Toolhub permits them, community annotations, and crawler URL registration.")}</p>
		<p>${t("static.rulesOfEngagement.futureSignalsBody", "Future Evolved-only signals such as popularity, thanks, health, usage, and screenshots stay hidden until they have real backend data. They do not ship as fixtures or generated values.")}</p>
		<h2>${t("static.rulesOfEngagement.verifiedClaims", "Verified author claims")}</h2>
		<p>${t("static.rulesOfEngagement.verifiedClaimsBody", "My tools and signed-toolinfo verification are Evolved-local evidence layers. A verified claim is always per tool: being verified for one tool does not verify the same display name everywhere, and Evolved reviewer/operator roles never grant official Toolhub admin or write rights.")}</p>
		<h2>${t("static.rulesOfEngagement.whereActionsGo", "Where your actions go")}</h2>
		<ul>
			<li>${t("static.rulesOfEngagement.officialWritesItem", "Signed-in supported writes go first to official Toolhub. If Toolhub rejects a write, Evolved keeps it locally as a draft or overlay where the feature supports that.")}</li>
			<li>${t("static.rulesOfEngagement.signedOutItem", "Signed-out users can read live Toolhub data, but create/update/delete actions require Toolhub sign-in.")}</li>
			<li>${t("static.rulesOfEngagement.noticeItem", "The site notice can be dismissed with its close button; that only hides the notice in this browser and does not change where data is stored.")}</li>
		</ul>
		<h2>${t("static.rulesOfEngagement.honestEdges", "The honest edges")}</h2>
		<p>${t("static.rulesOfEngagement.honestEdgesBody", "Because search is still based on Toolhub's live search API, a locally saved draft may not appear in live search until it has been accepted by official Toolhub. We label local overlays rather than presenting them as canonical Toolhub data.")}</p>
		<blockquote>${t("static.rulesOfEngagement.summary", "In short: Toolhub remains the source of truth for catalog data; Evolved publishes through Toolhub when signed in and keeps local overlay data for drafts, fallback, and features Toolhub does not expose.")}</blockquote>`
	}),
	"health-score": viewHealthScoreStaticPage,
	feeds: rssPage,
	rss: rssPage
};
/** @param {string} slug */
export function viewStatic(slug) {
	const p = STATIC[/** @type {keyof typeof STATIC} */ (slug)]?.();
	return p ? prosePage(p.title, p.body, slug === "health-score" ? "wide" : "") : viewNotFound();
}

/* ---- Help maintain Toolhub Evolved: the contribution hub ---------------- */
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
		<h1 class="page__title">${t("static.contribute.title", "Help maintain Toolhub Evolved")}</h1>
		<p class="page__intro">${t("static.contribute.intro", "Toolhub Evolved is a public beta for exploring Toolhub interface, discovery, maintainer, health-score, and developer-workflow improvements. Contributions should improve this prototype while respecting Toolhub as the upstream source of truth.")}</p>

		<h2 class="contribute__h2">${t("static.contribute.evolvedWork", "Improve Toolhub Evolved")}</h2>
		<div class="linkgrid">
			${linkCard(icon("report"), t("static.contribute.reportBug", "Report a beta issue"), t("static.contribute.reportBugDesc", "Open a Toolhub Evolved GitHub issue for UI bugs, data-display gaps, or broken beta behavior."), "https://github.com/schiste/toolhub-evolved/issues")}
			${linkCard(icon("check"), t("static.contribute.firstTask", "Find scoped work"), t("static.contribute.firstTaskDesc", "Browse open Evolved issues and prefer small, testable changes tied to one page or workflow."), "https://github.com/schiste/toolhub-evolved/issues")}
			${linkCard(icon("tools"), t("static.contribute.featureStatus", "Feature status"), t("static.contribute.featureStatusDesc", "Check which Evolved features are live, local-only, upstream-backed, or intentionally deferred."), "/experiments", true)}
		</div>

		<h2 class="contribute__h2">${t("static.contribute.writeCode", "Write code")}</h2>
		<div class="linkgrid">
			${linkCard(icon("code"), t("static.contribute.sourceCode", "Toolhub Evolved source"), t("static.contribute.sourceCodeDesc", "Browse the beta source, deployment notes, tests, and recent commits."), "https://github.com/schiste/toolhub-evolved")}
			${linkCard(icon("tools"), t("static.contribute.designSystem", "Design system"), t("static.contribute.designSystemDesc", "Use the shared tokens, atoms, molecules, organisms, and templates before adding bespoke UI."), "/styleguide", true)}
			${linkCard(icon("code"), t("static.contribute.apiGuide", "API explorer"), t("static.contribute.apiGuideDesc", "Run live read-only endpoints, inspect responses, and copy integration examples."), "/api-docs", true)}
			${linkCard(icon("check"), t("static.contribute.healthScore", "Health score system"), t("static.contribute.healthScoreDesc", "Understand the deterministic scoring inputs before changing public health signals."), "/health-score", true)}
		</div>

		<h2 class="contribute__h2">${t("static.contribute.upstreamCoordination", "Coordinate with upstream Toolhub")}</h2>
		<div class="linkgrid">
			${linkCard(icon("discuss"), t("static.contribute.officialDiscussion", "Official Toolhub discussion"), t("static.contribute.officialDiscussionDesc", "Use Meta-Wiki when the question is about Toolhub policy, upstream product direction, or the canonical catalog."), "https://meta.wikimedia.org/wiki/Talk:Toolhub")}
			${linkCard(icon("report"), t("static.contribute.officialPhabricator", "Official Toolhub Phabricator"), t("static.contribute.officialPhabricatorDesc", "File upstream Toolhub production issues that are not specific to this Evolved beta interface."), "https://phabricator.wikimedia.org/tag/toolhub/")}
			${linkCard(icon("code"), t("static.contribute.upstreamSource", "Official Toolhub source"), t("static.contribute.upstreamSourceDesc", "Reference the upstream Toolhub implementation when Evolved behavior must stay compatible."), "https://gerrit.wikimedia.org/r/admin/repos/wikimedia/toolhub")}
			${linkCard(icon("language"), t("static.contribute.translate", "Translation readiness"), t("static.contribute.translateDesc", "Keep Evolved strings i18n-ready now; full translatewiki integration is a later project phase."), "/rules-of-engagement", true)}
		</div>
	</div>`;
	return { title: t("static.contribute.title", "Help maintain Toolhub Evolved"), html };
}
// API docs — the live docs cannot be framed, so link out and list same-origin endpoints.
export async function viewApiDocs() {
	const [
		{ apiGet },
		{ mountApiExplorer, renderApiExplorer },
		{ TOOLINFO_DATA_MODEL_URL, TOOLINFO_EXAMPLE_JSON, TOOLINFO_SCHEMA_URL, TOOLINFO_SCHEMA_VERSION }
	] = await Promise.all([
		import("../lib/core/api.js"),
		import("../lib/organisms/api-explorer.js"),
		import("../lib/core/toolinfo-docs.js")
	]);
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
			<p class="page__intro">${tWithElements("static.apiDocs.intro", "Toolhub is API-first. Evolved reads the live catalog through a same-origin proxy and sends authenticated writes through its own $1 official-first lifecycle after Toolhub OAuth sign-in.", { html: code("/v1/write/*") })}</p>
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
				<p>${tWithElements("static.apiDocs.toolinfoSchemaBody", "Toolhub validates registered $1 files against schema version $2. Required fields are name, title, description, and url; use _schema to identify the toolinfo schema version when you publish a file.", { html: "<code>toolinfo.json</code>" }, { html: `<code>${esc(TOOLINFO_SCHEMA_VERSION)}</code>` })}</p>
				<pre tabindex="0" aria-label="${t("static.apiDocs.toolinfoExampleLabel", "Minimal toolinfo JSON example")}"><code>${esc(TOOLINFO_EXAMPLE_JSON)}</code></pre>
				<p><a href="${esc(TOOLINFO_SCHEMA_URL)}" target="_blank" rel="${EXTERNAL_REL}">${t("static.apiDocs.openToolinfoSchemaSource", "Open official schema source")} ${icon("external")}</a><br>
				<a href="${esc(TOOLINFO_DATA_MODEL_URL)}" target="_blank" rel="${EXTERNAL_REL}">${t("static.apiDocs.openToolinfoFieldReference", "Open Toolhub field reference")} ${icon("external")}</a></p>
			</div>
			<h2 class="contribute__h2">${t("static.apiDocs.schemaHeading", "OpenAPI schema for code generation")}</h2>
			<div class="prose">
				<p>${tWithElements("static.apiDocs.schemaBody", "$1 returns Toolhub's OpenAPI document. Use the live $2 URL when generating a production client, or this prototype's proxied $3 when you want to inspect the same document without leaving this site.", { html: code("GET /api/schema/") }, { html: code("https://toolhub.wikimedia.org/api/schema/") }, { html: code("/api/schema/") })}</p>
				<pre tabindex="0" aria-label="${t("static.apiDocs.generatorCommandLabel", "OpenAPI Generator command")}"><code>openapi-generator-cli generate -i https://toolhub.wikimedia.org/api/schema/ -g python -o toolhub-client</code></pre>
			</div>
			<h2 class="contribute__h2">${t("static.apiDocs.readOnlyBoundary", "Read-only boundary")}</h2>
			<p class="page__intro">${tWithElements("static.apiDocs.readOnlyBoundaryBody", "The public proxy exposes anonymous live Toolhub $1 responses for browsing and examples. Authenticated writes never go through that proxy; they use Evolved's CSRF-protected backend bridge so official OAuth tokens stay server-side.", { html: code("GET") })}</p>
			<h2 class="contribute__h2">${t("static.apiDocs.revisionDiffHeading", "Revision diffs and JSON Patch operations")}</h2>
			<div class="prose">
				<p>${tWithElements("static.apiDocs.revisionDiffBody", "Tool and list history endpoints expose revision rows, and their $1 subresources return what older tickets may call $2 operations. In the live Toolhub OpenAPI schema these are standard RFC 6902 $3 operations.", { html: code("diff") }, { html: code("jsondiff") }, { html: code("application/json-patch+json") })}</p>
				<ul>
					<li>${tWithElements("static.apiDocs.toolRevisionsItem", "$1 lists tool revisions.", { html: code("GET /api/tools/{name}/revisions/") })}</li>
					<li>${tWithElements("static.apiDocs.toolRevisionDiffItem", "$1 compares two tool revisions.", { html: code("GET /api/tools/{name}/revisions/{id}/diff/{other_id}/") })}</li>
					<li>${tWithElements("static.apiDocs.listRevisionDiffItem", "$1 does the same for lists.", { html: code("GET /api/lists/{id}/revisions/{revision_id}/diff/{other_id}/") })}</li>
				</ul>
				<p>${tWithElements("static.apiDocs.diffResponseBody", "A diff response contains $1, $2, and $3. Apply the operations to $1 to obtain $3; the URL order decides the direction of the comparison.", { html: code("original") }, { html: code("operations") }, { html: code("result") })}</p>
				<pre tabindex="0" aria-label="${t("static.apiDocs.revisionDiffExampleLabel", "Revision diff JSON Patch example")}"><code>${esc(REVISION_DIFF_EXAMPLE_JSON)}</code></pre>
				<p>${tWithElements("static.apiDocs.operationBody", "Each operation has an $1 such as $2. The $3 field is a JSON Pointer inside the versioned document; $4 appears for add, replace, and test, while $5 appears for move and copy. These objects describe historical differences; they are not the payload format for creating or editing tools.", { html: code("op") }, { html: `${code("add")}, ${code("remove")}, ${code("replace")}, ${code("move")}, ${code("copy")}, ${esc(t("static.apiDocs.or", "or"))} ${code("test")}` }, { html: code("path") }, { html: code("value") }, { html: code("from") })}</p>
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
			<h2 class="contribute__h2">${t("static.apiDocs.communityDirectory", "Community directory API")}</h2>
			<div class="prose">
				<p>${t("static.apiDocs.communityContract", "The public directory is one search over resolved people, official Toolhub accounts, related tools, and unresolved name-only attributions. Stable identifiers may connect evidence; usernames and display names never merge identities automatically.")}</p>
				<ul>
					<li>${tWithElements("static.apiDocs.unifiedCommunityEndpoint", "$1 is the product-facing ranked and paginated search. It separates primary people/accounts, relationship-backed or structured tool matches, unresolved display-label evidence, and description-only mentions. Each tool carries every applicable typed relationship and its provenance.", { html: code("GET /v1/community/") })}</li>
					<li>${tWithElements("static.apiDocs.peopleEndpoint", "$1 searches public identities with pagination, relationship, verification, activity, project, and ordering filters. Add $2 to require contributor eligibility; each result explains its evidence basis.", { html: code("GET /v1/people/") }, { html: code("contributor=observed") })}</li>
					<li>${tWithElements("static.apiDocs.accountsEndpoint", "$1 searches the complete local official-account projection by substring, exact group, name or recent ordering, and page. The response includes total count and projection sync state.", { html: code("GET /v1/accounts/") })}</li>
					<li>${tWithElements("static.apiDocs.accountDetailEndpoint", "$1 returns official registration facts. A $2 appears only after an immutable Toolhub user id or Wikimedia global user id match; usernames never create that link.", { html: code("GET /v1/accounts/{toolhub_user_id}/") }, { html: code("personId") })}</li>
				</ul>
			</div>
			<h2 class="contribute__h2">${t("static.apiDocs.connectedIdentities", "Connected identity API")}</h2>
			<div class="prose">
				<p>${t("static.apiDocs.connectedIdentityContract", "These private endpoints let a signed-in user inspect stable account bindings and optionally prove control of legacy Toolforge developer accounts. Account proof establishes identity only; it grants no Toolhub write permission.")}</p>
				<ul>
					<li>${tWithElements("static.apiDocs.accountLinksEndpoint", "$1 returns verified bindings, safe handle-match candidates, proof capability, and upstream repair links. The response is private and never cached.", { html: code("GET /v1/me/account-links/") })}</li>
					<li>${tWithElements("static.apiDocs.accountLinkChallengeEndpoint", "$1 creates a ten-minute, single-use challenge bound to the signed-in user, person, and immutable Toolforge uidNumber.", { html: code("POST /v1/me/account-links/toolforge/challenges/") })}</li>
					<li>${tWithElements("static.apiDocs.accountLinkVerifyEndpoint", "$1 verifies an OpenSSH SSHSIG against current LDAP public keys, consumes the challenge, and rebuilds every Toolforge membership relationship for that account.", { html: code("POST /v1/me/account-links/toolforge/verify/") })}</li>
				</ul>
			</div>
			<h2 class="contribute__h2">${t("static.apiDocs.liveProxyEndpoints", "Live proxy endpoints")}</h2>
			<div class="linkgrid">${endpointCards || `<p class="empty">${t("static.apiDocs.endpointIndexUnavailable", "The live endpoint index is unavailable.")}</p>`}</div>
		</div>`,
		mount: () => mountApiExplorer()
	};
}
/* ---- Sign-in-required stubs (auth/write features) ---------------------- */
/**
 * @param {string} title
 * @param {string} [lead]
 * @returns {{ title: string, html: string }}
 */
export function signInPage(title, lead) {
	const nextPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
	const devLogin = devLoginAvailable();
	const signInHref = devLogin ? `/oauth/dev-login?next=${encodeURIComponent(nextPath)}` : "/oauth/login";
	const signInIcon = devLogin ? "system" : "external";
	const signInLabel = devLogin
		? t("static.signIn.devLoginButton", "Use local dev sign-in")
		: t("static.signIn.continueButton", "Sign in with Toolhub");
	const signInNote = devLogin
		? t(
				"static.signIn.devLoginNote",
				"Local dev sign-in creates an Evolved-only test session. Official Toolhub writes stay unavailable."
			)
		: t(
				"static.signIn.oauthNote",
				"Toolhub Evolved signs you in with official Toolhub OAuth, then uses Toolhub's user API to identify you locally."
			);
	return {
		title: t("static.pageTitle", "$1 — Toolhub", title),
		html: `
		<div class="container page"><article class="prose prose--page">
			<h1>${esc(title)}</h1>
			<p>${lead}</p>
			<p>${signInNote}</p>
			<p>${button(signInLabel, { variant: "primary", href: signInHref, icon: signInIcon })}</p>
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
