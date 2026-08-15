// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { t, tWithElements } from "../lib/core/i18n.js";

const ENDPOINT = "https://toolhub-evolved.toolforge.org/mcp";
const CLAUDE_COMMAND = `claude mcp add --transport http toolhub-discovery ${ENDPOINT}`;
const VSCODE_CONFIG = JSON.stringify({ servers: { "toolhub-discovery": { type: "http", url: ENDPOINT } } }, null, 2);
const CURSOR_CONFIG = JSON.stringify({ mcpServers: { "toolhub-discovery": { type: "http", url: ENDPOINT } } }, null, 2);
const CURL_EXAMPLE = `curl -sS -X POST ${ENDPOINT} \\
  -H 'Content-Type: application/json' \\
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'`;

/** @param {string} value @returns {string} */
const code = (value) => `<code>${esc(value)}</code>`;

/** @param {string} value @param {string} label @returns {string} */
const blockCode = (value, label) => `<pre tabindex="0" aria-label="${esc(label)}"><code>${esc(value)}</code></pre>`;

/** @param {string} href @param {string} label @returns {string} */
const external = (href, label) => `<a href="${esc(href)}" target="_blank" rel="noopener nofollow">${esc(label)}</a>`;

/** @param {string[]} headers @param {string[][]} rows @param {string} caption @returns {string} */
function table(headers, rows, caption) {
	return `<div class="prose__table-wrap"><table>
		<caption>${esc(caption)}</caption>
		<thead><tr>${headers.map((header) => `<th scope="col">${esc(header)}</th>`).join("")}</tr></thead>
		<tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody>
	</table></div>`;
}

function clientSetupTable() {
	return table(
		[t("mcpServer.client", "Client"), t("mcpServer.setup", "Setup")],
		[
			[
				"Claude Code",
				external(
					"https://docs.anthropic.com/en/docs/claude-code/mcp",
					t("mcpServer.officialInstructions", "Official instructions")
				)
			],
			[
				"Visual Studio Code",
				external(
					"https://code.visualstudio.com/docs/agent-customization/mcp-servers",
					t("mcpServer.officialInstructions", "Official instructions")
				)
			],
			[
				"Cursor",
				external(
					"https://docs.cursor.com/context/model-context-protocol",
					t("mcpServer.officialInstructions", "Official instructions")
				)
			]
		],
		t("mcpServer.clientTableCaption", "Verified client configuration references")
	);
}

function toolTable() {
	return table(
		[t("mcpServer.tool", "Tool"), t("mcpServer.question", "What it answers")],
		[
			[
				code("search_tools(query, limit=10)"),
				esc(
					t("mcpServer.searchTools", "Text search over the latest complete local Toolhub catalog generation.")
				)
			],
			[
				code("facet_tools(…)"),
				esc(t("mcpServer.facetTools", "Tools matching declared metadata or detected source-code evidence."))
			],
			[
				code("list_facet_values(type)"),
				esc(t("mcpServer.listValues", "Adoption-ranked values for one public facet name."))
			],
			[
				code("get_tool(name)"),
				esc(t("mcpServer.getTool", "One full canonical record using its exact Toolhub name."))
			]
		],
		t("mcpServer.toolTableCaption", "Read-only discovery tools")
	);
}

function facetTable() {
	return table(
		[t("mcpServer.facet", "Facet"), t("mcpServer.source", "Source and meaning")],
		[
			[
				code("dependency"),
				esc(t("mcpServer.detectedDependency", "Detected package use; scanned repositories only."))
			],
			[code("api"), esc(t("mcpServer.detectedApi", "Detected Wikimedia API use; scanned repositories only."))],
			[
				code("detected_technology"),
				esc(t("mcpServer.detectedTechnology", "Detected language or technology; scanned repositories only."))
			],
			[code("technology"), esc(t("mcpServer.legacyTechnology", "Compatibility alias for detected_technology."))],
			[
				code("declared_technology"),
				esc(t("mcpServer.declaredTechnology", "Technology declared in Toolhub metadata."))
			],
			[
				code("tool_type, keyword, wiki, license, ui_language"),
				esc(
					t(
						"mcpServer.declaredMetadata",
						"Declared Toolhub metadata; availability depends on record completeness."
					)
				)
			],
			[
				code("task, audience"),
				esc(
					t(
						"mcpServer.purposeMetadata",
						"Sparse purpose annotations describing what a tool is for and whom it serves."
					)
				)
			]
		],
		t("mcpServer.facetTableCaption", "Canonical discovery facet names")
	);
}

/** @returns {{ title: string, html: string }} */
export function viewMcpServer() {
	const title = t("mcpServer.title", "MCP server");
	return {
		title: t("static.pageTitle", "$1 — Toolhub", title),
		html: `<div class="container page"><article class="prose prose--page prose--wide">
			<h1>${esc(title)}</h1>
			<p>${t("mcpServer.intro", "Toolhub Evolved publishes its catalog-discovery workflow as a read-only, anonymous Model Context Protocol server.")}</p>
			<p><strong>${t("mcpServer.payoff", "Use it before building: find existing Wikimedia tools, code worth extending, and technologies already used across the ecosystem.")}</strong></p>

			<h2>${t("mcpServer.connect", "Connect a client")}</h2>
			<p>${tWithElements("mcpServer.endpoint", "The remote HTTP endpoint is $1. It needs no API key, OAuth grant, cookie, or session.", { html: code(ENDPOINT) })}</p>
			${clientSetupTable()}
			<h3>Claude Code</h3>
			${blockCode(CLAUDE_COMMAND, t("mcpServer.claudeCommand", "Claude Code command"))}
			<h3>Visual Studio Code</h3>
			${blockCode(VSCODE_CONFIG, t("mcpServer.vscodeConfig", "Visual Studio Code mcp.json configuration"))}
			<h3>Cursor</h3>
			${blockCode(CURSOR_CONFIG, t("mcpServer.cursorConfig", "Cursor mcp.json configuration"))}
			<h3>${t("mcpServer.rawHttp", "Raw HTTP")}</h3>
			${blockCode(CURL_EXAMPLE, t("mcpServer.curlExample", "HTTP request listing MCP tools"))}

			<h2>${t("mcpServer.priorArt", "Start with the prior-art review")}</h2>
			<p>${tWithElements("mcpServer.prompt", "Ask your client to run the $1 prompt with a short project description. It searches several phrasings, checks relevant facets, and reports whether to reuse, contribute, differentiate, or build.", { html: code("prior-art-review") })}</p>
			${toolTable()}

			<h2>${t("mcpServer.facets", "Facet names and evidence")}</h2>
			${facetTable()}
			<p>${t("mcpServer.filterLogic", "Values within one facet are OR alternatives; different facets combine with AND. Unknown values legitimately match zero tools instead of widening the request.")}</p>

			<h2>${t("mcpServer.honestAnswers", "Read answers honestly")}</h2>
			<ul>
				<li>${t("mcpServer.honestSearch", "One phrasing is not a search. Catalog vocabulary varies, so use several short queries with different terms.")}</li>
				<li>${t("mcpServer.honestAbsence", "Absence is weak evidence: some tools are unregistered, sparsely described, or exist only as on-wiki scripts.")}</li>
				<li>${t("mcpServer.honestCoverage", "Detected facets cover scanned repositories only. Restate the returned scannedTools and totalTools counts when drawing conclusions.")}</li>
				<li>${t("mcpServer.honestAdoption", "Adoption is ecosystem evidence, not a quality guarantee or an endorsement.")}</li>
			</ul>

			<h2>${t("mcpServer.freshness", "Freshness, limits, and privacy")}</h2>
			<p>${t("mcpServer.localReplica", "Every tool call reads the local database. Scheduled jobs synchronize official Toolhub changes into an atomic catalog generation; no page or MCP request contacts Toolhub while it is being served.")}</p>
			<ul>
				<li>${t("mcpServer.syncCadence", "Incremental catalog synchronization normally runs every 15 minutes, with periodic integrity reconciliation as a safety net.")}</li>
				<li>${t("mcpServer.rateLimit", "The endpoint allows 60 requests per rolling minute per client address.")}</li>
				<li>${t("mcpServer.privacy", "It performs no writes and creates no account session. Requests are not associated with a Toolhub identity.")}</li>
			</ul>

			<h2>${t("mcpServer.troubleshooting", "Troubleshooting")}</h2>
			<ul>
				<li>${tWithElements("mcpServer.methodError", "$1 means the transport endpoint was opened with GET. Use a compatible MCP client or POST JSON-RPC requests.", { html: code("405 Method Not Allowed") })}</li>
				<li>${tWithElements("mcpServer.originError", "$1 means a browser origin failed the server's DNS-rebinding protection.", { html: code("403 origin not allowed") })}</li>
				<li>${tWithElements("mcpServer.rateError", "$1 means the address exceeded the rolling-minute allowance; wait before retrying.", { html: code("429 rate limited, retry later") })}</li>
			</ul>
			<p>${tWithElements("mcpServer.contribute", "Found missing or misleading catalog data? The $1 explains how official Toolhub and Evolved divide responsibility.", { html: '<a href="/rules-of-engagement">Rules of Engagement</a>' })}</p>
		</article></div>`
	};
}
