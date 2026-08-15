# SPDX-License-Identifier: GPL-3.0-or-later
"""Facet vocabulary contracts across storage and public API surfaces."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import facet_names  # noqa: E402


def test_discovery_technology_names_are_unambiguous_and_compatible():
    assert facet_names.to_storage("technology") == "detected_technology"
    assert facet_names.to_storage("detected_technology") == "detected_technology"
    assert facet_names.to_storage("declared_technology") == "technology"
    assert facet_names.to_public("detected_technology") == "detected_technology"
    assert facet_names.to_public("technology") == "declared_technology"


def test_catalog_and_projection_vocabulary_preserve_toolhub_names():
    assert facet_names.CATALOG_PUBLIC_TO_STORAGE["technology"] == "technology"
    assert facet_names.PROJECTED_FIELD_TO_STORAGE["technology_used"] == "technology"
    assert facet_names.CATALOG_PUBLIC_TO_STORAGE["keywords"] == "keywords"
    assert facet_names.to_storage("keyword") == "keywords"


def test_unknown_discovery_names_are_rejected_in_both_directions():
    assert facet_names.to_storage("internal_future_signal") is None
    assert facet_names.to_public("internal_future_signal") is None


def test_detected_facets_are_identified_through_the_public_vocabulary():
    assert facet_names.is_detected(" detected_technology ") is True
    assert facet_names.is_detected("declared_technology") is False
