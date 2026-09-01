// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { mountJsonReport } from "../lib/organisms/json-report.js";
import { t } from "../lib/core/i18n.js";
import { formatCount as count } from "../lib/core/util.js";
import { button } from "../lib/atoms/button.js";
import { loadingRegion, skeletonLine } from "../lib/molecules/skeleton.js";

export const STYLESHEET = "/styles/workers.css";

const MINUTES_PER_HOUR = 60;
const MINUTES_PER_DAY = 1440;
const SECONDS_PER_MINUTE = 60;

// The backend keeps the last ten executed runs per worker. Every card spends
// that same width on the same ten slots even when fewer have been recorded, so
// a single failed run cannot read as a wider failure than one failure in ten.
const RUN_SLOTS = 10;

// Descriptions are operator notes and range from one line to a page of prose.
// Past roughly three lines a card stops being scannable, so longer notes are
// clamped behind a toggle. The threshold is deliberately a little above three
// rendered lines so short notes never get a control that does nothing.
const NOTE_CLAMP_CHARS = 140;

// Anything not healthy sorts first: this page exists to make a stopped worker
// impossible to miss, so it must never be buried below the working ones.
const STATUS_ORDER = { stalled: 0, failing: 1, late: 2, unknown: 3, healthy: 4 };

/** @param {string} status */
function rank(status) {
	return STATUS_ORDER[/** @type {keyof typeof STATUS_ORDER} */ (status)] ?? 9;
}

/** @param {string} status */
function statusLabel(status) {
	const labels = {
		healthy: t("workers.statusHealthy", "Running"),
		late: t("workers.statusLate", "Late"),
		stalled: t("workers.statusStalled", "Stalled"),
		failing: t("workers.statusFailing", "Failing"),
		unknown: t("workers.statusUnknown", "No runs recorded")
	};
	return labels[/** @type {keyof typeof labels} */ (status)] || labels.unknown;
}

/**
 * Human label for a methodology key.
 *
 * The backend documents these under machine keys, and `recorded` is a note
 * about what counts as a run rather than a state, so neither can be shown raw.
 *
 * @param {string} key
 */
function definitionLabel(key) {
	const labels = {
		healthy: t("workers.statusHealthy", "Running"),
		late: t("workers.statusLate", "Late"),
		stalled: t("workers.statusStalled", "Stalled"),
		failing: t("workers.statusFailing", "Failing"),
		unknown: t("workers.statusUnknown", "No runs recorded"),
		recorded: t("workers.definitionRecorded", "What counts as a run")
	};
	return labels[/** @type {keyof typeof labels} */ (key)] || key;
}

/**
 * One term/definition pair. `data-status` stays on every row, note or not, so
 * the markup keeps naming the backend key it came from.
 *
 * @param {[string, unknown]} entry
 */
function definitionRow([key, value]) {
	return `<div><dt data-status="${esc(key)}">${esc(definitionLabel(key))}</dt><dd>${esc(String(value))}</dd></div>`;
}

/** @param {unknown} value */
function elapsed(value) {
	const minutes = Number(value);
	if (!Number.isFinite(minutes)) return t("workers.never", "never");
	if (minutes < 1) return t("workers.justNow", "just now");
	if (minutes < MINUTES_PER_HOUR) {
		return t("workers.minutesAgo", "$1 min ago", Math.round(minutes));
	}
	if (minutes < MINUTES_PER_DAY) {
		return t("workers.hoursAgo", "$1 h ago", Math.round(minutes / MINUTES_PER_HOUR));
	}
	return t("workers.daysAgo", "$1 d ago", Math.round(minutes / MINUTES_PER_DAY));
}

/** @param {unknown} value */
function period(value) {
	const minutes = Number(value);
	if (!Number.isFinite(minutes) || minutes <= 0) return t("workers.periodUnknown", "Irregular");
	if (minutes === 1) return t("workers.everyMinute", "Every minute");
	if (minutes < MINUTES_PER_HOUR) {
		return t("workers.everyMinutes", "Every $1 min", minutes);
	}
	if (minutes < MINUTES_PER_DAY) {
		return t("workers.everyHours", "Every $1 h", Math.round(minutes / MINUTES_PER_HOUR));
	}
	return t("workers.everyDays", "Every $1 d", Math.round(minutes / MINUTES_PER_DAY));
}

/** @param {unknown} value */
function duration(value) {
	const seconds = Number(value);
	if (!Number.isFinite(seconds)) return "";
	if (seconds < SECONDS_PER_MINUTE) return t("workers.seconds", "$1s", seconds);
	return t("workers.minutes", "$1m", Math.round(seconds / SECONDS_PER_MINUTE));
}

/** @param {Array<{ startedAt?: string, durationSeconds?: number, succeeded?: boolean }>} runs */
function sparkline(runs) {
	if (!Array.isArray(runs) || runs.length === 0) {
		return `<p class="workers-runs__empty">${esc(t("workers.noRuns", "No runs recorded yet."))}</p>`;
	}
	// Oldest first reads left-to-right like a timeline.
	const ordered = [...runs].slice(0, RUN_SLOTS).reverse();
	// Blanks pad the older side so the newest run is always the rightmost slot.
	// They carry no data, so they stay out of the accessibility tree.
	const blanks = Array.from(
		{ length: RUN_SLOTS - ordered.length },
		() => `<li class="workers-runs__tick workers-runs__tick--empty" aria-hidden="true"></li>`
	).join("");
	const ticks = ordered
		.map((run) => {
			const ok = run.succeeded !== false;
			const label = `${ok ? t("workers.runOk", "Succeeded") : t("workers.runFailed", "Failed")} · ${String(run.startedAt || "")}`;
			return `<li class="workers-runs__tick workers-runs__tick--${ok ? "ok" : "failed"}" title="${esc(label)}"><span class="visually-hidden">${esc(label)}</span></li>`;
		})
		.join("");
	return `<div class="workers-runs__group">
		<p class="workers-runs__caption">${esc(t("workers.runsCaption", "Last $1 runs", RUN_SLOTS))}</p>
		<ol class="workers-runs" aria-label="${esc(t("workers.recentRuns", "Recent runs"))}">${blanks}${ticks}</ol>
	</div>`;
}

/** @param {Record<string, any>} worker */
function note(worker) {
	const text = String(worker.description || "");
	const clamped = text.length > NOTE_CLAMP_CHARS;
	const toggle = clamped
		? `<button type="button" class="workers-card__more" data-workers-more aria-expanded="false">${esc(
				t("workers.showFull", "Show full note")
			)}</button>`
		: "";
	return `<div class="workers-card__note${clamped ? " workers-card__note--clamped" : ""}">
		<p class="workers-card__description">${esc(text)}</p>
		${toggle}
	</div>`;
}

/** @param {Record<string, any>} worker */
function workerRow(worker) {
	const status = String(worker.status || "unknown");
	const failed = worker.lastRunSucceeded === false;
	return `<article class="workers-card workers-card--${esc(status)}">
		<header class="workers-card__head">
			<div class="workers-card__ident">
				<h2><a href="/workers/${esc(encodeURIComponent(String(worker.name || "")))}">${esc(String(worker.name || ""))}</a></h2>
				<p class="workers-card__schedule"><code>${esc(worker.continuous ? "continuous" : String(worker.schedule || ""))}</code> <span class="workers-card__period">${esc(period(worker.expectedIntervalMinutes))}</span></p>
			</div>
			<p class="workers-card__status" data-status="${esc(status)}">${esc(statusLabel(status))}</p>
		</header>
		${note(worker)}
		<dl class="workers-card__facts">
			<div><dt>${esc(t("workers.lastRun", "Last run"))}</dt><dd>${esc(elapsed(worker.minutesSinceLastRun))}</dd></div>
			<div><dt>${esc(t("workers.lastDuration", "Took"))}</dt><dd>${esc(duration(worker.lastRunDurationSeconds) || "—")}</dd></div>
			<div><dt>${esc(t("workers.outcome", "Outcome"))}</dt><dd>${esc(
				worker.lastRunSucceeded === null || worker.lastRunSucceeded === undefined
					? "—"
					: failed
						? t("workers.exitCode", "exit $1", String(worker.lastRunExitCode))
						: t("workers.runOk", "Succeeded")
			)}</dd></div>
		</dl>
		${sparkline(worker.recentRuns)}
	</article>`;
}

/** @param {Record<string, any>} payload */
function workersHTML(payload) {
	const workers = Array.isArray(payload?.workers) ? payload.workers : [];
	const counts = payload?.counts && typeof payload.counts === "object" ? payload.counts : {};
	const definitions = payload?.definitions && typeof payload.definitions === "object" ? payload.definitions : {};
	const sorted = [...workers].sort(
		(a, b) => rank(String(a.status)) - rank(String(b.status)) || String(a.name).localeCompare(String(b.name))
	);
	const attention = sorted.filter((worker) => worker.status === "stalled" || worker.status === "failing").length;
	// Counts arrive keyed by status, so their order is the backend's object
	// order. Sorting by severity keeps the worst number leftmost.
	const summary = Object.entries(counts).sort(([a], [b]) => rank(a) - rank(b));
	// The backend documents states and non-states in one dict. Only the states
	// belong in the grid: `recorded` is a caveat about what a run is at all, and
	// left in the grid it wraps onto a row of its own and reads as a sixth state.
	const definitionEntries = Object.entries(definitions);
	const states = definitionEntries.filter(([key]) => key in STATUS_ORDER).sort(([a], [b]) => rank(a) - rank(b));
	const notes = definitionEntries.filter(([key]) => !(key in STATUS_ORDER));
	return `<div class="workers-page__inner">
		<header class="workers-hero">
			<p class="workers-hero__eyebrow">${esc(t("workers.eyebrow", "Evolved data"))}</p>
			<h1>${esc(t("workers.title", "Background workers"))}</h1>
			<p class="workers-hero__lead">${esc(t("workers.lead", "Every scheduled job that fetches, cleans, reconciles, or publishes data, with when it last actually ran."))}</p>
			<div class="workers-hero__state">
				${
					attention > 0
						? `<p class="workers-hero__alert" role="status">${esc(
								t("workers.attention", "$1 worker(s) need attention.", attention)
							)}</p>`
						: `<p class="workers-hero__ok" role="status">${esc(t("workers.allHealthy", "All workers are running on schedule."))}</p>`
				}
				<ul class="workers-summary">${summary
					.map(
						([status, value]) =>
							`<li data-status="${esc(status)}"><strong>${esc(String(value))}</strong><span>${esc(statusLabel(status))}</span></li>`
					)
					.join("")}</ul>
			</div>
		</header>
		<div class="workers-grid">${sorted.map((worker) => workerRow(worker)).join("")}</div>
		<details class="workers-method">
			<summary>${esc(t("workers.methodTitle", "How these states are decided"))}</summary>
			<dl class="workers-method__states">${states.map((entry) => definitionRow(entry)).join("")}</dl>
			${
				notes.length > 0
					? `<dl class="workers-method__notes">${notes.map((entry) => definitionRow(entry)).join("")}</dl>`
					: ""
			}
		</details>
	</div>`;
}

// Enough cards to fill the first screen of the grid without pretending to know
// how many jobs the backend will report.
const SKELETON_CARDS = 6;

function workerCardSkeleton() {
	const fact = `<div><dt>${skeletonLine("skeleton--w-lg")}</dt><dd>${skeletonLine("skeleton--w-md")}</dd></div>`;
	return `<article class="workers-card workers-card--skeleton">
		<header class="workers-card__head">
			<div class="workers-card__ident">${skeletonLine("skeleton--w-lg")}${skeletonLine("skeleton--w-md")}</div>
			${skeletonLine("skeleton--badge")}
		</header>
		<dl class="workers-card__facts">${fact.repeat(3)}</dl>
	</article>`;
}

const loadingHTML = () =>
	loadingRegion({
		label: t("workers.loading", "Checking background workers"),
		className: "workers-loading",
		bodyClass: "workers-page__inner",
		body: `<header class="workers-hero">
			${skeletonLine("skeleton--w-xs")}
			${skeletonLine("skeleton-page__title skeleton--w-md")}
			${skeletonLine("skeleton-page__intro skeleton--w-xl")}
		</header>
		<div class="workers-grid">${workerCardSkeleton().repeat(SKELETON_CARDS)}</div>`
	});

const errorHTML = () =>
	`<div class="workers-error" role="alert"><h1>${esc(t("workers.errorTitle", "Worker status is temporarily unavailable"))}</h1><p>${esc(t("workers.errorBody", "The background job report could not be loaded."))}</p>${button(t("workers.retry", "Try again"), { attrs: "data-workers-retry" })}</div>`;

/**
 * Expand or re-clamp one operator note.
 *
 * Delegated from the view root, which survives every re-render, so the toggle
 * keeps working after a retry replaces the card markup.
 *
 * @param {Event} event
 */
function onNoteToggle(event) {
	if (!(event.target instanceof Element)) return;
	const toggle = event.target.closest("[data-workers-more]");
	if (!toggle) return;
	const wrap = toggle.closest(".workers-card__note");
	if (!wrap) return;
	const clamped = wrap.classList.toggle("workers-card__note--clamped");
	toggle.setAttribute("aria-expanded", String(!clamped));
	toggle.textContent = clamped ? t("workers.showFull", "Show full note") : t("workers.showLess", "Show less");
}

export function viewWorkers() {
	const mountReport = mountJsonReport({
		name: "workers",
		endpoint: "/v1/workers/",
		render: workersHTML,
		renderLoading: loadingHTML,
		renderError: errorHTML
	});
	return {
		title: t("workers.docTitle", "Background workers — Toolhub"),
		html: `<div class="container page workers-page" data-workers-root>${loadingHTML()}</div>`,
		mount() {
			mountReport();
			document.querySelector("[data-workers-root]")?.addEventListener("click", onNoteToggle);
		},
		styles: [STYLESHEET]
	};
}

// The one summary group whose numbers describe the corpus rather than the run.
// Nothing in a number says which it is: 3,911 rejected pages is a total that
// only moves when the world does, while 3,973 asked is what this run alone did,
// and diffing them would be nonsense the other way round. Only the job knows,
// and `coverage` is how the jobs here say it. A job that reports none gets the
// run table and no trend, which is accurate rather than degraded.
const COVERAGE_GROUP = "coverage";

// A trend needs two points that both said something; one run is a reading, not
// a direction.
const TREND_MIN_POINTS = 2;

const SPARK_WIDTH = 120;
const SPARK_HEIGHT = 28;

/**
 * Split one run's summary into what it did, where things now stand, and prose.
 *
 * Flattened one level deep: jobs group their numbers (`counts`, `projection`),
 * and a page that only read top-level scalars would show almost nothing.
 *
 * @param {Record<string, any> | null | undefined} summary
 * @returns {{ work: Array<[string, number]>, coverage: Array<[string, number]>, notes: Array<[string, string]> }}
 */
function splitSummary(summary) {
	/** @type {Array<[string, number]>} */ const work = [];
	/** @type {Array<[string, number]>} */ const coverage = [];
	/** @type {Array<[string, string]>} */ const notes = [];
	if (!summary || typeof summary !== "object") return { work, coverage, notes };
	for (const [key, value] of Object.entries(summary)) {
		if (typeof value === "number" && Number.isFinite(value)) {
			work.push([key, value]);
		} else if (typeof value === "string" || typeof value === "boolean") {
			notes.push([key, String(value)]);
		} else if (value && typeof value === "object" && !Array.isArray(value)) {
			for (const [inner, nested] of Object.entries(value)) {
				if (typeof nested !== "number" || !Number.isFinite(nested)) continue;
				if (key === COVERAGE_GROUP) coverage.push([inner, nested]);
				else work.push([`${key}.${inner}`, nested]);
			}
		}
	}
	return { work, coverage, notes };
}

/**
 * Column order for the work table: newest run's keys first, then any older key.
 *
 * Ordering by the newest run rather than alphabetically keeps the columns in
 * the shape the job currently reports; a metric it has stopped reporting still
 * gets a column, because its disappearance is itself news.
 *
 * @param {Array<{ work: Array<[string, number]> }>} runs newest first
 */
function workColumns(runs) {
	/** @type {string[]} */ const columns = [];
	for (const run of runs) {
		for (const [key] of run.work) if (!columns.includes(key)) columns.push(key);
	}
	return columns;
}

/**
 * A minimal line of one metric over time, oldest point leftmost.
 *
 * @param {number[]} values oldest first
 */
function trendLine(values) {
	const low = Math.min(...values);
	const high = Math.max(...values);
	const span = high - low;
	const step = values.length > 1 ? SPARK_WIDTH / (values.length - 1) : 0;
	const points = values
		.map((value, index) => {
			// A flat series has no span to scale by; drawing it through the
			// middle says "unchanged", where dividing by zero says nothing.
			const y = span === 0 ? SPARK_HEIGHT / 2 : SPARK_HEIGHT - ((value - low) / span) * SPARK_HEIGHT;
			return `${(index * step).toFixed(1)},${y.toFixed(1)}`;
		})
		.join(" ");
	return `<svg class="worker-trend__spark" viewBox="0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}" preserveAspectRatio="none" aria-hidden="true"><polyline points="${points}" /></svg>`;
}

/**
 * How far each coverage metric has moved across the runs still retained.
 *
 * Runs that reported nothing are skipped rather than plotted at zero: a run
 * killed before it printed did not say the corpus was empty, and a chart that
 * dips to zero every time a job is stopped is worse than no chart.
 *
 * @param {Array<{ coverage: Array<[string, number]> }>} runs newest first
 */
function trendHTML(runs) {
	/** @type {Map<string, number[]>} */ const series = new Map();
	// Oldest first so each series reads left to right in time.
	for (const run of [...runs].reverse()) {
		for (const [key, value] of run.coverage) {
			const points = series.get(key) || [];
			points.push(value);
			series.set(key, points);
		}
	}
	const usable = [...series.entries()].filter(([, points]) => points.length >= TREND_MIN_POINTS);
	if (usable.length === 0) return "";
	const rows = usable
		.map(([key, points]) => {
			const first = points[0];
			const last = points[points.length - 1];
			const delta = last - first;
			const direction = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
			const change =
				delta === 0
					? t("worker.trendFlat", "no change over $1 runs", points.length)
					: t(
							"worker.trendChange",
							"$1$2 over $3 runs",
							delta > 0 ? "+" : "−",
							count(Math.abs(delta)),
							points.length
						);
			return `<div class="worker-trend__row">
		<dt>${esc(key)}</dt>
		<dd>
			<span class="worker-trend__now">${esc(count(last))}</span>
			<span class="worker-trend__delta" data-direction="${esc(direction)}">${esc(change)}</span>
			${trendLine(points)}
		</dd>
	</div>`;
		})
		.join("");
	return `<section class="worker-section">
	<h2>${esc(t("worker.trendTitle", "Progression"))}</h2>
	<p class="worker-section__lead">${esc(t("worker.trendLead", "How much of this worker's corpus is covered, across the runs still kept."))}</p>
	<dl class="worker-trend">${rows}</dl>
</section>`;
}

/**
 * Every retained run, with what it reported doing.
 *
 * @param {Array<{ startedAt: string, durationSeconds: number, succeeded: boolean, exitCode: number, reported: boolean, work: Array<[string, number]> }>} runs newest first
 */
function runsHTML(runs) {
	const heading = `<h2>${esc(t("worker.runsTitle", "Work done"))}</h2>`;
	if (runs.length === 0) {
		return `<section class="worker-section">${heading}<p class="workers-runs__empty">${esc(t("workers.noRuns", "No runs recorded yet."))}</p></section>`;
	}
	const columns = workColumns(runs);
	const body = runs
		.map((run) => {
			const values = new Map(run.work);
			// An em dash for a run that reported other numbers but not this one.
			// A run that reported none is marked on the row instead, so the two
			// never have to be told apart cell by cell.
			const cells = columns
				.map(
					(key) => `<td class="worker-runs__num">${esc(values.has(key) ? count(values.get(key)) : "—")}</td>`
				)
				.join("");
			const outcome = run.succeeded
				? t("workers.runOk", "Succeeded")
				: t("workers.exitCode", "exit $1", String(run.exitCode));
			return `<tr data-outcome="${run.succeeded ? "ok" : "failed"}"${run.reported ? "" : ' data-silent="true"'}>
		<th scope="row"><time datetime="${esc(run.startedAt)}">${esc(run.startedAt.replace("T", " ").replace("Z", ""))}</time></th>
		<td>${esc(duration(run.durationSeconds) || "—")}</td>
		<td>${esc(outcome)}</td>
		${cells}
	</tr>`;
		})
		.join("");
	// A run that said nothing is not a run that did nothing, and the table has
	// to say which it is, or every killed run reads as an idle one.
	const silent = runs.filter((run) => !run.reported).length;
	return `<section class="worker-section">
	${heading}
	<div class="worker-runs__scroll">
		<table class="worker-runs">
			<thead><tr>
				<th scope="col">${esc(t("worker.colStarted", "Started"))}</th>
				<th scope="col">${esc(t("workers.lastDuration", "Took"))}</th>
				<th scope="col">${esc(t("workers.outcome", "Outcome"))}</th>
				${columns.map((key) => `<th scope="col">${esc(key)}</th>`).join("")}
			</tr></thead>
			<tbody>${body}</tbody>
		</table>
	</div>
	${
		silent > 0
			? `<p class="worker-section__foot">${esc(t("worker.silentRuns", "$1 of these runs reported no figures: they either predate this record or were stopped before they could.", silent))}</p>`
			: ""
	}
</section>`;
}

/** @param {Record<string, any>} payload */
function workerHTML(payload) {
	const worker = payload?.worker && typeof payload.worker === "object" ? payload.worker : {};
	const status = String(worker.status || "unknown");
	const rawRuns = Array.isArray(payload?.runs) ? payload.runs : [];
	const runs = rawRuns.map((run) => ({
		startedAt: String(run?.startedAt || ""),
		durationSeconds: Number(run?.durationSeconds) || 0,
		succeeded: run?.succeeded !== false,
		exitCode: Number(run?.exitCode) || 0,
		// Boolean of the payload's null, not of an empty object: the backend
		// keeps "did not say" and "said nothing happened" apart, and so must this.
		reported: Boolean(run?.summary),
		...splitSummary(run?.summary)
	}));
	const definitions = payload?.definitions && typeof payload.definitions === "object" ? payload.definitions : {};
	const explanation = definitions[status];
	return `<div class="workers-page__inner worker-page__inner">
	<nav class="worker-back"><a href="/workers">${esc(t("worker.backToAll", "← All workers"))}</a></nav>
	<header class="workers-hero worker-hero">
		<p class="workers-hero__eyebrow">${esc(t("workers.eyebrow", "Evolved data"))}</p>
		<h1>${esc(String(worker.name || ""))}</h1>
		<p class="workers-hero__lead">${esc(String(worker.description || ""))}</p>
		<p class="workers-card__schedule"><code>${esc(worker.continuous ? "continuous" : String(worker.schedule || ""))}</code> <span class="workers-card__period">${esc(period(worker.expectedIntervalMinutes))}</span></p>
		<p class="workers-card__status worker-hero__status" data-status="${esc(status)}">${esc(statusLabel(status))}</p>
		${explanation ? `<p class="worker-hero__why">${esc(String(explanation))}</p>` : ""}
	</header>
	<dl class="workers-card__facts worker-facts">
		<div><dt>${esc(t("workers.lastRun", "Last run"))}</dt><dd>${esc(elapsed(worker.minutesSinceLastRun))}</dd></div>
		<div><dt>${esc(t("workers.lastDuration", "Took"))}</dt><dd>${esc(duration(worker.lastRunDurationSeconds) || "—")}</dd></div>
		<div><dt>${esc(t("worker.lastSuccess", "Last success"))}</dt><dd>${esc(String(worker.lastSuccessAt || "") || "—")}</dd></div>
		<div><dt>${esc(t("worker.retained", "Runs kept"))}</dt><dd>${esc(`${runs.length} / ${count(payload?.retainedRuns)}`)}</dd></div>
	</dl>
	${trendHTML(runs)}
	${runsHTML(runs)}
</div>`;
}

const workerLoadingHTML = () =>
	loadingRegion({
		label: t("worker.loading", "Loading this worker's history"),
		className: "workers-loading",
		bodyClass: "workers-page__inner",
		body: `<header class="workers-hero">
		${skeletonLine("skeleton--w-xs")}
		${skeletonLine("skeleton-page__title skeleton--w-md")}
		${skeletonLine("skeleton-page__intro skeleton--w-xl")}
	</header>
	<dl class="workers-card__facts worker-facts">${`<div><dt>${skeletonLine("skeleton--w-lg")}</dt><dd>${skeletonLine("skeleton--w-md")}</dd></div>`.repeat(4)}</dl>`
	});

const workerErrorHTML = () =>
	`<div class="workers-error" role="alert"><h1>${esc(t("worker.errorTitle", "This worker's history is unavailable"))}</h1><p>${esc(t("worker.errorBody", "The run history could not be loaded. It may not be a worker this site knows about."))}</p>${button(t("workers.retry", "Try again"), { attrs: "data-worker-retry" })}</div>`;

/**
 * One worker's own page: every run still retained, and what each one did.
 *
 * Shares this module rather than getting its own, because it shares nearly all
 * of its vocabulary -- status, schedule, elapsed time, duration are the same
 * words on both pages, and two copies would eventually disagree about them.
 *
 * @param {string} name
 */
export function viewWorker(name) {
	const mountReport = mountJsonReport({
		name: "worker",
		endpoint: `/v1/workers/${encodeURIComponent(name)}/`,
		render: workerHTML,
		renderLoading: workerLoadingHTML,
		renderError: workerErrorHTML
	});
	return {
		title: t("worker.docTitle", "$1 — Background workers — Toolhub", name),
		html: `<div class="container page workers-page worker-page" data-worker-root>${workerLoadingHTML()}</div>`,
		mount: mountReport,
		styles: [STYLESHEET]
	};
}
