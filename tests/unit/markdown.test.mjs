// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import * as markdown from "../../public_html/lib/core/markdown.js";

const { renderMarkdown } = markdown;

test("renderMarkdown returns empty string for absent or blank input", () => {
	assert.equal(renderMarkdown(null), "");
	assert.equal(renderMarkdown(undefined), "");
	assert.equal(renderMarkdown(""), "");
	assert.equal(renderMarkdown("   \n\t "), "");
});

test("headings render at the matched level, strip trailing hashes, and render inline", () => {
	assert.equal(renderMarkdown("# Hello"), "<h1>Hello</h1>");
	assert.equal(renderMarkdown("## Title ##   "), "<h2>Title</h2>");
	assert.equal(renderMarkdown("###### Title ###"), "<h6>Title</h6>");
	assert.equal(renderMarkdown("### a **b** c"), "<h3>a <strong>b</strong> c</h3>");
	// 7 hashes is past the {1,6} bound, so it is a paragraph, not a heading.
	assert.equal(renderMarkdown("####### nope"), "<p>####### nope</p>");
	// A hash with no following space is not a heading.
	assert.equal(renderMarkdown("#notheading"), "<p>#notheading</p>");
});

test("paragraphs escape HTML, join wrapped lines, and normalize CRLF", () => {
	assert.equal(renderMarkdown("Hello world"), "<p>Hello world</p>");
	assert.equal(renderMarkdown("line1\nline2"), "<p>line1\nline2</p>");
	assert.equal(renderMarkdown("a\r\nb\rc"), "<p>a\nb\nc</p>");
	assert.equal(renderMarkdown(`a < b & c > d "q" it's`), "<p>a &lt; b &amp; c &gt; d &quot;q&quot; it&#39;s</p>");
});

test("unordered lists handle both bullet markers and wrapped continuation lines", () => {
	assert.equal(renderMarkdown("- one\n- two"), "<ul><li>one</li><li>two</li></ul>");
	assert.equal(renderMarkdown("* a\n- b"), "<ul><li>a</li><li>b</li></ul>");
	assert.equal(renderMarkdown("- one\n  more\n- two"), "<ul><li>one more</li><li>two</li></ul>");
	// A blank line breaks one list into two.
	assert.equal(renderMarkdown("- a\n\n- b"), "<ul><li>a</li></ul>\n<ul><li>b</li></ul>");
	// A list followed by a paragraph.
	assert.equal(renderMarkdown("- a\n\nplain"), "<ul><li>a</li></ul>\n<p>plain</p>");
});

test("ordered lists match digits and stop at a following block start", () => {
	assert.equal(renderMarkdown("1. first\n2. second"), "<ol><li>first</li><li>second</li></ol>");
	assert.equal(renderMarkdown("12. item"), "<ol><li>item</li></ol>");
	assert.equal(renderMarkdown("1. a\n# H"), "<ol><li>a</li></ol>\n<h1>H</h1>");
});

test("fenced code blocks are literal, indentable, and tolerate a missing closing fence", () => {
	assert.equal(renderMarkdown("```\ncode <b>\nline2\n```"), "<pre><code>code &lt;b&gt;\nline2</code></pre>");
	// Up to three leading spaces and an info string are accepted; EOF closes the fence.
	assert.equal(renderMarkdown("   ```js\nx=1"), "<pre><code>x=1</code></pre>");
	assert.equal(renderMarkdown("```\na\n```\nafter"), "<pre><code>a</code></pre>\n<p>after</p>");
});

test("blockquotes recurse, allow an empty quote, and tolerate a missing space", () => {
	assert.equal(renderMarkdown("> quoted line\n> second"), "<blockquote><p>quoted line\nsecond</p></blockquote>");
	assert.equal(renderMarkdown("> - a\n> - b"), "<blockquote><ul><li>a</li><li>b</li></ul></blockquote>");
	assert.equal(renderMarkdown(">"), "<blockquote></blockquote>");
	assert.equal(renderMarkdown(">nospace"), "<blockquote><p>nospace</p></blockquote>");
});

test("inline code is protected from further markdown processing", () => {
	assert.equal(renderMarkdown("use `x = 1` now"), "<p>use <code>x = 1</code> now</p>");
	assert.equal(renderMarkdown("`**not bold**`"), "<p><code>**not bold**</code></p>");
	assert.equal(renderMarkdown("`a` and `b`"), "<p><code>a</code> and <code>b</code></p>");
});

test("bold and italic render for both asterisk and underscore forms with boundary rules", () => {
	assert.equal(renderMarkdown("**bold**"), "<p><strong>bold</strong></p>");
	assert.equal(renderMarkdown("__bold__"), "<p><strong>bold</strong></p>");
	assert.equal(renderMarkdown("a *italic* b"), "<p>a <em>italic</em> b</p>");
	assert.equal(renderMarkdown("a _italic_ b"), "<p>a <em>italic</em> b</p>");
	assert.equal(renderMarkdown("*x*"), "<p><em>x</em></p>");
	assert.equal(renderMarkdown("**b** and *i*"), "<p><strong>b</strong> and <em>i</em></p>");
	assert.equal(renderMarkdown("**a *b* c**"), "<p><strong>a <em>b</em> c</strong></p>");
	assert.equal(renderMarkdown("**a*b*c**"), "<p><strong>a<em>b</em>c</strong></p>");
	// No emphasis: a lone asterisk surrounded by spaces, underscores inside a word.
	assert.equal(renderMarkdown("a * b *"), "<p>a * b *</p>");
	assert.equal(renderMarkdown("snake_case_name"), "<p>snake_case_name</p>");
	assert.equal(renderMarkdown("****"), "<p>****</p>");
});

test("explicit links render with attributes and reject unsafe hrefs", () => {
	assert.equal(
		renderMarkdown("[label](https://example.org/p)"),
		'<p><a href="https://example.org/p" target="_blank" rel="noopener nofollow">label</a></p>'
	);
	// The label is rendered inline (without nested links).
	assert.equal(
		renderMarkdown("[a **b**](https://e.org)"),
		'<p><a href="https://e.org" target="_blank" rel="noopener nofollow">a <strong>b</strong></a></p>'
	);
	// Whitespace around the href is trimmed.
	assert.equal(
		renderMarkdown("[a]( https://e.org )"),
		'<p><a href="https://e.org" target="_blank" rel="noopener nofollow">a</a></p>'
	);
	// An unsafe scheme falls back to the raw matched text.
	assert.equal(renderMarkdown("[x](javascript:alert(1))"), "<p>[x](javascript:alert(1))</p>");
	// A URL inside a link label is NOT auto-linked (links disabled for labels).
	assert.equal(
		renderMarkdown("[see https://inner.example here](https://outer.example)"),
		'<p><a href="https://outer.example" target="_blank" rel="noopener nofollow">see https://inner.example here</a></p>'
	);
	// Inline-code token inside a label is dropped (inner pass has its own empty token table).
	assert.equal(
		renderMarkdown("[`c`](https://e.org)"),
		'<p><a href="https://e.org" target="_blank" rel="noopener nofollow"></a></p>'
	);
});

test("link hrefs decode HTML entities before re-escaping (no double escaping)", () => {
	assert.equal(
		renderMarkdown("[a](https://e.org/?x=1&y=2)"),
		'<p><a href="https://e.org/?x=1&amp;y=2" target="_blank" rel="noopener nofollow">a</a></p>'
	);
	assert.equal(
		renderMarkdown("[a](https://e.org/a<b)"),
		'<p><a href="https://e.org/a&lt;b" target="_blank" rel="noopener nofollow">a</a></p>'
	);
	assert.equal(
		renderMarkdown("[a](https://e.org/a>b)"),
		'<p><a href="https://e.org/a&gt;b" target="_blank" rel="noopener nofollow">a</a></p>'
	);
	assert.equal(
		renderMarkdown(`[a](https://e.org/a"b)`),
		'<p><a href="https://e.org/a&quot;b" target="_blank" rel="noopener nofollow">a</a></p>'
	);
	assert.equal(
		renderMarkdown("[a](https://e.org/a'b)"),
		'<p><a href="https://e.org/a&#39;b" target="_blank" rel="noopener nofollow">a</a></p>'
	);
	// All five entities at once.
	assert.equal(
		renderMarkdown(`[a](https://e.org/?x=1&y=2<z>q"w'v)`),
		'<p><a href="https://e.org/?x=1&amp;y=2&lt;z&gt;q&quot;w&#39;v" target="_blank" rel="noopener nofollow">a</a></p>'
	);
});

test("angle-bracket autolinks render only for http(s) schemes", () => {
	assert.equal(
		renderMarkdown("x <https://example.org/p> y"),
		'<p>x <a href="https://example.org/p" target="_blank" rel="noopener nofollow">https://example.org/p</a> y</p>'
	);
	assert.equal(
		renderMarkdown("x <HTTPS://Example.org/P> y"),
		'<p>x <a href="HTTPS://Example.org/P" target="_blank" rel="noopener nofollow">HTTPS://Example.org/P</a> y</p>'
	);
	// A non-http scheme is left as escaped text.
	assert.equal(renderMarkdown("x <ftp://example.org/p> y"), "<p>x &lt;ftp://example.org/p&gt; y</p>");
});

test("bare URLs are linked with trailing punctuation moved outside the anchor", () => {
	assert.equal(
		renderMarkdown("http://plain.example here"),
		'<p><a href="http://plain.example" target="_blank" rel="noopener nofollow">http://plain.example</a> here</p>'
	);
	assert.equal(
		renderMarkdown("visit https://example.org/p, ok"),
		'<p>visit <a href="https://example.org/p" target="_blank" rel="noopener nofollow">https://example.org/p</a>, ok</p>'
	);
	// Multiple trailing punctuation characters are all peeled off and reattached.
	assert.equal(
		renderMarkdown("https://example.org/a)."),
		'<p><a href="https://example.org/a" target="_blank" rel="noopener nofollow">https://example.org/a</a>).</p>'
	);
	assert.equal(
		renderMarkdown("https://e.org!!!"),
		'<p><a href="https://e.org" target="_blank" rel="noopener nofollow">https://e.org</a>!!!</p>'
	);
	assert.equal(
		renderMarkdown("a https://one.example b https://two.example"),
		'<p>a <a href="https://one.example" target="_blank" rel="noopener nofollow">https://one.example</a> b ' +
			'<a href="https://two.example" target="_blank" rel="noopener nofollow">https://two.example</a></p>'
	);
});

test("token placeholders restore correctly past index 9 (multi-digit indices)", () => {
	const md = Array.from({ length: 11 }, (_, n) => `\`c${n}\``).join(" ");
	assert.equal(
		renderMarkdown(md),
		"<p><code>c0</code> <code>c1</code> <code>c2</code> <code>c3</code> <code>c4</code> <code>c5</code> " +
			"<code>c6</code> <code>c7</code> <code>c8</code> <code>c9</code> <code>c10</code></p>"
	);
});

test("emphasis regexes honor inner-delimiter groups and word boundaries", () => {
	// Bold underscore/asterisk spans tolerate a single inner delimiter.
	assert.equal(renderMarkdown("__a_b__"), "<p><strong>a_b</strong></p>");
	assert.equal(renderMarkdown("**a*b**"), "<p><strong>a*b</strong></p>");
	assert.equal(renderMarkdown("__a__ __b__"), "<p><strong>a</strong> <strong>b</strong></p>");
	// Italic underscore needs a non-word left boundary and a non-word right boundary.
	assert.equal(renderMarkdown("(_x_)"), "<p>(<em>x</em>)</p>");
	assert.equal(renderMarkdown("_a_ _b_"), "<p><em>a</em> <em>b</em></p>");
	// Trailing word char defeats the closing underscore.
	assert.equal(renderMarkdown("_x_y"), "<p>_x_y</p>");
});

test("blank-line detection trims whitespace-only lines", () => {
	// A whitespace-only line is blank, so it splits two paragraphs.
	assert.equal(renderMarkdown("a\n   \nb"), "<p>a</p>\n<p>b</p>");
});

test("block prefixes respect the 0-3 space indent boundary", () => {
	// Fences, blockquotes, and lists accept up to three leading spaces.
	assert.equal(renderMarkdown("   ```\nx\n```"), "<pre><code>x</code></pre>");
	assert.equal(renderMarkdown("   > q"), "<blockquote><p>q</p></blockquote>");
	assert.equal(renderMarkdown("   - a"), "<ul><li>a</li></ul>");
	assert.equal(renderMarkdown("   1. a"), "<ol><li>a</li></ol>");
	// Four leading spaces falls through to a paragraph.
	assert.equal(renderMarkdown("    ```\nx"), "<p>    ```\nx</p>");
	assert.equal(renderMarkdown("    > q"), "<p>    &gt; q</p>");
	assert.equal(renderMarkdown("    - a"), "<p>    - a</p>");
	// Markers require a following space / a literal dot.
	assert.equal(renderMarkdown("-item"), "<p>-item</p>");
	assert.equal(renderMarkdown("1 item"), "<p>1 item</p>");
	// Hashes inside heading text are preserved.
	assert.equal(renderMarkdown("# a # b"), "<h1>a # b</h1>");
});

test("autolink regex matches every occurrence on a line", () => {
	assert.equal(
		renderMarkdown("<https://a.example> and <https://b.example>"),
		'<p><a href="https://a.example" target="_blank" rel="noopener nofollow">https://a.example</a> and ' +
			'<a href="https://b.example" target="_blank" rel="noopener nofollow">https://b.example</a></p>'
	);
});

test("a blockquote terminates at the first non-quote line", () => {
	assert.equal(renderMarkdown("> q\nplain"), "<blockquote><p>q</p></blockquote>\n<p>plain</p>");
});

test("regex anchors, quantifiers, and optional scheme letters are exact", () => {
	// Autolink accepts http as well as https (the `s` is optional).
	assert.equal(
		renderMarkdown("<http://x.example>"),
		'<p><a href="http://x.example" target="_blank" rel="noopener nofollow">http://x.example</a></p>'
	);
	// Bold-underscore inner run allows more than one character after an inner underscore.
	assert.equal(renderMarkdown("__a_bc__"), "<p><strong>a_bc</strong></p>");
	// Heading collapses one-or-more spaces after the hashes (no leading space leaks in).
	assert.equal(renderMarkdown("#  Title"), "<h1>Title</h1>");
	// List markers consume one-or-more spaces (no leading space leaks into the item).
	assert.equal(renderMarkdown("-  a"), "<ul><li>a</li></ul>");
	assert.equal(renderMarkdown("1.  a"), "<ol><li>a</li></ol>");
	// The ordered-list pattern is anchored at line start, so mid-line digits stay prose.
	assert.equal(renderMarkdown("see 1. point"), "<p>see 1. point</p>");
});

test("multiple distinct blocks are joined with newlines", () => {
	assert.equal(
		renderMarkdown("# T\n\npara\n\n- l1\n- l2\n\n> q"),
		"<h1>T</h1>\n<p>para</p>\n<ul><li>l1</li><li>l2</li></ul>\n<blockquote><p>q</p></blockquote>"
	);
});
