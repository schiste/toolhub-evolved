// SPDX-License-Identifier: GPL-3.0-or-later
// Which locales the language switcher can actually switch to.
//
// Deliberately separate from core/i18n.js. That module is imported by nearly
// every other one, so adding a dependency to it delays the whole app's module
// graph by a tick; keeping the catalog list here means shipping a translation
// touches only the switcher's graph.
import { SHIPPED_LOCALES } from "../../i18n/locales.js";
import { PSEUDO_LOCALE } from "./i18n.js";

/** Shipped catalogs plus the runtime-generated QA pseudolocale. */
export const AVAILABLE_LOCALES = [...SHIPPED_LOCALES, PSEUDO_LOCALE];
