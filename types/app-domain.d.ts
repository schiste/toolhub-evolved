// SPDX-License-Identifier: GPL-3.0-or-later
// Shared ambient domain types for `tsc --checkJs --strict`. Declaring them
// globally (no import needed) keeps annotations consistent across modules and
// avoids duplicated @typedef blocks (which jscpd would flag as clones). Shapes
// mirror normalizeTool()/normalizeList() in lib/core/api.js.

/** A maintainer/author object as normalized from the upstream record. */
interface AuthorObj {
	name: string;
	url: string | null;
	wikiUsername: string | null;
	developerUsername: string | null;
}

/** A local Evolved verification badge for a per-tool author claim. */
interface AuthorVerificationBadge {
	label: string;
	className: string;
}

/** One canonical relationship between the signed-in person and a tool. */
interface AccountToolRelationship {
	requestedRelationship?: "author" | "maintainer";
	type?: "author" | "maintainer";
	verificationStatus?: string;
	isVerified?: boolean;
	status?: string;
}

/** Stable public person identity attached to account-scoped tool results. */
interface AccountPerson {
	id: string;
	slug?: string;
	displayName: string;
}

/** Public identity and relationship subset carried by tool cards. */
interface RelationshipPerson extends AccountPerson {
	identifiers?: Array<{ namespace?: string; value?: string }>;
	relationships: Array<
		AccountToolRelationship & {
			observedNames?: string[];
			evidence?: Array<{ observedName?: string }>;
		}
	>;
}

/** Cached automated discovery state for an owned Toolhub tool. */
interface ToolinfoDiscovery {
	status: string;
	method?: string;
	toolUrl?: string;
	toolinfoUrl?: string;
	checkedAt?: string;
	lastError?: string;
}

/** Indexed source feed from the official Toolhub crawler registry. */
interface ToolinfoSource {
	toolName: string;
	title?: string;
	toolUrl?: string;
	sourceUrl: string;
	sourceId?: number;
	officialId?: number | null;
	sourceKind: string;
	sourceLabel: string;
	createdBy?: string;
	createdDate?: string;
	lastSeenAt?: string;
	lastFetchedAt?: string;
	status?: string;
	valid?: boolean;
	itemCount?: number;
	lastError?: string;
	source?: string;
	syncStatus?: string;
}

/** The level/label pair statusOf() produces — a closed domain, not free strings. */
type ToolStatus =
	| { level: "green"; label: "Healthy" }
	| { level: "yellow"; label: "Experimental" }
	| { level: "grey"; label: "Archived" }
	| { level: "red"; label: "Deprecated" };

/** A normalized tool record — the shape every view/component consumes. */
interface Tool {
	name: string;
	title: string;
	titleLanguage: string | null;
	description: string;
	descriptionLanguage: string | null;
	url: string;
	icon: string | null;
	keywords: string[];
	maintainer: string;
	authors: string[];
	authorObjs: AuthorObj[];
	wikidata: string | null;
	subtitle: string | null;
	subtitleLanguage: string | null;
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
	// "active", "archived", or "" when nothing has measured whether anybody uses
	// this tool -- which is the case for everything the official catalog supplies.
	lifecycle: string;
	// When the tool came into existence, not when this catalogue heard of it:
	// the Toolhub record's own creation date, or -- for a user script or gadget
	// -- the first revision of its page on the wiki. Null wherever nothing has
	// established one, which is every wiki page no replica has answered for.
	created: string | null;
	modified: string | null;
	origin: string;
	catalogProjection?: Record<string, any> | null;
	cachedIconUrl?: string | null;
	canonicalRecord?: Record<string, any>;
	weeklyViews: number;
	// statusOf() returns one of four fixed level/label pairs (see ToolStatus).
	status: ToolStatus;
	// Attached later by signals.js / Lane-B overlay — optional so freshly
	// normalized records and enriched ones both type-check.
	endorsement?: { count: number; lists: unknown[] };
	edited?: boolean;
	annotated?: boolean;
	source?: string;
	syncStatus?: string;
	syncLabel?: string;
	lastSyncedAt?: string;
	lastError?: string;
	officialId?: number;
	officialName?: string;
	toolhubResponse?: Record<string, unknown> | null;
	toolhubStatus?: number;
	toolhubCode?: number | string;
	viewerOwned?: boolean;
	validationErrors?: unknown[];
	reviewStatus?: string;
	visibility?: string;
	editSyncStatus?: string;
	editLastError?: string;
	editValidationErrors?: unknown[];
	editReviewStatus?: string;
	editLastSyncedAt?: string;
	editToolhubResponse?: Record<string, unknown> | null;
	editToolhubStatus?: number;
	editToolhubCode?: number | string;
	editViewerOwned?: boolean;
	annotationSyncStatus?: string;
	annotationLastError?: string;
	annotationValidationErrors?: unknown[];
	annotationReviewStatus?: string;
	annotationLastSyncedAt?: string;
	annotationToolhubResponse?: Record<string, unknown> | null;
	annotationToolhubStatus?: number;
	annotationToolhubCode?: number | string;
	annotationViewerOwned?: boolean;
	authorVerified?: boolean;
	authorVerificationLabel?: string;
	authorVerificationBadges?: AuthorVerificationBadge[];
	accountRelationships?: AccountToolRelationship[];
	accountPerson?: AccountPerson;
	relationshipPeople?: RelationshipPerson[];
	personRelationships?: RelationshipPerson["relationships"];
	toolinfoDiscovery?: ToolinfoDiscovery;
	toolinfoSource?: ToolinfoSource;
	toolforgeProjects?: string[];
}

/** A normalized curated-list record. */
interface ToolList {
	id: string;
	title: string;
	description: string;
	toolCount: number;
	tools: Tool[];
	featured: boolean;
	source?: string;
	syncStatus?: string;
	syncLabel?: string;
	lastSyncedAt?: string;
	lastError?: string;
	officialId?: number;
	validationErrors?: unknown[];
	reviewStatus?: string;
}

/** The user's saved fit-ranking context — a chosen wiki and/or audience role. */
interface UserContext {
	wiki?: string;
	role?: string;
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
