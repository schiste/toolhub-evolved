// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, esc } from "../core/dom.js";
import { apiGetResponse } from "../core/api.js";
import { t } from "../core/i18n.js";
import { button } from "../atoms/button.js";

const TOOLHUB_API_BASE = "https://toolhub.wikimedia.org/api";
const SAFE_RESPONSE_HEADERS = [
	"cache-control",
	"content-type",
	"etag",
	"last-modified",
	"server-timing",
	"x-toolhub-evolved-cache",
	"x-toolhub-evolved-upstream"
];

/**
 * @typedef {object} ApiExplorerField
 * @property {string} name
 * @property {string} label
 * @property {"path" | "query"} kind
 * @property {string} [queryName]
 * @property {string} [defaultValue]
 * @property {string} [placeholder]
 * @property {string} [hint]
 * @property {boolean} [required]
 */
/**
 * @typedef {object} ApiExplorerEndpoint
 * @property {string} id
 * @property {string} title
 * @property {string} description
 * @property {string} pathTemplate
 * @property {"toolhub" | "same-origin"} [origin]
 * @property {ApiExplorerField[]} fields
 */
/**
 * @typedef {object} ApiExplorerRequest
 * @property {string} method
 * @property {string} path
 * @property {string} proxyUrl
 * @property {string} canonicalUrl
 * @property {string} curlProxy
 * @property {string} curlCanonical
 * @property {string} fetchExample
 */
/**
 * @typedef {object} ApiExplorerResult
 * @property {boolean} ok
 * @property {number | null} status
 * @property {string} statusText
 * @property {number} durationMs
 * @property {ApiExplorerRequest} request
 * @property {Record<string, string>} headers
 * @property {string} bodyText
 * @property {string} [error]
 */

export const API_EXPLORER_ENDPOINTS = /** @type {ApiExplorerEndpoint[]} */ ([
	{
		id: "search-tools",
		title: t("apiExplorer.searchTools", "Search tools"),
		description: t("apiExplorer.searchToolsDesc", "Search the live Toolhub catalog with a small result page."),
		pathTemplate: "/api/search/tools/",
		fields: [
			{
				name: "q",
				label: t("apiExplorer.query", "Search query"),
				kind: "query",
				defaultValue: "wikidata",
				placeholder: "wikidata"
			},
			{
				name: "page_size",
				label: t("apiExplorer.pageSize", "Page size"),
				kind: "query",
				defaultValue: "5",
				placeholder: "5"
			}
		]
	},
	{
		id: "tool-detail",
		title: t("apiExplorer.toolDetail", "Tool detail"),
		description: t("apiExplorer.toolDetailDesc", "Read one canonical Toolhub tool record by stable name."),
		pathTemplate: "/api/tools/{name}/",
		fields: [
			{
				name: "name",
				label: t("apiExplorer.toolName", "Tool name"),
				kind: "path",
				defaultValue: "quickstatements",
				placeholder: "quickstatements",
				required: true
			}
		]
	},
	{
		id: "tool-people",
		title: t("apiExplorer.toolPeople", "People and relationships"),
		description: t(
			"apiExplorer.toolPeopleDesc",
			"Read deduplicated people and typed author, maintainer, and record-owner relationships for one tool."
		),
		pathTemplate: "/v1/people/tools/{name}/",
		origin: "same-origin",
		fields: [
			{
				name: "name",
				label: t("apiExplorer.toolName", "Tool name"),
				kind: "path",
				defaultValue: "quickstatements",
				placeholder: "quickstatements",
				required: true
			}
		]
	},
	{
		id: "tool-revisions",
		title: t("apiExplorer.toolRevisions", "Tool revisions"),
		description: t("apiExplorer.toolRevisionsDesc", "List recent revisions for one tool."),
		pathTemplate: "/api/tools/{name}/revisions/",
		fields: [
			{
				name: "name",
				label: t("apiExplorer.toolName", "Tool name"),
				kind: "path",
				defaultValue: "quickstatements",
				placeholder: "quickstatements",
				required: true
			},
			{
				name: "page_size",
				label: t("apiExplorer.pageSize", "Page size"),
				kind: "query",
				defaultValue: "5",
				placeholder: "5"
			}
		]
	},
	{
		id: "lists",
		title: t("apiExplorer.lists", "Lists"),
		description: t("apiExplorer.listsDesc", "Browse published Toolhub lists."),
		pathTemplate: "/api/lists/",
		fields: [
			{
				name: "page_size",
				label: t("apiExplorer.pageSize", "Page size"),
				kind: "query",
				defaultValue: "6",
				placeholder: "6"
			}
		]
	},
	{
		id: "recent",
		title: t("apiExplorer.recent", "Recent changes"),
		description: t("apiExplorer.recentDesc", "Read recent Toolhub catalog activity."),
		pathTemplate: "/api/recent/",
		fields: [
			{
				name: "page_size",
				label: t("apiExplorer.pageSize", "Page size"),
				kind: "query",
				defaultValue: "10",
				placeholder: "10"
			}
		]
	},
	{
		id: "crawler-urls",
		title: t("apiExplorer.crawlerUrls", "Crawler URLs"),
		description: t("apiExplorer.crawlerUrlsDesc", "Inspect registered toolinfo.json URLs known to Toolhub."),
		pathTemplate: "/api/crawler/urls/",
		fields: [
			{
				name: "page_size",
				label: t("apiExplorer.pageSize", "Page size"),
				kind: "query",
				defaultValue: "10",
				placeholder: "10"
			}
		]
	},
	{
		id: "schema",
		title: t("apiExplorer.schema", "OpenAPI schema"),
		description: t("apiExplorer.schemaDesc", "Fetch the machine-readable Toolhub API schema."),
		pathTemplate: "/api/schema/",
		fields: []
	}
]);

/** @param {string} id */
export function endpointById(id) {
	return API_EXPLORER_ENDPOINTS.find((endpoint) => endpoint.id === id) || null;
}

/**
 * @param {ApiExplorerField} field
 * @param {Record<string, string>} values
 */
function fieldValue(field, values) {
	return String(values[field.name] ?? field.defaultValue ?? "").trim();
}

/** @param {string} path @param {ApiExplorerEndpoint} endpoint */
function canonicalUrl(path, endpoint) {
	if (endpoint.origin === "same-origin") return path;
	return `${TOOLHUB_API_BASE}${path.replace(/^\/api/, "")}`;
}

/** @param {string} value */
function shellQuote(value) {
	return `'${value.replaceAll("'", "'\\''")}'`;
}

/**
 * @param {ApiExplorerEndpoint} endpoint
 * @param {Record<string, string>} [values]
 * @returns {ApiExplorerRequest}
 */
export function buildExplorerRequest(endpoint, values = {}) {
	let path = endpoint.pathTemplate;
	const params = new URLSearchParams();
	for (const field of endpoint.fields) {
		const value = fieldValue(field, values);
		if (field.kind === "path") {
			if (!value && field.required) {
				throw new Error(t("apiExplorer.requiredField", "$1 is required.", field.label));
			}
			path = path.replaceAll(`{${field.name}}`, encodeURIComponent(value));
		} else if (value) {
			params.set(field.queryName || field.name, value);
		}
	}
	const qs = params.toString();
	const fullPath = `${path}${qs ? `?${qs}` : ""}`;
	const canonical = canonicalUrl(fullPath, endpoint);
	return {
		method: "GET",
		path: fullPath,
		proxyUrl: fullPath,
		canonicalUrl: canonical,
		curlProxy: `curl -H 'Accept: application/json' ${shellQuote(fullPath)}`,
		curlCanonical: `curl -H 'Accept: application/json' ${shellQuote(canonical)}`,
		fetchExample: `const response = await fetch(${JSON.stringify(fullPath)}, { headers: { Accept: "application/json" } });\nconst data = await response.json();`
	};
}

/**
 * @param {Headers} headers
 * @returns {Record<string, string>}
 */
function safeHeaders(headers) {
	const out = /** @type {Record<string, string>} */ ({});
	for (const name of SAFE_RESPONSE_HEADERS) {
		const value = headers.get(name);
		if (value) out[name] = value;
	}
	return out;
}

/** @param {string} text */
export function formatJsonText(text) {
	try {
		return JSON.stringify(JSON.parse(text), null, 2);
	} catch {
		return text;
	}
}

/**
 * @param {ApiExplorerEndpoint} endpoint
 * @param {Record<string, string>} values
 * @param {(url: string) => Promise<Response>} [requester]
 * @param {() => number} [now]
 * @returns {Promise<ApiExplorerResult>}
 */
export async function runExplorerRequest(endpoint, values, requester = apiGetResponse, now = () => performance.now()) {
	const request = buildExplorerRequest(endpoint, values);
	const start = now();
	try {
		const response = await requester(request.proxyUrl);
		const bodyText = formatJsonText(await response.text());
		return {
			ok: response.ok,
			status: response.status,
			statusText: response.statusText || (response.ok ? "OK" : "Error"),
			durationMs: Math.max(0, Math.round(now() - start)),
			request,
			headers: safeHeaders(response.headers),
			bodyText
		};
	} catch (error) {
		return {
			ok: false,
			status: null,
			statusText: t("apiExplorer.networkError", "Network error"),
			durationMs: Math.max(0, Math.round(now() - start)),
			request,
			headers: {},
			bodyText: "",
			error: String((error && /** @type {{ message?: unknown }} */ (error).message) || error)
		};
	}
}

/** @param {ApiExplorerEndpoint} endpoint @param {Record<string, string>} [values] */
function examples(endpoint, values = {}) {
	const request = buildExplorerRequest(endpoint, values);
	return [
		{
			key: "curl-proxy",
			heading: t("apiExplorer.proxyCurl", "Proxied cURL"),
			label: t("apiExplorer.copyProxyCurl", "Copy proxied cURL"),
			code: request.curlProxy
		},
		{
			key: "curl-canonical",
			heading: t("apiExplorer.canonicalCurl", "Canonical cURL"),
			label: t("apiExplorer.copyCanonicalCurl", "Copy canonical cURL"),
			code: request.curlCanonical
		},
		{
			key: "fetch",
			heading: t("apiExplorer.fetchExample", "Fetch"),
			label: t("apiExplorer.copyFetch", "Copy fetch"),
			code: request.fetchExample
		}
	];
}

/** @param {ApiExplorerEndpoint} endpoint */
function endpointForm(endpoint) {
	const fields = endpoint.fields
		.map((field) => {
			const id = `api-field-${endpoint.id}-${field.name}`;
			const hint = field.hint ? `<span class="le__hint" id="${id}-hint">${esc(field.hint)}</span>` : "";
			const describedBy = field.hint ? ` aria-describedby="${id}-hint"` : "";
			return `<label class="le__label api-endpoint__field" for="${id}">
				${esc(field.label)}
				${hint}
				<input class="le__input" id="${id}" name="${esc(field.name)}" value="${esc(field.defaultValue || "")}" placeholder="${esc(field.placeholder || "")}"${field.required ? " required" : ""}${describedBy} />
			</label>`;
		})
		.join("");
	const request = buildExplorerRequest(endpoint);
	return `<form class="api-endpoint" data-api-endpoint="${esc(endpoint.id)}" aria-labelledby="api-endpoint-${esc(endpoint.id)}-title">
		<div class="api-endpoint__head">
			<h3 class="api-endpoint__title" id="api-endpoint-${esc(endpoint.id)}-title">
				<span class="api-method">GET</span>
				<span>${esc(endpoint.title)}</span>
			</h3>
			<code class="api-endpoint__path" data-api-path>${esc(request.path)}</code>
		</div>
		<p class="api-endpoint__desc">${esc(endpoint.description)}</p>
		${fields ? `<div class="api-endpoint__fields">${fields}</div>` : ""}
		<div class="api-endpoint__actions">
			${button(t("apiExplorer.runRequest", "Run request"), { variant: "primary", icon: "search", type: "submit" })}
			<a href="${esc(request.proxyUrl)}" target="_blank" rel="noopener nofollow">${t("apiExplorer.openJson", "Open JSON")}</a>
		</div>
		<div class="api-endpoint__examples" data-api-examples>${renderExamples(endpoint)}</div>
	</form>`;
}

/** @param {ApiExplorerEndpoint} endpoint @param {Record<string, string>} [values] */
function renderExamples(endpoint, values = {}) {
	return examples(endpoint, values)
		.map(
			(example) => `<div class="api-example">
				<div class="api-example__head">
					<strong>${esc(example.heading)}</strong>
					${button(example.label, {
						size: "sm",
						cls: "api-example__copy",
						attrs: `data-api-copy="${esc(example.key)}"`
					})}
				</div>
				<pre class="api-example__code" tabindex="0"><code>${esc(example.code)}</code></pre>
			</div>`
		)
		.join("");
}

export function renderApiExplorer() {
	return `<section class="api-explorer" data-api-explorer aria-labelledby="api-explorer-title">
		<div class="section-head api-explorer__section-head">
			<div>
				<h2 id="api-explorer-title">${t("apiExplorer.title", "Try read-only endpoints")}</h2>
				<p class="page__intro">${t("apiExplorer.intro", "Run common anonymous Toolhub reads through Evolved's same-origin proxy, then copy examples for production clients.")}</p>
			</div>
			<a href="https://toolhub.wikimedia.org/api-docs" target="_blank" rel="noopener nofollow">${t("apiExplorer.officialDocs", "Official docs")}</a>
		</div>
		<div class="api-explorer__layout">
			<div class="api-explorer__endpoints" aria-label="${t("apiExplorer.endpointForms", "Endpoint forms")}">
				${API_EXPLORER_ENDPOINTS.map((endpoint) => endpointForm(endpoint)).join("")}
			</div>
			<aside class="api-result" aria-labelledby="api-result-title">
				<h3 class="api-result__title" id="api-result-title">${t("apiExplorer.response", "Response")}</h3>
				<p class="api-result__status" data-api-status role="status" aria-live="polite" aria-atomic="true">${t("apiExplorer.chooseEndpoint", "Choose an endpoint and run a request.")}</p>
				<dl class="api-result__meta" data-api-meta></dl>
				<pre class="api-result__body" tabindex="0" aria-label="${t("apiExplorer.responseBody", "API response body")}" data-api-output><code>{}</code></pre>
			</aside>
		</div>
	</section>`;
}

/** @param {HTMLFormElement} form */
function formValues(form) {
	return Object.fromEntries(new FormData(form).entries());
}

/** @param {HTMLFormElement} form */
function formEndpoint(form) {
	const id = form.getAttribute("data-api-endpoint") || "";
	return endpointById(id);
}

/** @param {HTMLFormElement} form */
function updateFormExamples(form) {
	const endpoint = formEndpoint(form);
	if (!endpoint) return;
	const request = buildExplorerRequest(endpoint, /** @type {Record<string, string>} */ (formValues(form)));
	const path = $("[data-api-path]", form);
	if (path) path.textContent = request.path;
	const open = form.querySelector(".api-endpoint__actions a");
	if (open instanceof HTMLAnchorElement) open.href = request.proxyUrl;
	const target = $("[data-api-examples]", form);
	if (target) target.innerHTML = renderExamples(endpoint, /** @type {Record<string, string>} */ (formValues(form)));
}

/** @param {ApiExplorerResult} result */
function resultStatus(result) {
	if (result.error) return t("apiExplorer.requestFailed", "Request failed: $1", result.error);
	const status = result.status === null ? "" : `${result.status} ${result.statusText}`.trim();
	return t(
		"apiExplorer.requestComplete",
		"GET $1 returned $2 in $3 ms.",
		result.request.path,
		status,
		result.durationMs
	);
}

/** @param {ApiExplorerResult} result */
function renderResult(result) {
	const status = $("[data-api-status]");
	const meta = $("[data-api-meta]");
	const output = $("[data-api-output]");
	if (status) {
		status.classList.toggle("api-result__status--error", !result.ok);
		status.textContent = resultStatus(result);
	}
	if (meta) {
		const headers = Object.entries(result.headers)
			.map(([name, value]) => `<div><dt>${esc(name)}</dt><dd>${esc(value)}</dd></div>`)
			.join("");
		meta.innerHTML = `<div><dt>${t("apiExplorer.method", "Method")}</dt><dd>GET</dd></div>
			<div><dt>${t("apiExplorer.proxyUrl", "Proxy URL")}</dt><dd><code>${esc(result.request.proxyUrl)}</code></dd></div>
			<div><dt>${t("apiExplorer.canonicalUrl", "Canonical URL")}</dt><dd><code>${esc(result.request.canonicalUrl)}</code></dd></div>
			${headers}`;
	}
	if (output) output.innerHTML = `<code>${esc(result.error || result.bodyText || "{}")}</code>`;
}

/** @param {HTMLFormElement} form */
async function runForm(form) {
	const endpoint = formEndpoint(form);
	if (!endpoint) return;
	const status = $("[data-api-status]");
	if (status) {
		status.classList.remove("api-result__status--error");
		status.textContent = t("apiExplorer.loading", "Loading $1...", endpoint.title);
	}
	try {
		updateFormExamples(form);
	} catch (error) {
		renderResult({
			ok: false,
			status: null,
			statusText: t("apiExplorer.validationError", "Validation error"),
			durationMs: 0,
			request: buildExplorerRequest(endpoint),
			headers: {},
			bodyText: "",
			error: String((error && /** @type {{ message?: unknown }} */ (error).message) || error)
		});
		return;
	}
	const result = await runExplorerRequest(endpoint, /** @type {Record<string, string>} */ (formValues(form)));
	renderResult(result);
}

/** @param {HTMLButtonElement} buttonEl */
async function copyExample(buttonEl) {
	const form = buttonEl.closest("form");
	if (!(form instanceof HTMLFormElement)) return;
	const endpoint = formEndpoint(form);
	if (!endpoint) return;
	const key = buttonEl.getAttribute("data-api-copy");
	const example = examples(endpoint, /** @type {Record<string, string>} */ (formValues(form))).find(
		(item) => item.key === key
	);
	if (!example) return;
	const status = $("[data-api-status]");
	try {
		await navigator.clipboard.writeText(example.code);
		if (status) status.textContent = t("apiExplorer.copied", "Copied $1.", example.label);
	} catch {
		if (status) {
			status.classList.add("api-result__status--error");
			status.textContent = t("apiExplorer.copyFailed", "Copy failed. Select the example text manually.");
		}
	}
}

export function mountApiExplorer() {
	const root = $("[data-api-explorer]");
	if (!root) return;
	$$("[data-api-endpoint]", root).forEach((form) => {
		if (!(form instanceof HTMLFormElement)) return;
		form.addEventListener("input", () => updateFormExamples(form));
		form.addEventListener("submit", (event) => {
			event.preventDefault();
			runForm(form).catch(() => undefined);
		});
	});
	root.addEventListener("click", (event) => {
		const copy = /** @type {HTMLElement | null} */ (
			event.target instanceof Element ? event.target.closest("[data-api-copy]") : null
		);
		if (!(copy instanceof HTMLButtonElement)) return;
		event.preventDefault();
		copyExample(copy).catch(() => undefined);
	});
}
