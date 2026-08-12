# SPDX-License-Identifier: GPL-3.0-or-later
"""Authenticated, replay-safe external account reconnection proofs."""

from __future__ import annotations

import hashlib
import secrets
import shlex
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend import identity_graph, people_index, public_identity
from backend.models import AccountLinkChallenge, PersonAccountBinding, ToolforgeAccountProjection, User, utcnow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

CHALLENGE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
MAX_SIGNATURE_BYTES = 16_384
SIGNATURE_NAMESPACE = "toolhub-evolved"
SSH_KEYGEN = "/usr/bin/ssh-keygen"
TOOLSADMIN_SSH_KEYS_URL = "https://toolsadmin.wikimedia.org/profile/settings/ssh-keys/"
TOOLSADMIN_PROFILE_URL = "https://toolsadmin.wikimedia.org/profile/"
ERROR_ACCOUNT_NOT_FOUND = "Toolforge account was not found or is ambiguous"
ERROR_ALREADY_CONNECTED = "This Toolforge account is already connected"
ERROR_CONNECTED_ELSEWHERE = "This Toolforge account is connected to another person"
ERROR_CHALLENGE_NOT_FOUND = "Account-link challenge was not found"
ERROR_CHALLENGE_USED = "Account-link challenge has already been used"
ERROR_CHALLENGE_EXPIRED = "Account-link challenge has expired"
ERROR_TOO_MANY_ATTEMPTS = "Account-link challenge has too many failed attempts"
ERROR_CHALLENGE_MISMATCH = "Account-link challenge does not match"
ERROR_SIGNATURE_INVALID = "SSH signature was not valid for this Toolforge account"
ERROR_ACCOUNT_UNAVAILABLE = "Toolforge account is no longer available"

KeyLoader = Callable[[str], list[str]]
SignatureVerifier = Callable[[str, str, list[str]], bool]


class AccountLinkError(ValueError):
    """A safe user-facing account-link failure."""


def _error(message: str) -> AccountLinkError:
    return AccountLinkError(message)


def _clean(value: Any, limit: int = 255) -> str:  # noqa: ANN401 - request/LDAP data
    return str(value or "").strip()[:limit]


def _person_for_user(session: Session, user: User):  # noqa: ANN202 - SQLAlchemy model type is evident
    return people_index.link_user(session, user)


def link_state(session: Session, user: User) -> dict[str, Any]:
    """Describe verified and candidate accounts for the signed-in person."""
    person = _person_for_user(session, user)
    rows = list(
        session.execute(
            select(PersonAccountBinding).where(
                PersonAccountBinding.person_id == person.id,
                PersonAccountBinding.revoked_at.is_(None),
            )
        ).scalars()
    )
    bindings = [
        {
            "provider": row.provider,
            "externalId": row.external_id,
            "status": row.status,
            "proofMethod": row.proof_method,
            "confidence": row.confidence,
            "verifiedAt": row.verified_at.isoformat() + "Z" if row.verified_at else None,
        }
        for row in rows
    ]
    candidates = []
    for row in rows:
        if row.provider != identity_graph.PROVIDER_TOOLFORGE or row.status != identity_graph.STATUS_CANDIDATE:
            continue
        account = session.get(ToolforgeAccountProjection, row.external_id)
        if account is not None:
            candidates.append(
                {
                    "provider": "toolforge",
                    "externalId": account.uid_number,
                    "username": account.uid,
                    "status": row.status,
                    "proofMethod": row.proof_method,
                }
            )
    return {
        "personId": person.public_id,
        "bindings": bindings,
        "candidates": candidates,
        "upstreamRepair": {
            "profileUrl": TOOLSADMIN_PROFILE_URL,
            "sshKeysUrl": TOOLSADMIN_SSH_KEYS_URL,
        },
        "proofMethods": {
            "toolforgeSul": True,
            "toolforgeSshSignature": True,
            "toolControl": False,
        },
    }


def _account_by_username(session: Session, username: str) -> ToolforgeAccountProjection:
    normalized = _clean(username).casefold()
    rows = list(
        session.execute(
            select(ToolforgeAccountProjection).where(
                ToolforgeAccountProjection.normalized_uid == normalized,
                ToolforgeAccountProjection.disabled.is_(False),
            )
        ).scalars()
    )
    if len(rows) != 1:
        raise _error(ERROR_ACCOUNT_NOT_FOUND)
    return rows[0]


def start_toolforge_challenge(session: Session, user: User, username: str) -> dict[str, Any]:
    """Issue one challenge bound to this user and immutable Toolforge account."""
    account = _account_by_username(session, username)
    person = _person_for_user(session, user)
    existing = identity_graph.verified_person_for_account(
        session, identity_graph.PROVIDER_TOOLFORGE, account.uid_number
    )
    if existing is not None:
        if existing.id == person.id:
            raise _error(ERROR_ALREADY_CONNECTED)
        raise _error(ERROR_CONNECTED_ELSEWHERE)
    challenge_id = secrets.token_urlsafe(24)[:64]
    nonce = secrets.token_urlsafe(32)
    expires_at = utcnow() + CHALLENGE_TTL
    challenge = "\n".join(
        [
            "toolhub-evolved-account-link-v1",
            f"challenge-id:{challenge_id}",
            f"toolhub-user-id:{user.wm_sub}",
            f"person-id:{person.public_id}",
            f"toolforge-uid-number:{account.uid_number}",
            f"nonce:{nonce}",
            f"expires:{expires_at.isoformat()}Z",
        ]
    )
    session.add(
        AccountLinkChallenge(
            id=challenge_id,
            user_id=user.id,
            provider=identity_graph.PROVIDER_TOOLFORGE,
            external_id=account.uid_number,
            challenge_hash=hashlib.sha256(challenge.encode()).hexdigest(),
            expires_at=expires_at,
            attempts=0,
        )
    )
    return {
        "challengeId": challenge_id,
        "provider": "toolforge",
        "username": account.uid,
        "externalId": account.uid_number,
        "challenge": challenge,
        "expiresAt": expires_at.isoformat() + "Z",
        "namespace": SIGNATURE_NAMESPACE,
        "command": (
            f"printf %s {shlex.quote(challenge)} | ssh-keygen -Y sign -f ~/.ssh/id_ed25519 -n {SIGNATURE_NAMESPACE}"
        ),
    }


def load_toolforge_ssh_keys(uid_number: str) -> list[str]:
    """Read public SSH keys for exactly one immutable developer account."""
    if (
        public_identity.Connection is None
        or public_identity.Server is None
        or public_identity.escape_filter_chars is None
    ):
        return []
    escaped = public_identity.escape_filter_chars(_clean(uid_number, 64))
    server = public_identity.Server(
        public_identity.TOOLFORGE_LDAP_URI,
        use_ssl=True,
        connect_timeout=public_identity.TOOLFORGE_LDAP_TIMEOUT,
    )
    connection = public_identity.Connection(
        server,
        receive_timeout=public_identity.TOOLFORGE_LDAP_TIMEOUT,
        auto_bind=True,
        read_only=True,
    )
    try:
        connection.search(
            public_identity.TOOLFORGE_LDAP_BASE_DN,
            f"(&(objectClass=posixAccount)(uidNumber={escaped}))",
            attributes=["uidNumber", "sshPublicKey"],
            size_limit=2,
        )
        if len(connection.entries) != 1:
            return []
        row: Mapping[str, Any] = connection.entries[0].entry_attributes_as_dict
        resolved = row.get("uidNumber") or []
        resolved_id = _clean(resolved[0] if isinstance(resolved, (list, tuple)) and resolved else resolved, 64)
        if resolved_id != uid_number:
            return []
        values = row.get("sshPublicKey") or []
        return [_clean(value, 4096) for value in values if _clean(value, 4096)] if isinstance(values, list) else []
    finally:
        connection.unbind()


def verify_ssh_signature(challenge: str, signature: str, public_keys: list[str]) -> bool:
    """Verify an OpenSSH SSHSIG against any key published for the account."""
    safe_keys = [
        key
        for key in public_keys
        if "\n" not in key
        and "\r" not in key
        and key.split(" ", 1)[0]
        in {"ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "sk-ssh-ed25519@openssh.com"}
    ]
    if not safe_keys or not signature.startswith("-----BEGIN SSH SIGNATURE-----"):
        return False
    if len(signature.encode()) > MAX_SIGNATURE_BYTES or not Path(SSH_KEYGEN).is_file():
        return False
    with tempfile.TemporaryDirectory(prefix="toolhub-account-link-") as directory:
        allowed_path = Path(directory) / "allowed_signers"
        signature_path = Path(directory) / "signature"
        allowed_path.write_text("".join(f"toolhub-evolved {key}\n" for key in safe_keys), encoding="utf-8")
        signature_path.write_text(signature, encoding="utf-8")
        result = subprocess.run(  # noqa: S603 - fixed executable and argument vector
            [
                SSH_KEYGEN,
                "-Y",
                "verify",
                "-f",
                allowed_path,
                "-I",
                "toolhub-evolved",
                "-n",
                SIGNATURE_NAMESPACE,
                "-s",
                signature_path,
            ],
            input=challenge,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    return result.returncode == 0


def complete_toolforge_challenge(  # noqa: PLR0913 - injected proof providers keep tests deterministic
    session: Session,
    user: User,
    *,
    challenge_id: str,
    challenge: str,
    signature: str,
    key_loader: KeyLoader = load_toolforge_ssh_keys,
    verifier: SignatureVerifier = verify_ssh_signature,
) -> dict[str, Any]:
    """Verify, consume, and turn one challenge into a durable account binding."""
    row = session.get(AccountLinkChallenge, _clean(challenge_id, 64))
    if row is None or row.user_id != user.id or row.provider != identity_graph.PROVIDER_TOOLFORGE:
        raise _error(ERROR_CHALLENGE_NOT_FOUND)
    if row.completed_at is not None:
        raise _error(ERROR_CHALLENGE_USED)
    if row.expires_at <= utcnow():
        raise _error(ERROR_CHALLENGE_EXPIRED)
    if row.attempts >= MAX_ATTEMPTS:
        raise _error(ERROR_TOO_MANY_ATTEMPTS)
    if hashlib.sha256(challenge.encode()).hexdigest() != row.challenge_hash:
        row.attempts += 1
        row.last_error = "challenge_mismatch"
        raise _error(ERROR_CHALLENGE_MISMATCH)
    public_keys = key_loader(row.external_id)
    if not verifier(challenge, signature, public_keys):
        row.attempts += 1
        row.last_error = "signature_invalid"
        raise _error(ERROR_SIGNATURE_INVALID)
    account = session.get(ToolforgeAccountProjection, row.external_id)
    if account is None or account.disabled:
        raise _error(ERROR_ACCOUNT_UNAVAILABLE)
    person = _person_for_user(session, user)
    binding = identity_graph.bind_toolforge_account(
        session,
        account=account,
        person=person,
        proof_method=identity_graph.PROOF_AUTHENTICATED,
        confidence=100,
        evidence={
            "challengeId": row.id,
            "toolforgeUidNumber": account.uid_number,
            "verification": "openssh_sshsig",
        },
        verified_by_user_id=user.id,
    )
    row.completed_at = utcnow()
    row.last_error = None
    identity_graph.synchronize(session)
    return {
        "ok": True,
        "provider": binding.provider,
        "externalId": binding.external_id,
        "status": binding.status,
        "proofMethod": binding.proof_method,
    }
