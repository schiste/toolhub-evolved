// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { afterAll, beforeEach, test } from "vitest";
import * as session from "../../public_html/lib/core/session.js";

beforeEach(() => {
	localStorage.clear();
	session.setAuthRender(() => {});
	session.setServerUser(null);
	session.applyExp(false);
});

afterAll(() => {
	session.setServerUser(null);
	session.applyExp(false);
});

test("no server user by default", () => {
	assert.equal(session.serverUserName(), null);
});

test("a real session takes over the identity and turns feature mode on", () => {
	let renders = 0;
	session.setAuthRender(() => {
		renders += 1;
	});
	session.setServerUser("Grace Hopper");
	assert.equal(session.serverUserName(), "Grace Hopper");
	assert.equal(session.USER.name, "Grace Hopper");
	assert.equal(session.expOn(), true);
	assert.equal(session.expStored(), true); // persisted so reloads keep it
	assert.equal(session.signedIn(), true);
	assert.equal(renders, 1);
});

test("a real session signs in even when the demo identity had opted out", () => {
	localStorage.setItem(session.AUTH_KEY, "out"); // demo "Log out" marker
	session.setServerUser("Grace Hopper");
	assert.equal(session.signedIn(), true); // the server session wins
});

test("clearing the server user returns to signed-out read-only mode without touching exp", () => {
	session.setServerUser("Grace Hopper");
	session.setServerUser(null);
	assert.equal(session.serverUserName(), null);
	assert.equal(session.USER.name, "");
	assert.equal(session.expOn(), true); // feature mode choice is left as-is
	assert.equal(session.signedIn(), false);
	localStorage.setItem(session.AUTH_KEY, "out");
	assert.equal(session.signedIn(), false);
});
