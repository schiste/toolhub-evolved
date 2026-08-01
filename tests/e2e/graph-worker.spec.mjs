// SPDX-License-Identifier: GPL-3.0-or-later
import { expect, test } from "@playwright/test";
import { useSmokeServer } from "./harness.mjs";

test.describe("large graph worker", () => {
	const smoke = useSmokeServer();

	test("a 601-node grouped map settles in a same-origin Worker", async ({ page }) => {
		const nodes = Array.from({ length: 601 }, (_, index) => ({
			id: `tool-${index}`,
			title: `Tool ${index}`,
			community: index % 2,
			group: index % 2,
			groupValues: [index % 2],
			weight: 2,
			projects: [index % 2 ? "www.wikidata.org" : "commons.wikimedia.org"],
			languages: ["en"]
		}));
		const edges = nodes.slice(1).map((_node, index) => ({
			source: nodes[index].id,
			target: nodes[index + 1].id,
			weight: 0.8
		}));
		await page.route("**/v1/graph/**", (route) =>
			route.fulfill({
				contentType: "application/json",
				body: JSON.stringify({
					nodes,
					edges,
					layout: "force",
					groupBy: "project",
					groupMeta: [
						{ id: 0, label: "Commons", size: 301 },
						{ id: 1, label: "Wikidata", size: 300 }
					],
					groupingMeta: [
						{ id: "similarity", covered: 601, total: 601, enabled: true },
						{ id: "project", covered: 601, total: 601, enabled: true }
					],
					truncated: false
				})
			})
		);
		const browserErrors = [];
		page.on("console", (message) => {
			if (message.type() === "error") browserErrors.push(message.text());
		});
		page.on("pageerror", (error) => browserErrors.push(error.message));
		const workerStarted = page.waitForEvent("worker");

		await page.goto(new URL("/graph?limit=1000&groupBy=project", smoke.url).href);
		const worker = await workerStarted;

		expect(worker.url()).toContain("/lib/workers/graph-layout-worker.js");
		await expect(page.locator("#graph-canvas canvas")).toBeVisible();
		await expect(page.locator('[data-graph-option="groupBy"]')).toHaveValue("project");
		await expect
			.poll(() =>
				page
					.locator("#graph-canvas")
					.evaluate((element) => Object.keys(element.forceGraphHandle?.positions?.() || {}).length)
			)
			.toBe(601);
		expect(browserErrors).toEqual([]);
	});
});
