// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { viewMcpServer } from "../../public_html/views/mcp-server.js";

test("MCP guide publishes client-specific setup and the local-replica contract", () => {
	const view = viewMcpServer();
	assert.equal(view.title, "MCP server — Toolhub");
	assert.ok(view.html.includes("https://toolhub-evolved.toolforge.org/mcp"));
	assert.ok(view.html.includes("claude mcp add --transport http"));
	assert.ok(view.html.includes("&quot;servers&quot;"));
	assert.ok(view.html.includes("&quot;mcpServers&quot;"));
	assert.ok(view.html.includes("Every tool call reads the local database"));
	assert.ok(view.html.includes("detected_technology"));
	assert.ok(view.html.includes("declared_technology"));
	assert.ok(view.html.includes("Compatibility alias for detected_technology"));
	assert.ok(!view.html.includes("upstream Elasticsearch"));
});
