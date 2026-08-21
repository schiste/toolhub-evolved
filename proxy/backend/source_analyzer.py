# SPDX-License-Identifier: GPL-3.0-or-later
"""Static source-code signals for Toolhub metadata suggestions.

The analyzer is intentionally deterministic: every suggestion is backed by
bounded, redacted evidence from the submitted source files. It does not execute
tool code, clone repositories, or store raw source.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend import source_endpoints

MAX_FILES = 120
MAX_FILE_BYTES = 256 * 1024
# Not the effective ceiling for HTTP submissions: Flask's MAX_CONTENT_LENGTH
# (1 MiB, set in backend.register) rejects the request body first, so a caller
# coming through /v1/source-analysis/ can never reach this limit. It binds the
# in-process callers that bypass the request layer — repository_scan.py feeding
# a cloned checkout, and analyze_source.py run from the CLI — where nothing
# else caps the aggregate. Read it as the analyzer's own limit, not the API's.
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_PATH_CHARS = 240
MAX_LINE_CHARS = 500
MAX_EXCERPT_CHARS = 180
MAX_EVIDENCE_PER_FINDING = 5
MAX_FINDINGS_PER_BUCKET = 40
MAX_DEPENDENCY_NAME_CHARS = 120
MAX_CONTEXT_LIST_ITEMS = 40
MAX_CONTEXT_STRING_CHARS = 240
MAX_ASSESSMENT_SIGNALS = 8
MAX_SOURCE_CLASS_ITEMS = 20
JS_SCOPED_PACKAGE_PARTS = 2
CONFIDENCE_CAP = 0.99
CONFIDENCE_REPEAT_BOOST = 0.03
PROJECT_SUGGESTION_MIN_CONFIDENCE = 0.55
TECHNOLOGY_SUGGESTION_MIN_CONFIDENCE = 0.6
EVOLVED_METADATA_MIN_CONFIDENCE = 0.55
SCORING_MIN_CONFIDENCE = 0.55
# The weight at which a file's word is taken for an address. Every other bucket
# describes the repository -- it depends on this, it authenticates that way --
# and a weak mention there is still true. The endpoints bucket claims the tool
# talks to a service, and in a file that exists to point at things a mention is
# usually not that: a README lists where to download the tool, a changelog cites
# the ticket behind a fix, a test names a host nothing is listening on. Below
# this weight the address is only recorded when the line around it shows a call
# being made, which is the difference between citing an address and using one.
#
# Set at config (0.85) so that runtime, manifests, lockfiles, configuration and
# the frontend are believed outright, and documentation (0.75), CI, tests and
# examples must show their work. Measured over sixteen repositories this dropped
# 104 findings, all of them install instructions, badge images, project home
# pages and reading material; on cli/cli it was the whole report.
ENDPOINT_TRUSTED_SOURCE_WEIGHT = 0.85
SUGGESTION_MIN_SOURCE_WEIGHT = 0.55
ASSESSMENT_STRONG_SCORE = 85
ASSESSMENT_GOOD_SCORE = 70
ASSESSMENT_ATTENTION_SCORE = 50
ACTIVE_REPOSITORY_DAYS = 90
QUIET_REPOSITORY_DAYS = 365
STALE_REPOSITORY_DAYS = 730
ACTIVE_MAINTAINER_DAYS = 90
QUIET_MAINTAINER_DAYS = 365
STALE_MAINTAINER_DAYS = 730
HIGH_PROVENANCE_WEIGHT = 0.7
MULTIPLE_CONTRIBUTOR_MIN = 2
SMALL_COMMIT_HISTORY_THRESHOLD = 5
FRONTEND_SOURCE_EXTENSIONS = {".css", ".html", ".js", ".ts", ".tsx", ".vue"}
CONFIG_SOURCE_EXTENSIONS = {".ini", ".json", ".toml", ".yaml", ".yml", ".xml"}
RUNTIME_SOURCE_EXTENSIONS = {".go", ".java", ".lua", ".php", ".py", ".rb", ".rs", ".sh"}
IGNORED_SOURCE_DIRS = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "bower_components",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "playwright-report",
    "site-packages",
    "test-results",
    "vendor",
}
IGNORED_SOURCE_FILES = {
    "cspell.json",
}
LOCAL_IMPORT_ROOTS = {
    "app",
    "backend",
    "config",
    "docs",
    "migrations",
    "proxy",
    "public_html",
    "scripts",
    "tests",
    "tools",
}

SOURCE_EXTENSIONS = {
    ".css",
    ".go",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".lua",
    ".md",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".ts",
    ".tsx",
    ".txt",
    ".toml",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}

MANIFEST_FILE_KINDS = {
    "cargo.toml": "cargo",
    "composer.json": "composer",
    "gemfile": "rubygems",
    "go.mod": "go",
    "package.json": "npm",
    "pipfile": "pypi",
    "pyproject.toml": "python",
    "requirements.txt": "pypi",
}

LOCKFILE_KINDS = {
    "cargo.lock": "cargo",
    "composer.lock": "composer",
    "gemfile.lock": "rubygems",
    "npm-shrinkwrap.json": "npm",
    "package-lock.json": "npm",
    "pipfile.lock": "pypi",
    "pnpm-lock.yaml": "npm",
    "poetry.lock": "pypi",
    "yarn.lock": "npm",
}

DOCUMENTATION_FILE_KINDS = {
    "authors": "authors",
    "authors.md": "authors",
    "changelog": "changelog",
    "changelog.md": "changelog",
    "code_of_conduct.md": "code-of-conduct",
    "codeowners": "owners",
    "contributing": "contributing",
    "contributing.md": "contributing",
    "copying": "license",
    "copying.md": "license",
    "license": "license",
    "license.md": "license",
    "maintainers": "owners",
    "maintainers.md": "owners",
    "readme": "readme",
    "readme.md": "readme",
    "security": "security",
    "security.md": "security",
}

CI_FILE_KINDS = {
    ".buildkite/pipeline.yml": "buildkite",
    ".circleci/config.yml": "circleci",
    ".gitlab-ci.yml": "gitlab-ci",
    "azure-pipelines.yml": "azure-pipelines",
    "bitbucket-pipelines.yml": "bitbucket-pipelines",
    "noxfile.py": "nox",
    "tox.ini": "tox",
}

RUNTIME_FILE_KINDS = {
    ".lighttpd.conf": "lighttpd",
    "app.py": "python-web-entrypoint",
    "dockerfile": "container",
    "jobs.yaml": "toolforge-jobs",
    "lighttpd.conf": "lighttpd",
    "nginx.conf": "nginx",
    "procfile": "process",
    "service.template": "toolforge-webservice",
    "toolforge.yaml": "toolforge",
    "uwsgi.ini": "uwsgi",
    "webservice": "toolforge-webservice",
}

REPOSITORY_CONTEXT_REPOSITORY_KEYS = {
    "analyzedAt",
    "archived",
    "branch",
    "commitCount",
    "commitSha",
    "contributorCount",
    "defaultBranch",
    "dirty",
    "lastCommitAgeDays",
    "lastCommitAt",
    "provider",
    "tag",
    "url",
}

# What the maintainer says about the tool's life, from toolinfo. Distinct from
# `repository` (facts about the checkout and its host) and from `declared`
# (claims about technical shape that the source is checked against). Nothing
# here has a counterpart to detect: it is testimony, not evidence.
REPOSITORY_CONTEXT_LIFECYCLE_KEYS = {
    "deprecated",
    "replacedBy",
}

REPOSITORY_CONTEXT_DECLARED_KEYS = {
    "accessRights",
    "apis",
    "dependencies",
    "healthUrl",
    "license",
    "oauthScopes",
    "runtime",
}

REPOSITORY_CONTEXT_MAINTAINER_KEYS = {
    "activeMaintainerCount",
    "analyzedAt",
    "lastActivityAgeDays",
    "lastActivityAt",
    "maintainerCount",
    "recentActivityCount",
    "source",
}

HEALTH_SIGNAL_RE = re.compile(r"\b(?:healthz|healthcheck|readiness|liveness|/health)\b", re.IGNORECASE)
A11Y_SIGNAL_RE = re.compile(r"\b(?:aria-[a-z-]+|role=|lang=|tabindex|focus|keyboard|axe-core|axe)\b", re.IGNORECASE)
ANALYSIS_TOOLING_RE = re.compile(
    r"(?:^|/)(?:analyze[_-]?source|source[_-]?analy[sz]er|source-analysis)(?:[._/-]|$)",
    re.IGNORECASE,
)

SOURCE_CLASS_WEIGHTS = {
    "analysis-tooling": 0.15,
    "ci": 0.75,
    "config": 0.85,
    "docs": 0.75,
    "example": 0.25,
    "fixture": 0.15,
    "frontend": 0.95,
    "lockfile": 0.95,
    "manifest": 1.0,
    "runtime": 1.0,
    "test": 0.35,
    "unknown": 0.55,
}

HEALTH_DIMENSIONS = (
    (
        "tool-health",
        "Tool health",
        ("operational-readiness",),
        1.25,
        "Runtime, deployment, and health-check readiness.",
    ),
    (
        "source-maintenance",
        "Source maintenance",
        ("maintenance-activity",),
        1.0,
        "Repository activity and source history freshness.",
    ),
    (
        "maintainability",
        "Maintainability",
        ("maintenance-readiness", "dependency-health"),
        1.0,
        "Documentation, tests, CI, and dependency reproducibility.",
    ),
    (
        "safety",
        "Safety and permissions",
        ("security-review", "permission-clarity"),
        1.15,
        "Credential, elevated-rights, and permission clarity signals.",
    ),
    (
        "metadata-quality",
        "Metadata quality",
        ("metadata-completeness",),
        0.65,
        "Completeness of derived Toolhub metadata.",
    ),
    (
        "accessibility",
        "Frontend accessibility",
        ("frontend-accessibility",),
        0.6,
        "Accessibility evidence for web-facing tools.",
    ),
)
MAINTAINER_DIMENSION_WEIGHT = 1.2

TECH_BY_EXTENSION = {
    ".go": "Go",
    ".java": "Java",
    ".js": "JavaScript",
    ".lua": "Lua",
    ".php": "PHP",
    ".py": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".sh": "Shell",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
}

TECH_RULES = (
    ("Python", re.compile(r"\b(import|from)\s+(flask|django|pywikibot|mwclient|requests)\b", re.IGNORECASE), 0.78),
    ("Flask", re.compile(r"\bfrom\s+flask\s+import\b|\bFlask\s*\(", re.IGNORECASE), 0.9),
    ("Django", re.compile(r"\bDJANGO_SETTINGS_MODULE\b|\bfrom\s+django\b", re.IGNORECASE), 0.9),
    ("Pywikibot", re.compile(r"\bpywikibot\b", re.IGNORECASE), 0.96),
    ("mwclient", re.compile(r"\bmwclient\b", re.IGNORECASE), 0.95),
    ("Node.js", re.compile(r"\b(express|fastify|koa)\b|\"scripts\"\s*:", re.IGNORECASE), 0.72),
    ("React", re.compile(r"\bReact\b|from\s+[\"']react[\"']", re.IGNORECASE), 0.82),
    ("MediaWiki gadget", re.compile(r"\bmw\.loader\.using\b|\bmw\.Api\b|\.user\.js\b", re.IGNORECASE), 0.9),
)

# What a project runs on a machine of its own. Named against TECH_RULES above,
# and used only to rule the gadget suggestion out.
SERVER_TECHNOLOGIES = frozenset({"Flask", "Django", "Pywikibot", "mwclient"})

PROJECT_DOMAIN_RE = re.compile(
    r"\b(?:(?P<sub>[a-z0-9-]+)\.)?(?P<family>wikipedia|wikibooks|wikidata|wikimedia|wikinews|wikiquote|wikisource|wiktionary|wikiversity|wikivoyage|mediawiki)\.org\b",
    re.IGNORECASE,
)
PROJECT_DB_RE = re.compile(
    r"(?<![a-z0-9_.-])(?:commonswiki|wikidatawiki|metawiki|mediawikiwiki|[a-z][a-z0-9_]{1,14}wiki)(?![a-z0-9_-]|\.[a-z0-9_-])"
)
IGNORED_PROJECT_DB_NAMES = {"mediawiki"}
ACTION_QUERY_RE = re.compile(r"[?&]action\s*=\s*[\"']?([a-z0-9_]+)", re.IGNORECASE)
ACTION_OBJECT_RE = re.compile(r"\b[\"']?action[\"']?\s*:\s*[\"']([a-z0-9_]+)[\"']", re.IGNORECASE)
SCOPE_LINE_RE = re.compile(r"\bscopes?\b|mwoauth", re.IGNORECASE)
CSRF_RE = re.compile(
    r"\b(?:csrf|edit)token\b|meta\s*=\s*tokens|\btokens\s*:\s*[\"']csrf|postWithToken\(\s*[\"']csrf",
    re.IGNORECASE,
)
CREDENTIAL_RE = re.compile(
    r"[\"']?\b(?:client[_-]?secret|consumer[_-]?secret|api[_-]?key|access[_-]?token|refresh[_-]?token|password)\b[\"']?\s*[:=]\s*(?:[rubfRUBF]*[\"'][^\"']{4,}[\"']|[A-Za-z0-9/+=-]{20,})",
    re.IGNORECASE,
)

# What separates a URL that is called from a URL that is merely mentioned. A
# README linking to an API and a client invoking it look the same to a URL
# matcher, and this is the only cheap signal that tells them apart. It can only
# raise confidence: a call made through a variable or a wrapper still reports
# at the base, because the address is a fact whether or not this matches.
REQUEST_SIGNAL_RE = re.compile(
    r"\b(?:fetch|axios|XMLHttpRequest|ajax|urlopen|urlretrieve|requests?|session|httpx|got|"
    r"curl|wget|HttpClient|WebClient|RestTemplate|file_get_contents|urlfetch)\b"
    r"|\bmw\.(?:Api|loader)\b|\.(?:get|post|put|patch|delete|head)\s*\(",
    re.IGNORECASE,
)
ENDPOINT_CONFIDENCE = 0.75
ENDPOINT_CALLED_CONFIDENCE = 0.9

API_RULES = (
    (
        "mediawiki-action-api",
        "MediaWiki Action API",
        re.compile(r"\bw/api\.php\b|\bmediawiki action api\b|\bmw\.Api\b|\bpywikibot\b|\bmwclient\b", re.IGNORECASE),
        0.92,
        "MediaWiki Action API client or endpoint detected.",
    ),
    (
        "wikibase-api",
        "Wikibase API",
        re.compile(r"\bwb[a-z]+\b|\bWikibase\b", re.IGNORECASE),
        0.92,
        "Wikibase action or client detected.",
    ),
    (
        "wikidata-query-service",
        "Wikidata Query Service",
        re.compile(r"query\.wikidata\.org/sparql|\bSPARQL\b", re.IGNORECASE),
        0.94,
        "SPARQL query endpoint detected.",
    ),
    (
        "mediawiki-rest-api",
        "MediaWiki REST API",
        re.compile(r"/w/rest\.php|/api/rest_v1\b|\brestbase\b", re.IGNORECASE),
        0.88,
        "MediaWiki REST endpoint detected.",
    ),
    (
        "toolforge",
        "Toolforge platform",
        re.compile(r"\btoolforge\b|\btoolsdb\b|replica\.my\.cnf|toolsadmin\.wikimedia\.org", re.IGNORECASE),
        0.85,
        "Toolforge runtime or service endpoint detected.",
    ),
    (
        "commons-upload",
        "Commons upload workflow",
        re.compile(r"commons\.wikimedia\.org.*action\s*=\s*upload|Special:Upload|stash(?:file)?key", re.IGNORECASE),
        0.9,
        "Commons upload path detected.",
    ),
)

AUTH_RULES = (
    (
        "oauth",
        "OAuth",
        re.compile(r"\bmwoauth\b|\boauth\b|client_id|redirect_uri|authorization:\s*bearer", re.IGNORECASE),
        0.9,
        "OAuth client or bearer-token flow detected.",
    ),
    (
        "csrf-token",
        "CSRF token",
        CSRF_RE,
        0.84,
        "MediaWiki token handling detected.",
    ),
    (
        "bot-password",
        "Bot password",
        re.compile(r"\bbot.?password\b|\blgname\b|\blgpassword\b", re.IGNORECASE),
        0.86,
        "Legacy bot-password login signal detected.",
    ),
)

KNOWN_OAUTH_SCOPES = {
    "basic": ("Basic identity", 0.7),
    "blockusers": ("Block users", 0.9),
    "createaccount": ("Create accounts", 0.82),
    "createeditmovepage": ("Create, edit, and move pages", 0.9),
    "delete": ("Delete pages", 0.88),
    "editmywatchlist": ("Edit watchlist", 0.82),
    "editpage": ("Edit pages", 0.9),
    "email": ("Send email", 0.76),
    "highvolume": ("High-volume API access", 0.82),
    "patrol": ("Patrol changes", 0.84),
    "privateinfo": ("Private account information", 0.9),
    "rollback": ("Rollback edits", 0.86),
    "sendemail": ("Send email", 0.78),
    "uploadfile": ("Upload files", 0.9),
    "viewdeleted": ("View deleted revisions", 0.82),
    "viewmywatchlist": ("View watchlist", 0.8),
}

ACTION_RIGHTS = {
    "block": (("block", "Block users", "administrator", 0.9),),
    "createaccount": (("create-account", "Create accounts", "write", 0.82),),
    "delete": (("delete", "Delete pages", "administrator", 0.92), ("csrf-token", "CSRF token", "write", 0.78)),
    "edit": (("edit", "Edit pages", "write", 0.94), ("csrf-token", "CSRF token", "write", 0.78)),
    "emailuser": (("send-email", "Send email to users", "write", 0.82), ("csrf-token", "CSRF token", "write", 0.74)),
    "import": (("import", "Import pages", "administrator", 0.86), ("csrf-token", "CSRF token", "write", 0.76)),
    "mergehistory": (
        ("merge-history", "Merge page histories", "administrator", 0.86),
        ("csrf-token", "CSRF token", "write", 0.76),
    ),
    "move": (("move", "Move pages", "write", 0.88), ("csrf-token", "CSRF token", "write", 0.78)),
    "options": (("edit-preferences", "Edit user preferences", "write", 0.78),),
    "patrol": (("patrol", "Patrol edits", "moderation", 0.86), ("csrf-token", "CSRF token", "write", 0.76)),
    "protect": (("protect", "Protect pages", "administrator", 0.9), ("csrf-token", "CSRF token", "write", 0.78)),
    "review": (("review", "Review pending changes", "moderation", 0.84), ("csrf-token", "CSRF token", "write", 0.76)),
    "revisiondelete": (
        ("revision-delete", "Delete or suppress revision data", "administrator", 0.9),
        ("csrf-token", "CSRF token", "write", 0.78),
    ),
    "rollback": (("rollback", "Rollback edits", "moderation", 0.86), ("csrf-token", "CSRF token", "write", 0.76)),
    "tag": (("change-tags", "Apply change tags", "moderation", 0.72), ("csrf-token", "CSRF token", "write", 0.72)),
    "undelete": (("undelete", "Undelete pages", "administrator", 0.9), ("csrf-token", "CSRF token", "write", 0.78)),
    "upload": (("upload", "Upload files", "write", 0.94), ("csrf-token", "CSRF token", "write", 0.78)),
    "userrights": (
        ("user-rights", "Change user rights", "administrator", 0.92),
        ("csrf-token", "CSRF token", "write", 0.78),
    ),
    "watch": (("edit-watchlist", "Edit watchlist", "write", 0.78),),
    "wbcreateclaim": (
        ("edit", "Edit pages", "write", 0.88),
        ("wikibase-edit", "Edit Wikibase entities", "write", 0.94),
        ("csrf-token", "CSRF token", "write", 0.78),
    ),
    "wbeditentity": (
        ("edit", "Edit pages", "write", 0.9),
        ("wikibase-edit", "Edit Wikibase entities", "write", 0.94),
        ("csrf-token", "CSRF token", "write", 0.78),
    ),
    "wbmergeitems": (
        ("wikibase-edit", "Edit Wikibase entities", "write", 0.92),
        ("csrf-token", "CSRF token", "write", 0.78),
    ),
    "wbremoveclaims": (
        ("wikibase-edit", "Edit Wikibase entities", "write", 0.92),
        ("csrf-token", "CSRF token", "write", 0.78),
    ),
    "wbsetaliases": (
        ("wikibase-edit", "Edit Wikibase entities", "write", 0.9),
        ("csrf-token", "CSRF token", "write", 0.78),
    ),
    "wbsetclaim": (
        ("wikibase-edit", "Edit Wikibase entities", "write", 0.94),
        ("csrf-token", "CSRF token", "write", 0.78),
    ),
    "wbsetclaimvalue": (
        ("wikibase-edit", "Edit Wikibase entities", "write", 0.94),
        ("csrf-token", "CSRF token", "write", 0.78),
    ),
    "wbsetdescription": (
        ("wikibase-edit", "Edit Wikibase entities", "write", 0.9),
        ("csrf-token", "CSRF token", "write", 0.78),
    ),
    "wbsetlabel": (
        ("wikibase-edit", "Edit Wikibase entities", "write", 0.9),
        ("csrf-token", "CSRF token", "write", 0.78),
    ),
    "wbsetqualifier": (
        ("wikibase-edit", "Edit Wikibase entities", "write", 0.92),
        ("csrf-token", "CSRF token", "write", 0.78),
    ),
    "wbsetreference": (
        ("wikibase-edit", "Edit Wikibase entities", "write", 0.92),
        ("csrf-token", "CSRF token", "write", 0.78),
    ),
    "wbsetsitelink": (
        ("wikibase-edit", "Edit Wikibase entities", "write", 0.9),
        ("csrf-token", "CSRF token", "write", 0.78),
    ),
}

READ_ACTIONS = {
    "compare",
    "expandtemplates",
    "opensearch",
    "parse",
    "query",
    "wbgetentities",
    "wbsearchentities",
}
JS_IMPORT_RE = re.compile(
    r"(?:\bfrom\s+[\"'](?P<from>[^\"']+)[\"']|\b(?:require|import)\(\s*[\"'](?P<call>[^\"']+)[\"']\s*\))"
)
PY_IMPORT_RE = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*))")
PHP_USE_RE = re.compile(r"^\s*use\s+([A-Za-z_][\w\\]*)")
RUBY_REQUIRE_RE = re.compile(r"^\s*require\s+[\"']([^\"']+)[\"']")
GEM_RE = re.compile(r"^\s*gem\s+[\"']([^\"']+)[\"']")
REQ_NAME_RE = re.compile(r"^([A-Za-z0-9_.-]+)")
GO_REQUIRE_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)\s+v?[0-9]")
GEM_LOCK_RE = re.compile(r"^\s{4}([A-Za-z0-9_.-]+)\s+\(")
YARN_LOCK_RE = re.compile(r"^[\"']?([^\"':,\s]+(?:/[^\"':,\s]+)?)(?:@npm:|@patch:|@workspace:|@[^:]*:)")


class SourceAnalysisError(ValueError):
    """Raised when submitted source-analysis input is unsafe or malformed."""


@dataclass(frozen=True)
class SourceFile:
    """One bounded source file supplied to the analyzer."""

    path: str
    content: str


@dataclass
class Finding:
    """Accumulated finding before serialization."""

    value: str
    label: str
    kind: str
    category: str
    confidence: float
    reasons: set[str] = field(default_factory=set)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    source_classes: set[str] = field(default_factory=set)
    max_source_weight: float = 0.0

    def add(self, confidence: float, reason: str, evidence: dict[str, Any]) -> None:
        """Merge repeated evidence into one finding."""
        source_class = str(evidence.get("sourceClass") or "unknown")
        source_weight = float(evidence.get("sourceWeight") or SOURCE_CLASS_WEIGHTS["unknown"])
        adjusted_confidence = min(CONFIDENCE_CAP, max(0.0, confidence) * source_weight)
        repeated_evidence_boost = (
            CONFIDENCE_REPEAT_BOOST * source_weight if source_weight >= HIGH_PROVENANCE_WEIGHT else 0
        )
        self.confidence = min(CONFIDENCE_CAP, max(self.confidence, adjusted_confidence) + repeated_evidence_boost)
        self.reasons.add(reason)
        self.evidence.append(evidence)
        self.source_classes.add(source_class)
        self.max_source_weight = max(self.max_source_weight, source_weight)

    def payload(self) -> dict[str, Any]:
        """Serialize the finding for JSON responses."""
        return {
            "value": self.value,
            "label": self.label,
            "kind": self.kind,
            "category": self.category,
            "confidence": round(self.confidence, 2),
            "maxSourceWeight": round(self.max_source_weight, 2),
            "reasons": sorted(self.reasons),
            "sourceClasses": sorted(self.source_classes),
            "evidence": self.evidence[:MAX_EVIDENCE_PER_FINDING],
        }


def _suffix(path: str) -> str:
    match = re.search(r"(\.[A-Za-z0-9]+)$", path)
    return match.group(1).lower() if match else ""


def _clean_path(value: object) -> str:
    path = str(value or "").replace("\\", "/").strip().lstrip("/")
    path = re.sub(r"/+", "/", path)
    return path[:MAX_PATH_CHARS] if path else "source.txt"


def _is_source_path(path: str) -> bool:
    parts = {part.lower() for part in path.replace("\\", "/").split("/")}
    if parts & IGNORED_SOURCE_DIRS:
        return False
    suffix = _suffix(path)
    name = path.rsplit("/", 1)[-1].lower()
    if name in IGNORED_SOURCE_FILES:
        return False
    return suffix in SOURCE_EXTENSIONS or name in {
        "composer.json",
        "dockerfile",
        "gemfile",
        "go.mod",
        "makefile",
        "package.json",
        "pipfile",
        "requirements.txt",
    } | set(LOCKFILE_KINDS) | set(DOCUMENTATION_FILE_KINDS) | set(CI_FILE_KINDS) | set(RUNTIME_FILE_KINDS)


def is_supported_source_path(path: str) -> bool:
    """Return whether a source path should be accepted for analysis."""
    return _is_source_path(path)


def _line_excerpt(line: str) -> str:
    compact = re.sub(r"\s+", " ", line.strip())[:MAX_EXCERPT_CHARS]
    if CREDENTIAL_RE.search(compact):
        return "[redacted credential-like assignment]"
    return compact


def _manifest_kind(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1].lower()
    if name.startswith("requirements") and name.endswith(".txt"):
        return "pypi"
    return MANIFEST_FILE_KINDS.get(name)


def _is_fixture_path(path: str) -> bool:
    parts = {part.lower() for part in path.replace("\\", "/").split("/")}
    name = path.rsplit("/", 1)[-1].lower()
    return bool(parts & {"__fixtures__", "fixtures", "fixture"}) or "fixture" in name


def _is_example_path(path: str) -> bool:
    parts = {part.lower() for part in path.replace("\\", "/").split("/")}
    name = path.rsplit("/", 1)[-1].lower()
    return bool(parts & {"demo", "demos", "example", "examples", "sample", "samples"}) or re.search(
        r"(?:^|[._-])(?:demo|example|sample)(?:[._-]|$)",
        name,
    )


def _source_class_from_named_file(path: str, name: str) -> str | None:
    if _manifest_kind(path):
        return "manifest"
    if name in LOCKFILE_KINDS:
        return "lockfile"
    if _ci_kind(path):
        return "ci"
    return None


def _source_class_from_low_provenance_path(path: str) -> str | None:
    if _is_fixture_path(path):
        return "fixture"
    if _test_kind(path):
        return "test"
    if path.startswith("docs/") or _documentation_kind(path):
        return "docs"
    if _is_example_path(path):
        return "example"
    if ANALYSIS_TOOLING_RE.search(path):
        return "analysis-tooling"
    return None


def _source_class_from_runtime_shape(path: str, name: str, suffix: str) -> str | None:
    if _runtime_kind(path):
        return "runtime"
    if path.startswith("public_html/") or suffix in FRONTEND_SOURCE_EXTENSIONS:
        return "frontend"
    if name == "makefile" or suffix in CONFIG_SOURCE_EXTENSIONS:
        return "config"
    if suffix in RUNTIME_SOURCE_EXTENSIONS:
        return "runtime"
    return None


def _source_class(path: str) -> str:
    normalized = path.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    suffix = _suffix(normalized)
    for candidate in (
        _source_class_from_named_file(normalized, name),
        _source_class_from_low_provenance_path(normalized),
        _source_class_from_runtime_shape(normalized, name, suffix),
    ):
        if candidate:
            return candidate
    return "unknown"


def _source_weight(path: str) -> float:
    return SOURCE_CLASS_WEIGHTS.get(_source_class(path), SOURCE_CLASS_WEIGHTS["unknown"])


def source_reading_rank(path: str) -> tuple[float, int, str]:
    """Rank a candidate source for reading, the one most worth reading first.

    Both readers stop at MAX_FILES, so whichever order they walk in is what
    decides the whole report. Walking in path order let the alphabet decide: on
    cli/cli the budget was spent inside `.github/` and `docs/` and never reached
    `internal/update/update.go`, where the tool's one call to api.github.com is
    written. Where a file sorts is not evidence about what it holds.

    Provenance already answers the question that needs answering here. A file's
    source class says how much of the repository's own voice is in it, and the
    file the tool is made of is the file worth spending the budget on -- so the
    first key is that weight, descending. The second is path depth, because
    within one class the shallow file is what the package presents and the deep
    one is a detail of it; taking the shallow ones first spreads a hundred slots
    across the top of a tree instead of exhausting its first branch. The path
    itself settles what is left, so two reads of the same tree read the same
    files.

    Measured over sixteen repositories this took the endpoints reported from 206
    to 270 and the dependencies from 318 to 421, and cli/cli named api.github.com
    for the first time.
    """
    normalized = path.replace("\\", "/")
    return (-_source_weight(normalized), normalized.count("/"), normalized)


def _evidence(path: str, line_number: int, line: str, matched: str) -> dict[str, Any]:
    source_class = _source_class(path)
    return {
        "path": path,
        "line": line_number,
        "match": matched[:80],
        "excerpt": _line_excerpt(line),
        "sourceClass": source_class,
        "sourceWeight": SOURCE_CLASS_WEIGHTS.get(source_class, SOURCE_CLASS_WEIGHTS["unknown"]),
    }


def _line_for_text(content: str, needle: str) -> tuple[int, str]:
    for line_number, line in enumerate(content.splitlines() or [""], start=1):
        if needle in line:
            return line_number, line[:MAX_LINE_CHARS]
    return 1, (content.splitlines() or [""])[0][:MAX_LINE_CHARS]


def _normalize_source_files(files: object) -> list[SourceFile]:
    if not isinstance(files, list) or not files:
        message = "files must be a non-empty list of {path, content}"
        raise SourceAnalysisError(message)
    if len(files) > MAX_FILES:
        message = f"files may contain at most {MAX_FILES} entries"
        raise SourceAnalysisError(message)
    total = 0
    normalized: list[SourceFile] = []
    for item in files:
        if not isinstance(item, dict):
            message = "each file entry must be an object"
            raise SourceAnalysisError(message)
        path = _clean_path(item.get("path"))
        content = item.get("content")
        if not isinstance(content, str):
            message = f"{path}: content must be text"
            raise SourceAnalysisError(message)
        encoded_size = len(content.encode("utf-8"))
        if encoded_size > MAX_FILE_BYTES:
            message = f"{path}: file is larger than {MAX_FILE_BYTES} bytes"
            raise SourceAnalysisError(message)
        total += encoded_size
        if total > MAX_TOTAL_BYTES:
            message = f"submitted files are larger than {MAX_TOTAL_BYTES} bytes in total"
            raise SourceAnalysisError(message)
        if _is_source_path(path):
            normalized.append(SourceFile(path=path, content=content))
    if not normalized:
        message = "no supported source files were provided"
        raise SourceAnalysisError(message)
    return normalized


def _put(  # noqa: PLR0913 - explicit finding fields avoid opaque tuple packing at every call site.
    findings: dict[tuple[str, str], Finding],
    *,
    kind: str,
    value: str,
    label: str,
    category: str,
    confidence: float,
    reason: str,
    evidence: dict[str, Any],
) -> None:
    key = (kind, value)
    current = findings.get(key)
    if current is None:
        current = Finding(value=value, label=label, kind=kind, category=category, confidence=0.0)
        findings[key] = current
    current.add(confidence, reason, evidence)


def _clean_dependency_name(value: object) -> str | None:
    name = str(value or "").strip()
    if not name or len(name) > MAX_DEPENDENCY_NAME_CHARS:
        return None
    if name.startswith((".", "/", "http://", "https://", "git+", "file:")):
        return None
    return name


def _dependency_value(ecosystem: str, name: str) -> str:
    return f"{ecosystem}:{name.lower()}"


def _put_dependency(  # noqa: PLR0913 - explicit dependency fields keep call sites readable across ecosystems.
    findings: dict[tuple[str, str], Finding],
    *,
    ecosystem: str,
    name: str,
    category: str,
    confidence: float,
    reason: str,
    evidence: dict[str, Any],
) -> None:
    clean_name = _clean_dependency_name(name)
    if clean_name is None:
        return
    normalized = clean_name.lower()
    if (ecosystem == "pypi" and normalized == "python") or (
        ecosystem == "composer" and (normalized == "php" or normalized.startswith("ext-"))
    ):
        return
    _put(
        findings,
        kind="dependencies",
        value=_dependency_value(ecosystem, clean_name),
        label=f"{clean_name} ({ecosystem})",
        category=category,
        confidence=confidence,
        reason=reason,
        evidence=evidence,
    )
    _scan_dependency_api_signals(findings, ecosystem, clean_name, evidence)


def _scan_dependency_api_signals(
    findings: dict[tuple[str, str], Finding], ecosystem: str, name: str, evidence: dict[str, Any]
) -> None:
    normalized = name.lower()
    mediawiki_clients = {
        "mediawiki-api",
        "mediawiki",
        "mw-api",
        "mwclient",
        "pywikibot",
    }
    wikibase_clients = {
        "wikibase-sdk",
        "wikibase-edit",
        "wikidata-sdk",
        "wikidata-sdk-rdf",
    }
    if normalized in mediawiki_clients or normalized.endswith("/mediawiki-api"):
        _put(
            findings,
            kind="apis",
            value="mediawiki-action-api",
            label="MediaWiki Action API",
            category="detected",
            confidence=0.86,
            reason=f"{ecosystem} dependency suggests MediaWiki Action API usage.",
            evidence=evidence,
        )
    if normalized in wikibase_clients or "wikibase" in normalized or "wikidata" in normalized:
        _put(
            findings,
            kind="apis",
            value="wikibase-api",
            label="Wikibase API",
            category="detected",
            confidence=0.82,
            reason=f"{ecosystem} dependency suggests Wikibase API usage.",
            evidence=evidence,
        )


def _scan_mapping_dependencies(  # noqa: PLR0913 - manifest source, ecosystem, and confidence are independent.
    findings: dict[tuple[str, str], Finding],
    *,
    path: str,
    content: str,
    ecosystem: str,
    mapping: object,
    category: str,
    reason: str,
    confidence: float,
) -> None:
    if not isinstance(mapping, dict):
        return
    for name in mapping:
        clean_name = _clean_dependency_name(name)
        if clean_name is None:
            continue
        line_number, line = _line_for_text(content, str(name))
        _put_dependency(
            findings,
            ecosystem=ecosystem,
            name=clean_name,
            category=category,
            confidence=confidence,
            reason=reason,
            evidence=_evidence(path, line_number, line, clean_name),
        )


def _scan_package_json(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = json.loads(source_file.content)
    except json.JSONDecodeError:
        return
    groups = {
        "dependencies": ("runtime", "Declared npm runtime dependency.", 0.98),
        "optionalDependencies": ("optional", "Declared npm optional dependency.", 0.9),
        "peerDependencies": ("peer", "Declared npm peer dependency.", 0.88),
        "devDependencies": ("development", "Declared npm development dependency.", 0.78),
    }
    for key, (category, reason, confidence) in groups.items():
        _scan_mapping_dependencies(
            findings,
            path=source_file.path,
            content=source_file.content,
            ecosystem="npm",
            mapping=data.get(key) if isinstance(data, dict) else None,
            category=category,
            reason=reason,
            confidence=confidence,
        )


def _requirement_name(line: str) -> str | None:
    clean = line.split("#", 1)[0].strip()
    if not clean or clean.startswith(("-", "--")):
        return None
    if " @ " in clean:
        clean = clean.split(" @ ", 1)[0].strip()
    match = REQ_NAME_RE.match(clean.split("[", 1)[0])
    return match.group(1) if match else None


def _scan_requirements_txt(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    for line_number, raw_line in enumerate(source_file.content.splitlines() or [""], start=1):
        name = _requirement_name(raw_line)
        if name is None:
            continue
        _put_dependency(
            findings,
            ecosystem="pypi",
            name=name,
            category="runtime",
            confidence=0.94,
            reason="Declared Python requirement.",
            evidence=_evidence(source_file.path, line_number, raw_line, name),
        )


def _scan_pyproject_toml(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = tomllib.loads(source_file.content)
    except tomllib.TOMLDecodeError:
        return
    project = data.get("project") if isinstance(data, dict) else {}
    if isinstance(project, dict):
        for requirement in project.get("dependencies") or []:
            name = _requirement_name(str(requirement))
            if name:
                line_number, line = _line_for_text(source_file.content, name)
                _put_dependency(
                    findings,
                    ecosystem="pypi",
                    name=name,
                    category="runtime",
                    confidence=0.92,
                    reason="Declared Python project dependency.",
                    evidence=_evidence(source_file.path, line_number, line, name),
                )
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for requirements in optional.values():
                for requirement in requirements if isinstance(requirements, list) else []:
                    name = _requirement_name(str(requirement))
                    if name:
                        line_number, line = _line_for_text(source_file.content, name)
                        _put_dependency(
                            findings,
                            ecosystem="pypi",
                            name=name,
                            category="optional",
                            confidence=0.82,
                            reason="Declared Python optional dependency.",
                            evidence=_evidence(source_file.path, line_number, line, name),
                        )
    poetry = data.get("tool", {}).get("poetry", {}) if isinstance(data.get("tool"), dict) else {}
    if isinstance(poetry, dict):
        _scan_mapping_dependencies(
            findings,
            path=source_file.path,
            content=source_file.content,
            ecosystem="pypi",
            mapping=poetry.get("dependencies"),
            category="runtime",
            reason="Declared Poetry runtime dependency.",
            confidence=0.9,
        )
        _scan_mapping_dependencies(
            findings,
            path=source_file.path,
            content=source_file.content,
            ecosystem="pypi",
            mapping=poetry.get("group", {}).get("dev", {}).get("dependencies")
            if isinstance(poetry.get("group"), dict)
            else None,
            category="development",
            reason="Declared Poetry development dependency.",
            confidence=0.76,
        )
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="cargo",
        mapping=data.get("dependencies") if isinstance(data, dict) else None,
        category="runtime",
        reason="Declared Cargo runtime dependency.",
        confidence=0.92,
    )
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="cargo",
        mapping=data.get("dev-dependencies") if isinstance(data, dict) else None,
        category="development",
        reason="Declared Cargo development dependency.",
        confidence=0.78,
    )


def _scan_pipfile(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = tomllib.loads(source_file.content)
    except tomllib.TOMLDecodeError:
        return
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="pypi",
        mapping=data.get("packages") if isinstance(data, dict) else None,
        category="runtime",
        reason="Declared Pipfile runtime dependency.",
        confidence=0.9,
    )
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="pypi",
        mapping=data.get("dev-packages") if isinstance(data, dict) else None,
        category="development",
        reason="Declared Pipfile development dependency.",
        confidence=0.76,
    )


def _scan_composer_json(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = json.loads(source_file.content)
    except json.JSONDecodeError:
        return
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="composer",
        mapping=data.get("require") if isinstance(data, dict) else None,
        category="runtime",
        reason="Declared Composer runtime dependency.",
        confidence=0.94,
    )
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="composer",
        mapping=data.get("require-dev") if isinstance(data, dict) else None,
        category="development",
        reason="Declared Composer development dependency.",
        confidence=0.78,
    )


def _scan_go_mod(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    for line_number, raw_line in enumerate(source_file.content.splitlines() or [""], start=1):
        clean = raw_line.split("//", 1)[0].strip()
        if clean.startswith("require "):
            clean = clean.removeprefix("require ").strip()
        match = GO_REQUIRE_RE.match(clean)
        if not match:
            continue
        name = match.group(1)
        _put_dependency(
            findings,
            ecosystem="go",
            name=name,
            category="runtime",
            confidence=0.93,
            reason="Declared Go module dependency.",
            evidence=_evidence(source_file.path, line_number, raw_line, name),
        )


def _scan_gemfile(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    for line_number, raw_line in enumerate(source_file.content.splitlines() or [""], start=1):
        match = GEM_RE.match(raw_line)
        if not match:
            continue
        name = match.group(1)
        _put_dependency(
            findings,
            ecosystem="rubygems",
            name=name,
            category="runtime",
            confidence=0.92,
            reason="Declared Ruby gem dependency.",
            evidence=_evidence(source_file.path, line_number, raw_line, name),
        )


def _scan_package_lock(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = json.loads(source_file.content)
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    packages = data.get("packages")
    if isinstance(packages, dict):
        for package_path in packages:
            if not str(package_path).startswith("node_modules/"):
                continue
            name = str(package_path).removeprefix("node_modules/")
            line_number, line = _line_for_text(source_file.content, str(package_path))
            _put_dependency(
                findings,
                ecosystem="npm",
                name=name,
                category="locked",
                confidence=0.84,
                reason="Locked npm dependency.",
                evidence=_evidence(source_file.path, line_number, line, name),
            )
    dependencies = data.get("dependencies")
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="npm",
        mapping=dependencies if isinstance(dependencies, dict) else None,
        category="locked",
        reason="Locked npm dependency.",
        confidence=0.84,
    )


def _scan_pipfile_lock(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = json.loads(source_file.content)
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="pypi",
        mapping=data.get("default"),
        category="locked",
        reason="Locked Pipfile dependency.",
        confidence=0.84,
    )
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="pypi",
        mapping=data.get("develop"),
        category="development",
        reason="Locked Pipfile development dependency.",
        confidence=0.72,
    )


def _scan_poetry_lock(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = tomllib.loads(source_file.content)
    except tomllib.TOMLDecodeError:
        return
    packages = data.get("package") if isinstance(data, dict) else None
    for package in packages if isinstance(packages, list) else []:
        if not isinstance(package, dict):
            continue
        name = _clean_dependency_name(package.get("name"))
        if name is None:
            continue
        line_number, line = _line_for_text(source_file.content, str(name))
        _put_dependency(
            findings,
            ecosystem="pypi",
            name=name,
            category="locked",
            confidence=0.84,
            reason="Locked Poetry dependency.",
            evidence=_evidence(source_file.path, line_number, line, name),
        )


def _scan_composer_lock(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = json.loads(source_file.content)
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    for section, category, confidence in (("packages", "locked", 0.86), ("packages-dev", "development", 0.72)):
        packages = data.get(section)
        for package in packages if isinstance(packages, list) else []:
            if not isinstance(package, dict):
                continue
            name = _clean_dependency_name(package.get("name"))
            if name is None:
                continue
            line_number, line = _line_for_text(source_file.content, str(name))
            _put_dependency(
                findings,
                ecosystem="composer",
                name=name,
                category=category,
                confidence=confidence,
                reason="Locked Composer dependency.",
                evidence=_evidence(source_file.path, line_number, line, name),
            )


def _scan_cargo_lock(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = tomllib.loads(source_file.content)
    except tomllib.TOMLDecodeError:
        return
    packages = data.get("package") if isinstance(data, dict) else None
    for package in packages if isinstance(packages, list) else []:
        if not isinstance(package, dict):
            continue
        name = _clean_dependency_name(package.get("name"))
        if name is None:
            continue
        line_number, line = _line_for_text(source_file.content, str(name))
        _put_dependency(
            findings,
            ecosystem="cargo",
            name=name,
            category="locked",
            confidence=0.84,
            reason="Locked Cargo dependency.",
            evidence=_evidence(source_file.path, line_number, line, name),
        )


def _scan_gemfile_lock(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    for line_number, raw_line in enumerate(source_file.content.splitlines() or [""], start=1):
        match = GEM_LOCK_RE.match(raw_line)
        if not match:
            continue
        name = match.group(1)
        _put_dependency(
            findings,
            ecosystem="rubygems",
            name=name,
            category="locked",
            confidence=0.82,
            reason="Locked Ruby gem dependency.",
            evidence=_evidence(source_file.path, line_number, raw_line, name),
        )


def _lock_package_from_locator(locator: str) -> str | None:
    clean = locator.strip().strip("\"'")
    if clean.startswith((".", "/")):
        return None
    if clean.startswith("@"):
        parts = clean.split("@")
        return f"@{parts[1]}" if len(parts) > 1 else None
    return clean.split("@", 1)[0]


def _scan_yarn_lock(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    for line_number, raw_line in enumerate(source_file.content.splitlines() or [""], start=1):
        match = YARN_LOCK_RE.match(raw_line)
        if not match:
            continue
        name = _lock_package_from_locator(match.group(1))
        if name is None:
            continue
        _put_dependency(
            findings,
            ecosystem="npm",
            name=name,
            category="locked",
            confidence=0.78,
            reason="Locked Yarn dependency.",
            evidence=_evidence(source_file.path, line_number, raw_line, name),
        )


def _scan_lockfile_dependencies(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    name = source_file.path.rsplit("/", 1)[-1].lower()
    if name in {"package-lock.json", "npm-shrinkwrap.json"}:
        _scan_package_lock(findings, source_file)
    elif name == "pipfile.lock":
        _scan_pipfile_lock(findings, source_file)
    elif name == "poetry.lock":
        _scan_poetry_lock(findings, source_file)
    elif name == "composer.lock":
        _scan_composer_lock(findings, source_file)
    elif name == "cargo.lock":
        _scan_cargo_lock(findings, source_file)
    elif name == "gemfile.lock":
        _scan_gemfile_lock(findings, source_file)
    elif name in {"yarn.lock", "pnpm-lock.yaml"}:
        _scan_yarn_lock(findings, source_file)


def _external_js_package(value: str) -> str | None:
    if value.startswith((".", "/", "http://", "https://")):
        return None
    parts = value.split("/")
    if value.startswith("@") and len(parts) >= JS_SCOPED_PACKAGE_PARTS:
        return "/".join(parts[:JS_SCOPED_PACKAGE_PARTS])
    return parts[0]


def _scan_js_import_dependencies(
    findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str
) -> None:
    for match in JS_IMPORT_RE.finditer(line):
        name = _external_js_package(match.group("from") or match.group("call") or "")
        if name:
            _put_dependency(
                findings,
                ecosystem="npm",
                name=name,
                category="imported",
                confidence=0.7,
                reason="Imported JavaScript package.",
                evidence=_evidence(path, line_number, line, name),
            )


def _scan_python_import_dependencies(
    findings: dict[tuple[str, str], Finding],
    path: str,
    line_number: int,
    line: str,
    local_python_roots: set[str],
) -> None:
    match = PY_IMPORT_RE.match(line)
    if not match:
        return
    name = (match.group(1) or match.group(2) or "").split(".", 1)[0]
    if name and name not in sys.stdlib_module_names and name not in local_python_roots:
        _put_dependency(
            findings,
            ecosystem="pypi",
            name=name,
            category="imported",
            confidence=0.68,
            reason="Imported Python module; verify whether it is external.",
            evidence=_evidence(path, line_number, line, name),
        )


def _scan_php_import_dependencies(
    findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str
) -> None:
    match = PHP_USE_RE.match(line)
    if not match:
        return
    name = match.group(1).split("\\", 1)[0]
    _put_dependency(
        findings,
        ecosystem="composer",
        name=name,
        category="imported",
        confidence=0.62,
        reason="Imported PHP namespace; verify whether it is external.",
        evidence=_evidence(path, line_number, line, name),
    )


def _scan_ruby_import_dependencies(
    findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str
) -> None:
    match = RUBY_REQUIRE_RE.match(line)
    if not match:
        return
    name = match.group(1)
    _put_dependency(
        findings,
        ecosystem="rubygems",
        name=name,
        category="imported",
        confidence=0.62,
        reason="Required Ruby library; verify whether it is external.",
        evidence=_evidence(path, line_number, line, name),
    )


def _scan_import_dependencies(
    findings: dict[tuple[str, str], Finding],
    path: str,
    line_number: int,
    line: str,
    local_python_roots: set[str],
) -> None:
    suffix = _suffix(path)
    if suffix in {".js", ".ts", ".tsx", ".vue"}:
        _scan_js_import_dependencies(findings, path, line_number, line)
    elif suffix == ".py":
        _scan_python_import_dependencies(findings, path, line_number, line, local_python_roots)
    elif suffix == ".php":
        _scan_php_import_dependencies(findings, path, line_number, line)
    elif suffix == ".rb":
        _scan_ruby_import_dependencies(findings, path, line_number, line)


def _scan_manifest_dependencies(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    name = source_file.path.rsplit("/", 1)[-1].lower()
    if name == "package.json":
        _scan_package_json(findings, source_file)
    elif name.startswith("requirements") and name.endswith(".txt"):
        _scan_requirements_txt(findings, source_file)
    elif name in {"pyproject.toml", "cargo.toml"}:
        _scan_pyproject_toml(findings, source_file)
    elif name == "pipfile":
        _scan_pipfile(findings, source_file)
    elif name == "composer.json":
        _scan_composer_json(findings, source_file)
    elif name == "go.mod":
        _scan_go_mod(findings, source_file)
    elif name == "gemfile":
        _scan_gemfile(findings, source_file)
    elif name in LOCKFILE_KINDS:
        _scan_lockfile_dependencies(findings, source_file)


def _local_python_import_roots(files: list[SourceFile]) -> set[str]:
    roots = set(LOCAL_IMPORT_ROOTS)
    for source_file in files:
        if _suffix(source_file.path) != ".py":
            continue
        parts = source_file.path.split("/")
        name = parts[-1]
        if name == "__init__.py" and len(parts) > 1:
            roots.add(parts[-2])
        elif name.endswith(".py"):
            roots.add(name[:-3])
    return roots


def _project_from_host(host: str, sub: str, family: str) -> tuple[str, str, float]:
    if host == "commons.wikimedia.org":
        return "commonswiki", "Commons", 0.94
    if host in {"wikidata.org", "www.wikidata.org", "query.wikidata.org"}:
        return "wikidatawiki", "Wikidata", 0.94
    if host == "meta.wikimedia.org":
        return "metawiki", "Meta-Wiki", 0.94
    if host in {"mediawiki.org", "www.mediawiki.org"}:
        return "mediawikiwiki", "MediaWiki.org", 0.92
    if family == "wikipedia" and sub and sub != "www":
        return f"{sub}wiki", host, 0.9
    return host, host, 0.78


def _bounded_line(raw: str) -> str:
    """Return the line cut to budget, without splitting the token at the cut.

    A contributor table in a README is one very long line of URLs, and cutting
    it at a fixed width left `https://avatars.githubusercon` behind -- a name
    that parses as a hostname, resolves nowhere, and reads in a report as a
    real service the tool contacts. Dropping the partial token at the cut
    costs at most one hit and invents none.

    A line with no whitespace in it at all -- minified JavaScript, a long data
    URI -- has no token boundary to cut back to and is left as it was.
    """
    if len(raw) <= MAX_LINE_CHARS:
        return raw
    head, space, _ = raw[:MAX_LINE_CHARS].rpartition(" ")
    return head if space else raw[:MAX_LINE_CHARS]


def _external_endpoint_count(endpoints: list[dict[str, Any]]) -> int:
    return sum(1 for item in endpoints if item["category"] == source_endpoints.FAMILY_EXTERNAL)


def _scan_endpoints(
    findings: dict[tuple[str, str], Finding],
    path: str,
    line_number: int,
    line: str,
    *,
    require_call: bool,
) -> None:
    """Record the concrete addresses this line names, host and path and action.

    Complements the apis bucket rather than duplicating it. API_RULES says a
    tool speaks the Action API; this says it speaks it to commons.wikimedia.org
    with action=upload, which is the difference between a reader and a writer,
    and it is the only scanner that sees a service Wikimedia does not run.
    """
    # The signal has to be looked for around the URL, not inside it. A path
    # like /creating-a-pull-request-from-a-fork carries the word `request`, and
    # reading that as a call promoted a line of prose in CONTRIBUTING.md to the
    # same confidence as a fetch.
    called = bool(REQUEST_SIGNAL_RE.search(source_endpoints.URL_RE.sub(" ", line)))
    if require_call and not called:
        return
    for endpoint in source_endpoints.endpoints(line):
        _put(
            findings,
            kind="endpoints",
            value=endpoint.value,
            label=endpoint.label,
            category=endpoint.family,
            confidence=ENDPOINT_CALLED_CONFIDENCE if called else ENDPOINT_CONFIDENCE,
            reason=("Request to this endpoint." if called else "Endpoint address in source."),
            evidence=_evidence(path, line_number, line, endpoint.value),
        )


def _scan_projects(findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str) -> None:
    for match in PROJECT_DOMAIN_RE.finditer(line):
        host = match.group(0).lower()
        value, label, confidence = _project_from_host(host, match.group("sub") or "", match.group("family").lower())
        _put(
            findings,
            kind="projects",
            value=value,
            label=label,
            category="wiki",
            confidence=confidence,
            reason="Wikimedia project hostname detected.",
            evidence=_evidence(path, line_number, line, host),
        )
    for match in PROJECT_DB_RE.finditer(line):
        value = match.group(0).lower()
        if value in IGNORED_PROJECT_DB_NAMES or value.endswith("mediawiki"):
            continue
        _put(
            findings,
            kind="projects",
            value=value,
            label=value,
            category="wiki",
            confidence=0.76,
            reason="Wikimedia database name detected.",
            evidence=_evidence(path, line_number, line, value),
        )


def _scan_rules(  # noqa: PLR0913 - scan context plus rule table is clearer as named parameters.
    findings: dict[tuple[str, str], Finding],
    path: str,
    line_number: int,
    line: str,
    rules: tuple[tuple[str, str, re.Pattern[str], float, str], ...],
    *,
    kind: str,
) -> None:
    for value, label, pattern, confidence, reason in rules:
        match = pattern.search(line)
        if match:
            _put(
                findings,
                kind=kind,
                value=value,
                label=label,
                category="detected",
                confidence=confidence,
                reason=reason,
                evidence=_evidence(path, line_number, line, match.group(0)),
            )


def _scan_technology(findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str) -> None:
    suffix = _suffix(path)
    if line_number == 1 and suffix in TECH_BY_EXTENSION:
        value = TECH_BY_EXTENSION[suffix]
        _put(
            findings,
            kind="technology",
            value=value,
            label=value,
            category="language",
            confidence=0.64,
            reason="Source file extension detected.",
            evidence=_evidence(path, line_number, line, suffix),
        )
    for value, pattern, confidence in TECH_RULES:
        match = pattern.search(line)
        if match:
            _put(
                findings,
                kind="technology",
                value=value,
                label=value,
                category="framework",
                confidence=confidence,
                reason="Framework or library usage detected.",
                evidence=_evidence(path, line_number, line, match.group(0)),
            )


def _scan_actions(findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str) -> None:
    actions = [match.group(1).lower() for match in ACTION_QUERY_RE.finditer(line)]
    actions.extend(match.group(1).lower() for match in ACTION_OBJECT_RE.finditer(line))
    for action in actions:
        _put(
            findings,
            kind="apis",
            value="mediawiki-action-api",
            label="MediaWiki Action API",
            category="detected",
            confidence=0.9,
            reason=f"MediaWiki action={action} request detected.",
            evidence=_evidence(path, line_number, line, action),
        )
        if action in READ_ACTIONS:
            _put(
                findings,
                kind="accessRights",
                value="read-public",
                label="Read public wiki data",
                category="read",
                confidence=0.66,
                reason=f"Read-only action={action} request detected.",
                evidence=_evidence(path, line_number, line, action),
            )
        for value, label, category, confidence in ACTION_RIGHTS.get(action, ()):
            _put(
                findings,
                kind="accessRights",
                value=value,
                label=label,
                category=category,
                confidence=confidence,
                reason=f"MediaWiki action={action} usually requires {label.lower()}.",
                evidence=_evidence(path, line_number, line, action),
            )


def _scan_oauth_scopes(findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str) -> None:
    if not SCOPE_LINE_RE.search(line):
        return
    lower = line.lower()
    for scope, (label, confidence) in KNOWN_OAUTH_SCOPES.items():
        if re.search(rf"\b{re.escape(scope)}\b", lower):
            _put(
                findings,
                kind="oauthScopes",
                value=scope,
                label=label,
                category="scope",
                confidence=confidence,
                reason="OAuth scope string detected.",
                evidence=_evidence(path, line_number, line, scope),
            )


def _scan_warnings(findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str) -> None:
    match = CREDENTIAL_RE.search(line)
    if match:
        _put(
            findings,
            kind="warnings",
            value="credential-like-source",
            label="Credential-looking value in source",
            category="privacy",
            confidence=0.8,
            reason="A credential-like assignment was detected and redacted from evidence.",
            evidence=_evidence(path, line_number, line, match.group(0).split("=", 1)[0]),
        )


def _finding_rank(finding: Finding) -> tuple[float, int, int, tuple[float, int, str], str]:
    """Rank a finding for the per-bucket cap, the one most worth keeping first.

    Confidence decides first, and on most repositories it decides everything. But
    confidence is computed from a small set of ingredients, so a repository that
    names many addresses the same way produces a long block of findings that score
    identically -- on pageviews, thirty of them at 0.74 -- and the cap of forty falls
    inside that block. Sorting the block by label let the alphabet choose which half
    survived, and it chose badly: the tool's own API surface, the
    `wikimedia.org/api/rest_v1/metrics/*` calls its charts are built from, sorted
    below self-referential `pageviews.*` links copied out of the landing pages, and
    was cut.

    So the block is ordered by what is known about each finding beyond its score.
    First how many separate files said it, then how many times in total: a finding
    two files agree on is better attested than one a single generated table repeats.
    What settles the rest is where the best sighting came from, by the same reading
    rank that decided which files were worth opening at all. A finding read out of
    the code the tool is made of outranks one read out of a page describing the tool,
    and the ranking that chose the files now also chooses among what they said. The
    label remains the last resort, so two runs over one tree agree.

    The rank reads the finding rather than its payload because the payload rounds
    confidence to two places and keeps only the first few pieces of evidence. Ranking
    the rounded form invents ties that do not exist, and then breaks them without the
    evidence that would have settled them.
    """
    paths = {str(evidence["path"]) for evidence in finding.evidence}
    return (
        -finding.confidence,
        -len(paths),
        -len(finding.evidence),
        min(source_reading_rank(path) for path in paths),
        finding.label,
    )


def _serialized(findings: dict[tuple[str, str], Finding], kind: str) -> list[dict[str, Any]]:
    ranked = sorted(
        (finding for (finding_kind, _), finding in findings.items() if finding_kind == kind),
        key=_finding_rank,
    )
    return [finding.payload() for finding in ranked[:MAX_FINDINGS_PER_BUCKET]]


def _is_publishable_finding(item: dict[str, Any], min_confidence: float = EVOLVED_METADATA_MIN_CONFIDENCE) -> bool:
    return (
        float(item.get("confidence") or 0) >= min_confidence
        and float(item.get("maxSourceWeight") or SOURCE_CLASS_WEIGHTS["unknown"]) >= SUGGESTION_MIN_SOURCE_WEIGHT
    )


def _publishable_rows(
    rows: list[dict[str, Any]], min_confidence: float = EVOLVED_METADATA_MIN_CONFIDENCE
) -> list[dict[str, Any]]:
    return [row for row in rows if _is_publishable_finding(row, min_confidence)]


def _has_category(rows: list[dict[str, Any]], category: str, min_confidence: float = 0.0) -> bool:
    return any(row.get("category") == category and float(row.get("confidence") or 0) >= min_confidence for row in rows)


def _has_write_access(rows: list[dict[str, Any]], min_confidence: float = 0.0) -> bool:
    return any(
        row.get("category") in {"administrator", "moderation", "write"}
        and float(row.get("confidence") or 0) >= min_confidence
        for row in rows
    )


def _tool_type_suggestion(technology: list[dict[str, Any]], apis: list[dict[str, Any]]) -> str | None:
    tech_values = {str(item.get("value")) for item in technology}
    api_values = {str(item.get("value")) for item in apis}
    # A gadget is JavaScript a wiki serves into a reader's page. It has no
    # server, so nothing that ships one can be a gadget however much MediaWiki
    # JavaScript it contains -- and the gadget rule is the loosest here, firing
    # on a bare `mw.Api` mention anywhere in a repository, including in a test
    # fixture or a regex. Checking the server evidence first is what stops a
    # Flask application that talks to MediaWiki being catalogued as a gadget.
    if "MediaWiki gadget" in tech_values and not tech_values & SERVER_TECHNOLOGIES:
        return "gadget"
    if tech_values & {"Flask", "Django", "React", "Node.js", "Vue"}:
        return "web app"
    if "Pywikibot" in tech_values and api_values & {"mediawiki-action-api", "wikibase-api"}:
        return "bot"
    return None


def _add_cross_file_warnings(findings: dict[tuple[str, str], Finding], report: dict[str, Any]) -> None:
    access = report["accessRights"]
    auth = report["authentication"]
    warning_evidence = {
        "path": "analysis",
        "line": 0,
        "match": "cross-file",
        "excerpt": "Derived from aggregated source-analysis findings.",
    }
    if _has_category(access, "administrator", SCORING_MIN_CONFIDENCE):
        _put(
            findings,
            kind="warnings",
            value="administrator-actions",
            label="Administrator or suppressive actions detected",
            category="review",
            confidence=0.86,
            reason="Source references actions that usually require elevated wiki rights.",
            evidence=warning_evidence,
        )
    if _has_write_access(access, SCORING_MIN_CONFIDENCE) and not _publishable_rows(auth, SCORING_MIN_CONFIDENCE):
        _put(
            findings,
            kind="warnings",
            value="write-without-auth-signal",
            label="Write actions without an authentication signal",
            category="review",
            confidence=0.74,
            reason="Write actions were detected, but OAuth, bot-password, or token handling was not.",
            evidence=warning_evidence,
        )


def _clean_context_string(value: object) -> str | None:
    text = str(value or "").strip()
    return text[:MAX_CONTEXT_STRING_CHARS] if text else None


def _clean_context_list(value: object) -> list[str]:
    rows = value if isinstance(value, list | tuple | set) else [value]
    cleaned = [_clean_context_string(item) for item in rows]
    return sorted({item for item in cleaned if item})[:MAX_CONTEXT_LIST_ITEMS]


def _clean_context_value(value: object) -> str | int | bool | list[str] | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, list | tuple | set):
        return _clean_context_list(value)
    return _clean_context_string(value)


def _clean_context_object(value: object, allowed_keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for key in sorted(allowed_keys):
        cleaned_value = _clean_context_value(value.get(key))
        if cleaned_value not in (None, [], ""):
            cleaned[key] = cleaned_value
    return cleaned


def _normalize_repository_context(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        message = "repositoryContext must be an object"
        raise SourceAnalysisError(message)
    repository = _clean_context_object(value.get("repository"), REPOSITORY_CONTEXT_REPOSITORY_KEYS)
    declared = _clean_context_object(value.get("declared"), REPOSITORY_CONTEXT_DECLARED_KEYS)
    maintainers = _clean_context_object(value.get("maintainers"), REPOSITORY_CONTEXT_MAINTAINER_KEYS)
    lifecycle = _clean_context_object(value.get("lifecycle"), REPOSITORY_CONTEXT_LIFECYCLE_KEYS)
    result: dict[str, Any] = {}
    if repository:
        result["repository"] = repository
    if declared:
        result["declared"] = declared
    if maintainers:
        result["maintainers"] = maintainers
    if lifecycle:
        result["lifecycle"] = lifecycle
    return result


def _context_item(kind: str, path: str) -> dict[str, str]:
    return {"kind": kind, "path": path, "sourceClass": _source_class(path)}


def _documentation_kind(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1].lower()
    if name in DOCUMENTATION_FILE_KINDS:
        return DOCUMENTATION_FILE_KINDS[name]
    if name.startswith("readme."):
        return "readme"
    if name.startswith("license."):
        return "license"
    return None


def _ci_kind(path: str) -> str | None:
    normalized = path.lower()
    name = normalized.rsplit("/", 1)[-1]
    if normalized.startswith(".github/workflows/") and _suffix(normalized) in {".yaml", ".yml"}:
        return "github-actions"
    return CI_FILE_KINDS.get(normalized) or CI_FILE_KINDS.get(name)


def _runtime_kind(path: str) -> str | None:
    normalized = path.lower()
    name = normalized.rsplit("/", 1)[-1]
    if normalized.startswith(".toolforge/") or "/.toolforge/" in normalized:
        return "toolforge"
    return RUNTIME_FILE_KINDS.get(name)


def _test_kind(path: str) -> str | None:
    normalized = path.lower()
    name = normalized.rsplit("/", 1)[-1]
    if normalized.startswith("tests/") or "/tests/" in normalized:
        return "test-suite"
    if re.search(r"(?:^test_|_test\.|\.test\.|\.spec\.)", name):
        return "test-file"
    return None


def _line_match_item(kind: str, source_file: SourceFile, pattern: re.Pattern[str]) -> dict[str, Any] | None:
    for line_number, line in enumerate(source_file.content.splitlines() or [""], start=1):
        match = pattern.search(line)
        if match:
            source_class = _source_class(source_file.path)
            return {
                "kind": kind,
                "path": source_file.path,
                "line": line_number,
                "match": match.group(0)[:80],
                "sourceClass": source_class,
                "sourceWeight": SOURCE_CLASS_WEIGHTS.get(source_class, SOURCE_CLASS_WEIGHTS["unknown"]),
            }
    return None


def _sorted_context_items(index: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    return [index[key] for key in sorted(index)[:MAX_CONTEXT_LIST_ITEMS]]


def _extension_counts(files: list[SourceFile]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for source_file in files:
        extension = _suffix(source_file.path) or source_file.path.rsplit("/", 1)[-1].lower()
        counts[extension] = counts.get(extension, 0) + 1
    return [{"extension": key, "count": counts[key]} for key in sorted(counts)]


def _top_level_directories(files: list[SourceFile]) -> list[str]:
    roots = {source_file.path.split("/", 1)[0] for source_file in files if "/" in source_file.path}
    return sorted(roots)[:MAX_CONTEXT_LIST_ITEMS]


def _source_class_counts(files: list[SourceFile]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for source_file in files:
        source_class = _source_class(source_file.path)
        counts[source_class] = counts.get(source_class, 0) + 1
    return [
        {"class": key, "count": counts[key], "weight": SOURCE_CLASS_WEIGHTS.get(key, SOURCE_CLASS_WEIGHTS["unknown"])}
        for key in sorted(counts)[:MAX_SOURCE_CLASS_ITEMS]
    ]


def _dependency_source_context(report: dict[str, Any]) -> dict[str, Any]:
    categories: dict[str, int] = {}
    ecosystems: set[str] = set()
    for item in report["dependencies"]:
        category = str(item.get("category") or "detected")
        categories[category] = categories.get(category, 0) + 1
        value = str(item.get("value") or "")
        if ":" in value:
            ecosystems.add(value.split(":", 1)[0])
    return {
        "count": len(report["dependencies"]),
        "ecosystems": sorted(ecosystems),
        "categories": [{"category": key, "count": categories[key]} for key in sorted(categories)],
    }


def _file_context_items(source_file: SourceFile) -> list[tuple[str, str, dict[str, Any]]]:
    path = source_file.path
    name = path.rsplit("/", 1)[-1].lower()
    direct_items = (
        ("documentation", _documentation_kind(path)),
        ("manifests", _manifest_kind(path)),
        ("lockfiles", LOCKFILE_KINDS.get(name)),
        ("ci", _ci_kind(path)),
        ("runtime", _runtime_kind(path)),
        ("tests", _test_kind(path)),
    )
    rows = [(section, str(kind), _context_item(str(kind), path)) for section, kind in direct_items if kind is not None]
    matched_items = (
        ("health", _line_match_item("health-endpoint", source_file, HEALTH_SIGNAL_RE)),
        ("accessibility", _line_match_item("accessibility-signal", source_file, A11Y_SIGNAL_RE)),
    )
    rows.extend((section, str(item["kind"]), item) for section, item in matched_items if item is not None)
    return rows


def _empty_repository_context_indexes() -> dict[str, dict[tuple[str, str], dict[str, Any]]]:
    return {
        key: {}
        for key in ("documentation", "manifests", "lockfiles", "ci", "runtime", "tests", "health", "accessibility")
    }


def _repository_context_from_files(
    files: list[SourceFile], report: dict[str, Any], repository_context: object
) -> dict[str, Any]:
    external = _normalize_repository_context(repository_context)
    indexes = _empty_repository_context_indexes()
    for source_file in files:
        for section, kind, item in _file_context_items(source_file):
            indexes[section][(kind, source_file.path)] = item
    context: dict[str, Any] = {
        "schemaVersion": 1,
        "inventory": {
            "filesAnalyzed": len(files),
            "byExtension": _extension_counts(files),
            "bySourceClass": _source_class_counts(files),
            "topLevelDirectories": _top_level_directories(files),
        },
        "documentation": _sorted_context_items(indexes["documentation"]),
        "manifests": _sorted_context_items(indexes["manifests"]),
        "lockfiles": _sorted_context_items(indexes["lockfiles"]),
        "ci": _sorted_context_items(indexes["ci"]),
        "runtime": _sorted_context_items(indexes["runtime"]),
        "tests": _sorted_context_items(indexes["tests"]),
        "health": _sorted_context_items(indexes["health"]),
        "accessibility": _sorted_context_items(indexes["accessibility"]),
        "dependencySources": _dependency_source_context(report),
    }
    context.update(external)
    maintenance = _repository_maintenance_context(context.get("repository"))
    if maintenance:
        context["maintenance"] = maintenance
    maintainer_activity = _maintainer_activity_context(context.get("maintainers"), context.get("repository"))
    if maintainer_activity:
        context["maintainerActivity"] = maintainer_activity
    return context


def _context_kinds(context: dict[str, Any], section: str) -> set[str]:
    rows = context.get(section)
    return {str(item.get("kind")) for item in rows if isinstance(item, dict)} if isinstance(rows, list) else set()


def _declared_list(context: dict[str, Any], key: str) -> set[str]:
    declared = context.get("declared")
    value = declared.get(key) if isinstance(declared, dict) else []
    return {str(item) for item in value} if isinstance(value, list) else set()


def _category_counts(context: dict[str, Any]) -> dict[str, int]:
    dependency_sources = context.get("dependencySources")
    rows = dependency_sources.get("categories") if isinstance(dependency_sources, dict) else []
    return {
        str(row.get("category")): int(row.get("count") or 0)
        for row in rows
        if isinstance(row, dict) and row.get("category")
    }


def _parse_iso_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _int_context_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _last_commit_age_days(repository: dict[str, Any]) -> int | None:
    provided_age = _int_context_value(repository.get("lastCommitAgeDays"))
    if provided_age is not None:
        return max(0, provided_age)
    last_commit = _parse_iso_datetime(repository.get("lastCommitAt"))
    analyzed_at = _parse_iso_datetime(repository.get("analyzedAt"))
    if last_commit is None or analyzed_at is None:
        return None
    return max(0, (analyzed_at - last_commit).days)


def _activity_status(age_days: int | None, *, archived: bool = False) -> str:
    # Archived outranks age and is terminal. An archived repository is
    # read-only, so its commit age measures the archive flag rather than
    # neglect -- running the recency ladder on it would score our own
    # observation. Only repositories have this; _maintainer_status describes a
    # person, and a person cannot be archived.
    if archived:
        return "archived"
    if age_days is None:
        return "unknown"
    if age_days <= ACTIVE_REPOSITORY_DAYS:
        return "active"
    if age_days <= QUIET_REPOSITORY_DAYS:
        return "quiet"
    if age_days <= STALE_REPOSITORY_DAYS:
        return "stale"
    return "dormant"


def _maintainer_status(age_days: int | None) -> str:
    if age_days is None:
        return "unknown"
    if age_days <= ACTIVE_MAINTAINER_DAYS:
        return "active"
    if age_days <= QUIET_MAINTAINER_DAYS:
        return "quiet"
    if age_days <= STALE_MAINTAINER_DAYS:
        return "stale"
    return "dormant"


def _repository_maintenance_context(repository: object) -> dict[str, Any]:
    if not isinstance(repository, dict) or not repository:
        return {}
    age_days = _last_commit_age_days(repository)
    archived = repository.get("archived") is True
    status = _activity_status(age_days, archived=archived)
    contributor_count = _int_context_value(repository.get("contributorCount"))
    commit_count = _int_context_value(repository.get("commitCount"))
    signals: list[dict[str, Any]] = []
    # First, because it is the fact that decides the status and the signal list
    # is truncated to MAX_ASSESSMENT_SIGNALS.
    if archived:
        signals.append({"kind": "archived", "value": True})
    if age_days is not None:
        signals.append({"kind": "last-commit-age", "value": age_days, "unit": "days"})
    if contributor_count is not None:
        signals.append({"kind": "contributor-count", "value": contributor_count})
    if commit_count is not None:
        signals.append({"kind": "commit-count", "value": commit_count})
    if repository.get("dirty") is True:
        signals.append({"kind": "dirty-checkout", "value": True})
    return {
        "status": status,
        # Archived is deliberately not stale. Stale means work was expected and
        # did not arrive; archived means no work is expected at all, so the
        # outreach paths keyed on this flag must not fire.
        "stale": status in {"stale", "dormant"},
        "archived": archived,
        "lastCommitAgeDays": age_days,
        "contributorCount": contributor_count,
        "commitCount": commit_count,
        "signals": signals[:MAX_ASSESSMENT_SIGNALS],
    }


def _maintainer_activity_context(maintainers: object, repository: object) -> dict[str, Any]:
    if not isinstance(maintainers, dict) or not maintainers:
        return {}
    age_days = _int_context_value(maintainers.get("lastActivityAgeDays"))
    if age_days is None:
        last_activity = _parse_iso_datetime(maintainers.get("lastActivityAt"))
        analyzed_at = _parse_iso_datetime(maintainers.get("analyzedAt"))
        if analyzed_at is None and isinstance(repository, dict):
            analyzed_at = _parse_iso_datetime(repository.get("analyzedAt"))
        if last_activity is not None and analyzed_at is not None:
            age_days = max(0, (analyzed_at - last_activity).days)
    status = _maintainer_status(age_days)
    maintainer_count = _int_context_value(maintainers.get("maintainerCount"))
    active_count = _int_context_value(maintainers.get("activeMaintainerCount"))
    recent_activity_count = _int_context_value(maintainers.get("recentActivityCount"))
    signals: list[dict[str, Any]] = []
    if age_days is not None:
        signals.append({"kind": "last-maintainer-activity-age", "value": age_days, "unit": "days"})
    if maintainer_count is not None:
        signals.append({"kind": "maintainer-count", "value": maintainer_count})
    if active_count is not None:
        signals.append({"kind": "active-maintainer-count", "value": active_count})
    if recent_activity_count is not None:
        signals.append({"kind": "recent-maintainer-activity-count", "value": recent_activity_count})
    source = _clean_context_string(maintainers.get("source"))
    if source:
        signals.append({"kind": "maintainer-activity-source", "value": source})
    return {
        "status": status,
        "stale": status in {"stale", "dormant"},
        "lastActivityAgeDays": age_days,
        "maintainerCount": maintainer_count,
        "activeMaintainerCount": active_count,
        "recentActivityCount": recent_activity_count,
        "signals": signals[:MAX_ASSESSMENT_SIGNALS],
    }


def _first_finding_evidence(report: dict[str, Any], bucket: str) -> dict[str, Any] | None:
    rows = report.get(bucket)
    for row in rows if isinstance(rows, list) else []:
        evidence = row.get("evidence") if isinstance(row, dict) else []
        if isinstance(evidence, list) and evidence:
            return evidence[0]
    return None


def _first_context_evidence(context: dict[str, Any], section: str, kind: str | None = None) -> dict[str, Any] | None:
    rows = context.get(section)
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if kind is None or row.get("kind") == kind:
            return {
                "path": row.get("path", ""),
                "line": row.get("line", 0),
                "match": row.get("match", ""),
                "excerpt": row.get("kind", ""),
            }
    return None


def _score_grade(score: int) -> str:
    if score >= ASSESSMENT_STRONG_SCORE:
        return "strong"
    if score >= ASSESSMENT_GOOD_SCORE:
        return "good"
    if score >= ASSESSMENT_ATTENTION_SCORE:
        return "needs-attention"
    return "high-risk"


def _bounded_score(value: int) -> int:
    return max(0, min(100, value))


def _assessment_signal(
    status: str, label: str, detail: str = "", evidence: dict[str, Any] | None = None
) -> dict[str, Any]:
    signal: dict[str, Any] = {"status": status, "label": label}
    if detail:
        signal["detail"] = detail
    if evidence:
        signal["evidence"] = evidence
    return signal


def _assessment(  # noqa: PLR0913, PLR0917 - assessment payload fields are clearer as explicit arguments.
    key: str,
    label: str,
    score: int,
    confidence: float,
    summary: str,
    signals: list[dict[str, Any]],
    recommendations: list[str],
) -> dict[str, Any]:
    bounded = _bounded_score(score)
    return {
        "key": key,
        "label": label,
        "score": bounded,
        "grade": _score_grade(bounded),
        "confidence": round(max(0.1, min(0.99, confidence)), 2),
        "summary": summary,
        "signals": signals[:MAX_ASSESSMENT_SIGNALS],
        "recommendations": recommendations[:MAX_ASSESSMENT_SIGNALS],
    }


def _metadata_completeness_assessment(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    documentation = _context_kinds(context, "documentation")
    score = 20
    signals: list[dict[str, Any]] = []
    recommendations: list[str] = []
    buckets = (
        ("projects", "Projects detected", "Add target wiki/project metadata.", 15),
        ("apis", "API usage detected", "Document which APIs the tool uses.", 15),
        ("technology", "Technology detected", "Declare the tool technology stack.", 15),
        ("dependencies", "Dependencies detected", "Declare key external libraries.", 15),
    )
    for bucket, label, recommendation, points in buckets:
        has_bucket = bool(_publishable_rows(report.get(bucket, []), SCORING_MIN_CONFIDENCE))
        score += points if has_bucket else 0
        if has_bucket:
            signals.append(_assessment_signal("positive", label, evidence=_first_finding_evidence(report, bucket)))
        else:
            signals.append(_assessment_signal("negative", recommendation))
            recommendations.append(recommendation)
    if "readme" in documentation:
        score += 10
        signals.append(
            _assessment_signal(
                "positive", "README present", evidence=_first_context_evidence(context, "documentation", "readme")
            )
        )
    else:
        recommendations.append("Add a README with purpose, setup, and usage.")
    if "license" in documentation:
        score += 10
        signals.append(
            _assessment_signal(
                "positive",
                "License file present",
                evidence=_first_context_evidence(context, "documentation", "license"),
            )
        )
    else:
        recommendations.append("Add a license file or declare the license in Toolhub.")
    return _assessment(
        "metadata-completeness",
        "Metadata completeness",
        score,
        0.72 + min(0.2, len(signals) * 0.02),
        "How much useful Toolhub metadata can be derived from the submitted context.",
        signals,
        recommendations,
    )


def _permission_clarity_assessment(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    raw_access = report["accessRights"]
    access = _publishable_rows(raw_access, SCORING_MIN_CONFIDENCE)
    auth = _publishable_rows(report["authentication"], SCORING_MIN_CONFIDENCE)
    scopes = {item["value"] for item in _publishable_rows(report["oauthScopes"], SCORING_MIN_CONFIDENCE)}
    declared_scopes = _declared_list(context, "oauthScopes")
    admin_access = _has_category(access, "administrator", SCORING_MIN_CONFIDENCE)
    write_access = _has_write_access(access, SCORING_MIN_CONFIDENCE)
    signals: list[dict[str, Any]] = []
    recommendations: list[str] = []
    score = 55
    if not access:
        if raw_access:
            signals.append(_assessment_signal("neutral", "Only low-provenance access evidence found"))
            recommendations.append("Confirm whether low-provenance access strings describe runtime behavior.")
        else:
            signals.append(_assessment_signal("neutral", "No MediaWiki access actions detected"))
            recommendations.append("Confirm whether the tool is read-only or needs wiki permissions.")
    elif write_access:
        score = 65
        signals.append(
            _assessment_signal(
                "neutral", "Write-capable actions detected", evidence=_first_finding_evidence(report, "accessRights")
            )
        )
        if auth:
            score += 15
            signals.append(
                _assessment_signal(
                    "positive",
                    "Authentication handling detected",
                    evidence=_first_finding_evidence(report, "authentication"),
                )
            )
        else:
            score -= 25
            signals.append(_assessment_signal("negative", "No authentication signal found for write actions"))
            recommendations.append("Document OAuth, bot-password, or token handling for write actions.")
        if scopes:
            score += 10
            signals.append(
                _assessment_signal("positive", "OAuth scopes inferred from source", detail=", ".join(sorted(scopes)))
            )
        else:
            recommendations.append("Declare the OAuth scopes required by this tool.")
        if admin_access:
            score -= 20
            signals.append(_assessment_signal("negative", "Elevated wiki actions detected"))
            recommendations.append("Separate administrator-level actions from normal user workflows.")
    else:
        score = 90
        signals.append(
            _assessment_signal(
                "positive",
                "Only read-oriented actions detected",
                evidence=_first_finding_evidence(report, "accessRights"),
            )
        )
    if declared_scopes:
        score += 5
        signals.append(
            _assessment_signal("positive", "Declared OAuth scopes supplied", detail=", ".join(sorted(declared_scopes)))
        )
        missing = sorted(scopes - declared_scopes)
        if missing:
            score -= 15
            signals.append(
                _assessment_signal(
                    "negative", "Inferred scopes missing from declared context", detail=", ".join(missing)
                )
            )
            recommendations.append("Reconcile declared OAuth scopes with source-code usage.")
    return _assessment(
        "permission-clarity",
        "Permission clarity",
        score,
        0.66 + min(0.25, len(access + auth + raw_access) * 0.03),
        "How clearly the source explains required wiki access, OAuth scopes, and authentication.",
        signals,
        recommendations,
    )


def _dependency_health_assessment(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    categories = _category_counts(context)
    has_manifest = bool(context.get("manifests"))
    has_lockfile = bool(context.get("lockfiles"))
    dependency_count = len(_publishable_rows(report["dependencies"], SCORING_MIN_CONFIDENCE))
    signals: list[dict[str, Any]] = []
    recommendations: list[str] = []
    score = 40
    if has_manifest:
        score += 20
        signals.append(
            _assessment_signal(
                "positive", "Dependency manifest present", evidence=_first_context_evidence(context, "manifests")
            )
        )
    else:
        recommendations.append("Add a package manifest so dependencies are declared explicitly.")
    if dependency_count:
        score += 15
        signals.append(
            _assessment_signal(
                "positive",
                "External dependencies detected",
                detail=str(dependency_count),
                evidence=_first_finding_evidence(report, "dependencies"),
            )
        )
    else:
        score -= 20
        signals.append(_assessment_signal("negative", "No dependency evidence found"))
    if has_lockfile or categories.get("locked", 0):
        score += 15
        signals.append(
            _assessment_signal(
                "positive",
                "Lockfile or locked dependency evidence present",
                evidence=_first_context_evidence(context, "lockfiles"),
            )
        )
    else:
        recommendations.append("Commit a lockfile or provide one in the analysis bundle for reproducibility checks.")
    if categories.get("imported", 0) and not has_manifest:
        score -= 10
        signals.append(_assessment_signal("negative", "Dependencies inferred only from imports"))
    return _assessment(
        "dependency-health",
        "Dependency health",
        score,
        0.58 + min(0.32, (len(categories) + int(has_manifest) + int(has_lockfile)) * 0.08),
        "Whether dependency evidence is declared, reproducible, and separated from weak import inference.",
        signals,
        recommendations,
    )


def _security_review_assessment(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    warnings = _publishable_rows(report["warnings"], SCORING_MIN_CONFIDENCE)
    warning_values = {item["value"] for item in warnings}
    documentation = _context_kinds(context, "documentation")
    score = 85
    signals: list[dict[str, Any]] = []
    recommendations: list[str] = []
    if "credential-like-source" in warning_values:
        score -= 35
        signals.append(
            _assessment_signal(
                "negative",
                "Credential-looking source was redacted",
                evidence=_first_finding_evidence(report, "warnings"),
            )
        )
        recommendations.append(
            "Rotate any exposed credential-looking values and move secrets to runtime configuration."
        )
    if "administrator-actions" in warning_values:
        score -= 20
        signals.append(_assessment_signal("negative", "Administrator or suppressive actions need review"))
        recommendations.append("Document why elevated wiki rights are necessary.")
    if "write-without-auth-signal" in warning_values:
        score -= 20
        signals.append(_assessment_signal("negative", "Write action without authentication evidence"))
        recommendations.append("Add explicit authentication/token handling or document why it is external.")
    if report["authentication"]:
        score += 5
        signals.append(
            _assessment_signal(
                "positive", "Authentication signal detected", evidence=_first_finding_evidence(report, "authentication")
            )
        )
    if "security" in documentation:
        score += 5
        signals.append(
            _assessment_signal(
                "positive",
                "Security policy present",
                evidence=_first_context_evidence(context, "documentation", "security"),
            )
        )
    return _assessment(
        "security-review",
        "Security review",
        score,
        0.7 + min(0.2, len(report["warnings"]) * 0.04),
        "Static risk signals that should be reviewed before publishing metadata suggestions.",
        signals,
        recommendations,
    )


def _maintenance_readiness_assessment(context: dict[str, Any]) -> dict[str, Any]:
    documentation = _context_kinds(context, "documentation")
    repository = context.get("repository") if isinstance(context.get("repository"), dict) else {}
    score = 25
    signals: list[dict[str, Any]] = []
    recommendations: list[str] = []
    if "readme" in documentation:
        score += 20
        signals.append(
            _assessment_signal(
                "positive", "README present", evidence=_first_context_evidence(context, "documentation", "readme")
            )
        )
    else:
        recommendations.append("Add a README with setup and maintainer guidance.")
    if "license" in documentation:
        score += 10
        signals.append(_assessment_signal("positive", "License present"))
    else:
        recommendations.append("Add or declare a license.")
    if context.get("tests"):
        score += 15
        signals.append(
            _assessment_signal("positive", "Tests detected", evidence=_first_context_evidence(context, "tests"))
        )
    else:
        recommendations.append("Add a small automated test suite or smoke test.")
    if context.get("ci"):
        score += 15
        signals.append(
            _assessment_signal("positive", "CI configuration detected", evidence=_first_context_evidence(context, "ci"))
        )
    else:
        recommendations.append("Add CI to run lint/tests on changes.")
    if documentation & {"changelog", "contributing", "security", "owners"}:
        score += 10
        signals.append(_assessment_signal("positive", "Maintainer/process documentation present"))
    if repository:
        score += 10
        signals.append(_assessment_signal("positive", "Repository metadata supplied"))
    return _assessment(
        "maintenance-readiness",
        "Maintenance readiness",
        score,
        0.6 + min(0.3, len(signals) * 0.05),
        "Whether the repository has enough maintenance, docs, tests, and CI context for Toolhub reviewers.",
        signals,
        recommendations,
    )


def _activity_status_scoring(
    context: dict[str, Any], status: str, age_days: int | None
) -> tuple[int, list[dict[str, Any]], list[str]]:
    """Score one repository activity status, with the guidance that fits it.

    Archived costs the same as dormant by deliberate policy: read-only means no
    fix will ever land, whatever the maintainer intended. That does conflate
    "finished" and "moved to another forge" with "abandoned" -- recording a
    successor is what separates them, and where one exists it replaces the
    dead-end advice rather than the score.
    """
    if status == "archived":
        return (
            -35,
            [_assessment_signal("negative", "Repository is archived (read-only)")],
            [_lifecycle_recommendation(context, "Find a maintained alternative.")],
        )
    if status == "active":
        return 30, [_assessment_signal("positive", "Recent repository activity", detail=f"{age_days} days")], []
    if status == "quiet":
        return (
            10,
            [_assessment_signal("neutral", "Repository activity is quiet", detail=f"{age_days} days")],
            ["Confirm the repository still reflects the deployed tool."],
        )
    if status == "stale":
        return (
            -20,
            [_assessment_signal("negative", "Repository has stale activity", detail=f"{age_days} days")],
            ["Ask the maintainer to confirm ownership and deployment status."],
        )
    if status == "dormant":
        return (
            -35,
            [_assessment_signal("negative", "Repository appears dormant", detail=f"{age_days} days")],
            [_lifecycle_recommendation(context, "Flag the tool for maintainer outreach or archival review.")],
        )
    return (
        0,
        [_assessment_signal("neutral", "No last-commit age supplied")],
        ["Provide last commit date or age for no-longer-maintained checks."],
    )


def _maintenance_activity_assessment(context: dict[str, Any]) -> dict[str, Any]:
    maintenance = context.get("maintenance") if isinstance(context.get("maintenance"), dict) else {}
    repository = context.get("repository") if isinstance(context.get("repository"), dict) else {}
    status = str(maintenance.get("status") or "unknown")
    age_days = _int_context_value(maintenance.get("lastCommitAgeDays"))
    contributor_count = _int_context_value(maintenance.get("contributorCount"))
    commit_count = _int_context_value(maintenance.get("commitCount"))
    delta, signals, recommendations = _activity_status_scoring(context, status, age_days)
    score = 50 + delta
    if contributor_count is not None and contributor_count >= MULTIPLE_CONTRIBUTOR_MIN:
        score += 10
        signals.append(_assessment_signal("positive", "Multiple contributors detected", detail=str(contributor_count)))
    elif contributor_count == 1:
        score -= 10
        signals.append(_assessment_signal("neutral", "Single-contributor repository", detail="1"))
        recommendations.append("Consider adding secondary maintainer or ownership metadata.")
    if commit_count is not None and commit_count < SMALL_COMMIT_HISTORY_THRESHOLD:
        score -= 10
        signals.append(_assessment_signal("neutral", "Very small commit history", detail=str(commit_count)))
    if _replaced_by(context):
        signals.append(_assessment_signal("positive", "Replacement tool recorded", detail=_replaced_by(context)))
    if repository.get("dirty") is True:
        signals.append(_assessment_signal("neutral", "Local checkout had uncommitted changes"))
    return _assessment(
        "maintenance-activity",
        "Maintenance activity",
        score,
        0.56 + min(0.34, len(signals) * 0.08),
        "Whether repository activity suggests the tool is actively maintained or needs outreach.",
        signals,
        recommendations,
    )


def _operational_readiness_assessment(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    declared = context.get("declared") if isinstance(context.get("declared"), dict) else {}
    api_values = {item["value"] for item in report["apis"]}
    score = 35
    signals: list[dict[str, Any]] = []
    recommendations: list[str] = []
    if context.get("runtime"):
        score += 20
        signals.append(
            _assessment_signal(
                "positive",
                "Runtime/deploy configuration detected",
                evidence=_first_context_evidence(context, "runtime"),
            )
        )
    else:
        recommendations.append("Provide runtime or deployment configuration in the analysis context.")
    if "toolforge" in api_values or "toolforge" in _context_kinds(context, "runtime"):
        score += 20
        signals.append(_assessment_signal("positive", "Toolforge context detected"))
    if context.get("health") or declared.get("healthUrl"):
        score += 15
        signals.append(
            _assessment_signal(
                "positive", "Health-check signal present", evidence=_first_context_evidence(context, "health")
            )
        )
    else:
        recommendations.append("Expose or document a lightweight health endpoint for web services.")
    if context.get("ci"):
        score += 10
        signals.append(_assessment_signal("positive", "CI can support deployment confidence"))
    return _assessment(
        "operational-readiness",
        "Operational readiness",
        score,
        0.56 + min(0.34, len(signals) * 0.08),
        "Whether the repository exposes enough runtime and deployment signals for operators.",
        signals,
        recommendations,
    )


def _frontend_accessibility_assessment(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    technology_values = {item["value"] for item in _publishable_rows(report["technology"], SCORING_MIN_CONFIDENCE)}
    has_frontend = bool(technology_values & {"JavaScript", "TypeScript", "React", "Vue", "MediaWiki gadget"})
    if not has_frontend:
        return None
    dependency_values = {item["value"] for item in report["dependencies"]}
    score = 45
    signals: list[dict[str, Any]] = []
    recommendations: list[str] = []
    if context.get("accessibility"):
        score += 20
        signals.append(
            _assessment_signal(
                "positive",
                "Accessibility markup or tests detected",
                evidence=_first_context_evidence(context, "accessibility"),
            )
        )
    else:
        recommendations.append(
            "Add visible accessibility markers such as labels, aria state, or keyboard handling tests."
        )
    if any("axe" in value for value in dependency_values):
        score += 20
        signals.append(_assessment_signal("positive", "Automated a11y tooling dependency detected"))
    else:
        recommendations.append("Add automated a11y checks for web-facing tools.")
    if context.get("tests"):
        score += 10
        signals.append(_assessment_signal("positive", "Frontend-adjacent tests detected"))
    return _assessment(
        "frontend-accessibility",
        "Frontend accessibility",
        score,
        0.54 + min(0.34, len(signals) * 0.1),
        "Whether web-facing code includes deterministic accessibility evidence.",
        signals,
        recommendations,
    )


def _assessment_summary(assessments: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [int(item["score"]) for item in assessments]
    return {
        "assessmentCount": len(assessments),
        "assessmentScore": round(sum(scores) / len(scores)) if scores else 0,
    }


def _assessment_index(assessments: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("key")): item for item in assessments}


def _health_dimension(  # noqa: PLR0913 - public health dimension fields are intentionally explicit.
    key: str,
    label: str,
    score: int | None,
    weight: float,
    summary: str,
    *,
    confidence: float,
    status: str = "",
    components: tuple[str, ...] = (),
    applicable: bool = True,
) -> dict[str, Any]:
    bounded = _bounded_score(score) if score is not None else None
    grade = _score_grade(bounded) if bounded is not None else ("unknown" if applicable else "not-applicable")
    return {
        "key": key,
        "label": label,
        "score": bounded,
        "grade": grade,
        "status": status or grade,
        "weight": weight,
        "confidence": round(max(0.1, min(0.99, confidence)), 2),
        "applicable": applicable,
        "includedInScore": bounded is not None and applicable,
        "components": list(components),
        "summary": summary,
    }


def _health_dimension_from_assessments(
    index: dict[str, dict[str, Any]],
    spec: tuple[str, str, tuple[str, ...], float, str],
) -> dict[str, Any]:
    key, label, assessment_keys, weight, summary = spec
    rows = [index[item] for item in assessment_keys if item in index]
    if not rows:
        return _health_dimension(
            key,
            label,
            None,
            weight,
            summary,
            confidence=0.1,
            components=assessment_keys,
            applicable=key != "accessibility",
        )
    score = round(sum(int(item.get("score") or 0) for item in rows) / len(rows))
    confidence = sum(float(item.get("confidence") or 0.1) for item in rows) / len(rows)
    return _health_dimension(
        key,
        label,
        score,
        weight,
        summary,
        confidence=confidence,
        components=assessment_keys,
    )


def _maintainer_activity_score(activity: dict[str, Any]) -> int | None:
    status = str(activity.get("status") or "unknown")
    if status == "unknown":
        return None
    score = {"active": 85, "quiet": 70, "stale": 40, "dormant": 20}.get(status, 50)
    active_count = _int_context_value(activity.get("activeMaintainerCount"))
    maintainer_count = _int_context_value(activity.get("maintainerCount"))
    recent_activity_count = _int_context_value(activity.get("recentActivityCount"))
    if active_count is not None:
        if active_count >= MULTIPLE_CONTRIBUTOR_MIN:
            score += 10
        elif active_count == 0:
            score -= 15
    if maintainer_count is not None:
        if maintainer_count >= MULTIPLE_CONTRIBUTOR_MIN:
            score += 5
        elif maintainer_count == 0:
            score -= 25
    if recent_activity_count is not None and recent_activity_count > 0:
        score += 5
    return _bounded_score(score)


def _maintainer_activity_dimension(context: dict[str, Any]) -> dict[str, Any]:
    activity = context.get("maintainerActivity") if isinstance(context.get("maintainerActivity"), dict) else {}
    score = _maintainer_activity_score(activity)
    status = str(activity.get("status") or "unknown")
    detail = (
        "Maintainer activity supplied by trusted context." if activity else "No maintainer activity context supplied."
    )
    return _health_dimension(
        "maintainer-activity",
        "Maintainer activity",
        score,
        MAINTAINER_DIMENSION_WEIGHT,
        detail,
        confidence=0.82 if activity else 0.25,
        status=status,
    )


def _replaced_by(context: dict[str, Any]) -> str:
    lifecycle = context.get("lifecycle") if isinstance(context.get("lifecycle"), dict) else {}
    return str(lifecycle.get("replacedBy") or "").strip()


def _lifecycle_recommendation(context: dict[str, Any], fallback: str) -> str:
    """Name the successor when the maintainer recorded one.

    Telling somebody to go find an alternative, or asking a maintainer to
    confirm a tool they already retired, is wasted advice when the answer is
    sitting in the catalogue.
    """
    replaced_by = _replaced_by(context)
    return f"Use the recorded replacement: {replaced_by}" if replaced_by else fallback


def _terminal_stewardship(context: dict[str, Any], source_status: str) -> str:
    """Return the verdict no amount of maintainer activity can change, or "".

    These three do not combine with maintainer status the way the rest of the
    ladder does. A superseded tool stays superseded however busy its author is
    elsewhere, and an archived repository will receive no further work either
    way -- so pairing them with maintainer activity would only dilute them.
    """
    lifecycle = context.get("lifecycle") if isinstance(context.get("lifecycle"), dict) else {}
    # A recorded successor is the most complete thing a maintainer can say: it
    # answers "what should I use instead", which the inferred ladder below only
    # gestures at. So it wins even over an archived repository.
    if _replaced_by(context):
        return "superseded"
    if lifecycle.get("deprecated") is True:
        return "deprecated"
    if source_status == "archived":
        return "archived"
    return ""


def _stewardship_status(context: dict[str, Any]) -> str:
    source = context.get("maintenance") if isinstance(context.get("maintenance"), dict) else {}
    maintainer = context.get("maintainerActivity") if isinstance(context.get("maintainerActivity"), dict) else {}
    source_status = str(source.get("status") or "unknown")
    maintainer_status = str(maintainer.get("status") or "unknown")
    terminal = _terminal_stewardship(context, source_status)
    if terminal:
        return terminal
    stale_source = source_status in {"stale", "dormant"}
    active_maintainer = maintainer_status in {"active", "quiet"}
    stale_maintainer = maintainer_status in {"stale", "dormant"}
    if stale_source and active_maintainer:
        return "source-stale-maintainer-active"
    if stale_source and stale_maintainer:
        return "at-risk"
    if source_status in {"active", "quiet"} and stale_maintainer:
        return "maintainer-outreach-needed"
    if source_status == "active" and maintainer_status == "active":
        return "healthy"
    return "needs-context" if "unknown" in {source_status, maintainer_status} else "watch"


def _health_core(assessments: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    index = _assessment_index(assessments)
    dimensions = [_health_dimension_from_assessments(index, spec) for spec in HEALTH_DIMENSIONS]
    dimensions.insert(2, _maintainer_activity_dimension(context))
    score_weight = sum(float(item["weight"]) for item in dimensions if item["includedInScore"])
    total_weight = sum(float(item["weight"]) for item in dimensions if item["applicable"])
    weighted_score = sum(float(item["score"]) * float(item["weight"]) for item in dimensions if item["includedInScore"])
    score = round(weighted_score / score_weight) if score_weight else 0
    confidence = (score_weight / total_weight) if total_weight else 0.0
    maintenance = context.get("maintenance") if isinstance(context.get("maintenance"), dict) else {}
    maintainer = context.get("maintainerActivity") if isinstance(context.get("maintainerActivity"), dict) else {}
    return {
        "schemaVersion": 1,
        "score": score,
        "grade": _score_grade(score),
        "confidence": round(confidence, 2),
        "sourceMaintenanceStatus": str(maintenance.get("status") or "unknown"),
        "maintainerActivityStatus": str(maintainer.get("status") or "unknown"),
        "stewardshipStatus": _stewardship_status(context),
        "replacedBy": _replaced_by(context),
        "dimensions": dimensions,
    }


def _health_summary(health_core: dict[str, Any]) -> dict[str, Any]:
    return {
        "healthScore": int(health_core.get("score") or 0),
        "healthGrade": str(health_core.get("grade") or "unknown"),
        "healthConfidence": float(health_core.get("confidence") or 0),
        "maintenanceStatus": str(health_core.get("sourceMaintenanceStatus") or "unknown"),
        "maintainerStatus": str(health_core.get("maintainerActivityStatus") or "unknown"),
        "stewardshipStatus": str(health_core.get("stewardshipStatus") or "needs-context"),
    }


def _assessments(report: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        _metadata_completeness_assessment(report, context),
        _permission_clarity_assessment(report, context),
        _dependency_health_assessment(report, context),
        _security_review_assessment(report, context),
        _maintenance_readiness_assessment(context),
        _maintenance_activity_assessment(context),
        _operational_readiness_assessment(report, context),
    ]
    frontend = _frontend_accessibility_assessment(report, context)
    if frontend is not None:
        rows.append(frontend)
    return rows


def _suggestions(report: dict[str, Any]) -> dict[str, Any]:
    projects = [
        item["value"] for item in report["projects"] if _is_publishable_finding(item, PROJECT_SUGGESTION_MIN_CONFIDENCE)
    ]
    technology = [
        item["value"]
        for item in report["technology"]
        if _is_publishable_finding(item, TECHNOLOGY_SUGGESTION_MIN_CONFIDENCE)
    ]
    apis = _publishable_rows(report["apis"])
    technology_rows = _publishable_rows(report["technology"], TECHNOLOGY_SUGGESTION_MIN_CONFIDENCE)
    tool_type = _tool_type_suggestion(technology_rows, apis)
    access_rights = _publishable_rows(report["accessRights"])
    dependencies = _publishable_rows(report["dependencies"])
    oauth_scopes = _publishable_rows(report["oauthScopes"])
    warnings = _publishable_rows(report["warnings"])
    toolinfo_patch: dict[str, Any] = {}
    if projects:
        toolinfo_patch["for_wikis"] = projects[:50]
    if technology:
        toolinfo_patch["technology_used"] = technology[:20]
    if tool_type:
        toolinfo_patch["tool_type"] = tool_type
    return {
        "toolinfoPatch": toolinfo_patch,
        "evolvedMetadata": {
            "apis": [item["value"] for item in apis],
            "access_rights": [item["value"] for item in access_rights],
            "assessment_scores": {item["key"]: item["score"] for item in report.get("assessments", [])},
            "dependencies": [item["value"] for item in dependencies],
            "health_core": report.get("healthCore", {}),
            "health_score": report.get("summary", {}).get("healthScore", 0),
            "health_confidence": report.get("summary", {}).get("healthConfidence", 0),
            "maintainer_status": report.get("summary", {}).get("maintainerStatus", "unknown"),
            "maintenance_status": report.get("summary", {}).get("maintenanceStatus", "unknown"),
            "stewardship_status": report.get("summary", {}).get("stewardshipStatus", "needs-context"),
            "oauth_scopes": [item["value"] for item in oauth_scopes],
            "warnings": [item["value"] for item in warnings],
        },
    }


def analyze_source_files(
    files: object,
    *,
    tool_name: str | None = None,
    source_label: str | None = None,
    repository_context: object = None,
) -> dict[str, Any]:
    """Analyze source files and return metadata suggestions with evidence."""
    normalized = _normalize_source_files(files)
    findings: dict[tuple[str, str], Finding] = {}
    local_python_roots = _local_python_import_roots(normalized)
    for source_file in normalized:
        _scan_manifest_dependencies(findings, source_file)
        # A lockfile is a resolved dependency graph with a registry URL on
        # nearly every line. Those registries belong to the package manager,
        # not to the tool, and the dependency scanner has already read this
        # same file for the part of it that is about the tool. Its 0.95 weight
        # would otherwise make npmjs.org one of the loudest endpoints found.
        source_class = _source_class(source_file.path)
        # A lockfile is a list of registry mirrors and the tool calls none of
        # them, so it is skipped outright. Anywhere else the addresses are worth
        # reading; whether they are worth believing on their own depends on the
        # file, and that decision is per file rather than per line.
        wants_endpoints = source_class != "lockfile"
        endpoints_need_a_call = SOURCE_CLASS_WEIGHTS[source_class] < ENDPOINT_TRUSTED_SOURCE_WEIGHT
        for line_number, raw_line in enumerate(source_file.content.splitlines() or [""], start=1):
            line = _bounded_line(raw_line)
            if wants_endpoints:
                _scan_endpoints(findings, source_file.path, line_number, line, require_call=endpoints_need_a_call)
            _scan_projects(findings, source_file.path, line_number, line)
            _scan_rules(findings, source_file.path, line_number, line, API_RULES, kind="apis")
            _scan_rules(findings, source_file.path, line_number, line, AUTH_RULES, kind="authentication")
            _scan_technology(findings, source_file.path, line_number, line)
            _scan_import_dependencies(findings, source_file.path, line_number, line, local_python_roots)
            _scan_actions(findings, source_file.path, line_number, line)
            _scan_oauth_scopes(findings, source_file.path, line_number, line)
            _scan_warnings(findings, source_file.path, line_number, line)
    report: dict[str, Any] = {
        "toolName": tool_name or "",
        "sourceLabel": source_label or "",
        "filesAnalyzed": len(normalized),
        "projects": _serialized(findings, "projects"),
        "apis": _serialized(findings, "apis"),
        "accessRights": _serialized(findings, "accessRights"),
        "authentication": _serialized(findings, "authentication"),
        "dependencies": _serialized(findings, "dependencies"),
        "endpoints": _serialized(findings, "endpoints"),
        "oauthScopes": _serialized(findings, "oauthScopes"),
        "technology": _serialized(findings, "technology"),
        "warnings": _serialized(findings, "warnings"),
    }
    _add_cross_file_warnings(findings, report)
    report["warnings"] = _serialized(findings, "warnings")
    report["repositoryContext"] = _repository_context_from_files(normalized, report, repository_context)
    report["assessments"] = _assessments(report, report["repositoryContext"])
    report["healthCore"] = _health_core(report["assessments"], report["repositoryContext"])
    report["summary"] = {
        "filesAnalyzed": len(normalized),
        "projectCount": len(report["projects"]),
        "apiCount": len(report["apis"]),
        "accessRightCount": len(report["accessRights"]),
        "dependencyCount": len(report["dependencies"]),
        "endpointCount": len(report["endpoints"]),
        # Split out because the two halves answer different questions. Wikimedia
        # endpoints describe what a tool does; a third-party one is a dependency
        # on something nobody in the movement operates, which is the number a
        # reviewer is actually looking for.
        "externalEndpointCount": _external_endpoint_count(report["endpoints"]),
        "oauthScopeCount": len(report["oauthScopes"]),
        "technologyCount": len(report["technology"]),
        "warningCount": len(report["warnings"]),
        "writeActionsDetected": _has_write_access(report["accessRights"], SCORING_MIN_CONFIDENCE),
        **_assessment_summary(report["assessments"]),
        **_health_summary(report["healthCore"]),
    }
    report["suggestions"] = _suggestions(report)
    return report
