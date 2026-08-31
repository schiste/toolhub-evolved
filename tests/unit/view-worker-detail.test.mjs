// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

const h = vi.hoisted(() => ({ backendGetJson: vi.fn() }));
vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => ({
	...(await importOriginal()),
	backendGetJson: h.backendGetJson
}));

import { viewWorker } from "../../public_html/views/workers.js";

const run = (overrides = {}) => ({
	startedAt: "2026-08-14T05:00:00Z",
	finishedAt: "2026-08-14T05:01:02Z",
	durationSeconds: 62,
	succeeded: true,
	exitCode: 0,
	summary: null,
	...overrides
});

const payload = (runs, overrides = {}) => ({
	generatedAt: "2026-08-14T05:03:00Z",
	worker: {
		name: "inference-enrichment",
		description: "Ask the model about pages nobody has described.",
		schedule: "0 * * * *",
		expectedIntervalMinutes: 60,
		status: "healthy",
		lastRunAt: "2026-08-14T05:00:00Z",
		lastRunSucceeded: true,
		lastRunDurationSeconds: 62,
		lastRunExitCode: 0,
		lastSuccessAt: "2026-08-14T05:00:00Z",
		minutesSinceLastRun: 3
	},
	runs,
	retainedRuns: 50,
	definitions: { healthy: "The most recent run succeeded." },
	...overrides
});

async function render(body) {
	h.backendGetJson.mockResolvedValue(body);
	const view = viewWorker("inference-enrichment");
	document.body.innerHTML = view.html;
	view.mount();
	await new Promise((resolve) => setTimeout(resolve, 0));
	return document.body.innerHTML;
}

beforeEach(() => {
	h.backendGetJson.mockReset();
	document.body.innerHTML = "";
});

test("the view asks for the worker it was named with", async () => {
	await render(payload([]));
	assert.deepEqual(h.backendGetJson.mock.calls[0], ["/v1/workers/inference-enrichment/"]);
});

test("a worker name is escaped into the path rather than concatenated", () => {
	const view = viewWorker("a/b?c");
	document.body.innerHTML = view.html;
	h.backendGetJson.mockResolvedValue(payload([]));
	view.mount();
	assert.deepEqual(h.backendGetJson.mock.calls[0], ["/v1/workers/a%2Fb%3Fc/"]);
});

test("each run's own counts become columns of the work table", async () => {
	const html = await render(
		payload([
			run({ summary: { counts: { asked: 3973, rejected: 3475 }, spentSeconds: 2104 } }),
			run({ startedAt: "2026-08-14T04:00:00Z", summary: { counts: { asked: 120, rejected: 90 } } })
		])
	);
	assert.match(html, /counts\.asked/);
	assert.match(html, /counts\.rejected/);
	assert.match(html, /spentSeconds/);
	assert.match(html, /3,973/);
	assert.match(html, /2026-08-14 05:00:00/);
});

test("a run missing a column the others reported is blank, not zero", async () => {
	const html = await render(
		payload([
			run({ summary: { counts: { asked: 10, skipped: 2 } } }),
			run({ startedAt: "2026-08-14T04:00:00Z", summary: { counts: { asked: 8 } } })
		])
	);
	const rows = document.querySelectorAll(".worker-runs tbody tr");
	assert.equal(rows.length, 2);
	// The start time is the row header, so the cells are took, outcome, asked, skipped.
	assert.equal(rows[1].querySelectorAll("td")[3].textContent, "—");
	assert.doesNotMatch(html, /data-silent/);
});

test("a run that reported nothing is marked rather than charted as idle", async () => {
	await render(
		payload([run({ summary: null }), run({ startedAt: "2026-08-14T04:00:00Z", summary: { counts: { asked: 8 } } })])
	);
	assert.equal(document.querySelectorAll(".worker-runs tr[data-silent]").length, 1);
	assert.match(document.querySelector(".worker-section__foot").textContent, /1 of these runs reported no figures/);
});

test("coverage becomes a trend and is kept out of the per-run counts", async () => {
	const html = await render(
		payload([
			run({ summary: { counts: { asked: 40 }, coverage: { ready: 36465, rejected: 3911 } } }),
			run({
				startedAt: "2026-08-14T04:00:00Z",
				summary: { counts: { asked: 30 }, coverage: { ready: 36000, rejected: 4278 } }
			})
		])
	);
	const trend = document.querySelector(".worker-trend");
	assert.ok(trend);
	assert.match(trend.textContent, /36,465/);
	// Newest minus oldest, and the sign says which way it went.
	assert.match(trend.textContent, /\+465 over 2 runs/);
	assert.equal(trend.querySelector('[data-direction="down"]').textContent.trim(), "−367 over 2 runs");
	// A coverage total is not work this run did, so it must not be a column.
	assert.doesNotMatch(html, /coverage\.ready/);
});

test("a single run is a reading, not a trend", async () => {
	const html = await render(payload([run({ summary: { coverage: { ready: 10 } } })]));
	assert.equal(document.querySelector(".worker-trend"), null);
	assert.match(html, /Work done/);
});

test("a job that reports no coverage still gets its runs", async () => {
	const html = await render(payload([run({ summary: { fetched: 4 } }), run({ summary: { fetched: 9 } })]));
	assert.equal(document.querySelector(".worker-trend"), null);
	assert.match(html, /fetched/);
});

test("a worker with no runs at all still renders its identity", async () => {
	const html = await render(payload([]));
	assert.match(html, /inference-enrichment/);
	assert.match(html, /No runs recorded yet/);
	assert.match(html, /Every 1 h/);
});

test("the state the worker is in is explained on its own page", async () => {
	const html = await render(payload([]));
	assert.match(html, /The most recent run succeeded\./);
});

test("a failed fetch offers a retry that asks again", async () => {
	h.backendGetJson.mockRejectedValueOnce(new Error("nope"));
	const view = viewWorker("inference-enrichment");
	document.body.innerHTML = view.html;
	view.mount();
	await new Promise((resolve) => setTimeout(resolve, 0));
	assert.match(document.body.innerHTML, /This worker's history is unavailable/);

	h.backendGetJson.mockResolvedValue(payload([]));
	document.querySelector("[data-worker-retry]").click();
	await new Promise((resolve) => setTimeout(resolve, 0));
	assert.match(document.body.innerHTML, /inference-enrichment/);
});

test("the list links each worker to its own page", async () => {
	const { viewWorkers } = await import("../../public_html/views/workers.js");
	h.backendGetJson.mockResolvedValue({
		generatedAt: "2026-08-14T05:03:00Z",
		workers: [
			{
				name: "inference-enrichment",
				description: "",
				schedule: "0 * * * *",
				expectedIntervalMinutes: 60,
				status: "healthy",
				minutesSinceLastRun: 3,
				recentRuns: []
			}
		],
		counts: { healthy: 1 },
		definitions: {}
	});
	const view = viewWorkers();
	document.body.innerHTML = view.html;
	view.mount();
	await new Promise((resolve) => setTimeout(resolve, 0));
	assert.equal(
		document.querySelector(".workers-card__ident a").getAttribute("href"),
		"/workers/inference-enrichment"
	);
});
