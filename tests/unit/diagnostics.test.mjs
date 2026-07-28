// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test } from "vitest";
import {
	FRONTEND_TIMINGS,
	markFrontendTiming,
	markFrontendTimingOnce,
	measureFrontendTiming,
	resetFrontendTimingsForTests
} from "../../public_html/lib/core/diagnostics.js";

beforeEach(() => {
	resetFrontendTimingsForTests();
});

test("markFrontendTiming records a Performance mark and exposes the timing array", () => {
	const eventDetails = [];
	document.addEventListener("toolhub:frontend-timing", (event) => eventDetails.push(event.detail), { once: true });
	const entry = markFrontendTiming("probe", { url: "/api/probe/" });
	assert.equal(entry.name, "probe");
	assert.equal(FRONTEND_TIMINGS.length, 1);
	assert.equal(globalThis.__toolhubEvolvedTimings, FRONTEND_TIMINGS);
	assert.equal(eventDetails[0].name, "probe");
	assert.equal(performance.getEntriesByName("toolhub-evolved:probe").length > 0, true);
});

test("markFrontendTimingOnce records one mark per timing name", () => {
	assert.ok(markFrontendTimingOnce("first-api-response", { status: 200 }));
	assert.equal(markFrontendTimingOnce("first-api-response", { status: 304 }), null);
	assert.equal(FRONTEND_TIMINGS.length, 1);
	assert.equal(FRONTEND_TIMINGS[0].detail.status, 200);
});

test("measureFrontendTiming records a named measure entry", () => {
	markFrontendTiming("start");
	const entry = measureFrontendTiming("app-boot", { path: "/" }, "toolhub-evolved:start");
	assert.equal(entry.name, "app-boot");
	assert.equal(FRONTEND_TIMINGS.at(-1).name, "app-boot");
	assert.equal(performance.getEntriesByName("toolhub-evolved:app-boot").length > 0, true);
});
