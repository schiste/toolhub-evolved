// SPDX-License-Identifier: GPL-3.0-or-later

const PREFIX = "toolhub-evolved";
export const APP_BOOT_START = `${PREFIX}:app-boot-start`;
/** @typedef {{ name: string, mark?: string, measure?: string, at: number, detail: Record<string, any> }} FrontendTiming */
/** @type {FrontendTiming[]} */
export const FRONTEND_TIMINGS = [];

const markedOnce = new Set();
const PAGE_LOG_LIMIT = 80;
/** @type {Array<{level: string, message: string, at: number}>} */
const PAGE_LOGS = [];
/** @type {Array<{kind: string, message: string, at: number}>} */
const PAGE_ERRORS = [];
let pageStartedAt = Date.now();
let pagePath = typeof location === "object" ? location.pathname : "/";
let consoleCaptureReady = false;

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

/** @param {unknown} value @param {number} [depth] @returns {string} */
function diagnosticValue(value, depth = 0) {
	if (value instanceof Error) return redact(`${value.name}: ${value.message}\n${value.stack || ""}`);
	if (value === null || value === undefined) return String(value);
	if (typeof value === "string") return redact(value).slice(0, 4000);
	if (typeof value === "number" || typeof value === "boolean") return String(value);
	if (depth >= 2) {
		return "[object]";
	}
	if (Array.isArray(value)) {
		return `[${value
			.slice(0, 10)
			.map((item) => diagnosticValue(item, depth + 1))
			.join(", ")}]`;
	}
	if (typeof value === "object") {
		try {
			return redact(
				JSON.stringify(value, (_key, item) => (typeof item === "bigint" ? String(item) : item))
			).slice(0, 4000);
		} catch {
			return "[unserializable object]";
		}
	}
	return redact(String(value)).slice(0, 4000);
}

/** @param {string} value */
function redact(value) {
	return value.replaceAll(
		/(authorization|cookie|token|secret|password|csrf)(\s*[:=]\s*)[^\s,;]+/gi,
		"$1$2[redacted]"
	);
}

/** @param {string} level @param {unknown[]} args */
function recordConsole(level, args) {
	PAGE_LOGS.push({
		level,
		message: args
			.map((value) => diagnosticValue(value))
			.join(" ")
			.slice(0, 6000),
		at: Date.now()
	});
	if (PAGE_LOGS.length > PAGE_LOG_LIMIT) PAGE_LOGS.splice(0, PAGE_LOGS.length - PAGE_LOG_LIMIT);
}

/**
 * Install a bounded console/error buffer. It keeps only the current route's
 * entries when the report drawer asks for context; original console behavior is preserved.
 */
export function initPageDiagnostics() {
	if (consoleCaptureReady) return;
	consoleCaptureReady = true;
	// Diagnostics must preserve and wrap the native console methods. Going
	// through a record view is what makes that type-check: `Console` has no
	// string index signature, so the interface cannot be indexed by `level`.
	// It also keeps `no-console` quiet without a disable directive, since the
	// wrapping never touches a console member expression directly.
	const methods = /** @type {Record<string, (...args: any[]) => void>} */ (/** @type {unknown} */ (console));
	for (const level of ["debug", "info", "warn", "error"]) {
		const original = methods[level];
		if (typeof original !== "function") continue;
		methods[level] = (/** @type {any[]} */ ...args) => {
			recordConsole(level, args);
			original.apply(console, args);
		};
	}
	if (typeof window === "object") {
		window.addEventListener("error", (event) => {
			PAGE_ERRORS.push({
				kind: "error",
				message: redact(event.message || "Unknown window error").slice(0, 4000),
				at: Date.now()
			});
		});
		window.addEventListener("unhandledrejection", (event) => {
			PAGE_ERRORS.push({ kind: "unhandledrejection", message: diagnosticValue(event.reason), at: Date.now() });
		});
	}
}

/** @param {string} [path] */
export function markPageDiagnostics(path = typeof location === "object" ? location.pathname : "/") {
	pageStartedAt = Date.now();
	pagePath = path;
}

export function pageDiagnostics() {
	const recent = (/** @type {any[]} */ items) => items.filter((/** @type {any} */ item) => item.at >= pageStartedAt);
	const navigation = /** @type {PerformanceNavigationTiming | undefined} */ (
		perf()?.getEntriesByType?.("navigation")?.[0]
	);
	return {
		url: typeof location === "object" ? location.href : pagePath,
		path: pagePath,
		title: typeof document === "object" ? document.title : "",
		locale: typeof document === "object" ? document.documentElement.lang : "",
		userAgent: typeof navigator === "object" ? navigator.userAgent : "",
		platform: typeof navigator === "object" ? navigator.platform : "",
		viewport:
			typeof window === "object"
				? { width: window.innerWidth, height: window.innerHeight, devicePixelRatio: window.devicePixelRatio }
				: {},
		console: recent(PAGE_LOGS),
		errors: recent(PAGE_ERRORS),
		timings: FRONTEND_TIMINGS.slice(-30),
		navigation: navigation
			? {
					type: navigation.type,
					responseEnd: navigation.responseEnd,
					domContentLoaded: navigation.domContentLoadedEventEnd,
					load: navigation.loadEventEnd
				}
			: null
	};
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
