#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-or-later
/**
 * Small stdio MCP client used by the marketing changelog generator.
 *
 * It deliberately uses only the standard MCP JSON-RPC surface exposed by
 * Chau7. The hook passes the bounded release-note prompt on stdin; this
 * adapter returns only the completed agent output on stdout.
 */

import { spawn } from "node:child_process";
import { homedir } from "node:os";
import process from "node:process";

const BRIDGE = process.env.TOOLHUB_CHAU7_MCP_BRIDGE || `${homedir()}/.chau7/bin/chau7-mcp-bridge`;
const AGENT_COMMAND = process.env.TOOLHUB_CHANGELOG_AGENT_COMMAND || "codex";
const TIMEOUT_MS = 180_000;
const POLL_MS = 2_000;
const DEBUG = process.env.TOOLHUB_CHANGELOG_PROVIDER_DEBUG === "1";

function debug(message) {
	if (DEBUG) process.stderr.write(`Chau7 marketing provider: ${message}\n`);
}

function readPrompt() {
	return new Promise((resolve, reject) => {
		let value = "";
		process.stdin.setEncoding("utf8");
		process.stdin.on("data", (chunk) => (value += chunk));
		process.stdin.on("end", () => resolve(value.trim()));
		process.stdin.on("error", reject);
	});
}

class McpClient {
	constructor() {
		this.nextId = 1;
		this.pending = new Map();
		this.buffer = "";
		this.process = spawn(BRIDGE, [], { stdio: ["pipe", "pipe", "pipe"] });
		this.process.stderr.on("data", (chunk) => process.stderr.write(chunk));
		this.process.stdout.setEncoding("utf8");
		this.process.stdout.on("data", (chunk) => this.receive(chunk));
		this.process.on("error", (error) => this.fail(error));
		this.process.on("exit", (code) => {
			debug(`MCP bridge exited with status ${code}`);
			if (code !== 0 && this.pending.size > 0) this.fail(new Error(`MCP bridge exited with status ${code}`));
		});
	}

	receive(chunk) {
		this.buffer += chunk;
		const lines = this.buffer.split("\n");
		this.buffer = lines.pop() || "";
		for (const line of lines) {
			if (!line.trim()) continue;
			try {
				const message = JSON.parse(line);
				if (message.id && this.pending.has(message.id)) {
					const { resolve, reject } = this.pending.get(message.id);
					this.pending.delete(message.id);
					if (message.error) {
						reject(new Error(message.error.message || "MCP request failed"));
					} else {
						debug(`response ${message.id}`);
						resolve(message.result);
					}
				}
			} catch {
				process.stderr.write(`Ignoring non-JSON MCP output: ${line.slice(0, 160)}\n`);
			}
		}
	}

	fail(error) {
		for (const { reject } of this.pending.values()) reject(error);
		this.pending.clear();
	}

	request(method, params = {}) {
		const id = this.nextId++;
		debug(`request ${id}: ${method}`);
		return new Promise((resolve, reject) => {
			this.pending.set(id, { resolve, reject });
			this.process.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
		});
	}

	notify(method, params = {}) {
		this.process.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`);
	}

	close() {
		this.process.kill();
	}
}

function resultText(result) {
	if (!result || !Array.isArray(result.content)) return "";
	return result.content
		.filter((item) => item?.type === "text")
		.map((item) => item.text || "")
		.join("\n");
}

function structuredOutput(result) {
	return typeof result?.structuredContent?.output === "string" ? result.structuredContent.output : "";
}

function findTabId(result) {
	const text = resultText(result);
	const match = text.match(/"tab_id"\s*:\s*"([^"]+)"/);
	return match?.[1] || result?.structuredContent?.tab_id || null;
}

function outputText(result) {
	const structured = structuredOutput(result);
	if (structured) return structured;
	const text = resultText(result);
	try {
		const parsed = JSON.parse(text);
		return parsed.output || text;
	} catch {
		return text;
	}
}

function hasBothSections(text) {
	return /<TECHNICAL>[\s\S]*<\/TECHNICAL>/i.test(text) && /<USER>[\s\S]*<\/USER>/i.test(text);
}

async function main() {
	const prompt = await readPrompt();
	if (!prompt) throw new Error("No release-note prompt was supplied on stdin");
	const client = new McpClient();
	let tabId = null;
	const deadline = Date.now() + TIMEOUT_MS;
	try {
		await client.request("initialize", {
			protocolVersion: "2025-06-18",
			capabilities: {},
			clientInfo: { name: "toolhub-evolved-marketing-provider", version: "1" }
		});
		client.notify("notifications/initialized");
		const launched = await client.request("tools/call", {
			name: "agent_launch",
			arguments: {
				agent_command: AGENT_COMMAND,
				count: 1,
				directory: process.cwd(),
				prompt,
				ready_timeout_ms: 30_000
			}
		});
		tabId = findTabId(launched);
		debug(`spawned tab ${tabId || "(none)"}`);
		if (!tabId) throw new Error("Chau7 did not return a spawned tab id");

		let latest = "";
		while (Date.now() < deadline) {
			const output = await client.request("tools/call", {
				name: "tab_output",
				arguments: { tab_id: tabId, source: "pty_log", lines: 800 }
			});
			latest = outputText(output);
			debug(`tab output length ${latest.length}, markers=${hasBothSections(latest)}`);
			if (hasBothSections(latest)) {
				process.stdout.write(`${latest}\n`);
				return;
			}
			await new Promise((resolve) => {
				setTimeout(resolve, POLL_MS);
			});
		}
		throw new Error("Chau7 agent did not produce both release-note sections before timeout");
	} finally {
		if (tabId) {
			try {
				await client.request("tools/call", {
					name: "tab_close",
					arguments: { tab_id: tabId, force: true }
				});
			} catch (error) {
				process.stderr.write(`Could not close Chau7 tab ${tabId}: ${error.message}\n`);
			}
		}
		client.close();
	}
}

main().catch((error) => {
	console.error(`Chau7 marketing provider: ${error.message}`);
	process.exitCode = 1;
});
