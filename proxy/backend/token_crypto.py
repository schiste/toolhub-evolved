# SPDX-License-Identifier: GPL-3.0-or-later
"""Encryption at rest for stored official Toolhub OAuth grants.

The grants in `toolhub_tokens` are bearer credentials: anything holding one can
write to official Toolhub as that user. On Toolforge they live in ToolsDB, a
*shared* database instance, and they also land in every backup taken by the
runbook. Storing them as plaintext makes any read of that table — a stray dump,
a restored backup, a mis-scoped grant — equivalent to full account takeover for
every signed-in user, so they are sealed with Fernet (AES-128-CBC + HMAC).

Key material is derived from the app's session secret via HKDF with a distinct
info string, so a deployment that already sets TOOLHUB_SECRET_KEY needs no new
configuration. Operators who want to rotate the session key without
invalidating grants can set TOOLHUB_TOKEN_KEY to an independent value.

Rotating the key does not corrupt anything: unreadable ciphertext is treated as
"no grant" and the user simply re-authorizes (see backend.toolhub).
"""

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Stored values carry a version prefix so the format can change later and so
# `decrypt` can recognise pre-encryption rows. See `decrypt` for that path.
PREFIX = "v1:"
_HKDF_INFO = b"toolhub-evolved:oauth-grant-encryption"
_KEY_ENV = "TOOLHUB_TOKEN_KEY"

_fernet: Fernet | None = None


class GrantDecryptionError(RuntimeError):
    """A stored grant could not be decrypted with the configured key."""


def _derive_key(secret: str) -> bytes:
    """Derive a urlsafe-base64 Fernet key from arbitrary secret material."""
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO).derive(secret.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def configure(secret_key: str) -> None:
    """Set up the process-wide grant cipher (called from backend.register)."""
    global _fernet  # noqa: PLW0603 — module-level singleton, mirrors backend.db
    _fernet = Fernet(_derive_key(os.environ.get(_KEY_ENV) or secret_key))


def _cipher() -> Fernet:
    if _fernet is None:
        msg = "backend.token_crypto.configure() has not been called"
        raise RuntimeError(msg)
    return _fernet


def encrypt(value: str) -> str:
    """Seal one token for storage."""
    return PREFIX + _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(stored: str) -> str:
    """Open one stored token.

    Every stored grant is sealed. The pre-encryption plaintext tolerance that
    shipped alongside this module is gone: the rows it existed for were migrated,
    and an unsealed value now fails closed like any other unreadable one, so a
    row that somehow lost its prefix cannot be silently trusted as a live token.
    """
    try:
        return _cipher().decrypt(stored.removeprefix(PREFIX).encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        msg = "stored Toolhub grant could not be decrypted"
        raise GrantDecryptionError(msg) from exc
