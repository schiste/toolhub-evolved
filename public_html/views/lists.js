// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $input, dirAttrs, esc, textAttrs } from "../lib/core/dom.js";
import { countLabel, t } from "../lib/core/i18n.js";
import {
	ApiError,
	apiGet,
	backendErrorMessage,
	clearApiCache,
	getToolsByName,
	normalizeList,
	normalizeTool
} from "../lib/core/api.js";
import { attachEndorsements, rankFitsFirst } from "../lib/core/signals.js";
import { signedIn } from "../lib/core/session.js";
import { lifecycleMeta, officialWrite, officialWriteAvailable } from "../lib/core/serversync.js";
import { listHref, navigateTo } from "../lib/core/routing.js";
import {
	demoListDelete,
	demoListGet,
	demoListNew,
	demoListSave,
	demoLists,
	favNames,
	isDemoListId,
	SYNC_STATUS
} from "../lib/core/store.js";
import { button, iconButton } from "../lib/atoms/button.js";
import { fArea, fInput, fieldValue } from "../lib/atoms/form-fields.js";
import { icon } from "../lib/atoms/icon.js";
import { mountChangeReview, shouldProceedWithFieldChanges } from "../lib/molecules/change-review.js";
import { fieldProvenance, syncBadge, syncState, syncStatusPanel } from "../lib/molecules/sync-status.js";
import { grid } from "../lib/organisms/grid.js";
import { listCard, listCardData } from "../lib/organisms/list-card.js";
import { toolCard } from "../lib/organisms/tool-card.js";
import { viewNotFound } from "./static.js";

/** @param {{ id: string, title: string, description: string, tools: string[] }} list */
function officialListPayload(list) {
	return {
		clientId: list.id,
		title: list.title,
		description: list.description || null,
		published: true,
		tools: list.tools,
		comment: "Published from Toolhub Evolved"
	};
}

/**
 * @param {{ title?: string, description?: string, tools?: string[] }} source
 * @param {{ title: string, description: string, tools: string[] }} work
 * @returns {import("../lib/molecules/change-review.js").ChangeDescriptor[]}
 */
function listChangeDescriptors(source, work) {
	return /** @type {import("../lib/molecules/change-review.js").ChangeDescriptor[]} */ ([
		{
			key: "title",
			label: t("lists.title", "Title"),
			before: source.title,
			after: work.title
		},
		{
			key: "description",
			label: t("lists.description", "Description"),
			before: source.description,
			after: work.description
		},
		{
			key: "tools",
			label: t("lists.tools", "Tools"),
			before: source.tools || [],
			after: work.tools,
			type: "ordered-list"
		}
	]);
}

function toolhubSignInRequiredMessage() {
	return t("lists.signInRequired", "Toolhub sign-in is required before saving lists.");
}

/** @param {{ id: string, title: string, description: string, tools: string[] }} work */
function setupListRetry(work) {
	const retry = $("[data-le-retry]");
	if (!retry) return;
	retry.addEventListener("click", async () => {
		const out = /** @type {HTMLElement} */ ($("[data-official-result]"));
		out.className = "at__result";
		out.textContent = t("lists.publishingToToolhub", "Publishing to official Toolhub…");
		try {
			const res = await officialWrite("POST", `/v1/write/lists/${encodeURIComponent(work.id)}/retry/`);
			if (res?.result === SYNC_STATUS.localFallback) {
				const local = res?.local && typeof res.local === "object" ? res.local : null;
				demoListSave(
					{
						id: String(local?.id || work.id),
						title: local?.title || work.title,
						description: local?.description || work.description,
						tools: Array.isArray(local?.tools) ? local.tools : work.tools
					},
					lifecycleMeta(res)
				);
				out.className = "at__result at__result--err";
				out.textContent = t(
					"lists.officialWriteFailed",
					"Official Toolhub did not accept the write. Saved locally in Evolved instead: {msg}",
					{ msg: res.lastError || t("lists.unknownOfficialError", "Unknown Toolhub error") }
				);
				return;
			}
			demoListDelete(work.id);
			clearApiCache();
			const officialId = res?.toolhub?.id;
			navigateTo(officialId ? listHref(String(officialId)) : "/lists");
		} catch (error) {
			out.className = "at__result at__result--err";
			out.textContent = t(
				"lists.officialWriteFailedNoDraft",
				"Official Toolhub did not accept the write: {msg}",
				{
					msg: backendErrorMessage(error)
				}
			);
		}
	});
}

/**
 * @param {{ id: string }} work
 * @param {boolean} officialEditing
 */
function setupListDelete(work, officialEditing) {
	const del = $("[data-le-delete]");
	if (!del) return;
	del.addEventListener("click", async () => {
		const out = /** @type {HTMLElement} */ ($("[data-official-result]"));
		if (officialEditing && officialWriteAvailable()) {
			out.className = "at__result";
			out.textContent = t("lists.publishingToToolhub", "Publishing to official Toolhub…");
			try {
				await officialWrite("DELETE", `/v1/write/lists/${encodeURIComponent(work.id)}/`);
				clearApiCache();
				navigateTo("/lists");
				return;
			} catch (error) {
				out.className = "at__result at__result--err";
				out.textContent = t(
					"lists.officialWriteFailedNoDraft",
					"Official Toolhub did not accept the write: {msg}",
					{ msg: backendErrorMessage(error) }
				);
				return;
			}
		}
		if (officialWriteAvailable()) {
			await officialWrite("DELETE", `/v1/write/lists/${encodeURIComponent(work.id)}/fallback/`).catch(
				() => undefined
			);
			demoListDelete(work.id);
			navigateTo("/my-lists");
			return;
		}
		out.className = "at__result at__result--err";
		out.textContent = toolhubSignInRequiredMessage();
	});
}

/**
 * @param {string} html
 * @param {string} label
 * @param {Record<string, any> | null} meta
 * @returns {string}
 */
function withFieldProvenance(html, label, meta) {
	return meta ? `<div class="sync-field-wrap">${html}${fieldProvenance(label, meta)}</div>` : html;
}

/* ---- Lists overview + list detail -------------------------------------- */
export async function viewLists() {
	// Stryker disable next-line ObjectLiteral: `{}` is equivalent to `{ results: [] }` because the value is read as `.results || []`.
	const data = await apiGet("/lists/", { page_size: "30" }).catch(() => ({ results: [] }));
	const live = (data.results || []).map((/** @type {any} */ list) => normalizeList(list));
	// Signed-in local Evolved lists appear first, clearly tagged.
	const mine = signedIn() ? demoLists().map((/** @type {any} */ list) => listCardData(list)) : [];
	const all = [...mine, ...live];
	const html = `
	<div class="container page">
		<div class="section-head"><h1 class="page__title">${t("lists.curatedLists", "Curated lists")}</h1>
			${signedIn() ? button(t("lists.createAList", "Create a list"), { variant: "primary", href: "/lists/create", icon: "add" }) : ""}</div>
		<p class="page__intro">${t("lists.listsIntro", "Community-published collections of tools for specific tasks and communities.")}</p>
		${all.length > 0 ? grid("grid-lists", all, listCard) : `<p class="empty">${t("lists.noListsFound", "No lists found.")}</p>`}
	</div>`;
	return { title: t("lists.curatedListsDocTitle", "Curated lists — Toolhub"), html };
}
/**
 * @param {string} id
 * @returns {Promise<{ title: string, html: string }>}
 */
export async function viewList(id) {
	const isDemo = isDemoListId(id);
	let l,
		demoTag = "",
		editBtn = "";
	/** @type {Tool[]} */
	let tools;
	if (isDemo) {
		const d = demoListGet(id);
		if (!d) return viewNotFound();
		tools = /** @type {Tool[]} */ (await getToolsByName(d.tools));
		l = {
			title: d.title || t("lists.untitledList", "Untitled list"),
			description: d.description || "",
			toolCount: tools.length
		};
		demoTag = ` ${syncBadge(d)}`;
	} else {
		try {
			l = normalizeList(await apiGet(`/lists/${encodeURIComponent(id)}/`));
			tools = l.tools;
		} catch (error) {
			// 404 → the list is genuinely absent; anything else is an outage and
			// must reach the router boundary, not masquerade as "not found".
			if (error instanceof ApiError && error.status === 404) return viewNotFound();
			throw error;
		}
	}
	if (signedIn()) {
		// Stryker disable next-line StringLiteral: button() defaults variant to "outline", so "" renders identical markup — equivalent.
		editBtn = button(t("lists.editList", "Edit list"), {
			variant: "outline",
			href: `${listHref(id)}/edit`,
			icon: "edit"
		});
	}
	await attachEndorsements(tools);
	tools = rankFitsFirst(tools);
	const html = `
	<div class="container page">
		<a class="back" href="/lists">${t("lists.allLists", "← All lists")}</a>
		<div class="section-head"><h1 class="page__title"${dirAttrs(l.title)}>${esc(l.title)}${demoTag} <span class="lcard__count">${esc(countLabel(l.toolCount, t("lists.toolOne", "tool"), t("lists.toolOther", "tools")))}</span></h1>${editBtn}</div>
		<div class="prose page__intro"${dirAttrs(l.description)}>${esc(l.description)}</div>
		${tools.length > 0 ? grid("grid-tools", tools, (/** @type {Tool} */ t) => toolCard(t)) : `<p class="empty">${t("lists.noToolsInList", "This list has no tools yet.")}</p>`}
	</div>`;
	return { title: t("lists.docTitle", "{title} — Toolhub", { title: l.title }), html };
}
// Evolved-local list drafts/fallbacks for the signed-in user.
export function viewMyLists() {
	const cards = demoLists().map((/** @type {any} */ list) => listCardData(list));
	const html = `
	<div class="container page">
		<div class="section-head"><h1 class="page__title">${t("lists.yourLists", "Your lists")} <span class="exp-badge">${t("lists.experimental", "Experimental")}</span></h1>
			${button(t("lists.createAList", "Create a list"), { variant: "primary", href: "/lists/create", icon: "add" })}</div>
		<p class="page__intro">${t("lists.yourListsIntro", "Lists saved in Evolved as drafts, fallbacks, or local records — see")}
		<a href="/rules-of-engagement">${t("lists.rulesOfEngagement", "Rules of Engagement")}</a>.</p>
		${cards.length > 0 ? grid("grid-lists", cards, listCard) : `<p class="empty">${t("lists.noListsYet", "No lists yet.")} <a href="/lists/create">${t("lists.createFirstList", "Create your first list")}</a>.</p>`}
	</div>`;
	return { title: t("lists.yourListsDocTitle", "Your lists — Toolhub"), html };
}
// EXPERIMENTAL — favorites view. Tools are read by name (local-first via getTool); the
// overlay only stores which names are favorited. Needs: GET /api/user/favorites/ in production.
export async function viewFavorites() {
	const tools = /** @type {Tool[]} */ (await getToolsByName(favNames()));
	await attachEndorsements(tools);
	const body =
		tools.length > 0
			? grid("grid-tools", tools, (/** @type {Tool} */ t) => toolCard(t))
			: `<p class="empty">${t("lists.noFavoritesYet", "No favorites yet. Tap the")} ${icon("starOutline")}<span class="skip-label">${t("lists.star", "star")}</span> ${t("lists.favoritesHint", "on any tool card or page to save it here.")}</p>`;
	return {
		title: t("lists.favoritesDocTitle", "Favorites — Toolhub"),
		html: `
		<div class="container page">
			<h1 class="page__title">${t("lists.favorites", "Favorites")} <span class="exp-badge">${t("lists.experimental", "Experimental")}</span></h1>
			<p class="page__intro">${t("lists.favoritesIntro", "Tools you've saved. Stored only in this browser — see")}
			<a href="/rules-of-engagement">${t("lists.rulesOfEngagement", "Rules of Engagement")}</a>.</p>
			${body}
		</div>`
	};
}
// Create/edit a list. Official lists write to Toolhub; Evolved draft lists keep
// using the overlay store as a local fallback.
/**
 * @param {string | null} id
 * @returns {{ title: string, html: string, mount: () => void } | { title: string, html: string } | Promise<{ title: string, html: string, mount: () => void } | { title: string, html: string }>}
 */
export function viewListEdit(id) {
	const editing = id !== null && id !== undefined;
	const localList = editing ? demoListGet(id) : null;
	const src = localList || (editing ? null : demoListNew());
	if (src) return renderListEdit(src, { editing, officialEditing: false });
	if (editing) {
		return Promise.resolve(apiGet(`/lists/${encodeURIComponent(id)}/`))
			.then((raw) => {
				const official = officialListSource(id, raw);
				return official ? renderListEdit(official, { editing: true, officialEditing: true }) : viewNotFound();
			})
			.catch((error) => {
				if (error instanceof ApiError && error.status === 404) return viewNotFound();
				throw error;
			});
	}
	return viewNotFound();
}

/**
 * @param {string} fallbackId
 * @param {any} raw
 * @returns {{ id: string, title: string, description: string, tools: string[] } | null}
 */
function officialListSource(fallbackId, raw) {
	if (!raw || typeof raw !== "object") return null;
	return {
		id: String(raw.id ?? fallbackId),
		title: raw.title || "",
		description: raw.description || "",
		tools: (raw.tools || [])
			.map((/** @type {string | { name?: string }} */ tool) => (typeof tool === "string" ? tool : tool.name))
			.filter(Boolean)
	};
}

/**
 * @param {{ id: string, title: string, description: string, tools: string[] }} src
 * @param {{ editing: boolean, officialEditing: boolean }} options
 * @returns {{ title: string, html: string, mount: () => void }}
 */
function renderListEdit(src, { editing, officialEditing }) {
	const metaSource =
		/** @type {{ syncStatus?: string, lastError?: string, validationErrors?: any[], reviewStatus?: string }} */ (
			src
		);
	const work = {
		id: src.id,
		title: src.title || "",
		description: src.description || "",
		// Stryker disable next-line ArrayDeclaration: demoListNew()/demoListGet() always provide a tools array, so the `|| []` fallback is never taken — equivalent.
		tools: [...(src.tools || [])]
	};
	const listMeta = editing
		? officialEditing
			? { syncStatus: SYNC_STATUS.official }
			: {
					syncStatus: metaSource.syncStatus || SYNC_STATUS.localDraft,
					lastError: metaSource.lastError,
					validationErrors: metaSource.validationErrors,
					reviewStatus: metaSource.reviewStatus
				}
		: null;
	const listState = listMeta ? syncState(listMeta) : null;
	const listStatusPanel = listMeta
		? syncStatusPanel(listMeta, {
				title: t("lists.writeStatus", "List write status"),
				retryAttrs: listState?.retryAvailable && officialWriteAvailable() ? "data-le-retry" : "",
				discardAttrs: officialEditing ? "" : "data-le-delete",
				discardLabel: t("lists.discardLocalList", "Discard local list"),
				showIfOfficial: true
			})
		: "";
	// Stryker disable next-line StringLiteral: button() defaults variant to "outline", so "" renders identical markup — equivalent.
	const searchToolsBtn = button(t("lists.search", "Search"), { variant: "outline", attrs: "data-le-search" });
	const html = `
	<div class="container page le">
		<a class="back" href="${editing ? listHref(work.id) : "/my-lists"}">${t("lists.back", "← Back")}</a>
		<h1 class="page__title">${editing ? t("lists.editList", "Edit list") : t("lists.createAList", "Create a list")} <span class="exp-badge">${t("lists.experimental", "Experimental")}</span></h1>
		<form data-le-form>
			${listStatusPanel}
			${withFieldProvenance(fInput(t("lists.title", "Title"), "le-title", work.title, { req: true, max: 120, reqMark: false }), t("lists.title", "Title"), listMeta)}
			${withFieldProvenance(fArea(t("lists.description", "Description"), "le-desc", work.description, null, { max: 600 }), t("lists.description", "Description"), listMeta)}
			<h2 class="le__h2">${t("lists.tools", "Tools")} <span class="le__count" data-le-count></span></h2>
			${listMeta ? fieldProvenance(t("lists.tools", "Tools"), listMeta) : ""}
			<ol class="le__tools" data-le-tools></ol>
			<div class="le__add">
				<input class="le__input" id="le-q" type="search" aria-label="${t("lists.searchToolsToAdd", "Search tools to add")}" placeholder="${t("lists.searchToolsToAddPlaceholder", "Search tools to add…")}" autocomplete="off" />
				${searchToolsBtn}
			</div>
			<div class="le__results" data-le-results></div>
			<div class="le__actions">
				${button(editing ? t("lists.saveChanges", "Save changes") : t("lists.createList", "Create list"), { variant: "primary", type: "submit" })}
				${editing && officialEditing ? button(t("lists.deleteList", "Delete list"), { variant: "danger", cls: "le__delete", attrs: "data-le-delete" }) : ""}
			</div>
			<p class="at__result" data-official-result aria-live="polite"></p>
		</form>
	</div>`;
	function mount() {
		const form = /** @type {HTMLFormElement} */ ($("[data-le-form]"));
		const changeReview = editing ? mountChangeReview(form) : null;
		const resetChangeReview = () => changeReview?.reset();
		form.addEventListener("input", resetChangeReview);
		form.addEventListener("change", resetChangeReview);
		const toolsEl = /** @type {HTMLElement} */ ($("[data-le-tools]")),
			countEl = /** @type {HTMLElement} */ ($("[data-le-count]")),
			resultsEl = /** @type {HTMLElement} */ ($("[data-le-results]"));
		function renderTools() {
			countEl.textContent = countLabel(
				work.tools.length,
				t("lists.toolOne", "tool"),
				t("lists.toolOther", "tools")
			);
			toolsEl.innerHTML =
				work.tools.length > 0
					? work.tools
							.map(
								(n, i) => `
				<li data-tn="${esc(n)}"><span class="le__tn"${dirAttrs(n)}>${esc(n)}</span>
					<span class="le__rowact">
						${iconButton("chevronUp", t("lists.moveUp", "Move up"), { size: "sm", attrs: 'data-move="up"', disabled: i === 0 })}
						${iconButton("chevronDown", t("lists.moveDown", "Move down"), { size: "sm", attrs: 'data-move="down"', disabled: i === work.tools.length - 1 })}
						${iconButton("close", t("lists.removeFromList", "Remove from list"), { size: "sm", variant: "danger", attrs: "data-rm" })}
					</span></li>`
							)
							.join("")
					: `<li class="le__empty">${t("lists.noToolsYet", "No tools yet — search below to add some.")}</li>`;
		}
		renderTools();
		toolsEl.addEventListener("click", (e) => {
			const target = /** @type {EventTarget} */ (e.target);
			const li = target.closest("[data-tn]");
			// Stryker disable next-line ConditionalExpression: clicks always originate inside a rendered row, so `li` is never null here — defensive guard, unreachable false case.
			if (!li) return;
			const n = /** @type {string} */ (li.getAttribute("data-tn")),
				i = work.tools.indexOf(n);
			// Stryker disable next-line ConditionalExpression: rows are rendered from work.tools, so the clicked name is always present (i !== -1) — defensive guard.
			if (i === -1) return;
			const up = target.closest('[data-move="up"]');
			const down = target.closest('[data-move="down"]');
			if (target.closest("[data-rm]")) {
				work.tools.splice(i, 1);
				// up/down boundary rows render their move button `disabled`, so a clickable
				// up implies i>0 and a clickable down implies i<len-1; `up || down` is enough.
			} else if (up || down) {
				work.tools.splice(i + (up ? -1 : 1), 0, work.tools.splice(i, 1)[0]);
			} else {
				return;
			}
			renderTools();
			resetChangeReview();
		});
		async function runSearch() {
			const q = /** @type {HTMLInputElement} */ ($input("#le-q")).value.trim();
			if (!q) return;
			resultsEl.innerHTML = `<p class="le__searching">${t("lists.searching", "Searching…")}</p>`;
			try {
				const data = await apiGet("/search/tools/", { q, page_size: "8" });
				const rows = (data.results || []).map((/** @type {any} */ tool) => normalizeTool(tool));
				resultsEl.innerHTML =
					rows.length > 0
						? rows
								.map((/** @type {Tool} */ t) => {
									const inList = work.tools.includes(t.name);
									return `<button class="le__result${inList ? " is-in" : ""}" type="button" data-add="${esc(t.name)}" ${inList ? "disabled" : ""}>
						${inList ? icon("check") : icon("add")} <span${textAttrs(t.title, t.titleLanguage)}>${esc(t.title)}</span></button>`;
								})
								.join("")
						: `<p class="le__empty">${t("lists.noMatches", "No matches.")}</p>`;
			} catch {
				resultsEl.innerHTML = `<p class="le__empty">${t("lists.searchFailed", "Search failed.")}</p>`;
			}
		}
		/** @type {HTMLElement} */ ($("[data-le-search]")).addEventListener("click", runSearch);
		/** @type {HTMLInputElement} */ ($input("#le-q")).addEventListener("keydown", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				runSearch();
			}
		});
		resultsEl.addEventListener("click", (e) => {
			const b = /** @type {HTMLButtonElement | null} */ (
				/** @type {EventTarget} */ (e.target).closest("[data-add]")
			);
			// Stryker disable next-line ConditionalExpression: only [data-add] buttons live in the results list, so clicks always resolve to one — defensive guard.
			if (!b) return;
			const n = /** @type {string} */ (b.getAttribute("data-add"));
			// Stryker disable next-line ConditionalExpression: results for already-listed tools render `disabled`, so an enabled click never targets a tool already in work.tools — guard's false branch is unreachable.
			if (!work.tools.includes(n)) {
				work.tools.push(n);
				renderTools();
				resetChangeReview();
				b.disabled = true;
				b.classList.add("is-in");
				/** @type {HTMLElement} */ (b.querySelector(".icon")).outerHTML = icon("check");
			}
		});
		form.addEventListener("submit", async (e) => {
			e.preventDefault();
			const title = fieldValue("le-title");
			if (!title) {
				/** @type {HTMLElement} */ ($("#le-title")).focus();
				return;
			}
			work.title = title;
			work.description = fieldValue("le-desc");
			const out = /** @type {HTMLElement} */ ($("[data-official-result]"));
			const canOfficialWrite = officialWriteAvailable();
			if (
				editing &&
				canOfficialWrite &&
				!shouldProceedWithFieldChanges(changeReview, listChangeDescriptors(src, work), out)
			) {
				return;
			}
			if (canOfficialWrite) {
				out.className = "at__result";
				out.textContent = t("lists.publishingToToolhub", "Publishing to official Toolhub…");
				try {
					const res = await officialWrite(
						officialEditing ? "PUT" : "POST",
						officialEditing ? `/v1/write/lists/${encodeURIComponent(work.id)}/` : "/v1/write/lists/",
						officialListPayload(work)
					);
					const local = res?.local && typeof res.local === "object" ? res.local : null;
					if (local) {
						demoListSave(
							{
								id: String(local.id || work.id),
								title: local.title || work.title,
								description: local.description || work.description,
								tools: Array.isArray(local.tools) ? local.tools : work.tools
							},
							lifecycleMeta(res)
						);
					} else if (!officialEditing) {
						demoListDelete(work.id);
					}
					if (res?.result === SYNC_STATUS.localFallback) {
						out.className = "at__result at__result--err";
						out.textContent = t(
							"lists.officialWriteFailed",
							"Official Toolhub did not accept the write. Saved locally in Evolved instead: {msg}",
							{ msg: res.lastError || t("lists.unknownOfficialError", "Unknown Toolhub error") }
						);
						return;
					}
					clearApiCache();
					const officialId = res?.toolhub?.id;
					navigateTo(officialId ? listHref(String(officialId)) : listHref(work.id));
					return;
				} catch (error) {
					const msg = backendErrorMessage(error);
					out.className = "at__result at__result--err";
					out.textContent = t(
						"lists.officialWriteFailedNoDraft",
						"Official Toolhub did not accept the write: {msg}",
						{
							msg
						}
					);
					return;
				}
			}
			out.className = "at__result at__result--err";
			out.textContent = toolhubSignInRequiredMessage();
		});
		setupListRetry(work);
		setupListDelete(work, officialEditing);
	}
	return {
		title: t("lists.docTitle", "{title} — Toolhub", {
			title: editing ? t("lists.editList", "Edit list") : t("lists.createAList", "Create a list")
		}),
		html,
		mount
	};
}
