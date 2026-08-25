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

// A lens is a whole document, not a slice of one: the counts narrow, and so do
// the percentages, which is why the page cannot re-derive one lens from another.
/** @param {number} totalTools @param {number} percent @param {number} created */
const lens = (totalTools, percent, created) => {
	const verified = Math.round((totalTools * percent) / 100);
	const coverage = { count: verified, missingCount: totalTools - verified, percent };
	return {
		...payload,
		catalog: {
			totalTools,
			unresolvedAuthorTools: 0,
			verifiedAuthors: coverage,
			listedAuthors: coverage,
			verifiedMaintainers: coverage,
			coreMetadataComplete: coverage
		},
		metadata: [{ key: "title", label: "Title", ...coverage }],
		distributions: { ...payload.distributions, createdByYear: [{ key: "2025", label: "2025", count: created }] }
	};
};

payload.lenses = { catalog: lens(2000, 45, 320), wiki: lens(1000, 4, 180) };

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

test("the page opens on the combined reading and offers each lane as a whole page", () => {
	document.body.innerHTML = statisticsHTML(payload);
	const report = document.querySelector(".statistics-report");
	assert.equal(report.dataset.statisticsLens, "all");
	assert.deepEqual(
		[...document.querySelectorAll("[data-statistics-lens-option]")].map((input) => input.value),
		["all", "catalog", "wiki"]
	);
	assert.equal(document.querySelector("[data-statistics-lens-option]:checked").value, "all");
	// The control sits in the report itself, ahead of the first section, so it
	// reads as governing the page rather than the block it happens to precede.
	assert.ok(report.querySelector(".statistics-lens"));
});

test("a lens redraws every figure on the page, not only the chart it came from", () => {
	const wiki = statisticsHTML(payload, "wiki");
	// The ledger, the coverage meter, and the histogram are three different
	// blocks; all three have to move together or the page reads as a mix.
	assert.match(wiki, /1,000/);
	assert.match(wiki, /<meter min="0" max="100" value="4">4%<\/meter>/);
	assert.match(wiki, /180/);
	// Nothing from the combined document leaks through: the wiki lane's own
	// total is what the ledger shows, and the whole-catalog figure is gone.
	assert.doesNotMatch(wiki, /3,000/);
	const registered = statisticsHTML(payload, "catalog");
	assert.match(registered, /2,000/);
	assert.match(registered, /<meter min="0" max="100" value="45">45%<\/meter>/);
	assert.match(registered, /320/);
});

test("the snapshot timestamp stays the payload's, because all three lenses share it", () => {
	for (const name of ["all", "catalog", "wiki"]) {
		assert.match(statisticsHTML(payload, name), /datetime="2026-08-13T12:00:00Z"/);
	}
});

test("choosing a lane redraws the report from the document already in memory", async () => {
	h.backendGetJson.mockResolvedValue(payload);
	const view = viewStatistics();
	document.body.innerHTML = view.html;
	view.mount();
	await vi.waitFor(() => assert.ok(document.querySelector(".statistics-lens")));
	const wiki = document.querySelector('[data-statistics-lens-option][value="wiki"]');
	wiki.checked = true;
	wiki.dispatchEvent(new window.Event("change", { bubbles: true }));
	assert.equal(document.querySelector(".statistics-report").dataset.statisticsLens, "wiki");
	assert.match(document.body.textContent, /1,000/);
	// No second request: every lens arrived in the first response.
	assert.equal(h.backendGetJson.mock.calls.length, 1);
	// The radio the reader just used was replaced along with the rest of the
	// report, so focus is put back on its successor rather than left on <body>.
	assert.equal(document.activeElement.value, "wiki");
	assert.equal(document.querySelector("[data-statistics-lens-option]:checked").value, "wiki");
});

test("a snapshot cached before lenses existed is drawn without offering the choice", () => {
	const older = { ...payload, lenses: undefined };
	document.body.innerHTML = statisticsHTML(older);
	// Withheld rather than falling back: a "wiki" option that quietly showed
	// whole-catalog numbers would be worse than no option at all.
	assert.equal(document.querySelector(".statistics-lens"), null);
	assert.match(document.body.textContent, /3,000/);
});
