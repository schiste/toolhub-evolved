// SPDX-License-Identifier: GPL-3.0-or-later
//
// Rules that only one view can produce were moved out of the global CSS bundle
// into per-route stylesheets. That trade is only safe while two things stay
// true, and neither of them fails loudly on its own:
//
//   1. Nothing outside the owning view produces the classes a route sheet
//      matches. If another view starts emitting one, that page silently loses
//      its styling -- no error, no failing render, just wrong-looking output
//      that only a human looking at the right page would catch.
//   2. A route sheet is appended after the merged app.css, so it lands after
//      templates.css too. Any equal-specificity tie a moved rule used to lose,
//      it now wins. Rules whose selector also appears in the global bundle were
//      left behind for exactly that reason, and must stay left behind.
//
// These tests hold both, plus the plumbing: the href is written in two places
// (the view's own STYLESHEET const, which dispatch awaits, and the router's
// prefetch map, which starts the request early), and a rename that updates only
// one of them costs a round-trip on that route's first paint without breaking
// anything visibly.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "vitest";

import { ROUTE_STYLES } from "../../public_html/views/router.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const VIEWS = path.join(ROOT, "public_html/views");
const STYLES = path.join(ROOT, "public_html/styles");

const read = (file) => fs.readFileSync(file, "utf8");
const sheetPath = (href) => path.join(ROOT, "public_html", href.replace(/^\//, ""));

/** CSS with comments removed, so a prose mention of a class is not a rule. */
function stripComments(css) {
	return css.replaceAll(/\/\*[\s\S]*?\*\//g, "");
}

/**
 * Selector preludes of every rule in `css`, at any nesting depth, normalized so
 * two spellings of the same selector compare equal. At-rule preludes (@media,
 * @supports) are skipped -- only what actually matches elements is returned.
 * @param {string} css
 * @returns {string[]}
 */
function selectorPreludes(css) {
	const out = [];
	let depth = 0;
	let start = 0;
	// Depth at which a @keyframes block opened, if we are inside one. Its `from`
	// and `to` are not selectors and must not be compared against real ones.
	let keyframesDepth = -1;
	const body = stripComments(css);
	for (let i = 0; i < body.length; i += 1) {
		const ch = body[i];
		if (ch === "{") {
			const prelude = body.slice(start, i).trim();
			if (prelude.startsWith("@keyframes") && keyframesDepth < 0) {
				keyframesDepth = depth;
			} else if (prelude && !prelude.startsWith("@") && keyframesDepth < 0) {
				out.push(prelude.replaceAll(/\s+/g, " "));
			}
			depth += 1;
			start = i + 1;
		} else if (ch === "}") {
			depth -= 1;
			if (depth === keyframesDepth) keyframesDepth = -1;
			start = i + 1;
		} else if (ch === ";" && depth === 0) {
			start = i + 1;
		}
	}
	return out;
}

/**
 * Each selector in a stylesheet, split on commas, paired with the classes it
 * names. A rule is only reachable from a view that can produce *all* of them --
 * `.digest-cadences__link.is-active` does not leak to a page that merely has an
 * `is-active` somewhere -- so the classes are kept grouped per selector rather
 * than pooled into one set.
 * @param {string} css
 * @returns {Array<{selector: string, classes: string[]}>}
 */
function selectorClasses(css) {
	const out = [];
	for (const prelude of selectorPreludes(css)) {
		for (const selector of prelude.split(",")) {
			const classes = [...selector.matchAll(/\.(-?[A-Za-z_][\w-]*)/g)].map((m) => m[1]);
			if (classes.length > 0) out.push({ selector: selector.trim(), classes });
		}
	}
	return out;
}

/**
 * Whether `source` can produce `cls`. A literal occurrence counts, and so does
 * a template prefix: `class="chip chip--${kind}"` never contains the string
 * "chip--active", but it produces it. Treating a prefix as claiming everything
 * beneath it is what keeps this check from green-lighting a move that breaks a
 * page whose class names are assembled at runtime.
 * @param {string} source
 * @param {string} cls
 */
function canProduce(source, cls) {
	// A whole-token match, not a substring one: "account-directory" occurs
	// inside "account-directory__notice" without the shorter class ever being
	// produced, and counting that would forbid every split whose base class
	// happens to prefix another.
	if (new RegExp(`(?<![\\w-])${cls.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\w-])`).test(source)) {
		return true;
	}
	for (const match of source.matchAll(/([A-Za-z][\w-]*?[-_]{1,2})\$\{/g)) {
		if (cls.startsWith(match[1])) return true;
	}
	return false;
}

/** Module basename -> file contents, for every view in the app. */
function viewSources() {
	const sources = new Map();
	for (const name of fs.readdirSync(VIEWS)) {
		if (name.endsWith(".js")) sources.set(name, read(path.join(VIEWS, name)));
	}
	return sources;
}

/**
 * href -> owning module, as each view declares it for itself.
 *
 * Read as a value rather than scraped out of the source, because the source is
 * not always the source: under Stryker the tests run against an instrumented
 * copy where `const STYLESHEET = "/styles/x.css"` has become a ternary and
 * `styles: [STYLESHEET]` an array literal wrapped in another, so every regex
 * that matched here found nothing and this file failed the dry run before a
 * single mutant was tried. Importing sidesteps the whole class of problem, and
 * it leaves the href covered: a mutant that empties the string now fails a
 * test instead of surviving unnoticed.
 */
async function declaredByViews() {
	const declared = new Map();
	// Every view, not just the prefetched ones -- a view that declares a sheet
	// the router forgot to prefetch is exactly what the second half of the
	// agreement test is looking for, and iterating the map would hide it.
	for (const name of viewSources().keys()) {
		// The `.js` has to sit in the static part or vite cannot enumerate the
		// candidates, so the basename goes in bare and the extension comes back.
		const module = await import(`../../public_html/views/${name.replace(/\.js$/, "")}.js`);
		if (module.STYLESHEET) declared.set(module.STYLESHEET, name);
	}
	return declared;
}

test("every stylesheet the router prefetches exists", () => {
	for (const [specifier, href] of Object.entries(ROUTE_STYLES)) {
		assert.ok(
			fs.existsSync(path.join(VIEWS, specifier.replace("./", ""))),
			`ROUTE_STYLES names ${specifier}, which is not a view module`
		);
		assert.ok(fs.existsSync(sheetPath(href)), `${specifier} prefetches ${href}, which does not exist`);
	}
});

test("the router's prefetch map and the views agree on every route stylesheet", async () => {
	const declared = await declaredByViews();
	for (const [href, module] of declared) {
		assert.equal(
			ROUTE_STYLES[`./${module}`],
			href,
			`views/${module} returns styles: ["${href}"], but the router prefetches ` +
				`${JSON.stringify(ROUTE_STYLES[`./${module}`])} for it. Without a match the sheet is ` +
				`discovered only after the module resolves, and its first paint waits a round-trip.`
		);
	}
	for (const [specifier, href] of Object.entries(ROUTE_STYLES)) {
		assert.equal(
			declared.get(href),
			specifier.replace("./", ""),
			`the router prefetches ${href} for ${specifier}, but that view does not return it in ` +
				`\`styles\`. Prefetching alone does not block paint, so the page can render unstyled.`
		);
	}
});

test("no route stylesheet claims a rule another view can match", () => {
	const sources = viewSources();
	for (const [specifier, href] of Object.entries(ROUTE_STYLES)) {
		const owner = specifier.replace("./", "");
		const rules = selectorClasses(read(sheetPath(href)));
		assert.ok(rules.length > 0, `${href} defines no class rules; is it still a route sheet?`);
		for (const [name, source] of sources) {
			if (name === owner) continue;
			const stolen = rules
				.filter((rule) => rule.classes.every((cls) => canProduce(source, cls)))
				.map((rule) => rule.selector);
			assert.deepEqual(
				stolen,
				[],
				`views/${name} can produce ${stolen.join(" / ")}, styled only in ${href}, which loads ` +
					`with ${owner}. That page renders unstyled. Move those rules back into ` +
					`public_html/styles/organisms.css.`
			);
		}
	}
});

test("no route stylesheet re-declares a selector the global bundle still carries", () => {
	// A route sheet is appended after app.css, so a duplicated selector here
	// silently outranks the global one at equal specificity. Rules in this
	// position were left in organisms.css on purpose.
	const global = new Set();
	for (const name of ["templates.css", "organisms.css", "molecules.css", "atoms.css", "base.css"]) {
		for (const prelude of selectorPreludes(read(path.join(STYLES, name)))) global.add(prelude);
	}
	for (const href of Object.values(ROUTE_STYLES)) {
		const clashing = selectorPreludes(read(sheetPath(href))).filter((prelude) => global.has(prelude));
		assert.deepEqual(
			clashing,
			[],
			`${href} repeats ${clashing.join(" / ")} from the global bundle. Because this sheet loads ` +
				`after app.css it now wins that tie, changing pages that never loaded it before.`
		);
	}
});

test("a route hint preloads the same stylesheet url the router requests", () => {
	// The shell preloads by url; the router later asks for the sheet by url too.
	// A version suffix, a trailing slash, anything at all that differs makes them
	// two cache entries: the browser fetches twice, the preload is wasted, and
	// the page still pays the round-trip it was supposed to avoid. Nothing about
	// that is visible short of reading a waterfall.
	const html = fs.readFileSync(path.join(ROOT, "public_html/index.html"), "utf8");
	const island = html.match(/<script type="application\/json" id="route-hints">([\s\S]*?)<\/script>/);
	assert.ok(island, "index.html no longer carries a route-hints table");
	for (const [routePath, hint] of Object.entries(JSON.parse(island[1]))) {
		if (!hint.css) continue;
		const specifier = `./${hint.module.replace("views/", "")}`;
		assert.equal(
			hint.css,
			ROUTE_STYLES[specifier],
			`the ${routePath} hint preloads ${hint.css}, but ${specifier} loads ` +
				`${JSON.stringify(ROUTE_STYLES[specifier])}. Two urls, two fetches, no head start.`
		);
	}
});

/** Specificity of a single selector, as (ids, classes, elements). */
function specificity(selector) {
	const ids = selector.match(/#[\w-]+/g) || [];
	const classes = [
		...(selector.match(/\.[-\w]+/g) || []),
		...(selector.match(/\[[^\]]+\]/g) || []),
		...(selector.match(/:(?!:)(?!where\b)[\w-]+/g) || [])
	];
	const elements = selector.match(/(?:^|[\s>+~(,])([a-z][a-z\d]*)\b/g) || [];
	return `${ids.length}-${classes.length}-${elements.length}`;
}

/** Rules of a stylesheet, one entry per comma-separated selector. */
function declaredRules(css) {
	const out = [];
	const body = stripComments(css);
	for (const match of body.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
		const prelude = match[1].trim().replaceAll(/\s+/g, " ");
		if (!prelude || prelude.startsWith("@") || prelude === "from" || prelude === "to") continue;
		const properties = new Set([...match[2].matchAll(/(?:^|;)\s*([-\w]+)\s*:/g)].map((p) => p[1]));
		for (const selector of prelude.split(",")) out.push({ selector: selector.trim(), properties });
	}
	return out;
}

/**
 * Classes of a combinator-free selector, or null for one that has a combinator.
 * Whether `.a .b` and `.c > .b` can land on the same element depends on how the
 * page nests, which this file cannot know; guessing would either miss real
 * reversals or invent them. So the check covers the case it can decide -- a
 * single compound, matching on its own classes alone -- which is where the
 * reversal this test was written for lived.
 */
function targetClasses(selector) {
	const trimmed = selector.trim();
	if (/[\s>+~]/.test(trimmed)) return null;
	return new Set([...trimmed.matchAll(/\.(-?[A-Za-z_][\w-]*)/g)].map((m) => m[1]));
}

/** Class attributes the owning view actually emits, as sets. */
function emittedClassSets(source) {
	const sets = [];
	for (const match of source.matchAll(/class="([^"]*)"/g)) {
		const names = match[1]
			.replaceAll(/\$\{[^}]*\}/g, " ")
			.split(/\s+/)
			.filter((name) => /^-?[A-Za-z_][\w-]*$/.test(name));
		if (names.length > 0) sets.push(new Set(names));
	}
	return sets;
}

// Two rules of equal specificity are decided by source order alone. templates.css
// is the last layer of the merged bundle, so before the split it outranked every
// organisms.css rule it tied with -- and a route sheet, loading after the whole
// bundle, reverses exactly those ties. That is not a visible break: the page
// still renders, with a rule that had been dead for as long as it existed.
// The one pair below predates the split and is therefore not a change.
const TIES_THAT_PREDATE_THE_SPLIT = new Set(["/styles/styleguide.css .sg-loading-demo vs .loading"]);

test("no route stylesheet reverses a tie templates.css used to win", () => {
	const templates = declaredRules(read(path.join(STYLES, "templates.css")));
	for (const [specifier, href] of Object.entries(ROUTE_STYLES)) {
		const emitted = emittedClassSets(read(path.join(VIEWS, specifier.replace("./", ""))));
		for (const rule of declaredRules(read(sheetPath(href)))) {
			const mine = targetClasses(rule.selector);
			if (!mine || mine.size === 0) continue;
			for (const other of templates) {
				const theirs = targetClasses(other.selector);
				if (!theirs || theirs.size === 0 || specificity(other.selector) !== specificity(rule.selector)) {
					continue;
				}
				const shared = [...rule.properties].filter((p) => other.properties.has(p));
				if (shared.length === 0) continue;
				const together = emitted.some(
					(names) => [...mine].every((c) => names.has(c)) && [...theirs].every((c) => names.has(c))
				);
				if (!together) continue;
				const pair = `${href} ${rule.selector} vs ${other.selector}`;
				assert.ok(
					TIES_THAT_PREDATE_THE_SPLIT.has(pair),
					`${href} declares ${rule.selector}, which ties ${other.selector} in templates.css on ` +
						`${shared.join(", ")}. Both land on the same element, and this sheet loads last, so ` +
						`${rule.selector} now wins where templates.css used to. Leave that rule in ` +
						`public_html/styles/organisms.css.`
				);
			}
		}
	}
});
