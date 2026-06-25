// SPDX-License-Identifier: GPL-3.0-or-later
import { AxeBuilder } from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { startSmokeServer } from "../../tools/smoke-server.mjs";

const routes = [
	{ path: "/", title: /community catalog/i },
	{ path: "/search", title: /browse tools/i },
	{ path: "/tools/toolforge-admin", title: /toolforge admin/i },
	{ path: "/by/Bryan%20Davis", title: /bryan davis/i },
	{ path: "/lists", title: /curated lists/i },
	{ path: "/recent?show=unpatrolled", title: /recent changes/i },
	{ path: "/api-docs", title: /api documentation/i }
];

test.describe("deterministic app smoke", () => {
	let smokeServer;
	let smokeUrl;

	test.beforeAll(async () => {
		smokeServer = await startSmokeServer({ port: 0 });
		smokeUrl = smokeServer.url;
	});

	test.afterAll(async () => {
		if (!smokeServer) return;
		await new Promise((resolve, reject) => {
			smokeServer.server.close((error) => (error ? reject(error) : resolve()));
		});
	});

	for (const route of routes) registerSmokeCase(route);

	function registerSmokeCase(route) {
		test(`${route.path} renders, stays clean, and passes axe`, async ({ page }) => {
			await smokeRoute(page, route, smokeUrl);
		});
	}
});

async function smokeRoute(page, route, smokeUrl) {
	const browserErrors = [];
	page.on("console", (message) => {
		if (message.type() === "error") browserErrors.push(message.text());
	});
	page.on("pageerror", (error) => browserErrors.push(error.message));

	await page.goto(new URL(route.path, smokeUrl).href);
	await expect(page.locator("#view")).toBeVisible();
	await expect(page.locator("h1").first()).toContainText(route.title);
	await expect(page).not.toHaveURL(/\/#\//);
	await expect(page.locator("body")).not.toHaveCSS("overflow-x", "scroll");

	const { violations } = await new AxeBuilder({ page })
		.withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"])
		.analyze();
	expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
	expect(browserErrors).toEqual([]);
}
