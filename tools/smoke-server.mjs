#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-or-later
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const publicDir = path.join(root, "public_html");

const tools = [
	{
		name: "toolforge-admin",
		title: "Toolforge admin",
		description: "Administrative interface for Toolforge maintainers.",
		url: "https://admin.toolforge.org/",
		author: [{ name: "Bryan Davis", url: "https://www.mediawiki.org/wiki/User:BD808" }],
		keywords: ["toolforge", "admin", "cloud"],
		audiences: ["developer", "admin"],
		tasks: ["manage", "deploy"],
		for_wikis: ["*"],
		available_ui_languages: ["en"],
		tool_type: "web app",
		license: "GPL-3.0-or-later",
		repository: "https://gitlab.wikimedia.org/repos/cloud/toolforge/admin",
		user_docs_url: [{ url: "https://wikitech.wikimedia.org/wiki/Portal:Toolforge/Admin" }],
		developer_docs_url: [{ url: "https://wikitech.wikimedia.org/wiki/Portal:Toolforge/Admin" }],
		modified_date: "2026-06-01T12:00:00Z",
		origin: "crawler"
	},
	{
		name: "wikidata-query-helper",
		title: "Wikidata query helper",
		description: "Build and share SPARQL examples for Wikidata research.",
		url: "https://query.wikidata.org/",
		author: [{ name: "Ada Lovelace", url: "https://www.wikidata.org/wiki/Q7259" }],
		keywords: ["wikidata", "query", "sparql"],
		audiences: ["researcher", "developer"],
		tasks: ["analyze", "query"],
		for_wikis: ["wikidatawiki"],
		available_ui_languages: ["en", "fr"],
		tool_type: "web app",
		license: "Apache-2.0",
		repository: "https://gerrit.wikimedia.org/r/admin/repos/wikidata/query/gui",
		modified_date: "2026-05-20T10:00:00Z",
		origin: "crawler"
	},
	{
		name: "citation-needed",
		title: "Citation Needed",
		description: "Find statements that need sources and help editors improve articles.",
		url: "https://citation-needed.toolforge.org/",
		author: [{ name: "Example Maintainer", url: "https://meta.wikimedia.org/wiki/User:Example" }],
		keywords: ["citation", "editing"],
		audiences: ["editor"],
		tasks: ["edit", "curate"],
		for_wikis: ["enwiki"],
		available_ui_languages: ["en"],
		tool_type: "web app",
		license: "MIT",
		modified_date: "2026-04-12T09:00:00Z",
		origin: "crawler"
	}
];

const list = {
	id: "featured-toolforge",
	title: "Toolforge essentials",
	description: "Starter tools for Toolforge maintainers.",
	featured: true,
	tools: [tools[0], tools[1]]
};

const facets = {
	_filter_tool_type: {
		tool_type: {
			meta: { param: "tool_type__term" },
			buckets: [{ key: "web app", doc_count: 3 }]
		}
	},
	_filter_keywords: {
		keywords: {
			meta: { param: "keywords__term" },
			buckets: [
				{ key: "toolforge", doc_count: 1 },
				{ key: "wikidata", doc_count: 1 },
				{ key: "citation", doc_count: 1 }
			]
		}
	},
	_filter_audiences: {
		audiences: {
			meta: { param: "audiences__term" },
			buckets: [
				{ key: "developer", doc_count: 2 },
				{ key: "editor", doc_count: 1 }
			]
		}
	},
	_filter_tasks: {
		tasks: {
			meta: { param: "tasks__term" },
			buckets: [
				{ key: "manage", doc_count: 1 },
				{ key: "query", doc_count: 1 }
			]
		}
	}
};

const mime = {
	".css": "text/css; charset=utf-8",
	".html": "text/html; charset=utf-8",
	".js": "text/javascript; charset=utf-8",
	".json": "application/json; charset=utf-8",
	".svg": "image/svg+xml"
};

function json(res, data, status = 200) {
	const body = JSON.stringify(data);
	res.writeHead(status, {
		"cache-control": "no-store",
		"content-length": Buffer.byteLength(body),
		"content-type": "application/json; charset=utf-8"
	});
	res.end(body);
}

function api(req, res, pathname) {
	if (pathname === "/api/") {
		return json(res, {
			search: "/api/search/",
			tools: "/api/tools/",
			lists: "/api/lists/",
			recent: "/api/recent/",
			users: "/api/users/",
			crawler: "/api/crawler/",
			auditlogs: "/api/auditlogs/",
			schema: "/api/schema/"
		});
	}
	if (pathname === "/api/ui/home/") return json(res, {});
	if (pathname === "/api/search/tools/") return json(res, { count: tools.length, facets, results: tools });
	if (pathname === "/api/lists/") return json(res, { count: 1, results: [list] });
	if (pathname === "/api/lists/featured-toolforge/") return json(res, list);
	if (pathname === "/api/recent/") {
		return json(res, {
			count: 1,
			results: [
				{
					action: "created",
					content_type: "tool",
					content_id: tools[0].name,
					timestamp: "2026-06-20T08:00:00Z"
				}
			]
		});
	}
	if (pathname === "/api/users/") return json(res, { count: 1, results: [{ username: "Ada Lovelace", count: 12 }] });
	if (pathname === "/api/crawler/runs/") {
		return json(res, { count: 1, results: [{ id: 1, status: "completed", urls: 4 }] });
	}
	if (pathname === "/api/auditlogs/") {
		return json(res, { count: 1, results: [{ id: 1, target: tools[0].name, action: "created" }] });
	}
	const toolMatch = pathname.match(/^\/api\/tools\/([^/]+)\/(?:revisions\/)?$/);
	if (toolMatch) {
		const name = decodeURIComponent(toolMatch[1]);
		if (pathname.endsWith("/revisions/")) return json(res, { count: 1, results: [{ id: 1, content_id: name }] });
		const tool = tools.find((item) => item.name === name);
		return tool ? json(res, tool) : json(res, { error: "not found" }, 404);
	}
	return json(res, { error: `unhandled mock endpoint: ${req.url}` }, 404);
}

async function staticFile(res, pathname) {
	const clean = path.normalize(decodeURIComponent(pathname)).replace(/^(\.\.[/\\])+/, "");
	const candidate = path.join(publicDir, clean === "/" ? "index.html" : clean);
	const safe = candidate.startsWith(publicDir) ? candidate : path.join(publicDir, "index.html");
	try {
		const body = await readFile(safe);
		const type = mime[path.extname(safe)] || "application/octet-stream";
		res.writeHead(200, { "cache-control": "no-store", "content-type": type });
		res.end(body);
	} catch {
		const body = await readFile(path.join(publicDir, "index.html"));
		res.writeHead(200, { "cache-control": "no-store", "content-type": "text/html; charset=utf-8" });
		res.end(body);
	}
}

export function createSmokeServer() {
	return createServer((req, res) => {
		const url = new URL(req.url, `http://${req.headers.host}`);
		if (url.pathname.startsWith("/api/")) return api(req, res, url.pathname);
		return staticFile(res, url.pathname);
	});
}

export function startSmokeServer({ host = "127.0.0.1", port = Number(process.env.PORT || 4173) } = {}) {
	return new Promise((resolve, reject) => {
		const server = createSmokeServer();
		server.once("error", reject);
		server.listen(port, host, () => {
			server.off("error", reject);
			const address = server.address();
			const actualPort = address && typeof address === "object" ? address.port : port;
			resolve({ server, url: `http://${host}:${actualPort}` });
		});
	});
}

async function main() {
	const { url } = await startSmokeServer();
	console.log(`smoke server listening on ${url}`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
	main().catch((error) => {
		console.error(error);
		process.exit(1);
	});
}
