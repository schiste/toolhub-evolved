// SPDX-License-Identifier: GPL-3.0-or-later
import { esc, safeHttpUrl } from "../core/dom.js";
import { backendGetJson } from "../core/api.js";
import { t } from "../core/i18n.js";
import { toolHref } from "../core/routing.js";
import { serverWrite } from "../core/serversync.js";
import { accountSection } from "./account-workbench.js";

const EDIT_FIELDS = [
	{ name: "title", label: () => t("wikiUserScripts.displayTitle", "Display title"), kind: "input", required: true },
	{ name: "subtitle", label: () => t("wikiUserScripts.subtitle", "Subtitle"), kind: "input" },
	{ name: "description", label: () => t("wikiUserScripts.description", "Description"), kind: "textarea" },
	{ name: "license", label: () => t("wikiUserScripts.license", "License"), kind: "input" },
	{ name: "keywords", label: () => t("wikiUserScripts.keywords", "Keywords"), kind: "lines" },
	{
		name: "user_docs_url",
		label: () => t("wikiUserScripts.userDocumentation", "User documentation links (JSON)"),
		kind: "json"
	},
	{
		name: "developer_docs_url",
		label: () => t("wikiUserScripts.developerDocumentation", "Developer documentation links (JSON)"),
		kind: "json"
	}
];

const FIELD_LABELS = new Map(EDIT_FIELDS.map((field) => [field.name, field]));

/** @param {unknown} value */
function record(value) {
	return value && typeof value === "object" && !Array.isArray(value)
		? /** @type {Record<string, any>} */ (value)
		: {};
}

/** @param {string} value */
function domId(value) {
	return value.toLowerCase().replaceAll(/[^a-z0-9_-]+/g, "-") || "tool";
}

/** @param {unknown} value */
function localizedUrlEntries(value) {
	const entries = Array.isArray(value) ? value : typeof value === "string" && value.trim() ? [value] : [];
	return entries.map((item) => (typeof item === "string" ? { url: item } : item));
}

/** @param {any} field @param {unknown} value */
function fieldText(field, value) {
	if (field.kind === "lines") return Array.isArray(value) ? value.join("\n") : "";
	if (field.kind === "json") return JSON.stringify(localizedUrlEntries(value), null, 2);
	return typeof value === "string" ? value : "";
}

/** @param {string} name */
function fieldLabel(name) {
	const field = FIELD_LABELS.get(name);
	return field ? field.label() : name.replaceAll("_", " ");
}

/** @param {any} value */
function metadataPreview(value) {
	if (Array.isArray(value)) {
		return value
			.map((item) => {
				if (item && typeof item === "object") {
					const url = String(item.url || "");
					const language = String(item.language || "");
					return language ? `${url} (${language})` : url;
				}
				return String(item ?? "");
			})
			.filter(Boolean)
			.join(", ");
	}
	return typeof value === "string" ? value : String(value ?? "");
}

/** @param {Record<string, any>} values */
function metadataRows(values) {
	const rows = EDIT_FIELDS.filter((field) => values[field.name] !== undefined && values[field.name] !== null)
		.map((field) => {
			const value = metadataPreview(values[field.name]);
			return `<dt>${esc(fieldLabel(field.name))}</dt><dd>${esc(value || "—")}</dd>`;
		})
		.join("");
	return rows
		? `<dl class="wiki-user-scripts__metadata">${rows}</dl>`
		: `<p class="empty">${t("wikiUserScripts.noMetadata", "No catalogue metadata is available.")}</p>`;
}

/** @param {string} name @param {unknown} value @param {string} toolName */
function renderEditorField(name, value, toolName) {
	const field = FIELD_LABELS.get(name);
	if (!field) return "";
	const id = `wiki-user-script-owner-${domId(toolName)}-${name}`;
	const label = field.label();
	const hint =
		field.kind === "lines"
			? t("wikiUserScripts.keywordsHint", "Enter one keyword per line.")
			: field.kind === "json"
				? t(
						"wikiUserScripts.localizedLinksHint",
						"Use a JSON array of objects with a URL and optional language tag."
					)
				: "";
	const describedBy = hint ? ` aria-describedby="${id}-hint"` : "";
	const labelContent = `${esc(label)}${field.required ? ' <span class="le__req">*</span>' : ""}${hint ? `<span class="le__hint" id="${id}-hint">${esc(hint)}</span>` : ""}`;
	/** @param {string} controlHtml */
	const wrapControl = (controlHtml) => `<label class="le__label" for="${id}">${labelContent}${controlHtml}</label>`;
	const valueText = fieldText(field, value);
	if (field.kind === "textarea" || field.kind === "lines" || field.kind === "json") {
		const rows = field.kind === "textarea" ? 5 : field.kind === "lines" ? 3 : 5;
		const max = field.kind === "json" ? 50000 : 4000;
		return wrapControl(
			`<textarea class="le__input" id="${id}" data-owner-edit-field="${name}" rows="${rows}" maxlength="${max}"${describedBy}${field.required ? " required" : ""}>${esc(valueText)}</textarea>`
		);
	}
	return wrapControl(
		`<input class="le__input" id="${id}" data-owner-edit-field="${name}" type="text" maxlength="4000" value="${esc(valueText)}"${describedBy}${field.required ? " required" : ""} />`
	);
}

/** @param {string} name @param {string} text */
function parseEditorValue(name, text) {
	const field = FIELD_LABELS.get(name);
	if (!field) throw new Error(t("wikiUserScripts.unsupportedField", "This field is not editable here."));
	if (field.kind === "lines") {
		return text
			.split(/\r?\n/)
			.map((item) => item.trim())
			.filter(Boolean)
			.slice(0, 50);
	}
	if (field.kind === "json") {
		if (!text.trim()) return [];
		let value;
		try {
			value = JSON.parse(text);
		} catch {
			throw new Error(t("wikiUserScripts.invalidLinksJson", "Documentation links must be valid JSON."));
		}
		if (!Array.isArray(value)) {
			throw new Error(t("wikiUserScripts.linksArrayRequired", "Documentation links must be a JSON array."));
		}
		return value;
	}
	return text.trim();
}

/** @param {any} left @param {any} right */
function sameValue(left, right) {
	return JSON.stringify(left) === JSON.stringify(right);
}

/** @param {string} name @param {any} value */
function normalizedCurrentValue(name, value) {
	const field = FIELD_LABELS.get(name);
	if (field?.kind === "lines") return Array.isArray(value) ? value : [];
	if (field?.kind === "json") return localizedUrlEntries(value);
	return typeof value === "string" ? value.trim() : "";
}

/** @param {HTMLFormElement} form @param {Record<string, any>} current */
function changedFields(form, current) {
	/** @type {Record<string, any>} */
	const patch = {};
	for (const field of EDIT_FIELDS) {
		const input = form.querySelector(`[data-owner-edit-field="${field.name}"]`);
		if (!(input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement)) continue;
		const value = parseEditorValue(field.name, input.value);
		const currentValue = normalizedCurrentValue(field.name, Reflect.get(current, field.name));
		if (!sameValue(value, currentValue)) {
			patch[field.name] = value;
		}
	}
	return patch;
}

/** @param {string} status */
function reviewStatus(status) {
	const normalized = String(status || "unknown").toLowerCase();
	if (normalized === "pending") {
		return { label: t("wikiUserScripts.pending", "Pending moderation"), className: "sync-badge--review-pending" };
	}
	if (normalized === "approved") {
		return {
			label: t("wikiUserScripts.approved", "Approved Evolved curation"),
			className: "sync-badge--review-approved"
		};
	}
	if (normalized === "rejected") {
		return { label: t("wikiUserScripts.rejected", "Rejected"), className: "sync-badge--sync-error" };
	}
	return { label: t("wikiUserScripts.unknownStatus", "Status unavailable"), className: "sync-badge--review-pending" };
}

/** @param {any} item */
function renderRevision(item) {
	const data = record(item?.data);
	const status = reviewStatus(data.reviewStatus);
	const patch = record(data.patch);
	const proposedValues = Object.entries(patch)
		.map(([name, value]) => `<li><strong>${esc(fieldLabel(name))}:</strong> ${esc(metadataPreview(value))}</li>`)
		.join("");
	const conflicts = Array.isArray(data.conflictFields)
		? data.conflictFields.filter((field) => typeof field === "string")
		: [];
	const date = String(data.modifiedAt || data.createdAt || "");
	return `<li class="wiki-user-scripts__revision">
		<div class="wiki-user-scripts__revision-head"><span class="sync-badge ${status.className}">${esc(status.label)}</span><span class="recent-table__muted">${esc(date)}</span><span class="recent-table__muted">${esc(t("wikiUserScripts.revision", "Revision $1", String(data.id || item?.id || "")))}</span></div>
		${proposedValues ? `<ul class="wiki-user-scripts__revision-values">${proposedValues}</ul>` : ""}
		${data.rationale ? `<p>${esc(String(data.rationale))}</p>` : ""}
		${conflicts.length > 0 ? `<p class="wiki-user-scripts__conflict">${esc(t("wikiUserScripts.conflict", "Source conflict on: $1", conflicts.join(", ")))}</p>` : ""}
	</li>`;
}

/** @param {any[]} items @param {string} toolName */
function renderHistory(items, toolName) {
	const headingId = `wiki-user-script-history-title-${domId(toolName)}`;
	const rows = items.filter(
		(item) => item?.kind === "catalog-curations" && record(item.data).editKind === "wiki_userscript_owner"
	);
	return `<section class="wiki-user-scripts__history" aria-labelledby="${esc(headingId)}">
		<h4 id="${esc(headingId)}">${t("wikiUserScripts.historyTitle", "Proposal history (Evolved-local, not official Toolhub data)")}</h4>
		${rows.length > 0 ? `<ol class="wiki-user-scripts__revisions">${rows.map((item) => renderRevision(item)).join("")}</ol>` : `<p class="empty">${t("wikiUserScripts.noHistory", "No owner proposals yet.")}</p>`}
	</section>`;
}

/** @param {Record<string, any>} entry @param {Record<string, any>} context @param {string} notice */
function renderOwnerEditor(entry, context, notice = "") {
	const toolName = String(entry.toolName || "");
	const proof = record(context.ownerProof);
	const items = Array.isArray(context.items) ? context.items : [];
	const current = record(entry.currentMetadata);
	const prefix = `wiki-user-script-owner-${domId(toolName)}`;
	const verification = context.canEdit
		? `<p class="wiki-user-scripts__verified">${esc(t("wikiUserScripts.verifiedOwner", "Verified page owner"))}: ${esc(String(proof.username || entry.owner || ""))} · ${esc(String(proof.wiki || entry.wiki || ""))}</p>`
		: context.supported
			? `<p class="wiki-user-scripts__read-only" role="status">${t("wikiUserScripts.ownerUnverified", "This Wikimedia identity is not verified as the owner of this script page. You can review your edit history, but cannot propose changes from this account.")}</p>`
			: `<p class="wiki-user-scripts__read-only" role="status">${t("wikiUserScripts.notSupported", "This listing is not an editable Wikimedia user-script page.")}</p>`;
	const form = context.canEdit
		? `<form class="wiki-user-scripts__form" data-wiki-owner-form="${esc(toolName)}" novalidate>
			<p class="wiki-user-scripts__local-note">${t("wikiUserScripts.localOnly", "These fields create an Evolved-local metadata proposal. They do not edit the script page or an official Toolhub record.")}</p>
			<div class="wiki-user-scripts__fields">${EDIT_FIELDS.map((field) => renderEditorField(field.name, Reflect.get(current, field.name), toolName)).join("")}</div>
			<label class="le__label" for="${prefix}-rationale">${t("wikiUserScripts.rationale", "Why are you proposing this edit?")} <span class="le__req">*</span><textarea class="le__input" id="${prefix}-rationale" data-owner-edit-rationale rows="3" maxlength="2000" required></textarea></label>
			<div class="wiki-user-scripts__actions"><button class="btn btn--primary" type="submit">${t("wikiUserScripts.submit", "Submit for moderation")}</button></div>
			<p class="wiki-user-scripts__notice" data-owner-editor-notice role="status" aria-live="polite">${esc(notice)}</p>
		</form>`
		: notice
			? `<p class="wiki-user-scripts__notice" role="status" aria-live="polite">${esc(notice)}</p>`
			: "";
	return `<div class="wiki-user-scripts__editor-content">
		<h3>${esc(String(entry.title || toolName))}</h3>
		${verification}
		<p class="wiki-user-scripts__local-note">${t("wikiUserScripts.notOfficial", "This workbench only creates Evolved-local curation. It never changes official Toolhub data or the Wikimedia source script.")}</p>
		${notice && !context.canEdit ? `<p class="wiki-user-scripts__notice" role="status" aria-live="polite">${esc(notice)}</p>` : ""}
		${form}
		${renderHistory(items, toolName)}
	</div>`;
}

/** @param {Record<string, any>} entry */
function renderEntry(entry) {
	const toolName = String(entry.toolName || "");
	const sourceUrl = safeHttpUrl(entry.sourceUrl);
	const current = record(entry.currentMetadata);
	const source = record(entry.sourceMetadata);
	const curatedFields = Array.isArray(entry.ownerCuratedFields)
		? entry.ownerCuratedFields.filter((field) => typeof field === "string")
		: [];
	const projectionNote = entry.projectionAvailable
		? t("wikiUserScripts.currentValues", "Current effective Evolved value")
		: t("wikiUserScripts.sourceFallback", "Evolved projection unavailable; showing the source-page snapshot");
	return `<article class="wiki-user-scripts__entry" data-wiki-owner-entry="${esc(toolName)}">
		<div class="wiki-user-scripts__entry-head">
			<div><h3><a href="${esc(toolHref(toolName))}">${esc(String(entry.title || toolName))}</a></h3><code>${esc(toolName)}</code></div>
			<button class="account-records__action" type="button" data-wiki-owner-open="${esc(toolName)}">${t("wikiUserScripts.reviewMetadata", "Review metadata")}</button>
		</div>
		<p class="wiki-user-scripts__owner">${esc(String(entry.owner || ""))} · ${esc(String(entry.wiki || ""))}${entry.historyOnly ? ` · ${t("wikiUserScripts.historyOnly", "History only")}` : ""}</p>
		<p class="wiki-user-scripts__local-note">${t("wikiUserScripts.localOnly", "These fields create an Evolved-local metadata proposal. They do not edit the script page or an official Toolhub record.")}</p>
		<section class="wiki-user-scripts__current" aria-label="${esc(projectionNote)}">
			<h4>${esc(projectionNote)}</h4>
			${metadataRows(current)}
			${curatedFields.length > 0 ? `<p class="wiki-user-scripts__curated">${esc(t("wikiUserScripts.curatedFields", "Approved owner-curated fields"))}: ${curatedFields.map((field) => esc(fieldLabel(field))).join(", ")}</p>` : ""}
		</section>
		<details class="wiki-user-scripts__source-values"><summary>${t("wikiUserScripts.sourceCensusValues", "Source-page census values")}</summary>${metadataRows(source)}</details>
		${sourceUrl ? `<p><a href="${sourceUrl}" target="_blank" rel="noopener nofollow">${t("wikiUserScripts.openSource", "Open Wikimedia source page")}</a></p>` : ""}
		<div class="wiki-user-scripts__editor" data-wiki-owner-editor hidden></div>
	</article>`;
}

/** @param {any} error */
function errorMessage(error) {
	const body = record(error?.body);
	return String(
		body.error || error?.message || t("wikiUserScripts.requestFailed", "The request could not be completed.")
	);
}

/** @param {string} toolName */
function ownerEditPath(toolName) {
	return `/v1/catalog/tools/${encodeURIComponent(toolName)}/owner-edits/`;
}

export function wikiUserScriptOwnerEditsWorkspace() {
	return {
		html: accountSection({
			id: "wiki-user-scripts-title",
			title: t("wikiUserScripts.title", "My wiki user-script listings"),
			intro: t(
				"wikiUserScripts.intro",
				"These listings come from Wikimedia user-script pages. Changes proposed here stay local to Toolhub Evolved and are never written to the source page or an official Toolhub record."
			),
			className: "wiki-user-scripts",
			body: `<div data-wiki-owner-list aria-live="polite"><p class="empty">${t("wikiUserScripts.loading", "Loading wiki user-script listings...")}</p></div>`
		}),
		mount() {
			const root = document.querySelector(".wiki-user-scripts");
			if (!(root instanceof HTMLElement)) return;
			const workspaceRoot = root;
			const list = workspaceRoot.querySelector("[data-wiki-owner-list]");
			if (!(list instanceof HTMLElement)) return;
			const listRegion = list;
			/** @type {Record<string, any>[]} */
			let entries = [];
			let activeToolName = "";
			let activeContext = {};

			async function loadEntries() {
				const data = await backendGetJson("/v1/me/wiki-user-scripts/");
				if (!data) {
					listRegion.innerHTML = `<p class="empty" role="alert">${t("wikiUserScripts.loadFailed", "Wiki user-script listings could not be loaded.")}</p>`;
					return;
				}
				const candidates = /** @type {unknown[]} */ (Array.isArray(data.entries) ? data.entries : []);
				entries = candidates
					.filter((entry) => entry !== null && typeof entry === "object" && !Array.isArray(entry))
					.map((entry) => /** @type {Record<string, any>} */ (entry));
				listRegion.innerHTML =
					entries.length > 0
						? `<div class="wiki-user-scripts__entries">${entries.map((entry) => renderEntry(entry)).join("")}</div>`
						: `<p class="empty">${t("wikiUserScripts.empty", "No Wikimedia user-script listings were found for this account.")}</p>`;
			}

			/** @param {string} toolName */
			async function openEditor(toolName) {
				const entry = entries.find((item) => item.toolName === toolName);
				const card = [...workspaceRoot.querySelectorAll("[data-wiki-owner-entry]")].find(
					(item) => item.getAttribute("data-wiki-owner-entry") === toolName
				);
				const panel = card?.querySelector("[data-wiki-owner-editor]");
				if (!entry || !(panel instanceof HTMLElement)) return;
				if (activeToolName && activeToolName !== toolName) {
					const previous = [...workspaceRoot.querySelectorAll("[data-wiki-owner-entry]")].find(
						(item) => item.getAttribute("data-wiki-owner-entry") === activeToolName
					);
					const previousPanel = previous?.querySelector("[data-wiki-owner-editor]");
					if (previousPanel instanceof HTMLElement) previousPanel.hidden = true;
				}
				activeToolName = toolName;
				activeContext = {};
				panel.hidden = false;
				panel.innerHTML = `<p class="empty">${t("wikiUserScripts.checkingOwner", "Checking exact Wikimedia page ownership...")}</p>`;
				const context = await backendGetJson(ownerEditPath(toolName));
				if (!context) {
					panel.innerHTML = `<p class="empty" role="alert">${t("wikiUserScripts.ownerCheckFailed", "Ownership could not be verified. No edit form is available.")}</p>`;
					return;
				}
				activeContext = context;
				panel.innerHTML = renderOwnerEditor(entry, context);
			}

			workspaceRoot.addEventListener("click", (event) => {
				const target = event.target;
				if (!(target instanceof Element)) return;
				const button = target.closest("[data-wiki-owner-open]");
				if (!button) return;
				const toolName = button.getAttribute("data-wiki-owner-open") || "";
				openEditor(toolName).catch((error) => {
					const card = button.closest("[data-wiki-owner-entry]");
					const panel = card?.querySelector("[data-wiki-owner-editor]");
					if (panel) panel.innerHTML = `<p class="empty" role="alert">${esc(errorMessage(error))}</p>`;
				});
			});

			workspaceRoot.addEventListener("submit", (event) => {
				const form = event.target;
				if (!(form instanceof HTMLFormElement) || !form.matches("[data-wiki-owner-form]")) return;
				event.preventDefault();
				const toolName = form.getAttribute("data-wiki-owner-form") || "";
				const entry = entries.find((item) => item.toolName === toolName);
				const panel = activeToolName === toolName ? form.closest(".wiki-user-scripts__editor") : null;
				const status = form.querySelector("[data-owner-editor-notice]");
				const rationale = form.querySelector("[data-owner-edit-rationale]");
				const submit = form.querySelector('button[type="submit"]');
				if (!(rationale instanceof HTMLTextAreaElement) || !entry) return;
				if (!rationale.value.trim()) {
					if (status) {
						status.textContent = t(
							"wikiUserScripts.rationaleRequired",
							"Explain the correction before submitting."
						);
					}
					rationale.focus();
					return;
				}
				if (!form.reportValidity()) return;
				/** @type {Record<string, any>} */
				let patch;
				try {
					patch = changedFields(form, record(entry.currentMetadata));
				} catch (error) {
					if (status) status.textContent = errorMessage(error);
					return;
				}
				if (Object.keys(patch).length === 0) {
					if (status) {
						status.textContent = t(
							"wikiUserScripts.noChanges",
							"Change at least one catalogue field before submitting."
						);
					}
					return;
				}
				if (submit instanceof HTMLButtonElement) submit.disabled = true;
				if (status) status.textContent = t("wikiUserScripts.saving", "Saving your proposal for moderation...");
				serverWrite("POST", ownerEditPath(toolName), { patch, rationale: rationale.value.trim() })
					.then(async (response) => {
						let refreshed = null;
						try {
							refreshed = await backendGetJson(ownerEditPath(toolName));
						} catch {
							// The proposal is already saved; keep the returned revision if refresh fails.
						}
						const prior = record(activeContext);
						const refreshedContext = record(refreshed);
						const serverItems = Array.isArray(refreshedContext.items)
							? refreshedContext.items
							: Array.isArray(prior.items)
								? prior.items
								: [];
						const savedItem = response?.item;
						const items = savedItem
							? [savedItem, ...serverItems.filter((item) => item?.id !== savedItem.id)]
							: serverItems;
						const nextContext = { ...prior, ...refreshedContext, items };
						activeContext = nextContext;
						if (panel instanceof HTMLElement) {
							panel.innerHTML = renderOwnerEditor(
								entry,
								nextContext,
								t(
									"wikiUserScripts.saved",
									"Saved for moderation. This proposal is not official Toolhub data."
								)
							);
						}
					})
					.catch((error) => {
						if (status) {
							status.textContent = t(
								"wikiUserScripts.saveFailed",
								"Proposal could not be saved: $1",
								errorMessage(error)
							);
						}
						if (submit instanceof HTMLButtonElement) submit.disabled = false;
					});
			});

			loadEntries().catch((error) => {
				listRegion.innerHTML = `<p class="empty" role="alert">${esc(errorMessage(error))}</p>`;
			});
		}
	};
}
