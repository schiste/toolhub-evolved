# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only normalization of Evolved skills for the MCP transport.

The canonical Toolhub catalog remains a tool catalog.  Evolved skill metadata
is therefore read as an optional extension from a canonical record and never
participates in tool search, facets, or tool serialization.  This module is
the one boundary between the several metadata shapes currently accepted by
Evolved and the single ``io.modelcontextprotocol/skills`` wire shape.

Resource bodies are deliberately optional in the catalog record.  The evolved
manifest normally carries only size and digest information; a later resource
cache can provide the bytes without changing the MCP serializers.  Test and
small local catalogs may carry an inline ``content``/``text`` value, which is
also useful while the ingestion lane is being built.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from dataclasses import dataclass
from typing import Any, NoReturn
from urllib.parse import quote, unquote, urlsplit

from sqlalchemy import select

from backend import db
from backend.models import CanonicalToolCache

SKILLS_EXTENSION = "io.modelcontextprotocol/skills"
EVOLVED_TOOLINFO_SCHEMA = "/toolinfo/evolved/1.0.0"
EVOLVED_CATALOG_TYPE = "evolved-catalog"
SKILL_ENTRYPOINT = "SKILL.md"
MAX_SKILLS_PAGE = 50
MAX_RESOURCES_PER_SKILL = 512
MAX_SKILL_BYTES = 16 * 1024 * 1024
MAX_URI_LENGTH = 2048
MIN_URI_SEGMENTS = 2
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MIME_FALLBACK = "application/octet-stream"


class InvalidSkillError(ValueError):
    """A candidate does not satisfy the Evolved/MCP skill contract."""


def _invalid(message: str) -> NoReturn:
    raise InvalidSkillError(message)


@dataclass(frozen=True)
class SkillResource:
    """One addressable skill file and its optional locally cached bytes."""

    uri: str
    name: str
    mime_type: str
    size: int | None
    digest: str | None
    content: bytes | None
    description: str = ""

    def manifest(self) -> dict[str, Any]:
        """Return the compact resource entry required by ``skills/list``."""
        payload: dict[str, Any] = {"uri": self.uri}
        if self.digest is not None:
            payload["digest"] = self.digest
        if self.size is not None:
            payload["size"] = self.size
        return payload

    def listing(self) -> dict[str, Any]:
        """Return standard MCP resource metadata without exposing file bytes."""
        payload: dict[str, Any] = {
            "uri": self.uri,
            "name": self.name,
            "mimeType": self.mime_type,
        }
        if self.description:
            payload["description"] = self.description
        if self.size is not None:
            payload["size"] = self.size
        if self.digest is not None:
            payload["_meta"] = {f"{SKILLS_EXTENSION}/digest": self.digest}
        return payload


@dataclass(frozen=True)
class SkillEntry:
    """A normalized skill entry; content remains available only per resource."""

    uri: str
    frontmatter: dict[str, Any]
    resources: tuple[SkillResource, ...] | str
    artifact_id: str
    source: dict[str, Any]
    evolved: dict[str, Any]
    catalog_metadata: dict[str, Any]

    def public_entry(self) -> dict[str, Any]:
        """Return the extension entry shared by ``skills/list`` and ``get``."""
        manifest: list[dict[str, Any]] | str
        if isinstance(self.resources, str):
            manifest = self.resources
        else:
            manifest = [resource.manifest() for resource in self.resources]
        payload: dict[str, Any] = {
            "uri": self.uri,
            "frontmatter": dict(self.frontmatter),
            "resources": manifest,
        }
        metadata: dict[str, Any] = {}
        if self.artifact_id:
            metadata[f"{SKILLS_EXTENSION}/artifactId"] = self.artifact_id
        if self.source:
            metadata[f"{SKILLS_EXTENSION}/source"] = dict(self.source)
        if self.evolved:
            metadata[f"{SKILLS_EXTENSION}/evolved"] = dict(self.evolved)
        if self.catalog_metadata:
            metadata[f"{SKILLS_EXTENSION}/catalog"] = dict(self.catalog_metadata)
        if metadata:
            payload["_meta"] = metadata
        return payload

    def resource(self, uri: str) -> SkillResource | None:
        """Find one exact resource URI in this skill."""
        if isinstance(self.resources, str):
            return None
        return next((resource for resource in self.resources if resource.uri == uri), None)


def _text(value: Any) -> str:  # noqa: ANN401 - catalog JSON is untrusted
    return value.strip() if isinstance(value, str) else ""


def is_evolved_catalog(record: Any) -> bool:  # noqa: ANN401 - catalog JSON is untrusted
    """Return whether a record declares the supported versioned Evolved envelope."""
    return (
        isinstance(record, dict)
        and _text(record.get("_schema")) == EVOLVED_TOOLINFO_SCHEMA
        and _text(record.get("type")) == EVOLVED_CATALOG_TYPE
    )


def _dict(value: Any) -> dict[str, Any]:  # noqa: ANN401 - catalog JSON is untrusted
    return dict(value) if isinstance(value, dict) else {}


def _first_text(*values: Any) -> str:  # noqa: ANN401 - catalog JSON is untrusted
    for value in values:
        result = _text(value)
        if result:
            return result
    return ""


def _source_id(source: dict[str, Any]) -> str:
    return _first_text(source.get("id"), source.get("repository"), "catalog")


def _source_slug(source: dict[str, Any]) -> str:
    """Create a stable URI-safe namespace for generated URIs."""
    raw = _source_id(source).casefold()
    pieces = [piece for piece in re.split(r"[^a-z0-9._~-]+", raw) if piece]
    return "/".join(pieces[-3:]) or "catalog"


def _normalise_uri(raw: object) -> str:
    uri = _text(raw)
    if not uri or len(uri) > MAX_URI_LENGTH:
        _invalid("skill URI is missing or too long")
    parsed = urlsplit(uri)
    if not parsed.scheme or parsed.query or parsed.fragment:
        _invalid("skill URI must have a scheme and no query or fragment")
    if parsed.scheme == "skill" and not parsed.netloc:
        _invalid("skill URI must have a namespace")
    segments = [part for part in ([parsed.netloc] if parsed.netloc else []) + parsed.path.split("/") if part]
    decoded = [unquote(part) for part in segments]
    if any(part in {".", ".."} or "/" in part or "\\" in part for part in decoded):
        _invalid("skill URI contains an unsafe path segment")
    if len(decoded) < MIN_URI_SEGMENTS or decoded[-1] != SKILL_ENTRYPOINT:
        _invalid("skill URI must end with a skill root/SKILL.md")
    return uri


def _generated_uri(name: str, source: dict[str, Any], root: str) -> str:
    namespace = _source_slug(source)
    root_parts = [part for part in root.replace("\\", "/").strip("/").split("/") if part]
    if (
        root_parts
        and root_parts[-1].casefold() == name.casefold()
        and not any(part in {".", ".."} for part in root_parts)
    ):
        suffix = quote("/".join(root_parts), safe="/._~-")
    else:
        suffix = quote(name, safe="-._~")
    return f"skill://toolhub-evolved/catalog/{namespace}/{suffix}/{SKILL_ENTRYPOINT}"


def _skill_root(uri: str) -> str:
    return uri[: -len(f"/{SKILL_ENTRYPOINT}")]


def _resource_relative(uri: str, skill_uri: str) -> str:
    root = _skill_root(skill_uri)
    if uri == skill_uri:
        return SKILL_ENTRYPOINT
    if not uri.startswith(f"{root}/"):
        _invalid("resource URI is outside the skill root")
    relative = uri[len(root) + 1 :]
    parsed = urlsplit(uri)
    if parsed.query or parsed.fragment:
        _invalid("resource URI must not contain a query or fragment")
    parts = [unquote(part) for part in relative.split("/") if part]
    if not parts or any(part in {".", ".."} or "/" in part or "\\" in part for part in parts):
        _invalid("resource URI contains an unsafe path")
    return "/".join(parts)


def _relative_path(raw_path: object, root: str) -> str:
    path = _text(raw_path).replace("\\", "/").strip("/")
    if not path:
        return ""
    root = root.replace("\\", "/").strip("/")
    if root and path == root:
        return ""
    prefix = f"{root}/" if root else ""
    relative = path[len(prefix) :] if prefix and path.startswith(prefix) else path
    parts = [part for part in relative.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        return ""
    return "/".join(parts)


def _body(value: object) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return None


def _content_for(resource: dict[str, Any], skill: dict[str, Any], candidate: dict[str, Any]) -> bytes | None:
    """Read only explicit inline bodies; never follow a catalog path on disk."""
    for key in ("content", "text", "body"):
        content = _body(resource.get(key))
        if content is not None:
            return content
    path = _text(resource.get("path"))
    uri = _text(resource.get("uri"))
    relative = _text(resource.get("relative_path") or resource.get("relativePath"))
    keys = {key for key in (path, uri, relative) if key}
    for container in (skill.get("contents"), skill.get("files"), candidate.get("contents"), candidate.get("files")):
        if not isinstance(container, dict):
            continue
        for key in keys:
            content = _body(container.get(key))
            if content is not None:
                return content
    return None


def _digest(raw: object) -> str | None:
    value = _text(raw).casefold()
    if value.startswith("sha256:"):
        value = value.removeprefix("sha256:")
    return f"sha256:{value}" if _SHA256.fullmatch(value) else None


def _size(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _mime(resource: dict[str, Any], relative: str) -> str:
    value = _first_text(resource.get("mime_type"), resource.get("mimeType"))
    if value:
        return value
    if relative == SKILL_ENTRYPOINT:
        return "text/markdown"
    return mimetypes.guess_type(relative)[0] or _MIME_FALLBACK


def _resource_uri(raw: dict[str, Any], relative: str, skill_uri: str, *, first: bool) -> str:
    uri = _text(raw.get("uri"))
    if not uri and relative:
        uri = f"{_skill_root(skill_uri)}/{quote(relative, safe='/._~-')}"
    if not uri and (relative == SKILL_ENTRYPOINT or first):
        uri = skill_uri
    if not uri:
        _invalid("resource has neither uri nor path")
    return uri


def _resource_digest_and_size(raw: dict[str, Any], content: bytes | None) -> tuple[int, str]:
    size = _size(raw.get("size"))
    digest = _digest(raw.get("digest") or raw.get("sha256"))
    if content is not None:
        actual_size = len(content)
        actual_digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
        if size is not None and size != actual_size:
            _invalid("resource size does not match its content")
        if digest is not None and digest != actual_digest:
            _invalid("resource digest does not match its content")
        size, digest = actual_size, actual_digest
    if size is None or digest is None:
        _invalid("static resources require size and sha256 digest")
    return size, digest


def _resource_entry(
    raw: dict[str, Any],
    *,
    skill: dict[str, Any],
    candidate: dict[str, Any],
    skill_uri: str,
    first: bool,
) -> SkillResource:
    path = _text(raw.get("path"))
    relative = _relative_path(path, _first_text(skill.get("root"), candidate.get("root")))
    uri = _resource_uri(raw, relative, skill_uri, first=first)
    resource_relative = _resource_relative(uri, skill_uri)
    content = _content_for(raw, skill, candidate)
    size, digest = _resource_digest_and_size(raw, content)
    if size > MAX_SKILL_BYTES:
        _invalid("resource exceeds the per-skill size limit")
    return SkillResource(
        uri=uri,
        name=resource_relative.rsplit("/", 1)[-1],
        mime_type=_mime(raw, resource_relative),
        size=size,
        digest=digest,
        content=content,
        description=_text(raw.get("description")),
    )


def _resource_entries(
    resources: object,
    *,
    skill: dict[str, Any],
    candidate: dict[str, Any],
    skill_uri: str,
) -> tuple[SkillResource, ...] | str:
    if resources == "dynamic":
        return resources
    if not isinstance(resources, list) or not resources or len(resources) > MAX_RESOURCES_PER_SKILL:
        _invalid("resources must be a non-empty array or dynamic")
    normalized: list[SkillResource] = []
    seen: set[str] = set()
    for index, raw in enumerate(resources):
        if not isinstance(raw, dict):
            _invalid("resource entries must be objects")
        resource = _resource_entry(raw, skill=skill, candidate=candidate, skill_uri=skill_uri, first=index == 0)
        if resource.uri in seen:
            _invalid("resource URI appears more than once")
        seen.add(resource.uri)
        normalized.append(resource)
    if not any(resource.uri == skill_uri for resource in normalized):
        _invalid("resources must include the root SKILL.md")
    if sum(resource.size or 0 for resource in normalized) > MAX_SKILL_BYTES:
        _invalid("skill exceeds the total size limit")
    return tuple(normalized)


def _candidate_skill_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    nested = candidate.get("skill")
    return dict(nested) if isinstance(nested, dict) else candidate


def _candidate_list(value: object) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _candidate_frontmatter(skill: dict[str, Any], candidate: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    explicit = skill.get("frontmatter")
    if isinstance(explicit, dict):
        return dict(explicit)
    explicit = candidate.get("frontmatter")
    if isinstance(explicit, dict):
        return dict(explicit)
    values: dict[str, Any] = {}
    for source in (record, candidate, skill):
        for key, value in source.items():
            if key not in {"skill", "skills", "artifacts", "evolved", "source", "resources", "contents", "files"}:
                values.setdefault(key, value)
    return values


def _candidate_records(record: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Return (candidate, repository source) pairs for all supported shapes."""
    if _text(record.get("type")) == EVOLVED_CATALOG_TYPE and not is_evolved_catalog(record):
        # The versioned envelope is fail-closed: guessing at a future major
        # shape could publish the wrong artifact identity or review metadata.
        return []
    source = _dict(record.get("source"))
    artifacts = record.get("artifacts")
    if isinstance(artifacts, list):
        return [(item, _dict(item.get("source")) or source) for item in artifacts if isinstance(item, dict)]
    candidates: list[dict[str, Any]] = []
    candidates.extend(_candidate_list(record.get("skills")))
    candidates.extend(_candidate_list(record.get("skill")))
    evolved = _dict(record.get("evolved"))
    if not candidates:
        candidates.extend(_candidate_list(evolved.get("skills")))
    if not candidates:
        candidates.extend(_candidate_list(evolved.get("skill")))
    if not candidates and _text(record.get("tool_type")).casefold() == "skill":
        candidates.append(record)
    return [(candidate, _dict(candidate.get("source")) or source) for candidate in candidates]


def _entry_from_candidate(candidate: dict[str, Any], source: dict[str, Any], record: dict[str, Any]) -> SkillEntry:
    canonical = is_evolved_catalog(record)
    skill = _candidate_skill_payload(candidate)
    source = _dict(candidate.get("source")) or source or _dict(record.get("source"))
    frontmatter = _candidate_frontmatter(skill, candidate, record)
    name = _first_text(frontmatter.get("name"), skill.get("name"), candidate.get("name"))
    description = _first_text(frontmatter.get("description"), skill.get("description"), candidate.get("description"))
    if not name or not description:
        _invalid("skill frontmatter requires name and description")
    if canonical and not _text(candidate.get("id")):
        _invalid("versioned skill artifacts require an id")
    frontmatter.setdefault("name", name)
    frontmatter.setdefault("description", description)
    evolved = _dict(candidate.get("evolved"))
    if not evolved:
        evolved = _dict(skill.get("evolved"))
    if not evolved:
        evolved = _dict(record.get("evolved"))
    mcp = _dict(evolved.get("mcp"))
    uri = _first_text(
        mcp.get("resource_uri"),
        mcp.get("resourceUri"),
        candidate.get("uri"),
        skill.get("uri"),
    )
    root = _first_text(skill.get("root"), candidate.get("root"))
    entrypoint = _first_text(skill.get("entrypoint"), candidate.get("entrypoint"), SKILL_ENTRYPOINT)
    if canonical and not root:
        _invalid("versioned skill artifacts require a repository-relative root")
    if entrypoint != SKILL_ENTRYPOINT:
        _invalid("skill entrypoint must be SKILL.md")
    skill_uri = _normalise_uri(uri or _generated_uri(name, source, root))
    resources = _resource_entries(
        skill.get("resources", candidate.get("resources")),
        skill=skill,
        candidate=candidate,
        skill_uri=skill_uri,
    )
    controls = {
        "id",
        "tool_type",
        "name",
        "title",
        "description",
        "skill",
        "frontmatter",
        "resources",
        "source",
        "root",
        "entrypoint",
        "evolved",
        "uri",
        "contents",
        "files",
    }
    catalog_metadata = {key: value for key, value in candidate.items() if key not in controls}
    return SkillEntry(
        uri=skill_uri,
        frontmatter=frontmatter,
        resources=resources,
        artifact_id=_first_text(candidate.get("id")),
        source=source,
        evolved=evolved,
        catalog_metadata=catalog_metadata,
    )


def _entries_from_record(record: Any) -> list[SkillEntry]:  # noqa: ANN401 - catalog JSON is untrusted
    if not isinstance(record, dict):
        return []
    entries: list[SkillEntry] = []
    for candidate, source in _candidate_records(record):
        if _text(candidate.get("tool_type")).casefold() not in {"", "skill"}:
            continue
        try:
            entries.append(_entry_from_candidate(candidate, source, record))
        except InvalidSkillError:
            continue
    return entries


def all_entries() -> list[SkillEntry]:
    """Read and normalize all skills from the local canonical catalog."""
    with db.session_scope() as session:
        records = list(
            session.execute(select(CanonicalToolCache.record).order_by(CanonicalToolCache.tool_name.asc())).scalars()
        )
    by_uri: dict[str, SkillEntry] = {}
    for record in records:
        for entry in _entries_from_record(record):
            # The URI is the protocol identity. Keep the first deterministic
            # record when stale duplicate metadata happens to share one URI.
            by_uri.setdefault(entry.uri, entry)
    return [by_uri[uri] for uri in sorted(by_uri)]


def resource_entries() -> list[tuple[SkillEntry, SkillResource]]:
    """Flatten static resource manifests for the standard ``resources/list``."""
    flattened: list[tuple[SkillEntry, SkillResource]] = []
    for entry in all_entries():
        if isinstance(entry.resources, str):
            continue
        flattened.extend((entry, resource) for resource in entry.resources)
    return sorted(flattened, key=lambda pair: pair[1].uri)


def find_skill(uri: str) -> SkillEntry | None:
    """Find a skill by its exact root ``SKILL.md`` URI."""
    return next((entry for entry in all_entries() if entry.uri == uri), None)


def find_resource(uri: str) -> tuple[SkillEntry, SkillResource] | None:
    """Find a static resource by its exact URI."""
    return next((pair for pair in resource_entries() if pair[1].uri == uri), None)
