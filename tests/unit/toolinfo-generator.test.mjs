// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";
import {
	buildToolinfoGeneratorEntries,
	toolinfoGeneratorWorkspace
} from "../../public_html/lib/organisms/toolinfo-generator.js";
import { CORE_TOOLINFO_FIELDS } from "../../public_html/lib/core/toolinfo-generator.js";

const writeText = vi.fn();

beforeEach(() => {
	document.body.innerHTML = "";
	vi.clearAllMocks();
	Object.defineProperty(navigator, "clipboard", {
		configurable: true,
		value: { writeText }
	});
});

function tool(name, project, title = name) {
	return {
		name,
		title,
		toolforgeProjects: project ? [project] : [],
		canonicalRecord: {
			name,
			title,
			description: `${title} description`,
			url: `https://${project || "example"}.toolforge.org/`,
			author: [{ name: "Ada" }]
		},
		toolinfoSource: { sourceKind: "toolsadmin" }
	};
}

test("entry builder prefers the correctly named record and includes unregistered projects", () => {
	const entries = buildToolinfoGeneratorEntries(
		[tool("legacy-example", "example", "Legacy"), tool("toolforge-example", "example", "Exact")],
		{
			toolforgeProjects: [
				{ name: "example", developerUsernames: ["ada"] },
				{ name: "new-project", developerUsernames: ["ada-alt"] }
			]
		}
	);

	assert.equal(entries.length, 2);
	assert.equal(entries.find((entry) => entry.projectName === "example").toolName, "toolforge-example");
	assert.equal(entries.find((entry) => entry.projectName === "new-project").sourceKind, "unregistered");
	assert.deepEqual(entries.find((entry) => entry.projectName === "new-project").developerUsernames, ["ada-alt"]);
});

test("workspace renders every core field, prefills identity, validates, copies, and resets", async () => {
	const entries = buildToolinfoGeneratorEntries([tool("toolforge-example", "example", "Example")], {
		toolforgeProjects: [{ name: "example", developerUsernames: ["ada"] }]
	});
	const workspace = toolinfoGeneratorWorkspace(entries, { displayName: "Ada", wikiUsername: "AdaWiki" });
	document.body.innerHTML = workspace.html;
	workspace.mount();

	const choice = document.querySelector("[data-toolinfo-choice]");
	choice.value = entries[0].key;
	choice.dispatchEvent(new Event("change", { bubbles: true }));

	assert.equal(document.querySelector('[data-toolinfo-field="name"]').value, "toolforge-example");
	assert.equal(document.querySelector('[data-toolinfo-field="author-wiki"]').value, "AdaWiki");
	assert.equal(document.querySelector('[data-toolinfo-field="author-developer"]').value, "ada");
	for (const field of CORE_TOOLINFO_FIELDS) {
		const renderedField = field === "author" ? "author-name" : field;
		assert.ok(document.querySelector(`[data-toolinfo-field="${renderedField}"]`), `${field} should be editable`);
	}
	assert.match(document.querySelector("[data-toolinfo-preview]").value, /"name": "toolforge-example"/);
	assert.match(document.querySelector("[data-toolinfo-validation]").textContent, /Valid for schema 1.2.2/);

	document.querySelector("[data-toolinfo-copy]").click();
	await Promise.resolve();
	assert.match(writeText.mock.calls[0][0], /"wiki_username": "AdaWiki"/);

	const description = document.querySelector('[data-toolinfo-field="description"]');
	description.value = "";
	description.dispatchEvent(new Event("input", { bubbles: true }));
	assert.equal(document.querySelector("[data-toolinfo-copy]").disabled, true);
	assert.match(document.querySelector("[data-toolinfo-validation]").textContent, /description is required/);

	document.querySelector("[data-toolinfo-reset]").click();
	assert.equal(document.querySelector('[data-toolinfo-field="description"]').value, "Example description");
});

test("workspace adds and removes structured author rows", () => {
	const entries = buildToolinfoGeneratorEntries([tool("plain-tool", "")], {});
	const workspace = toolinfoGeneratorWorkspace(entries, { displayName: "Ada", wikiUsername: "Ada" });
	document.body.innerHTML = workspace.html;
	workspace.mount();
	const choice = document.querySelector("[data-toolinfo-choice]");
	choice.value = entries[0].key;
	choice.dispatchEvent(new Event("change", { bubbles: true }));

	document.querySelector("[data-toolinfo-author-add]").click();
	assert.equal(document.querySelectorAll("[data-toolinfo-author]").length, 2);
	document.querySelectorAll("[data-toolinfo-author-remove]")[1].click();
	assert.equal(document.querySelectorAll("[data-toolinfo-author]").length, 1);
});
