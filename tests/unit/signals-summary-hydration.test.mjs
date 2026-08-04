// SPDX-License-Identifier: GPL-3.0-or-later
// Health scores have to survive the page. The in-memory summary map starts
// empty on every load, so without persistence every name reads as stale and the
// score can only ever arrive in a later repaint — which is what users saw as
// "the card renders, then the score shows up".
import assert from "node:assert/strict";
import { afterEach, beforeEach, test, vi } from "vitest";
import { installStorage } from "./_storage-setup.mjs";

const SIGNALS = "../../public_html/lib/core/signals.js";
const STORAGE_KEY = "toolhub-tool-summaries:v1";

let originalFetch;
let originalRequestIdleCallback;
beforeEach(() => {
	installStorage();
	originalFetch = globalThis.fetch;
	originalRequestIdleCallback = globalThis.requestIdleCallback;
	// Force the setTimeout fallback so idle work is drivable by fake timers.
	globalThis.requestIdleCallback = undefined;
	vi.useFakeTimers();
});
afterEach(() => {
	globalThis.fetch = originalFetch;
	globalThis.requestIdleCallback = originalRequestIdleCallback;
	vi.useRealTimers();
});

/** Run every pending idle callback and let the promises behind them settle. */
async function settleIdle() {
	await vi.advanceTimersByTimeAsync(1500);
	await Promise.resolve();
	await Promise.resolve();
}

/* Past EVOLVED_SUMMARY_TTL_MS, so a stored summary is still shown but is due
   for a background revalidation. Inside the TTL nothing is re-requested at all,
   which is the common case when navigating between routes. */
const PAST_REVALIDATION_TTL_MS = 6 * 60 * 1000;

test("a summary stored by an earlier page load is attached before any request", async () => {
	const calls = [];
	globalThis.fetch = async (url) => {
		calls.push(String(url));
		return { ok: true, json: async () => ({ results: { "stored-tool": { health: { score: 88 } } } }) };
	};

	// First page load: the summary arrives from the backend and is stored.
	vi.resetModules();
	const first = await import(SIGNALS);
	await first.attachEvolvedSummaries([{ name: "stored-tool" }]);
	await settleIdle();
	assert.equal(calls.length, 1, "expected the deferred refresh to run once");
	assert.ok(localStorage.getItem(STORAGE_KEY), "summary was not persisted for the next load");

	// Second page load: a fresh module graph, the same browser profile.
	calls.length = 0;
	vi.resetModules();
	const second = await import(SIGNALS);
	const tools = [{ name: "stored-tool" }];
	await second.attachEvolvedSummaries(tools);

	assert.equal(tools[0].evolvedSummary.health.score, 88, "score is missing from the first render");
	assert.deepEqual(calls, [], "a request ran before the score could be shown");
});

test("revalidating an unchanged summary does not repaint the route", async () => {
	const summary = { health: { score: 64, grade: "good" } };
	const calls = [];
	globalThis.fetch = async (url) => {
		calls.push(String(url));
		return { ok: true, json: async () => ({ results: { "steady-tool": summary } }) };
	};

	vi.resetModules();
	const first = await import(SIGNALS);
	await first.attachEvolvedSummaries([{ name: "steady-tool" }]);
	await settleIdle();

	const events = [];
	const onRefresh = (event) => events.push(event.detail);
	document.addEventListener("toolhub:evolved-summaries-refresh", onRefresh);
	try {
		// A later page load attaches the stored score, then revalidates in the
		// background. The backend returns the same summary, so there is nothing
		// to redraw and no event should fire.
		await vi.advanceTimersByTimeAsync(PAST_REVALIDATION_TTL_MS);
		calls.length = 0;
		vi.resetModules();
		const second = await import(SIGNALS);
		const tools = [{ name: "steady-tool" }];
		await second.attachEvolvedSummaries(tools);
		assert.equal(tools[0].evolvedSummary.health.score, 64);
		await settleIdle();

		assert.equal(calls.length, 1, "expected exactly one background revalidation");
		assert.deepEqual(events, [], "an unchanged score still triggered a rerender");
	} finally {
		document.removeEventListener("toolhub:evolved-summaries-refresh", onRefresh);
	}
});

test("a stored summary is reused without any request while it is fresh", async () => {
	const calls = [];
	globalThis.fetch = async (url) => {
		calls.push(String(url));
		return { ok: true, json: async () => ({ results: { "fresh-tool": { health: { score: 51 } } } }) };
	};
	vi.resetModules();
	const first = await import(SIGNALS);
	await first.attachEvolvedSummaries([{ name: "fresh-tool" }]);
	await settleIdle();

	// Navigating to another route moments later must not re-ask for a summary
	// the browser already has.
	calls.length = 0;
	vi.resetModules();
	const second = await import(SIGNALS);
	const tools = [{ name: "fresh-tool" }];
	await second.attachEvolvedSummaries(tools);
	await settleIdle();

	assert.equal(tools[0].evolvedSummary.health.score, 51);
	assert.deepEqual(calls, [], "re-requested a summary that was still fresh");
});

test("storing more summaries than fit keeps the most recent rather than dropping everything", async () => {
	const { toolSummaryCacheRead, toolSummaryCacheWrite } = await import("../../public_html/lib/core/store.js");
	// Real summaries run about 8KB; 120 of them are far past the budget.
	const filler = "x".repeat(8000);
	const now = Date.now();
	const cache = {};
	for (let i = 0; i < 120; i += 1) cache[`tool-${i}`] = { summary: { filler, i }, ts: now - i * 1000 };
	toolSummaryCacheWrite(cache);

	const stored = toolSummaryCacheRead();
	const names = Object.keys(stored);
	assert.ok(names.length > 0, "the whole cache was thrown away instead of trimmed");
	assert.ok(names.length < 120, "expected the oversized cache to be trimmed");
	assert.ok(localStorage.getItem(STORAGE_KEY).length <= 400000, "stored payload exceeded the budget");
	// Newest first, so the tools the reader just looked at are the ones kept.
	assert.ok(Object.hasOwn(stored, "tool-0"), "dropped the most recently seen summary");
	assert.ok(!Object.hasOwn(stored, "tool-119"), "kept the oldest summary over newer ones");
});

test("a changed score still reaches the view without a reload", async () => {
	globalThis.fetch = async () => ({
		ok: true,
		json: async () => ({ results: { "moving-tool": { health: { score: 40 } } } })
	});
	vi.resetModules();
	const first = await import(SIGNALS);
	await first.attachEvolvedSummaries([{ name: "moving-tool" }]);
	await settleIdle();

	const events = [];
	const onRefresh = (event) => events.push(event.detail);
	document.addEventListener("toolhub:evolved-summaries-refresh", onRefresh);
	try {
		globalThis.fetch = async () => ({
			ok: true,
			json: async () => ({ results: { "moving-tool": { health: { score: 77 } } } })
		});
		await vi.advanceTimersByTimeAsync(PAST_REVALIDATION_TTL_MS);
		vi.resetModules();
		const second = await import(SIGNALS);
		const tools = [{ name: "moving-tool" }];
		await second.attachEvolvedSummaries(tools);
		assert.equal(tools[0].evolvedSummary.health.score, 40, "stored score should paint first");
		await settleIdle();

		assert.deepEqual(events, [{ names: ["moving-tool"] }], "the new score never reached the view");
		await second.attachEvolvedSummaries(tools);
		assert.equal(tools[0].evolvedSummary.health.score, 77);
	} finally {
		document.removeEventListener("toolhub:evolved-summaries-refresh", onRefresh);
	}
});

test("cache-first mode paints a slow summary late rather than holding the page", async () => {
	let release;
	globalThis.fetch = async () =>
		new Promise((resolve) => {
			release = () =>
				resolve({ ok: true, json: async () => ({ results: { "slow-tool": { health: { score: 33 } } } }) });
		});

	vi.resetModules();
	const signals = await import(SIGNALS);
	const events = [];
	const onRefresh = (event) => events.push(event.detail);
	document.addEventListener("toolhub:evolved-summaries-refresh", onRefresh);
	try {
		const tools = [{ name: "slow-tool" }];
		const attached = signals.attachEvolvedSummaries(tools, { graceMs: signals.EVOLVED_SUMMARY_GRACE_MS });
		// The read has not answered, so the grace window must expire and let the
		// route render without a score.
		await vi.advanceTimersByTimeAsync(signals.EVOLVED_SUMMARY_GRACE_MS);
		await attached;
		assert.equal(tools[0].evolvedSummary, undefined, "grace window did not expire");
		assert.deepEqual(events, []);

		// The answer arrives after the page painted, so now it has to repaint.
		release();
		await settleIdle();
		assert.deepEqual(events, [{ names: ["slow-tool"] }], "a late summary never reached the view");
	} finally {
		document.removeEventListener("toolhub:evolved-summaries-refresh", onRefresh);
	}
});

test("cache-first mode does not wait when every summary is already known", async () => {
	const calls = [];
	globalThis.fetch = async (url) => {
		calls.push(String(url));
		return { ok: true, json: async () => ({ results: { "known-tool": { health: { score: 12 } } } }) };
	};
	vi.resetModules();
	const first = await import(SIGNALS);
	await first.attachEvolvedSummaries([{ name: "known-tool" }]);
	await settleIdle();

	calls.length = 0;
	vi.resetModules();
	const second = await import(SIGNALS);
	const tools = [{ name: "known-tool" }];
	// No timer advance at all: a fully cached route must not pay the grace period.
	await second.attachEvolvedSummaries(tools, { graceMs: second.EVOLVED_SUMMARY_GRACE_MS });

	assert.equal(tools[0].evolvedSummary.health.score, 12);
	assert.deepEqual(calls, [], "re-requested a summary it already had");
});

test("a card summary does not satisfy the detail page", async () => {
	const CARD = { health: { score: 55 }, maintainer: { counts: { verifiedMaintainers: 1 } } };
	const FULL = { health: { score: 55 }, maintainer: { counts: { verifiedMaintainers: 1 }, people: ["ada"] } };
	const calls = [];
	globalThis.fetch = async (url) => {
		calls.push(String(url));
		const card = String(url).includes("view=card");
		return { ok: true, json: async () => ({ results: { "two-view-tool": card ? CARD : FULL } }) };
	};

	vi.resetModules();
	const signals = await import(SIGNALS);
	// A card route populates the cache with the projected shape.
	const cardTools = [{ name: "two-view-tool" }];
	await signals.attachEvolvedSummaries(cardTools, { graceMs: signals.EVOLVED_SUMMARY_GRACE_MS });
	await settleIdle();
	assert.equal(cardTools[0].evolvedSummary.maintainer.people, undefined);
	assert.ok(calls[0].includes("view=card"));

	// The detail page needs the maintainer record, so the card entry — fresh as
	// it is — must not be treated as a hit.
	calls.length = 0;
	const detailTools = [{ name: "two-view-tool" }];
	await signals.attachEvolvedSummaries(detailTools, {
		graceMs: signals.EVOLVED_SUMMARY_GRACE_MS,
		view: signals.SUMMARY_VIEW_FULL
	});
	await settleIdle();

	assert.equal(calls.length, 1, "detail page reused a card-shaped summary");
	assert.ok(calls[0].includes("view=full"), `asked for the wrong shape: ${calls[0]}`);
	assert.deepEqual(detailTools[0].evolvedSummary.maintainer.people, ["ada"]);
});
