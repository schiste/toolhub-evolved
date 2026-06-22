// SPDX-License-Identifier: GPL-3.0-or-later
/* Toolhub demonstrator — a small hash-routed multi-view app that reads the
   live, read-only Toolhub API through a same-origin proxy. Experimental
   signals (weeklyViews, reviews, usage) are synthesized client-side and clearly
   badged; the API has no popularity signal. */
(function () {
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
	const DEFAULT_LOCALE = "en";
	const RTL_LANGS = new Set(["ar", "arc", "ckb", "dv", "fa", "ha", "he", "khw", "ks", "ku", "ps", "sd", "ug", "ur", "yi"]);
	function appLocale() {
		const stored = localStorage.getItem("toolhub-locale");
		return (stored || DEFAULT_LOCALE).replace(/_/g, "-");
	}
	const LOCALE = appLocale();
	const numberFmt = new Intl.NumberFormat(LOCALE);
	const compactNumberFmt = new Intl.NumberFormat(LOCALE, { notation: "compact", maximumFractionDigits: 1 });
	const relativeTimeFmt = new Intl.RelativeTimeFormat(LOCALE, { numeric: "auto" });
	const dateTimeFmt = new Intl.DateTimeFormat(LOCALE, { dateStyle: "medium", timeStyle: "short" });
	const pluralRules = new Intl.PluralRules(LOCALE);
	function localeDir(locale) { return RTL_LANGS.has(String(locale).split("-")[0].toLowerCase()) ? "rtl" : "ltr"; }
	function applyLocaleAttrs() {
		document.documentElement.lang = LOCALE;
		document.documentElement.dir = localeDir(LOCALE);
	}
	function dirAttrs(value) { return value ? ' dir="auto"' : ""; }
	function fmt(n) { return numberFmt.format(Number(n) || 0); }
	function compactFmt(n) { return compactNumberFmt.format(Number(n) || 0); }
	function plural(n, forms) {
		const cat = pluralRules.select(Math.abs(Number(n) || 0));
		return forms[cat] || forms.other || forms.one || "";
	}
	function countLabel(n, one, other) {
		const value = Number(n) || 0;
		return `${fmt(value)} ${plural(value, { one, other })}`;
	}
	function relativeTime(iso) {
		if (!iso) return "";
		const date = new Date(iso);
		if (Number.isNaN(date.getTime())) return "";
		const delta = date.getTime() - Date.now();
		const abs = Math.abs(delta);
		if (abs < 86400000) return relativeTimeFmt.format(0, "day");
		if (abs < 30 * 86400000) return relativeTimeFmt.format(Math.round(delta / 86400000), "day");
		if (abs < 365 * 86400000) return relativeTimeFmt.format(Math.round(delta / (30 * 86400000)), "month");
		return relativeTimeFmt.format(Math.round(delta / (365 * 86400000)), "year");
	}
	function relTime(iso) {
		const rel = relativeTime(iso);
		return rel ? `Updated ${rel}` : "";
	}
	function timeTag(iso, cls, text) {
		if (!iso) return "";
		const date = new Date(iso);
		if (Number.isNaN(date.getTime())) return "";
		const label = text || relativeTime(iso);
		const classAttr = cls ? ` class="${esc(cls)}"` : "";
		return `<time${classAttr} datetime="${esc(date.toISOString())}" title="${esc(dateTimeFmt.format(date))}">${esc(label)}</time>`;
	}
	function updatedTimeTag(iso, cls) { return timeTag(iso, cls, relTime(iso)); }
	function views(n) { return `${compactFmt(n)} ${plural(n, { one: "view", other: "views" })}`; }
	applyLocaleAttrs();
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

	/* Tool cache for O(1) detail / quick-view lookups; filled by normalizeTool()
	   as live data arrives (search results, lists, tool pages). No snapshot. */
	const INDEX = {};

	/* ===================================================================== LIVE API
	   Every read goes through the same-origin proxy (/api → toolhub.wikimedia.org/api).
	   Tool/list objects are normalized to the compact shape the views/cards expect.
	   There is no bundled snapshot — the catalog is always the live one. */
	const API_BASE = "/api";
	async function apiGet(path, params) {
		const qs = params ? "?" + new URLSearchParams(params).toString() : "";
		const res = await fetch(API_BASE + path + qs, { headers: { Accept: "application/json" } });
		if (!res.ok) throw new Error("API " + res.status + " " + path);
		return res.json();
	}
	function firstUrl(v) {
		if (!v) return null;
		if (typeof v === "string") return v;
		if (Array.isArray(v) && v.length) { const x = v[0]; return x && typeof x === "object" ? x.url : x; }
		return null;
	}
	function hasValue(v) { return Array.isArray(v) ? v.length > 0 : v != null && v !== ""; }
	function pick(core, annotation, fallback) {
		if (hasValue(core)) return core;
		if (hasValue(annotation)) return annotation;
		return fallback;
	}
	// EXPERIMENTAL — popularity. MISSING: no usage/view data in the API; synthesized
	// deterministically from the tool name so the "popular" ordering is stable.
	function synthViews(name) { const h = hash(name), b = h % 100; return b >= 92 ? 1000 + (h % 1500) : b >= 70 ? 250 + (h % 750) : 20 + (h % 230); }
	function statusOf(t) { return t.deprecated ? { level: "red", label: "Deprecated" } : t.experimental ? { level: "yellow", label: "Experimental" } : { level: "green", label: "Healthy" }; }
	function normalizeTool(t) {
		const ann = t.annotations || {};
		const ra = t.author;
		const authors = Array.isArray(ra)
			? ra.map((a) => (a && a.name) || (typeof a === "string" ? a : null)).filter(Boolean)
			: typeof ra === "string" && ra ? [ra] : [];
		const o = {
			name: t.name, title: t.title || t.name, description: t.description || "", url: pick(t.url, ann.url, ""), icon: pick(t.icon, ann.icon, null),
			keywords: t.keywords || [], maintainer: authors[0] || (t.created_by && t.created_by.username) || "Unknown", authors,
			toolType: pick(t.tool_type, ann.tool_type, null), license: pick(t.license, ann.license, null),
			repository: pick(t.repository, ann.repository, null), apiUrl: pick(t.api_url, ann.api_url, null),
			technologyUsed: pick(t.technology_used, ann.technology_used, []),
			audiences: pick(t.audiences, ann.audiences, []), tasks: pick(t.tasks, ann.tasks, []),
			forWikis: pick(t.for_wikis, ann.for_wikis, []), uiLanguages: pick(t.available_ui_languages, ann.available_ui_languages, []),
			userDocs: firstUrl(pick(t.user_docs_url, ann.user_docs_url, [])),
			devDocs: firstUrl(pick(t.developer_docs_url, ann.developer_docs_url, [])),
			feedback: firstUrl(pick(t.feedback_url, ann.feedback_url, [])),
			bugtracker: pick(t.bugtracker_url, ann.bugtracker_url, null), translate: pick(t.translate_url, ann.translate_url, null),
			deprecated: !!(t.deprecated || ann.deprecated), experimental: !!(t.experimental || ann.experimental), modified: t.modified_date || t.modified || null,
		};
		o.weeklyViews = synthViews(o.name);
		o.status = statusOf(o);
		INDEX[o.name] = o; // cache for quick-view
		return o;
	}
	function normalizeList(l) {
		const tools = (l.tools || []).map(normalizeTool);
		return {
			id: l.id, title: l.title || "Untitled list", description: l.description || "",
			toolCount: tools.length, tools, featured: !!l.featured,
		};
	}

	/* ------------------------------------------------------------ card markup */
	function toolCard(t, opts) {
		opts = opts || {};
		// (3) Tags: 2 + "+N" overflow chip so every card is the same height.
		const allk = t.keywords || [];
		const tags = allk.slice(0, 2).map((k) => `<span class="tag" data-q="${esc(k)}"${dirAttrs(k)}>${esc(k)}</span>`).join("")
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
			? `<span class="views experimental"><span aria-hidden="true">🔥</span> ${views(t.weeklyViews)}</span>`
			: `<span class="tcard__meta"${dirAttrs(meta)}>${meta}</span>`;
		// The whole card opens the quick-view; (5) a hover cue signals the peek.
		return `
		<article class="tcard${opts.popular ? " tcard--popular" : ""}" data-tool="${esc(t.name)}" role="button" tabindex="0" aria-label="Quick look: ${esc(t.title)}">
			${flag}
			<div class="tcard__head">
				${rank}${toolIcon(t)}
				<div class="tcard__heading">
					<div class="tcard__title"${dirAttrs(t.title)}>${esc(t.title)}</div>
					<div class="tcard__maint">by <span${dirAttrs(t.maintainer)}>${esc(t.maintainer)}</span></div>
				</div>
			</div>
			<p class="tcard__desc"${dirAttrs(t.description)}>${esc(t.description)}</p>
			<div class="tcard__tags">${tags}</div>
			<div class="tcard__foot">${footLeft}${updatedTimeTag(t.modified, "tcard__when")}</div>
			<span class="tcard__hint" aria-hidden="true">🔍</span>
		</article>`;
	}
	function listCard(l) {
		const count = countLabel(l.toolCount, "tool", "tools");
		return `
		<a class="lcard" href="#/lists/${encodeURIComponent(l.id)}" aria-label="${esc(l.title)} list, ${esc(count)}">
			${avatar(l.title)}
			<div class="lcard__body">
				<div class="lcard__title"${dirAttrs(l.title)}>${esc(l.title)} <span class="lcard__count">${esc(count)}</span></div>
				<div class="lcard__desc"${dirAttrs(l.description)}>${esc(l.description)}</div>
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

	async function viewHome() {
		// Live: total count, featured curated lists (with embedded tools), recent tools.
		const [home, flists, recent] = await Promise.all([
			apiGet("/ui/home/").catch(() => ({})),
			apiGet("/lists/", { featured: "true", page_size: "6" }).catch(() => ({ results: [] })),
			apiGet("/search/tools/", { ordering: "-modified_date", page_size: "5" }).catch(() => ({ results: [] })),
		]);
		const total = home.total_tools || 0;
		const lists = (flists.results || []).map(normalizeList);
		// "Featured tools" = the curated tools drawn from the featured lists (deduped).
		const seen = new Set(), featured = [];
		for (const l of lists) for (const t of l.tools) if (!seen.has(t.name)) { seen.add(t.name); featured.push(t); }
		const popular = featured.slice().sort((a, b) => (b.weeklyViews - a.weeklyViews) || a.title.localeCompare(b.title));
		const recentTools = (recent.results || []).map(normalizeTool);

		const personas = PERSONAS.map(([ic, l, q]) => `<a class="persona" href="#/search?q=${encodeURIComponent(q)}"><span aria-hidden="true">${ic}</span> ${l}</a>`).join("");
		const needs = NEEDS.map(([ic, l, q]) => `<li><a href="#/search?q=${encodeURIComponent(q)}"><span aria-hidden="true">${ic}</span> ${l}<span class="need__chev" aria-hidden="true">›</span></a></li>`).join("");
		const steps = STEPS.map(([ic, t, d]) => `<div class="step"><div class="step__icon" aria-hidden="true">${ic}</div><div class="step__title">${t}</div><div class="step__desc">${d}</div></div>`).join("");
		const recentHtml = recentTools.map((t) => `
			<li><a href="#/tools/${encodeURIComponent(t.name)}">${avatar(t.title)}
				<div><div class="recent__title"${dirAttrs(t.title)}>${esc(t.title)}</div>
				<div class="recent__meta">Maintainer: <span${dirAttrs(t.maintainer)}>${esc(t.maintainer)}</span></div></div>
				${updatedTimeTag(t.modified, "recent__when")}</a></li>`).join("");

		const html = `
		<section class="hero">
			<h1 class="hero__title">Find the right Wikimedia tool faster</h1>
			<form class="search" role="search" data-home-search>
				<label for="home-q" class="skip-label">Search tools</label>
				<input id="home-q" class="search__input" type="search" aria-label="Search tools" placeholder="Search ${esc(countLabel(total, "tool", "tools"))}…" autocomplete="off" />
				<button class="btn btn--primary search__btn" type="submit">Search</button>
			</form>
		</section>
		<section class="personas container"><span class="personas__label">I'm looking for tools for:</span><div class="personas__row">${personas}</div></section>
		<div class="container layout">
			<div class="layout__main">
				<div class="section-head"><h2>Featured tools</h2><a class="link" href="#/lists/${encodeURIComponent((lists[0] || {}).id || "")}">View all</a></div>
				${grid("grid-tools", featured.slice(0, 8), (t) => toolCard(t))}
				<!-- EXPERIMENTAL — "Popular this week" ranks by weeklyViews.
				     MISSING: no popularity/usage signal in the Toolhub API; ranks shown here are synthetic. -->
				<div class="experimental">
					<div class="section-head"><h2>Popular this week <span class="exp-badge">Experimental</span></h2><a class="link" href="#/search?sort=views">View all</a></div>
					${grid("grid-tools", popular.slice(0, 8), (t, i) => toolCard(t, { rank: i + 1, popular: true }))}
				</div>
				<div class="section-head"><h2>Curated lists</h2><a class="link" href="#/lists">View all lists</a></div>
				${grid("grid-lists", lists.slice(0, 6), listCard)}
				<div class="section-head"><h2>Getting started</h2></div>
				<div class="card-grid grid-steps">${steps}</div>
			</div>
			<aside class="layout__side">
				<div class="panel"><h3 class="panel__title">Browse by need</h3><ul class="needs">${needs}</ul><a class="link panel__foot" href="#/search">View all categories</a></div>
				<div class="panel"><h3 class="panel__title">Recently updated</h3><ul class="recent">${recentHtml}</ul></div>
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
	// Facet groups we surface (a subset of the API's 11), in display order.
	const FACET_GROUPS = [
		{ field: "tool_type", label: "Tool type" }, { field: "keywords", label: "Keywords" },
		{ field: "audiences", label: "Audience" }, { field: "ui_language", label: "Interface language" },
		{ field: "license", label: "License" }, { field: "wiki", label: "Works on wiki" },
	];
	function renderFacetGroup(g, facets, selected) {
		const wrap = facets && facets["_filter_" + g.field];
		const inner = wrap && wrap[g.field];
		if (!inner) return "";
		const param = inner.meta && inner.meta.param;
		const buckets = (inner.buckets || []).filter((b) => b.key !== "--" && b.doc_count > 0).slice(0, 10);
		if (!buckets.length || !param) return "";
		const rows = buckets.map((b) => {
			const checked = selected.has(param + "=" + b.key) ? " checked" : "";
			return `<label class="facet"><input type="checkbox" data-facet="${esc(param)}" value="${esc(b.key)}"${checked}> <span${dirAttrs(b.key)}>${esc(b.key)}</span> <span class="facet__n">${fmt(b.doc_count)}</span></label>`;
		}).join("");
		return `<div class="facet-group"><h2 class="facet-group__title">${esc(g.label)}</h2>${rows}</div>`;
	}
	async function viewSearch() {
		const usp = new URLSearchParams(location.hash.split("?")[1] || "");
		const q = usp.get("q") || "";
		const page = Math.max(1, parseInt(usp.get("page")) || 1);
		const exp = expOn();
		const defaultSort = exp ? "relevance" : "recent";
		const requestedSort = usp.get("sort") || defaultSort;
		const allowedSorts = exp ? ["relevance", "recent", "name", "views"] : ["recent", "name"];
		const sort = allowedSorts.includes(requestedSort) ? requestedSort : defaultSort;
		const ordering = sort === "name" ? "name" : sort === "recent" ? "-modified_date" : "";

		// Live API params: q, paging, ordering + every *__term facet filter from the URL.
		const api = new URLSearchParams();
		if (q) api.set("q", q);
		api.set("page", String(page));
		api.set("page_size", String(PAGE_SIZE));
		if (ordering) api.set("ordering", ordering);
		const selected = new Set();
		for (const [k, v] of usp.entries()) {
			if (k.endsWith("__term")) { api.append(k, v); selected.add(k + "=" + v); }
		}

		const data = await apiGet("/search/tools/", api);
		const results = (data.results || []).map(normalizeTool);
		if (sort === "views") results.sort((a, b) => (b.weeklyViews - a.weeklyViews) || a.title.localeCompare(b.title));
		const total = data.count || 0;
		const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
		const facetHTML = FACET_GROUPS.map((g) => renderFacetGroup(g, data.facets, selected)).join("");

		const sortOpts = (exp ? '<option value="relevance">Most relevant</option>' : "") +
			'<option value="recent">Recently updated</option><option value="name">Name (A–Z)</option>' +
			(exp ? '<option value="views">Popular this week</option>' : "");
		const pagerHTML = (() => {
			if (pages <= 1) return "";
			const btn = (p, label, dis, cur) => `<button class="pager__btn${cur ? " is-current" : ""}" type="button" ${dis ? "disabled" : ""} data-page="${p}"${cur ? ' aria-current="page"' : ""}>${label}</button>`;
			let out = btn(page - 1, "‹ Prev", page <= 1), last = 0;
			const win = [];
			for (let p = 1; p <= pages; p++) if (p === 1 || p === pages || Math.abs(p - page) <= 2) win.push(p);
			win.forEach((p) => { if (p - last > 1) out += '<span class="pager__gap">…</span>'; out += btn(p, p, false, p === page); last = p; });
			return out + btn(page + 1, "Next ›", page >= pages);
		})();

		const html = `
		<div class="container page">
			<h1 class="page__title">Browse tools</h1>
			<div class="browse">
				<aside class="facets" aria-label="Filters">
					<form data-facet-q role="search">
						<label for="facet-q" class="skip-label">Search within tools</label>
						<input id="facet-q" class="facets__search" type="search" placeholder="Search tools…" autocomplete="off" value="${esc(q)}" />
					</form>
					${facetHTML || '<p class="facet__empty">No filters available.</p>'}
					<a class="btn btn--outline facets__reset" href="#/search">Clear filters</a>
				</aside>
				<div class="browse__main">
					<div class="browse__bar">
						<span class="browse__count" aria-live="polite">${esc(countLabel(total, "tool", "tools"))}${q ? ` for &ldquo;<span${dirAttrs(q)}>${esc(q)}</span>&rdquo;` : ""}</span>
						<label class="sort"><span class="skip-label">Sort by</span><select id="sort">${sortOpts}</select></label>
					</div>
					<div class="card-grid grid-tools">${results.length ? results.map((t, i) => toolCard(t, sort === "views" ? { rank: ((page - 1) * PAGE_SIZE) + i + 1, popular: true } : {})).join("") : '<p class="empty">No tools match these filters.</p>'}</div>
					<nav class="pager" aria-label="Pagination">${pagerHTML}</nav>
				</div>
			</div>`;

		function mount() {
			$("#sort").value = sort;
			const navigate = (extra) => {
				const u = new URLSearchParams();
				const qv = $("#facet-q").value.trim(); if (qv) u.set("q", qv);
				$$(".facets input[type=checkbox]:checked").forEach((c) => u.append(c.getAttribute("data-facet"), c.value));
				const sv = $("#sort").value; if (sv && sv !== defaultSort) u.set("sort", sv);
				if (extra && extra.page > 1) u.set("page", String(extra.page));
				location.hash = "#/search" + (u.toString() ? "?" + u.toString() : "");
			};
			$(".facets").addEventListener("change", () => navigate({}));
			$("#sort").addEventListener("change", () => navigate({}));
			$("[data-facet-q]").addEventListener("submit", (e) => { e.preventDefault(); navigate({}); });
			$(".pager").addEventListener("click", (e) => {
				const b = e.target.closest("[data-page]"); if (!b) return;
				navigate({ page: parseInt(b.getAttribute("data-page")) });
			});
		}
		return { title: q ? `“${q}” — Toolhub` : "Browse tools — Toolhub", html, mount };
	}
	function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

	/* ---- Tool detail page (T3) --------------------------------------------- */
	function metaItem(k, v) { return `<div><div class="meta__k">${k}</div><div class="meta__v" dir="auto">${v || "—"}</div></div>`; }
	function linkOut(label, url) { const u = safeUrl(url); return u ? `<a class="btn btn--outline" href="${u}" target="_blank" rel="noopener">${label} <span aria-hidden="true">↗</span></a>` : ""; }
	// REAL — related tools derived from shared keywords (no missing data).
	async function relatedTools(t) {
		const kw = (t.keywords || [])[0];
		if (!kw) return [];
		try {
			const data = await apiGet("/search/tools/", { keywords__term: kw, page_size: "5" });
			return (data.results || []).map(normalizeTool).filter((o) => o.name !== t.name).slice(0, 4);
		} catch (e) { return []; }
	}
	const wikiLabel = (a) => (!a || !a.length ? "Any wiki" : a.includes("*") ? "All wikis" : a.map(esc).join(", "));
	const langLabel = (a) => (!a || !a.length ? "English (default)" : a.map(esc).join(", "));
	// Compact "works on" label for cards (full list shown on the detail page).
	const wikiShort = (a) => (!a || !a.length ? "Any wiki" : a.includes("*") ? "All wikis" : (a.length === 1 ? a[0] : countLabel(a.length, "wiki", "wikis")));

	async function viewTool(name) {
		let t;
		try { t = normalizeTool(await apiGet("/tools/" + encodeURIComponent(name) + "/")); }
		catch (e) { return viewNotFound(); }
		const st = t.status || { level: "green", label: "Healthy" };
		const tags = (t.keywords || []).map((k) => `<a class="tag" href="#/search?keywords__term=${encodeURIComponent(k)}"${dirAttrs(k)}>${esc(k)}</a>`).join("") || "—";
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

		const related = await relatedTools(t);
		const relatedHtml = related.length
			? `<h2 class="toolpage__h2">Related tools</h2>${grid("grid-tools", related, (x) => toolCard(x))}`
			: "";

		// At-a-glance chips (real metadata).
		const glance = [
			t.toolType && `<span class="glance"${dirAttrs(t.toolType)}>${esc(t.toolType)}</span>`,
			t.license && `<span class="glance"${dirAttrs(t.license)}>${esc(t.license)}</span>`,
			`<span class="glance"${dirAttrs(wikiLabel(t.forWikis))}>${esc(wikiLabel(t.forWikis))}</span>`,
			(t.uiLanguages && t.uiLanguages.length) && `<span class="glance">${esc(countLabel(t.uiLanguages.length, "language", "languages"))}</span>`,
		].filter(Boolean).join("");

		const maintList = (t.authors && t.authors.length ? t.authors : [t.maintainer])
			.map((a) => `<li>${avatar(a)}<span${dirAttrs(a)}>${esc(a)}</span></li>`).join("");

		const html = `
		<div class="container page">
			<a class="back" href="#/search">← Back to tools</a>
			<header class="toolpage__head">
				${toolIcon(t, "lg")}
				<div class="toolpage__id">
					<h1 class="toolpage__title"${dirAttrs(t.title)}>${esc(t.title)}</h1>
					<div class="toolpage__by">by <span dir="auto">${authors}</span></div>
					<div class="toolpage__glance">${glance}</div>
					<div class="toolpage__row">
						${realBadge}
						<!-- EXPERIMENTAL — operational health. MISSING: no uptime/health-check backend. -->
						<span class="status status--green experimental"><span class="dot dot--green"></span>Healthy</span>
						<!-- EXPERIMENTAL — popularity. MISSING: no usage/view tracking in the API. -->
						<span class="views experimental"><span aria-hidden="true">🔥</span> ${views(t.weeklyViews)}</span>
						${updatedTimeTag(t.modified, "toolpage__when")}
					</div>
				</div>
				<div class="toolpage__cta">
					${t.url ? `<a class="btn btn--primary btn--lg" href="${safeUrl(t.url)}" target="_blank" rel="noopener">Open tool <span aria-hidden="true">↗</span></a>` : ""}
					<!-- EXPERIMENTAL — save/bookmark. MISSING: needs an authenticated session. -->
					<button class="btn btn--outline experimental" type="button"><span aria-hidden="true">🔖</span> Save to a list</button>
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

					<div class="prose"${dirAttrs(t.description)}>${esc(t.description) || "<em>No description provided.</em>"}</div>
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
							<span class="reviews__count">· ${esc(countLabel(18, "review", "reviews"))}</span>
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
						<p class="usage"><strong>${fmt(2000 + (hash(t.name) % 9000))}</strong> ${plural(2000 + (hash(t.name) % 9000), { one: "editor used", other: "editors used" })} this in the last 30 days</p>
					</div>
				</aside>
			</div>
		</div>`;
		return { title: `${t.title} — Toolhub`, html };
	}

	/* ---- Lists overview + list detail -------------------------------------- */
	async function viewLists() {
		const data = await apiGet("/lists/", { page_size: "30" }).catch(() => ({ results: [] }));
		const lists = (data.results || []).map(normalizeList);
		const html = `
		<div class="container page">
			<h1 class="page__title">Curated lists</h1>
			<p class="page__intro">Community-published collections of tools for specific tasks and communities.</p>
			${lists.length ? grid("grid-lists", lists, listCard) : '<p class="empty">No lists found.</p>'}
		</div>`;
		return { title: "Curated lists — Toolhub", html };
	}
	async function viewList(id) {
		let l;
		try { l = normalizeList(await apiGet("/lists/" + encodeURIComponent(id) + "/")); }
		catch (e) { return viewNotFound(); }
		const html = `
		<div class="container page">
			<a class="back" href="#/lists">← All lists</a>
			<h1 class="page__title"${dirAttrs(l.title)}>${esc(l.title)} <span class="lcard__count">${esc(countLabel(l.toolCount, "tool", "tools"))}</span></h1>
			<div class="prose page__intro"${dirAttrs(l.description)}>${esc(l.description)}</div>
			${l.tools.length ? grid("grid-tools", l.tools, (t) => toolCard(t)) : '<p class="empty">This list has no tools yet.</p>'}
		</div>`;
		return { title: `${l.title} — Toolhub`, html };
	}

	/* ---- Static prose pages (T9) ------------------------------------------- */
	function prosePage(title, bodyHtml) {
		return { title: `${title} — Toolhub`, html: `<div class="container page"><article class="prose prose--page"><h1>${esc(title)}</h1>${bodyHtml}</article></div>` };
	}
	const ext = (url, label) => `<a href="${safeUrl(url)}" target="_blank" rel="noopener">${esc(label)} <span aria-hidden="true">↗</span></a>`;
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
			<blockquote>This is a design prototype that reads live, read-only data from the
			public Toolhub API — not the production site.</blockquote>` },
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
		const arrow = internal ? "" : ' <span aria-hidden="true">↗</span>';
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
	// Recent changes — live from /api/recent/ (deep-links tools via content_id slug).
	async function viewRecent() {
		const data = await apiGet("/recent/", { page_size: "30" }).catch(() => ({ results: [] }));
		const rows = (data.results || []).map((r) => {
			const title = esc(r.content_title || r.content_id || "—");
			const who = esc((r.user && r.user.username) || "system");
			const inner = `<span class="feed__ic" aria-hidden="true">✎</span>
				<span class="feed__main"><strong dir="auto">${title}</strong> <span class="feed__sub">${esc(r.content_type || "item")} · <span dir="auto">${who}</span></span></span>
				${timeTag(r.timestamp, "feed__when")}`;
			const link = r.content_type === "tool" && r.content_id
				? "#/tools/" + encodeURIComponent(r.content_id)
				: r.content_type === "list" && r.content_id ? "#/lists/" + encodeURIComponent(r.content_id) : null;
			return link ? `<li><a href="${link}">${inner}</a></li>` : `<li><div class="feed__static">${inner}</div></li>`;
		}).join("");
		return { title: "Recent changes — Toolhub", html: `
			<div class="container page">
				<h1 class="page__title">Recent changes</h1>
				<p class="page__intro">The latest edits across the catalog.</p>
				<ul class="feed">${rows || '<li><div class="feed__static">No recent changes.</div></li>'}</ul>
			</div>` };
	}
	// Members — live from /api/users/.
	async function viewMembers() {
		const data = await apiGet("/users/", { page_size: "60" }).catch(() => ({ results: [], count: 0 }));
		const cards = (data.results || []).map((u) => {
			const meta = u.groups && u.groups.length ? esc(u.groups.join(", ")) : "Member";
			return `<div class="mcard">${avatar(u.username)}<div class="mcard__b">
				<div class="mcard__n"${dirAttrs(u.username)}>${esc(u.username)}</div>
				<div class="mcard__c">${meta} · joined ${timeTag(u.date_joined)}</div></div></div>`;
		}).join("");
		return { title: "Members — Toolhub", html: `
			<div class="container page">
				<h1 class="page__title">Members</h1>
				<p class="page__intro">${esc(countLabel(data.count || 0, "registered Wikimedian", "registered Wikimedians"))} contribute to the catalog.</p>
				<div class="mgrid">${cards}</div>
			</div>` };
	}
	// Crawler history — live from /api/crawler/runs/.
	async function viewCrawler() {
		const data = await apiGet("/crawler/runs/", { page_size: "12" }).catch(() => ({ results: [] }));
		const runs = data.results || [];
		const last = runs[0] || {};
		const rows = runs.map((r) => `
			<tr><td>${timeTag(r.start_date)}</td><td>${fmt(r.crawled_urls || 0)}</td>
			<td>${fmt(r.new_tools || 0)}</td><td>${fmt(r.updated_tools || 0)}</td><td>${fmt(r.total_tools || 0)}</td></tr>`).join("");
		return { title: "Crawler history — Toolhub", html: `
			<div class="container page">
				<h1 class="page__title">Crawler history</h1>
				<p class="page__intro">Toolhub re-reads every registered <code>toolinfo.json</code> URL roughly hourly and updates the catalog with any changes.</p>
				<div class="detail__meta">
					${metaItem("Last crawl", timeTag(last.start_date))}
					${metaItem("URLs crawled", fmt(last.crawled_urls || 0))}
					${metaItem("Updated in last run", fmt(last.updated_tools || 0))}
				</div>
				<table class="runs">
					<thead><tr><th>Run</th><th>URLs</th><th>New</th><th>Updated</th><th>Total</th></tr></thead>
					<tbody>${rows}</tbody>
				</table>
			</div>` };
	}
	// Audit logs — live from /api/auditlogs/.
	function targetHref(target) {
		if (!target || !target.id) return null;
		if (target.type === "tool") return "#/tools/" + encodeURIComponent(target.id);
		if (target.type === "list") return "#/lists/" + encodeURIComponent(target.id);
		return null;
	}
	async function viewAudit() {
		const data = await apiGet("/auditlogs/", { page_size: "25" }).catch(() => ({ results: [] }));
		const rows = (data.results || []).map((a) => {
			const who = esc((a.user && a.user.username) || "System");
			const tgt = a.target ? `${esc(a.target.type)} “${esc(a.target.label)}”` : "";
			const inner = `<span class="feed__ic" aria-hidden="true">📝</span>
				<span class="feed__main"><span dir="auto">${who}</span> <em>${esc(a.action || "changed")}</em> <span dir="auto">${tgt}</span></span>
				${timeTag(a.timestamp, "feed__when")}`;
			const href = targetHref(a.target);
			return href ? `<li><a href="${href}">${inner}</a></li>` : `<li><div class="feed__static">${inner}</div></li>`;
		}).join("");
		return { title: "Audit logs — Toolhub", html: `
			<div class="container page">
				<h1 class="page__title">Audit logs</h1>
				<p class="page__intro">A record of changes across the catalog, for patrollers and administrators.</p>
				<ul class="feed">${rows || '<li><div class="feed__static">No audit entries.</div></li>'}</ul>
			</div>` };
	}
	// API docs — the live docs cannot be framed, so link out and list same-origin endpoints.
	async function viewApiDocs() {
		const root = await apiGet("/").catch(() => ({}));
		const endpoints = Object.keys(root).sort();
		const endpointCards = endpoints.map((ep) => {
			const href = "/api/" + ep + "/";
			return `<a class="linkcard" href="${esc(href)}" target="_blank" rel="noopener">
				<span class="linkcard__icon" aria-hidden="true">{ }</span>
				<span class="linkcard__body"><span class="linkcard__title"><code>GET ${esc(href)}</code> ↗</span>
				<span class="linkcard__desc">Open the live JSON response through this app's read-only proxy.</span></span></a>`;
		}).join("");
		return { title: "API documentation — Toolhub", html: `
			<div class="container page">
				<h1 class="page__title">API documentation</h1>
				<p class="page__intro">Toolhub is API-first — everything in this interface is available over HTTP. The live interactive documentation blocks embedding, so open it directly or inspect the same-origin read-only endpoints below.</p>
				<div class="linkgrid">
					${linkCard("📦", "Interactive API docs", "Open the canonical Toolhub API documentation.", "https://toolhub.wikimedia.org/api-docs")}
					${linkCard("🧭", "API root", "Browse the upstream API endpoint index.", "https://toolhub.wikimedia.org/api/")}
				</div>
				<h2 class="contribute__h2">Live proxy endpoints</h2>
				<div class="linkgrid">${endpointCards || '<p class="empty">The live endpoint index is unavailable.</p>'}</div>
			</div>` };
	}
	// Tool revision history — illustrative, from the tool's modified date.
	async function viewToolHistory(name) {
		const [t, data] = await Promise.all([
			apiGet("/tools/" + encodeURIComponent(name) + "/").then(normalizeTool).catch(() => null),
			apiGet("/tools/" + encodeURIComponent(name) + "/revisions/", { page_size: "20" }).catch(() => ({ results: [] })),
		]);
		const revs = data.results || [];
		if (!t && !revs.length) return viewNotFound();
		const title = t ? t.title : (revs[0] && revs[0].content_title) || name;
		const rows = revs.map((r, i) => `
			<li><span class="feed__ic" aria-hidden="true">🕓</span>
				<span class="feed__main">Revision by <strong${dirAttrs((r.user && r.user.username) || "system")}>${esc((r.user && r.user.username) || "system")}</strong> · ${timeTag(r.timestamp)}${r.comment ? " — <span dir=\"auto\">" + esc(r.comment) + "</span>" : ""}${i === 0 ? ' <span class="tag">current</span>' : ""}</span>
				<span class="feed__when">#${esc(String(r.id))}</span></li>`).join("");
		return { title: `History: ${title} — Toolhub`, html: `
			<div class="container page">
				<a class="back" href="#/tools/${encodeURIComponent(name)}">← Back to ${esc(title)}</a>
				<h1 class="page__title">Revision history</h1>
				<ul class="feed">${rows || '<li><div class="feed__static">No revisions recorded.</div></li>'}</ul>
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
				<p><a class="btn btn--primary" href="https://toolhub.wikimedia.org/" target="_blank" rel="noopener">Continue on toolhub.wikimedia.org <span aria-hidden="true">↗</span></a></p>
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
	function setPageInert(on) {
		$$("body > *").forEach((el) => {
			if (el.id === "qv" || el.tagName === "SCRIPT") return;
			if ("inert" in el) el.inert = on;
			if (on) el.setAttribute("aria-hidden", "true");
			else el.removeAttribute("aria-hidden");
		});
	}
	function quickViewBody(t) {
		const st = t.status || { level: "green", label: "Healthy" };
		const authors = (t.authors || []).map(esc).join(", ") || esc(t.maintainer);
		const tags = (t.keywords || []).slice(0, 6).map((k) => `<a class="tag" href="#/search?keywords__term=${encodeURIComponent(k)}"${dirAttrs(k)}>${esc(k)}</a>`).join("");
		const realBadge = (t.deprecated || t.experimental) ? `<span class="status status--${st.level}"><span class="dot dot--${st.level}"></span>${esc(st.label)}</span>` : "";
		const glance = [
			t.toolType && `<span class="glance"${dirAttrs(t.toolType)}>${esc(t.toolType)}</span>`,
			t.license && `<span class="glance"${dirAttrs(t.license)}>${esc(t.license)}</span>`,
			`<span class="glance"${dirAttrs(wikiLabel(t.forWikis))}>${esc(wikiLabel(t.forWikis))}</span>`,
			(t.uiLanguages && t.uiLanguages.length) && `<span class="glance">${esc(countLabel(t.uiLanguages.length, "language", "languages"))}</span>`,
		].filter(Boolean).join("");
		return `
			<div class="qv__head">${toolIcon(t, "lg")}
				<div class="qv__id"><h2 class="qv__title" id="qv-title"${dirAttrs(t.title)}>${esc(t.title)}</h2>
				<div class="qv__by">by <span dir="auto">${authors}</span></div></div>
			</div>
			<div class="qv__status">
				${realBadge}
				<!-- EXPERIMENTAL — health/popularity (no API data) -->
				<span class="status status--green experimental"><span class="dot dot--green"></span>Healthy</span>
				<span class="views experimental"><span aria-hidden="true">🔥</span> ${views(t.weeklyViews)}</span>
				${updatedTimeTag(t.modified, "toolpage__when")}
			</div>
			<p class="qv__desc"${dirAttrs(t.description)}>${esc(t.description) || "<em>No description provided.</em>"}</p>
			<div class="toolpage__glance">${glance}</div>
			<div class="tcard__tags qv__tags">${tags}</div>
			<div class="qv__actions">
				${t.url ? `<a class="btn btn--primary" href="${safeUrl(t.url)}" target="_blank" rel="noopener">Open tool <span aria-hidden="true">↗</span></a>` : ""}
				<a class="btn btn--outline" href="#/tools/${encodeURIComponent(t.name)}">View full page <span aria-hidden="true">→</span></a>
			</div>`;
	}
	async function openQuickView(name) {
		let t = INDEX[name];
		if (!t) {
			try { t = normalizeTool(await apiGet("/tools/" + encodeURIComponent(name) + "/")); }
			catch (e) { location.hash = "#/tools/" + encodeURIComponent(name); return; }
		}
		qvLastFocus = document.activeElement;
		$("#qv-body").innerHTML = quickViewBody(t);
		$("#qv").classList.remove("hidden");
		$("#qv").setAttribute("aria-hidden", "false");
		setPageInert(true);
		document.body.style.overflow = "hidden";
		$(".qv__x").focus();
	}
	function closeQuickView() {
		const qv = $("#qv");
		if (!qv || qv.classList.contains("hidden")) return;
		qv.classList.add("hidden");
		qv.setAttribute("aria-hidden", "true");
		setPageInert(false);
		document.body.style.overflow = "";
		if (qvLastFocus && qvLastFocus.focus) qvLastFocus.focus();
	}
	function qvTrap(e) {
		const qv = $("#qv");
		if (e.key !== "Tab" || qv.classList.contains("hidden")) return;
		const f = Array.from(qv.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'))
			.filter((el) => !el.hidden && el.offsetParent !== null);
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
			<button class="acct__btn" id="acct-btn" type="button" aria-haspopup="true" aria-expanded="false" aria-controls="acct-menu">
				${avatar(USER.name, "avatar--sm")}
				<span class="acct__name">${esc(USER.name)}</span>
				<span class="acct__caret" aria-hidden="true">▾</span>
			</button>
			<div class="acct__menu" id="acct-menu" aria-labelledby="acct-btn" hidden>
				<div class="acct__head">Signed in as <strong>${esc(USER.name)}</strong></div>
				<a href="#/my-lists"><span aria-hidden="true">📋</span> Your lists</a>
				<a href="#/favorites"><span aria-hidden="true">⭐</span> Favorites</a>
				<a href="#/add-or-remove-tools"><span aria-hidden="true">🧰</span> Add or remove tools</a>
				<a href="#/developer-settings"><span aria-hidden="true">🔧</span> Developer settings</a>
				<hr />
				<button class="acct__logout" type="button" data-logout><span aria-hidden="true">↪</span> Log out</button>
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
		if (willOpen) { const first = m.querySelector("a, button"); if (first) first.focus(); }
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
		let currentSet = false;
		$$("#nav-links a").forEach((a) => {
			const href = a.getAttribute("href");
			const matches = href === h || (h.startsWith("#/search") && href === "#/search") || (h.startsWith("#/lists") && href === "#/lists");
			const active = matches && !currentSet;
			if (active) currentSet = true;
			a.classList.toggle("is-active", active);
			if (active) a.setAttribute("aria-current", "page");
			else a.removeAttribute("aria-current");
		});
	}
	let lastPath = null;
	let navSeq = 0;
	const loadingHTML = () => '<div class="container page loading" role="status" aria-live="polite"><span class="spinner" aria-hidden="true"></span><span class="skip-label">Loading</span></div>';
	const errorHTML = (e) => '<div class="container page errorpage"><h1>Couldn\'t load live data</h1>'
		+ '<p class="prose">The Toolhub API didn\'t respond (' + esc(String((e && e.message) || e)) + ').</p>'
		+ '<a class="btn btn--primary" href="#/">Back to home</a></div>';
	async function render() {
		closeQuickView(); // any navigation dismisses the peek modal
		closeAcctMenu();  // …and the account dropdown
		const seq = ++navSeq;
		const { path } = parseHash();
		const viewEl = $("#view");
		if (path !== lastPath) {
			viewEl.setAttribute("aria-busy", "true");
			viewEl.innerHTML = loadingHTML(); // spinner only on real page change
		}
		let view;
		try { view = await dispatch(); }
		catch (e) { view = { title: "Error — Toolhub", html: errorHTML(e) }; }
		if (seq !== navSeq) return; // a newer navigation superseded this one
		viewEl.innerHTML = view.html;
		viewEl.setAttribute("aria-busy", "false");
		document.body.classList.toggle("on-home", path === "/"); // expbar blends with the hero on home
		document.title = view.title || "Toolhub";
		if (typeof view.mount === "function") view.mount();
		setActiveNav();
		if (path !== lastPath) {
			window.scrollTo({ top: 0, behavior: "auto" });
			const h1 = $("#view h1") || viewEl;
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
		if (e.target.closest("#acct-menu a, #acct-menu button")) { closeAcctMenu(); } // links route natively
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
