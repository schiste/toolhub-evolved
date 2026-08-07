// SPDX-License-Identifier: GPL-3.0-or-later
import { backendGetJson } from "./api.js";

/**
 * @typedef {{q?: string, page?: number, pageSize?: number, group?: string, ordering?: string}} AccountDirectorySearch
 */

/** @param {AccountDirectorySearch} search */
function accountParams(search) {
	const params = new URLSearchParams();
	if (search.q) params.set("q", search.q);
	if (search.page && search.page > 1) params.set("page", String(search.page));
	if (search.pageSize) params.set("page_size", String(search.pageSize));
	if (search.group) params.set("group", search.group);
	if (search.ordering) params.set("ordering", search.ordering);
	return params;
}

/** @param {AccountDirectorySearch} [search] */
export async function searchAccounts(search = {}) {
	const params = accountParams(search);
	const data = await backendGetJson(`/v1/accounts/${params.size > 0 ? `?${params}` : ""}`);
	if (!data) throw new Error("Account directory unavailable");
	const accounts = Array.isArray(data.results) ? data.results : [];
	return {
		accounts,
		count: Number.isFinite(Number(data.count)) ? Number(data.count) : accounts.length,
		page: Number(data.page) || 1,
		pageSize: Number(data.pageSize) || search.pageSize || 24,
		pageCount: Number(data.pageCount) || 1,
		next: data.next || null,
		previous: data.previous || null,
		sync: data.sync || { status: "unavailable", complete: false }
	};
}

/** @param {string} accountId */
export function accountById(accountId) {
	return backendGetJson(`/v1/accounts/${encodeURIComponent(accountId)}/`);
}
