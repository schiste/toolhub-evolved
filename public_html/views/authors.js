// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, safeUrl } from "../lib/core/dom.js";
import { authorProfileUrl, toolsByAuthor } from "../lib/core/author-index.js";
import { countLabel } from "../lib/core/i18n.js";
import { icon } from "../lib/atoms/icon.js";
import { grid } from "../lib/organisms/grid.js";
import { toolCard } from "../lib/organisms/tool-card.js";

export async function viewAuthor(name) {
	const entry = await toolsByAuthor(name);
	const authorName = entry.name || name;
	const tools = entry.tools || [];
	const profileUrl = safeUrl(authorProfileUrl(entry.profile));
	const profileLink = profileUrl
		? `<a class="author-page__profile" href="${profileUrl}" target="_blank" rel="noopener nofollow">Author profile ${icon("external")}</a>`
		: "";
	const body =
		tools.length > 0
			? grid("grid-tools", tools, (t) => toolCard(t))
			: '<p class="empty">No tools found for this author.</p>';
	const html = `
	<div class="container page author-page">
		<a class="back" href="/search">← Back to tools</a>
		<div class="section-head author-page__head">
			<div>
				<h1 class="page__title"${dirAttrs(authorName)}>${esc(authorName)}</h1>
				<p class="page__intro">${esc(countLabel(tools.length, "tool", "tools"))}</p>
			</div>
			${profileLink}
		</div>
		${body}
	</div>`;
	return { title: `${authorName} — Toolhub`, html };
}
