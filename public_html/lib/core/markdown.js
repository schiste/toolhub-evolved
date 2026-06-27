// SPDX-License-Identifier: GPL-3.0-or-later
import { esc, safeUrl } from "./dom.js";

const LINK_ATTRS = 'target="_blank" rel="noopener nofollow"';

/** @param {unknown} value */
function decodeEscapedUrl(value) {
	// Stryker disable next-line all — only ever called with non-null string hrefs captured by the link regex; the `?? ""` nullish branch is unreachable.
	return String(value ?? "")
		.replaceAll("&amp;", "&")
		.replaceAll("&lt;", "<")
		.replaceAll("&gt;", ">")
		.replaceAll("&quot;", '"')
		.replaceAll("&#39;", "'");
}

/**
 * @param {string[]} tokens
 * @param {string} html
 */
function tokenFor(tokens, html) {
	const key = `\uE000MD${tokens.length}\uE000`;
	tokens.push(html);
	return key;
}

/**
 * @param {string} value
 * @param {string[]} tokens
 */
function restoreTokens(value, tokens) {
	return value.replaceAll(/\uE000MD(\d+)\uE000/g, (_, i) => tokens[Number(i)] || "");
}

/**
 * @param {string} hrefText
 * @param {string} labelHtml
 */
function linkHtml(hrefText, labelHtml) {
	const href = safeUrl(decodeEscapedUrl(hrefText));
	if (!href) return "";
	return `<a href="${href}" ${LINK_ATTRS}>${labelHtml}</a>`;
}

/** @param {string} value */
function trimLinkedPunctuation(value) {
	let url = value;
	let trail = "";
	while (/[!),.:;?]$/.test(url)) {
		trail = url.slice(-1) + trail;
		url = url.slice(0, -1);
	}
	return { url, trail };
}

/**
 * @param {string | null | undefined} value
 * @param {{ allowLinks?: boolean }} [opts]
 */
function renderInline(value, opts = {}) {
	const allowLinks = opts.allowLinks !== false;
	/** @type {string[]} */
	// Stryker disable next-line ArrayDeclaration — a seeded element is never indexed (token keys derive from the live array length), so it is unobservable.
	const tokens = [];
	// Stryker disable next-line all — renderInline only receives joined strings, so the `?? ""` nullish branch is unreachable.
	let out = String(value ?? "");

	out = out.replaceAll(/`([^\n`]+)`/g, (_, code) => tokenFor(tokens, `<code>${code}</code>`));

	if (allowLinks) {
		out = out.replaceAll(/\[([^\n\]]+)]\(([^\n)]+)\)/g, (match, label, href) => {
			// Stryker disable next-line MethodExpression — safeUrl() trims internally, so this .trim() is redundant and removing it is unobservable.
			const linked = linkHtml(href.trim(), renderInline(label, { allowLinks: false }));
			return tokenFor(tokens, linked || match);
		});
		out = out.replaceAll(/&lt;(https?:\/\/\S+?)&gt;/gi, (_, href) => {
			const linked = linkHtml(href, href);
			// Stryker disable next-line StringLiteral — the regex guarantees an http(s) URL, so linkHtml never returns empty and this fallback is dead.
			return tokenFor(tokens, linked || `&lt;${href}&gt;`);
		});
		out = out.replaceAll(/\bhttps?:\/\/[^\s<]+/gi, (match) => {
			const parts = trimLinkedPunctuation(match);
			// Stryker disable next-line ConditionalExpression — a matched bare URL always starts with http(s) and cannot trim to empty, so this guard never fires.
			if (!parts.url) return match;
			const linked = linkHtml(parts.url, parts.url);
			return tokenFor(tokens, linked ? linked + parts.trail : match);
		});
	}

	out = out
		.replaceAll(/\*\*([^*]+(?:\*[^*]+)*)\*\*/g, "<strong>$1</strong>")
		.replaceAll(/__([^_]+(?:_[^_]+)*)__/g, "<strong>$1</strong>")
		.replaceAll(/(^|[^*])\*([^\s*](?:[^*]*[^\s*])?)\*(?!\*)/g, "$1<em>$2</em>")
		.replaceAll(/(^|\W)_([^\s_](?:[^_]*[^\s_])?)_(?!\w)/g, "$1<em>$2</em>");

	return restoreTokens(out, tokens);
}

/** @param {string} line */
function isBlank(line) {
	return !String(line || "").trim();
}

/** @param {string} line */
function isFence(line) {
	return /^ {0,3}```/.test(line);
}

/** @param {string} line */
function headingMatch(line) {
	return /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line);
}

/** @param {string} line */
function blockquoteMatch(line) {
	// Stryker disable next-line Regex — the trailing `$` is redundant: `.*` is greedy to end-of-line (lines never contain newlines), so dropping `$` is unobservable.
	return /^ {0,3}&gt; ?(.*)$/.exec(line);
}

/** @param {string} line */
function unorderedMatch(line) {
	// Stryker disable next-line Regex — the trailing `$` is redundant with the greedy `.*` (single-line input), so dropping it is unobservable.
	return /^ {0,3}[*-]\s+(.*)$/.exec(line);
}

/** @param {string} line */
function orderedMatch(line) {
	// Stryker disable next-line Regex — the trailing `$` is redundant with the greedy `.*` (single-line input), so dropping it is unobservable.
	return /^ {0,3}\d+\.\s+(.*)$/.exec(line);
}

/** @param {string} line */
function isBlockStart(line) {
	return isFence(line) || headingMatch(line) || blockquoteMatch(line) || unorderedMatch(line) || orderedMatch(line);
}

/**
 * @param {string[]} lines
 * @param {number} start
 * @param {boolean} ordered
 */
function renderList(lines, start, ordered) {
	const tag = ordered ? "ol" : "ul";
	const matcher = ordered ? orderedMatch : unorderedMatch;
	/** @type {string[]} */
	const items = [];
	let i = start;
	// Stryker disable next-line EqualityOperator — at EOF lines[length] is undefined, which matcher() rejects (break), so the `<=` off-by-one is unobservable.
	while (i < lines.length) {
		const first = matcher(lines[i]);
		if (!first) break;
		const itemLines = [first[1]];
		i++;
		// Stryker disable next-line ConditionalExpression,EqualityOperator — at EOF lines[length] is undefined and isBlank(undefined) is true, so the `i < length` bound (vs `<=`/true) is unobservable.
		while (i < lines.length && !isBlank(lines[i]) && !matcher(lines[i]) && !isBlockStart(lines[i])) {
			itemLines.push(lines[i].trim());
			i++;
		}
		items.push(`<li>${renderInline(itemLines.join(" "))}</li>`);
	}
	return { html: `<${tag}>${items.join("")}</${tag}>`, next: i };
}

/**
 * @param {string} escaped
 * @returns {string}
 */
function renderBlocks(escaped) {
	const lines = escaped.split("\n");
	/** @type {string[]} */
	const out = [];
	let i = 0;

	// Stryker disable next-line EqualityOperator — at EOF lines[length] is undefined and isBlank(undefined) is true, so the extra `<=` iteration just skips and exits: unobservable.
	while (i < lines.length) {
		if (isBlank(lines[i])) {
			i++;
			continue;
		}

		if (isFence(lines[i])) {
			const code = [];
			i++;
			while (i < lines.length && !isFence(lines[i])) {
				code.push(lines[i]);
				i++;
			}
			// Stryker disable next-line ConditionalExpression,EqualityOperator — when the fence is unterminated i is already at EOF, so the `<=`/true variants only no-op past end: unobservable.
			if (i < lines.length) i++;
			out.push(`<pre><code>${code.join("\n")}</code></pre>`);
			continue;
		}

		const heading = headingMatch(lines[i]);
		if (heading) {
			const level = heading[1].length;
			out.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
			i++;
			continue;
		}

		if (blockquoteMatch(lines[i])) {
			const quote = [];
			// Stryker disable next-line EqualityOperator — at EOF blockquoteMatch(undefined) is null (break), so the `<=` off-by-one is unobservable.
			while (i < lines.length) {
				const quoted = blockquoteMatch(lines[i]);
				if (!quoted) break;
				quote.push(quoted[1]);
				i++;
			}
			const inner = renderBlocks(quote.join("\n"));
			out.push(`<blockquote>${inner}</blockquote>`);
			continue;
		}

		if (unorderedMatch(lines[i])) {
			const rendered = renderList(lines, i, false);
			out.push(rendered.html);
			i = rendered.next;
			continue;
		}

		if (orderedMatch(lines[i])) {
			const rendered = renderList(lines, i, true);
			out.push(rendered.html);
			i = rendered.next;
			continue;
		}

		const paragraph = [];
		// Stryker disable next-line ConditionalExpression,EqualityOperator — at EOF lines[length] is undefined and isBlank(undefined) is true, so the `i < length` bound (vs `<=`/true) is unobservable.
		while (i < lines.length && !isBlank(lines[i]) && !isBlockStart(lines[i])) {
			paragraph.push(lines[i]);
			i++;
		}
		out.push(`<p>${renderInline(paragraph.join("\n"))}</p>`);
	}

	return out.join("\n");
}

/** @param {unknown} src */
export function renderMarkdown(src) {
	// Stryker disable next-line all — for every guard-caught input (null/undefined/blank) the downstream esc()+renderBlocks() pipeline already yields "", so the early return is a pure optimization and its mutants are equivalent.
	if (src === null || src === undefined || !String(src).trim()) return "";
	const escaped = esc(src).replaceAll(/\r\n?/g, "\n");
	return renderBlocks(escaped);
}
