# SPDX-License-Identifier: GPL-3.0-or-later
"""Owned facet vocabularies and their storage boundary.

Toolhub record fields, Toolhub-compatible catalog query parameters, and the
Evolved discovery API are distinct public contracts. They share storage but
must not be conflated: notably, the discovery API historically used
``technology`` for analyzer-detected evidence while catalog search uses it for
declared ``technology_used`` metadata.

All crossings live here so storage names never become an accidental API and
each surface can preserve its own compatibility guarantees.
"""

from types import MappingProxyType

# Canonical names emitted by discovery REST and MCP responses.
DISCOVERY_CANONICAL_TO_STORAGE = MappingProxyType(
    {
        "dependency": "dependency",
        "api": "wikimedia_api",
        "detected_technology": "detected_technology",
        "declared_technology": "technology",
        "tool_type": "tool_type",
        "keyword": "keywords",
        "wiki": "wiki",
        "license": "license",
        "task": "tasks",
        "audience": "audiences",
        "ui_language": "ui_language",
    }
)

# Accepted request aliases. ``technology`` cannot change meaning without
# silently changing existing MCP and REST queries, so it remains detected.
DISCOVERY_ALIASES = MappingProxyType({"technology": "detected_technology"})
DISCOVERY_PUBLIC_TO_STORAGE = MappingProxyType({**DISCOVERY_CANONICAL_TO_STORAGE, **DISCOVERY_ALIASES})
DISCOVERY_STORAGE_TO_PUBLIC = MappingProxyType(
    {storage: public for public, storage in DISCOVERY_CANONICAL_TO_STORAGE.items()}
)

DETECTED_PUBLIC = frozenset({"dependency", "api", "detected_technology", "technology"})
DECLARED_PUBLIC = frozenset(DISCOVERY_CANONICAL_TO_STORAGE) - DETECTED_PUBLIC

# Toolhub-compatible local catalog reads preserve Toolhub's plural parameter
# names because browser URLs and API consumers already use them.
CATALOG_PUBLIC_TO_STORAGE = MappingProxyType(
    {
        "tool_type": "tool_type",
        "keywords": "keywords",
        "audiences": "audiences",
        "tasks": "tasks",
        "ui_language": "ui_language",
        "license": "license",
        "wiki": "wiki",
        "technology": "technology",
    }
)

# Projected Toolhub/toolinfo record field -> CatalogFacetValue.field.
PROJECTED_FIELD_TO_STORAGE = MappingProxyType(
    {
        "tool_type": "tool_type",
        "keywords": "keywords",
        "for_wikis": "wiki",
        "technology_used": "technology",
        "tasks": "tasks",
        "audiences": "audiences",
        "available_ui_languages": "ui_language",
        "license": "license",
    }
)

# Backwards-compatible module name for callers migrating from the original PR.
PUBLIC_TO_STORAGE = DISCOVERY_PUBLIC_TO_STORAGE


def to_storage(public_name: str) -> str | None:
    """Map a discovery request name to storage, including stable aliases."""
    return DISCOVERY_PUBLIC_TO_STORAGE.get(str(public_name or "").strip().casefold())


def to_public(storage_name: str) -> str | None:
    """Map storage to the canonical discovery response name."""
    return DISCOVERY_STORAGE_TO_PUBLIC.get(str(storage_name or "").strip().casefold())


def is_detected(public_name: str) -> bool:
    """Whether a discovery name is limited to source-analysis coverage."""
    return str(public_name or "").strip().casefold() in DETECTED_PUBLIC
