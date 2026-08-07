# SPDX-License-Identifier: GPL-3.0-or-later
"""Public local-only directory of accounts registered with official Toolhub."""

from urllib.parse import urlencode

from flask import Blueprint, Response, jsonify, request

from backend import account_directory, db, security, v1
from backend import v1_common as common
from backend.sync import SOURCE_OFFICIAL, SYNC_OFFICIAL, clean_int

v1_accounts_bp = Blueprint("v1_accounts", __name__)
MAX_DIRECTORY_TEXT_LENGTH = 255


class InvalidAccountQueryError(ValueError):
    """Raised when an account-directory parameter is invalid."""


def _positive_arg(name: str, default: int, *, maximum: int | None = None) -> int:
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    value = clean_int(raw)
    if value is None or value < 1:
        message = f"{name} must be a positive integer"
        raise InvalidAccountQueryError(message)
    return min(value, maximum) if maximum is not None else value


def _page_url(page: int | None) -> str | None:
    if page is None:
        return None
    args = request.args.to_dict(flat=True)
    args["page"] = str(page)
    return f"{request.path}?{urlencode(args)}"


@v1_accounts_bp.route("/v1/accounts/")
def v1_accounts() -> Response:
    """Search the synchronized official account projection."""
    if security.read_rate_limited(request.remote_addr):
        return common.deny(v1.HTTP_TOO_MANY, "rate limit exceeded")
    query = str(request.args.get("q") or "").strip()
    group = str(request.args.get("group") or "").strip()
    ordering = str(request.args.get("ordering") or account_directory.ORDER_NAME).strip()
    if len(query) > MAX_DIRECTORY_TEXT_LENGTH:
        return common.bad("q must be 255 characters or fewer")
    if len(group) > MAX_DIRECTORY_TEXT_LENGTH:
        return common.bad("group must be 255 characters or fewer")
    if ordering not in account_directory.ORDERINGS:
        return common.bad("unsupported ordering")
    try:
        page = _positive_arg("page", 1)
        page_size = _positive_arg("page_size", 24, maximum=100)
    except InvalidAccountQueryError as exc:
        return common.bad(str(exc))
    with db.session_scope() as s:
        payload = account_directory.search_accounts(
            s,
            account_directory.AccountDirectoryQuery(
                query=query,
                page=page,
                page_size=page_size,
                group=group,
                ordering=ordering,
            ),
        )
    return jsonify(
        payload
        | {
            "next": _page_url(payload["nextPage"]),
            "previous": _page_url(payload["previousPage"]),
            "source": SOURCE_OFFICIAL,
            "syncStatus": SYNC_OFFICIAL,
            "canonicalAuthority": {"accounts": "toolhub"},
        }
    )


@v1_accounts_bp.route("/v1/accounts/<toolhub_user_id>/")
def v1_account(toolhub_user_id: str) -> Response:
    """Return one official account projection without an upstream request."""
    if security.read_rate_limited(request.remote_addr):
        return common.deny(v1.HTTP_TOO_MANY, "rate limit exceeded")
    with db.session_scope() as s:
        payload = account_directory.account_detail(s, toolhub_user_id)
    if payload is None:
        return common.deny(common.HTTP_NOT_FOUND, "account not found")
    return jsonify(
        payload
        | {
            "source": SOURCE_OFFICIAL,
            "syncStatus": SYNC_OFFICIAL,
            "canonicalAuthority": {"accounts": "toolhub"},
        }
    )
