// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

const h = vi.hoisted(() => ({
	backendGetJson: vi.fn(),
	serverWrite: vi.fn(),
	writeText: vi.fn()
}));

vi.mock("../../public_html/lib/core/api.js", async (orig) => {
	const actual = await orig();
	return { ...actual, backendGetJson: h.backendGetJson };
});
vi.mock("../../public_html/lib/core/serversync.js", async (orig) => {
	const actual = await orig();
	return { ...actual, serverWrite: h.serverWrite };
});

const { sourceAnalysisContextSampleJson, sourceAnalysisSampleJson, sourceAnalysisWorkspace } =
	await import("../../public_html/lib/organisms/source-analysis.js");

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function sourceReport() {
	return {
		id: 7,
		toolName: "ada-tool",
		sourceLabel: "local checkout",
		reviewStatus: "open",
		createdAt: "2026-07-29T12:00:00Z",
		report: {
			toolName: "ada-tool",
			sourceLabel: "local checkout",
			filesAnalyzed: 1,
			summary: {
				filesAnalyzed: 1,
				projectCount: 1,
				apiCount: 1,
				accessRightCount: 1,
				dependencyCount: 1,
				oauthScopeCount: 0,
				technologyCount: 1,
				warningCount: 0,
				assessmentCount: 2,
				assessmentScore: 78,
				healthScore: 74,
				healthConfidence: 0.82,
				maintenanceStatus: "quiet",
				maintainerStatus: "active",
				stewardshipStatus: "source-stale-maintainer-active"
			},
			repositoryContext: {
				repository: { url: "https://github.com/example/ada-tool", branch: "main", commitSha: "abc123" },
				inventory: { bySourceClass: [{ class: "frontend", count: 1, weight: 0.95 }] },
				maintenance: { status: "quiet", lastCommitAgeDays: 120 },
				maintainerActivity: { status: "active", lastActivityAgeDays: 4, maintainerCount: 2 },
				documentation: [{ kind: "readme", path: "README.md" }],
				manifests: [{ kind: "npm", path: "package.json" }],
				lockfiles: [{ kind: "npm", path: "package-lock.json" }],
				ci: [{ kind: "github-actions", path: ".github/workflows/ci.yml" }],
				runtime: [{ kind: "container", path: "Dockerfile" }],
				dependencySources: { count: 1, ecosystems: ["npm"], categories: [{ category: "runtime", count: 1 }] }
			},
			healthCore: {
				schemaVersion: 1,
				score: 74,
				grade: "good",
				confidence: 0.82,
				sourceMaintenanceStatus: "quiet",
				maintainerActivityStatus: "active",
				stewardshipStatus: "source-stale-maintainer-active",
				dimensions: [
					{ key: "tool-health", label: "Tool health", score: 80, grade: "good", status: "good" },
					{
						key: "maintainer-activity",
						label: "Maintainer activity",
						score: 90,
						grade: "strong",
						status: "active"
					}
				]
			},
			projects: [
				{
					value: "enwiki",
					label: "en.wikipedia.org",
					category: "wiki",
					confidence: 0.9,
					maxSourceWeight: 0.95,
					reasons: ["Wikimedia project hostname detected."],
					sourceClasses: ["frontend"],
					evidence: [{ path: "src/app.js", line: 2, excerpt: "https://en.wikipedia.org/w/api.php" }]
				}
			],
			apis: [{ value: "mediawiki-action-api", label: "MediaWiki Action API", confidence: 0.92 }],
			accessRights: [{ value: "edit", label: "Edit pages", category: "write", confidence: 0.94 }],
			authentication: [],
			dependencies: [
				{ value: "npm:mediawiki-api", label: "mediawiki-api (npm)", category: "runtime", confidence: 0.98 }
			],
			assessments: [
				{
					key: "metadata-completeness",
					label: "Metadata completeness",
					score: 85,
					grade: "strong",
					summary: "Enough context for metadata suggestions.",
					signals: [
						{ status: "positive", label: "Projects detected", evidence: { path: "src/app.js", line: 2 } }
					],
					recommendations: []
				},
				{
					key: "permission-clarity",
					label: "Permission clarity",
					score: 70,
					grade: "good",
					summary: "Write actions need scope review.",
					signals: [{ status: "neutral", label: "Write-capable actions detected" }],
					recommendations: ["Declare OAuth scopes."]
				}
			],
			oauthScopes: [],
			technology: [{ value: "JavaScript", label: "JavaScript", category: "language", confidence: 0.64 }],
			warnings: [],
			suggestions: {
				toolinfoPatch: { for_wikis: ["enwiki"], technology_used: ["JavaScript"] },
				evolvedMetadata: {
					apis: ["mediawiki-action-api"],
					access_rights: ["edit"],
					dependencies: ["npm:mediawiki-api"],
					health_core: { score: 74, grade: "good" },
					health_confidence: 0.82,
					maintainer_status: "active",
					oauth_scopes: [],
					stewardship_status: "source-stale-maintainer-active",
					warnings: []
				}
			}
		}
	};
}

beforeEach(() => {
	vi.clearAllMocks();
	document.body.innerHTML = "";
	Object.defineProperty(navigator, "clipboard", {
		configurable: true,
		value: { writeText: h.writeText }
	});
});

test("source analysis workspace renders shared account controls", () => {
	const workspace = sourceAnalysisWorkspace();
	assert.ok(workspace.html.includes("Source code analysis"));
	assert.ok(workspace.html.includes("Source files JSON"));
	assert.ok(workspace.html.includes("Repository context JSON"));
	assert.ok(workspace.html.includes("Analyze source"));
	assert.ok(sourceAnalysisSampleJson().includes("src/example.js"));
	assert.ok(sourceAnalysisContextSampleJson().includes("commitSha"));
});

test("source analysis workspace loads saved reports and copies the suggested patch", async () => {
	h.backendGetJson.mockResolvedValue({ results: [sourceReport()] });
	const workspace = sourceAnalysisWorkspace();
	document.body.innerHTML = workspace.html;
	workspace.mount();
	await tick();

	assert.deepEqual(h.backendGetJson.mock.calls[0], ["/v1/source-analysis/?limit=5"]);
	assert.ok(document.body.innerHTML.includes("ada-tool"));
	assert.ok(document.body.innerHTML.includes("en.wikipedia.org"));
	assert.ok(document.body.innerHTML.includes("Metadata completeness"));
	assert.ok(document.body.innerHTML.includes("Repository context"));
	assert.ok(document.body.innerHTML.includes("Source classes"));
	assert.ok(document.body.innerHTML.includes("Health"));
	assert.ok(document.body.innerHTML.includes("Health core"));
	assert.ok(document.body.innerHTML.includes("Maintainer activity"));
	assert.ok(document.body.innerHTML.includes("quiet"));

	document.querySelector("[data-source-analysis-copy]").click();
	await tick();
	assert.match(h.writeText.mock.calls[0][0], /"for_wikis"/);
	assert.equal(document.querySelector("[data-source-analysis-status]").textContent, "Suggested patch copied.");
});

test("source analysis workspace submits JSON source bundles and reviews reports", async () => {
	h.backendGetJson.mockResolvedValue({ results: [sourceReport()] });
	h.serverWrite.mockResolvedValue({ sourceAnalysis: sourceReport() });
	const workspace = sourceAnalysisWorkspace();
	document.body.innerHTML = workspace.html;
	workspace.mount();
	await tick();

	document.querySelector("#source-analysis-tool").value = "ada-tool";
	document.querySelector("#source-analysis-label").value = "local checkout";
	document.querySelector("#source-analysis-json").value = sourceAnalysisSampleJson();
	document.querySelector("#source-analysis-context-json").value = '{"declared":{"oauthScopes":["editpage"]}}';
	document.querySelector("[data-source-analysis-form]").dispatchEvent(new Event("submit", { bubbles: true }));
	await tick();
	await tick();

	assert.deepEqual(h.serverWrite.mock.calls[0], [
		"POST",
		"/v1/source-analysis/",
		{
			toolName: "ada-tool",
			sourceLabel: "local checkout",
			files: JSON.parse(sourceAnalysisSampleJson()),
			repositoryContext: { declared: { oauthScopes: ["editpage"] } }
		}
	]);
	assert.equal(document.querySelector("[data-source-analysis-status]").textContent, "Source analysis saved.");

	document.querySelector('[data-source-analysis-review="approved"]').click();
	await tick();
	assert.deepEqual(h.serverWrite.mock.calls[1], [
		"POST",
		"/v1/source-analysis/7/review/",
		{ reviewStatus: "approved" }
	]);
});

test("source analysis workspace reports bad JSON and backend failures", async () => {
	h.backendGetJson.mockRejectedValue(new Error("offline"));
	const workspace = sourceAnalysisWorkspace();
	document.body.innerHTML = workspace.html;
	workspace.mount();
	await tick();
	assert.ok(document.querySelector("[data-source-analysis-list]").textContent.includes("offline"));

	document.querySelector("#source-analysis-json").value = "{";
	document.querySelector("[data-source-analysis-form]").dispatchEvent(new Event("submit", { bubbles: true }));
	await tick();
	assert.equal(h.serverWrite.mock.calls.length, 0);
	assert.match(document.querySelector("[data-source-analysis-status]").textContent, /JSON|Unexpected|property name/);

	document.querySelector("#source-analysis-json").value = sourceAnalysisSampleJson();
	document.querySelector("#source-analysis-context-json").value = "[]";
	document.querySelector("[data-source-analysis-form]").dispatchEvent(new Event("submit", { bubbles: true }));
	await tick();
	assert.equal(h.serverWrite.mock.calls.length, 0);
	assert.match(document.querySelector("[data-source-analysis-status]").textContent, /Repository context JSON/);
});
