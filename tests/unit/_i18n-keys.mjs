// SPDX-License-Identifier: GPL-3.0-or-later
// Make a message key observable to the unit suite.
//
// `t(key, fallback)` returns the fallback whenever the catalog has no entry for
// the key, and this suite installs no catalog, so the key selected nothing:
// every key rendered the same English. A passing run never notices, but it
// leaves both halves of the call unfalsifiable under mutation testing, because
// rewriting `t("facetGroup.keywords", "Keywords")` as `t("", "Keywords")`
// produces a byte-identical page. Roughly 4,000 call sites went that way when
// the English strings moved behind `t()`.
//
// Handing the resolver the generated catalog's key set puts the key back into
// the output: a key that catalog cannot translate renders as a marker instead
// of the English, so the assertions already written against that English fail.
// No catalog is installed, so every known key still renders its fallback and
// nothing else about the suite changes.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { setKnownMessageKeys } from "../../public_html/lib/core/i18n.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
/** Read rather than imported: an import attribute for JSON is still gated
 *  behind a flag on some of the Node versions this suite runs under. */
const CATALOG = JSON.parse(readFileSync(path.join(ROOT, "public_html/i18n/en.json"), "utf8"));

/** `@metadata` is translatewiki bookkeeping, not a message. */
export const CATALOG_KEYS = Object.keys(CATALOG).filter((key) => !key.startsWith("@"));

setKnownMessageKeys(CATALOG_KEYS);
