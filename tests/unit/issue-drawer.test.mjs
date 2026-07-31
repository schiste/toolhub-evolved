// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

vi.mock("../../public_html/lib/core/serversync.js", async (importActual) => ({
	...(await importActual()),
	serverWrite: vi.fn()
}));
vi.mock("../../public_html/lib/core/diagnostics.js", async (importActual) => ({
	...(await importActual()),
	pageDiagnostics: vi.fn(() => ({
		path: "/tools/example",
		url: "https://toolhub-evolved.local/tools/example",
		console: [{ level: "error", message: "page failure", at: Date.now() }],
		errors: [],
		viewport: { width: 1200, height: 800 }
	}))
}));

import { setServerUser } from "../../public_html/lib/core/session.js";
import { serverWrite } from "../../public_html/lib/core/serversync.js";
import {
	clearIssueContext,
	initIssueDrawer,
	setIssueContext,
	syncIssueReportTrigger
} from "../../public_html/lib/organisms/issue-drawer.js";

function shell() {
	document.body.innerHTML = `
		<a data-issue-external href="https://github.com/schiste/toolhub-evolved/issues">External</a>
		<button data-issue-trigger data-issue-trigger-public type="button"><span class="issue-report-fab__icon"></span>Report</button>
		<button data-issue-trigger data-issue-trigger-authenticated type="button">Report from account</button>
		<aside class="issue-drawer hidden" id="issue-drawer" aria-hidden="true">
			<div role="dialog"><h2 id="issue-drawer-title">Report</h2><button data-issue-close type="button">Close</button><div id="issue-drawer-body"></div></div>
		</aside>`;
	initIssueDrawer();
}

beforeEach(() => {
	setServerUser("Reporter");
	serverWrite.mockReset();
	clearIssueContext();
	shell();
});

test("authenticated trigger replaces the external issue link", () => {
	syncIssueReportTrigger();
	assert.equal(document.querySelector("[data-issue-trigger]").hidden, false);
	assert.equal(document.querySelector("[data-issue-trigger-authenticated]").hidden, false);
	assert.equal(document.querySelector("[data-issue-external]").hidden, true);
	setServerUser(null);
	syncIssueReportTrigger();
	assert.equal(document.querySelector("[data-issue-trigger-public]").hidden, false);
	assert.equal(document.querySelector("[data-issue-trigger-authenticated]").hidden, true);
	assert.equal(document.querySelector("[data-issue-external]").hidden, false);
});

test("signed-out floating trigger opens the Wikimedia sign-in prompt", () => {
	setServerUser(null);
	syncIssueReportTrigger();
	document.querySelector("[data-issue-trigger-public]").click();
	assert.match(document.querySelector("#issue-drawer-body").textContent, /Sign in to report an issue/);
	assert.equal(document.querySelector("#issue-drawer-body a").getAttribute("href"), "/login");
});

test("drawer collects context, requires review, then publishes the approved report", async () => {
	setIssueContext(() => ({ kind: "tool", name: "example" }));
	serverWrite.mockResolvedValue({ number: 42, url: "https://github.com/schiste/toolhub-evolved/issues/42" });
	const trigger = document.querySelector("[data-issue-trigger-public]");
	trigger.click();
	assert.equal(document.body.classList.contains("issue-drawer-open"), true);
	assert.match(document.querySelector("#issue-drawer-body").textContent, /Console entries/);
	document.querySelector("[name=title]").value = "Broken example";
	document.querySelector("[name=description]").value = "The example page failed to load.";
	document.querySelector("[data-issue-form]").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
	assert.match(document.querySelector("#issue-drawer-body").textContent, /Check the public issue/);
	document.querySelector("[data-issue-publish]").click();
	await new Promise((resolve) => setTimeout(resolve, 0));
	assert.equal(serverWrite.mock.calls[0][0], "POST");
	assert.equal(serverWrite.mock.calls[0][1], "/v1/issue-reports/");
	assert.equal(serverWrite.mock.calls[0][2].approved, true);
	assert.equal(serverWrite.mock.calls[0][2].context.custom.name, "example");
	assert.match(document.querySelector("#issue-drawer-body").textContent, /Issue published/);
});
