// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { mountJsonReport } from "../lib/organisms/json-report.js";
import { t } from "../lib/core/i18n.js";
import { button } from "../lib/atoms/button.js";

const STYLESHEET = "/styles/workers.css";

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
				<h2>${esc(String(worker.name || ""))}</h2>
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
			<dl>${Object.entries(definitions)
				.sort(([a], [b]) => rank(a) - rank(b))
				.map(
					([key, value]) =>
						`<div><dt data-status="${esc(key)}">${esc(definitionLabel(key))}</dt><dd>${esc(String(value))}</dd></div>`
				)
				.join("")}</dl>
		</details>
	</div>`;
}

const loadingHTML = () =>
	`<div class="workers-loading" role="status"><span class="spinner" aria-hidden="true"></span><span>${esc(t("workers.loading", "Checking background workers"))}</span></div>`;

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
