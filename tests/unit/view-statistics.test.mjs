// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

const h = vi.hoisted(() => ({ backendGetJson: vi.fn() }));
vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => ({
	...(await importOriginal()),
	backendGetJson: h.backendGetJson
}));

import { statisticsHTML, viewStatistics } from "../../public_html/views/statistics.js";

const payload = {
	generatedAt: "2026-08-13T12:00:00Z",
	catalog: {
		totalTools: 3000,
		verifiedAuthors: { count: 900, missingCount: 2100, percent: 30 },
		listedAuthors: { count: 2400, missingCount: 600, percent: 80 },
		verifiedMaintainers: { count: 750, missingCount: 2250, percent: 25 },
		unresolvedAuthorTools: 420,
		coreMetadataComplete: { count: 1800, missingCount: 1200, percent: 60 }
	},
	metadata: [{ key: "title", label: "Title", count: 2900, missingCount: 100, percent: 97 }],
	relationships: { authors: { verified: 950, unverified: 600 }, maintainers: { verified: 800 } },
	relationshipMetrics: {
		people: { withAnyCurrentRelationship: 500, withAnyVerifiedRelationship: 480, identityOnly: 120 },
		rows: { total: 2350, verified: 1750, stale: 25 },
		newlyVerifiedTools: { last24Hours: { all: 12, authors: 3, maintainers: 10 } },
		evidenceFreshness: { active: 2500, expired: 8, expiringWithin72Hours: 15, withdrawn: 100 }
	},
	identities: { publishablePeople: 600, stablePeople: 400, handlePeople: 200, unresolvedLabels: 350 },
	sources: {
		total: 200,
		validFeeds: 180,
		items: 2600,
		statuses: { verified: 150, unverified: 50 },
		classifications: { single_controller: 140, shared: 40, unknown: 20 }
	},
	distributions: {
		createdByYear: [{ key: "2025", label: "2025", count: 500 }],
		modifiedByYear: [{ key: "2026", label: "2026", count: 700 }],
		modifiedRecency: [{ key: "last30Days", label: "Last 30 days", count: 300 }],
		toolTypes: [{ key: "web-app", label: "Web app", count: 1200 }]
	},
	definitions: {
		verifiedAuthor: "Verified author definition",
		listedAuthor: "Listed author definition",
		verifiedMaintainer: "Verified maintainer definition",
		dateBasis: "Canonical date definition"
	}
};

beforeEach(() => {
	document.body.innerHTML = "";
	h.backendGetJson.mockReset();
});

test("statistics report exposes exact counts alongside accessible histograms", () => {
	const html = statisticsHTML(payload);
	assert.match(html, /Total tools/);
	assert.match(html, /3,000/);
	assert.match(html, /Need author verification/);
	assert.match(html, /2,100/);
	assert.match(html, /<meter min="0" max="100" value="30">30%<\/meter>/);
	assert.match(html, /Catalog records created by year/);
	assert.match(html, /<figure class="statistics-histogram">/);
	assert.match(html, /How these statistics are calculated/);
	assert.match(html, /Verified author definition/);
	assert.match(html, /People with a verified relationship/);
	assert.match(html, /480/);
	assert.match(html, /Newly verified tools · 24h/);
	assert.match(html, /Stale relationships/);
});

test("statistics route settles immediately, then replaces its local loading state", async () => {
	h.backendGetJson.mockResolvedValue(payload);
	const view = viewStatistics();
	assert.deepEqual(view.styles, ["/styles/statistics.css"]);
	document.body.innerHTML = view.html;
	view.mount();
	await vi.waitFor(() => assert.match(document.body.textContent, /3,000/));
	assert.deepEqual(h.backendGetJson.mock.calls[0], ["/v1/statistics/"]);
	assert.equal(document.querySelector("[data-statistics-root]").hasAttribute("aria-busy"), false);
});

test("statistics request failures remain retryable instead of looking empty", async () => {
	h.backendGetJson.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(payload);
	const view = viewStatistics();
	document.body.innerHTML = view.html;
	view.mount();
	await vi.waitFor(() => assert.match(document.body.textContent, /temporarily unavailable/));
	document.querySelector("[data-statistics-retry]").click();
	await vi.waitFor(() => assert.match(document.body.textContent, /3,000/));
	assert.equal(h.backendGetJson.mock.calls.length, 2);
});

test("the wait is a skeleton of the ledger, announced but not written out", () => {
	const view = viewStatistics();
	document.body.innerHTML = view.html;
	const region = document.querySelector(".statistics-loading");
	assert.equal(region.getAttribute("role"), "status");
	assert.equal(region.querySelector(".visually-hidden").textContent, "Calculating catalog quality");
	// The shapes stand in for the report's own layout, and none of them is
	// readable text: a reader sees placeholders, not the word "loading".
	const body = region.querySelector('[aria-hidden="true"]');
	assert.ok(body.classList.contains("statistics-report"));
	assert.equal(body.textContent.trim(), "");
	assert.equal(body.querySelectorAll(".statistics-ledger > div").length, 4);
	assert.equal(body.querySelectorAll(".statistics-section").length, 2);
	assert.equal(region.querySelector(".spinner"), null);
});
