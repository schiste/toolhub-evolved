// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { mountJsonReport } from "../lib/organisms/json-report.js";
import { t } from "../lib/core/i18n.js";
import { button } from "../lib/atoms/button.js";

const STYLESHEET = "/styles/workers.css";

const MINUTES_PER_HOUR = 60;
const MINUTES_PER_DAY = 1440;
const SECONDS_PER_MINUTE = 60;

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
	const ordered = [...runs].reverse();
	return `<ol class="workers-runs" aria-label="${esc(t("workers.recentRuns", "Recent runs"))}">${ordered
		.map((run) => {
			const ok = run.succeeded !== false;
			const label = `${ok ? t("workers.runOk", "Succeeded") : t("workers.runFailed", "Failed")} · ${String(run.startedAt || "")}`;
			return `<li class="workers-runs__tick workers-runs__tick--${ok ? "ok" : "failed"}" title="${esc(label)}"><span class="visually-hidden">${esc(label)}</span></li>`;
		})
		.join("")}</ol>`;
}

/** @param {Record<string, any>} worker */
function workerRow(worker) {
	const status = String(worker.status || "unknown");
	const failed = worker.lastRunSucceeded === false;
	return `<article class="workers-card workers-card--${esc(status)}">
		<header class="workers-card__head">
			<div>
				<h2>${esc(String(worker.name || ""))}</h2>
				<p class="workers-card__schedule"><code>${esc(String(worker.schedule || ""))}</code> · ${esc(period(worker.expectedIntervalMinutes))}</p>
			</div>
			<p class="workers-card__status" data-status="${esc(status)}">${esc(statusLabel(status))}</p>
		</header>
		<p class="workers-card__description">${esc(String(worker.description || ""))}</p>
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
	// Anything not healthy first: this page exists to make a stopped worker
	// impossible to miss, so it must never be buried below the working ones.
	const order = { stalled: 0, failing: 1, late: 2, unknown: 3, healthy: 4 };
	const sorted = [...workers].sort(
		(a, b) =>
			(order[/** @type {keyof typeof order} */ (a.status)] ?? 9) -
				(order[/** @type {keyof typeof order} */ (b.status)] ?? 9) ||
			String(a.name).localeCompare(String(b.name))
	);
	const attention = sorted.filter((worker) => worker.status === "stalled" || worker.status === "failing").length;
	return `<div class="workers-page__inner">
		<header class="workers-hero">
			<p class="workers-hero__eyebrow">${esc(t("workers.eyebrow", "Evolved data"))}</p>
			<h1>${esc(t("workers.title", "Background workers"))}</h1>
			<p>${esc(t("workers.lead", "Every scheduled job that fetches, cleans, reconciles, or publishes data, with when it last actually ran."))}</p>
			${
				attention > 0
					? `<p class="workers-hero__alert" role="status">${esc(
							t("workers.attention", "$1 worker(s) need attention.", attention)
						)}</p>`
					: `<p class="workers-hero__ok" role="status">${esc(t("workers.allHealthy", "All workers are running on schedule."))}</p>`
			}
			<ul class="workers-summary">${Object.entries(counts)
				.map(
					([status, value]) =>
						`<li data-status="${esc(status)}"><strong>${esc(String(value))}</strong><span>${esc(statusLabel(status))}</span></li>`
				)
				.join("")}</ul>
		</header>
		<div class="workers-grid">${sorted.map((worker) => workerRow(worker)).join("")}</div>
		<details class="workers-method">
			<summary>${esc(t("workers.methodTitle", "How these states are decided"))}</summary>
			<dl>${Object.entries(definitions)
				.map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(String(value))}</dd></div>`)
				.join("")}</dl>
		</details>
	</div>`;
}

const loadingHTML = () =>
	`<div class="workers-loading" role="status"><span class="spinner" aria-hidden="true"></span><span>${esc(t("workers.loading", "Checking background workers"))}</span></div>`;

const errorHTML = () =>
	`<div class="workers-error" role="alert"><h1>${esc(t("workers.errorTitle", "Worker status is temporarily unavailable"))}</h1><p>${esc(t("workers.errorBody", "The background job report could not be loaded."))}</p>${button(t("workers.retry", "Try again"), { attrs: "data-workers-retry" })}</div>`;

export function viewWorkers() {
	return {
		title: t("workers.docTitle", "Background workers — Toolhub"),
		html: `<div class="container page workers-page" data-workers-root>${loadingHTML()}</div>`,
		mount: mountJsonReport({
			name: "workers",
			endpoint: "/v1/workers/",
			render: workersHTML,
			renderLoading: loadingHTML,
			renderError: errorHTML
		}),
		styles: [STYLESHEET]
	};
}
