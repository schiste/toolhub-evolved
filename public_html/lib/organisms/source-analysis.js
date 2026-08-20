// SPDX-License-Identifier: GPL-3.0-or-later
import { $, dirAttrs, esc, safeUrl } from "../core/dom.js";
import { backendErrorExplanation, backendGetJson } from "../core/api.js";
import { t, timeTag } from "../core/i18n.js";
import { toolHref } from "../core/routing.js";
import { serverWrite } from "../core/serversync.js";
import { button } from "../atoms/button.js";
import { fArea, fInput } from "../atoms/form-fields.js";
import { accountSection } from "./account-workbench.js";

const SAMPLE_FILES = [
	{
		path: "src/example.js",
		content:
			'const api = new mw.Api();\napi.postWithToken("csrf", { action: "edit", title: "Sandbox", text: "..." });'
	}
];

const SAMPLE_REPOSITORY_CONTEXT = {
	repository: {
		url: "https://github.com/example/tool",
		branch: "main",
		commitSha: "0123456789abcdef",
		analyzedAt: "2026-07-30T12:00:00Z",
		lastCommitAt: "2026-07-29T12:00:00Z"
	},
	declared: {
		oauthScopes: ["editpage"],
		runtime: "Toolforge webservice",
		healthUrl: "https://example.toolforge.org/healthz"
	},
	maintainers: {
		maintainerCount: 2,
		activeMaintainerCount: 1,
		lastActivityAgeDays: 14,
		recentActivityCount: 3,
		source: "Toolhub and repository activity"
	}
};

/** @type {Array<[string, () => string]>} */
const FINDING_GROUPS = [
	["projects", () => t("sourceAnalysis.projects", "Projects")],
	["apis", () => t("sourceAnalysis.apis", "APIs")],
	["accessRights", () => t("sourceAnalysis.accessRights", "Access rights")],
	["authentication", () => t("sourceAnalysis.authentication", "Authentication")],
	["dependencies", () => t("sourceAnalysis.dependencies", "Dependencies")],
	["endpoints", () => t("sourceAnalysis.endpoints", "Endpoints")],
	["oauthScopes", () => t("sourceAnalysis.oauthScopes", "OAuth scopes")],
	["technology", () => t("sourceAnalysis.technology", "Technology")],
	["warnings", () => t("sourceAnalysis.warnings", "Warnings")]
];

/** @type {Map<number, any>} */
let reportCache = new Map();

export function sourceAnalysisSampleJson() {
	return JSON.stringify(SAMPLE_FILES, null, 2);
}

export function sourceAnalysisContextSampleJson() {
	return JSON.stringify(SAMPLE_REPOSITORY_CONTEXT, null, 2);
}

/** @param {unknown} rows */
function arrayRows(rows) {
	return Array.isArray(rows) ? rows : [];
}

/** @param {unknown} report */
function reportBody(report) {
	const record = report && typeof report === "object" ? /** @type {Record<string, any>} */ (report) : {};
	return record.report && typeof record.report === "object" ? record.report : record;
}

/** @param {unknown} value */
function sourceFilesJson(value) {
	const text = String(value || "").trim();
	if (!text) {
		return [];
	}
	const parsed = JSON.parse(text);
	if (!Array.isArray(parsed)) {
		throw new Error(t("sourceAnalysis.invalidJsonShape", "JSON must be an array of files."));
	}
	return parsed;
}

/** @param {unknown} value */
function repositoryContextJson(value) {
	const text = String(value || "").trim();
	if (!text) {
		return {};
	}
	const parsed = JSON.parse(text);
	if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
		throw new Error(t("sourceAnalysis.invalidContextShape", "Repository context JSON must be an object."));
	}
	return parsed;
}

/** @param {File} file */
async function sourceFileFromBrowserFile(file) {
	return {
		path: String(/** @type {{ webkitRelativePath?: string }} */ (file).webkitRelativePath || file.name),
		content: await file.text()
	};
}

/** @param {HTMLInputElement | null} input */
async function sourceFilesFromInput(input) {
	const files = input?.files ? [...input.files] : [];
	return Promise.all(files.map((file) => sourceFileFromBrowserFile(file)));
}

/** @param {unknown} value */
function confidence(value) {
	const number = Number(value || 0);
	return `${Math.round(number * 100)}%`;
}

/** @param {unknown} rows */
function evidenceList(rows) {
	const evidence = arrayRows(rows);
	if (evidence.length === 0) return "";
	return `<details class="source-analysis__evidence">
		<summary>${t("sourceAnalysis.evidence", "Evidence")}</summary>
		<ul>
			${evidence
				.map(
					(item) => `<li>
						<code>${esc(item.path)}${Number(item.line) > 0 ? `:${esc(item.line)}` : ""}</code>
						<span>${esc(item.excerpt || item.match || "")}</span>
					</li>`
				)
				.join("")}
		</ul>
	</details>`;
}

/** @param {any} item */
function findingItem(item) {
	const category = String(item.category || "detected");
	const reasons = arrayRows(item.reasons);
	const sourceClasses = arrayRows(item.sourceClasses).slice(0, 3).join(", ");
	return `<li class="source-analysis__finding source-analysis__finding--${esc(category)}">
		<div class="source-analysis__finding-head">
			<strong>${esc(item.label || item.value)}</strong>
			<span>
				${sourceClasses ? `<span class="sync-badge sync-badge--local-draft">${esc(sourceClasses)}</span>` : ""}
				<span class="sync-badge sync-badge--official">${confidence(item.confidence)}</span>
			</span>
		</div>
		${reasons.length > 0 ? `<p>${esc(reasons.join(" "))}</p>` : ""}
		${evidenceList(item.evidence)}
	</li>`;
}

/**
 * @param {Record<string, any>} data
 * @param {string} key
 */
function findingsGroup(data, key) {
	const rows = arrayRows(data[key]);
	const group = FINDING_GROUPS.find(([groupKey]) => groupKey === key);
	const label = group ? group[1]() : key;
	return `<section class="source-analysis__group" aria-labelledby="source-analysis-${esc(key)}">
		<h3 id="source-analysis-${esc(key)}">${esc(label)} <span class="source-analysis__group-count">${esc(String(rows.length))}</span></h3>
		${
			rows.length > 0
				? `<ul class="source-analysis__findings" role="list">${rows.map((item) => findingItem(item)).join("")}</ul>`
				: `<p class="empty">${t("sourceAnalysis.noneDetected", "None detected.")}</p>`
		}
	</section>`;
}

/** @param {any} data */
function fullSuggestionPatch(data) {
	const suggestions = data.suggestions && typeof data.suggestions === "object" ? data.suggestions : {};
	const toolinfoPatch =
		suggestions.toolinfoPatch && typeof suggestions.toolinfoPatch === "object" ? suggestions.toolinfoPatch : {};
	const evolved =
		suggestions.evolvedMetadata && typeof suggestions.evolvedMetadata === "object"
			? suggestions.evolvedMetadata
			: {};
	return {
		...toolinfoPatch,
		x_toolhub_evolved_source_analysis: evolved
	};
}

/** @param {any} data */
function suggestionBlock(data) {
	const patch = fullSuggestionPatch(data);
	const hasValues = Object.values(patch).some((value) => {
		if (Array.isArray(value)) return value.length > 0;
		return Boolean(value && typeof value === "object" ? Object.keys(value).length : value);
	});
	if (!hasValues) return `<p class="empty">${t("sourceAnalysis.noSuggestions", "No metadata suggestions yet.")}</p>`;
	return `<div class="source-analysis__suggestion">
		<div class="source-analysis__suggestion-head">
			<strong>${t("sourceAnalysis.suggestedPatch", "Suggested metadata patch")}</strong>
			${button(t("sourceAnalysis.copyPatch", "Copy patch"), {
				size: "sm",
				icon: "code",
				attrs: "data-source-analysis-copy"
			})}
		</div>
		<pre tabindex="0"><code>${esc(JSON.stringify(patch, null, 2))}</code></pre>
	</div>`;
}

/** @param {unknown} status */
function reviewBadge(status) {
	const value = String(status || "open");
	const className =
		value === "approved" ? "review-approved" : value === "rejected" ? "review-rejected" : "local-draft";
	const label =
		value === "approved"
			? t("sourceAnalysis.reviewApproved", "Accepted")
			: value === "rejected"
				? t("sourceAnalysis.reviewRejected", "Rejected")
				: t("sourceAnalysis.reviewOpen", "Open review");
	return `<span class="sync-badge sync-badge--${className}">${esc(label)}</span>`;
}

/** @param {unknown} value */
function gradeLabel(value) {
	const grade = String(value || "");
	if (grade === "strong") return t("sourceAnalysis.gradeStrong", "Legendary");
	if (grade === "good") return t("sourceAnalysis.gradeGood", "Great");
	if (grade === "needs-attention") return t("sourceAnalysis.gradeAttention", "Needs attention");
	if (grade === "unknown") return t("sourceAnalysis.gradeUnknown", "Unknown");
	if (grade === "not-applicable") return t("sourceAnalysis.gradeNotApplicable", "Not applicable");
	return t("sourceAnalysis.gradeRisk", "Needs attention");
}

/** @param {unknown} value */
function gradeClass(value) {
	const grade = String(value || "");
	if (grade === "strong") return "legendary";
	if (grade === "good") return "great";
	if (grade === "needs-attention") return "review-pending";
	if (grade === "unknown" || grade === "not-applicable") return "unknown";
	return "sync-error";
}

/** @param {any} signal */
function assessmentSignal(signal) {
	const status = String(signal.status || "neutral");
	const evidence = signal.evidence || {};
	const detail = signal.detail ? `<span>${esc(signal.detail)}</span>` : "";
	const evidenceText = evidence.path
		? `<code>${esc(evidence.path)}${Number(evidence.line) > 0 ? `:${esc(evidence.line)}` : ""}</code>`
		: "";
	return `<li class="source-analysis__assessment-signal source-analysis__assessment-signal--${esc(status)}">
		<strong>${esc(signal.label || "")}</strong>
		${detail}
		${evidenceText}
	</li>`;
}

/** @param {unknown} rows */
function assessmentsBlock(rows) {
	const assessments = arrayRows(rows);
	if (assessments.length === 0) return "";
	return `<section class="source-analysis__assessments" aria-label="${t("sourceAnalysis.assessments", "Assessments")}">
		${assessments
			.map(
				(
					item
				) => `<article class="source-analysis__assessment source-analysis__assessment--${esc(item.grade || "")}">
					<div class="source-analysis__assessment-head">
						<div>
							<h3>${esc(item.label || item.key)}</h3>
							<p>${esc(item.summary || "")}</p>
						</div>
						<span class="sync-badge sync-badge--${gradeClass(item.grade)}">${esc(String(item.score ?? 0))} · ${gradeLabel(item.grade)}</span>
					</div>
					${
						arrayRows(item.signals).length > 0
							? `<ul class="source-analysis__assessment-signals" role="list">${arrayRows(item.signals)
									.map((signal) => assessmentSignal(signal))
									.join("")}</ul>`
							: ""
					}
					${
						arrayRows(item.recommendations).length > 0
							? `<p class="source-analysis__assessment-recommendation">${esc(arrayRows(item.recommendations).join(" "))}</p>`
							: ""
					}
				</article>`
			)
			.join("")}
	</section>`;
}

/** @param {unknown} raw */
function replacementLink(raw) {
	// healthCore.replacedBy carries toolinfo's replaced_by verbatim, and
	// maintainers write both kinds: a URL for a successor hosted elsewhere, a
	// bare name for one already in the catalogue. Resolve them the same way the
	// tool page's replacement notice does, so one field does not mean two
	// things depending on where you read it.
	const name = String(raw ?? "").trim();
	if (!name) return "";
	const href = safeUrl(name);
	const linked = href
		? `<a href="${href}" target="_blank" rel="noopener nofollow">${esc(name)}</a>`
		: `<a href="${esc(toolHref(name))}"${dirAttrs(name)}>${esc(name)}</a>`;
	return `<p>${t("sourceAnalysis.replacedBy", "Replaced by")} ${linked}</p>`;
}

/** @param {any} data */
function healthCoreBlock(data) {
	const core = data.healthCore && typeof data.healthCore === "object" ? data.healthCore : {};
	const dimensions = arrayRows(core.dimensions);
	if (dimensions.length === 0) return "";
	return `<section class="source-analysis__assessments" aria-label="${t("sourceAnalysis.healthCore", "Health core")}">
		<article class="source-analysis__assessment source-analysis__assessment--${esc(core.grade || "")}">
			<div class="source-analysis__assessment-head">
				<div>
					<h3>${t("sourceAnalysis.healthCore", "Health core")}</h3>
					<p>${esc(core.stewardshipStatus || "")}</p>
					${replacementLink(core.replacedBy)}
				</div>
				<span class="sync-badge sync-badge--${gradeClass(core.grade)}">${esc(String(core.score ?? 0))} · ${gradeLabel(core.grade)}</span>
			</div>
			<ul class="source-analysis__assessment-signals" role="list">
				${dimensions
					.map((item) => {
						const score = item.score === null || item.score === undefined ? "—" : String(item.score);
						return `<li class="source-analysis__assessment-signal source-analysis__assessment-signal--neutral">
							<strong>${esc(item.label || item.key)}</strong>
							<span>${esc(score)} · ${gradeLabel(item.grade)} · ${esc(item.status || "")}</span>
						</li>`;
					})
					.join("")}
			</ul>
		</article>
	</section>`;
}

/** @param {unknown} rows */
function contextRows(rows) {
	return arrayRows(rows)
		.slice(0, 6)
		.map((item) => {
			const kind = item?.kind ? `${item.kind}: ` : "";
			const sourceClass = item?.sourceClass ? ` · ${item.sourceClass}` : "";
			return `<li><span>${esc(kind)}${esc(item?.path || "")}${esc(sourceClass)}</span></li>`;
		})
		.join("");
}

/** @param {unknown} rows */
function sourceClassRows(rows) {
	return arrayRows(rows)
		.slice(0, 6)
		.map((item) => `<li><span>${esc(item?.class || "")}: ${esc(String(item?.count || 0))}</span></li>`)
		.join("");
}

/** @param {any} data */
function repositoryContextBlock(data) {
	const context = data.repositoryContext && typeof data.repositoryContext === "object" ? data.repositoryContext : {};
	const repository = context.repository && typeof context.repository === "object" ? context.repository : {};
	const inventory = context.inventory && typeof context.inventory === "object" ? context.inventory : {};
	const maintenance = context.maintenance && typeof context.maintenance === "object" ? context.maintenance : {};
	const maintainerActivity =
		context.maintainerActivity && typeof context.maintainerActivity === "object" ? context.maintainerActivity : {};
	const dependencySources =
		context.dependencySources && typeof context.dependencySources === "object" ? context.dependencySources : {};
	const sections = [
		[t("sourceAnalysis.contextSourceClasses", "Source classes"), sourceClassRows(inventory.bySourceClass)],
		[t("sourceAnalysis.contextDocs", "Docs"), contextRows(context.documentation)],
		[t("sourceAnalysis.contextManifests", "Manifests"), contextRows(context.manifests)],
		[t("sourceAnalysis.contextLockfiles", "Lockfiles"), contextRows(context.lockfiles)],
		[t("sourceAnalysis.contextCi", "CI"), contextRows(context.ci)],
		[t("sourceAnalysis.contextRuntime", "Runtime"), contextRows(context.runtime)]
	].filter(([, rows]) => rows);
	if (
		!repository.url &&
		sections.length === 0 &&
		!dependencySources.count &&
		!maintenance.status &&
		!maintainerActivity.status
	) {
		return "";
	}
	return `<details class="source-analysis__context">
		<summary>${t("sourceAnalysis.repositoryContext", "Repository context")}</summary>
		<div class="source-analysis__context-grid">
			${
				repository.url
					? `<div>
						<strong>${t("sourceAnalysis.contextRepository", "Repository")}</strong>
						<p>${esc(repository.url)}</p>
						${repository.branch ? `<p>${t("sourceAnalysis.contextBranch", "Branch")}: ${esc(repository.branch)}</p>` : ""}
						${repository.commitSha ? `<p>${t("sourceAnalysis.contextCommit", "Commit")}: <code>${esc(repository.commitSha)}</code></p>` : ""}
					</div>`
					: ""
			}
			${
				maintenance.status
					? `<div>
						<strong>${t("sourceAnalysis.contextMaintenance", "Maintenance")}</strong>
						<p>${esc(maintenance.status)}${
							Number.isFinite(Number(maintenance.lastCommitAgeDays))
								? ` · ${esc(String(maintenance.lastCommitAgeDays))} ${t("sourceAnalysis.contextDays", "days")}`
								: ""
						}</p>
					</div>`
					: ""
			}
			${
				maintainerActivity.status
					? `<div>
						<strong>${t("sourceAnalysis.contextMaintainers", "Maintainers")}</strong>
						<p>${esc(maintainerActivity.status)}${
							Number.isFinite(Number(maintainerActivity.lastActivityAgeDays))
								? ` · ${esc(String(maintainerActivity.lastActivityAgeDays))} ${t("sourceAnalysis.contextDays", "days")}`
								: ""
						}</p>
					</div>`
					: ""
			}
			${
				dependencySources.count
					? `<div>
						<strong>${t("sourceAnalysis.contextDependencies", "Dependency evidence")}</strong>
						<p>${esc(String(dependencySources.count))} ${esc(arrayRows(dependencySources.ecosystems).join(", "))}</p>
					</div>`
					: ""
			}
			${sections
				.map(
					([label, rows]) => `<div>
						<strong>${esc(label)}</strong>
						<ul>${rows}</ul>
					</div>`
				)
				.join("")}
		</div>
	</details>`;
}

/** @param {any} report */
function reportActions(report) {
	if (!report.id) return "";
	const id = esc(report.id);
	return `<div class="source-analysis__actions">
		${button(t("sourceAnalysis.accept", "Accept"), {
			size: "sm",
			icon: "check",
			attrs: `data-source-analysis-review="approved" data-source-analysis-id="${id}"`
		})}
		${button(t("sourceAnalysis.reject", "Reject"), {
			size: "sm",
			variant: "danger",
			icon: "reset",
			attrs: `data-source-analysis-review="rejected" data-source-analysis-id="${id}"`
		})}
	</div>`;
}

/** @param {any} report */
function reportCard(report) {
	const data = reportBody(report);
	const title = report.toolName || data.toolName || t("sourceAnalysis.untitledReport", "Source analysis");
	const summary = data.summary || {};
	const counts = [
		[t("sourceAnalysis.files", "Files"), data.filesAnalyzed || summary.filesAnalyzed || 0],
		[t("sourceAnalysis.projects", "Projects"), summary.projectCount || 0],
		[t("sourceAnalysis.apis", "APIs"), summary.apiCount || 0],
		[t("sourceAnalysis.accessRights", "Access rights"), summary.accessRightCount || 0],
		[t("sourceAnalysis.dependencies", "Dependencies"), summary.dependencyCount || 0],
		[t("sourceAnalysis.externalEndpoints", "Third-party endpoints"), summary.externalEndpointCount || 0],
		[t("sourceAnalysis.assessmentScore", "Assessment"), summary.assessmentScore || 0],
		[t("sourceAnalysis.healthScore", "Health"), summary.healthScore || 0],
		[t("sourceAnalysis.healthConfidence", "Confidence"), summary.healthConfidence || 0],
		[t("sourceAnalysis.maintenance", "Maintenance"), summary.maintenanceStatus || "unknown"],
		[t("sourceAnalysis.maintainer", "Maintainer"), summary.maintainerStatus || "unknown"],
		[t("sourceAnalysis.warnings", "Warnings"), summary.warningCount || 0]
	];
	return `<article class="source-analysis__report" data-source-analysis-report="${esc(report.id || "")}">
		<header class="source-analysis__report-head">
			<div>
				<h3>${esc(title)}</h3>
				<p>${esc(report.sourceLabel || data.sourceLabel || t("sourceAnalysis.manualSource", "Manual source bundle"))}</p>
				${report.createdAt ? `<p class="recent-table__muted">${timeTag(report.createdAt)}</p>` : ""}
			</div>
			<div class="source-analysis__report-state">
				${reviewBadge(report.reviewStatus)}
				${reportActions(report)}
			</div>
		</header>
		<dl class="source-analysis__summary">
			${counts.map(([label, count]) => `<div><dt>${esc(label)}</dt><dd>${esc(String(count))}</dd></div>`).join("")}
		</dl>
		${healthCoreBlock(data)}
		${repositoryContextBlock(data)}
		${assessmentsBlock(data.assessments)}
		${suggestionBlock(data)}
		<div class="source-analysis__groups">
			${FINDING_GROUPS.map(([key]) => findingsGroup(data, key)).join("")}
		</div>
	</article>`;
}

/** @param {any[]} reports */
function rememberReports(reports) {
	reportCache = new Map(reports.filter((report) => Number(report?.id)).map((report) => [Number(report.id), report]));
}

/** @param {any[]} reports */
function reportsList(reports) {
	rememberReports(reports);
	if (reports.length === 0) return `<p class="empty">${t("sourceAnalysis.noReports", "No analyses saved yet.")}</p>`;
	return reports.map((report) => reportCard(report)).join("");
}

/** @param {string} message @param {"ok" | "err" | ""} [kind] */
function setSourceAnalysisStatus(message, kind = "") {
	const out = $("[data-source-analysis-status]");
	if (!out) return;
	out.className = `at__result${kind ? ` at__result--${kind}` : ""}`;
	out.textContent = message;
}

async function loadReports() {
	const list = $("[data-source-analysis-list]");
	if (!list) return;
	try {
		const data = await backendGetJson("/v1/source-analysis/?limit=5");
		list.innerHTML = reportsList(arrayRows(data?.results));
	} catch (error) {
		list.innerHTML = `<p class="empty">${esc(backendErrorExplanation(error))}</p>`;
	}
}

/** @param {Event} event */
async function submitAnalysis(event) {
	event.preventDefault();
	const form = /** @type {HTMLFormElement} */ (event.currentTarget);
	const fileInput = /** @type {HTMLInputElement | null} */ ($("#source-analysis-files"));
	const submit = $("[data-source-analysis-submit]");
	let files;
	try {
		files = [
			...sourceFilesJson(/** @type {HTMLTextAreaElement | null} */ ($("#source-analysis-json"))?.value),
			...(await sourceFilesFromInput(fileInput))
		];
	} catch (error) {
		setSourceAnalysisStatus(backendErrorExplanation(error), "err");
		return;
	}
	if (files.length === 0) {
		setSourceAnalysisStatus(
			t("sourceAnalysis.noFilesSelected", "Select source files or paste a JSON file list."),
			"err"
		);
		return;
	}
	form.setAttribute("aria-busy", "true");
	if (submit instanceof HTMLButtonElement) submit.disabled = true;
	setSourceAnalysisStatus(t("sourceAnalysis.analyzing", "Analyzing source..."));
	try {
		const repositoryContext = repositoryContextJson(
			/** @type {HTMLTextAreaElement | null} */ ($("#source-analysis-context-json"))?.value
		);
		/** @type {Record<string, any>} */
		const payload = {
			toolName: /** @type {HTMLInputElement | null} */ ($("#source-analysis-tool"))?.value.trim() || "",
			sourceLabel: /** @type {HTMLInputElement | null} */ ($("#source-analysis-label"))?.value.trim() || "",
			files
		};
		if (Object.keys(repositoryContext).length > 0) {
			payload.repositoryContext = repositoryContext;
		}
		const result = await serverWrite("POST", "/v1/source-analysis/", {
			...payload
		});
		const report = result?.sourceAnalysis;
		if (report) {
			rememberReports([report, ...reportCache.values()]);
			const current = $("[data-source-analysis-current]");
			if (current) current.innerHTML = reportCard(report);
		}
		setSourceAnalysisStatus(t("sourceAnalysis.saved", "Source analysis saved."), "ok");
		await loadReports();
	} catch (error) {
		setSourceAnalysisStatus(
			t("sourceAnalysis.failed", "Analysis failed: $1", backendErrorExplanation(error)),
			"err"
		);
	} finally {
		form.removeAttribute("aria-busy");
		if (submit instanceof HTMLButtonElement) submit.disabled = false;
	}
}

/** @param {Event} event */
async function handleSourceAnalysisAction(event) {
	const target =
		event.target instanceof HTMLElement
			? event.target.closest("[data-source-analysis-review], [data-source-analysis-copy]")
			: null;
	if (!(target instanceof HTMLElement)) return;
	const id = Number(
		target.getAttribute("data-source-analysis-id") ||
			target.closest("[data-source-analysis-report]")?.getAttribute("data-source-analysis-report") ||
			0
	);
	const report = reportCache.get(id);
	if (target.hasAttribute("data-source-analysis-copy")) {
		if (!report || !navigator.clipboard) {
			setSourceAnalysisStatus(t("sourceAnalysis.copyUnavailable", "Patch copy is unavailable."), "err");
			return;
		}
		await navigator.clipboard.writeText(JSON.stringify(fullSuggestionPatch(reportBody(report)), null, 2));
		setSourceAnalysisStatus(t("sourceAnalysis.copied", "Suggested patch copied."), "ok");
		return;
	}
	const reviewStatus = target.getAttribute("data-source-analysis-review") || "";
	if (!id || !reviewStatus) return;
	setSourceAnalysisStatus(t("sourceAnalysis.reviewing", "Saving review..."));
	try {
		await serverWrite("POST", `/v1/source-analysis/${encodeURIComponent(String(id))}/review/`, { reviewStatus });
		setSourceAnalysisStatus(t("sourceAnalysis.reviewSaved", "Review saved."), "ok");
		await loadReports();
	} catch (error) {
		setSourceAnalysisStatus(
			t("sourceAnalysis.reviewFailed", "Review failed: $1", backendErrorExplanation(error)),
			"err"
		);
	}
}

export function sourceAnalysisWorkspace() {
	return {
		html: accountSection({
			id: "source-analysis-title",
			title: t("sourceAnalysis.title", "Source code analysis"),
			intro: t(
				"sourceAnalysis.intro",
				"Derive projects, APIs, access rights, dependencies, OAuth scopes, repository context, assessments, and toolinfo suggestions from selected source files."
			),
			className: "source-analysis",
			body: `
				<form class="source-analysis__form" data-source-analysis-form novalidate>
					<div class="source-analysis__fields">
						${fInput(t("sourceAnalysis.toolName", "Tool name"), "source-analysis-tool", "", {
							hint: t("sourceAnalysis.toolNameHint", "Optional Toolhub id to attach to the report."),
							max: 255
						})}
						${fInput(t("sourceAnalysis.sourceLabel", "Source label"), "source-analysis-label", "", {
							hint: t(
								"sourceAnalysis.sourceLabelHint",
								"Optional repository, branch, release, or upload label."
							),
							max: 255
						})}
					</div>
					<label class="le__label" for="source-analysis-files">${t("sourceAnalysis.sourceFiles", "Source files")}
						<span class="le__hint" id="source-analysis-files-hint">${t("sourceAnalysis.sourceFilesHint", "Select files from a local checkout, or paste a JSON file list below.")}</span>
						<input class="le__input source-analysis__file-input" id="source-analysis-files" type="file" multiple aria-describedby="source-analysis-files-hint" />
					</label>
					${fArea(
						t("sourceAnalysis.sourceJson", "Source files JSON"),
						"source-analysis-json",
						"",
						t("sourceAnalysis.sourceJsonHint", "Automation format: an array of path/content objects."),
						{
							rows: 7,
							max: false,
							ph: sourceAnalysisSampleJson()
						}
					)}
					${fArea(
						t("sourceAnalysis.repositoryContextJson", "Repository context JSON"),
						"source-analysis-context-json",
						"",
						t(
							"sourceAnalysis.repositoryContextHint",
							"Optional deterministic repository metadata from the CLI or another trusted automation source."
						),
						{
							rows: 7,
							max: false,
							ph: sourceAnalysisContextSampleJson()
						}
					)}
					<div class="source-analysis__actions">
						${button(t("sourceAnalysis.analyze", "Analyze source"), {
							variant: "primary",
							icon: "analyze",
							type: "submit",
							attrs: "data-source-analysis-submit"
						})}
					</div>
				</form>
				<p class="at__result" data-source-analysis-status aria-live="polite"></p>
				<div data-source-analysis-current></div>
				<div class="source-analysis__saved" data-source-analysis-list aria-live="polite">
					<p class="empty">${t("sourceAnalysis.loadingReports", "Loading saved analyses...")}</p>
				</div>`
		}),
		mount() {
			$("[data-source-analysis-form]")?.addEventListener("submit", submitAnalysis);
			$("[data-source-analysis-current]")?.addEventListener("click", handleSourceAnalysisAction);
			$("[data-source-analysis-list]")?.addEventListener("click", handleSourceAnalysisAction);
			loadReports();
		}
	};
}
