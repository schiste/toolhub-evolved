// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";
import * as S from "../../public_html/views/static.js";
import * as api from "../../public_html/lib/core/api.js";
import * as serversync from "../../public_html/lib/core/serversync.js";

vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, apiGet: vi.fn() };
});

vi.mock("../../public_html/lib/core/serversync.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, devLoginAvailable: vi.fn(() => false) };
});

beforeEach(() => vi.clearAllMocks());

const STATIC_TITLES = {
	about: "About Toolhub — Toolhub",
	help: "Help — Toolhub",
	community: "Community — Toolhub",
	privacy: "Privacy policy — Toolhub",
	terms: "Terms of Use — Toolhub",
	"code-of-conduct": "Code of Conduct — Toolhub",
	api: "API — Toolhub",
	"rules-of-engagement": "Rules of Engagement — Toolhub",
	"health-score": "Health score system — Toolhub",
	rss: "Feeds — Toolhub"
};

test("prosePage wraps an escaped title and raw body", () => {
	assert.deepEqual(S.prosePage("A&B <x>", "<p>body</p>"), {
		title: "A&B <x> — Toolhub",
		html: '<div class="container page"><article class="prose prose--page"><h1>A&amp;B &lt;x&gt;</h1><p>body</p></article></div>'
	});
	assert.ok(S.prosePage("Wide", "<p>body</p>", "wide").html.includes('class="prose prose--page prose--wide"'));
});

test("ext renders safe external links and rejects unsafe URLs", () => {
	const link = S.ext("https://e.x/p?a=b&c", "L<a>bel");
	assert.ok(link.includes('href="https://e.x/p?a=b&amp;c"'));
	assert.ok(link.includes('target="_blank" rel="noopener nofollow"'));
	assert.ok(link.includes("L&lt;a&gt;bel"));
	assert.ok(link.includes("<svg"));
	assert.ok(S.ext("javascript:alert(1)", "x").includes('href=""'));
});

test("viewStatic exposes every static page with current hybrid Toolhub/Evolved copy", () => {
	const slugs = Object.keys(STATIC_TITLES);
	assert.equal(slugs.length, 10);
	assert.deepEqual(Object.keys(S.STATIC), slugs);
	for (const slug of slugs) {
		assert.equal(S.viewStatic(slug).title, STATIC_TITLES[slug]);
	}
	assert.ok(S.viewStatic("about").html.includes("Sign in with Toolhub"));
	assert.ok(S.viewStatic("about").html.includes("keeps Evolved-only additions in its local overlay database"));
	assert.ok(S.viewStatic("help").html.includes("publish permitted edits"));
	assert.ok(S.viewStatic("community").html.includes("Toolhub Evolved is an experimental companion interface"));
	assert.ok(S.viewStatic("community").html.includes("Toolhub Evolved issues"));
	assert.ok(S.viewStatic("community").html.includes("Official Toolhub channels"));
	assert.ok(S.viewStatic("privacy").html.includes("server-side OAuth grant"));
	assert.ok(
		S.viewStatic("privacy").html.includes("not operated, endorsed, or maintained by the Wikimedia Foundation")
	);
	assert.ok(S.viewStatic("terms").html.includes("not a Wikimedia Foundation-operated service"));
	assert.ok(S.viewStatic("terms").html.includes("Using this beta"));
	assert.ok(S.viewStatic("code-of-conduct").html.includes("not an official Wikimedia Foundation venue"));
	assert.ok(S.viewStatic("code-of-conduct").html.includes("accessibility, localization, privacy"));
	const rules = S.viewStatic("rules-of-engagement").html;
	assert.ok(rules.includes("supported writes are sent back to the official Toolhub API"));
	assert.ok(rules.includes("server-side canonical cache of official tool records"));
	assert.ok(rules.includes("every 15 minutes"));
	assert.ok(rules.includes("one catalog page is reconciled every 12 hours"));
	assert.ok(rules.includes("What's Evolved-only"));
	assert.ok(rules.includes("Evolved additions are visible by default"));
	assert.ok(rules.includes("Verified author claims"));
	assert.ok(rules.includes("being verified for one tool"));
	assert.ok(rules.includes("site notice can be dismissed"));
	assert.ok(rules.includes("Toolhub remains the source of truth"));
	assert.ok(!rules.includes("Nothing here is ever written back to Toolhub"));
	const health = S.viewStatic("health-score").html;
	assert.ok(health.includes('class="prose prose--page prose--wide"'));
	assert.ok(health.includes("reproducibility spec"));
	assert.ok(health.includes("/v1/tools/summaries/?name=TOOL_NAME"));
	assert.ok(health.includes("sum(dimension.score * dimension.weight"));
	assert.ok(health.includes("source-health"));
	assert.ok(health.includes("maintainer-status"));
	assert.ok(health.includes("counts.verifiedMaintainers"));
	assert.ok(health.includes("runtime-health"));
	assert.ok(health.includes("healthy"));
	assert.ok(health.includes("95"));
	assert.ok(health.includes("metadata-completeness"));
	assert.ok(health.includes("credential-like-source"));
	assert.ok(health.includes("maxSourceWeight"));
	assert.ok(health.includes("public_score = 93"));
	assert.ok(health.includes("Variables used"));
	assert.ok(health.includes("No large language model output is used"));
	assert.ok(health.includes("last commit timestamp"));
	const rss = S.viewStatic("rss").html;
	assert.ok(rss.includes("/feeds/recent.xml"));
	assert.ok(rss.includes("/feeds/tools/recently-updated.xml"));
	assert.ok(rss.includes("/feeds/lists.xml"));
	assert.ok(rss.includes("/feeds/tools/TOOL_NAME/revisions.xml"));
	assert.ok(rss.includes("RSS 2.0 XML"));
});

test("viewStatic falls back to the not-found page for an unknown slug", () => {
	const view = S.viewStatic("nope");
	assert.equal(view.title, "Not found — Toolhub");
	assert.ok(view.html.includes("Page not found"));
	assert.ok(view.html.includes('href="/">Go to the home page</a>'));
});

test("viewContribute renders the contribution hub", () => {
	const view = S.viewContribute();
	assert.equal(view.title, "Help maintain Toolhub Evolved");
	assert.ok(view.html.includes("Report a beta issue"));
	assert.ok(view.html.includes("Toolhub Evolved source"));
	assert.ok(view.html.includes("Official Toolhub Phabricator"));
	assert.ok(view.html.includes("API explorer"));
});

test("linkCard handles internal, external and unsafe URLs", () => {
	assert.ok(S.linkCard("<i/>", "T&t", "D<d>", "/path", true).includes('href="/path"'));
	assert.ok(S.linkCard("<i/>", "T&t", "D<d>", "/path", true).includes("T&amp;t"));
	const external = S.linkCard("<i/>", "T&t", "D<d>", "https://x.y/z", false);
	assert.ok(external.includes('href="https://x.y/z"'));
	assert.ok(external.includes('target="_blank" rel="noopener nofollow"'));
	assert.ok(external.includes("<svg"));
	assert.ok(S.linkCard("<i/>", "T", "D", "javascript:bad", false).includes('href="#"'));
});

test("signInPage renders the Toolhub OAuth sign-in stub", () => {
	const view = S.signInPage("Sign&in", "Lead<x>");
	assert.equal(view.title, "Sign&in — Toolhub");
	assert.ok(view.html.includes("<h1>Sign&amp;in</h1>"));
	assert.ok(view.html.includes("<p>Lead<x></p>"));
	assert.ok(view.html.includes("official Toolhub OAuth"));
	assert.ok(view.html.includes('href="/oauth/login"'));
	assert.ok(view.html.includes("Sign in with Toolhub"));
	assert.ok(view.html.includes("Official writes still follow Toolhub's permissions"));
});

test("signInPage renders the local dev sign-in stub when available", () => {
	serversync.devLoginAvailable.mockReturnValue(true);
	window.history.replaceState({}, "", "/preferences?x=1");
	const view = S.signInPage("Preferences", "Lead");
	assert.ok(view.html.includes("Evolved-only test session"));
	assert.ok(view.html.includes('href="/oauth/dev-login?next=%2Fpreferences%3Fx%3D1"'));
	assert.ok(view.html.includes("Use local dev sign-in"));
});

test("viewNotFound renders the 404 page", () => {
	const view = S.viewNotFound();
	assert.equal(view.title, "Not found — Toolhub");
	assert.ok(view.html.includes("Page not found"));
});

test("viewApiDocs lists sorted proxy endpoints from the API root", async () => {
	api.apiGet.mockResolvedValue({ tools: {}, lists: {}, search: {} });
	const view = await S.viewApiDocs();
	assert.deepEqual(api.apiGet.mock.calls[0], ["/"]);
	assert.equal(view.title, "API documentation — Toolhub");
	assert.ok(view.html.includes("Evolved reads the live catalog through a same-origin proxy"));
	assert.ok(view.html.includes("<code>/v1/write/*</code> official-first lifecycle"));
	assert.ok(view.html.includes("official OAuth tokens stay server-side"));
	assert.equal(typeof view.mount, "function");
	assert.ok(view.html.includes("data-api-explorer"));
	assert.ok(view.html.includes('data-api-endpoint="search-tools"'));
	assert.ok(view.html.includes("/api/crawler/urls/"));
	assert.ok(view.html.includes("Try read-only endpoints"));
	assert.ok(view.html.includes("toolinfo JSON Schema"));
	assert.ok(view.html.includes("toolinfo.json schema"));
	assert.ok(view.html.includes("current.yaml"));
	assert.ok(view.html.includes("&quot;_schema&quot;: &quot;/toolinfo/1.2.2&quot;"));
	assert.ok(view.html.includes("OpenAPI schema for code generation"));
	assert.ok(view.html.includes("Revision diffs and JSON Patch operations"));
	assert.ok(view.html.includes("<code>jsondiff</code> operations"));
	assert.ok(view.html.includes("<code>application/json-patch+json</code> operations"));
	assert.ok(view.html.includes("GET /api/tools/{name}/revisions/{id}/diff/{other_id}/"));
	assert.ok(view.html.includes("&quot;op&quot;: &quot;replace&quot;"));
	assert.ok(view.html.includes("&quot;path&quot;: &quot;/keywords/1&quot;"));
	assert.ok(view.html.indexOf("<code>GET /api/lists/</code>") < view.html.indexOf("<code>GET /api/search/</code>"));
	assert.ok(view.html.indexOf("<code>GET /api/search/</code>") < view.html.indexOf("<code>GET /api/tools/</code>"));
});

test("viewApiDocs shows the unavailable placeholder when the root cannot be read", async () => {
	api.apiGet.mockRejectedValue(new Error("x"));
	const view = await S.viewApiDocs();
	assert.equal(view.title, "API documentation — Toolhub");
	assert.ok(view.html.includes("The live endpoint index is unavailable."));
	assert.ok(view.html.includes("data-api-explorer"));
	assert.ok(view.html.includes("Authenticated writes never go through that proxy"));
});
