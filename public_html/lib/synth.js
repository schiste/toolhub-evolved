// SPDX-License-Identifier: GPL-3.0-or-later
import { hash } from "./dom.js";

/* ===== Synthetic signals (Lane B) =========================================
   EXPERIMENTAL decorations the read-only Toolhub API can't provide. Each is a
   pure, deterministic function of the tool name, so values are stable per tool
   and the same everywhere the tool appears (the "overload real data" pattern).
   Each notes the backend capability it would need in production. */
export function synthSeed(name, salt) { return hash(name + "·" + salt); }
// Popularity — Needs: usage/view tracking the API doesn't expose.
export function synthViews(name) { const h = hash(name), b = h % 100; return b >= 92 ? 1000 + (h % 1500) : b >= 70 ? 250 + (h % 750) : 20 + (h % 230); }
// Operational health — Needs: an uptime/health-check service.
export function synthHealth(name) {
	const b = synthSeed(name, "health") % 100;
	if (b >= 96) return { level: "red", label: "Down" };
	if (b >= 85) return { level: "yellow", label: "Degraded" };
	return { level: "green", label: "Healthy" };
}
// Ratings & reviews — Needs: a reviews data model + authenticated submissions.
export function synthReviews(name) {
	const h = synthSeed(name, "rating");
	return { rating: (35 + (h % 16)) / 10, count: 3 + (synthSeed(name, "rcount") % 140) }; // 3.5–5.0
}
export function starString(rating) {
	const full = Math.floor(rating), half = rating - full >= 0.5;
	return "★".repeat(full) + (half ? "½" : "") + "☆".repeat(5 - full - (half ? 1 : 0));
}
// 30-day usage — Needs: usage analytics the API doesn't expose.
export function synthUsage(name) { return 50 + (synthSeed(name, "usage") % 9000); }
