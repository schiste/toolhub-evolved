// SPDX-License-Identifier: GPL-3.0-or-later

const PREFIX = "toolhub-evolved";
export const APP_BOOT_START = `${PREFIX}:app-boot-start`;
/** @typedef {{ name: string, mark?: string, measure?: string, at: number, detail: Record<string, any> }} FrontendTiming */
/** @type {FrontendTiming[]} */
export const FRONTEND_TIMINGS = [];

const markedOnce = new Set();

function perf() {
	return typeof globalThis.performance === "object" ? globalThis.performance : null;
}

function now() {
	const p = perf();
	return typeof p?.now === "function" ? p.now() : Date.now();
}

/**
 * @param {string} markName
 * @param {Record<string, any>} detail
 * @param {number} [startTime]
 */
function safeMark(markName, detail, startTime) {
	const p = perf();
	if (typeof p?.mark !== "function") return;
	try {
		p.mark(markName, startTime === undefined ? { detail } : { detail, startTime });
	} catch {
		try {
			p.mark(markName);
		} catch {}
	}
}

/**
 * @param {string} measureName
 * @param {string} start
 * @param {string} end
 * @param {Record<string, any>} detail
 */
function safeMeasure(measureName, start, end, detail) {
	const p = perf();
	if (typeof p?.measure !== "function") return;
	try {
		p.measure(measureName, { start, end, detail });
	} catch {
		try {
			p.measure(measureName, start, end);
		} catch {}
	}
}

function exposeTimings() {
	try {
		if (Object.prototype.hasOwnProperty.call(globalThis, "__toolhubEvolvedTimings")) return;
		Object.defineProperty(globalThis, "__toolhubEvolvedTimings", {
			configurable: true,
			get: () => FRONTEND_TIMINGS
		});
	} catch {}
}

/**
 * @param {string} name
 * @param {Record<string, any>} [detail]
 * @param {number} [startTime]
 */
export function markFrontendTiming(name, detail = {}, startTime) {
	exposeTimings();
	const markName = `${PREFIX}:${name}`;
	const at = startTime === undefined ? now() : startTime;
	const entry = { name, mark: markName, at, detail };
	FRONTEND_TIMINGS.push(entry);
	safeMark(markName, detail, startTime);
	try {
		document.dispatchEvent(new CustomEvent("toolhub:frontend-timing", { detail: entry }));
	} catch {}
	return entry;
}

/**
 * @param {string} name
 * @param {Record<string, any>} [detail]
 * @param {number} [startTime]
 */
export function markFrontendTimingOnce(name, detail = {}, startTime) {
	if (markedOnce.has(name)) return null;
	markedOnce.add(name);
	return markFrontendTiming(name, detail, startTime);
}

/**
 * @param {string} name
 * @param {Record<string, any>} [detail]
 * @param {string} [startMark]
 */
export function measureFrontendTiming(name, detail = {}, startMark = APP_BOOT_START) {
	const endMark = `${PREFIX}:${name}:end`;
	const endedAt = now();
	safeMark(endMark, detail);
	safeMeasure(`${PREFIX}:${name}`, startMark, endMark, detail);
	const entry = { name, measure: `${PREFIX}:${name}`, at: endedAt, detail };
	FRONTEND_TIMINGS.push(entry);
	return entry;
}

export function markAppBootStart() {
	return markFrontendTimingOnce("app-boot-start", { path: location.pathname }, 0);
}

export function observeFirstContentPaint() {
	const p = perf();
	if (typeof globalThis.PerformanceObserver !== "function" || typeof p?.getEntriesByType !== "function") {
		return false;
	}
	/** @param {PerformanceEntry} entry */
	const recordPaint = (entry) => {
		if (!entry || entry.name !== "first-contentful-paint") return;
		markFrontendTimingOnce("first-content-paint", { source: "paint", entryType: entry.entryType }, entry.startTime);
	};
	for (const entry of p.getEntriesByType("paint")) recordPaint(entry);
	if (markedOnce.has("first-content-paint")) return true;
	try {
		const observer = new PerformanceObserver((list) => {
			for (const entry of list.getEntries()) recordPaint(entry);
			if (markedOnce.has("first-content-paint")) observer.disconnect();
		});
		observer.observe({ type: "paint", buffered: true });
		return true;
	} catch {
		return false;
	}
}

export function resetFrontendTimingsForTests() {
	FRONTEND_TIMINGS.length = 0;
	markedOnce.clear();
}
