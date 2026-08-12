// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { afterEach, beforeEach, test, vi } from "vitest";
import {
	API_EXPLORER_ENDPOINTS,
	buildExplorerRequest,
	endpointById,
	formatJsonText,
	mountApiExplorer,
	renderApiExplorer,
	runExplorerRequest
} from "../../public_html/lib/organisms/api-explorer.js";

beforeEach(() => {
	document.body.innerHTML = "";
	vi.restoreAllMocks();
});

afterEach(() => {
	vi.unstubAllGlobals();
});

function response(body, init = {}) {
	return new Response(body, {
		status: init.status || 200,
		statusText: init.statusText || "OK",
		headers: init.headers || { "content-type": "application/json", "x-toolhub-evolved-cache": "hit" }
	});
}

function mustEndpoint(id) {
	const endpoint = endpointById(id);
	assert.ok(endpoint);
	return endpoint;
}

test("endpoint definitions cover the curated anonymous read surface", () => {
	assert.deepEqual(
		API_EXPLORER_ENDPOINTS.map((endpoint) => endpoint.pathTemplate),
		[
			"/api/search/tools/",
			"/api/tools/{name}/",
			"/v1/people/tools/{name}/",
			"/api/tools/{name}/revisions/",
			"/api/lists/",
			"/api/recent/",
			"/api/crawler/urls/",
			"/api/schema/"
		]
	);
});

test("buildExplorerRequest encodes path parameters and query strings", () => {
	const endpoint = mustEndpoint("tool-revisions");
	const request = buildExplorerRequest(endpoint, { name: "Foo/Bar & Baz", page_size: "7" });
	assert.equal(request.method, "GET");
	assert.equal(request.path, "/api/tools/Foo%2FBar%20%26%20Baz/revisions/?page_size=7");
	assert.equal(request.proxyUrl, request.path);
	assert.equal(
		request.canonicalUrl,
		"https://toolhub.wikimedia.org/api/tools/Foo%2FBar%20%26%20Baz/revisions/?page_size=7"
	);
	assert.match(request.curlProxy, /curl -H 'Accept: application\/json' '\/api\/tools\//);
	assert.match(request.fetchExample, /fetch\("\/api\/tools\/Foo%2FBar%20%26%20Baz\/revisions\/\?page_size=7"/);
});

test("buildExplorerRequest keeps Evolved endpoints same-origin", () => {
	const request = buildExplorerRequest(mustEndpoint("tool-people"), { name: "Foo/Bar" });
	assert.equal(request.path, "/v1/people/tools/Foo%2FBar/");
	assert.equal(request.proxyUrl, request.path);
	assert.equal(request.canonicalUrl, request.path);
	assert.match(request.curlCanonical, /'\/v1\/people\/tools\/Foo%2FBar\/'/);
});

test("buildExplorerRequest uses defaults and reports missing required path fields", () => {
	assert.equal(buildExplorerRequest(mustEndpoint("search-tools")).path, "/api/search/tools/?q=wikidata&page_size=5");
	assert.throws(() => buildExplorerRequest(mustEndpoint("tool-detail"), { name: "" }), /Tool name is required/);
});

test("formatJsonText pretty-prints JSON and leaves plain text alone", () => {
	assert.equal(formatJsonText('{"a":1,"b":[2]}'), '{\n  "a": 1,\n  "b": [\n    2\n  ]\n}');
	assert.equal(formatJsonText("not json"), "not json");
});

test("runExplorerRequest returns status, safe headers, timing, and formatted body", async () => {
	const fetcher = vi.fn(async () =>
		response('{"results":[{"name":"x"}]}', {
			headers: {
				"content-type": "application/json",
				"x-toolhub-evolved-cache": "hit",
				"set-cookie": "private"
			}
		})
	);
	let now = 10;
	const result = await runExplorerRequest(mustEndpoint("recent"), { page_size: "2" }, fetcher, () => {
		now += 25;
		return now;
	});
	assert.deepEqual(fetcher.mock.calls[0], ["/api/recent/?page_size=2"]);
	assert.equal(result.ok, true);
	assert.equal(result.status, 200);
	assert.equal(result.durationMs, 25);
	assert.equal(result.headers["content-type"], "application/json");
	assert.equal(result.headers["x-toolhub-evolved-cache"], "hit");
	assert.equal(result.headers["set-cookie"], undefined);
	assert.match(result.bodyText, /"results"/);
});

test("runExplorerRequest renders HTTP and network errors as text states", async () => {
	const http = await runExplorerRequest(mustEndpoint("schema"), {}, async () =>
		response('{"detail":"down"}', { status: 503, statusText: "Service Unavailable" })
	);
	assert.equal(http.ok, false);
	assert.equal(http.status, 503);
	assert.match(http.bodyText, /"detail": "down"/);

	const network = await runExplorerRequest(mustEndpoint("schema"), {}, async () => {
		throw new Error("offline");
	});
	assert.equal(network.ok, false);
	assert.equal(network.status, null);
	assert.equal(network.error, "offline");
});

test("mounted explorer submits forms, announces output, and updates examples", async () => {
	document.body.innerHTML = renderApiExplorer();
	const fetcher = vi.fn(async () => response('{"ok":true}'));
	vi.stubGlobal("fetch", fetcher);
	mountApiExplorer();

	const form = document.querySelector('[data-api-endpoint="tool-detail"]');
	assert.ok(form instanceof HTMLFormElement);
	const input = form.querySelector("input");
	assert.ok(input instanceof HTMLInputElement);
	input.value = "Tool/With Space";
	input.dispatchEvent(new Event("input", { bubbles: true }));
	assert.match(form.querySelector("[data-api-path]").textContent, /Tool%2FWith%20Space/);
	assert.match(form.querySelector("[data-api-examples]").textContent, /Tool%2FWith%20Space/);

	form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
	await new Promise((resolve) => {
		setTimeout(resolve, 0);
	});

	const status = document.querySelector("[data-api-status]");
	const output = document.querySelector("[data-api-output]");
	assert.ok(status);
	assert.ok(output);
	assert.match(status.textContent, /returned 200 OK/);
	assert.equal(output.getAttribute("tabindex"), "0");
	assert.match(output.textContent, /"ok": true/);
	assert.equal(fetcher.mock.calls[0][0], "/api/tools/Tool%2FWith%20Space/");
	assert.deepEqual(fetcher.mock.calls[0][1].headers, { Accept: "application/json" });
	assert.ok(fetcher.mock.calls[0][1].signal instanceof AbortSignal);
});
