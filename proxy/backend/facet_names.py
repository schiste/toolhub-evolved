# SPDX-License-Identifier: GPL-3.0-or-later
"""The single boundary between stored facet field names and public facet names.

WHY THIS MODULE EXISTS
----------------------
There are three vocabularies for the same concepts in this codebase, and only
two of them are ours:

1. **Upstream toolinfo names** (`for_wikis`, `technology_used`,
   `available_ui_languages`). Toolhub's schema. We do not own these and must
   not rename them — `/v1/catalog/tools/<name>/projection/` echoes them in
   `record` and `provenance` because matching upstream is the contract there.
2. **Storage names** — `CatalogFacetValue.field`. Internal. Free to change.
3. **Public facet names** — what `facet_tools`, `/v1/facets/`, and
   `list_facet_values` speak. Stable for clients.

(2) and (3) differ for four fields, and the original code expressed that as a
single dict consulted at each call site. That worked on the request side and
was forgotten on the other two: `list_facet_values` validated incoming types
against the *storage* side of the map, and matched-facet rows went out with
`CatalogFacetValue.field` verbatim. Clients ended up filtering with `api` and
getting `wikimedia_api` back.

The lesson was not that translation is wrong — it is that a boundary
implemented once per call site is a boundary that will be forgotten at the
next call site. So it lives here, as two functions, and every crossing calls
them.

WE DO NOT PROMISE STORAGE NAMES ARE STABLE
------------------------------------------
Storage names are not a frozen API and nothing here should be read as making
them one. The point is the opposite: because translation is total, storage
names can be renamed, split, or normalized without any client noticing. The
inconsistent pluralization below (`keywords` and `tasks` are plural, `wiki`
and `license` are singular) is exactly the kind of thing that is now cheap to
fix and invisible until someone does.

HOW TO ADD A FACET
------------------
Add one entry to `PUBLIC_TO_STORAGE` and put its public name in the right
family set. Everything else — REST filters, MCP input schemas, value listing,
matched-facet reporting — derives from those. Do not hardcode a storage name
in a route, a tool schema, or a response body.

`test_facet_name_boundary.py` holds this: it serializes every public payload
and fails if any storage-only name appears anywhere in one. That check is
surface-agnostic on purpose — a future API service that forgets to translate
trips it without anyone having to remember to extend the test.

THE TWO FAMILIES
----------------
Facets split by where the assertion comes from, and the split drives the
coverage caveat every response carries:

- **Detected** — extracted by scanning a tool's source, so they exist only for
  tools with a scanned repository. An empty result means "no *scanned* tool
  matches", never "no such tool exists".
- **Declared** — catalog metadata, present for the whole catalog. An empty
  result is about the catalog, not about scan coverage.

`technology` and `detected_technology` are deliberately both present and
deliberately not merged: one is what a tool's record claims it is built with,
the other is what the analyzer found in its code. They disagree often, and
which one a caller wants depends on whether they trust the claim or the
evidence.
"""

from types import MappingProxyType

# Public facet name -> CatalogFacetValue.field.
# Identity entries are not redundant: they declare that the public name is
# deliberate rather than an accident of storage, so renaming the storage side
# later is a one-line change here.
PUBLIC_TO_STORAGE = MappingProxyType(
    {
        # Detected family — scanned repositories only.
        "dependency": "dependency",
        "api": "wikimedia_api",
        "detected_technology": "detected_technology",
        # Declared family — whole catalog.
        "technology": "technology",
        "tool_type": "tool_type",
        "keyword": "keywords",
        "wiki": "wiki",
        "license": "license",
        "task": "tasks",
        "audience": "audiences",
        "ui_language": "ui_language",
    }
)

DETECTED_PUBLIC = frozenset({"dependency", "api", "detected_technology"})
DECLARED_PUBLIC = frozenset(PUBLIC_TO_STORAGE) - DETECTED_PUBLIC

STORAGE_TO_PUBLIC = MappingProxyType({storage: public for public, storage in PUBLIC_TO_STORAGE.items()})

# Storage names that are not also public names. These must never appear in a
# public response body; the boundary test asserts exactly that.
STORAGE_ONLY_NAMES = frozenset(set(STORAGE_TO_PUBLIC) - set(PUBLIC_TO_STORAGE))


def to_storage(public_name: str) -> str | None:
    """Map a client-supplied facet name to its stored field, or None if unknown.

    None means "not a facet this API exposes" and callers must reject the
    request rather than guessing — silently dropping an unrecognized filter
    would widen an AND query, which is the one failure mode the facet surface
    must never have.
    """
    return PUBLIC_TO_STORAGE.get(str(public_name or "").strip().casefold())


def to_public(storage_name: str) -> str | None:
    """Map a stored field back to its public name, or None if it is internal.

    None means the field is stored but deliberately not exposed. Callers
    building a response must omit it rather than falling back to the storage
    name — that fallback is what leaked names before.
    """
    return STORAGE_TO_PUBLIC.get(str(storage_name or "").strip().casefold())
