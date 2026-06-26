// SPDX-License-Identifier: GPL-3.0-or-later
// Vitest setup file (wired via vitest.config.mjs setupFiles): installs a working
// localStorage before every test. This build's happy-dom ships a non-functional
// localStorage, and store.js iterates Object.keys(localStorage), so stored keys
// must be enumerable own-properties — methods live on the prototype.
class MemStorage {
	getItem(key) {
		const k = String(key);
		return Object.prototype.hasOwnProperty.call(this, k) ? this[k] : null;
	}

	setItem(key, value) {
		this[String(key)] = String(value);
	}

	removeItem(key) {
		delete this[String(key)];
	}

	clear() {
		for (const k of Object.keys(this)) delete this[k];
	}

	key(index) {
		return Object.keys(this)[index] ?? null;
	}

	get length() {
		return Object.keys(this).length;
	}
}

export function installStorage() {
	const value = new MemStorage();
	Object.defineProperty(globalThis, "localStorage", { value, configurable: true, writable: true });
	if (globalThis.window) {
		Object.defineProperty(window, "localStorage", { value, configurable: true, writable: true });
	}
	return value;
}

installStorage();
