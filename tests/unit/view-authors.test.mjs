// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";
// toolsByAuthor hits the network (paginate → apiGet), so it is fixture-driven here.
// authorProfileUrl, grid, toolCard, and the dom/i18n helpers stay real so the rendered
// HTML — and the `(t) => toolCard(t)` mapper arrow — is exercised end to end.
import { peopleDirectoryState, viewAuthor, viewPeople, viewPerson } from "../../public_html/views/authors.js";
import { icon } from "../../public_html/lib/atoms/icon.js";
import * as authorIndex from "../../public_html/lib/core/author-index.js";

const h = vi.hoisted(() => ({
	backendGetJson: vi.fn(() => Promise.resolve({ results: {} })),
	getToolsByName: vi.fn(() => Promise.resolve([]))
}));

vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, backendGetJson: h.backendGetJson, getToolsByName: h.getToolsByName };
});
vi.mock("../../public_html/lib/core/author-index.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, toolsByAuthor: vi.fn() };
});

const tool = (name, title) => ({ name, title, keywords: [], forWikis: [] });

beforeEach(() => {
	window.history.replaceState({}, "", "/people");
	h.backendGetJson.mockReset();
	h.backendGetJson.mockResolvedValue({ status: "not_found" });
	h.getToolsByName.mockReset();
	h.getToolsByName.mockResolvedValue([]);
	authorIndex.toolsByAuthor.mockReset();
});

test("viewAuthor renders the author name, count, back link and a tools grid", async () => {
	authorIndex.toolsByAuthor.mockResolvedValue({
		name: "Ada Lovelace",
		tools: [tool("t1", "Tool One"), tool("t2", "Tool Two")],
		profile: { url: "https://example.org/ada" }
	});
	const view = await viewAuthor("ada");

	assert.equal(view.title, "Ada Lovelace — Toolhub");
	assert.match(view.html, /<a class="back" href="\/search">← Back to tools<\/a>/);
	assert.match(view.html, /<h1 class="page__title" dir="auto">Ada Lovelace<\/h1>/);
	// countLabel(2, "tool", "tools") → "2 tools" (kills the "tool"/"tools" literals + count).
	assert.match(view.html, /<p class="page__intro">2 tools<\/p>/);
	// Real grid + the mapper arrow produce one card per tool.
	assert.match(view.html, /<ul class="card-grid grid-tools author-page__tool-grid" role="list">/);
	assert.match(view.html, /data-tool="t1"/);
	assert.match(view.html, /data-tool="t2"/);
	// Author profile link present and outbound, with the real external icon
	// (kills icon("external") → icon("")).
	assert.match(
		view.html,
		/<a class="author-page__profile" href="https:\/\/example\.org\/ada" target="_blank" rel="noopener nofollow">example\.org /
	);
	assert.ok(view.html.includes(`example.org ${icon("external")}</a>`));
	assert.match(view.html, /<h2 id="author-related-tools">Related tools<\/h2>/);
	assert.match(view.html, /Listed author/);
	assert.match(view.html, /<dt>Public contributions<\/dt><dd>0<\/dd>/);
});

test("viewPerson renders every role with distinct provenance on one tool", async () => {
	h.backendGetJson.mockResolvedValueOnce({
		id: "person-trust",
		displayName: "Ada Lovelace",
		identityQuality: "stable_id",
		profile: {},
		activity: { status: "unknown", relatedToolCount: 1, verifiedToolCount: 1 },
		toolCount: 1,
		tools: {
			count: 1,
			page: 1,
			pageSize: 24,
			pageCount: 1,
			results: [
				{
					name: "trust-tool",
					summary: { name: "trust-tool", title: "Trust Tool", description: "A compact profile summary." },
					summaryStatus: "available",
					relationships: [
						{
							type: "author",
							status: "unverified",
							confidence: 45,
							evidenceCount: 1,
							toolhubCanonical: true,
							evidence: [
								{
									source: "toolhub_author_metadata",
									method: "toolhub_author_metadata",
									status: "unverified",
									checkedAt: "2026-08-01T12:00:00Z",
									identityBasis: "stable_id"
								}
							]
						},
						{
							type: "maintainer",
							status: "verified",
							confidence: 95,
							evidenceCount: 1,
							evidence: [
								{
									source: "toolforge_toolsadmin",
									method: "toolforge_maintainer",
									status: "verified",
									checkedAt: "2026-08-02T12:00:00Z"
								}
							]
						},
						{
							type: "record_owner",
							status: "verified",
							confidence: 90,
							evidenceCount: 1,
							evidence: [{ method: "toolhub_write_access", status: "verified" }]
						}
					]
				}
			]
		}
	});

	const view = await viewPerson("person-trust");

	assert.equal(view.html.match(/data-tool="trust-tool"/g)?.length, 1);
	assert.match(view.html, /Trust Tool/);
	assert.match(view.html, /Identity backed by a stable account ID/);
	assert.match(view.html, /Listed author/);
	assert.match(view.html, /Verified Toolforge maintainer/);
	assert.doesNotMatch(view.html, /record authority/i);
	assert.match(view.html, /Toolhub author field/);
	assert.match(view.html, /datetime="2026-08-01T12:00:00\.000Z"/);
	assert.match(view.html, /<dt>Tools with a verified relationship<\/dt><dd>1<\/dd>/);
	assert.equal(h.getToolsByName.mock.calls.length, 0);
});

test("viewPerson requests one bounded embedded page and never loads per-tool details", async () => {
	window.history.replaceState({}, "", "/people/person-prolific?page=2");
	const results = Array.from({ length: 24 }, (_, offset) => {
		const index = offset + 24;
		const name = `profile-tool-${String(index).padStart(3, "0")}`;
		return {
			name,
			summary: { name, title: `Profile Tool ${index}`, description: `Compact summary ${index}` },
			summaryStatus: "available",
			relationships: []
		};
	});
	h.backendGetJson.mockImplementation((url) => {
		if (url === "/v1/people/person-prolific/?tool_page=2") {
			return Promise.resolve({
				id: "person-prolific",
				displayName: "Prolific Maintainer",
				profile: {},
				activity: { status: "active", relatedToolCount: 250 },
				toolCount: 250,
				tools: { count: 250, page: 2, pageSize: 24, pageCount: 11, results }
			});
		}
		if (String(url).startsWith("/v1/tools/summaries/")) return Promise.resolve({ results: {} });
		return Promise.reject(new Error(`unexpected request: ${url}`));
	});

	const view = await viewPerson("person-prolific");

	assert.equal(h.backendGetJson.mock.calls[0][0], "/v1/people/person-prolific/?tool_page=2");
	assert.equal(view.html.match(/data-tool="profile-tool-/g)?.length, 24);
	assert.match(view.html, /<p class="page__intro">250 tools<\/p>/);
	assert.match(view.html, /Showing 25–48 of 250/);
	assert.equal(h.getToolsByName.mock.calls.length, 0);
	document.body.innerHTML = view.html;
	view.mount();
	document.querySelector('[data-person-tools-pager] [data-page="3"]').click();
	assert.equal(location.pathname, "/people/person-prolific");
	assert.equal(new URLSearchParams(location.search).get("page"), "3");
});

test("viewAuthor uses the requested name and singular label when the index omits them", async () => {
	// No `name` → falls back to the requested name; no `tools` → empty array → empty state.
	authorIndex.toolsByAuthor.mockResolvedValue({ profile: {} });
	const view = await viewAuthor("Grace Hopper");

	assert.equal(view.title, "Grace Hopper — Toolhub");
	assert.match(view.html, /<h1 class="page__title" dir="auto">Grace Hopper<\/h1>/);
	// Empty tools → empty state, never a grid.
	assert.match(view.html, /<p class="empty">No tools found for this person\.<\/p>/);
	assert.doesNotMatch(view.html, /card-grid/);
	// No profile → profileLink is exactly "" (kills the `: ""` → injected-string mutant):
	// the inner head <div> closes and the section-head <div> closes with only whitespace
	// between them — an injected fallback string would appear there.
	assert.doesNotMatch(view.html, /author-page__profile/);
	assert.match(view.html, /<\/p(?:>\s*<\/div){2}>/);
});

test("viewAuthor shows exactly one tool with the singular 'tool' label", async () => {
	authorIndex.toolsByAuthor.mockResolvedValue({ name: "Solo", tools: [tool("only", "Only Tool")], profile: {} });
	const view = await viewAuthor("Solo");
	assert.match(view.html, /<p class="page__intro">1 tool<\/p>/);
	assert.match(view.html, /<ul class="card-grid grid-tools author-page__tool-grid" role="list">/);
});

test("viewAuthor builds a Meta-Wiki profile URL from a wikiUsername", async () => {
	authorIndex.toolsByAuthor.mockResolvedValue({
		name: "Wiki User",
		tools: [],
		profile: { wikiUsername: "Wiki User" }
	});
	const view = await viewAuthor("Wiki User");
	assert.match(
		view.html,
		/href="https:\/\/meta\.wikimedia\.org\/wiki\/User:Wiki%20User" target="_blank" rel="noopener nofollow"/
	);
});

test("viewAuthor drops an unsafe (non-http) profile URL via safeUrl", async () => {
	authorIndex.toolsByAuthor.mockResolvedValue({
		name: "Sneaky",
		tools: [],
		// authorProfileUrl returns this verbatim; safeUrl must reject it, so no link renders.
		profile: { url: "javascript:alert(1)" }
	});
	const view = await viewAuthor("Sneaky");
	assert.doesNotMatch(view.html, /author-page__profile/);
	assert.doesNotMatch(view.html, /javascript:/);
});

test("viewAuthor resolves one exact handle through the dedicated resolver", async () => {
	h.backendGetJson
		.mockResolvedValueOnce({
			status: "resolved",
			person: { id: "person-ada", displayName: "Ada Lovelace" }
		})
		.mockResolvedValueOnce({
			id: "person-ada",
			displayName: "Ada Lovelace",
			identifiers: [{ namespace: "toolhub_username", value: "Ada" }],
			profile: {},
			activity: { status: "unknown" },
			tools: []
		});

	const view = await viewAuthor("Ada");

	assert.equal(h.backendGetJson.mock.calls[0][0], "/v1/people/resolve/?handle=Ada");
	assert.equal(h.backendGetJson.mock.calls[1][0], "/v1/people/person-ada/");
	assert.equal(view.title, "Ada Lovelace — Toolhub");
	assert.equal(authorIndex.toolsByAuthor.mock.calls.length, 0);
});

test("viewAuthor renders disambiguation instead of selecting the first duplicate", async () => {
	h.backendGetJson.mockResolvedValueOnce({
		status: "ambiguous",
		matchType: "display_name",
		candidates: [
			{
				id: "person-one",
				displayName: "Shared Name",
				identifiers: [{ namespace: "toolforge_username", value: "shared-one" }]
			},
			{
				id: "person-two",
				displayName: "Shared Name",
				identifiers: [{ namespace: "wiki_username", value: "Shared Two" }]
			}
		],
		unresolvedAttributions: []
	});

	const view = await viewAuthor("Shared Name");

	assert.equal(view.title, "Shared Name — Choose a person");
	assert.match(view.html, /This name does not identify one unique person/);
	assert.match(view.html, /href="\/people\/person-one"/);
	assert.match(view.html, /href="\/people\/person-two"/);
	assert.match(view.html, /Toolforge: shared-one/);
	assert.match(view.html, /Wiki: Shared Two/);
	assert.equal(authorIndex.toolsByAuthor.mock.calls.length, 0);
});

test("viewAuthor explains unresolved labels without inventing a person link", async () => {
	h.backendGetJson.mockResolvedValueOnce({
		status: "ambiguous",
		matchType: "none",
		candidates: [],
		unresolvedAttributions: [
			{ label: "Magnus Manske", toolCount: 50, evidenceCount: 50, identityStatus: "unresolved_attribution" }
		]
	});

	const view = await viewAuthor("Magnus Manske");

	assert.match(view.html, /Attributions awaiting identity evidence/);
	assert.match(view.html, /50 tools · 50 observations/);
	assert.doesNotMatch(view.html, /href="\/people\/[^"]+"/);
	assert.equal(authorIndex.toolsByAuthor.mock.calls.length, 0);
});

test("viewPeople unifies resolved people, official accounts, tools, and unresolved attributions", async () => {
	h.backendGetJson.mockResolvedValueOnce({
		count: 2,
		totalCount: 5,
		page: 1,
		pageSize: 24,
		pageCount: 1,
		counts: {
			people: 1,
			accounts: 1,
			tools: 1,
			otherToolMatches: 1,
			unresolvedAttributions: 1,
			foldedUnresolvedAttributions: 1
		},
		accountSync: { status: "ready", complete: true },
		primaryResults: [
			{
				kind: "person",
				person: {
					id: "person-1",
					displayName: "Ada",
					identityQuality: "stable_id",
					profile: {},
					activity: { relatedToolCount: 3 },
					relationshipSummary: {
						types: ["author", "maintainer", "record_owner"],
						verifiedTypes: ["maintainer", "record_owner"],
						toolCountsByType: { author: 1, maintainer: 2, record_owner: 1 },
						verifiedToolCountsByType: { author: 0, maintainer: 1, record_owner: 1 }
					}
				},
				identityEvidence: { officialToolhubAccount: true, wikimediaIdentity: true },
				officialAccountMatches: [{ id: "42", username: "AdaToolhub" }],
				matchBasis: ["account", "identity"],
				supportingEvidence: [
					{
						label: "Ada",
						identityStatus: "unresolved_attribution",
						toolCount: 50,
						evidenceCount: 50,
						relationshipBreakdown: [
							{ type: "author", status: "unverified", toolCount: 30 },
							{ type: "maintainer", status: "verified", toolCount: 12 },
							{ type: "maintainer", status: "stale", toolCount: 8 }
						]
					}
				]
			},
			{
				kind: "account",
				account: { id: "99", username: "Official Only", identityLinkStatus: "unlinked" }
			}
		],
		relatedTools: {
			count: 1,
			truncated: false,
			results: [
				{
					kind: "tool",
					match: { field: "relationship", reason: "person_relationship", value: "Ada" },
					tool: {
						name: "magnus-tool",
						title: "Magnus Tool",
						description: "A directly matching catalog tool",
						keywords: ["magnus"],
						for_wikis: ["wikidata.org"],
						author: [{ name: "Ada" }]
					},
					relationships: [
						{
							personName: "Ada",
							type: "author",
							status: "unverified",
							evidenceCount: 1,
							confidence: 45,
							toolhubCanonical: true,
							evidence: [
								{
									source: "toolhub_author_metadata",
									method: "toolhub_author_metadata",
									status: "unverified"
								}
							]
						},
						{
							personName: "Ada",
							type: "maintainer",
							status: "verified",
							evidenceCount: 2,
							confidence: 95,
							evidence: [
								{ source: "toolforge_toolsadmin", method: "toolforge_maintainer", status: "verified" }
							]
						}
					]
				}
			]
		},
		unresolvedEvidence: {
			count: 1,
			truncated: false,
			results: [{ label: "Shared Label", toolCount: 2, evidenceCount: 3, relationshipBreakdown: [] }]
		},
		otherMatches: {
			count: 1,
			truncated: false,
			results: [
				{
					kind: "tool",
					match: { field: "description", reason: "description_mention", value: "Based on a script by Ada" },
					tool: {
						name: "description-only",
						title: "Description Only",
						description: "Based on a script by Ada",
						keywords: [],
						for_wikis: [],
						author: [{ name: "Someone Else" }]
					}
				}
			]
		}
	});

	const view = await viewPeople();

	assert.match(view.html, /<div class="browse">/);
	assert.match(view.html, /<aside class="facets community-facets"/);
	assert.match(view.html, /class="browse__bar"/);
	assert.match(view.html, /<ul class="card-grid grid-tools community-results" role="list">/);
	assert.equal(view.html.match(/class="tcard entity-card/g)?.length, 2);
	assert.match(view.html, /data-tool="magnus-tool"/);
	assert.match(view.html, /data-tool="description-only"/);
	assert.doesNotMatch(view.html, /class="people-card/);
	assert.match(view.html, /href="\/people\/person-1"/);
	assert.match(view.html, /Showing 1–2 of 2 primary matches/);
	assert.match(view.html, /1 related tool/);
	assert.match(view.html, /1 other text match/);
	assert.match(view.html, /Official Toolhub account/);
	assert.match(view.html, /Wikimedia identity matched by stable ID/);
	assert.match(view.html, /Listed Author/);
	assert.match(view.html, /Maintainer · 1 of 2 tools verified/);
	assert.doesNotMatch(view.html, /record owner/i);
	assert.match(view.html, /href="\/people\?account=99"/);
	assert.match(view.html, /No stable public person or tool relationship is linked yet/);
	assert.match(view.html, /50 additional observations across 50 tools are not safely linked/);
	assert.match(view.html, /Name observed in metadata — not a resolved person/);
	assert.match(view.html, /Shared Label/);
	assert.match(view.html, /Listed Author · 30 tools/);
	assert.match(view.html, /Verified Maintainer relationship · 12 tools/);
	assert.match(view.html, /Previous Maintainer verification—renewal needed · 8 tools/);
	assert.match(view.html, /Related tools and strong matches/);
	assert.match(view.html, /Related through this person&#39;s tool relationships/);
	assert.match(view.html, /Listed author/);
	assert.match(view.html, /Verified Toolforge maintainer/);
	assert.match(view.html, /Tools mentioning this text/);
	assert.match(view.html, /The name is mentioned only in the tool description/);
	assert.match(view.html, /href="\/tools\/magnus-tool"/);
});

test("peopleDirectoryState validates and restores shareable URL state", () => {
	const state = peopleDirectoryState(
		new URLSearchParams(
			"q=Magnus+Manske&page=3&page_size=48&role=maintainer&verification=verified&activity=active&project=wikidata.org&ordering=name&contributor=observed"
		)
	);

	assert.deepEqual(state, {
		q: "Magnus Manske",
		page: 3,
		pageSize: 48,
		role: "maintainer",
		verification: "verified",
		activity: "active",
		project: "wikidata.org",
		ordering: "name",
		contributor: true,
		accountId: ""
	});
	assert.deepEqual(peopleDirectoryState(new URLSearchParams("page=0&page_size=999&role=admin&ordering=random")), {
		q: "",
		page: 1,
		pageSize: 24,
		role: "",
		verification: "",
		activity: "",
		project: "",
		ordering: "relevance",
		contributor: false,
		accountId: ""
	});
});

test("viewPeople hydrates filters from the URL and sends the complete API query", async () => {
	window.history.replaceState(
		{},
		"",
		"/people?q=Magnus+Manske&page=2&page_size=48&role=maintainer&verification=verified&activity=active&project=wikidata.org&ordering=name"
	);
	h.backendGetJson.mockResolvedValueOnce({ count: 0, page: 2, pageSize: 48, pageCount: 1, results: [] });

	const view = await viewPeople();

	assert.match(view.html, /name="q"[^>]*value="Magnus Manske"/);
	assert.match(view.html, /option value="maintainer" selected/);
	assert.match(view.html, /option value="verified" selected/);
	assert.match(view.html, /option value="active" selected/);
	assert.match(view.html, /name="project" value="wikidata.org"/);
	assert.match(view.html, /option value="name" selected/);
	assert.equal(h.backendGetJson.mock.calls.length, 1);
	assert.match(h.backendGetJson.mock.calls[0][0], /^\/v1\/community\/\?/);
	assert.match(h.backendGetJson.mock.calls[0][0], /q=Magnus\+Manske/);
	assert.match(h.backendGetJson.mock.calls[0][0], /page=2/);
	assert.match(h.backendGetJson.mock.calls[0][0], /role=maintainer/);
});

test("people search submission navigates, resets paging, and announces loading", async () => {
	h.backendGetJson
		.mockResolvedValueOnce({ count: 0, page: 1, pageSize: 24, pageCount: 1, results: [] })
		.mockResolvedValueOnce({ count: 0, page: 1, pageSize: 10, pageCount: 1, results: [] });
	const view = await viewPeople();
	document.body.innerHTML = view.html;
	view.mount();

	document.querySelector('[name="q"]').value = "Ada Lovelace";
	document.querySelector('[name="role"]').value = "author";
	document.querySelector("[data-people-search]").dispatchEvent(new Event("submit", { cancelable: true }));

	assert.equal(location.pathname, "/people");
	assert.equal(new URLSearchParams(location.search).get("q"), "Ada Lovelace");
	assert.equal(new URLSearchParams(location.search).get("role"), "author");
	assert.equal(new URLSearchParams(location.search).has("page"), false);
	assert.match(document.querySelector("[data-people-results]").innerHTML, /role="status"/);
	assert.match(document.querySelector("[data-people-results]").textContent, /Searching/);
});

test("people search submission is stable when the form already represents the current URL", async () => {
	window.history.replaceState({}, "", "/people?q=Ada");
	h.backendGetJson.mockResolvedValueOnce({ count: 0, page: 1, pageSize: 24, pageCount: 1, results: [] });
	const view = await viewPeople();
	document.body.innerHTML = view.html;
	view.mount();
	let navigations = 0;
	const countNavigation = () => {
		navigations += 1;
	};
	window.addEventListener("toolhub:navigate", countNavigation);
	try {
		document.querySelector("[data-people-search]").dispatchEvent(new Event("submit", { cancelable: true }));
		assert.equal(navigations, 0);
		assert.doesNotMatch(document.querySelector("[data-people-results]").textContent, /Searching/);
	} finally {
		window.removeEventListener("toolhub:navigate", countNavigation);
	}
});

test("people pagination preserves filters in the URL", async () => {
	window.history.replaceState({}, "", "/people?q=Ada&role=maintainer");
	h.backendGetJson
		.mockResolvedValueOnce({ count: 50, page: 1, pageSize: 24, pageCount: 3, results: [] })
		.mockResolvedValueOnce({ count: 0, page: 1, pageSize: 10, pageCount: 1, results: [] });
	const view = await viewPeople();
	document.body.innerHTML = view.html;
	view.mount();

	document.querySelector('[data-people-pager] [data-page="2"]').click();

	const params = new URLSearchParams(location.search);
	assert.equal(params.get("q"), "Ada");
	assert.equal(params.get("role"), "maintainer");
	assert.equal(params.get("page"), "2");
});

test("people directory renders retryable errors instead of remaining in a loading state", async () => {
	h.backendGetJson.mockRejectedValue(new Error("offline"));
	const view = await viewPeople();

	assert.match(view.html, /role="alert"/);
	assert.match(view.html, /Community search could not be loaded/);
	assert.match(view.html, /Retry search/);
	assert.doesNotMatch(view.html, /Searching…/);
});

test("contributors view requests eligibility and explains each evidence basis", async () => {
	window.history.replaceState({}, "", "/people?view=contributors&q=Ada");
	h.backendGetJson.mockResolvedValueOnce({
		count: 1,
		page: 1,
		pageSize: 24,
		pageCount: 1,
		counts: { people: 1, accounts: 0, unresolvedAttributions: 0 },
		accountSync: { status: "ready", complete: true },
		results: [
			{
				kind: "person",
				person: {
					id: "person-ada",
					displayName: "Ada",
					identityQuality: "stable_id",
					profile: {},
					activity: { relatedToolCount: 1 },
					relationshipSummary: { types: [], verifiedTypes: [] },
					contributor: {
						eligible: true,
						bases: ["observed_public_contribution"]
					}
				},
				identityEvidence: { officialToolhubAccount: true },
				matchBasis: ["identity"]
			}
		]
	});
	const view = await viewPeople();

	assert.equal(h.backendGetJson.mock.calls.length, 1, "contributors do not request unresolved labels");
	assert.match(h.backendGetJson.mock.calls[0][0], /contributor=observed/);
	assert.match(view.html, /Community directory/);
	assert.match(view.html, /Observed contributors/);
	assert.match(view.html, /Observed public contribution activity/);
	assert.doesNotMatch(view.html, /catalog actor/i);
	assert.match(view.html, /option value="observed" selected/);
	document.body.innerHTML = view.html;
	view.mount();
	assert.equal(new URLSearchParams(location.search).get("view"), null);
	assert.equal(new URLSearchParams(location.search).get("contributor"), "observed");
});
