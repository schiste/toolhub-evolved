// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

const h = vi.hoisted(() => ({ backendGetJson: vi.fn() }));
vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => ({
	...(await importOriginal()),
	backendGetJson: h.backendGetJson
}));

import { viewWorkers } from "../../public_html/views/workers.js";

const worker = (overrides = {}) => ({
	name: "catalog-sync",
	description: "Mirror the official catalog.",
	schedule: "*/15 * * * *",
	expectedIntervalMinutes: 15,
	timeoutSeconds: 300,
	status: "healthy",
	lastRunAt: "2026-08-14T05:00:00Z",
	lastRunSucceeded: true,
	lastRunDurationSeconds: 62,
	lastRunExitCode: 0,
	lastSuccessAt: "2026-08-14T05:00:00Z",
	minutesSinceLastRun: 3,
	recentRuns: [
		{ startedAt: "2026-08-14T05:00:00Z", durationSeconds: 62, succeeded: true, exitCode: 0 },
		{ startedAt: "2026-08-14T04:45:00Z", durationSeconds: 58, succeeded: false, exitCode: 1 }
	],
	...overrides
});

const payload = (workers) => ({
	generatedAt: "2026-08-14T05:03:00Z",
	workers,
	counts: workers.reduce((all, row) => ({ ...all, [row.status]: (all[row.status] || 0) + 1 }), {}),
	definitions: { recorded: "Only executed runs are recorded." }
});

async function render(body) {
	h.backendGetJson.mockResolvedValue(body);
	const view = viewWorkers();
	document.body.innerHTML = view.html;
	view.mount();
	await new Promise((resolve) => setTimeout(resolve, 0));
	return document.body.innerHTML;
}

beforeEach(() => {
	h.backendGetJson.mockReset();
	document.body.innerHTML = "";
});

test("viewWorkers exposes its title and stylesheet", () => {
	const view = viewWorkers();
	assert.match(view.title, /Background workers/);
	assert.deepEqual(view.styles, ["/styles/workers.css"]);
	assert.match(view.html, /data-workers-root/);
});

test("a healthy fleet reports that everything is on schedule", async () => {
	const html = await render(payload([worker()]));
	assert.match(html, /All workers are running on schedule/);
	assert.match(html, /catalog-sync/);
	assert.match(html, /Mirror the official catalog/);
	assert.match(html, /Every 15 min/);
});

test("workers needing attention are counted and sorted first", async () => {
	const html = await render(
		payload([
			worker(),
			worker({ name: "stuck-job", status: "stalled", minutesSinceLastRun: 4000 }),
			worker({ name: "broken-job", status: "failing", lastRunSucceeded: false, lastRunExitCode: 7 })
		])
	);
	assert.match(html, /2 worker\(s\) need attention/);
	// The page exists to make a stopped worker impossible to miss.
	assert.ok(html.indexOf("stuck-job") < html.indexOf("catalog-sync"));
	assert.ok(html.indexOf("broken-job") < html.indexOf("catalog-sync"));
	assert.match(html, /exit 7/);
});

test("elapsed time and period are rendered at every scale", async () => {
	const html = await render(
		payload([
			worker({ name: "a", minutesSinceLastRun: 0, expectedIntervalMinutes: 1 }),
			worker({ name: "b", minutesSinceLastRun: 30, expectedIntervalMinutes: 45 }),
			worker({ name: "c", minutesSinceLastRun: 180, expectedIntervalMinutes: 360 }),
			worker({ name: "d", minutesSinceLastRun: 4320, expectedIntervalMinutes: 10080 }),
			worker({ name: "e", minutesSinceLastRun: null, expectedIntervalMinutes: 0, status: "unknown" })
		])
	);
	assert.match(html, /just now/);
	assert.match(html, /30 min ago/);
	assert.match(html, /3 h ago/);
	assert.match(html, /3 d ago/);
	assert.match(html, /Every minute/);
	assert.match(html, /Every 45 min/);
	assert.match(html, /Every 6 h/);
	assert.match(html, /Every 7 d/);
	assert.match(html, /Irregular/);
});

test("a worker with no recorded run says so instead of implying failure", async () => {
	const html = await render(
		payload([
			worker({
				name: "never-ran",
				status: "unknown",
				minutesSinceLastRun: null,
				lastRunSucceeded: null,
				lastRunDurationSeconds: null,
				recentRuns: []
			})
		])
	);
	assert.match(html, /No runs recorded/);
	assert.match(html, /No runs recorded yet/);
});

test("run durations render in seconds and minutes", async () => {
	const html = await render(
		payload([
			worker({ name: "quick", lastRunDurationSeconds: 4 }),
			worker({ name: "slow", lastRunDurationSeconds: 240 })
		])
	);
	assert.match(html, /4s/);
	assert.match(html, /4m/);
});

test("each recent run is a labelled tick so failures are visible", async () => {
	const html = await render(payload([worker()]));
	assert.match(html, /workers-runs__tick--ok/);
	assert.match(html, /workers-runs__tick--failed/);
	assert.match(html, /Succeeded/);
	assert.match(html, /Failed/);
});

test("a failed load offers a retry that reloads", async () => {
	h.backendGetJson.mockRejectedValueOnce(new Error("offline")).mockResolvedValue(payload([worker()]));
	const view = viewWorkers();
	document.body.innerHTML = view.html;
	view.mount();
	await new Promise((resolve) => setTimeout(resolve, 0));
	assert.match(document.body.innerHTML, /temporarily unavailable/);

	document.querySelector("[data-workers-retry]").click();
	await new Promise((resolve) => setTimeout(resolve, 0));
	assert.match(document.body.innerHTML, /catalog-sync/);
});

test("a malformed payload renders without throwing", async () => {
	const html = await render({});
	assert.match(html, /Background workers/);
	assert.match(html, /All workers are running on schedule/);
});

test("mounting without the root element is a no-op", () => {
	const view = viewWorkers();
	document.body.innerHTML = "<div></div>";
	view.mount();
	assert.equal(h.backendGetJson.mock.calls.length, 0);
});
