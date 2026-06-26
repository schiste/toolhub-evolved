// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import * as dom from "../../public_html/lib/core/dom.js";

test("$ / $$ / $input query the document by default and a root when given", () => {
	document.body.innerHTML =
		'<span class="needle" id="outer">O</span>' +
		'<div id="host"><span class="needle" id="inner">I</span><input id="inp" class="f" value="v"/></div>';
	const host = document.querySelector("#host");

	// Default root is `document`: first match in document order.
	assert.equal(dom.$(".needle").id, "outer");
	// Explicit root scopes the query.
	assert.equal(dom.$(".needle", host).id, "inner");

	assert.equal(dom.$$(".needle").length, 2);
	assert.equal(dom.$$(".needle", host).length, 1);
	assert.equal(dom.$$(".needle", host)[0].id, "inner");

	assert.equal(dom.$input(".f").value, "v");
	assert.equal(dom.$input(".f", host).value, "v");
	assert.equal(dom.$("#missing"), null);
});

test("hash is the exact deterministic 31-multiplier rolling hash", () => {
	assert.equal(dom.hash(""), 0);
	assert.equal(dom.hash("A"), 65);
	assert.equal(dom.hash("ab"), 3105);
	assert.equal(dom.hash("abc"), 96354);
});

test("esc coerces non-strings and escapes all five entities", () => {
	assert.equal(dom.esc(0), "0");
	assert.equal(dom.esc(false), "false");
	assert.equal(dom.esc(undefined), "");
	assert.equal(dom.esc(null), "");
	assert.equal(dom.esc(`a&b<c>d"e'f`), "a&amp;b&lt;c&gt;d&quot;e&#39;f");
});

test("normalizeVcsUrl trims then rewrites git+/scp/ssh and strips trailing .git", () => {
	assert.equal(dom.normalizeVcsUrl("  git+https://github.com/e/r.git  "), "https://github.com/e/r");
	assert.equal(dom.normalizeVcsUrl("GIT+https://github.com/e/r"), "https://github.com/e/r");
	// "git+" must be ANCHORED at the start: a mid-string "git+" leaves the value
	// untouched (the trailing .git is preserved because no rewrite happened).
	assert.equal(dom.normalizeVcsUrl("foogit+https://x.example/r.git"), "foogit+https://x.example/r.git");
	assert.equal(dom.normalizeVcsUrl("git@gitlab.example:group/repo.git"), "https://gitlab.example/group/repo");
	// multiple leading slashes in the path are all stripped (\/+, not a single \/).
	assert.equal(dom.normalizeVcsUrl("git@gitlab.example://lead/repo.git"), "https://gitlab.example/lead/repo");
	assert.equal(dom.normalizeVcsUrl("ssh://git@host.example/path/repo.git"), "https://host.example/path/repo");
	assert.equal(dom.normalizeVcsUrl("ssh://git@host.example///deep/repo.git"), "https://host.example/deep/repo");
	// .git stripped only before # ? or end — not mid-path.
	assert.equal(dom.normalizeVcsUrl("git+https://x.example/r.git#frag"), "https://x.example/r#frag");
	assert.equal(dom.normalizeVcsUrl("git+https://x.example/r.git?q=1"), "https://x.example/r?q=1");
	assert.equal(dom.normalizeVcsUrl("git+https://x.example/r.git/sub"), "https://x.example/r.git/sub");
	// No git/ssh marker => returned verbatim (unchanged), including a .git suffix.
	assert.equal(dom.normalizeVcsUrl("https://x.example/r.git"), "https://x.example/r.git");
});

test("safeUrl only allows http(s) and escapes the result", () => {
	assert.equal(dom.safeUrl("http://x.example"), "http://x.example");
	assert.equal(dom.safeUrl("HTTPS://X.example"), "HTTPS://X.example");
	assert.equal(dom.safeUrl("https://x.example/?a=<b>"), "https://x.example/?a=&lt;b&gt;");
	assert.equal(dom.safeUrl("ftp://x.example"), "");
	assert.equal(dom.safeUrl("htp://x.example"), "");
	// the http(s) scheme must be ANCHORED at the start.
	assert.equal(dom.safeUrl("xhttp://y.example"), "");
	assert.equal(dom.safeUrl("  https://x.example  "), "https://x.example");
	assert.equal(dom.safeUrl(undefined), "");
	assert.equal(dom.safeUrl(null), "");
});

test("dirAttrs emits dir=auto only for truthy values", () => {
	assert.equal(dom.dirAttrs("text"), ' dir="auto"');
	assert.equal(dom.dirAttrs(1), ' dir="auto"');
	assert.equal(dom.dirAttrs(""), "");
	assert.equal(dom.dirAttrs(0), "");
	assert.equal(dom.dirAttrs(null), "");
});
