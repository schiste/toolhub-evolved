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

test("run history always fills ten slots so tick width never encodes history length", async () => {
	const html = await render(
		payload([
			worker({
				name: "one-run",
				recentRuns: [{ startedAt: "2026-08-14T05:00:00Z", durationSeconds: 3, succeeded: false, exitCode: 1 }]
			})
		])
	);
	// One recorded run plus nine blanks: a lone failure must not read as a
	// wider failure than one failure in ten.
	assert.equal(html.match(/<li class="workers-runs__tick/g).length, 10);
	assert.equal(html.match(/workers-runs__tick--empty/g).length, 9);
	assert.equal(html.match(/workers-runs__tick--failed/g).length, 1);
});

test("a full history renders ten real ticks and no blanks", async () => {
	const runs = Array.from({ length: 10 }, (unused, index) => ({
		startedAt: `2026-08-14T0${index}:00:00Z`,
		durationSeconds: 5,
		succeeded: true
	}));
	const html = await render(payload([worker({ name: "busy", recentRuns: runs })]));
	assert.equal(html.match(/workers-runs__tick--ok/g).length, 10);
	assert.equal(html.match(/workers-runs__tick--empty/g), null);
});

test("a long operator note is clamped and expands in place", async () => {
	const long = "Reconcile every unresolved attribution against later evidence. ".repeat(6);
	await render(payload([worker({ description: long })]));
	const note = document.querySelector(".workers-card__note");
	const toggle = document.querySelector("[data-workers-more]");
	assert.ok(note.classList.contains("workers-card__note--clamped"));
	assert.equal(toggle.getAttribute("aria-expanded"), "false");

	toggle.click();
	assert.ok(!note.classList.contains("workers-card__note--clamped"));
	assert.equal(toggle.getAttribute("aria-expanded"), "true");
	assert.match(toggle.textContent, /Show less/);

	toggle.click();
	assert.ok(note.classList.contains("workers-card__note--clamped"));
	assert.match(toggle.textContent, /Show full note/);
});

test("a short operator note gets no toggle", async () => {
	const html = await render(payload([worker({ description: "Mirror the official catalog." })]));
	assert.doesNotMatch(html, /data-workers-more/);
	assert.doesNotMatch(html, /workers-card__note--clamped/);
});

test("methodology entries are labelled for readers rather than by machine key", async () => {
	const html = await render({
		workers: [worker()],
		counts: { healthy: 1 },
		definitions: {
			recorded: "Only executed runs are recorded.",
			stalled: "No run for 10 or more periods."
		}
	});
	assert.match(html, /What counts as a run/);
	assert.match(html, /<dt data-status="stalled">Stalled<\/dt>/);
});

test("the what-counts-as-a-run note sits outside the state grid", async () => {
	await render({
		workers: [worker()],
		counts: { healthy: 1 },
		definitions: {
			recorded: "Only executed runs are recorded.",
			stalled: "No run for 10 or more periods.",
			healthy: "The most recent run succeeded."
		}
	});
	const states = document.querySelector(".workers-method__states");
	const notes = document.querySelector(".workers-method__notes");
	// Left in the grid it takes a column and wraps to a row of its own, which
	// reads as one more state rather than as a caveat about all of them.
	assert.equal(states.querySelector('[data-status="recorded"]'), null);
	assert.equal(states.querySelectorAll("dt").length, 2);
	assert.equal(notes.querySelectorAll("dt").length, 1);
	assert.equal(notes.querySelector("dt").dataset.status, "recorded");
});

test("an all-states payload renders no empty note list", async () => {
	await render({
		workers: [worker()],
		counts: { healthy: 1 },
		definitions: { stalled: "No run for 10 or more periods." }
	});
	assert.equal(document.querySelector(".workers-method__notes"), null);
	assert.equal(document.querySelectorAll(".workers-method__states dt").length, 1);
});

test("summary counts lead with the worst status", async () => {
	const html = await render(
		payload([worker(), worker({ name: "broken", status: "failing", lastRunSucceeded: false, lastRunExitCode: 3 })])
	);
	assert.ok(html.indexOf('data-status="failing"') < html.indexOf('data-status="healthy"'));
});

test("the wait is a skeleton of the report, announced but not written out", () => {
	const view = viewWorkers();
	document.body.innerHTML = view.html;
	const region = document.querySelector(".workers-loading");
	assert.equal(region.getAttribute("role"), "status");
	assert.equal(region.querySelector(".visually-hidden").textContent, "Checking background workers");
	// The shapes stand in for the grid the report will fill, and none of them is
	// readable text: a reader sees placeholders, not the word "loading".
	const body = region.querySelector('[aria-hidden="true"]');
	assert.ok(body.classList.contains("workers-page__inner"));
	assert.equal(body.textContent.trim(), "");
	assert.equal(body.querySelectorAll(".workers-card--skeleton").length, 6);
	assert.equal(region.querySelector(".spinner"), null);
});
