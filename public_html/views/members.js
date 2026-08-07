// SPDX-License-Identifier: GPL-3.0-or-later
import { viewPeople } from "./authors.js";

// Backward-compatible alias. Account evidence now strengthens results inside
// the unified Community directory.
export async function viewMembers() {
	const view = await viewPeople();
	return {
		...view,
		mount() {
			const params = new URLSearchParams(location.search);
			params.delete("view");
			history.replaceState({}, "", `/people${params.size > 0 ? `?${params}` : ""}`);
			view.mount?.();
		}
	};
}
