#!/usr/bin/env python3
# ruff: noqa: T201
"""Create and validate Wikimedia Toolinfo 1.2.2 records using only stdlib."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA = "/toolinfo/1.2.2"
MAX_PERSON_LENGTH = 255
MAX_LANGUAGE_LENGTH = 16
MAX_URL_LENGTH = 2047
REQUIRED = ("name", "title", "description", "url")
TOOL_TYPES = {
    "web app",
    "desktop app",
    "bot",
    "gadget",
    "user script",
    "command line tool",
    "coding framework",
    "lua module",
    "template",
    "other",
}
CORE_FIELDS = {
    "_schema",
    "_language",
    "name",
    "title",
    "subtitle",
    "description",
    "url",
    "url_alternates",
    "author",
    "repository",
    "openhub_id",
    "bot_username",
    "deprecated",
    "replaced_by",
    "experimental",
    "for_wikis",
    "icon",
    "license",
    "sponsor",
    "available_ui_languages",
    "technology_used",
    "tool_type",
    "api_url",
    "developer_docs_url",
    "user_docs_url",
    "feedback_url",
    "privacy_policy_url",
    "translate_url",
    "bugtracker_url",
    "keywords",
}
ANNOTATION_FIELDS = {"audiences", "tasks", "content_types", "subject_domains", "wikidata_qid"}
URL_FIELDS = {"url", "repository", "replaced_by", "icon", "api_url", "translate_url", "bugtracker_url"}
MULTILINGUAL_URL_FIELDS = {
    "url_alternates",
    "developer_docs_url",
    "user_docs_url",
    "feedback_url",
    "privacy_policy_url",
}
STRING_LIMITS = {
    "_schema": 32,
    "_language": 16,
    "name": 255,
    "title": 255,
    "subtitle": 255,
    "description": 65535,
    "openhub_id": 255,
    "bot_username": 255,
    "license": 255,
    "tool_type": 32,
    "keywords": 2047,
}
LANGUAGE_RE = re.compile(r"^(x-.*|[A-Za-z]{2,3}(-.*)?)$")
WIKI_RE = re.compile(
    r"^(\*|(.*)?\.?(mediawiki|wiktionary|wiki(pedia|quote|books|source|news|versity|data|voyage|media))\.org)$",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def text(value: Any) -> str:  # noqa: ANN401 - untrusted JSON
    return str(value or "").strip()


def is_http_url(value: Any) -> bool:  # noqa: ANN401 - untrusted JSON
    parsed = urlparse(text(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def values(value: Any) -> list[Any]:  # noqa: ANN401 - untrusted JSON
    if value in (None, "", []):
        return []
    return value if isinstance(value, list) else [value]


def validate_person(author: Any, location: str) -> list[str]:  # noqa: ANN401 - untrusted JSON
    if isinstance(author, str):
        return [] if text(author) else [f"{location}.name is required"]
    if not isinstance(author, dict):
        return [f"{location} must be a string or object"]
    errors = []
    if not text(author.get("name")):
        errors.append(f"{location}.name is required")
    unknown = set(author) - {"name", "wiki_username", "developer_username", "email", "url"}
    if unknown:
        errors.append(f"{location} has unsupported fields: {', '.join(sorted(unknown))}")
    errors.extend(
        f"{location}.{field} must be {MAX_PERSON_LENGTH} characters or fewer"
        for field in ("name", "wiki_username", "developer_username", "email")
        if len(text(author.get(field))) > MAX_PERSON_LENGTH
    )
    if author.get("email") and not EMAIL_RE.fullmatch(text(author["email"])):
        errors.append(f"{location}.email is invalid")
    if author.get("url") and not is_http_url(author["url"]):
        errors.append(f"{location}.url must be an http(s) URL")
    if len(text(author.get("url"))) > MAX_URL_LENGTH:
        errors.append(f"{location}.url must be {MAX_URL_LENGTH} characters or fewer")
    return errors


def validate_multilingual(value: Any, location: str) -> list[str]:  # noqa: ANN401 - untrusted JSON
    errors = []
    for index, item in enumerate(values(value)):
        item_location = f"{location}[{index}]"
        if isinstance(item, str):
            if not is_http_url(item):
                errors.append(f"{item_location} must be an http(s) URL")
            if len(item) > MAX_URL_LENGTH:
                errors.append(f"{item_location} must be {MAX_URL_LENGTH} characters or fewer")
            continue
        if not isinstance(item, dict) or set(item) != {"language", "url"}:
            errors.append(f"{item_location} must contain exactly language and url")
            continue
        if not LANGUAGE_RE.fullmatch(text(item["language"])):
            errors.append(f"{item_location}.language is invalid")
        if len(text(item["language"])) > MAX_LANGUAGE_LENGTH:
            errors.append(f"{item_location}.language must be {MAX_LANGUAGE_LENGTH} characters or fewer")
        if not is_http_url(item["url"]):
            errors.append(f"{item_location}.url must be an http(s) URL")
        if len(text(item["url"])) > MAX_URL_LENGTH:
            errors.append(f"{item_location}.url must be {MAX_URL_LENGTH} characters or fewer")
    return errors


def validate_record(  # noqa: C901, PLR0912 - mirrors independent JSON Schema constraints.
    record: Any,  # noqa: ANN401 - untrusted JSON
    *,
    project: str = "",
    location: str = "record",
) -> tuple[list[str], list[str]]:
    if not isinstance(record, dict):
        return [f"{location} must be a JSON object"], []
    errors = []
    warnings = []
    if record.get("_schema") != SCHEMA:
        errors.append(f"{location}._schema must be {SCHEMA}")
    errors.extend(f"{location}.{field} is required" for field in REQUIRED if not text(record.get(field)))
    if project and record.get("name") != f"toolforge-{project}":
        errors.append(f"{location}.name must be toolforge-{project}")
    errors.extend(
        f"{location}.{field} must be {limit} characters or fewer"
        for field, limit in STRING_LIMITS.items()
        if len(text(record.get(field))) > limit
    )
    errors.extend(
        f"{location}.{field} is a Toolhub annotation and does not belong in core toolinfo"
        for field in sorted(set(record) & ANNOTATION_FIELDS)
    )
    errors.extend(
        f"{location}.{field} must be {MAX_URL_LENGTH} characters or fewer"
        for field in URL_FIELDS
        if len(text(record.get(field))) > MAX_URL_LENGTH
    )
    unknown = set(record) - CORE_FIELDS - ANNOTATION_FIELDS
    if unknown:
        warnings.append(f"{location} has unknown fields: {', '.join(sorted(unknown))}")
    errors.extend(
        f"{location}.{field} must be an http(s) URL"
        for field in URL_FIELDS
        if record.get(field) and not is_http_url(record[field])
    )
    if record.get("url_alternates") and not isinstance(record["url_alternates"], list):
        errors.append(f"{location}.url_alternates must be an array")
    for field in MULTILINGUAL_URL_FIELDS:
        errors.extend(validate_multilingual(record.get(field), f"{location}.{field}"))
    if record.get("icon") and not text(record["icon"]).startswith("https://commons.wikimedia.org/wiki/File:"):
        errors.append(f"{location}.icon must be a Commons File: page URL")
    if record.get("tool_type") and record["tool_type"] not in TOOL_TYPES:
        errors.append(f"{location}.tool_type is not a Toolinfo 1.2.2 value")
    errors.extend(
        f"{location}.{field} must be a boolean"
        for field in ("deprecated", "experimental")
        if field in record and not isinstance(record[field], bool)
    )
    if "author" in record and not isinstance(record["author"], str | list):
        errors.append(f"{location}.author must be a string or array")
    errors.extend(
        f"{location}.for_wikis contains invalid target {wiki!r}"
        for wiki in values(record.get("for_wikis"))
        if not WIKI_RE.fullmatch(text(wiki))
    )
    for field in ("sponsor", "technology_used"):
        for item in values(record.get(field)):
            if not isinstance(item, str):
                errors.append(f"{location}.{field} values must be strings")
            elif len(item) > MAX_PERSON_LENGTH:
                errors.append(f"{location}.{field} values must be {MAX_PERSON_LENGTH} characters or fewer")
    errors.extend(
        f"{location} has invalid language code {language!r}"
        for language in [record.get("_language", "en"), *values(record.get("available_ui_languages"))]
        if language != "*" and not LANGUAGE_RE.fullmatch(text(language))
    )
    for index, author in enumerate(values(record.get("author"))):
        errors.extend(validate_person(author, f"{location}.author[{index}]"))
    if record.get("replaced_by") and not record.get("deprecated"):
        errors.append(f"{location}.replaced_by requires deprecated=true")
    if "keywords" in record:
        warnings.append(f"{location}.keywords is deprecated in Toolinfo 1.2.2")
    return errors, warnings


def load_records(path: Path) -> list[Any]:
    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    return payload if isinstance(payload, list) else [payload]


def check(args: argparse.Namespace) -> int:
    try:
        records = load_records(args.path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    errors = []
    warnings = []
    for index, record in enumerate(records):
        record_errors, record_warnings = validate_record(
            record,
            project=args.toolforge_project if len(records) == 1 else "",
            location=f"record[{index}]",
        )
        errors.extend(record_errors)
        warnings.extend(record_warnings)
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"OK: {args.path} contains {len(records)} valid Toolinfo 1.2.2 record(s)")
    return 0


def create(args: argparse.Namespace) -> int:
    if args.output.exists() and not args.force:
        print(f"ERROR: refusing to overwrite {args.output}; edit it or pass --force", file=sys.stderr)
        return 1
    author = {"name": args.author_name}
    if args.wiki_username:
        author["wiki_username"] = args.wiki_username
    if args.developer_username:
        author["developer_username"] = args.developer_username
    record: dict[str, Any] = {
        "_schema": SCHEMA,
        "_language": "en",
        "name": f"toolforge-{args.toolforge_project}",
        "title": args.title,
        "description": args.description,
        "url": args.url,
        "author": [author],
        "for_wikis": ["*"],
        "available_ui_languages": ["en"],
    }
    for field in ("repository", "license", "tool_type"):
        value = getattr(args, field)
        if value:
            record[field] = value
    errors, warnings = validate_record(record, project=args.toolforge_project)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"WARNING: {warning}")
    args.output.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Created {args.output}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    check_parser = commands.add_parser("check", help="validate an existing toolinfo.json")
    check_parser.add_argument("path", type=Path)
    check_parser.add_argument("--toolforge-project", default="")
    check_parser.set_defaults(run=check)

    create_parser = commands.add_parser("create", help="create a Toolforge toolinfo.json")
    create_parser.add_argument("--toolforge-project", required=True)
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--description", required=True)
    create_parser.add_argument("--url", required=True)
    create_parser.add_argument("--author-name", required=True)
    create_parser.add_argument("--wiki-username", default="")
    create_parser.add_argument("--developer-username", default="")
    create_parser.add_argument("--repository", default="")
    create_parser.add_argument("--license", default="")
    create_parser.add_argument("--tool-type", choices=sorted(TOOL_TYPES), default="")
    create_parser.add_argument("--output", type=Path, default=Path("toolinfo.json"))
    create_parser.add_argument("--force", action="store_true")
    create_parser.set_defaults(run=create)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
