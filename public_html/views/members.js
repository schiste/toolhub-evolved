// SPDX-License-Identifier: GPL-3.0-or-later
import { viewAccounts } from "./accounts.js";

// Backward-compatible alias. The canonical, shareable location is the Accounts
// view inside the Community directory.
export async function viewMembers() {
	return viewAccounts({ canonicalize: true });
}
