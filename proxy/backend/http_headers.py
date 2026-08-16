# SPDX-License-Identifier: GPL-3.0-or-later
"""Validation for outbound HTTP header values that come from configuration.

These values are Toolforge environment variables, edited by hand and routinely
wrapped across lines. `str.strip()` removes only the outer whitespace, so an
interior newline survives all the way into `requests`, which rejects it far
from the configuration that caused it and embeds the offending value in the
exception message. Validate next to the configuration instead, the way
`public_base_url()` already validates its origin.
"""

from __future__ import annotations

import re

#: Runs of ASCII whitespace, including the newlines a wrapped envvar leaves behind.
WHITESPACE_RUN = re.compile(r"\s+")
#: Control characters that survive whitespace folding; never silently repairable.
CONTROL = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]")


def clean_header_value(name: str, value: str) -> str:
    """Return a descriptive header value safe to transmit, folding wrapped configuration.

    Interior whitespace runs collapse to one space: a contact string wrapped
    across lines in the envvar editor means the single-line string it was
    written as, so repairing it preserves operator intent. Other control
    characters carry no such intent and raise instead.

    The error names the variable and never quotes its value, so the message
    stays safe to surface to a caller.
    """
    folded = WHITESPACE_RUN.sub(" ", value).strip()
    if CONTROL.search(folded):
        message = f"{name} contains control characters"
        raise ValueError(message)
    return folded


def clean_secret_header_value(name: str, value: str) -> str:
    """Return a credential safe to transmit, refusing any interior whitespace.

    A credential is deliberately not repaired the way a contact string is:
    folding whitespace inside a token would transmit something other than what
    was configured, and the value must never reach `requests`, whose
    `InvalidHeader` message quotes the header value verbatim.

    Outer whitespace is still stripped, since a trailing newline from a heredoc
    or editor is not part of the secret.
    """
    stripped = value.strip()
    if not stripped:
        return ""
    if WHITESPACE_RUN.search(stripped) or CONTROL.search(stripped):
        message = f"{name} contains whitespace or control characters"
        raise ValueError(message)
    return stripped
