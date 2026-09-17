// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";
import {
	FRONTEND_TIMINGS,
	FRONTEND_TIMING_LIMIT,
	PAGE_ERROR_LIMIT,
	initPageDiagnostics,
	markFrontendTiming,
	markFrontendTimingOnce,
	markPageDiagnostics,
	measureFrontendTiming,
	pageDiagnostics,
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

test("frontend timings retain only the bounded recent window", () => {
	for (let i = 0; i < FRONTEND_TIMING_LIMIT + 7; i += 1) {
		markFrontendTiming(`timing-${i}`);
	}

	assert.equal(FRONTEND_TIMINGS.length, FRONTEND_TIMING_LIMIT);
	assert.equal(FRONTEND_TIMINGS[0].name, "timing-7");
	assert.equal(FRONTEND_TIMINGS.at(-1).name, `timing-${FRONTEND_TIMING_LIMIT + 6}`);
});

test("performance timeline keeps one entry per diagnostic name", () => {
	const markName = "toolhub-evolved:diagnostic-reused-mark";
	const measureName = "toolhub-evolved:diagnostic-reused-measure";
	markFrontendTiming("diagnostic-reused-mark");
	markFrontendTiming("diagnostic-reused-mark");
	markFrontendTiming("diagnostic-reused-start");
	measureFrontendTiming("diagnostic-reused-measure", {}, "toolhub-evolved:diagnostic-reused-start");
	measureFrontendTiming("diagnostic-reused-measure", {}, "toolhub-evolved:diagnostic-reused-start");

	assert.equal(performance.getEntriesByName(markName).length, 1);
	assert.equal(performance.getEntriesByName(measureName).length, 1);
});

test("browser diagnostics retain only the bounded recent error window", () => {
	const nowSpy = vi.spyOn(Date, "now").mockReturnValue(10_000_000_000_000);
	try {
		initPageDiagnostics();
		markPageDiagnostics("/diagnostics-memory");
		for (let i = 0; i < PAGE_ERROR_LIMIT + 7; i += 1) {
			const event = new Event("error");
			Object.defineProperty(event, "message", { value: `error-${i}` });
			window.dispatchEvent(event);
		}

		const errors = pageDiagnostics().errors;
		assert.equal(errors.length, PAGE_ERROR_LIMIT);
		assert.equal(errors[0].message, "error-7");
		assert.equal(errors.at(-1).message, `error-${PAGE_ERROR_LIMIT + 6}`);
	} finally {
		nowSpy.mockRestore();
	}
});

test("browser diagnostics cap verbose Error details", () => {
	initPageDiagnostics();
	markPageDiagnostics("/diagnostics-error-size");
	const event = new Event("unhandledrejection");
	Object.defineProperty(event, "reason", { value: new Error("x".repeat(8_000)) });
	window.dispatchEvent(event);

	const errors = pageDiagnostics().errors;
	assert.equal(errors.at(-1).message.length, 4_000);
});
