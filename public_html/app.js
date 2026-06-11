// SPDX-License-Identifier: GPL-3.0-or-later
/* Toolhub demonstrator — a small hash-routed multi-view app over a fixed
   Toolhub API snapshot. Real catalog data; weeklyViews is synthesized
   deterministically in build_data.py (the API has no popularity signal). */
(function () {
	const DATA = window.TOOLHUB_DATA || {};
	const $ = (s, r) => (r || document).querySelector(s);
	const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

	/* ---------------------------------------------------------------- helpers */
	const AVATAR_COLORS = [
		"#0c57a8", "#246342", "#8a4b08", "#970302", "#5748b5",
		"#305d70", "#0e65c0", "#308557", "#b03b78", "#1f6f8b",
	];
	function hash(str) { let h = 0; for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0; return Math.abs(h); }
	function esc(s) {
		return String(s == null ? "" : s)
			.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
	}
	function safeUrl(u) { const s = String(u == null ? "" : u).trim(); return /^https?:\/\//i.test(s) ? esc(s) : ""; }
	function avatar(title, cls) {
		const ch = (title || "?").trim().charAt(0).toUpperCase();
		const color = AVATAR_COLORS[hash(title || "?") % AVATAR_COLORS.length];
		return `<span class="avatar ${cls || ""}" style="background:${color}" aria-hidden="true">${esc(ch)}</span>`;
	}
	// Commons "File:Foo.svg" page URL → a rendered thumbnail URL.
	function commonsThumb(fileUrl, w) {
		const m = /File:(.+)$/.exec(fileUrl || "");
		if (!m) return null;
		return "https://commons.wikimedia.org/wiki/Special:FilePath/" + encodeURIComponent(decodeURIComponent(m[1])) + "?width=" + w;
	}
	// Tool icon: real Commons image if the tool has one, else a letter avatar.
	function toolIcon(t, variant) {
		const px = variant === "lg" ? 72 : 48;
		const cls = "avatar" + (variant === "lg" ? " avatar--lg" : "");
		const thumb = commonsThumb(t.icon, px * 2);
		if (thumb) {
			return `<img class="${cls} avatar--img" src="${esc(thumb)}" alt="" width="${px}" height="${px}" loading="lazy" />`;
		}
		return avatar(t.title, variant === "lg" ? "avatar--lg" : "");
	}
	function relTime(iso) {
		if (!iso) return "";
		const days = Math.floor((Date.now() - new Date(iso)) / 86400000);
		if (days <= 0) return "Updated today";
		if (days === 1) return "Updated yesterday";
		if (days < 30) return `Updated ${days} days ago`;
		const mo = Math.floor(days / 30);
		if (mo < 12) return `Updated ${mo} month${mo > 1 ? "s" : ""} ago`;
		const yr = Math.floor(mo / 12);
		return `Updated ${yr} year${yr > 1 ? "s" : ""} ago`;
	}
	function fmt(n) { return (n || 0).toLocaleString("en-US"); }
	function views(n) { return n >= 1000 ? (n / 1000).toFixed(1) + "k views" : n + " views"; }
	const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
	const scrollBehavior = REDUCED ? "auto" : "smooth";

	/* ---- Experimental mode -------------------------------------------------
	   "Experimental" features are ones we can't fully back with today's Toolhub
	   API/data. Each is marked `class="experimental"` in the DOM and documented
	   inline with what's MISSING. When the header toggle is OFF, body gets
	   `.exp-off` and CSS hides every `.experimental` element, leaving only the
	   genuinely shippable UI. Default: ON. */
	const EXP_KEY = "toolhub-exp";
	function expOn() { return !document.body.classList.contains("exp-off"); }
	function applyExp(on) {
		document.body.classList.toggle("exp-off", !on);
		const btn = document.getElementById("exp-toggle");
		if (btn) btn.setAttribute("aria-checked", String(on));
	}
	applyExp((localStorage.getItem(EXP_KEY) || "on") !== "off");

	/* Index every tool we know about, for O(1) detail lookups. */
	const INDEX = {};
	function indexTools(a) { (a || []).forEach((t) => { if (t && t.name && !INDEX[t.name]) INDEX[t.name] = t; }); }
	indexTools(DATA.catalog); indexTools(DATA.featured); indexTools(DATA.recent); indexTools(DATA.popular);
	(DATA.curatedLists || []).forEach((l) => indexTools(l.tools));

	/* Facet options computed once from the full catalog. */
	const CATALOG = DATA.catalog || [];
	const TOOL_TYPES = (() => {
		const m = {};
		CATALOG.forEach((t) => { if (t.toolType) m[t.toolType] = (m[t.toolType] || 0) + 1; });
		return Object.keys(m).sort((a, b) => m[b] - m[a]).map((k) => ({ key: k, count: m[k] }));
	})();
	const TOP_KEYWORDS = (() => {
		const m = {};
		CATALOG.forEach((t) => (t.keywords || []).forEach((k) => { m[k] = (m[k] || 0) + 1; }));
		return Object.keys(m).sort((a, b) => m[b] - m[a]).slice(0, 14);
	})();

	/* ------------------------------------------------------------ card markup */
	function toolCard(t, opts) {
		opts = opts || {};
		// (3) Tags: 2 + "+N" overflow chip so every card is the same height.
		const allk = t.keywords || [];
		const tags = allk.slice(0, 2).map((k) => `<span class="tag" data-q="${esc(k)}">${esc(k)}</span>`).join("")
			+ (allk.length > 2 ? `<span class="tag tag--more">+${allk.length - 2}</span>` : "");
		const rank = opts.rank ? `<span class="rankbadge" aria-hidden="true">${opts.rank}</span>` : "";
		// (1) Top-right shows ONLY the real deprecated/experimental flags (genuine
		// warnings). The old assumed "Healthy" pill is gone (it had no real data).
		let flag = "";
		if (t.deprecated) flag = `<span class="tcard__flag status status--red"><span class="dot dot--red"></span>Deprecated</span>`;
		else if (t.experimental) flag = `<span class="tcard__flag status status--yellow"><span class="dot dot--yellow"></span>Experimental</span>`;
		// (1,2,4) Calm footer-left: real tool type + "works on" facet (no colour noise).
		const meta = [t.toolType && esc(t.toolType), esc(wikiShort(t.forWikis))].filter(Boolean).join(" · ");
		// EXPERIMENTAL — popularity (only the home "Popular" grid; shown when toggle on).
		const footLeft = opts.popular
			? `<span class="views experimental">🔥 ${views(t.weeklyViews)}</span>`
			: `<span class="tcard__meta">${meta}</span>`;
		// The whole card opens the quick-view; (5) a hover cue signals the peek.
		return `
		<article class="tcard${opts.popular ? " tcard--popular" : ""}" data-tool="${esc(t.name)}" role="button" tabindex="0" aria-label="Quick look: ${esc(t.title)}">
			${flag}
			<div class="tcard__head">
				${rank}${toolIcon(t)}
				<div class="tcard__heading">
					<div class="tcard__title">${esc(t.title)}</div>
					<div class="tcard__maint">by ${esc(t.maintainer)}</div>
				</div>
			</div>
			<p class="tcard__desc">${esc(t.description)}</p>
			<div class="tcard__tags">${tags}</div>
			<div class="tcard__foot">${footLeft}<span class="tcard__when">${esc(relTime(t.modified))}</span></div>
			<span class="tcard__hint" aria-hidden="true">🔍</span>
		</article>`;
	}
	function listCard(l) {
		return `
		<a class="lcard" href="#/lists/${l.id}" aria-label="${esc(l.title)} list, ${l.toolCount} tools">
			${avatar(l.title)}
			<div class="lcard__body">
				<div class="lcard__title">${esc(l.title)} <span class="lcard__count">${l.toolCount} tools</span></div>
				<div class="lcard__desc">${esc(l.description)}</div>
			</div>
		</a>`;
	}
	function grid(cls, items, render) {
		return `<div class="card-grid ${cls}">${items.map(render).join("")}</div>`;
	}

	/* ------------------------------------------------------------- static cfg */
	const PERSONAS = [
		["✏️", "Editors", "edit"], ["🛡️", "Patrollers", "patrol"],
		["👥", "Organizers", "organiz"], ["📖", "Researchers", "research"],
		["☁️", "Upload media", "commons"], ["📊", "Analyze data", "statistic"],
		["❝", "Find references", "citation"], ["🗛", "Translate", "translat"],
	];
	const NEEDS = [
		["✏️", "Write and edit content", "edit"], ["🗂️", "Find and manage content", "category"],
		["🖼️", "Upload and use media", "image"], ["🛡️", "Monitor and patrol", "patrol"],
		["📊", "Analyze and visualize data", "statistic"], ["🗛", "Translate and localize", "translat"],
		["👥", "Manage projects and events", "wikiproject"],
	];
	const STEPS = [
		["🔍", "1. Find a tool", "Search or browse by task, audience or category."],
		["🔖", "2. Try it out", "Most tools are free and open for everyone."],
		["💬", "3. Learn & connect", "Read docs, join discussions and ask for help."],
		["❤️", "4. Contribute back", "Share feedback or submit a tool for others."],
	];

	/* ==================================================================== views
	   Each view returns { title, html, mount? }. mount() runs after injection. */

	function viewHome() {
		const personas = PERSONAS.map(([ic, l, q]) => `<a class="persona" href="#/search?q=${encodeURIComponent(q)}"><span aria-hidden="true">${ic}</span> ${l}</a>`).join("");
		const needs = NEEDS.map(([ic, l, q]) => `<li><a href="#/search?q=${encodeURIComponent(q)}"><span aria-hidden="true">${ic}</span> ${l}<span class="need__chev" aria-hidden="true">›</span></a></li>`).join("");
		const steps = STEPS.map(([ic, t, d]) => `<div class="step"><div class="step__icon" aria-hidden="true">${ic}</div><div class="step__title">${t}</div><div class="step__desc">${d}</div></div>`).join("");
		const recent = (DATA.recent || []).slice(0, 5).map((t) => `
			<li><a href="#/tools/${encodeURIComponent(t.name)}">${avatar(t.title)}
				<div><div class="recent__title">${esc(t.title)}</div>
				<div class="recent__meta">Maintainer: ${esc(t.maintainer)}</div></div>
				<span class="recent__when">${esc(relTime(t.modified))}</span></a></li>`).join("");

		const html = `
		<section class="hero">
			<h1 class="hero__title">Find the right Wikimedia tool faster</h1>
			<form class="search" role="search" data-home-search>
				<label for="home-q" class="skip-label">Search tools</label>
				<input id="home-q" class="search__input" type="search" aria-label="Search tools" placeholder="Search ${fmt(DATA.totalTools)} tools…" autocomplete="off" />
				<button class="btn btn--primary search__btn" type="submit">Search</button>
			</form>
		</section>
		<section class="personas container"><span class="personas__label">I'm looking for tools for:</span><div class="personas__row">${personas}</div></section>
		<div class="container layout">
			<div class="layout__main">
				<div class="section-head"><h2>Featured tools</h2><a class="link" href="#/lists/${(DATA.curatedLists[0] || {}).id || ""}">View all</a></div>
				${grid("grid-tools", (DATA.featured || []).slice(0, 8), (t) => toolCard(t))}
				<!-- EXPERIMENTAL — "Popular this week" ranks by weeklyViews.
				     MISSING: no popularity/usage signal in the Toolhub API. -->
				<div class="experimental">
					<div class="section-head"><h2>Popular this week <span class="exp-badge">Experimental</span></h2><a class="link" href="#/search?sort=views">View all</a></div>
					${grid("grid-tools", (DATA.popular || []).slice(0, 8), (t, i) => toolCard(t, { rank: i + 1, popular: true }))}
				</div>
				<div class="section-head"><h2>Curated lists</h2><a class="link" href="#/lists">View all lists</a></div>
				${grid("grid-lists", (DATA.curatedLists || []).slice(0, 6), listCard)}
				<div class="section-head"><h2>Getting started</h2></div>
				<div class="card-grid grid-steps">${steps}</div>
			</div>
			<aside class="layout__side">
				<div class="panel"><h3 class="panel__title">Browse by need</h3><ul class="needs">${needs}</ul><a class="link panel__foot" href="#/search">View all categories</a></div>
				<div class="panel"><h3 class="panel__title">Recently updated</h3><ul class="recent">${recent}</ul></div>
				<div class="panel panel--cta"><div class="cta__icon" aria-hidden="true">💡</div><h3>Have a tool to share?</h3><p>Help the community by submitting your tool to Toolhub.</p><a class="btn btn--outline" href="https://toolhub.wikimedia.org/tools/create" target="_blank" rel="noopener">Submit a tool</a></div>
			</aside>
		</div>`;
		return {
			title: "Toolhub — discover Wikimedia tools",
			html,
			mount() {
				$("[data-home-search]").addEventListener("submit", (e) => {
					e.preventDefault();
					const q = $("#home-q").value.trim();
					location.hash = "#/search" + (q ? "?q=" + encodeURIComponent(q) : "");
				});
			},
		};
	}

	/* ---- Search / Browse (T2): facets + sort + pagination ------------------ */
	const PAGE_SIZE = 12;
	function viewSearch(params) {
		const typeFacets = TOOL_TYPES.map(({ key, count }) =>
			`<label class="facet"><input type="checkbox" name="type" value="${esc(key)}"> <span>${esc(key)}</span> <span class="facet__n">${count}</span></label>`).join("");
		const kwFacets = TOP_KEYWORDS.map((k) =>
			`<label class="facet"><input type="checkbox" name="kw" value="${esc(k)}"> <span>${esc(k)}</span></label>`).join("");

		// "Most popular" sort relies on weeklyViews → EXPERIMENTAL.
		// MISSING: no popularity signal in the API. Hidden when experimental is off.
		const exp = expOn();
		const sortOpts = (exp ? `<option value="relevance">Most popular</option>` : "") +
			`<option value="recent">Recently updated</option><option value="name">Name (A–Z)</option>`;

		const html = `
		<div class="container page">
			<h1 class="page__title">Browse tools</h1>
			<div class="browse">
				<aside class="facets" aria-label="Filters">
					<form data-facet-q role="search">
						<label for="facet-q" class="skip-label">Search within tools</label>
						<input id="facet-q" class="facets__search" type="search" placeholder="Search tools…" autocomplete="off" />
					</form>
					<div class="facet-group"><h2 class="facet-group__title">Tool type</h2>${typeFacets || '<p class="facet__empty">—</p>'}</div>
					<div class="facet-group"><h2 class="facet-group__title">Keywords</h2>${kwFacets}</div>
					<button type="button" class="btn btn--outline facets__reset" data-facet-reset>Clear filters</button>
				</aside>
				<div class="browse__main">
					<div class="browse__bar">
						<span id="result-count" class="browse__count" aria-live="polite"></span>
						<label class="sort"><span class="skip-label">Sort by</span>
							<select id="sort">${sortOpts}</select>
						</label>
					</div>
					<div id="search-results" class="card-grid grid-tools"></div>
					<nav id="search-pager" class="pager" aria-label="Pagination"></nav>
				</div>
			</div>
		</div>`;

		function mount() {
			// hydrate controls from URL
			$("#facet-q").value = params.q || "";
			const allowedSorts = exp ? ["relevance", "recent", "name"] : ["recent", "name"];
			$("#sort").value = allowedSorts.includes(params.sort) ? params.sort : (exp ? "relevance" : "recent");
			const pre = (name, csv) => (csv ? csv.split(",") : []).forEach((v) => {
				const el = $(`input[name="${name}"][value="${CSS.escape(v)}"]`); if (el) el.checked = true;
			});
			pre("type", params.type); pre("kw", params.kw);
			let page = Math.max(1, parseInt(params.page) || 1);

			function readState() {
				return {
					q: $("#facet-q").value.trim(),
					type: $$('input[name="type"]:checked').map((e) => e.value),
					kw: $$('input[name="kw"]:checked').map((e) => e.value),
					sort: $("#sort").value,
				};
			}
			function filterSort(s) {
				let out = CATALOG.filter((t) => {
					if (s.type.length && !s.type.includes(t.toolType)) return false;
					if (s.kw.length && !s.kw.some((k) => (t.keywords || []).includes(k))) return false;
					if (s.q) {
						const hay = [t.title, t.description, t.maintainer, (t.keywords || []).join(" "), (t.audiences || []).join(" ")].join(" ").toLowerCase();
						if (!hay.includes(s.q.toLowerCase())) return false;
					}
					return true;
				});
				if (s.sort === "name") out.sort((a, b) => a.title.localeCompare(b.title));
				else if (s.sort === "recent") out.sort((a, b) => new Date(b.modified) - new Date(a.modified));
				else out.sort((a, b) => b.weeklyViews - a.weeklyViews);
				return out;
			}
			function pager(total, cur) {
				const pages = Math.ceil(total / PAGE_SIZE);
				if (pages <= 1) return "";
				const btn = (p, label, dis, cur2) =>
					`<button class="pager__btn${cur2 ? " is-current" : ""}" ${dis ? "disabled" : ""} data-page="${p}"${cur2 ? ' aria-current="page"' : ""}>${label}</button>`;
				let out = btn(cur - 1, "‹ Prev", cur <= 1);
				const win = [];
				for (let p = 1; p <= pages; p++) if (p === 1 || p === pages || Math.abs(p - cur) <= 2) win.push(p);
				let last = 0;
				win.forEach((p) => { if (p - last > 1) out += `<span class="pager__gap">…</span>`; out += btn(p, p, false, p === cur); last = p; });
				out += btn(cur + 1, "Next ›", cur >= pages);
				return out;
			}
			function apply(updateHash) {
				const s = readState();
				const results = filterSort(s);
				const pages = Math.max(1, Math.ceil(results.length / PAGE_SIZE));
				if (page > pages) page = pages;
				const slice = results.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
				$("#result-count").textContent = `${fmt(results.length)} tool${results.length === 1 ? "" : "s"}`;
				$("#search-results").innerHTML = slice.length
					? slice.map((t) => toolCard(t)).join("")
					: `<p class="empty">No tools match these filters. <button class="linkbtn" data-facet-reset>Clear filters</button></p>`;
				$("#search-pager").innerHTML = pager(results.length, page);
				if (updateHash) {
					const qs = new URLSearchParams();
					if (s.q) qs.set("q", s.q);
					if (s.type.length) qs.set("type", s.type.join(","));
					if (s.kw.length) qs.set("kw", s.kw.join(","));
					if (s.sort !== "relevance") qs.set("sort", s.sort);
					if (page > 1) qs.set("page", page);
					const str = qs.toString();
					history.replaceState(null, "", "#/search" + (str ? "?" + str : ""));
				}
			}
			// events
			$(".facets").addEventListener("change", () => { page = 1; apply(true); });
			$("[data-facet-q]").addEventListener("submit", (e) => { e.preventDefault(); page = 1; apply(true); });
			$("#facet-q").addEventListener("input", debounce(() => { page = 1; apply(true); }, 250));
			$("#search-pager").addEventListener("click", (e) => {
				const b = e.target.closest("[data-page]"); if (!b) return;
				page = parseInt(b.getAttribute("data-page")); apply(true);
				$(".browse__bar").scrollIntoView({ behavior: scrollBehavior, block: "start" });
			});
			$(".browse__main").addEventListener("click", (e) => {
				if (e.target.closest("[data-facet-reset]")) { reset(); }
			});
			$(".facets__reset").addEventListener("click", reset);
			function reset() { $("#facet-q").value = ""; $$('.facets input[type=checkbox]').forEach((c) => (c.checked = false)); page = 1; apply(true); }
			apply(false);
		}
		return { title: "Browse tools — Toolhub", html, mount };
	}
	function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

	/* ---- Tool detail page (T3) --------------------------------------------- */
	function metaItem(k, v) { return `<div><div class="meta__k">${k}</div><div class="meta__v">${v || "—"}</div></div>`; }
	function linkOut(label, url) { const u = safeUrl(url); return u ? `<a class="btn btn--outline" href="${u}" target="_blank" rel="noopener">${label} ↗</a>` : ""; }
	// REAL — related tools derived from shared keywords (no missing data).
	function relatedTools(t) {
		const kws = new Set(t.keywords || []);
		if (!kws.size) return [];
		return CATALOG
			.filter((o) => o.name !== t.name && (o.keywords || []).some((k) => kws.has(k)))
			.map((o) => ({ o, score: (o.keywords || []).filter((k) => kws.has(k)).length }))
			.sort((a, b) => b.score - a.score || new Date(b.o.modified) - new Date(a.o.modified))
			.slice(0, 4).map((x) => x.o);
	}
	const wikiLabel = (a) => (!a || !a.length ? "Any wiki" : a.includes("*") ? "All wikis" : a.map(esc).join(", "));
	const langLabel = (a) => (!a || !a.length ? "English (default)" : a.map(esc).join(", "));
	// Compact "works on" label for cards (full list shown on the detail page).
	const wikiShort = (a) => (!a || !a.length ? "Any wiki" : a.includes("*") ? "All wikis" : (a.length === 1 ? a[0] : a.length + " wikis"));

	function viewTool(name) {
		const t = INDEX[name];
		if (!t) return viewNotFound();
		const st = t.status || { level: "green", label: "Healthy" };
		const tags = (t.keywords || []).map((k) => `<a class="tag" href="#/search?kw=${encodeURIComponent(k)}">${esc(k)}</a>`).join("") || "—";
		const authors = (t.authors || []).map(esc).join(", ") || esc(t.maintainer);

		// REAL links — render only the ones present on the record.
		const actions = [
			linkOut("Open tool", t.url), linkOut("Source code", t.repository),
			linkOut("API", t.apiUrl), linkOut("User docs", t.userDocs),
			linkOut("Developer docs", t.devDocs), linkOut("Report a bug", t.bugtracker),
			linkOut("Give feedback", t.feedback), linkOut("Translate", t.translate),
		].filter(Boolean).join("");

		// REAL status — only the deprecated/experimental flags (shown even when exp off).
		const realBadge = (t.deprecated || t.experimental)
			? `<span class="status status--${st.level}"><span class="dot dot--${st.level}"></span>${esc(st.label)}</span>` : "";

		const related = relatedTools(t);
		const relatedHtml = related.length
			? `<h2 class="toolpage__h2">Related tools</h2>${grid("grid-tools", related, (x) => toolCard(x))}`
			: "";

		// At-a-glance chips (real metadata).
		const glance = [
			t.toolType && `<span class="glance">${esc(t.toolType)}</span>`,
			t.license && `<span class="glance">${esc(t.license)}</span>`,
			`<span class="glance">${esc(wikiLabel(t.forWikis))}</span>`,
			(t.uiLanguages && t.uiLanguages.length) && `<span class="glance">${t.uiLanguages.length} language${t.uiLanguages.length > 1 ? "s" : ""}</span>`,
		].filter(Boolean).join("");

		const maintList = (t.authors && t.authors.length ? t.authors : [t.maintainer])
			.map((a) => `<li>${avatar(a)}<span>${esc(a)}</span></li>`).join("");

		const html = `
		<div class="container page">
			<a class="back" href="#/search">← Back to tools</a>
			<header class="toolpage__head">
				${toolIcon(t, "lg")}
				<div class="toolpage__id">
					<h1 class="toolpage__title">${esc(t.title)}</h1>
					<div class="toolpage__by">by ${authors}</div>
					<div class="toolpage__glance">${glance}</div>
					<div class="toolpage__row">
						${realBadge}
						<!-- EXPERIMENTAL — operational health. MISSING: no uptime/health-check backend. -->
						<span class="status status--green experimental"><span class="dot dot--green"></span>Healthy</span>
						<!-- EXPERIMENTAL — popularity. MISSING: no usage/view tracking in the API. -->
						<span class="views experimental">🔥 ${views(t.weeklyViews)}</span>
						<span class="toolpage__when">${esc(relTime(t.modified))}</span>
					</div>
				</div>
				<div class="toolpage__cta">
					${t.url ? `<a class="btn btn--primary btn--lg" href="${safeUrl(t.url)}" target="_blank" rel="noopener">Open tool ↗</a>` : ""}
					<!-- EXPERIMENTAL — save/bookmark. MISSING: needs an authenticated session. -->
					<button class="btn btn--outline experimental" type="button">🔖 Save to a list</button>
				</div>
			</header>

			<div class="toolpage__grid">
				<div class="toolpage__main">
					<!-- EXPERIMENTAL — screenshots/preview. MISSING: no screenshot field in the
					     toolinfo schema and no image storage for tool previews. -->
					<div class="experimental shotstrip">
						<div class="shot"></div><div class="shot"></div><div class="shot"></div>
						<span class="exp-badge shotstrip__badge">Experimental · screenshots</span>
					</div>

					<div class="prose">${esc(t.description) || "<em>No description provided.</em>"}</div>
					<div class="tcard__tags toolpage__tags">${tags}</div>

					<h2 class="toolpage__h2">Details</h2>
					<div class="detail__meta">
						${metaItem("Type", esc(t.toolType))}
						${metaItem("License", esc(t.license))}
						${metaItem("Works on", wikiLabel(t.forWikis))}
						${metaItem("Interface languages", langLabel(t.uiLanguages))}
						${metaItem("Technology", (t.technologyUsed || []).map(esc).join(", "))}
						${metaItem("Audiences", (t.audiences || []).map(esc).join(", "))}
					</div>

					<!-- EXPERIMENTAL — ratings & reviews. MISSING: no reviews data model / auth. Placeholder values. -->
					<div class="experimental reviews">
						<h2 class="toolpage__h2">Reviews <span class="exp-badge">Experimental</span></h2>
						<div class="reviews__agg">
							<span class="reviews__stars" aria-hidden="true">★★★★☆</span>
							<span class="reviews__score">4.2</span>
							<span class="reviews__count">· 18 reviews</span>
						</div>
						<button class="btn btn--outline" type="button" disabled>Write a review</button>
					</div>

					${relatedHtml}
				</div>

				<aside class="toolpage__side">
					<div class="panel">
						<h2 class="panel__title">Get started</h2>
						<div class="toolpage__actions">${actions || '<span class="meta__v">No links provided</span>'}</div>
						<div class="toolpage__sub">
							<a href="#/tools/${encodeURIComponent(t.name)}/history">View history</a>
							<a href="#/tools/${encodeURIComponent(t.name)}/edit">Suggest an edit</a>
						</div>
					</div>
					<div class="panel">
						<h2 class="panel__title">Maintainers</h2>
						<ul class="maint-list">${maintList}</ul>
					</div>
					<!-- EXPERIMENTAL — usage stat. MISSING: no usage analytics in the API. -->
					<div class="panel experimental">
						<h2 class="panel__title">Usage <span class="exp-badge">Experimental</span></h2>
						<p class="usage"><strong>${fmt(2000 + (hash(t.name) % 9000))}</strong> editors used this in the last 30 days</p>
					</div>
				</aside>
			</div>
		</div>`;
		return { title: `${t.title} — Toolhub`, html };
	}

	/* ---- Lists overview + list detail -------------------------------------- */
	function viewLists() {
		const html = `
		<div class="container page">
			<h1 class="page__title">Curated lists</h1>
			<p class="page__intro">Hand-picked collections of tools for specific tasks and communities.</p>
			${grid("grid-lists", DATA.curatedLists || [], listCard)}
		</div>`;
		return { title: "Curated lists — Toolhub", html };
	}
	function viewList(id) {
		const l = (DATA.curatedLists || []).find((x) => String(x.id) === String(id));
		if (!l) return viewNotFound();
		const html = `
		<div class="container page">
			<a class="back" href="#/lists">← All lists</a>
			<h1 class="page__title">${esc(l.title)} <span class="lcard__count">${l.toolCount} tools</span></h1>
			<div class="prose page__intro">${esc(l.description)}</div>
			${grid("grid-tools", l.tools || [], (t) => toolCard(t))}
		</div>`;
		return { title: `${l.title} — Toolhub`, html };
	}

	/* ---- Static prose pages (T9) ------------------------------------------- */
	function prosePage(title, bodyHtml) {
		return { title: `${title} — Toolhub`, html: `<div class="container page"><article class="prose prose--page"><h1>${esc(title)}</h1>${bodyHtml}</article></div>` };
	}
	const ext = (url, label) => `<a href="${safeUrl(url)}" target="_blank" rel="noopener">${esc(label)} ↗</a>`;
	// Faithful summaries of real Toolhub / Wikimedia content, rendered in our style.
	// Canonical policies link out to their authoritative source (as the real site does).
	const STATIC = {
		about: { title: "About Toolhub", body: `
			<p>Toolhub is <strong>a community-managed catalog of software tools used in the
			Wikimedia movement</strong>. Technical volunteers document the tools they build,
			and all Wikimedians can search the catalog, build lists, and share them.</p>
			<p>A "tool" is defined inclusively — user scripts, gadgets, bots, templates, Lua
			modules, web applications and mobile apps that interact with Wikimedia projects.
			The catalog aims to be <em>inclusive rather than exclusive</em>, as long as an
			entry helps people work on the projects.</p>
			<h2>How tools get here</h2>
			<p>Tools enter the catalog three ways: by registering a <code>toolinfo.json</code>
			URL that Toolhub crawls roughly hourly, through the Toolhub UI, or via the API
			(<code>POST /api/tools/</code>). All paths validate against the same versioned
			schema, so the data stays consistent.</p>
			<h2>Core information vs. annotations</h2>
			<p>Each tool has authoritative <em>core</em> information, editable only by its
			owner or administrators, plus community <em>annotations</em> that any logged-in
			Wikimedian can enrich. When both are set for a field, Toolhub shows the core
			value — balancing maintainer control with community contribution.</p>
			<p>Structured data is released under CC0; attribution via links back is
			encouraged but not required. Sign in with your existing Wikimedia account — no
			new account or password is needed.</p>
			<p>Want to help build Toolhub itself? See ${"<a href=\"#/contribute\">Help maintain Toolhub</a>"}.</p>
			<blockquote>This is a design prototype built on a fixed snapshot of the public
			Toolhub API — not the production site.</blockquote>` },
		help: { title: "Help", body: `
			<p>New to Toolhub? Here is the quickest path to finding and sharing tools. Sign
			in with your Wikimedia account (via OAuth) to save favourites and edit listings —
			no new account needed.</p>
			<h2>Find a tool</h2>
			<ul>
				<li><strong>Search</strong> by name, keyword, or what you want to do.</li>
				<li><strong>Filter</strong> on the Browse page by tool type and keywords.</li>
				<li><strong>Browse by need</strong> from the home-page shortcuts.</li>
			</ul>
			<h2>Share a tool</h2>
			<p>Maintainers can publish a <code>toolinfo.json</code> file in their repository
			(so volunteers can submit improvements over time) or create a record directly in
			the UI or API.</p>
			<h2>Build a list</h2>
			<p>Group useful tools into a list and share it — great for onboarding new editors
			or running an event.</p>
			<p>${"<a href=\"#/about\">Learn more about Toolhub →</a>"}</p>` },
		community: { title: "Community", body: `
			<p>Toolhub is developed in the open under Wikimedia Cloud Services. Everyone is
			welcome to take part — reporting bugs, suggesting tools, translating, or writing
			code.</p>
			<h2>Where the conversation happens</h2>
			<ul>
				<li>Discuss the project on ${ext("https://meta.wikimedia.org/wiki/Talk:Toolhub", "Talk:Toolhub")} (Meta-Wiki).</li>
				<li>File and track work on the ${ext("https://phabricator.wikimedia.org/tag/toolhub/", "#toolhub Phabricator board")}.</li>
				<li>Help translate the interface on ${ext("https://translatewiki.net/wiki/Translating:Toolhub", "translatewiki.net")}.</li>
			</ul>
			<p>Looking to contribute code or report an issue? Start at
			${"<a href=\"#/contribute\">Help maintain Toolhub</a>"}.</p>` },
		privacy: { title: "Privacy policy", body: `
			<p>Toolhub is operated by the Wikimedia Foundation and is governed by the
			${ext("https://foundation.wikimedia.org/wiki/Policy:Privacy_policy", "Wikimedia Foundation Privacy Policy")}.</p>
			<h2>What this means in practice</h2>
			<ul>
				<li>You sign in with your Wikimedia account using OAuth; Toolhub does not store
				a separate password.</li>
				<li>Like a wiki, your contributions (tool edits, annotations, lists, comments)
				are <strong>public</strong> and attributed to your username.</li>
				<li>Catalog data is released under CC0.</li>
			</ul>
			<p>Please read the full ${ext("https://foundation.wikimedia.org/wiki/Policy:Privacy_policy", "Privacy Policy")} for the authoritative details.</p>` },
		terms: { title: "Terms of Use", body: `
			<p>Use of Toolhub is subject to the
			${ext("https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use", "Wikimedia Foundation Terms of Use")}.</p>
			<p>By contributing, you agree that your edits are public and that structured
			catalog data is made available under CC0. Tools listed here are owned and operated
			by their respective maintainers; Toolhub catalogs them but does not host or endorse
			them. See the full ${ext("https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use", "Terms of Use")} for details.</p>` },
		"code-of-conduct": { title: "Code of Conduct", body: `
			<p>Toolhub follows the
			${ext("https://www.mediawiki.org/wiki/Code_of_Conduct", "Code of Conduct for Wikimedia technical spaces")},
			which applies to MediaWiki.org, Phabricator, Gerrit, mailing lists, chat, and
			events.</p>
			<blockquote>Technical skills and community status make no difference to the right
			to be respected and the obligation to respect others.</blockquote>
			<h2>Expected behaviour</h2>
			<p>Be welcoming and helpful, especially to newcomers. Harassment and other
			inappropriate behaviour are unacceptable in all public and private Wikimedia
			technical spaces.</p>
			<h2>Reporting</h2>
			<p>Ask the person to stop and point them to the Code of Conduct; at events, notify
			organisers; or report directly to the Code of Conduct Committee at
			<code>techconduct@wikimedia.org</code>. For threats of harm, contact local
			authorities first, then <code>emergency@wikimedia.org</code>.</p>` },
		api: { title: "API", body: `
			<p>Toolhub is built <strong>API-first</strong>: everything you can do in this
			interface is also available over a documented HTTP API, so anyone can build their
			own tools on top of the catalog.</p>
			<ul>
				<li>Browse the interactive documentation at ${ext("https://toolhub.wikimedia.org/api-docs", "toolhub.wikimedia.org/api-docs")}.</li>
				<li>The OpenAPI schema and endpoints live under ${ext("https://toolhub.wikimedia.org/api/", "/api/")}.</li>
				<li>Read access is anonymous; creating or editing records uses your Wikimedia
				OAuth identity. For example, <code>POST /api/tools/</code> adds a tool.</li>
			</ul>` },
		rss: { title: "Feeds", body: `
			<p>Follow changes to the catalog without checking back. Toolhub publishes Atom/RSS
			feeds for activity such as recently added and recently updated tools, and for the
			history of individual tools and lists.</p>
			<p>Browse the latest additions on the ${ext("https://toolhub.wikimedia.org/", "live site")},
			or sort the ${"<a href=\"#/search?sort=recent\">Browse page</a>"} by "Recently
			updated".</p>` },
	};
	function viewStatic(slug) {
		const p = STATIC[slug];
		return p ? prosePage(p.title, p.body) : viewNotFound();
	}

	/* ---- Help maintain Toolhub: the contribution hub ----------------------- */
	function linkCard(icon, title, desc, url, internal) {
		const href = internal ? url : safeUrl(url);
		const attrs = internal ? "" : ` target="_blank" rel="noopener"`;
		const arrow = internal ? "" : " ↗";
		return `<a class="linkcard" href="${href || "#"}"${attrs}>
			<span class="linkcard__icon" aria-hidden="true">${icon}</span>
			<span class="linkcard__body"><span class="linkcard__title">${esc(title)}${arrow}</span>
			<span class="linkcard__desc">${esc(desc)}</span></span></a>`;
	}
	function viewContribute() {
		const html = `
		<div class="container page">
			<h1 class="page__title">Help maintain Toolhub</h1>
			<p class="page__intro">Toolhub is free and open source, built by the community
			under Wikimedia Cloud Services. Here is everything you need to report a problem,
			translate, or contribute code — pick a starting point.</p>

			<h2 class="contribute__h2">Report &amp; track work</h2>
			<div class="linkgrid">
				${linkCard("🐞", "Report a bug or request a feature", "Open a task on the #toolhub Phabricator board.", "https://phabricator.wikimedia.org/tag/toolhub/")}
				${linkCard("✅", "Find a good first task", "Browse open work and pick something to start with.", "https://phabricator.wikimedia.org/tag/toolhub/")}
				${linkCard("💬", "Discuss the project", "Share ideas and feedback on the Toolhub talk page.", "https://meta.wikimedia.org/wiki/Talk:Toolhub")}
			</div>

			<h2 class="contribute__h2">Write code</h2>
			<div class="linkgrid">
				${linkCard("🧩", "Source code (Gerrit)", "The canonical repository where changes are reviewed.", "https://gerrit.wikimedia.org/r/admin/repos/wikimedia/toolhub")}
				${linkCard("🐙", "GitHub mirror", "Read-only mirror for browsing the code and history.", "https://github.com/wikimedia/toolhub")}
				${linkCard("🛠️", "Set up a dev environment", "The CONTRIBUTING guide: run the whole stack with Docker.", "https://github.com/wikimedia/toolhub/blob/main/docs/CONTRIBUTING.rst")}
				${linkCard("🔑", "Get developer access", "Create a Wikimedia developer account and configure Gerrit.", "https://www.mediawiki.org/wiki/Developer_access")}
			</div>

			<h2 class="contribute__h2">Translate &amp; document</h2>
			<div class="linkgrid">
				${linkCard("🌐", "Translate Toolhub", "Localise the interface into your language on translatewiki.net.", "https://translatewiki.net/wiki/Translating:Toolhub")}
				${linkCard("📦", "The toolinfo standard", "Learn the schema that describes a tool, and the API.", "https://toolhub.wikimedia.org/api-docs")}
				${linkCard("📝", "Add or improve a tool listing", "List your own tool, or enrich an existing record.", "#/help", true)}
			</div>
		</div>`;
		return { title: "Help maintain Toolhub", html };
	}
	/* ---- Parity pages: data-driven (read-only) ----------------------------- */
	// Recent changes — real, from modified dates.
	function viewRecent() {
		const items = [...CATALOG].sort((a, b) => new Date(b.modified) - new Date(a.modified)).slice(0, 30);
		const rows = items.map((t) => `
			<li><a href="#/tools/${encodeURIComponent(t.name)}">
				<span class="feed__ic" aria-hidden="true">✎</span>
				<span class="feed__main"><strong>${esc(t.title)}</strong> updated by ${esc(t.maintainer)}</span>
				<span class="feed__when">${esc(relTime(t.modified))}</span></a></li>`).join("");
		return { title: "Recent changes — Toolhub", html: `
			<div class="container page">
				<h1 class="page__title">Recent changes</h1>
				<p class="page__intro">The latest edits to tools in the catalog.</p>
				<ul class="feed">${rows}</ul>
			</div>` };
	}
	// Members — real, derived from tool authors/maintainers.
	function viewMembers() {
		const counts = {};
		CATALOG.forEach((t) => (t.authors && t.authors.length ? t.authors : [t.maintainer]).forEach((a) => { if (a) counts[a] = (counts[a] || 0) + 1; }));
		const members = Object.keys(counts).sort((a, b) => counts[b] - counts[a]).slice(0, 60);
		const cards = members.map((n) => `
			<div class="mcard">${avatar(n)}<div class="mcard__b">
				<div class="mcard__n">${esc(n)}</div>
				<div class="mcard__c">${counts[n]} tool${counts[n] > 1 ? "s" : ""}</div></div></div>`).join("");
		return { title: "Members — Toolhub", html: `
			<div class="container page">
				<h1 class="page__title">Members</h1>
				<p class="page__intro">Maintainers and authors who have tools in the catalog.</p>
				<div class="mgrid">${cards}</div>
			</div>` };
	}
	// Crawler history — uses the real last-crawl timestamp.
	function viewCrawler() {
		const last = DATA.lastCrawlTime ? new Date(DATA.lastCrawlTime).toUTCString() : "unknown";
		return { title: "Crawler history — Toolhub", html: `
			<div class="container page">
				<h1 class="page__title">Crawler history</h1>
				<p class="page__intro">Toolhub re-reads every registered <code>toolinfo.json</code> URL roughly hourly and updates the catalog with any changes.</p>
				<div class="detail__meta">
					${metaItem("Last crawl", esc(last))}
					${metaItem("Tools in catalog", fmt(DATA.totalTools))}
					${metaItem("Changes in last run", String(DATA.lastCrawlChanged != null ? DATA.lastCrawlChanged : 0))}
				</div>
				<p class="signin-note">Full per-run crawl logs are available on the live site.</p>
			</div>` };
	}
	// Audit log — illustrative feed built from catalog activity.
	function viewAudit() {
		const items = [...CATALOG].sort((a, b) => new Date(b.modified) - new Date(a.modified)).slice(0, 20);
		const verbs = ["updated", "published", "annotated", "created"];
		const rows = items.map((t) => `
			<li><a href="#/tools/${encodeURIComponent(t.name)}">
				<span class="feed__ic" aria-hidden="true">📝</span>
				<span class="feed__main">${esc(t.maintainer)} ${verbs[hash(t.name) % verbs.length]} <strong>${esc(t.title)}</strong></span>
				<span class="feed__when">${esc(relTime(t.modified))}</span></a></li>`).join("");
		return { title: "Audit logs — Toolhub", html: `
			<div class="container page">
				<h1 class="page__title">Audit logs</h1>
				<p class="page__intro">A record of changes across the catalog, for patrollers and administrators.</p>
				<ul class="feed">${rows}</ul>
				<p class="signin-note">Illustrative feed for the prototype; the live audit log is backed by the API.</p>
			</div>` };
	}
	// API docs — embed the live interactive documentation.
	function viewApiDocs() {
		return { title: "API documentation — Toolhub", html: `
			<div class="container page">
				<h1 class="page__title">API documentation</h1>
				<p class="page__intro">Toolhub is API-first — everything in this interface is available over HTTP. The interactive documentation is embedded below; if it doesn't load, open <a href="https://toolhub.wikimedia.org/api-docs" target="_blank" rel="noopener">toolhub.wikimedia.org/api-docs ↗</a>.</p>
				<iframe class="apidoc-frame" src="https://toolhub.wikimedia.org/api-docs" title="Toolhub API documentation" loading="lazy"></iframe>
			</div>` };
	}
	// Tool revision history — illustrative, from the tool's modified date.
	function viewToolHistory(name) {
		const t = INDEX[name];
		if (!t) return viewNotFound();
		const base = t.modified ? new Date(t.modified).getTime() : Date.now();
		const revs = [0, 1, 2, 3].map((i) => {
			const d = new Date(base - i * (3 + (hash(t.name + i) % 25)) * 86400000);
			return { id: 1000 + (hash(t.name) % 9000) - i, when: d.toISOString(), who: t.maintainer };
		});
		const rows = revs.map((r, i) => `
			<li><span class="feed__ic" aria-hidden="true">🕓</span>
				<span class="feed__main">Revision by <strong>${esc(r.who)}</strong> · ${esc(relTime(r.when))}${i === 0 ? ' <span class="tag">current</span>' : ""}</span>
				<a class="feed__when" href="#/tools/${encodeURIComponent(t.name)}/history/revision/${r.id}/diff/${r.id - 1}">view changes</a></li>`).join("");
		return { title: `History: ${t.title} — Toolhub`, html: `
			<div class="container page">
				<a class="back" href="#/tools/${encodeURIComponent(t.name)}">← Back to ${esc(t.title)}</a>
				<h1 class="page__title">Revision history</h1>
				<ul class="feed">${rows}</ul>
				<p class="signin-note">Illustrative history for the prototype; full revisions and diffs are on the live site.</p>
			</div>` };
	}
	function viewDiffStub(name) {
		const t = INDEX[name];
		return prosePage("Revision diff", `
			<p>Compare two revisions of <strong>${esc(t ? t.title : name)}</strong> side by side.</p>
			<p>Revision diffs are served from Toolhub's versioning API. In this prototype the
			diff viewer is not wired up — see it on the
			<a href="https://toolhub.wikimedia.org/" target="_blank" rel="noopener">live site</a>.</p>
			<p><a href="#/tools/${encodeURIComponent(name)}/history">← Back to history</a></p>`);
	}

	/* ---- Sign-in-required stubs (auth/write features) ---------------------- */
	function signInPage(title, lead) {
		return { title: `${title} — Toolhub`, html: `
			<div class="container page"><article class="prose prose--page">
				<h1>${esc(title)}</h1>
				<p>${lead}</p>
				<p>Toolhub uses your existing Wikimedia account via OAuth — no new account or
				password is needed.</p>
				<p><a class="btn btn--primary" href="https://toolhub.wikimedia.org/" target="_blank" rel="noopener">Continue on toolhub.wikimedia.org ↗</a></p>
				<p class="signin-note">In this prototype these actions are read-only: they need an
				authenticated session and the live back-end. See
				<a href="#/contribute">Help maintain Toolhub</a> to contribute.</p>
			</article></div>` };
	}

	function viewNotFound() {
		return { title: "Not found — Toolhub", html: `
			<div class="container page errorpage">
				<h1>Page not found</h1>
				<p class="prose">We couldn't find that page. It may have moved, or the link may be incomplete.</p>
				<a class="btn btn--primary" href="#/">Go to the home page</a>
			</div>` };
	}

	/* ====================================================================== router */
	function parseHash() {
		let h = location.hash.replace(/^#/, "");
		if (!h || h === "/") return { path: "/", query: {} };
		const [path, qs] = h.split("?");
		const query = {};
		new URLSearchParams(qs || "").forEach((v, k) => (query[k] = v));
		return { path, query };
	}
	/* ---- Quick-view modal (peek from any listing) -------------------------- */
	let qvLastFocus = null;
	function quickViewBody(t) {
		const st = t.status || { level: "green", label: "Healthy" };
		const authors = (t.authors || []).map(esc).join(", ") || esc(t.maintainer);
		const tags = (t.keywords || []).slice(0, 6).map((k) => `<a class="tag" href="#/search?kw=${encodeURIComponent(k)}">${esc(k)}</a>`).join("");
		const realBadge = (t.deprecated || t.experimental) ? `<span class="status status--${st.level}"><span class="dot dot--${st.level}"></span>${esc(st.label)}</span>` : "";
		const glance = [
			t.toolType && `<span class="glance">${esc(t.toolType)}</span>`,
			t.license && `<span class="glance">${esc(t.license)}</span>`,
			`<span class="glance">${esc(wikiLabel(t.forWikis))}</span>`,
			(t.uiLanguages && t.uiLanguages.length) && `<span class="glance">${t.uiLanguages.length} language${t.uiLanguages.length > 1 ? "s" : ""}</span>`,
		].filter(Boolean).join("");
		return `
			<div class="qv__head">${toolIcon(t, "lg")}
				<div class="qv__id"><h2 class="qv__title" id="qv-title">${esc(t.title)}</h2>
				<div class="qv__by">by ${authors}</div></div>
			</div>
			<div class="qv__status">
				${realBadge}
				<!-- EXPERIMENTAL — health/popularity (no API data) -->
				<span class="status status--green experimental"><span class="dot dot--green"></span>Healthy</span>
				<span class="views experimental">🔥 ${views(t.weeklyViews)}</span>
				<span class="toolpage__when">${esc(relTime(t.modified))}</span>
			</div>
			<p class="qv__desc">${esc(t.description) || "<em>No description provided.</em>"}</p>
			<div class="toolpage__glance">${glance}</div>
			<div class="tcard__tags qv__tags">${tags}</div>
			<div class="qv__actions">
				${t.url ? `<a class="btn btn--primary" href="${safeUrl(t.url)}" target="_blank" rel="noopener">Open tool ↗</a>` : ""}
				<a class="btn btn--outline" href="#/tools/${encodeURIComponent(t.name)}">View full page →</a>
			</div>`;
	}
	function openQuickView(name) {
		const t = INDEX[name];
		if (!t) { location.hash = "#/tools/" + encodeURIComponent(name); return; }
		$("#qv-body").innerHTML = quickViewBody(t);
		$("#qv").classList.remove("hidden");
		document.body.style.overflow = "hidden";
		qvLastFocus = document.activeElement;
		$(".qv__x").focus();
	}
	function closeQuickView() {
		const qv = $("#qv");
		if (!qv || qv.classList.contains("hidden")) return;
		qv.classList.add("hidden");
		document.body.style.overflow = "";
		if (qvLastFocus && qvLastFocus.focus) qvLastFocus.focus();
	}
	function qvTrap(e) {
		const qv = $("#qv");
		if (e.key !== "Tab" || qv.classList.contains("hidden")) return;
		const f = qv.querySelectorAll('a[href],button,[tabindex]:not([tabindex="-1"])');
		if (!f.length) return;
		const first = f[0], last = f[f.length - 1];
		if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
		else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
	}

	/* ---- Account: logged-in user fixture + profile dropdown ---------------- */
	const USER = { name: "Schiste" }; // demo fixture (a signed-in Wikimedia user)
	const AUTH_KEY = "toolhub-auth";
	function authIn() { return (localStorage.getItem(AUTH_KEY) || "in") !== "out"; } // default: signed in
	function setAuth(on) { localStorage.setItem(AUTH_KEY, on ? "in" : "out"); renderAccount(); }
	function renderAccount() {
		const el = document.getElementById("account");
		if (!el) return;
		if (!authIn()) {
			el.innerHTML = `<a class="btn btn--outline" href="#/login" data-login>Log in</a>`;
			return;
		}
		el.innerHTML = `
			<button class="acct__btn" id="acct-btn" type="button" aria-haspopup="menu" aria-expanded="false" aria-controls="acct-menu">
				${avatar(USER.name, "avatar--sm")}
				<span class="acct__name">${esc(USER.name)}</span>
				<span class="acct__caret" aria-hidden="true">▾</span>
			</button>
			<div class="acct__menu" id="acct-menu" role="menu" aria-label="Account" hidden>
				<div class="acct__head">Signed in as <strong>${esc(USER.name)}</strong></div>
				<a role="menuitem" href="#/my-lists"><span aria-hidden="true">📋</span> Your lists</a>
				<a role="menuitem" href="#/favorites"><span aria-hidden="true">⭐</span> Favorites</a>
				<a role="menuitem" href="#/add-or-remove-tools"><span aria-hidden="true">🧰</span> Add or remove tools</a>
				<a role="menuitem" href="#/developer-settings"><span aria-hidden="true">🔧</span> Developer settings</a>
				<hr />
				<button class="acct__logout" role="menuitem" type="button" data-logout><span aria-hidden="true">↪</span> Log out</button>
			</div>`;
	}
	function closeAcctMenu() {
		const m = document.getElementById("acct-menu"), b = document.getElementById("acct-btn");
		if (m) m.hidden = true;
		if (b) b.setAttribute("aria-expanded", "false");
	}
	function toggleAcctMenu() {
		const m = document.getElementById("acct-menu"), b = document.getElementById("acct-btn");
		if (!m) return;
		const willOpen = m.hidden;
		m.hidden = !willOpen;
		b.setAttribute("aria-expanded", String(willOpen));
		if (willOpen) { const first = m.querySelector("[role=menuitem]"); if (first) first.focus(); }
	}

	function dispatch() {
		const { path, query } = parseHash();
		const seg = path.split("/").filter(Boolean); // e.g. ["tools","foo"]
		if (path === "/") return viewHome();
		if (seg[0] === "search") return viewSearch(query);
		// Tool + its sub-routes
		if (seg[0] === "tools" && seg[1]) {
			const nm = decodeURIComponent(seg[1]);
			if (seg[2] === "edit") return signInPage("Edit tool", "Edit this tool's core information — title, description, URL and more. Only the owner or an administrator can change core data.");
			if (seg[2] === "edit-annotations") return signInPage("Edit annotations", "Add or refine community annotations for this tool — audiences, tasks and more.");
			if (seg[2] === "history") return seg[3] ? viewDiffStub(nm) : viewToolHistory(nm);
			return viewTool(nm);
		}
		// Lists + sub-routes
		if (seg[0] === "lists" && seg[1] === "create") return signInPage("Create a list", "Create a new list to group and share useful tools.");
		if (seg[0] === "lists" && seg[1]) {
			if (seg[2] === "edit") return signInPage("Edit list", "Edit this list's title, description and tools.");
			if (seg[2] === "history") return prosePage("List history", "<p>Revision history for this list is available on the <a href=\"https://toolhub.wikimedia.org/\" target=\"_blank\" rel=\"noopener\">live site</a>.</p>");
			return viewList(seg[1]);
		}
		if (seg[0] === "lists" || seg[0] === "published-lists") return viewLists();
		if (seg[0] === "my-lists") return signInPage("Your lists", "See and manage the lists you've created.");
		if (seg[0] === "favorites") return signInPage("Favorites", "Your saved tools, all in one place.");
		if (seg[0] === "add-or-remove-tools") return signInPage("Add or remove tools", "Register a toolinfo.json URL to be crawled, or create a tool record directly.");
		if (seg[0] === "developer-settings") return signInPage("Developer settings", "Manage your API tokens and registered OAuth applications.");
		if (seg[0] === "login") return signInPage("Sign in", "Sign in to save favourites, build lists, and edit tool information.");
		// Maintenance / discovery pages
		if (seg[0] === "recent") return viewRecent();
		if (seg[0] === "members") return viewMembers();
		if (seg[0] === "crawler-history") return viewCrawler();
		if (seg[0] === "audit-logs") return viewAudit();
		if (seg[0] === "api-docs") return viewApiDocs();
		if (seg[0] === "contribute") return viewContribute();
		if (STATIC[seg[0]]) return viewStatic(seg[0]);
		return viewNotFound();
	}
	function setActiveNav() {
		const h = "#" + (parseHash().path);
		$$("#nav-links a").forEach((a) => {
			const href = a.getAttribute("href");
			a.classList.toggle("is-active", href === h || (h.startsWith("#/search") && href === "#/search") || (h.startsWith("#/lists") && href === "#/lists"));
		});
	}
	let lastPath = null;
	function render() {
		closeQuickView(); // any navigation dismisses the peek modal
		closeAcctMenu();  // …and the account dropdown
		const view = dispatch();
		const { path } = parseHash();
		$("#view").innerHTML = view.html;
		document.body.classList.toggle("on-home", path === "/"); // expbar blends with the hero on home
		document.title = view.title || "Toolhub";
		if (typeof view.mount === "function") view.mount();
		setActiveNav();
		// Only reset scroll/focus on a real page change (not in-page filter sync).
		if (path !== lastPath) {
			window.scrollTo({ top: 0, behavior: "auto" });
			const h1 = $("#view h1") || $("#view");
			h1.setAttribute("tabindex", "-1");
			h1.focus({ preventScroll: true });
			lastPath = path;
		}
	}

	/* Skip link focuses the view without hijacking the route. */
	const skip = $(".skip");
	if (skip) skip.addEventListener("click", (e) => { e.preventDefault(); const m = $("#view"); m.focus(); m.scrollIntoView(); });

	/* Keyword chips INSIDE a card anchor: intercept so they filter search
	   instead of following the card's link to the tool page. */
	$("#view").addEventListener("click", (e) => {
		const q = e.target.closest("[data-q]");
		if (q && !q.matches("a[href]")) { e.preventDefault(); location.hash = "#/search?q=" + encodeURIComponent(q.getAttribute("data-q")); return; }
		if (e.target.closest("a[href]")) return; // real links route natively
		const card = e.target.closest("[data-tool]");
		if (card) { openQuickView(card.getAttribute("data-tool")); } // default: peek
	});
	// Keyboard: Enter/Space on a focused tool card opens the quick-view.
	$("#view").addEventListener("keydown", (e) => {
		if (e.key !== "Enter" && e.key !== " ") return;
		const card = e.target.closest("[data-tool]");
		if (card && e.target === card) { e.preventDefault(); openQuickView(card.getAttribute("data-tool")); }
	});

	/* Quick-view modal: backdrop/close + keyword chips, Esc + Tab-trap */
	$("#qv").addEventListener("click", (e) => {
		if (e.target.id === "qv" || e.target.closest("[data-qv-close]")) { e.preventDefault(); closeQuickView(); return; }
		const q = e.target.closest("[data-q]");
		if (q && !q.matches("a[href]")) { e.preventDefault(); closeQuickView(); location.hash = "#/search?q=" + encodeURIComponent(q.getAttribute("data-q")); }
	});
	document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeQuickView(); closeAcctMenu(); } else { qvTrap(e); } });

	/* Account dropdown: toggle, log out / log in, close on outside click */
	const accountEl = document.getElementById("account");
	if (accountEl) accountEl.addEventListener("click", (e) => {
		if (e.target.closest("#acct-btn")) { e.preventDefault(); toggleAcctMenu(); return; }
		if (e.target.closest("[data-logout]")) { e.preventDefault(); closeAcctMenu(); setAuth(false); return; }
		if (e.target.closest("[data-login]")) { e.preventDefault(); setAuth(true); return; }
		if (e.target.closest("[role=menuitem]")) { closeAcctMenu(); } // links route natively
	});
	document.addEventListener("click", (e) => { if (!e.target.closest("#account")) closeAcctMenu(); });
	renderAccount();

	/* Experimental toggle: persist, flip body state, re-render so JS-conditional
	   experimental logic (e.g. the sort options) updates too. */
	const expBtn = $("#exp-toggle");
	if (expBtn) expBtn.addEventListener("click", () => {
		const on = !expOn();
		localStorage.setItem(EXP_KEY, on ? "on" : "off");
		applyExp(on);
		render();
	});

	/* Most links are real <a href="#/..."> and route natively via hashchange. */
	window.addEventListener("hashchange", render);
	render();
})();
