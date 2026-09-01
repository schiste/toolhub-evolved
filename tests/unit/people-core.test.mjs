// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

const h = vi.hoisted(() => ({ backendGetJson: vi.fn(), normalizeTool: vi.fn((tool) => tool) }));
vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => ({
	...(await importOriginal()),
	backendGetJson: h.backendGetJson,
	normalizeTool: h.normalizeTool
}));

import {
	peopleForTool,
	personByHandle,
	personById,
	resolvePersonHandle,
	searchCommunity,
	searchPeople,
	searchPeopleDirectory,
	searchUnresolvedAttributions,
	toolsForPerson
} from "../../public_html/lib/core/people.js";

beforeEach(() => {
	h.backendGetJson.mockReset();
	h.normalizeTool.mockClear();
});

test("people endpoints encode identities and bounded pagination", async () => {
	h.backendGetJson.mockResolvedValue({ ok: true });
	await peopleForTool("A tool/name");
	await personById("person/id");
	await personById("person/id", { toolPage: 1, toolPageSize: 12 });
	await personById("person/id", { toolPage: 3, toolPageSize: 0 });

	assert.deepEqual(
		h.backendGetJson.mock.calls.map(([url]) => url),
		[
			"/v1/people/tools/A%20tool%2Fname/",
			"/v1/people/person%2Fid/",
			"/v1/people/person%2Fid/?tool_page_size=12",
			"/v1/people/person%2Fid/?tool_page=3"
		]
	);
});

test("community search passes every filter and preserves explicit sections", async () => {
	h.backendGetJson.mockResolvedValue({
		results: [{ id: "legacy" }],
		primaryResults: [{ id: "person-1" }],
		relatedTools: { count: "2", results: [{ name: "tool" }], truncated: 1 },
		unresolvedEvidence: { count: 1, results: [{ label: "Ada" }], truncated: false },
		otherMatches: { count: 0, results: "invalid", truncated: 0 },
		count: "7",
		totalCount: 9,
		counts: { people: 1 },
		page: 2,
		pageSize: 5,
		pageCount: 3,
		next: 3,
		previous: 1,
		truncated: true,
		accountSync: { status: "complete", complete: true }
	});
	const result = await searchCommunity({
		q: "Ada Lovelace",
		page: 2,
		pageSize: 5,
		role: "maintainer",
		verification: "verified",
		activity: "active",
		project: "toolforge",
		ordering: "name",
		contributor: "yes"
	});

	assert.equal(
		h.backendGetJson.mock.calls[0][0],
		"/v1/community/?q=Ada+Lovelace&page=2&page_size=5&role=maintainer&verification=verified&activity=active&project=toolforge&ordering=name&contributor=yes"
	);
	assert.deepEqual(result.results, [{ id: "person-1" }]);
	assert.deepEqual(result.relatedTools, { count: 2, results: [{ name: "tool" }], truncated: true });
	assert.deepEqual(result.otherMatches, { count: 0, results: [], truncated: false });
	assert.equal(result.count, 7);
	assert.equal(result.totalCount, 9);
	assert.equal(result.page, 2);
	assert.equal(result.next, 3);
	assert.deepEqual(result.accountSync, { status: "complete", complete: true });
});

test("community search normalizes sparse and malformed responses", async () => {
	h.backendGetJson
		.mockResolvedValueOnce({ results: "invalid", count: "nope", totalCount: null })
		.mockResolvedValueOnce({
			results: [{ id: "person-2" }]
		});
	const sparse = await searchCommunity("Ada");
	const fallback = await searchCommunity();

	assert.equal(h.backendGetJson.mock.calls[0][0], "/v1/community/?q=Ada");
	assert.deepEqual(sparse.results, []);
	assert.equal(sparse.count, 0);
	assert.equal(sparse.totalCount, 0);
	assert.deepEqual(sparse.counts, {
		people: 0,
		accounts: 0,
		tools: 0,
		otherToolMatches: 0,
		unresolvedAttributions: 0,
		foldedUnresolvedAttributions: 0
	});
	assert.equal(sparse.pageSize, 24);
	assert.deepEqual(sparse.accountSync, { status: "unavailable", complete: false });
	assert.deepEqual(fallback.results, [{ id: "person-2" }]);
	assert.equal(fallback.count, 1);

	h.backendGetJson.mockResolvedValue(null);
	await assert.rejects(() => searchCommunity(), /Community directory unavailable/);
});

test("people and unresolved searches normalize paging and reject outages", async () => {
	h.backendGetJson
		.mockResolvedValueOnce({
			results: [{ id: "person-1" }],
			unresolvedAttributions: [{ label: "Ada" }],
			count: "4",
			page: 2,
			pageSize: 8,
			pageCount: 3,
			next: 3,
			previous: 1
		})
		.mockResolvedValueOnce({ results: [{ id: "person-2" }] })
		.mockResolvedValueOnce({ results: [{ label: "Unknown" }], count: "bad" })
		.mockResolvedValueOnce({ results: "invalid", count: 0, pageSize: 5 });

	const directory = await searchPeopleDirectory({ q: "Ada", page: 2, pageSize: 8, role: "author" });
	assert.equal(h.backendGetJson.mock.calls[0][0], "/v1/people/?q=Ada&page=2&page_size=8&role=author");
	assert.equal(directory.count, 4);
	assert.deepEqual(directory.unresolvedAttributions, [{ label: "Ada" }]);
	assert.deepEqual(await searchPeople("Grace"), [{ id: "person-2" }]);

	const unresolved = await searchUnresolvedAttributions({ q: "Unknown", pageSize: 10, project: "meta" });
	assert.equal(h.backendGetJson.mock.calls[2][0], "/v1/people/attributions/?q=Unknown&page_size=10&project=meta");
	assert.equal(unresolved.count, 1);
	assert.equal(unresolved.pageSize, 10);
	const malformed = await searchUnresolvedAttributions();
	assert.deepEqual(malformed.attributions, []);
	assert.equal(malformed.pageSize, 5);

	h.backendGetJson.mockResolvedValue(null);
	await assert.rejects(() => searchPeopleDirectory(), /People directory unavailable/);
	await assert.rejects(() => searchUnresolvedAttributions(), /Unresolved attribution search unavailable/);
});

test("handle resolution only loads a person for a stable resolved identity", async () => {
	h.backendGetJson
		.mockResolvedValueOnce({ status: "ok" })
		.mockResolvedValueOnce({ status: "resolved", person: { id: "person-1" } })
		.mockResolvedValueOnce({ id: "person-1" })
		.mockResolvedValueOnce({ status: "ambiguous", person: { id: "person-2" } })
		.mockResolvedValueOnce({ status: "resolved", person: {} });

	await resolvePersonHandle("Ada Lovelace", { context: "attribution" });
	assert.equal(h.backendGetJson.mock.calls[0][0], "/v1/people/resolve/?handle=Ada+Lovelace&context=attribution");
	assert.deepEqual(await personByHandle("Ada"), { id: "person-1" });
	assert.equal(h.backendGetJson.mock.calls[2][0], "/v1/people/person-1/");
	assert.equal(await personByHandle("shared"), null);
	assert.equal(await personByHandle("missing-id"), null);
});

test("profile tools accept both embedded shapes and discard invalid rows", () => {
	const rows = [
		{
			name: "complete",
			summary: { title: "Complete", _missingCanonical: false },
			relationships: [{ type: "author" }],
			summaryStatus: "fresh"
		},
		{ name: "missing", summary: { _missingCanonical: true }, relationships: "invalid" },
		{ name: "plain", summary: "invalid" },
		{ summary: { title: "no name" } },
		null
	];
	const tools = toolsForPerson({ tools: { results: rows } });

	assert.equal(tools.length, 3);
	assert.equal(tools[0].profileSummaryStatus, "fresh");
	assert.deepEqual(tools[0].personRelationships, [{ type: "author" }]);
	assert.equal(tools[1].profileSummaryStatus, "missing");
	assert.deepEqual(tools[1].personRelationships, []);
	assert.equal(tools[2].profileSummaryStatus, "available");
	assert.deepEqual(
		toolsForPerson({ tools: rows }).map(({ name }) => name),
		["complete", "missing", "plain"]
	);
	assert.deepEqual(toolsForPerson({ tools: null }), []);
});
