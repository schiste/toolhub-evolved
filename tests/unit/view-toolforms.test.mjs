// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import fs from "node:fs";
import { test, vi, beforeEach, afterEach } from "vitest";

const SCRATCH =
	"/private/tmp/claude-501/-Users-christophehenner-Downloads-Wikimedia-striker-toolhub-demo/bad07c6e-1967-4490-8d44-3fe4ee515e59/scratchpad";
const BAKE = process.env.BAKE === "1";

const h = vi.hoisted(() => ({
	getTool: vi.fn(),
	isNewTool: vi.fn(),
	newToolBase: vi.fn(),
	navigateTo: vi.fn(),
	getSimilarityIndex: vi.fn(),
	nearestNeighbors: vi.fn(),
	crawlerUrls: vi.fn(),
	crawlerUrlAdd: vi.fn(),
	crawlerUrlDelete: vi.fn(),
	ingestToolinfo: vi.fn(),
	logActivity: vi.fn(),
	toolEditsMap: vi.fn(),
	toolAnnosMap: vi.fn(),
	toolNewMap: vi.fn(),
	demoStoreSet: vi.fn()
}));

vi.mock("../../public_html/lib/core/api.js", async (orig) => {
	const actual = await orig();
	return { ...actual, getTool: h.getTool, isNewTool: h.isNewTool, newToolBase: h.newToolBase };
});
vi.mock("../../public_html/lib/core/routing.js", async (orig) => {
	const actual = await orig();
	return { ...actual, navigateTo: h.navigateTo };
});
vi.mock("../../public_html/lib/core/similarity.js", async (orig) => {
	const actual = await orig();
	return { ...actual, getSimilarityIndex: h.getSimilarityIndex, nearestNeighbors: h.nearestNeighbors };
});
vi.mock("../../public_html/lib/core/store.js", async (orig) => {
	const actual = await orig();
	return {
		...actual,
		crawlerUrls: h.crawlerUrls,
		crawlerUrlAdd: h.crawlerUrlAdd,
		crawlerUrlDelete: h.crawlerUrlDelete,
		ingestToolinfo: h.ingestToolinfo,
		logActivity: h.logActivity,
		toolEditsMap: h.toolEditsMap,
		toolAnnosMap: h.toolAnnosMap,
		toolNewMap: h.toolNewMap,
		demoStore: { set: h.demoStoreSet, get: () => null }
	};
});
vi.mock("../../public_html/lib/core/i18n.js", async (orig) => {
	const actual = await orig();
	return {
		...actual,
		updatedTimeTag: (iso, cls) => `<u|${iso ?? ""}|${cls ?? ""}>`,
		timeTag: (iso, cls, text) => `<t|${iso ?? ""}|${cls ?? ""}|${text ?? ""}>`
	};
});

const tf = await import("../../public_html/views/toolforms.js");
const { viewNotFound } = await import("../../public_html/views/static.js");
const { DEMO_KEYS, SAMPLE_TOOLINFO } = await import("../../public_html/lib/core/store.js");

const S = {
	addtools: `
	<div class="container page at">
		<div class="section-head"><h1 class="page__title">Add or remove tools <span class="exp-badge">Experimental</span></h1>
			<a class="btn btn--primary btn--md" href="/tools/create"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.005 9H16v2h-4.995v5.005h-2V11H4V9h5.005V4.005h2z"/></svg> Submit a tool</a></div>
		<p class="page__intro">Register a <code>toolinfo.json</code> URL, or paste/ingest toolinfo to add records.
		Everything stays in this browser — see <a href="/rules-of-engagement">Rules of Engagement</a>.</p>

		<h2 class="le__h2">Register a toolinfo.json URL</h2>
		<form class="le__add" data-url-form novalidate>
			<label class="le__label">toolinfo.json URL
		 <span class="le__hint" id="at-url-hint">Full public URL the crawler should re-read, usually ending in toolinfo.json.</span>
		<input class="le__input" id="at-url" type="url" aria-describedby="at-url-hint at-url-err" maxlength="300" value="" placeholder="https://example.org/toolinfo.json" /><span class="le__error" id="at-url-err" hidden></span></label>
			<button class="btn btn--outline btn--md" type="submit">Register</button>
		</form>
		<ul class="at__urls" data-url-list><li><code class="at__url">https://a.example/toolinfo.json</code> <button class="btn btn--icon btn--sm at__rm" aria-label="Remove URL" type="button" data-url-rm="https://a.example/toolinfo.json"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M16.707 4.707 11.414 10l5.293 5.293-1.414 1.414L10 11.414l-5.293 5.293-1.414-1.414L8.586 10 3.293 4.707l1.414-1.414L10 8.586l5.293-5.293z"/></svg></button></li><li><code class="at__url">https://b.example/toolinfo.json</code> <button class="btn btn--icon btn--sm at__rm" aria-label="Remove URL" type="button" data-url-rm="https://b.example/toolinfo.json"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M16.707 4.707 11.414 10l5.293 5.293-1.414 1.414L10 11.414l-5.293 5.293-1.414-1.414L8.586 10 3.293 4.707l1.414-1.414L10 8.586l5.293-5.293z"/></svg></button></li></ul>

		<h2 class="le__h2">Ingest toolinfo</h2>
		<label class="le__label">Toolinfo JSON <span class="le__hint" id="at-json-hint">Paste one tool object or an array; successful entries appear below in Your tools.</span>
		<textarea class="le__input at__json" id="at-json" rows="10" aria-describedby="at-json-hint" placeholder="{ &quot;name&quot;: &quot;my-tool&quot;, &quot;title&quot;: &quot;My Tool&quot;, &quot;description&quot;: &quot;…&quot;, &quot;url&quot;: &quot;https://…&quot; }"></textarea></label>
		<div class="le__actions">
			<button class="btn btn--primary btn--md" type="button" data-ingest>Ingest</button>
			<button class="btn btn--outline btn--md" type="button" data-sample>Load sample</button>
		</div>
		<p class="at__result" data-ingest-result aria-live="polite"></p>

		<h2 class="le__h2">Your tools <span class="le__count" data-sub-count></span></h2>
		<div data-sub-grid><ul class="card-grid grid-tools" role="list"><li>
	<article class="tcard" data-tool="sub-1">
		
		<div class="tcard__head">
			<span class="avatar " style="background:var(--color-favorite)" aria-hidden="true">S</span>
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="sub-1" aria-label="Quick look: Sub One" style="appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;" dir="auto">Sub One</button>
				<div class="tcard__maint">by <span></span></div>
			</div>
		</div>
		<p class="tcard__desc"></p>
		<div class="tcard__tags"></div>
		<div class="tcard__signals"><span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span></div>
		<div class="tcard__foot"><span class="tcard__meta" dir="auto">Any wiki</span><span class="tcard__footr"><u||tcard__when></span></div>
		<svg class="icon tcard__hint" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M8 1a7 7 0 015.605 11.191l5.102 5.102-1.414 1.414-5.102-5.102A7 7 0 118 1m0 2a5 5 0 100 10A5 5 0 008 3"/></svg>
	</article></li></ul></div>
	</div>`,
	addtools_empty: `
	<div class="container page at">
		<div class="section-head"><h1 class="page__title">Add or remove tools <span class="exp-badge">Experimental</span></h1>
			<a class="btn btn--primary btn--md" href="/tools/create"><svg class="icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path d="M11.005 9H16v2h-4.995v5.005h-2V11H4V9h5.005V4.005h2z"/></svg> Submit a tool</a></div>
		<p class="page__intro">Register a <code>toolinfo.json</code> URL, or paste/ingest toolinfo to add records.
		Everything stays in this browser — see <a href="/rules-of-engagement">Rules of Engagement</a>.</p>

		<h2 class="le__h2">Register a toolinfo.json URL</h2>
		<form class="le__add" data-url-form novalidate>
			<label class="le__label">toolinfo.json URL
		 <span class="le__hint" id="at-url-hint">Full public URL the crawler should re-read, usually ending in toolinfo.json.</span>
		<input class="le__input" id="at-url" type="url" aria-describedby="at-url-hint at-url-err" maxlength="300" value="" placeholder="https://example.org/toolinfo.json" /><span class="le__error" id="at-url-err" hidden></span></label>
			<button class="btn btn--outline btn--md" type="submit">Register</button>
		</form>
		<ul class="at__urls" data-url-list><li class="le__empty">No URLs registered.</li></ul>

		<h2 class="le__h2">Ingest toolinfo</h2>
		<label class="le__label">Toolinfo JSON <span class="le__hint" id="at-json-hint">Paste one tool object or an array; successful entries appear below in Your tools.</span>
		<textarea class="le__input at__json" id="at-json" rows="10" aria-describedby="at-json-hint" placeholder="{ &quot;name&quot;: &quot;my-tool&quot;, &quot;title&quot;: &quot;My Tool&quot;, &quot;description&quot;: &quot;…&quot;, &quot;url&quot;: &quot;https://…&quot; }"></textarea></label>
		<div class="le__actions">
			<button class="btn btn--primary btn--md" type="button" data-ingest>Ingest</button>
			<button class="btn btn--outline btn--md" type="button" data-sample>Load sample</button>
		</div>
		<p class="at__result" data-ingest-result aria-live="polite"></p>

		<h2 class="le__h2">Your tools <span class="le__count" data-sub-count></span></h2>
		<div data-sub-grid><p class="empty">No tools yet. Submit one above, or ingest sample toolinfo.</p></div>
	</div>`,
	anno: `
	<div class="container page le">
		<a class="back" href="/tools/my-tool">← Back to My Tool</a>
		<h1 class="page__title">Edit annotations <span class="exp-badge">Experimental</span></h1>
		<p class="page__intro">Community annotations enrich a tool without touching its core data. Saved only in
		this browser — see <a href="/rules-of-engagement">Rules of Engagement</a>.</p>
		<form data-anno-form>
			<h2 class="le__h2">Community annotations for <span dir="auto">My Tool</span></h2>
			<label class="le__label">Audiences (comma-separated)
		 <span class="le__hint" id="an-aud-hint">User groups this tool serves, such as editors, admins, researchers, or developers.</span>
		<input class="le__input" id="an-aud" type="text" aria-describedby="an-aud-hint an-aud-err" maxlength="300" value="editor"  /><span class="le__error" id="an-aud-err" hidden></span></label>
			<label class="le__label">Tasks (comma-separated)
		 <span class="le__hint" id="an-tasks-hint">Workflows this tool supports, such as editing, patrolling, importing, or analysis.</span>
		<input class="le__input" id="an-tasks" type="text" aria-describedby="an-tasks-hint an-tasks-err" maxlength="300" value="editing"  /><span class="le__error" id="an-tasks-err" hidden></span></label>
			<label class="le__label">Tool type <span class="le__hint" id="an-type-hint">Community classification used for discovery when core metadata is sparse.</span>
		<select class="le__input" id="an-type" aria-describedby="an-type-hint"><option value="" selected>—</option><option value="web app">web app</option><option value="desktop app">desktop app</option><option value="bot">bot</option><option value="gadget">gadget</option><option value="user script">user script</option><option value="command line tool">command line tool</option><option value="coding framework">coding framework</option><option value="lua module">lua module</option><option value="template">template</option><option value="other">other</option></select></label>
			<label class="le__label">Icon (Commons File: URL)
		 <span class="le__hint" id="an-icon-hint">Optional Commons-hosted image URL for visual identification.</span>
		<input class="le__input" id="an-icon" type="url" aria-describedby="an-icon-hint an-icon-err" maxlength="300" value=""  /><span class="le__error" id="an-icon-err" hidden></span></label>
			<div class="le__actions">
				<button class="btn btn--primary btn--md" type="submit">Save annotations</button>
				<button class="btn btn--danger btn--md le__delete" type="button" data-an-revert>Revert annotations</button>
			</div>
		</form>
	</div>`,
	anno_norevert: `
	<div class="container page le">
		<a class="back" href="/tools/my-tool">← Back to My Tool</a>
		<h1 class="page__title">Edit annotations <span class="exp-badge">Experimental</span></h1>
		<p class="page__intro">Community annotations enrich a tool without touching its core data. Saved only in
		this browser — see <a href="/rules-of-engagement">Rules of Engagement</a>.</p>
		<form data-anno-form>
			<h2 class="le__h2">Community annotations for <span dir="auto">My Tool</span></h2>
			<label class="le__label">Audiences (comma-separated)
		 <span class="le__hint" id="an-aud-hint">User groups this tool serves, such as editors, admins, researchers, or developers.</span>
		<input class="le__input" id="an-aud" type="text" aria-describedby="an-aud-hint an-aud-err" maxlength="300" value=""  /><span class="le__error" id="an-aud-err" hidden></span></label>
			<label class="le__label">Tasks (comma-separated)
		 <span class="le__hint" id="an-tasks-hint">Workflows this tool supports, such as editing, patrolling, importing, or analysis.</span>
		<input class="le__input" id="an-tasks" type="text" aria-describedby="an-tasks-hint an-tasks-err" maxlength="300" value=""  /><span class="le__error" id="an-tasks-err" hidden></span></label>
			<label class="le__label">Tool type <span class="le__hint" id="an-type-hint">Community classification used for discovery when core metadata is sparse.</span>
		<select class="le__input" id="an-type" aria-describedby="an-type-hint"><option value="" selected>—</option><option value="web app">web app</option><option value="desktop app">desktop app</option><option value="bot">bot</option><option value="gadget">gadget</option><option value="user script">user script</option><option value="command line tool">command line tool</option><option value="coding framework">coding framework</option><option value="lua module">lua module</option><option value="template">template</option><option value="other">other</option></select></label>
			<label class="le__label">Icon (Commons File: URL)
		 <span class="le__hint" id="an-icon-hint">Optional Commons-hosted image URL for visual identification.</span>
		<input class="le__input" id="an-icon" type="url" aria-describedby="an-icon-hint an-icon-err" maxlength="300" value=""  /><span class="le__error" id="an-icon-err" hidden></span></label>
			<div class="le__actions">
				<button class="btn btn--primary btn--md" type="submit">Save annotations</button>
				
			</div>
		</form>
	</div>`,
	create: `
	<div class="container page le">
		<a class="back" href="/add-or-remove-tools">← Back</a>
		<h1 class="page__title">Submit a tool <span class="exp-badge">Experimental</span></h1>
		<p class="page__intro">Changes are saved only in this browser — see <a href="/rules-of-engagement">Rules of Engagement</a>.
		</p>
		<form data-tool-form novalidate>
			<h2 class="le__h2">Core information</h2>
			<label class="le__label">Name (unique id) <span class="le__req">*</span>
		 <span class="le__hint" id="tf-name-hint">Stable lowercase id used in Toolhub URLs; it cannot be changed later.</span>
		<input class="le__input" id="tf-name" type="text" required aria-describedby="tf-name-hint tf-name-err" maxlength="120" value="" placeholder="my-cool-tool" /><span class="le__error" id="tf-name-err" hidden></span></label>
			<label class="le__label">Title <span class="le__req">*</span>
		 <span class="le__hint" id="tf-title-hint">Short public name shown in search results and tool pages.</span>
		<input class="le__input" id="tf-title" type="text" required aria-describedby="tf-title-hint tf-title-err" maxlength="300" value=""  /><span class="le__error" id="tf-title-err" hidden></span></label>
			<label class="le__label">Description <span class="le__hint" id="tf-desc-hint">One or two useful sentences: what it does, who it helps, and when to use it.</span>
		<textarea class="le__input" id="tf-desc" rows="3" aria-describedby="tf-desc-hint" maxlength="2000"></textarea></label>
			<label class="le__label">URL <span class="le__req">*</span>
		 <span class="le__hint" id="tf-url-hint">Primary place people launch the tool or read its documentation.</span>
		<input class="le__input" id="tf-url" type="url" required aria-describedby="tf-url-hint tf-url-err" maxlength="300" value="" placeholder="https://…" /><span class="le__error" id="tf-url-err" hidden></span></label>
			<label class="le__label">Source code repository
		 <span class="le__hint" id="tf-repo-hint">Optional public repository where contributors can inspect or patch the code.</span>
		<input class="le__input" id="tf-repo" type="url" aria-describedby="tf-repo-hint tf-repo-err" maxlength="300" value=""  /><span class="le__error" id="tf-repo-err" hidden></span></label>
			<label class="le__label">License (SPDX id)
		 <span class="le__hint" id="tf-license-hint">Use an SPDX identifier when known; leave blank if the license is unknown.</span>
		<input class="le__input" id="tf-license" type="text" aria-describedby="tf-license-hint tf-license-err" maxlength="300" value="" placeholder="GPL-3.0-or-later" /><span class="le__error" id="tf-license-err" hidden></span></label>
			<label class="le__label">Tool type <span class="le__hint" id="tf-type-hint">Choose the closest match; community annotations can refine discovery later.</span>
		<select class="le__input" id="tf-type" aria-describedby="tf-type-hint"><option value="" selected>—</option><option value="web app">web app</option><option value="desktop app">desktop app</option><option value="bot">bot</option><option value="gadget">gadget</option><option value="user script">user script</option><option value="command line tool">command line tool</option><option value="coding framework">coding framework</option><option value="lua module">lua module</option><option value="template">template</option><option value="other">other</option></select></label>
			<label class="le__label">Keywords (comma-separated)
		 <span class="le__hint" id="tf-keywords-hint">Search terms people may try; avoid repeating only the title.</span>
		<input class="le__input" id="tf-keywords" type="text" aria-describedby="tf-keywords-hint tf-keywords-err" maxlength="300" value=""  /><span class="le__error" id="tf-keywords-err" hidden></span></label>
			<section class="dupes" data-dupes aria-labelledby="dupes-title" aria-live="polite" hidden>
		<h3 class="dupes__title" id="dupes-title">Possible duplicates</h3>
		<p class="dupes__note">These existing tools look similar — check before creating a duplicate.</p>
		<ul class="dupes__list" data-dupes-list></ul>
	</section>
			<label class="le__label">Works on wikis (comma-separated, * for all)
		 <span class="le__hint" id="tf-wikis-hint">Use wiki database names such as enwiki or commonswiki, or * for all wikis.</span>
		<input class="le__input" id="tf-wikis" type="text" aria-describedby="tf-wikis-hint tf-wikis-err" maxlength="300" value=""  /><span class="le__error" id="tf-wikis-err" hidden></span></label>
			<label class="le__label">Available UI languages (comma-separated codes)
		 <span class="le__hint" id="tf-langs-hint">BCP-47 / wiki language codes; saved values refresh the tool page immediately in this demo.</span>
		<input class="le__input" id="tf-langs" type="text" aria-describedby="tf-langs-hint tf-langs-err" maxlength="300" value="" placeholder="en, fr, de" /><span class="le__error" id="tf-langs-err" hidden></span></label>
			<div class="le__checks"><label class="le__check"><input type="checkbox" id="tf-deprecated" /> Deprecated</label><label class="le__check"><input type="checkbox" id="tf-experimental" /> Experimental</label></div>
			<div class="le__actions">
				<button class="btn btn--primary btn--md" type="submit">Submit tool</button>
				
				
			</div>
		</form>
	</div>`,
	dupes: `<li class="dupes__item">
		<a href="/tools/citation-helper">
			<span class="dupes__name" dir="auto">Citation Helper</span>
			<span class="dupes__meta">by <span dir="auto">Maint A</span></span>
		</a>
	</li><li class="dupes__item">
		<a href="/tools/name-cite">
			<span class="dupes__name" dir="auto">Other</span>
			<span class="dupes__meta">by <span dir="auto">Author B</span></span>
		</a>
	</li><li class="dupes__item">
		<a href="/tools/nomaint">
			<span class="dupes__name" dir="auto">Citation Two</span>
			<span class="dupes__meta">by <span dir="auto">Unknown maintainer</span></span>
		</a>
	</li><li class="dupes__item">
		<a href="/tools/near">
			<span class="dupes__name" dir="auto">Near</span>
			<span class="dupes__meta">by <span dir="auto">Unknown maintainer</span></span>
		</a>
	</li>`,
	edit_api: `
	<div class="container page le">
		<a class="back" href="/tools/my-tool">← Back</a>
		<h1 class="page__title">Edit tool <span class="exp-badge">Experimental</span></h1>
		<p class="page__intro">Changes are saved only in this browser — see <a href="/rules-of-engagement">Rules of Engagement</a>.
		</p>
		<form data-tool-form novalidate>
			<h2 class="le__h2">Core information</h2>
			<p class="le__ro">Name: <code>my-tool</code></p>
			<label class="le__label">Title <span class="le__req">*</span>
		 <span class="le__hint" id="tf-title-hint">Short public name shown in search results and tool pages.</span>
		<input class="le__input" id="tf-title" type="text" required aria-describedby="tf-title-hint tf-title-err" maxlength="300" value="My Tool"  /><span class="le__error" id="tf-title-err" hidden></span></label>
			<label class="le__label">Description <span class="le__hint" id="tf-desc-hint">One or two useful sentences: what it does, who it helps, and when to use it.</span>
		<textarea class="le__input" id="tf-desc" rows="3" aria-describedby="tf-desc-hint" maxlength="2000">desc</textarea></label>
			<label class="le__label">URL <span class="le__req">*</span>
		 <span class="le__hint" id="tf-url-hint">Primary place people launch the tool or read its documentation.</span>
		<input class="le__input" id="tf-url" type="url" required aria-describedby="tf-url-hint tf-url-err" maxlength="300" value="https://x.example" placeholder="https://…" /><span class="le__error" id="tf-url-err" hidden></span></label>
			<label class="le__label">Source code repository
		 <span class="le__hint" id="tf-repo-hint">Optional public repository where contributors can inspect or patch the code.</span>
		<input class="le__input" id="tf-repo" type="url" aria-describedby="tf-repo-hint tf-repo-err" maxlength="300" value="https://r.example"  /><span class="le__error" id="tf-repo-err" hidden></span></label>
			<label class="le__label">License (SPDX id)
		 <span class="le__hint" id="tf-license-hint">Use an SPDX identifier when known; leave blank if the license is unknown.</span>
		<input class="le__input" id="tf-license" type="text" aria-describedby="tf-license-hint tf-license-err" maxlength="300" value="MIT" placeholder="GPL-3.0-or-later" /><span class="le__error" id="tf-license-err" hidden></span></label>
			<label class="le__label">Tool type <span class="le__hint" id="tf-type-hint">Choose the closest match; community annotations can refine discovery later.</span>
		<select class="le__input" id="tf-type" aria-describedby="tf-type-hint"><option value="">—</option><option value="web app">web app</option><option value="desktop app">desktop app</option><option value="bot" selected>bot</option><option value="gadget">gadget</option><option value="user script">user script</option><option value="command line tool">command line tool</option><option value="coding framework">coding framework</option><option value="lua module">lua module</option><option value="template">template</option><option value="other">other</option></select></label>
			<label class="le__label">Keywords (comma-separated)
		 <span class="le__hint" id="tf-keywords-hint">Search terms people may try; avoid repeating only the title.</span>
		<input class="le__input" id="tf-keywords" type="text" aria-describedby="tf-keywords-hint tf-keywords-err" maxlength="300" value="k1, k2"  /><span class="le__error" id="tf-keywords-err" hidden></span></label>
			
			<label class="le__label">Works on wikis (comma-separated, * for all)
		 <span class="le__hint" id="tf-wikis-hint">Use wiki database names such as enwiki or commonswiki, or * for all wikis.</span>
		<input class="le__input" id="tf-wikis" type="text" aria-describedby="tf-wikis-hint tf-wikis-err" maxlength="300" value="enwiki"  /><span class="le__error" id="tf-wikis-err" hidden></span></label>
			<label class="le__label">Available UI languages (comma-separated codes)
		 <span class="le__hint" id="tf-langs-hint">BCP-47 / wiki language codes; saved values refresh the tool page immediately in this demo.</span>
		<input class="le__input" id="tf-langs" type="text" aria-describedby="tf-langs-hint tf-langs-err" maxlength="300" value="en" placeholder="en, fr, de" /><span class="le__error" id="tf-langs-err" hidden></span></label>
			<div class="le__checks"><label class="le__check"><input type="checkbox" id="tf-deprecated" /> Deprecated</label><label class="le__check"><input type="checkbox" id="tf-experimental" /> Experimental</label></div>
			<div class="le__actions">
				<button class="btn btn--primary btn--md" type="submit">Save changes</button>
				<button class="btn btn--danger btn--md le__delete" type="button" data-tf-revert>Revert demo edits</button>
				
			</div>
		</form>
	</div>`,
	edit_crawler_new: `
	<div class="container page le">
		<a class="back" href="/tools/crawled">← Back</a>
		<h1 class="page__title">Edit tool <span class="exp-badge">Experimental</span></h1>
		<p class="page__intro">Changes are saved only in this browser — see <a href="/rules-of-engagement">Rules of Engagement</a>.
		In production, core fields of crawler-imported tools are owned by the maintainer's <code>toolinfo.json</code>; only <code>origin=api</code> tools are core-editable. This demo lets you edit anyway.</p>
		<form data-tool-form novalidate>
			<h2 class="le__h2">Core information</h2>
			<p class="le__ro">Name: <code>crawled</code></p>
			<label class="le__label">Title <span class="le__req">*</span>
		 <span class="le__hint" id="tf-title-hint">Short public name shown in search results and tool pages.</span>
		<input class="le__input" id="tf-title" type="text" required aria-describedby="tf-title-hint tf-title-err" maxlength="300" value="Crawled"  /><span class="le__error" id="tf-title-err" hidden></span></label>
			<label class="le__label">Description <span class="le__hint" id="tf-desc-hint">One or two useful sentences: what it does, who it helps, and when to use it.</span>
		<textarea class="le__input" id="tf-desc" rows="3" aria-describedby="tf-desc-hint" maxlength="2000"></textarea></label>
			<label class="le__label">URL <span class="le__req">*</span>
		 <span class="le__hint" id="tf-url-hint">Primary place people launch the tool or read its documentation.</span>
		<input class="le__input" id="tf-url" type="url" required aria-describedby="tf-url-hint tf-url-err" maxlength="300" value="" placeholder="https://…" /><span class="le__error" id="tf-url-err" hidden></span></label>
			<label class="le__label">Source code repository
		 <span class="le__hint" id="tf-repo-hint">Optional public repository where contributors can inspect or patch the code.</span>
		<input class="le__input" id="tf-repo" type="url" aria-describedby="tf-repo-hint tf-repo-err" maxlength="300" value=""  /><span class="le__error" id="tf-repo-err" hidden></span></label>
			<label class="le__label">License (SPDX id)
		 <span class="le__hint" id="tf-license-hint">Use an SPDX identifier when known; leave blank if the license is unknown.</span>
		<input class="le__input" id="tf-license" type="text" aria-describedby="tf-license-hint tf-license-err" maxlength="300" value="" placeholder="GPL-3.0-or-later" /><span class="le__error" id="tf-license-err" hidden></span></label>
			<label class="le__label">Tool type <span class="le__hint" id="tf-type-hint">Choose the closest match; community annotations can refine discovery later.</span>
		<select class="le__input" id="tf-type" aria-describedby="tf-type-hint"><option value="" selected>—</option><option value="web app">web app</option><option value="desktop app">desktop app</option><option value="bot">bot</option><option value="gadget">gadget</option><option value="user script">user script</option><option value="command line tool">command line tool</option><option value="coding framework">coding framework</option><option value="lua module">lua module</option><option value="template">template</option><option value="other">other</option></select></label>
			<label class="le__label">Keywords (comma-separated)
		 <span class="le__hint" id="tf-keywords-hint">Search terms people may try; avoid repeating only the title.</span>
		<input class="le__input" id="tf-keywords" type="text" aria-describedby="tf-keywords-hint tf-keywords-err" maxlength="300" value=""  /><span class="le__error" id="tf-keywords-err" hidden></span></label>
			
			<label class="le__label">Works on wikis (comma-separated, * for all)
		 <span class="le__hint" id="tf-wikis-hint">Use wiki database names such as enwiki or commonswiki, or * for all wikis.</span>
		<input class="le__input" id="tf-wikis" type="text" aria-describedby="tf-wikis-hint tf-wikis-err" maxlength="300" value=""  /><span class="le__error" id="tf-wikis-err" hidden></span></label>
			<label class="le__label">Available UI languages (comma-separated codes)
		 <span class="le__hint" id="tf-langs-hint">BCP-47 / wiki language codes; saved values refresh the tool page immediately in this demo.</span>
		<input class="le__input" id="tf-langs" type="text" aria-describedby="tf-langs-hint tf-langs-err" maxlength="300" value="" placeholder="en, fr, de" /><span class="le__error" id="tf-langs-err" hidden></span></label>
			<div class="le__checks"><label class="le__check"><input type="checkbox" id="tf-deprecated" /> Deprecated</label><label class="le__check"><input type="checkbox" id="tf-experimental" /> Experimental</label></div>
			<div class="le__actions">
				<button class="btn btn--primary btn--md" type="submit">Save changes</button>
				
				<button class="btn btn--danger btn--md le__delete" type="button" data-tf-delete>Delete submission</button>
			</div>
		</form>
	</div>`
};

function expect(name, actual) {
	if (BAKE) {
		fs.writeFileSync(`${SCRATCH}/toolforms__${name}.txt`, actual);
		return;
	}
	assert.equal(actual, S[name], name);
}

function toolFixture(name, o = {}) {
	return {
		name,
		title: o.title ?? name,
		description: o.description ?? "",
		url: o.url ?? "",
		repository: o.repository ?? null,
		license: o.license ?? null,
		toolType: o.toolType ?? null,
		keywords: o.keywords ?? [],
		forWikis: o.forWikis ?? [],
		uiLanguages: o.uiLanguages ?? [],
		audiences: o.audiences ?? [],
		tasks: o.tasks ?? [],
		icon: o.icon ?? null,
		deprecated: o.deprecated ?? false,
		experimental: o.experimental ?? false,
		origin: o.origin ?? "api",
		...o
	};
}

beforeEach(() => {
	localStorage.clear();
	document.body.innerHTML = "";
	for (const fn of Object.values(h)) fn.mockReset();
	h.isNewTool.mockReturnValue(false);
	h.crawlerUrls.mockReturnValue([]);
	h.toolNewMap.mockReturnValue({});
	h.toolEditsMap.mockReturnValue({});
	h.toolAnnosMap.mockReturnValue({});
});

afterEach(() => {
	vi.useRealTimers();
});

/* ---------------- viewToolForm render ---------------- */

test("viewToolForm create", async () => {
	const r = await tf.viewToolForm(null);
	assert.equal(r.title, "Submit a tool — Toolhub");
	expect("create", r.html);
});

test("viewToolForm edit (api origin, existing tool) → revert button, no crawler note", async () => {
	h.getTool.mockResolvedValue(
		toolFixture("my-tool", {
			title: "My Tool",
			description: "desc",
			url: "https://x.example",
			repository: "https://r.example",
			license: "MIT",
			toolType: "bot",
			keywords: ["k1", "k2"],
			forWikis: ["enwiki"],
			uiLanguages: ["en"],
			origin: "api"
		})
	);
	h.isNewTool.mockReturnValue(false);
	const r = await tf.viewToolForm("my-tool");
	assert.equal(r.title, "Edit tool — Toolhub");
	expect("edit_api", r.html);
});

test("viewToolForm edit (crawler origin + new tool) → crawler note + delete button", async () => {
	h.getTool.mockResolvedValue(toolFixture("crawled", { title: "Crawled", origin: "crawler" }));
	h.isNewTool.mockReturnValue(true);
	const r = await tf.viewToolForm("crawled");
	expect("edit_crawler_new", r.html);
});

test("viewToolForm edit not found → viewNotFound", async () => {
	h.getTool.mockResolvedValue(null);
	const r = await tf.viewToolForm("ghost");
	assert.deepEqual(r, viewNotFound());
});

/* ---------------- viewAddTools render ---------------- */

test("viewAddTools with urls + submissions", async () => {
	// two URLs so urlRows().join("") is observable (a join("X") mutant inserts X between <li>s)
	h.crawlerUrls.mockReturnValue([
		{ url: "https://a.example/toolinfo.json" },
		{ url: "https://b.example/toolinfo.json" }
	]);
	h.toolNewMap.mockReturnValue({ "sub-1": {} });
	h.newToolBase.mockReturnValue(toolFixture("sub-1", { title: "Sub One" }));
	const r = tf.viewAddTools();
	assert.equal(r.title, "Add or remove tools — Toolhub");
	expect("addtools", r.html);
});

test("viewAddTools empty", async () => {
	h.crawlerUrls.mockReturnValue([]);
	h.toolNewMap.mockReturnValue({});
	const r = tf.viewAddTools();
	expect("addtools_empty", r.html);
});

/* ---------------- viewAnnotationsEdit render ---------------- */

test("viewAnnotationsEdit with existing annotation → revert button", async () => {
	h.getTool.mockResolvedValue(
		toolFixture("my-tool", { title: "My Tool", audiences: ["editor"], tasks: ["editing"] })
	);
	h.toolAnnosMap.mockReturnValue({ "my-tool": {} });
	const r = await tf.viewAnnotationsEdit("my-tool");
	assert.equal(r.title, "Edit annotations — Toolhub");
	expect("anno", r.html);
});

test("viewAnnotationsEdit without annotation → no revert", async () => {
	h.getTool.mockResolvedValue(toolFixture("my-tool", { title: "My Tool" }));
	h.toolAnnosMap.mockReturnValue({});
	const r = await tf.viewAnnotationsEdit("my-tool");
	expect("anno_norevert", r.html);
});

test("viewAnnotationsEdit not found → viewNotFound", async () => {
	h.getTool.mockResolvedValue(null);
	const r = await tf.viewAnnotationsEdit("ghost");
	assert.deepEqual(r, viewNotFound());
});

/* ---------------- viewToolForm mount ---------------- */

async function mountToolForm(name) {
	const r = await tf.viewToolForm(name);
	document.body.innerHTML = r.html;
	r.mount();
	return r;
}
function setVal(id, v) {
	document.querySelector(`#${id}`).value = v;
}
// advance past the 300ms debounce on fake timers and flush the async update
async function flushDebounce() {
	await vi.advanceTimersByTimeAsync(350);
}

test("mount create: full valid submit saves a new tool and navigates", async () => {
	h.isNewTool.mockReturnValue(false);
	await mountToolForm(null);
	setVal("tf-name", "new-tool");
	setVal("tf-title", "New Tool");
	setVal("tf-url", "https://example.org");
	setVal("tf-desc", "A description");
	setVal("tf-repo", "https://repo.example");
	setVal("tf-license", "MIT");
	setVal("tf-keywords", "a, b");
	setVal("tf-wikis", "enwiki");
	setVal("tf-langs", "en, fr");
	document.querySelector("#tf-deprecated").checked = true;
	document.querySelector("[data-tool-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(h.demoStoreSet.mock.calls.length, 1);
	assert.equal(h.demoStoreSet.mock.calls[0][0], DEMO_KEYS.toolNew);
	const saved = h.demoStoreSet.mock.calls[0][1]["new-tool"];
	assert.deepEqual(saved, {
		title: "New Tool",
		description: "A description",
		url: "https://example.org",
		repository: "https://repo.example",
		license: "MIT",
		toolType: null,
		keywords: ["a", "b"],
		forWikis: ["enwiki"],
		uiLanguages: ["en", "fr"],
		deprecated: true,
		experimental: false
	});
	assert.deepEqual(h.logActivity.mock.calls[0], ["created", "new-tool", "New Tool"]);
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/tools/new-tool"]);
});

test("mount edit: valid submit saves edits and logs 'edited'", async () => {
	h.getTool.mockResolvedValue(toolFixture("my-tool", { title: "My Tool", url: "https://x.example", origin: "api" }));
	h.isNewTool.mockReturnValue(false);
	await mountToolForm("my-tool");
	setVal("tf-title", "Renamed");
	setVal("tf-url", "https://x.example");
	document.querySelector("[data-tool-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(h.demoStoreSet.mock.calls[0][0], DEMO_KEYS.toolEdits);
	assert.deepEqual(h.logActivity.mock.calls[0], ["edited", "my-tool", "Renamed"]);
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/tools/my-tool"]);
});

test("mount edit of a NEW tool: submit logs 'created' and writes toolNew", async () => {
	h.getTool.mockResolvedValue(toolFixture("brand-new", { title: "Brand New", url: "https://x.example" }));
	h.isNewTool.mockReturnValue(true);
	await mountToolForm("brand-new");
	setVal("tf-title", "Brand New");
	setVal("tf-url", "https://x.example");
	document.querySelector("[data-tool-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(h.demoStoreSet.mock.calls[0][0], DEMO_KEYS.toolNew);
	assert.deepEqual(h.logActivity.mock.calls[0], ["edited", "brand-new", "Brand New"]);
});

test("mount create: missing name/title focuses the name field, no save", async () => {
	await mountToolForm(null);
	setVal("tf-title", ""); // missing
	setVal("tf-name", "");
	document.querySelector("[data-tool-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(h.demoStoreSet.mock.calls.length, 0);
	assert.equal(document.activeElement, document.querySelector("#tf-name"));
});

test("mount edit: missing title focuses the title field", async () => {
	h.getTool.mockResolvedValue(toolFixture("my-tool", { title: "T", url: "https://x.example" }));
	await mountToolForm("my-tool");
	setVal("tf-title", "");
	document.querySelector("[data-tool-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(document.activeElement, document.querySelector("#tf-title"));
});

test("mount create: invalid URL is rejected and focused", async () => {
	await mountToolForm(null);
	setVal("tf-name", "n");
	setVal("tf-title", "T");
	setVal("tf-url", "ftp://nope");
	document.querySelector("[data-tool-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(h.demoStoreSet.mock.calls.length, 0);
	assert.equal(document.activeElement, document.querySelector("#tf-url"));
});

test("mount create: invalid repository URL is rejected and focused", async () => {
	await mountToolForm(null);
	setVal("tf-name", "n");
	setVal("tf-title", "T");
	setVal("tf-url", "https://ok.example");
	setVal("tf-repo", "not-a-url");
	document.querySelector("[data-tool-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(h.demoStoreSet.mock.calls.length, 0);
	assert.equal(document.activeElement, document.querySelector("#tf-repo"));
});

test("mount create: duplicate name shows an error and does not save", async () => {
	h.isNewTool.mockReturnValue(true); // name already exists as a demo tool
	await mountToolForm(null);
	setVal("tf-name", "dupe");
	setVal("tf-title", "T");
	setVal("tf-url", "https://ok.example");
	document.querySelector("[data-tool-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(h.demoStoreSet.mock.calls.length, 0);
	assert.equal(document.activeElement, document.querySelector("#tf-name"));
	assert.ok(document.querySelector("#tf-name-err"), "field error rendered");
});

test("mount edit (existing): revert button clears the demo edit and navigates", async () => {
	h.getTool.mockResolvedValue(toolFixture("my-tool", { title: "T", url: "https://x.example", origin: "api" }));
	h.isNewTool.mockReturnValue(false);
	h.toolEditsMap.mockReturnValue({ "my-tool": { title: "edited" } });
	await mountToolForm("my-tool");
	document.querySelector("[data-tf-revert]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	assert.equal(h.demoStoreSet.mock.calls[0][0], DEMO_KEYS.toolEdits);
	assert.deepEqual(h.demoStoreSet.mock.calls[0][1], {}, "edit entry deleted");
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/tools/my-tool"]);
});

test("mount edit (new tool): delete button removes the submission and navigates", async () => {
	h.getTool.mockResolvedValue(toolFixture("brand-new", { title: "T", url: "https://x.example" }));
	h.isNewTool.mockReturnValue(true);
	h.toolNewMap.mockReturnValue({ "brand-new": {} });
	await mountToolForm("brand-new");
	document.querySelector("[data-tf-delete]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	assert.equal(h.demoStoreSet.mock.calls[0][0], DEMO_KEYS.toolNew);
	assert.deepEqual(h.demoStoreSet.mock.calls[0][1], {});
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/add-or-remove-tools"]);
});

test("mount create: typing keeps the URL error until the value becomes valid/empty", async () => {
	await mountToolForm(null);
	const url = document.querySelector("#tf-url");
	const err = document.querySelector("#tf-url-err");
	// Seed an error via a failed submit (invalid required URL).
	setVal("tf-name", "n");
	setVal("tf-title", "T");
	url.value = "ftp://nope";
	document.querySelector("[data-tool-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(err.hidden, false, "error shown after invalid submit");
	// Typing another invalid value does NOT clear it.
	url.value = "still-bad";
	url.dispatchEvent(new Event("input", { bubbles: true }));
	assert.equal(err.hidden, false, "invalid value keeps the error");
	// Typing a valid URL clears it.
	url.value = "https://ok.example";
	url.dispatchEvent(new Event("input", { bubbles: true }));
	assert.equal(err.hidden, true, "valid value clears the error");
	assert.equal(url.classList.contains("is-invalid"), false);
});

test("mount create: clearing the URL field also clears the error", async () => {
	await mountToolForm(null);
	const url = document.querySelector("#tf-url");
	const err = document.querySelector("#tf-url-err");
	setVal("tf-name", "n");
	setVal("tf-title", "T");
	url.value = "ftp://nope";
	document.querySelector("[data-tool-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(err.hidden, false);
	url.value = "   ";
	url.dispatchEvent(new Event("input", { bubbles: true }));
	assert.equal(err.hidden, true, "empty value clears the error");
});

/* duplicate suggestions (create only, debounced) */

test("mount create: duplicate suggestions render from title match + neighbors", async () => {
	vi.useFakeTimers();
	h.getSimilarityIndex.mockResolvedValue({
		tools: [toolFixture("citation-helper", { title: "Citation Helper" }), toolFixture("other", { title: "Other" })]
	});
	h.nearestNeighbors.mockReturnValue([{ tool: toolFixture("near-tool", { title: "Near Tool" }) }]);
	await mountToolForm(null);
	setVal("tf-title", "citation");
	document.querySelector("#tf-title").dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	const dupes = document.querySelector("[data-dupes]");
	assert.equal(dupes.hidden, false);
	const items = dupes.querySelectorAll("[data-dupes-list] .dupes__item");
	const names = new Set([...items].map((li) => li.querySelector(".dupes__name").textContent));
	assert.ok(names.has("Citation Helper"), "title match included");
	assert.ok(names.has("Near Tool"), "neighbor included");
	assert.ok(!names.has("Other"), "non-matching tool excluded");
});

test("mount create: no signal (empty title/keywords/type) hides duplicates", async () => {
	vi.useFakeTimers();
	h.getSimilarityIndex.mockResolvedValue({ tools: [toolFixture("x", { title: "X" })] });
	h.nearestNeighbors.mockReturnValue([]);
	await mountToolForm(null);
	document.querySelector("#tf-keywords").dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	assert.equal(document.querySelector("[data-dupes]").hidden, true);
	assert.equal(h.getSimilarityIndex.mock.calls.length, 0, "index not loaded with no signal");
});

test("mount create: keyword-only signal still queries neighbors", async () => {
	vi.useFakeTimers();
	h.getSimilarityIndex.mockResolvedValue({ tools: [] });
	h.nearestNeighbors.mockReturnValue([{ tool: toolFixture("kw-tool", { title: "KW Tool" }) }]);
	await mountToolForm(null);
	setVal("tf-keywords", "maps, charts");
	document.querySelector("#tf-keywords").dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	const names = [...document.querySelectorAll(".dupes__name")].map((n) => n.textContent);
	assert.deepEqual(names, ["KW Tool"]);
});

test("mount create: similarity index failure hides duplicates", async () => {
	vi.useFakeTimers();
	h.getSimilarityIndex.mockRejectedValue(new Error("down"));
	await mountToolForm(null);
	setVal("tf-title", "citation");
	document.querySelector("#tf-title").dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	assert.equal(document.querySelector("[data-dupes]").hidden, true);
});

test("mount create: index without a tools array hides duplicates", async () => {
	vi.useFakeTimers();
	h.getSimilarityIndex.mockResolvedValue({});
	await mountToolForm(null);
	setVal("tf-title", "citation");
	document.querySelector("#tf-title").dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	assert.equal(document.querySelector("[data-dupes]").hidden, true);
});

test("mount create: the tool being typed is excluded from duplicates by name", async () => {
	vi.useFakeTimers();
	h.getSimilarityIndex.mockResolvedValue({ tools: [toolFixture("my-tool", { title: "My Tool" })] });
	h.nearestNeighbors.mockReturnValue([{ tool: toolFixture("my-tool", { title: "My Tool" }) }]);
	await mountToolForm(null);
	setVal("tf-name", "my-tool");
	setVal("tf-title", "My Tool");
	document.querySelector("#tf-title").dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	assert.equal(document.querySelector("[data-dupes]").hidden, true, "self excluded → no dupes");
});

test("mount create: type change triggers suggestions", async () => {
	vi.useFakeTimers();
	h.getSimilarityIndex.mockResolvedValue({ tools: [] });
	h.nearestNeighbors.mockReturnValue([{ tool: toolFixture("typed", { title: "Typed" }) }]);
	await mountToolForm(null);
	document.querySelector("#tf-type").value = "bot";
	document.querySelector("#tf-type").dispatchEvent(new Event("change", { bubbles: true }));
	await flushDebounce();
	assert.ok([...document.querySelectorAll(".dupes__name")].some((n) => n.textContent === "Typed"));
});

/* ---------------- viewAddTools mount ---------------- */

test("mount addtools: register a valid url adds it and refreshes the list", () => {
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	h.crawlerUrls.mockReturnValue([{ url: "https://added.example/toolinfo.json" }]);
	setVal("at-url", "https://added.example/toolinfo.json");
	document.querySelector("[data-url-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.deepEqual(h.crawlerUrlAdd.mock.calls[0], ["https://added.example/toolinfo.json"]);
	assert.ok(document.querySelector("[data-url-list]").innerHTML.includes("https://added.example/toolinfo.json"));
	assert.equal(document.querySelector("#at-url").value, "", "input cleared");
});

test("mount addtools: invalid url is rejected (focused, not added)", () => {
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	setVal("at-url", "nope");
	document.querySelector("[data-url-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(h.crawlerUrlAdd.mock.calls.length, 0);
	assert.equal(document.activeElement, document.querySelector("#at-url"));
});

test("mount addtools: empty url submit is a no-op", () => {
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	setVal("at-url", "");
	document.querySelector("[data-url-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(h.crawlerUrlAdd.mock.calls.length, 0);
});

test("mount addtools: removing a url updates the list", () => {
	h.crawlerUrls.mockReturnValue([{ url: "https://x.example/toolinfo.json" }]);
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	h.crawlerUrls.mockReturnValue([]);
	document
		.querySelector('[data-url-rm="https://x.example/toolinfo.json"]')
		.dispatchEvent(new MouseEvent("click", { bubbles: true }));
	assert.deepEqual(h.crawlerUrlDelete.mock.calls[0], ["https://x.example/toolinfo.json"]);
	assert.ok(document.querySelector("[data-url-list]").innerHTML.includes("No URLs registered."));
});

test("mount addtools: url-list click outside a remove button is a no-op", () => {
	h.crawlerUrls.mockReturnValue([{ url: "https://x.example/toolinfo.json" }]);
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-url-list]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	assert.equal(h.crawlerUrlDelete.mock.calls.length, 0);
});

test("mount addtools: load sample fills the textarea", () => {
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-sample]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	assert.equal(document.querySelector("#at-json").value, SAMPLE_TOOLINFO);
});

test("mount addtools: ingest success shows summary and refreshes grid", () => {
	h.ingestToolinfo.mockReturnValue({ added: 2, updated: 1 }); // no `errors` key → exercises `res.errors || []`
	h.toolNewMap.mockReturnValue({ a: {}, b: {} });
	h.newToolBase.mockImplementation((n) => toolFixture(n, { title: n.toUpperCase() }));
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	setVal("at-json", '{"name":"x"}');
	document.querySelector("[data-ingest]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	const out = document.querySelector("[data-ingest-result]");
	assert.equal(out.textContent, "2 added, 1 updated");
	assert.equal(out.className, "at__result at__result--ok");
	assert.ok(document.querySelector("[data-sub-grid]").innerHTML.includes('data-tool="a"'));
	assert.equal(document.querySelector("[data-sub-count]").textContent, "2 tools");
});

test("mount addtools: ingest hard error shows error class", () => {
	h.ingestToolinfo.mockReturnValue({ error: "Invalid JSON" });
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	setVal("at-json", "garbage");
	document.querySelector("[data-ingest]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	const out = document.querySelector("[data-ingest-result]");
	assert.equal(out.textContent, "Invalid JSON");
	assert.equal(out.className, "at__result at__result--err");
});

test("mount addtools: ingest with only per-item errors marks error class", () => {
	h.ingestToolinfo.mockReturnValue({ added: 0, updated: 0, errors: ["bad item"] });
	h.toolNewMap.mockReturnValue({});
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	setVal("at-json", "[]");
	document.querySelector("[data-ingest]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	const out = document.querySelector("[data-ingest-result]");
	assert.equal(out.textContent, "Nothing ingested · bad item");
	assert.equal(out.className, "at__result at__result--err");
});

test("mount addtools: ingest with adds and per-item errors stays ok class", () => {
	h.ingestToolinfo.mockReturnValue({ added: 1, updated: 0, errors: ["bad item"] });
	h.toolNewMap.mockReturnValue({ a: {} });
	h.newToolBase.mockImplementation((n) => toolFixture(n, { title: n }));
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	setVal("at-json", "[]");
	document.querySelector("[data-ingest]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	const out = document.querySelector("[data-ingest-result]");
	assert.equal(out.textContent, "1 added · bad item");
	assert.equal(out.className, "at__result at__result--ok");
});

/* ---------------- viewAnnotationsEdit mount ---------------- */

test("mount annotations: submit saves annotation and navigates", async () => {
	h.getTool.mockResolvedValue(
		toolFixture("my-tool", { title: "My Tool", audiences: ["editor"], tasks: ["editing"] })
	);
	h.toolAnnosMap.mockReturnValue({});
	const r = await tf.viewAnnotationsEdit("my-tool");
	document.body.innerHTML = r.html;
	r.mount();
	setVal("an-aud", "editor, admin");
	setVal("an-tasks", "editing");
	document.querySelector("#an-type").value = "bot";
	setVal("an-icon", "https://commons.example/icon.png");
	document.querySelector("[data-anno-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(h.demoStoreSet.mock.calls[0][0], DEMO_KEYS.toolAnnos);
	assert.deepEqual(h.demoStoreSet.mock.calls[0][1]["my-tool"], {
		audiences: ["editor", "admin"],
		tasks: ["editing"],
		toolType: "bot",
		icon: "https://commons.example/icon.png"
	});
	assert.deepEqual(h.logActivity.mock.calls[0], ["annotated", "my-tool", "My Tool"]);
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/tools/my-tool"]);
});

test("mount annotations: revert deletes the annotation and navigates", async () => {
	h.getTool.mockResolvedValue(toolFixture("my-tool", { title: "My Tool" }));
	h.toolAnnosMap.mockReturnValue({ "my-tool": {} });
	const r = await tf.viewAnnotationsEdit("my-tool");
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-an-revert]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	assert.equal(h.demoStoreSet.mock.calls[0][0], DEMO_KEYS.toolAnnos);
	assert.deepEqual(h.demoStoreSet.mock.calls[0][1], {});
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/tools/my-tool"]);
});

/* ---- additional coverage ---- */

test("viewToolForm(undefined) is treated as create", async () => {
	const r = await tf.viewToolForm(undefined);
	assert.equal(r.title, "Submit a tool — Toolhub");
	assert.equal(h.getTool.mock.calls.length, 0, "create does not fetch a tool");
});

test("mount create: an http:// (not https) URL is accepted", async () => {
	h.isNewTool.mockReturnValue(false);
	await mountToolForm(null);
	setVal("tf-name", "n");
	setVal("tf-title", "T");
	setVal("tf-url", "http://insecure.example");
	document.querySelector("[data-tool-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(h.demoStoreSet.mock.calls.length, 1, "http URL passes validation");
	assert.deepEqual(h.navigateTo.mock.calls.at(-1), ["/tools/n"]);
});

test("mount create: duplicate list renders exact items (maintainer / authors / unknown)", async () => {
	vi.useFakeTimers();
	h.getSimilarityIndex.mockResolvedValue({
		tools: [
			toolFixture("citation-helper", { title: "Citation Helper", maintainer: "Maint A" }),
			toolFixture("name-cite", { title: "Other", authors: ["Author B"] }),
			toolFixture("nomaint", { title: "Citation Two" })
		]
	});
	// neighbor adds "near"; citation-helper repeated → must be de-duplicated
	h.nearestNeighbors.mockReturnValue([
		{ tool: toolFixture("near", { title: "Near" }) },
		{ tool: toolFixture("citation-helper", { title: "Citation Helper", maintainer: "Maint A" }) }
	]);
	await mountToolForm(null);
	setVal("tf-title", "cit");
	setVal("tf-keywords", "a, b");
	document.querySelector("#tf-title").dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	assert.equal(document.querySelector("[data-dupes]").hidden, false);
	expect("dupes", document.querySelector("[data-dupes-list]").innerHTML);
	// nearestNeighbors received the assembled partial query
	assert.deepEqual(h.nearestNeighbors.mock.calls[0][0], {
		keywords: ["a", "b"],
		forWikis: [],
		audiences: [],
		tasks: [],
		toolType: ""
	});
});

test("mount create: no signal clears the list and hides the region", async () => {
	vi.useFakeTimers();
	h.getSimilarityIndex.mockResolvedValue({ tools: [toolFixture("x", { title: "X" })] });
	await mountToolForm(null);
	// seed some content first via a title search, then clear it
	h.nearestNeighbors.mockReturnValue([{ tool: toolFixture("y", { title: "Y" }) }]);
	setVal("tf-title", "x");
	document.querySelector("#tf-title").dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	assert.equal(document.querySelector("[data-dupes]").hidden, false);
	// now no signal
	setVal("tf-title", "");
	document.querySelector("#tf-title").dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	const box = document.querySelector("[data-dupes]");
	assert.equal(box.hidden, true);
	assert.equal(document.querySelector("[data-dupes-list]").innerHTML, "");
});

test("mount create: the similarity index is loaded once and cached", async () => {
	vi.useFakeTimers();
	h.getSimilarityIndex.mockResolvedValue({ tools: [] });
	h.nearestNeighbors.mockReturnValue([{ tool: toolFixture("z", { title: "Z" }) }]);
	await mountToolForm(null);
	const title = document.querySelector("#tf-title");
	setVal("tf-title", "a");
	title.dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	setVal("tf-title", "ab");
	title.dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	assert.equal(h.getSimilarityIndex.mock.calls.length, 1, "index promise reused");
});

test("mount create: keyword-only signal skips the title-needle scan", async () => {
	vi.useFakeTimers();
	h.getSimilarityIndex.mockResolvedValue({ tools: [toolFixture("should-not-appear", { title: "Anything" })] });
	h.nearestNeighbors.mockReturnValue([{ tool: toolFixture("via-neighbor", { title: "Via Neighbor" }) }]);
	await mountToolForm(null);
	setVal("tf-keywords", "maps");
	document.querySelector("#tf-keywords").dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	const names = [...document.querySelectorAll(".dupes__name")].map((n) => n.textContent);
	assert.deepEqual(names, ["Via Neighbor"], "title loop skipped when no title typed");
});

test("mount create: a name-only title match is included", async () => {
	vi.useFakeTimers();
	h.getSimilarityIndex.mockResolvedValue({ tools: [toolFixture("zeta-cit", { title: "Totally Different" })] });
	h.nearestNeighbors.mockReturnValue([]);
	await mountToolForm(null);
	setVal("tf-title", "cit");
	document.querySelector("#tf-title").dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	const names = [...document.querySelectorAll(".dupes__name")].map((n) => n.textContent);
	assert.deepEqual(names, ["Totally Different"], "matched by name even though title does not contain the needle");
});

test("mount create: the tool being typed is excluded but others remain", async () => {
	vi.useFakeTimers();
	h.getSimilarityIndex.mockResolvedValue({
		tools: [toolFixture("my-tool", { title: "My Tool" }), toolFixture("keeper", { title: "My Keeper" })]
	});
	h.nearestNeighbors.mockReturnValue([]);
	await mountToolForm(null);
	setVal("tf-name", "my-tool");
	setVal("tf-title", "my");
	document.querySelector("#tf-title").dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	const names = [...document.querySelectorAll(".dupes__name")].map((n) => n.textContent);
	assert.deepEqual(names, ["My Keeper"], "self excluded by typed name; others kept");
});

test("mount create: duplicate candidates are capped at 5", async () => {
	vi.useFakeTimers();
	const many = Array.from({ length: 8 }, (_, i) => toolFixture(`cit-${i}`, { title: `Citation ${i}` }));
	h.getSimilarityIndex.mockResolvedValue({ tools: many });
	h.nearestNeighbors.mockReturnValue([]);
	await mountToolForm(null);
	setVal("tf-title", "citation");
	document.querySelector("#tf-title").dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	assert.equal(document.querySelectorAll("[data-dupes-list] .dupes__item").length, 5);
});

/* ---- validation messages + required flag + crawler note ---- */

test("mount create: empty required URL is rejected (required:true)", async () => {
	h.isNewTool.mockReturnValue(false);
	await mountToolForm(null);
	setVal("tf-name", "n");
	setVal("tf-title", "T");
	setVal("tf-url", ""); // empty, but required
	document.querySelector("[data-tool-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(h.demoStoreSet.mock.calls.length, 0, "empty required URL blocks save");
	assert.equal(document.activeElement, document.querySelector("#tf-url"));
});

test("mount create: URL/repo validation messages are exact", async () => {
	await mountToolForm(null);
	setVal("tf-name", "n");
	setVal("tf-title", "T");
	setVal("tf-url", "ftp://nope");
	setVal("tf-repo", "also-bad");
	document.querySelector("[data-tool-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(document.querySelector("#tf-url-err").textContent, "Enter a valid http(s) URL.");
	assert.equal(document.querySelector("#tf-repo-err").textContent, "Enter a valid http(s) repository URL.");
});

test("mount create: duplicate-name error message is exact", async () => {
	h.isNewTool.mockReturnValue(true);
	await mountToolForm(null);
	setVal("tf-name", "dupe");
	setVal("tf-title", "T");
	setVal("tf-url", "https://ok.example");
	document.querySelector("[data-tool-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(document.querySelector("#tf-name-err").textContent, "A demo tool with that name already exists.");
});

test("edit (api origin) shows no crawler note", async () => {
	h.getTool.mockResolvedValue(toolFixture("my-tool", { title: "My Tool", origin: "api" }));
	const r = await tf.viewToolForm("my-tool");
	assert.ok(!r.html.includes("In production, core fields"), "api-origin edit has no crawler note");
});

test("addtools: registering an http (not https) toolinfo URL is accepted", () => {
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	setVal("at-url", "http://insecure.example/toolinfo.json");
	document.querySelector("[data-url-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.deepEqual(h.crawlerUrlAdd.mock.calls[0], ["http://insecure.example/toolinfo.json"]);
});

test("addtools: invalid toolinfo URL message is exact", () => {
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	setVal("at-url", "nope");
	document.querySelector("[data-url-form]").dispatchEvent(new Event("submit", { cancelable: true }));
	assert.equal(document.querySelector("#at-url-err").textContent, "Enter a valid http(s) toolinfo URL.");
});

/* ---- more mount coverage ---- */

test("mount edit: duplicate suggestions are NOT wired up (create-only)", async () => {
	vi.useFakeTimers();
	h.getTool.mockResolvedValue(toolFixture("my-tool", { title: "My Tool", url: "https://x.example" }));
	h.getSimilarityIndex.mockResolvedValue({ tools: [] });
	await mountToolForm("my-tool");
	document.querySelector("#tf-title").dispatchEvent(new Event("input", { bubbles: true }));
	await flushDebounce();
	assert.equal(h.getSimilarityIndex.mock.calls.length, 0, "no duplicate suggestions in edit mode");
});

test("mount addtools: ingest with nothing added/updated and no errors → 'Nothing ingested' (ok class)", () => {
	h.ingestToolinfo.mockReturnValue({ added: 0, updated: 0 });
	h.toolNewMap.mockReturnValue({});
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	setVal("at-json", "[]");
	document.querySelector("[data-ingest]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	const out = document.querySelector("[data-ingest-result]");
	assert.equal(out.textContent, "Nothing ingested");
	assert.equal(out.className, "at__result at__result--ok");
});

test("mount addtools: ingest joins multiple per-item errors with '; '", () => {
	h.ingestToolinfo.mockReturnValue({ added: 1, updated: 0, errors: ["bad one", "bad two"] });
	h.toolNewMap.mockReturnValue({ a: {} });
	h.newToolBase.mockImplementation((n) => toolFixture(n, { title: n }));
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	setVal("at-json", "[]");
	document.querySelector("[data-ingest]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	assert.equal(document.querySelector("[data-ingest-result]").textContent, "1 added · bad one; bad two");
});

test("mount addtools: ingest updates the count with singular wording for one tool", () => {
	h.ingestToolinfo.mockReturnValue({ added: 1, updated: 0 });
	h.toolNewMap.mockReturnValue({ only: {} });
	h.newToolBase.mockImplementation((n) => toolFixture(n, { title: n }));
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	setVal("at-json", "[]");
	document.querySelector("[data-ingest]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	assert.equal(document.querySelector("[data-sub-count]").textContent, "1 tool");
});

test("mount addtools: ingest trims the textarea before parsing", () => {
	h.ingestToolinfo.mockReturnValue({ added: 0, updated: 0 });
	h.toolNewMap.mockReturnValue({});
	const r = tf.viewAddTools();
	document.body.innerHTML = r.html;
	r.mount();
	setVal("at-json", '   {"name":"x"}   ');
	document.querySelector("[data-ingest]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
	assert.equal(h.ingestToolinfo.mock.calls[0][0], '{"name":"x"}', "leading/trailing whitespace stripped");
});
