// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { avatar, AVATAR_COLORS, commonsThumb, toolIcon } from "../../public_html/lib/atoms/avatar.js";

// Frozen color list (hardcoded, not derived from source) — kills every color string literal.
const COLORS = [
	"var(--wmf-blue-aaa)",
	"var(--wmf-green-aaa)",
	"var(--color-warning-text)",
	"var(--wmf-red-aaa)",
	"var(--wmf-purple)",
	"var(--color-text-muted)",
	"var(--color-progressive)",
	"var(--color-success)",
	"var(--color-favorite)",
	"var(--color-progressive-hover)"
];

test("AVATAR_COLORS is the exact ordered palette", () => {
	assert.deepEqual(AVATAR_COLORS, COLORS);
});

// One input per hash-residue 0..9, so each palette index is selected exactly once.
// (Verified via hash(s) % AVATAR_COLORS.length.)
const RESIDUE_INPUT = ["k5", "k6", "k7", "k8", "k9", "k0", "k1", "k2", "k3", "k4"];

test("avatar() selects the palette color by hash(title) % length and uppercases first char", () => {
	for (let i = 0; i < 10; i++) {
		const s = RESIDUE_INPUT[i];
		assert.equal(avatar(s), `<span class="avatar " style="background:${COLORS[i]}" aria-hidden="true">K</span>`);
	}
});

test("avatar() appends the cls when provided", () => {
	assert.equal(
		avatar("Alpha", "x"),
		`<span class="avatar x" style="background:${COLORS[6]}" aria-hidden="true">A</span>`
	);
});

test("avatar() falls back to '?' for empty title", () => {
	assert.equal(avatar(""), `<span class="avatar " style="background:${COLORS[3]}" aria-hidden="true">?</span>`);
});

test("avatar() falls back to '?' for null title", () => {
	assert.equal(avatar(null), `<span class="avatar " style="background:${COLORS[3]}" aria-hidden="true">?</span>`);
});

test("avatar() trims leading whitespace before taking first char", () => {
	assert.equal(
		avatar("  hello"),
		`<span class="avatar " style="background:${COLORS[6]}" aria-hidden="true">H</span>`
	);
});

test("avatar() escapes the rendered character", () => {
	assert.match(avatar("<script>"), /aria-hidden="true">&lt;<\/span>$/);
	assert.match(avatar("&co"), /aria-hidden="true">&amp;<\/span>$/);
});

test("avatar() empty title and null title produce identical markup (both '?')", () => {
	assert.equal(avatar(""), avatar(null));
	assert.equal(avatar(undefined), avatar("?"));
});

// ---- commonsThumb -------------------------------------------------------------
test("commonsThumb() builds a FilePath thumbnail URL from a File: page", () => {
	assert.equal(
		commonsThumb("https://commons.wikimedia.org/wiki/File:Foo bar.svg", 96),
		"https://commons.wikimedia.org/wiki/Special:FilePath/Foo%20bar.svg?width=96"
	);
});

test("commonsThumb() matches the %3a-encoded colon variant", () => {
	assert.equal(
		commonsThumb("https://x/File%3aAbc.png", 50),
		"https://commons.wikimedia.org/wiki/Special:FilePath/Abc.png?width=50"
	);
});

test("commonsThumb() keeps raw name when decodeURIComponent throws", () => {
	assert.equal(
		commonsThumb("File:%E0%A4.svg", 10),
		"https://commons.wikimedia.org/wiki/Special:FilePath/%25E0%25A4.svg?width=10"
	);
});

test("commonsThumb() returns null when there is no File: segment", () => {
	assert.equal(commonsThumb("https://example.org/x", 96), null);
	assert.equal(commonsThumb(null, 48), null);
	assert.equal(commonsThumb("", 48), null);
});

// ---- toolIcon -----------------------------------------------------------------
test("toolIcon() renders a direct upload.wikimedia.org image at 48px", () => {
	assert.equal(
		toolIcon({ icon: "https://upload.wikimedia.org/a/b.png", title: "T" }),
		'<img class="avatar avatar--img" src="https://upload.wikimedia.org/a/b.png" alt="" width="48" height="48" loading="lazy" />'
	);
});

test("toolIcon() renders a direct image detected by URL pathname extension", () => {
	assert.equal(
		toolIcon({ icon: "https://x.org/pic.PNG", title: "T" }),
		'<img class="avatar avatar--img" src="https://x.org/pic.PNG" alt="" width="48" height="48" loading="lazy" />'
	);
});

test("toolIcon() renders a direct Special:FilePath image", () => {
	assert.equal(
		toolIcon({ icon: "https://commons.wikimedia.org/wiki/Special:FilePath/Foo.svg", title: "T" }),
		'<img class="avatar avatar--img" src="https://commons.wikimedia.org/wiki/Special:FilePath/Foo.svg" alt="" width="48" height="48" loading="lazy" />'
	);
});

test("toolIcon() detects image via the catch-path regex when new URL throws", () => {
	assert.equal(
		toolIcon({ icon: "https://exa mple.org/a.png", title: "T" }),
		'<img class="avatar avatar--img" src="https://exa mple.org/a.png" alt="" width="48" height="48" loading="lazy" />'
	);
});

test("toolIcon() turns a Commons File: page into a thumbnail (lg => 72px, width*2=144)", () => {
	assert.equal(
		toolIcon({ icon: "https://commons.wikimedia.org/wiki/File:Foo.svg", title: "T" }, "lg"),
		'<img class="avatar avatar--lg avatar--img" src="https://commons.wikimedia.org/wiki/Special:FilePath/Foo.svg?width=144" alt="" width="72" height="72" loading="lazy" />'
	);
});

test("toolIcon() falls back to a lg letter avatar when there is no usable image", () => {
	assert.equal(
		toolIcon({ icon: null, title: "Zeta" }, "lg"),
		'<span class="avatar avatar--lg" style="background:var(--wmf-purple)" aria-hidden="true">Z</span>'
	);
});

test("toolIcon() falls back to a default (sm) letter avatar for a non-URL icon", () => {
	assert.equal(
		toolIcon({ icon: "not a url", title: "Zeta" }),
		'<span class="avatar " style="background:var(--wmf-purple)" aria-hidden="true">Z</span>'
	);
});

test("toolIcon() falls back to avatar for an http URL without an image extension", () => {
	assert.equal(
		toolIcon({ icon: "https://x.org/a", title: "T" }),
		'<span class="avatar " style="background:var(--wmf-purple)" aria-hidden="true">T</span>'
	);
});

test("toolIcon() trims surrounding whitespace before the http check", () => {
	// Without .trim() the leading spaces would fail the ^https? test => avatar.
	assert.equal(
		toolIcon({ icon: "  https://upload.wikimedia.org/a.png  ", title: "T" }),
		'<img class="avatar avatar--img" src="https://upload.wikimedia.org/a.png" alt="" width="48" height="48" loading="lazy" />'
	);
});

test("toolIcon() non-http file: page falls through to a Commons thumbnail (not direct)", () => {
	// isDirectImageUrl must return false here; the http guard short-circuits so the
	// commonsThumb() fallback runs and yields a usable image.
	assert.equal(
		toolIcon({ icon: "file:Foo.png", title: "T" }),
		'<img class="avatar avatar--img" src="https://commons.wikimedia.org/wiki/Special:FilePath/Foo.png?width=96" alt="" width="48" height="48" loading="lazy" />'
	);
});

test("toolIcon() ^-anchored http test: 'http' mid-string does not count as direct", () => {
	// 'x-http://…' contains 'http' but is not http-prefixed; the ^https? guard must
	// short-circuit to false so the upload.wikimedia.org check is never reached and
	// the Commons-thumb fallback renders instead. (Avoids new URL() parsing quirks.)
	assert.equal(
		toolIcon({ icon: "x-http://upload.wikimedia.org/File:Pic.png", title: "T" }),
		'<img class="avatar avatar--img" src="https://commons.wikimedia.org/wiki/Special:FilePath/Pic.png?width=96" alt="" width="48" height="48" loading="lazy" />'
	);
});

test("toolIcon() accepts a plain http:// (not https) direct image", () => {
	assert.equal(
		toolIcon({ icon: "http://upload.wikimedia.org/a.png", title: "T" }),
		'<img class="avatar avatar--img" src="http://upload.wikimedia.org/a.png" alt="" width="48" height="48" loading="lazy" />'
	);
});

test("toolIcon() special:filepath without an extension is still a direct image", () => {
	// Exercises the `||` between special:filepath and upload.wikimedia.org and the
	// early `return true` (no commonsThumb fallback would match this URL).
	assert.equal(
		toolIcon({ icon: "https://commons.wikimedia.org/wiki/Special:FilePath/SomeFile", title: "T" }),
		'<img class="avatar avatar--img" src="https://commons.wikimedia.org/wiki/Special:FilePath/SomeFile" alt="" width="48" height="48" loading="lazy" />'
	);
});

test("toolIcon() extension must be anchored at end of pathname (try path)", () => {
	// `.png` not at the end => not an image => avatar.
	assert.equal(
		toolIcon({ icon: "https://x.org/a.png/raw", title: "T" }),
		'<span class="avatar " style="background:var(--wmf-purple)" aria-hidden="true">T</span>'
	);
});

test("toolIcon() matches a .jpg via the optional 'e' in jpe?g (try path)", () => {
	assert.equal(
		toolIcon({ icon: "https://x.org/a.jpg", title: "T" }),
		'<img class="avatar avatar--img" src="https://x.org/a.jpg" alt="" width="48" height="48" loading="lazy" />'
	);
});

test("toolIcon() matches a .jpg via the catch-path regex when new URL throws", () => {
	assert.equal(
		toolIcon({ icon: "https://exa mple.org/a.jpg", title: "T" }),
		'<img class="avatar avatar--img" src="https://exa mple.org/a.jpg" alt="" width="48" height="48" loading="lazy" />'
	);
});

test("toolIcon() catch-path also requires the extension anchored at end", () => {
	assert.equal(
		toolIcon({ icon: "https://exa mple.org/a.png/raw", title: "T" }),
		'<span class="avatar " style="background:var(--wmf-purple)" aria-hidden="true">T</span>'
	);
});

test("commonsThumb() requires the captured name to run to end of string (rejects embedded newline)", () => {
	assert.equal(commonsThumb("https://commons.wikimedia.org/wiki/File:Foo\nBar.svg", 96), null);
});

test("commonsThumb() decodes percent-encoding in the file name", () => {
	// Without decode, '%20' would be re-encoded to '%2520'.
	assert.equal(
		commonsThumb("https://commons.wikimedia.org/wiki/File:Foo%20bar.svg", 96),
		"https://commons.wikimedia.org/wiki/Special:FilePath/Foo%20bar.svg?width=96"
	);
});
