# SPDX-License-Identifier: GPL-3.0-or-later
"""The shape gate decides which free-text labels may be resolved at all.

Every case below is a real label observed in the production catalog, so this
file doubles as the record of what the gate was calibrated against.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend.people_policy import is_handle_shaped  # noqa: E402

# High-entropy, self-chosen: resolving these is close to risk-free.
HANDLES = [
    "0xDeadbeef",
    "1234qwer1234qwer4",
    "-jem-",
    "1F616EMO",
    "20after4",
    "01tonythomas",
    "1Veertje",
    "~aanzx",
    ".avgas",
    "-chanakyakdas",
    "4shadoww",
    "A-NEUN",
    "Abbasidaniyal",
    "Abhishek02bhardwaj",
    "1250metersdeep",
    "AFigureOfBlue",
]

# Low-entropy human names: a real account may exist and have nothing to do
# with the tool, so these must never be resolved automatically.
NAMES = [
    "Aaron Liu",
    "Abdullah AL Shohag",
    "Abdulfatai Mustapha",
    "Abhishek Bhardwaj",
    "Abdelilah Jalal",
    "Aditya Kumar",
    "A Chinese user",
    "A particle for world to form",
]

# Single-token labels that could be a surname or a handle. The gate admits
# them deliberately: they are the bulk of the population, and the corroboration
# rules downstream are what stop a bare match from publishing anything.
AMBIGUOUS_ADMITTED = ["Abartov", "Aafi", "Abián", "Emijrp", "Legoktm"]


@pytest.mark.parametrize("label", HANDLES)
def test_self_chosen_handles_are_admitted(label):
    assert is_handle_shaped(label) is True


@pytest.mark.parametrize("label", NAMES)
def test_human_names_are_refused(label):
    assert is_handle_shaped(label) is False


@pytest.mark.parametrize("label", AMBIGUOUS_ADMITTED)
def test_single_token_labels_are_admitted_by_design(label):
    assert is_handle_shaped(label) is True


def test_a_multi_word_label_needs_a_non_name_character():
    # "Aditya Suthar07" carries a digit, so it is a handle someone typed with
    # a space; "Aditya Suthar" is indistinguishable from a name.
    assert is_handle_shaped("Aditya Suthar07") is True
    assert is_handle_shaped("Aditya Suthar") is False


def test_wikitext_and_markup_are_refused():
    # R3 extracts these into structured handles before they can reach here;
    # anything still carrying markup is not a username.
    assert is_handle_shaped("[[User:Emijrp]] and [[User:The Photographer]]") is False
    assert is_handle_shaped("someone@example.org") is False
    assert is_handle_shaped("https://example.org/u/ada") is False


def test_prose_words_disqualify_a_label_even_with_symbols():
    assert is_handle_shaped("Ada and Grace-99") is False
    assert is_handle_shaped("Tool users") is False


def test_lengths_outside_a_username_are_refused():
    assert is_handle_shaped("") is False
    assert is_handle_shaped("x") is False
    assert is_handle_shaped("a" * 86) is False
    assert is_handle_shaped("a" * 85) is True


def test_surrounding_whitespace_never_changes_the_verdict():
    assert is_handle_shaped("  0xDeadbeef  ") is True
    assert is_handle_shaped("Aaron   Liu") is False


def test_the_gate_is_pure_and_total_for_odd_input():
    # Called over untrusted catalog text, so it must not raise on anything.
    for value in (None, "", "   ", "\n\t", "…", "🙂", 12345):
        assert isinstance(is_handle_shaped(value), bool)
