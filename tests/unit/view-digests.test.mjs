// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

const h = vi.hoisted(() => ({ backendGetJson: vi.fn(), serverWrite: vi.fn(), signedIn: vi.fn() }));
vi.mock("../../public_html/lib/core/api.js", async (original) => ({
	...(await original()),
	backendGetJson: h.backendGetJson
}));
vi.mock("../../public_html/lib/core/serversync.js", async (original) => ({
	...(await original()),
	serverWrite: h.serverWrite
}));
vi.mock("../../public_html/lib/core/session.js", async (original) => ({
	...(await original()),
	signedIn: h.signedIn
}));

import { viewDigests } from "../../public_html/views/digests.js";

const edition = {
	cadence: "daily",
	editionKey: "2026-08-12",
	periodStart: "2026-08-12T00:00:00Z",
	title: "Toolhub Daily — 12 August 2026",
	introduction: "Two focused additions for editors.",
	toolCount: 1,
	html: '<article class="digest-entry"><h1>Toolhub Daily</h1></article>',
	metaPageUrl: "https://meta.wikimedia.org/wiki/Toolhub/Digest/Daily/2026-08-12",
	tools: [{ name: "example" }]
};

beforeEach(() => {
	document.body.innerHTML = "";
	h.backendGetJson.mockReset();
	h.serverWrite.mockReset();
	h.signedIn.mockReset().mockReturnValue(false);
});

test("archive is a date-led editorial stream with cadence RSS and signed-out CTA", async () => {
	h.backendGetJson.mockResolvedValue({ editions: [edition] });

	const view = await viewDigests("daily");

	assert.deepEqual(view.styles, ["/styles/digests.css"]);
	assert.match(view.html, /Toolhub Digest/);
	assert.match(view.html, /August 12, 2026/);
	assert.match(view.html, /1 tool added/);
	assert.match(view.html, /feeds\/digests\/daily\.xml/);
	assert.match(view.html, /Sign in to subscribe/);
	assert.deepEqual(h.backendGetJson.mock.calls, [["/v1/digests/?cadence=daily"]]);
});

test("edition detail renders frozen server HTML and canonical Meta link", async () => {
	h.backendGetJson.mockResolvedValue(edition);

	const view = await viewDigests("daily", "2026-08-12");

	assert.match(view.html, /<article class="digest-entry">/);
	assert.match(view.html, /Read on Meta-Wiki/);
	assert.match(view.html, /meta\.wikimedia\.org/);
});

test("historical website edition renders as an ordinary entry without claiming Meta publication", async () => {
	h.backendGetJson.mockResolvedValue({
		...edition,
		metaPageUrl: "",
		html: '<article class="digest-entry"><footer>Author: LiftWing Qwen</footer></article>'
	});

	const view = await viewDigests("daily", "2026-08-12");

	assert.match(view.html, /Author: LiftWing Qwen/);
	assert.doesNotMatch(view.html, /Read on Meta-Wiki/);
	assert.doesNotMatch(view.html, /preview/i);
});

test("signed-in talk-page form sends cadence and wiki through the CSRF server writer", async () => {
	h.signedIn.mockReturnValue(true);
	h.backendGetJson.mockImplementation((path) =>
		path.includes("subscriptions") ? Promise.resolve({ subscriptions: [] }) : Promise.resolve({ editions: [] })
	);
	h.serverWrite.mockResolvedValue({ subscription: { confirmed: true } });
	const view = await viewDigests("weekly");
	document.body.innerHTML = view.html;
	view.mount();
	const form = document.querySelector("[data-digest-subscribe]");
	form.querySelector('[value="talk"]').click();
	form.querySelector('[name="wikiDomain"]').value = "fr.wikipedia.org";
	form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

	await vi.waitFor(() => assert.equal(h.serverWrite.mock.calls.length, 1));
	assert.deepEqual(h.serverWrite.mock.calls[0], [
		"POST",
		"/v1/digests/subscriptions/",
		{ channel: "talk", cadence: "weekly", language: "en", wikiDomain: "fr.wikipedia.org" }
	]);
	assert.match(document.body.textContent, /Subscription active/);
});
