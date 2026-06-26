// SPDX-License-Identifier: GPL-3.0-or-later
// Shared ambient domain types for `tsc --checkJs --strict`. Declaring them
// globally (no import needed) keeps annotations consistent across modules and
// avoids duplicated @typedef blocks (which jscpd would flag as clones). Shapes
// mirror normalizeTool()/normalizeList() in lib/core/api.js.

/** A maintainer/author object as normalized from the upstream record. */
interface AuthorObj {
	name: string;
	url: string | null;
}

/** A normalized tool record — the shape every view/component consumes. */
interface Tool {
	name: string;
	title: string;
	description: string;
	url: string;
	icon: string | null;
	keywords: string[];
	maintainer: string;
	authors: string[];
	authorObjs: AuthorObj[];
	wikidata: string | null;
	subtitle: string | null;
	sponsor: string[];
	replacedBy: string | null;
	toolType: string | null;
	license: string | null;
	repository: string | null;
	apiUrl: string | null;
	technologyUsed: string[];
	audiences: string[];
	tasks: string[];
	forWikis: string[];
	uiLanguages: string[];
	userDocs: string | null;
	devDocs: string | null;
	feedback: string | null;
	bugtracker: string | null;
	translate: string | null;
	deprecated: boolean;
	experimental: boolean;
	modified: string | null;
	origin: string;
	weeklyViews: number;
	// statusOf() returns a {level,label} pair, not a bare string.
	status: { level: string; label: string };
	// Attached later by signals.js / Lane-B overlay — optional so freshly
	// normalized records and enriched ones both type-check.
	endorsement?: { count: number; lists: unknown[] };
	edited?: boolean;
	annotated?: boolean;
}

/** A normalized curated-list record. */
interface ToolList {
	id: string;
	title: string;
	description: string;
	toolCount: number;
	tools: Tool[];
	featured: boolean;
}

/** The user's saved context signals (audience/wiki/tasks) for fit ranking. */
interface UserContext {
	audiences: string[];
	wikis: string[];
	tasks: string[];
}

/** A node in the similarity / ego graph. */
interface GraphNode {
	id: string;
	title: string;
	community?: number;
}

/** An edge in the similarity / ego graph. */
interface GraphEdge {
	source: string;
	target: string;
	weight: number;
}
