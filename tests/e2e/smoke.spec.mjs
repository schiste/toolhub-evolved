// SPDX-License-Identifier: GPL-3.0-or-later
import { AxeBuilder } from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { useSmokeServer } from "./harness.mjs";

const routes = [
	{ path: "/", title: /community catalog/i },
	{ path: "/search", title: /browse tools/i },
	{ path: "/search?ordering=-modified_date", title: /browse tools/i },
	{ path: "/tools/toolforge-admin", title: /toolforge admin/i },
	{ path: "/by/Bryan%20Davis", title: /bryan davis/i },
	{ path: "/lists", title: /curated lists/i },
	{ path: "/people", title: /community directory/i },
	{ path: "/changelog", title: /changelog/i },
	{ path: "/recent?show=unpatrolled", title: /recent changes/i },
	{ path: "/api-docs", title: /api documentation/i },
	{ path: "/mcp-server", title: /mcp server/i },
	{ path: "/user/login/?next=/", title: /sign in/i },
	{ path: "/user/logout/", title: /signed out/i }
];

test.describe("deterministic app smoke", () => {
	const smoke = useSmokeServer();

	for (const route of routes) registerSmokeCase(route);

	test("cold enrichment settles without a render loop or shared account spinner", async ({ page }) => {
		await page.addInitScript(() => {
			window.__routeRenderStarts = 0;
			document.addEventListener("toolhub:route-render-start", () => {
				window.__routeRenderStarts += 1;
			});
		});
		await page.goto(new URL("/search", smoke.url).href);
		await expect(page.getByRole("heading", { name: "Browse tools" })).toBeVisible();
		await page.waitForTimeout(1000);

		expect(await page.evaluate(() => window.__routeRenderStarts)).toBeLessThanOrEqual(2);
		await expect(page.locator("#view")).toHaveAttribute("aria-busy", "false");
		await expect(page.locator("#view .route-loading")).toHaveCount(0);
		await expect(page.locator("#account .spinner")).toHaveCount(0);
	});

	test("multi-author cards disclose every author without inventing identity links", async ({ page }) => {
		await page.addInitScript(() => localStorage.setItem("toolhub-whats-new-never", "1"));
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(new URL("/search", smoke.url).href);
		await page.waitForTimeout(1000);
		const card = page.locator('[data-tool="toolforge-admin"]');
		const authors = card.locator(".tcard__authors");
		const summary = authors.locator("summary");

		await expect(summary).toContainText("by Bryan Davis, Grace Hopper +1");
		await expect(authors.locator(".tcard__authors-panel")).not.toBeVisible();
		await summary.click();
		await expect(authors).toHaveJSProperty("open", true);
		await expect(page.locator("#qv")).not.toBeVisible();
		const links = authors.locator(".tcard__authors-panel a");
		await expect(links).toHaveCount(0);
		await expect(authors.locator(".tcard__authors-panel li span")).toHaveCount(3);
		const panel = authors.locator(".tcard__authors-panel");
		await expect(panel).toBeVisible();
		const panelBox = await panel.boundingBox();
		expect(panelBox).not.toBeNull();
		expect(panelBox.x).toBeGreaterThanOrEqual(0);
		expect(panelBox.x + panelBox.width).toBeLessThanOrEqual(390);
		const { violations } = await new AxeBuilder({ page }).include('[data-tool="toolforge-admin"]').analyze();
		expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
	});

	test("a failed optional command-palette chunk does not block the route", async ({ page }) => {
		await page.route("**/lib/organisms/command-palette.js*", (route) => route.fulfill({ status: 503 }));
		await page.goto(new URL("/people", smoke.url).href);
		await expect(page.getByRole("heading", { name: "Community directory" })).toBeVisible();
		await expect(page.locator("#view")).toHaveAttribute("aria-busy", "false");
	});

	test("a persistent entry-module failure stops at a visible retry state", async ({ page }) => {
		let failedRequests = 0;
		await page.route("**/main.js*", (route) => {
			failedRequests += 1;
			return route.fulfill({ status: 503 });
		});
		await page.goto(new URL("/people", smoke.url).href);
		const recovery = page.getByRole("heading", { name: "Toolhub could not finish loading" });
		await expect(recovery).toBeVisible({ timeout: 10_000 });
		await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
		await expect(page.locator("#view")).toHaveAttribute("aria-busy", "false");
		expect(failedRequests).toBeGreaterThanOrEqual(2);
		await page.waitForTimeout(3500);
		await expect(recovery).toBeVisible();
	});

	function registerSmokeCase(route) {
		test(`${route.path} renders, stays clean, and passes axe`, async ({ page }) => {
			await smokeRoute(page, route, smoke.url);
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
	await expect(page.locator("#view")).toHaveAttribute("aria-busy", "false");
	await expect(page.locator("#view .route-loading")).toHaveCount(0);
	await expect(page.locator("#account .spinner")).toHaveCount(0);
	await expect(page).not.toHaveURL(/\/#\//);
	await expect(page.locator("body")).not.toHaveCSS("overflow-x", "scroll");

	const { violations } = await new AxeBuilder({ page })
		.withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"])
		.analyze();
	expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
	expect(browserErrors).toEqual([]);
}
