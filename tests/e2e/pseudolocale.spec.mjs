// SPDX-License-Identifier: GPL-3.0-or-later
import { expect, test } from "@playwright/test";
import { useSmokeServer } from "./harness.mjs";

test.describe("pseudolocale QA", () => {
	const smoke = useSmokeServer();

	test("renders expanded chrome through the real locale path without overflow", async ({ page }) => {
		await openPseudo(page, "/", smoke.url);
		await expect(page.locator("html")).toHaveAttribute("lang", "en-x-pseudo");
		await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
		await expect(page.locator("#nav-links a").first()).toContainText("[Ţǿǿļş");
		await expect(page.locator(".command-trigger__label")).toContainText("[Şḗåřç");
		await expectNoDocumentOverflow(page, "pseudolocalized home shell");

		await page.locator("#lang-btn").click();
		await expect(page.locator('[data-lang="en-x-pseudo"]')).toHaveAttribute("aria-checked", "true");
		await expectNoDocumentOverflow(page, "pseudolocalized language menu");
	});

	test("keeps search chrome transformed while live Toolhub data remains data", async ({ page }) => {
		await openPseudo(page, "/search", smoke.url);
		await expect(page.locator("h1").first()).toContainText("[Ɓřǿŵşḗ ŧǿǿļş");
		await expect(page.locator(".tcard")).toHaveCount(3);
		await expect(page.locator(".tcard__maint").first()).toContainText("[ƀ");
		await expect(page.locator(".tcard__title").first()).not.toContainText("[");
		await expectNoDocumentOverflow(page, "pseudolocalized search results");
	});
});

async function openPseudo(page, path, smokeUrl) {
	await page.setViewportSize({ width: 1280, height: 900 });
	await page.addInitScript(() => {
		localStorage.setItem("toolhub-locale", "en-x-pseudo");
	});
	await page.goto(new URL(path, smokeUrl).href);
	await expect(page.locator("#view")).toBeVisible();
	await expect(page.locator("h1").first()).toBeVisible();
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
