// SPDX-License-Identifier: GPL-3.0-or-later
import { expect, test } from "@playwright/test";
import { useSmokeServer } from "./harness.mjs";

test.describe("RTL layout smoke", () => {
	const smoke = useSmokeServer();

	test("mirrors the core shell and language menu without horizontal overflow", async ({ page }) => {
		await openRtl(page, "/", smoke.url);
		await expectNoDocumentOverflow(page, "home shell");
		await expectVisibleSelectorsInsideViewport(page, [
			{ selector: ".nav__inner", required: true },
			{ selector: ".nav__links", required: true },
			{ selector: ".nav__actions", required: true },
			{ selector: "#account", required: true },
			{ selector: "#langpicker", required: true },
			{ selector: "#theme-toggle", required: true }
		]);

		await page.locator("#lang-btn").click();
		await expect(page.locator("#lang-menu")).not.toHaveAttribute("hidden", /.*/);
		await expectNoDocumentOverflow(page, "language menu");
		await expectVisibleSelectorsInsideViewport(page, [{ selector: "#lang-menu", required: true }]);
	});

	test("keeps signed-in account disclosure inside the RTL viewport", async ({ page }) => {
		await page.route("**/v1/user/", (route) =>
			route.fulfill({
				contentType: "application/json; charset=utf-8",
				json: { authenticated: true, username: "RTL User", csrf: "csrf-token" }
			})
		);
		await page.route("**/v1/overlay/", (route) =>
			route.fulfill({ contentType: "application/json; charset=utf-8", json: {} })
		);

		await openRtl(page, "/", smoke.url);
		await page.locator("#acct-btn").click();
		await expect(page.locator("#acct-menu")).not.toHaveAttribute("hidden", /.*/);
		await expectNoDocumentOverflow(page, "account menu");
		await expectVisibleSelectorsInsideViewport(page, [{ selector: "#acct-menu", required: true }]);
	});

	test("keeps search cards, status flags, and quick-view inside the RTL viewport", async ({ page }) => {
		await openRtl(page, "/search", smoke.url);
		await expect(page.locator(".tcard")).toHaveCount(3);
		await expect(page.locator(".tcard__flag")).toBeVisible();
		await expectNoDocumentOverflow(page, "search results");
		await expectVisibleSelectorsInsideViewport(page, [
			{ selector: ".tcard", required: true },
			{ selector: ".tcard__flag", required: true }
		]);

		await page.getByRole("button", { name: /quick look: wikidata query helper/i }).click();
		await expect(page.locator("#qv")).not.toHaveClass(/hidden/);
		await expectNoDocumentOverflow(page, "quick-view");
		await expectVisibleSelectorsInsideViewport(page, [
			{ selector: ".qv__box", required: true },
			{ selector: ".qv__status", required: true }
		]);
	});

	test("keeps the recent table inside the RTL viewport", async ({ page }) => {
		await openRtl(page, "/recent?show=unpatrolled", smoke.url);
		await expect(page.locator(".recent-table")).toBeVisible();
		await expectNoDocumentOverflow(page, "recent table");
		await expectVisibleSelectorsInsideViewport(page, [{ selector: ".recent-table", required: true }]);
	});
});

async function openRtl(page, path, smokeUrl) {
	await page.setViewportSize({ width: 1280, height: 900 });
	await page.addInitScript(() => {
		localStorage.setItem("toolhub-locale", "ar");
	});
	await page.goto(new URL(path, smokeUrl).href);
	await expect(page.locator("#view")).toBeVisible();
	await expect(page.locator("h1").first()).toBeVisible();
	await expect(page.locator("html")).toHaveAttribute("lang", "ar");
	await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
}

async function expectNoDocumentOverflow(page, label) {
	const metrics = await page.evaluate(() => ({
		clientWidth: document.documentElement.clientWidth,
		scrollWidth: document.documentElement.scrollWidth
	}));
	expect(
		metrics.scrollWidth,
		`${label}: document scrollWidth ${metrics.scrollWidth} exceeds viewport ${metrics.clientWidth}`
	).toBeLessThanOrEqual(metrics.clientWidth + 1);
}

async function expectVisibleSelectorsInsideViewport(page, selectors) {
	const failures = await page.evaluate((wanted) => {
		const viewportWidth = document.documentElement.clientWidth;
		const isVisible = (el) => {
			const style = getComputedStyle(el);
			const rect = el.getBoundingClientRect();
			return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
		};
		return wanted.flatMap(({ selector, required }) => {
			const elements = [...document.querySelectorAll(selector)].filter((element) => isVisible(element));
			if (required && elements.length === 0) return [`${selector}: no visible elements`];
			return elements
				.map((el, index) => {
					const rect = el.getBoundingClientRect();
					return rect.left < -1 || rect.right > viewportWidth + 1
						? `${selector}[${index}]: horizontal bounds ${rect.left.toFixed(1)}..${rect.right.toFixed(1)} outside 0..${viewportWidth}`
						: "";
				})
				.filter(Boolean);
		});
	}, selectors);
	expect(failures).toEqual([]);
}
