// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test, vi, beforeEach } from "vitest";
// apiGet hits the network and demoFeed reads localStorage; both are made deterministic.
// demoFeed is a pass-through so the live results render verbatim (and we assert the key
// it is called with). Everything else (esc, i18n, routing hrefs, avatar, metaItem) is real.
import { viewRecent, viewMembers, viewCrawler, viewAudit, targetHref } from "../../public_html/views/parity.js";
import * as api from "../../public_html/lib/core/api.js";
import { DEMO_KEYS } from "../../public_html/lib/core/store.js";

vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, apiGet: vi.fn() };
});
vi.mock("../../public_html/lib/core/store.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, demoFeed: vi.fn((_key, live) => live) };
});

// Clear call history (but keep the demoFeed pass-through impl) so each test inspects
// only its own apiGet/demoFeed calls.
beforeEach(() => vi.clearAllMocks());

const setSearch = (search) => window.history.replaceState({}, "", `/recent${search}`);
const ISO = "2019-01-01T00:00:00Z";

/* ---- viewRecent -------------------------------------------------------- */

test("viewRecent: a tool change deep-links via toolHref with title and user", async () => {
	setSearch("");
	api.apiGet.mockResolvedValue({
		results: [
			{
				content_type: "tool",
				content_id: "my-tool",
				content_title: "My Tool",
				user: { username: "alice" },
				timestamp: ISO
			}
		]
	});
	const view = await viewRecent();

	assert.equal(view.title, "Recent changes — Toolhub");
	assert.deepEqual(api.apiGet.mock.calls[0], ["/recent/", { page_size: "30" }]);
	// demoFeed merges under the revisions key.
	const store = await import("../../public_html/lib/core/store.js");
	assert.equal(store.demoFeed.mock.calls[0][0], DEMO_KEYS.revisions);

	assert.match(view.html, /<li><a href="\/tools\/my-tool"><svg class="icon feed__ic"/);
	assert.match(view.html, /<strong dir="auto">My Tool<\/strong>/);
	assert.match(view.html, /tool · <span dir="auto">alice<\/span>/);
	assert.match(view.html, /<time class="feed__when" datetime="2019-01-01T00:00:00\.000Z"/);
	// show defaults to "all" → the "All" filter is active, "Tools" is not, and no patrol note.
	// Adjacency (no text between the links) kills the filters' .join("") separator mutant.
	assert.match(
		view.html,
		/show=all" aria-current="page">All<\/a><a class="rc-filter__link" href="\/recent\?show=tools">Tools<\/a>/
	);
	// Empty patrolNote: <nav> closes directly onto the <ul> (kills the `: ""` → injected string).
	assert.match(view.html, /<\/nav>\s*<ul class="feed">/);
	assert.doesNotMatch(view.html, /Patrolled and unpatrolled/);
});

test("viewRecent: a list change uses content_id when title is absent and links via listHref", async () => {
	setSearch("");
	api.apiGet.mockResolvedValue({ results: [{ content_type: "list", content_id: "42", user: {}, timestamp: ISO }] });
	const view = await viewRecent();
	assert.match(view.html, /<li><a href="\/lists\/42">/);
	assert.match(view.html, /<strong dir="auto">42<\/strong>/);
	// user:{} (present but no username) still falls back to "system".
	assert.match(view.html, /list · <span dir="auto">system<\/span>/);
});

test("viewRecent: untyped change renders static with dash/item/system defaults", async () => {
	setSearch("");
	api.apiGet.mockResolvedValue({ results: [{ timestamp: ISO }] });
	const view = await viewRecent();
	assert.match(view.html, /<li><div class="feed__static"><svg/);
	assert.match(view.html, /<strong dir="auto">—<\/strong>/);
	assert.match(view.html, /item · <span dir="auto">system<\/span>/);
	assert.doesNotMatch(view.html, /<a href="\/tools/);
});

test("viewRecent: typed changes without an id never become links", async () => {
	setSearch("");
	api.apiGet.mockResolvedValue({
		results: [
			{ content_type: "tool", content_title: "NoId Tool" },
			{ content_type: "list", content_title: "NoId List" }
		]
	});
	const view = await viewRecent();
	assert.doesNotMatch(view.html, /<a href="\/tools/);
	assert.doesNotMatch(view.html, /<a href="\/lists/);
	assert.match(view.html, /<strong dir="auto">NoId Tool<\/strong>/);
	assert.match(view.html, /<strong dir="auto">NoId List<\/strong>/);
});

test("viewRecent: each filter keeps only its own content type", async () => {
	const results = [
		{ content_type: "tool", content_id: "t", content_title: "T", timestamp: ISO },
		{ content_type: "list", content_id: "l", content_title: "L", timestamp: ISO },
		{ content_type: "category", content_id: "c", content_title: "C", timestamp: ISO }
	];
	api.apiGet.mockResolvedValue({ results });

	setSearch("?show=tools");
	let view = await viewRecent();
	assert.match(view.html, />T</);
	assert.doesNotMatch(view.html, />L</);
	assert.doesNotMatch(view.html, />C</);
	assert.match(view.html, /class="rc-filter__link is-active" href="\/recent\?show=tools" aria-current="page">Tools</);
	assert.match(view.html, /class="rc-filter__link" href="\/recent\?show=all">All</);

	setSearch("?show=lists");
	view = await viewRecent();
	assert.match(view.html, />L</);
	assert.doesNotMatch(view.html, />T</);

	setSearch("?show=other");
	view = await viewRecent();
	assert.match(view.html, />C</);
	assert.doesNotMatch(view.html, />T</);

	setSearch("?show=all");
	view = await viewRecent();
	assert.match(view.html, />T</);
	assert.match(view.html, />L</);
	assert.match(view.html, />C</);
	// Three rows joined with "" → adjacent <li>s (kills the rows .join("") separator).
	assert.match(view.html, /<\/li><li>/);
	// A "category" change has an id but is neither tool nor list → static, never a list link
	// (kills `r.content_type === "list"` → `true`).
	assert.doesNotMatch(view.html, /href="\/lists\/c"/);
	// The Lists/Other filter labels render (kills their label string literals).
	assert.match(view.html, /href="\/recent\?show=lists">Lists<\/a>/);
	assert.match(view.html, /href="\/recent\?show=other">Other<\/a>/);
});

test("viewRecent: an unknown show falls back to all", async () => {
	setSearch("?show=banana");
	api.apiGet.mockResolvedValue({
		results: [{ content_type: "tool", content_id: "t", content_title: "Kept", timestamp: ISO }]
	});
	const view = await viewRecent();
	assert.match(view.html, />Kept</);
	assert.match(view.html, /class="rc-filter__link is-active" href="\/recent\?show=all" aria-current="page">All</);
	assert.doesNotMatch(view.html, /Patrolled and unpatrolled/);
});

test("viewRecent: both patrol filters add the note and still fall back to all", async () => {
	api.apiGet.mockResolvedValue({ results: [] });

	setSearch("?show=patrolled");
	let view = await viewRecent();
	assert.match(view.html, /<p class="page__intro">Patrolled and unpatrolled state is not exposed/);
	assert.match(view.html, /class="rc-filter__link is-active" href="\/recent\?show=all" aria-current="page">All</);

	// "unpatrolled" is the second member of the unsupported set (kills its literal).
	setSearch("?show=unpatrolled");
	view = await viewRecent();
	assert.match(view.html, /Patrolled and unpatrolled state is not exposed/);
});

test("viewRecent: an API failure yields the empty placeholder", async () => {
	setSearch("");
	api.apiGet.mockRejectedValue(new Error("down"));
	const view = await viewRecent();
	assert.match(view.html, /<ul class="feed"><li><div class="feed__static">No recent changes\.<\/div><\/li><\/ul>/);
});

test("viewRecent: a response with no results array also shows the placeholder", async () => {
	setSearch("");
	api.apiGet.mockResolvedValue({});
	const view = await viewRecent();
	assert.match(view.html, /No recent changes\./);
});

/* ---- viewMembers ------------------------------------------------------- */

test("viewMembers: renders cards with groups, the Member fallback and a plural count", async () => {
	api.apiGet.mockResolvedValue({
		count: 2,
		results: [
			{ username: "Bob", groups: ["admin", "bots"], date_joined: ISO },
			{ username: "Cleo", groups: [] }
		]
	});
	const view = await viewMembers();
	assert.equal(view.title, "Members — Toolhub");
	assert.deepEqual(api.apiGet.mock.calls[0], ["/users/", { page_size: "60" }]);
	assert.match(view.html, /<div class="mcard__n" dir="auto">Bob<\/div>/);
	assert.match(view.html, /admin, bots · joined <time/);
	// Cleo has an empty groups array → the "Member" fallback (kills && and length > 0).
	assert.match(view.html, /<div class="mcard__n" dir="auto">Cleo<\/div>/);
	assert.match(view.html, /Member · joined /);
	assert.match(view.html, /<span class="avatar /);
	assert.match(view.html, /<p class="page__intro">2 registered Wikimedians contribute to the catalog\.<\/p>/);
	// Two cards joined with "" → Bob's card closes directly onto Cleo's (kills the .join("")).
	assert.match(view.html, /<\/div><\/div><div class="mcard">/);
});

test("viewMembers: a response with no results array renders an empty grid", async () => {
	// data.results is undefined here (not the [] from .catch) → the `|| []` fallback must
	// stay empty; an injected non-empty array would render a phantom card.
	api.apiGet.mockResolvedValue({ count: 0 });
	const view = await viewMembers();
	assert.match(view.html, /<div class="mgrid"><\/div>/);
});

test("viewMembers: an API failure shows zero members and an empty grid", async () => {
	api.apiGet.mockRejectedValue(new Error("nope"));
	const view = await viewMembers();
	assert.match(view.html, /<p class="page__intro">0 registered Wikimedians contribute to the catalog\.<\/p>/);
	assert.match(view.html, /<div class="mgrid"><\/div>/);
});

test("viewMembers: a single member uses the singular label", async () => {
	api.apiGet.mockResolvedValue({ count: 1, results: [{ username: "Solo" }] });
	const view = await viewMembers();
	assert.match(view.html, /<p class="page__intro">1 registered Wikimedian contribute to the catalog\.<\/p>/);
});

/* ---- viewCrawler ------------------------------------------------------- */

test("viewCrawler: renders meta from the first run and a row per run", async () => {
	api.apiGet.mockResolvedValue({
		results: [
			{ start_date: ISO, crawled_urls: 10, new_tools: 2, updated_tools: 3, total_tools: 100 },
			{} // missing fields → fmt(0) everywhere
		]
	});
	const view = await viewCrawler();
	assert.equal(view.title, "Crawler history — Toolhub");
	assert.deepEqual(api.apiGet.mock.calls[0], ["/crawler/runs/", { page_size: "12" }]);
	// Header meta uses runs[0].
	assert.match(view.html, /<div class="meta__k">URLs crawled<\/div><div class="meta__v" dir="auto">10<\/div>/);
	assert.match(view.html, /<div class="meta__k">Updated in last run<\/div><div class="meta__v" dir="auto">3<\/div>/);
	assert.match(view.html, /<div class="meta__k">Last crawl<\/div><div class="meta__v" dir="auto"><time/);
	// First data row.
	assert.match(view.html, /<td>10<\/td>\s*<td>2<\/td><td>3<\/td><td>100<\/td>/);
	// Second (empty) row → zeros.
	assert.match(view.html, /<td>0<\/td>\s*(?:<td>0<\/td>){3}/);
	// Two rows joined with "" → first row's </tr> meets the second row (kills the .join("")).
	assert.match(view.html, /<\/tr>\s*<tr>/);
});

test("viewCrawler: a response with no results array renders an empty table body", async () => {
	// data.results undefined → the `|| []` fallback must stay empty (no phantom row).
	api.apiGet.mockResolvedValue({});
	const view = await viewCrawler();
	assert.match(view.html, /<tbody><\/tbody>/);
});

test("viewCrawler: no runs → dash meta, zero urls and an empty table body", async () => {
	api.apiGet.mockRejectedValue(new Error("x"));
	const view = await viewCrawler();
	assert.match(view.html, /<div class="meta__k">Last crawl<\/div><div class="meta__v" dir="auto">—<\/div>/);
	assert.match(view.html, /<div class="meta__k">URLs crawled<\/div><div class="meta__v" dir="auto">0<\/div>/);
	assert.match(view.html, /<tbody><\/tbody>/);
});

/* ---- targetHref -------------------------------------------------------- */

test("targetHref maps tool/list targets and returns null for everything else", () => {
	assert.equal(targetHref({ id: "x", type: "tool" }), "/tools/x");
	assert.equal(targetHref({ id: "y", type: "list" }), "/lists/y");
	assert.equal(targetHref({ id: "z", type: "other" }), null);
	assert.equal(targetHref({ type: "tool" }), null); // no id
	assert.equal(targetHref(null), null);
	assert.equal(targetHref(undefined), null);
});

/* ---- viewAudit --------------------------------------------------------- */

test("viewAudit: a linked tool entry and a static entry render who/action/target", async () => {
	api.apiGet.mockResolvedValue({
		results: [
			{
				user: { username: "mod" },
				action: "deleted",
				target: { id: "t1", type: "tool", label: "Tool 1" },
				timestamp: ISO
			},
			// user:{} (present, no username) → "System"; no target/action → "changed" + empty target.
			{ user: {}, timestamp: ISO }
		]
	});
	const view = await viewAudit();
	assert.equal(view.title, "Audit logs — Toolhub");
	assert.deepEqual(api.apiGet.mock.calls[0], ["/auditlogs/", { page_size: "25" }]);
	const store = await import("../../public_html/lib/core/store.js");
	assert.equal(store.demoFeed.mock.calls.at(-1)[0], DEMO_KEYS.auditlogs);
	assert.match(view.html, /<li><a href="\/tools\/t1"><svg class="icon feed__ic"/);
	assert.match(view.html, /<span dir="auto">mod<\/span> <em>deleted<\/em> <span dir="auto">tool “Tool 1”<\/span>/);
	assert.match(view.html, /<time class="feed__when" datetime="2019-01-01T00:00:00\.000Z"/);
	// Static (target-less) row with System/changed defaults.
	assert.match(view.html, /<li><div class="feed__static"><svg/);
	assert.match(view.html, /<span dir="auto">System<\/span> <em>changed<\/em> <span dir="auto"><\/span>/);
	// Two rows joined with "" → adjacent <li>s (kills the rows .join("") separator).
	assert.match(view.html, /<\/li><li>/);
});

test("viewAudit: no entries → the empty placeholder", async () => {
	api.apiGet.mockRejectedValue(new Error("x"));
	const view = await viewAudit();
	assert.match(view.html, /<ul class="feed"><li><div class="feed__static">No audit entries\.<\/div><\/li><\/ul>/);
});

test("viewAudit: a response with no results array also shows the placeholder", async () => {
	// data.results undefined → the `|| []` fallback must stay empty (no phantom entry).
	api.apiGet.mockResolvedValue({});
	const view = await viewAudit();
	assert.match(view.html, /No audit entries\./);
});
