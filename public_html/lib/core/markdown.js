// SPDX-License-Identifier: GPL-3.0-or-later
import { esc, safeUrl } from "./dom.js";

const LINK_ATTRS = 'target="_blank" rel="noopener nofollow"';

function decodeEscapedUrl(value) {
	return String(value == null ? "" : value)
		.replace(/&amp;/g, "&")
		.replace(/&lt;/g, "<")
		.replace(/&gt;/g, ">")
		.replace(/&quot;/g, '"')
		.replace(/&#39;/g, "'");
}

function tokenFor(tokens, html) {
	const key = `\x00MD${tokens.length}\x00`;
	tokens.push(html);
	return key;
}

function restoreTokens(value, tokens) {
	return value.replace(/\x00MD(\d+)\x00/g, (_, i) => tokens[Number(i)] || "");
}

function linkHtml(hrefText, labelHtml) {
	const href = safeUrl(decodeEscapedUrl(hrefText));
	if (!href) return "";
	return `<a href="${href}" ${LINK_ATTRS}>${labelHtml}</a>`;
}

function trimLinkedPunctuation(value) {
	let url = value;
	let trail = "";
	while (/[.,;:!?)]$/.test(url)) {
		trail = url.slice(-1) + trail;
		url = url.slice(0, -1);
	}
	return { url, trail };
}

function renderInline(value, opts) {
	opts = opts || {};
	const allowLinks = opts.allowLinks !== false;
	const tokens = [];
	let out = String(value == null ? "" : value);

	out = out.replace(/`([^`\n]+)`/g, (_, code) => tokenFor(tokens, `<code>${code}</code>`));

	if (allowLinks) {
		out = out.replace(/\[([^\]\n]+)\]\(([^)\n]+)\)/g, (match, label, href) => {
			const linked = linkHtml(href.trim(), renderInline(label, { allowLinks: false }));
			return tokenFor(tokens, linked || match);
		});
		out = out.replace(/&lt;(https?:\/\/[^\s]+?)&gt;/gi, (_, href) => {
			const linked = linkHtml(href, href);
			return tokenFor(tokens, linked || `&lt;${href}&gt;`);
		});
		out = out.replace(/\bhttps?:\/\/[^\s<]+/gi, (match) => {
			const parts = trimLinkedPunctuation(match);
			if (!parts.url) return match;
			const linked = linkHtml(parts.url, parts.url);
			return tokenFor(tokens, linked ? linked + parts.trail : match);
		});
	}

	out = out
		.replace(/\*\*([^*]+(?:\*[^*]+)*)\*\*/g, "<strong>$1</strong>")
		.replace(/__([^_]+(?:_[^_]+)*)__/g, "<strong>$1</strong>")
		.replace(/(^|[^*])\*([^*\s](?:[^*]*[^*\s])?)\*(?!\*)/g, "$1<em>$2</em>")
		.replace(/(^|[^\w_])_([^_\s](?:[^_]*[^_\s])?)_(?![\w_])/g, "$1<em>$2</em>");

	return restoreTokens(out, tokens);
}

function isBlank(line) {
	return !String(line || "").trim();
}

function isFence(line) {
	return /^ {0,3}```/.test(line);
}

function headingMatch(line) {
	return /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line);
}

function blockquoteMatch(line) {
	return /^ {0,3}&gt; ?(.*)$/.exec(line);
}

function unorderedMatch(line) {
	return /^ {0,3}[-*]\s+(.*)$/.exec(line);
}

function orderedMatch(line) {
	return /^ {0,3}\d+\.\s+(.*)$/.exec(line);
}

function isBlockStart(line) {
	return isFence(line) || headingMatch(line) || blockquoteMatch(line) || unorderedMatch(line) || orderedMatch(line);
}

function renderList(lines, start, ordered) {
	const tag = ordered ? "ol" : "ul";
	const matcher = ordered ? orderedMatch : unorderedMatch;
	const items = [];
	let i = start;
	while (i < lines.length) {
		const first = matcher(lines[i]);
		if (!first) break;
		const itemLines = [first[1]];
		i++;
		while (i < lines.length && !isBlank(lines[i]) && !matcher(lines[i]) && !isBlockStart(lines[i])) {
			itemLines.push(lines[i].trim());
			i++;
		}
		items.push(`<li>${renderInline(itemLines.join(" "))}</li>`);
	}
	return { html: `<${tag}>${items.join("")}</${tag}>`, next: i };
}

function renderBlocks(escaped) {
	const lines = escaped.split("\n");
	const out = [];
	let i = 0;

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
		while (i < lines.length && !isBlank(lines[i]) && !isBlockStart(lines[i])) {
			paragraph.push(lines[i]);
			i++;
		}
		out.push(`<p>${renderInline(paragraph.join("\n"))}</p>`);
	}

	return out.join("\n");
}

export function renderMarkdown(src) {
	if (src == null || !String(src).trim()) return "";
	const escaped = esc(src).replace(/\r\n?/g, "\n");
	return renderBlocks(escaped);
}
