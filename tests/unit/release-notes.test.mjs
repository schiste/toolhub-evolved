// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test, vi } from "vitest";

const h = vi.hoisted(() => ({ backendGetJson: vi.fn() }));
vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => ({
	...(await importOriginal()),
	backendGetJson: h.backendGetJson
}));

import { releaseNoteItems, releaseNotesHTML } from "../../public_html/lib/molecules/release-notes.js";
import * as whatsNew from "../../public_html/lib/organisms/whats-new.js";
import { viewChangelog } from "../../public_html/views/changelog.js";

test("release notes normalize reviewed bullets and escape their content", () => {
	assert.deepEqual(releaseNoteItems("- One\n* Two\n\nThree"), ["One", "Two", "Three"]);
	assert.equal(
		releaseNotesHTML("- Safer <script>alert(1)</script>"),
		'<ul class="release-notes"><li>Safer &lt;script&gt;alert(1)&lt;/script&gt;</li></ul>'
	);
});

test("changelog groups curated notes by release without exposing raw commit rows", async () => {
	h.backendGetJson.mockResolvedValue({
		deployments: [
			{
				id: "community-directory",
				title: "Community directory",
				sha: "abc123def",
				releasedAt: "2026-08-11T08:00:00Z",
				deployedAt: "2026-08-12T08:00:00Z",
				changes: [{ subject: "fix: internal detail", shortSha: "deadbee" }],
				marketing: { user: "- Loading now settles", technical: "- Refresh notifications converge" }
			}
		]
	});
	const view = await viewChangelog();

	assert.deepEqual(h.backendGetJson.mock.calls.at(-1), ["/data/deployments.json"]);
	assert.match(view.html, /class="changelog__release"/);
	assert.match(view.html, /Community directory/);
	assert.match(view.html, /Serving build/);
	assert.match(view.html, /Loading now settles/);
	assert.match(view.html, /<details class="changelog__technical">/);
	assert.doesNotMatch(view.html, /internal detail|deadbee|changelog__item/);
});

test("What's New shows two curated releases without raw commit rows", async () => {
	document.body.innerHTML = `<div id="whats-new" class="hidden" aria-hidden="true">
		<button data-whats-new-close>Close</button><div id="whats-new-body"></div>
	</div>`;
	h.backendGetJson.mockResolvedValue({
		deployments: Array.from({ length: 3 }, (_, index) => ({
			id: `release-${index}`,
			title: `Release ${index}`,
			sha: `${index}`.repeat(40),
			deployedAt: "2026-08-12T08:00:00Z",
			changes: [{ subject: `raw commit ${index}` }],
			marketing: { user: `- Outcome ${index}`, technical: `- Detail ${index}` }
		}))
	});
	whatsNew.resetWhatsNewForTests();
	await whatsNew.initWhatsNew();
	whatsNew.renderWhatsNew();
	const body = document.querySelector("#whats-new-body");

	assert.equal(body.querySelectorAll(".whats-new__deploy").length, 2);
	assert.match(body.textContent, /Outcome 0/);
	assert.match(body.textContent, /Outcome 1/);
	assert.doesNotMatch(body.textContent, /Outcome 2|raw commit/);
	assert.doesNotMatch(body.textContent, /\bDeploy\b/);
});
