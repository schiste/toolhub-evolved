# SPDX-License-Identifier: GPL-3.0-or-later
"""Constants and shared primitives for static source analysis.

The reading caps, provenance weights, confidence thresholds, health dimensions
and match vocabularies the analyzer is built from, together with the handful of
small helpers that both the scanning rules and the assessments need -- reading a
date, counting categories, deciding whether a finding may be published.

Nothing here opens a source file or assembles a report. It is the layer the
other two sit on, and it imports neither of them, which is what keeps them from
importing each other.

Split out of source_analyzer.py, which had grown past 3800 lines. See
source_analysis_assessments.py for the other half of that split.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from backend import wiki_sources

MAX_FILES = 120
# Of those slots, a reserve that only context-bearing files may fill.
#
# source_reading_rank() orders by source-class weight descending, and runtime
# files weigh 1.0 against 0.75 for documentation and CI and 0.35 for tests. On
# any repository with 120 or more code files that ordering is total: every code
# file sorts ahead of the README, so the budget is spent before reaching it. On
# this repository, of 521 tracked candidates, the top 120 were 117 runtime files
# and 3 manifests and nothing else -- README.md ranked 286, LICENSE 285,
# .github/workflows 299 and tests/ 314 -- so repositoryContext came back with
# empty documentation, ci, tests and lockfiles lists for a repository that has
# all four, and maintenance readiness scored 35/100 "high-risk" off those
# absences. Four assessments read these lists, and they cannot tell a repository
# that lacks a README from one whose README we declined to read.
#
# A reserve rather than a larger MAX_FILES: the weighted ordering earned its
# place (endpoints 206 -> 270, dependencies 318 -> 421 over sixteen
# repositories) and raising the cap would pay for context in clone-read time
# across every tool in the catalogue. 20 slots is enough for a README, a
# licence, a changelog, a CI workflow or two, a handful of test files and a
# lockfile, which is all the assessments actually read.
CONTEXT_RESERVE_SLOTS = 20
# ...and never more than one slot in six of the budget actually in force. The
# reserve exists to stop context being crowded out; it must not do the crowding
# itself. A caller reading a handful of files wants those files chosen on merit,
# so at small budgets the reserve shrinks to nothing rather than taking the lot.
CONTEXT_RESERVE_BUDGET_DIVISOR = 6
# A per-class quota, not a priority queue over one shared pool. Filling greedily
# in priority order means the first class takes everything it can reach: this
# repository has 22 documentation candidates, which is more than the whole
# reserve, so docs alone would consume all 20 slots and ci, tests and lockfiles
# would stay exactly as empty as before. Each class gets its own allowance, and
# whatever a repository cannot fill spills to the classes after it.
#
# Sized to what the assessments read rather than to what exists: a README, a
# licence and a changelog satisfy maintenance-readiness and
# metadata-completeness; one or two workflows establish CI; a handful of test
# files establish that tests exist at all, since no assessment reads their
# contents; and dependency-health needs the lockfile present, not parsed in full.
CONTEXT_RESERVE_QUOTAS = (("docs", 6), ("ci", 4), ("test", 6), ("lockfile", 4))
MAX_FILE_BYTES = 256 * 1024
# Wiki pages get a larger ceiling than checkout files, because the cap is doing a
# different job on each. In a clone, a file past 256 KiB is nearly always a
# vendored bundle, a minified artifact or a fixture, and skipping it costs one
# file out of hundreds. A wiki tool has no vendoring -- every page was typed by a
# maintainer on-wiki -- and a gadget is frequently a single page, so the same
# skip drops the whole tool rather than a file of it. That is how fr.wikipedia's
# LiveRC, 700 KiB in one page, reached the analyzer with an empty file list and
# failed the non-empty check instead of being read. Measured across the eight
# wikis in the catalogue, 11 of 1647 gadget source pages exceed 256 KiB and one
# exceeds this; MAX_TOTAL_BYTES still bounds the page set either way.
MAX_WIKI_FILE_BYTES = 1024 * 1024
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
MAX_VERSION_CHARS = 40
MAX_VERSION_SPECS_PER_FINDING = 5
MAX_CONTEXT_LIST_ITEMS = 40
MAX_CONTEXT_STRING_CHARS = 240
MAX_ASSESSMENT_SIGNALS = 8
MAX_SOURCE_CLASS_ITEMS = 20
JS_SCOPED_PACKAGE_PARTS = 2
CONFIDENCE_CAP = 0.99
CONFIDENCE_REPEAT_BOOST = 0.03
# How many distinct files may corroborate one finding before the boost stops.
# Three steps of 0.03 is enough for genuine agreement across a codebase to read
# as stronger than a single sighting, and small enough that a rule misfiring on
# a common idiom cannot climb to certainty on volume alone.
CONFIDENCE_MAX_CORROBORATING_FILES = 3
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
# A finding from a file at or above this weight -- manifest, runtime, lockfile,
# frontend, config -- may be published on its own evidence. Anything softer
# (documentation, CI, unclassified) has to be corroborated by a second file
# before it reaches a caller's catalogue record. See _is_corroborated().
PUBLICATION_TRUSTED_SOURCE_WEIGHT = 0.85
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
#: Every suffix the JavaScript family is written under. One set, because the
#: three questions asked of it -- may this file be read, are its imports npm
#: imports, is `mw.Api(` in it a call rather than a quotation -- are all the
#: same question of whether the file is JavaScript, and keeping three lists
#: is what let them disagree: `.jsx` was in none of them, so a React tool
#: written in `.jsx` had no source the analyzer could see, and `.mjs` and
#: `.cjs` were named as browser scripts but never read, which made those
#: entries dead.
JS_SOURCE_SUFFIXES = frozenset({".cjs", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".vue"})
FRONTEND_SOURCE_EXTENSIONS = {".css", ".html"} | JS_SOURCE_SUFFIXES
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
    ".json",
    ".lua",
    ".md",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".txt",
    ".toml",
    ".xml",
    ".yaml",
    ".yml",
} | JS_SOURCE_SUFFIXES

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

# The dimension weights below are editorial, not calibrated. No labelled corpus
# of healthy and unhealthy tools exists to fit them against, and inventing one
# from this analyzer's own output would only measure the analyzer agreeing with
# itself. They encode a stated position -- that a tool which runs and is safe
# matters more than one that is merely tidy -- and should be read as that
# position rather than as a measurement. What keeps the composite honest is not
# the weights but HEALTH_MIN_SCORING_CONFIDENCE, which withholds the grade when
# the dimensions feeding it were not confident enough to support one.
#
# Below this, the weighted dimensions did not carry enough evidence between them
# for the composite to mean anything, and _health_core() reports the grade as
# "unknown" rather than asserting a band. The value sits between the two
# reference points available without a labelled corpus: a repository holding a
# single trivial file, whose dimensions score almost entirely on the absence of
# things and reach about 0.52, and this repository, whose dimensions are backed
# by real findings and reach about 0.66. It is a floor under the obviously
# unsupported, not a calibrated threshold, and it errs toward withholding.
HEALTH_MIN_SCORING_CONFIDENCE = 0.6

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
    (
        "browser-permissions",
        "Browser permissions",
        ("browser-permissions",),
        0.7,
        "What the source asks the reader's own browser for.",
    ),
)
MAINTAINER_DIMENSION_WEIGHT = 1.2

TECH_BY_EXTENSION = {
    ".cjs": "JavaScript",
    ".go": "Go",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".lua": "Lua",
    ".mjs": "JavaScript",
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
    # Deliberately not IGNORECASE, and deliberately requiring a usage rather
    # than a mention, for the same reason as `mw.Api` below. `\bReact\b` under
    # IGNORECASE matched the English word in a comment, and -- because the rules
    # read every file rather than only code -- the string `node_modules/react`
    # in a lockfile, so any checkout that had ever installed React was
    # catalogued as a React tool. A package the tool actually declares still
    # names it, through TECHNOLOGY_PACKAGES.
    (
        "React",
        re.compile(r"\bReact\.[A-Za-z_]|\bfrom\s+[\"']react[\"']|\brequire\s*\(\s*[\"']react[\"']"),
        0.82,
    ),
    # Deliberately not IGNORECASE, and deliberately requiring the call: `mw.Api`
    # and `mw.loader.using` are JavaScript identifiers, so `MW.API` is not one
    # of them, and a bare mention is somebody writing *about* the API rather
    # than calling it. The old spelling matched a prose mention anywhere in a
    # checkout, which is how this project's own analyzer -- whose rules, tests
    # and UI all quote `mw.Api` -- came to be catalogued as a gadget.
    ("MediaWiki JavaScript", re.compile(r"\bmw\.loader\.using\s*\(|\bmw\.Api\s*\("), 0.9),
)

# JavaScript is the only place the MediaWiki JS API can be called or a React
# component written, so evidence of either found anywhere else is a quotation.
# A Python docstring naming `mw.Api` is the case that prompted this.
TECH_RULE_SUFFIXES = {
    "MediaWiki JavaScript": JS_SOURCE_SUFFIXES,
    "React": JS_SOURCE_SUFFIXES,
}

# A file the wiki would serve as a user script. Read off the name rather than
# the contents: the suffix is what makes a wiki page a script, and it says so
# whatever the file goes on to contain.
#: The technology each declared runtime constraint names, and the manifest key
#: it is written under. A manifest that pins a runtime is naming the technology
#: as surely as a source file written in it, so these create the finding rather
#: than only annotating one -- `engines.node` is why a Node.js tool with no
#: `.js` file at the root is still a Node.js tool.
RUNTIME_TECHNOLOGY = {
    "node": "Node.js",
    "python": "Python",
    "php": "PHP",
    "go": "Go",
}

#: The package behind each technology, and the category the technology belongs
#: in when the package is all that names it. `from flask import ...` says the
#: tool uses Flask; only the manifest says which Flask, and it says it under a
#: name the technology finding does not share, so the two are joined here
#: rather than by string match.
TECHNOLOGY_PACKAGES = {
    "Flask": ("pypi:flask", "framework"),
    "Django": ("pypi:django", "framework"),
    "Pywikibot": ("pypi:pywikibot", "framework"),
    "mwclient": ("pypi:mwclient", "framework"),
    "React": ("npm:react", "framework"),
    "Vue": ("npm:vue", "language"),
    "TypeScript": ("npm:typescript", "language"),
}

#: Source classes that mean somebody wrote the dependency into this tool: a
#: manifest, or an import in its own code. A `lockfile` row is the resolver's
#: output instead -- it names every transitive package a build would fetch,
#: which is why one line of `node_modules/react` used to be enough. The
#: low-provenance classes are left out for the same reason: a package a fixture
#: imports is not a technology the tool is built with.
DECLARED_DEPENDENCY_SOURCE_CLASSES = frozenset({"config", "frontend", "manifest", "runtime"})

#: The confidence a technology earns from a declared package alone. Below every
#: source-observed rule in TECH_RULES: declaring a dependency is deliberate, but
#: it is evidence of an intent to use rather than of a use.
DECLARED_TECHNOLOGY_CONFIDENCE = 0.8

USER_SCRIPT_SUFFIX = ".user.js"

# The toolinfo vocabulary term for each kind of wiki-hosted source page.
# `wiki_sources` already decides which kind a page is; this only spells the
# answer the way toolinfo does.
#
# KIND_GADGET_PAGE has no entry, and that absence is the policy: a
# `MediaWiki:Gadget-*` page becomes KIND_GADGET only once the definition page
# has been read and found to list it, so anything still carrying the page kind
# is either unregistered or unverified, and neither is a gadget anyone can
# state. It yields no suggestion rather than a plausible one, because a
# suggestion fills an empty catalogue field unattended.
WIKI_KIND_TOOL_TYPE = {
    wiki_sources.KIND_GADGET: "gadget",
    wiki_sources.KIND_USER_SCRIPT: "user script",
}

PROJECT_DOMAIN_RE = re.compile(
    r"\b(?:(?P<sub>[a-z0-9-]+)\.)?(?P<family>wikipedia|wikibooks|wikidata|wikimedia|wikinews|wikiquote|wikisource|wiktionary|wikiversity|wikivoyage|mediawiki)\.org\b",
    re.IGNORECASE,
)
# Two deliberate restrictions live in this pattern.
#
# The character immediately before the `wiki` suffix may not be an underscore.
# WMF database names do contain underscores -- `zh_yuewiki`, `be_x_oldwiki` --
# so the class cannot simply drop `_`, but the underscore always sits inside
# the language code and never directly before the suffix. Every false positive
# this rule used to emit had it in exactly that position: `target_wiki`,
# `clean_wiki`, `whole_wiki`, `created_at_wiki` and `enumerate_wiki` are Python
# identifiers from this repository that were published as wikis a tool works on.
#
# The boundary assertions are case-insensitive even though the body is not.
# They were `[a-z0-9_.-]`, which does not block a capital, so the `M` in a
# `MediaWiki:Gadget-*` page title failed to stop a match starting one character
# in and the scanner emitted `ediawiki`.
PROJECT_DB_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:commonswiki|wikidatawiki|metawiki|mediawikiwiki|[a-z][a-z0-9_]{0,13}[a-z0-9]wiki)(?![A-Za-z0-9_-]|\.[A-Za-z0-9_-])"
)
# Words that end in "wiki" without naming a wiki: MediaWiki vocabulary, and the
# names of competing wiki engines a tool might merely mention. `interwiki` is
# the one that actually showed up in a live run over this repository.
IGNORED_PROJECT_DB_NAMES = {
    "mediawiki",
    "interwiki",
    "wikiwiki",
    "subwiki",
    "sisterwiki",
    "dokuwiki",
    "tikiwiki",
    "foswiki",
    "jspwiki",
    "pmwiki",
    "twiki",
    "xwiki",
}

# for_wikis is a closed vocabulary, not "whatever hostname we saw". Content
# families map a language subdomain onto the database name that MediaWiki
# itself uses; wikimedia.org is enumerated because most of its subdomains are
# infrastructure (gerrit, phabricator, upload, toolsadmin) rather than wikis.
PROJECT_FAMILY_DB_SUFFIX = {
    "wikipedia": "wiki",
    "wikibooks": "wikibooks",
    "wikinews": "wikinews",
    "wikiquote": "wikiquote",
    "wikisource": "wikisource",
    "wikiversity": "wikiversity",
    "wikivoyage": "wikivoyage",
    "wiktionary": "wiktionary",
}
WIKIMEDIA_ORG_WIKIS = {
    "commons": ("commonswiki", "Commons"),
    "meta": ("metawiki", "Meta-Wiki"),
    "species": ("specieswiki", "Wikispecies"),
    "incubator": ("incubatorwiki", "Wikimedia Incubator"),
    "outreach": ("outreachwiki", "Outreach"),
    "wikitech": ("labswiki", "Wikitech"),
    "foundation": ("foundationwiki", "Wikimedia Foundation Governance"),
    "strategy": ("strategywiki", "Strategy"),
    "office": ("officewiki", "Office"),
    "wikimania": ("wikimaniawiki", "Wikimania"),
}
# `en.m.wikipedia.org` presents `m` as the subdomain to PROJECT_DOMAIN_RE, which
# would otherwise become the database name `mwiki`. Dropping the whole host
# costs one true hit and invents none.
NON_WIKI_SUBDOMAINS = {"m", "mobile", "wap", "zero", "api", "static", "upload", "test", "test2"}
LANGUAGE_SUBDOMAIN_RE = re.compile(r"[a-z]{2,11}(?:-[a-z0-9]{2,8}){0,2}")
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

# Capabilities the browser will not hand over silently. A wiki gadget and a
# Toolforge web app run in the reader's browser, so what they ask the browser
# for is part of what a reviewer is agreeing to install, and until now nothing
# in the report said so: `accessRights` and `oauthScopes` describe what a tool
# asks the *wiki* for, which is a different question with a different answer.
#
# Three families, kept as three tables because they are found in three places
# and mean three slightly different things: a runtime call that raises a browser
# prompt, a string a WebExtension must declare before anyone can install it, and
# a metadata directive a user-script manager reads before it runs a line.
#
# Measured on en.wikipedia, over the 90,016 pages in the User and MediaWiki
# namespaces whose title ends in `.js`: navigator.clipboard appears on 110,
# Notification.requestPermission on 19, `// @grant` on 307 and `// @connect` on
# 444, while getUserMedia appears on none. The rare ones are kept anyway --
# their cost is a table row, and a gadget that turns on the camera is exactly
# the finding this bucket exists to surface -- but the ordering is why the
# clipboard and notification rules are the ones written most carefully.

#: Runtime calls that ask the person using the tool, not the wiki. Each pattern
#: requires the call, not the object: `navigator.clipboard` alone is a feature
#: test, and a tool that checks whether an API exists has not used it.
BROWSER_PERMISSION_RULES: tuple[tuple[str, str, re.Pattern[str], float, str], ...] = (
    (
        "clipboard-read",
        "Read the clipboard",
        re.compile(r"\bnavigator\.clipboard\.read(?:Text)?\s*\("),
        0.86,
        "Clipboard read call detected; the browser prompts for this.",
    ),
    (
        "clipboard-write",
        "Write to the clipboard",
        re.compile(r"\bnavigator\.clipboard\.write(?:Text)?\s*\("),
        0.8,
        "Clipboard write call detected.",
    ),
    (
        "notifications",
        "Show desktop notifications",
        re.compile(r"\bNotification\.requestPermission\s*\(|\bnew\s+Notification\s*\("),
        0.86,
        "Desktop notification request detected.",
    ),
    (
        "geolocation",
        "Read the device location",
        re.compile(r"\bnavigator\.geolocation\.(?:getCurrentPosition|watchPosition)\s*\("),
        0.9,
        "Geolocation request detected.",
    ),
    (
        "camera-microphone",
        "Use the camera or microphone",
        re.compile(r"\bnavigator\.mediaDevices\.getUserMedia\s*\(|\bnavigator\.getUserMedia\s*\("),
        0.9,
        "Camera or microphone capture request detected.",
    ),
    (
        "screen-capture",
        "Capture the screen",
        re.compile(r"\bnavigator\.mediaDevices\.getDisplayMedia\s*\("),
        0.9,
        "Screen capture request detected.",
    ),
    (
        "persistent-storage",
        "Keep storage the browser would otherwise evict",
        re.compile(r"\bnavigator\.storage\.persist\s*\("),
        0.82,
        "Persistent storage request detected.",
    ),
    (
        "storage-access",
        "Read its own cookies inside another site's page",
        re.compile(r"\bdocument\.requestStorageAccess\s*\("),
        0.82,
        "Storage Access API request detected.",
    ),
    (
        "midi",
        "Use MIDI devices",
        re.compile(r"\bnavigator\.requestMIDIAccess\s*\("),
        0.86,
        "MIDI device request detected.",
    ),
    (
        "bluetooth",
        "Use Bluetooth devices",
        re.compile(r"\bnavigator\.bluetooth\.requestDevice\s*\("),
        0.88,
        "Bluetooth device request detected.",
    ),
    (
        "usb",
        "Use USB devices",
        re.compile(r"\bnavigator\.usb\.requestDevice\s*\("),
        0.88,
        "USB device request detected.",
    ),
    (
        "serial",
        "Use serial ports",
        re.compile(r"\bnavigator\.serial\.requestPort\s*\("),
        0.88,
        "Serial port request detected.",
    ),
    (
        "hid",
        "Use human-interface devices",
        re.compile(r"\bnavigator\.hid\.requestDevice\s*\("),
        0.88,
        "HID device request detected.",
    ),
    (
        "file-system",
        "Read or write files the reader picks",
        re.compile(r"\b(?:showOpenFilePicker|showSaveFilePicker|showDirectoryPicker)\s*\("),
        0.86,
        "File System Access request detected.",
    ),
    (
        "screen-wake-lock",
        "Keep the screen awake",
        re.compile(r"\bnavigator\.wakeLock\.request\s*\("),
        0.8,
        "Screen wake lock request detected.",
    ),
    (
        "push",
        "Receive push messages",
        re.compile(r"\bpushManager\.subscribe\s*\("),
        0.84,
        "Push subscription request detected.",
    ),
    (
        "credentials",
        "Read stored credentials or passkeys",
        re.compile(r"\bnavigator\.credentials\.(?:get|create)\s*\("),
        0.84,
        "Credential Management request detected.",
    ),
    (
        "cross-origin-request",
        "Make requests the page's origin policy would refuse",
        re.compile(r"\bGM[._]xmlhttpRequest\b", re.IGNORECASE),
        0.84,
        "User-script cross-origin request helper detected.",
    ),
)

#: The strings a WebExtension declares, from the Chrome and Firefox permission
#: lists. Only the ones that carry a real capability are here: `alarms` and
#: `contextMenus` are declared the same way and grant nothing worth reporting,
#: and listing them would bury the four or five that matter under twenty that
#: do not.
WEB_EXTENSION_PERMISSIONS = {
    "bookmarks": ("Read and change bookmarks", 0.86),
    "browsingData": ("Clear browsing data", 0.86),
    "clipboardRead": ("Read the clipboard", 0.88),
    "clipboardWrite": ("Write to the clipboard", 0.82),
    "contentSettings": ("Change per-site browser settings", 0.86),
    "cookies": ("Read and set cookies", 0.88),
    "debugger": ("Attach the browser debugger", 0.92),
    "downloads": ("Manage downloads", 0.84),
    "geolocation": ("Read the device location", 0.9),
    "history": ("Read and change browsing history", 0.88),
    "management": ("Manage other extensions", 0.9),
    "nativeMessaging": ("Talk to a program installed on the computer", 0.92),
    "notifications": ("Show desktop notifications", 0.8),
    "pageCapture": ("Capture page contents", 0.86),
    "privacy": ("Change privacy settings", 0.88),
    "proxy": ("Route traffic through a proxy", 0.9),
    "scripting": ("Inject scripts into pages", 0.88),
    "storage": ("Store data in the browser", 0.72),
    "tabCapture": ("Capture tab audio and video", 0.88),
    "tabs": ("Read tab titles and addresses", 0.82),
    "topSites": ("Read the most-visited sites", 0.84),
    "webNavigation": ("Watch navigation between pages", 0.86),
    "webRequest": ("Observe and modify network requests", 0.9),
    "webRequestBlocking": ("Block network requests", 0.9),
}

#: How far past its own page each permission reaches. Three tiers, and the line
#: between them is a property of the capability rather than a feeling about it:
#: `device` touches hardware, the filesystem, or stored credentials -- things
#: that outlive the browser session and belong to the person, not the page.
#: `browser` reaches other pages, other sites, or the traffic between them, so
#: the tool learns things the reader never showed it. `page` is everything left:
#: capabilities that need a prompt but stop at the tab the tool runs in.
#:
#: A first calibration, and worth saying so. The three tiers were drawn from
#: what each API grants as documented, not from a measurement of how these
#: permissions are used in practice -- there was no such measurement to draw on,
#: because until this bucket existed nothing recorded them. What is measured is
#: how often they appear at all: over en.wikipedia's 90,016 User and MediaWiki
#: `.js` pages, `// @connect` on 444, `// @grant` on 307, navigator.clipboard on
#: 110, Notification.requestPermission on 19, getUserMedia on none.
BROWSER_PERMISSION_DEVICE = frozenset(
    {
        "bluetooth",
        "camera-microphone",
        "credentials",
        "extension:nativeMessaging",
        "file-system",
        "geolocation",
        "extension:geolocation",
        "hid",
        "midi",
        "screen-capture",
        "serial",
        "usb",
    }
)

BROWSER_PERMISSION_BROWSER = frozenset(
    {
        "cross-origin-request",
        "extension:bookmarks",
        "extension:browsingData",
        "extension:contentSettings",
        "extension:cookies",
        "extension:debugger",
        "extension:downloads",
        "extension:history",
        "extension:management",
        "extension:pageCapture",
        "extension:privacy",
        "extension:proxy",
        "extension:scripting",
        "extension:tabCapture",
        "extension:tabs",
        "extension:topSites",
        "extension:webNavigation",
        "extension:webRequest",
        "extension:webRequestBlocking",
        "storage-access",
    }
)

BROWSER_PERMISSION_REACH_DEVICE = "device"
BROWSER_PERMISSION_REACH_BROWSER = "browser"
BROWSER_PERMISSION_REACH_PAGE = "page"

#: The user-script grants that reach past the page. `GM_xmlhttpRequest` is the
#: cross-origin helper -- the whole reason a script asks for it is to call a
#: host the page's origin policy would refuse -- and `GM_cookie` reads cookies
#: the script did not set. Every other grant stores values, adds menu commands,
#: or reaches the page's own window, which is where the script already is.
USER_SCRIPT_BROWSER_GRANTS = frozenset({"gm_cookie", "gm_xmlhttprequest", "gm.cookie", "gm.xmlhttprequest"})

#: Every site the reader visits, in the spellings a manifest and a user-script
#: `@match` use for it. The finding values carry the prefix the scanner gave
#: them, so both forms are listed rather than the bare pattern.
BROWSER_PERMISSION_EVERY_SITE = frozenset(
    {
        "host:<all_urls>",
        "host:*://*/*",
        "match:*://*/*",
        "match:<all_urls>",
        "match:http://*/*",
        "match:https://*/*",
        "include:*",
    }
)


def browser_permission_reach(value: str) -> str:
    """Report how far past its own page one browser-permission finding reaches.

    Keyed on the finding value rather than its category, because the category
    says where the permission was found -- a runtime call, a manifest, a
    user-script directive -- and three sources can name the same capability.
    Anything the tiers do not name is `page`: the conservative direction for a
    default here is the low one, because a capability nobody thought to classify
    is more likely to be a new prompt than a new way to read the reader's disk,
    and a default of `device` would put every unclassified string at the top of
    a report about what to worry about.
    """
    if value in BROWSER_PERMISSION_DEVICE:
        return BROWSER_PERMISSION_REACH_DEVICE
    if value in BROWSER_PERMISSION_BROWSER or value in BROWSER_PERMISSION_EVERY_SITE:
        return BROWSER_PERMISSION_REACH_BROWSER
    prefix, _colon, rest = value.partition(":")
    if prefix == "grant" and rest.casefold() in USER_SCRIPT_BROWSER_GRANTS:
        return BROWSER_PERMISSION_REACH_BROWSER
    if prefix == "connect":
        # A host the script is allowed to call from a page it does not own.
        return BROWSER_PERMISSION_REACH_BROWSER
    return BROWSER_PERMISSION_REACH_PAGE


#: A WebExtension manifest, and not a Progressive Web App manifest or a package
#: of the same name: `manifest_version` is required in the first and absent from
#: both others, so it is what separates them. Read over the whole file rather
#: than per line, because the permission array and this key are rarely adjacent.
EXTENSION_MANIFEST_RE = re.compile(r'"manifest_version"\s*:')

#: An address a manifest asks to run on. `<all_urls>` and `*://*/*` are the two
#: spellings of "every site the reader visits", and both are worth naming as
#: themselves rather than folded into a count.
#: The asterisk is required. Without it this matches `"homepage_url"`'s value
#: and every other address in the manifest, none of which is a permission; a
#: match pattern that grants nothing beyond one exact page is not what a
#: reviewer needs told either way.
EXTENSION_HOST_MATCH_RE = re.compile(r'"(<all_urls>|[a-z*]{1,10}://[^"\s]{0,60}\*[^"\s]{0,60})"')

#: One alternation rather than 24 searches per line. The lookahead drops a key
#: of the same name: in a manifest `"storage"` is a permission and
#: `"storage":` is the section that configures it.
WEB_EXTENSION_PERMISSION_RE = re.compile(r'"(' + "|".join(sorted(WEB_EXTENSION_PERMISSIONS)) + r')"\s*(?!:)')

#: Every site the reader visits, in the two spellings a manifest uses for it.
EXTENSION_ALL_HOSTS = frozenset({"<all_urls>", "*://*/*"})

#: `// @grant GM_setValue`, `// @connect example.org`, `// @match https://*/*`.
#: Anchored to the line start because these are only directives inside the
#: metadata block; the same words appear in prose and in JSDoc mid-line.
USER_SCRIPT_DIRECTIVE_RE = re.compile(r"^\s*//\s*@(grant|connect|match|include)\s+(\S{1,120})\s*$")

USER_SCRIPT_DIRECTIVE_LABELS = {
    "grant": ("Privileged user-script API", 0.9, "Declared in a user-script @grant directive."),
    "connect": ("Cross-origin host the script may call", 0.88, "Declared in a user-script @connect directive."),
    "match": ("Site the script runs on", 0.76, "Declared in a user-script @match directive."),
    "include": ("Site the script runs on", 0.7, "Declared in a user-script @include directive."),
}


#: The suffix that marks a file as a stylesheet, and what to look for once it
#: is one. `.css` has always been inside SOURCE_SUFFIXES, so gadget stylesheets
#: were fetched and counted against the file and byte budget, but nothing read
#: them for what only a stylesheet does: name an address the reader's browser
#: fetches without any script running.
#:
#: The endpoint scanner sees a line of CSS, but `STATIC_ASSET_RE` drops
#: anything ending in an image or font extension, and that filter is right --
#: it exists because interface icons were fifteen of twenty-four findings on
#: one tool. So the same URLs that filter removes from "what does this tool
#: talk to" are recorded here instead, where the question is different: a
#: background image or a webfont on somebody else's host sends every reader's
#: address and browser to that host on every page view, with no request the
#: reader made and no script to audit.
CSS_SUFFIX = ".css"

#: `@import url("...")`, `@import "..."`, `url(...)` and the `src:` inside an
#: `@font-face` all resolve through the same `url()` or `@import` opening, so
#: one pattern covers them. Protocol-relative `//host/path` is included because
#: it is the older spelling of the same request and still common in gadget CSS.
CSS_REMOTE_REF_RE = re.compile(
    r"(?:@import\s+(?:url\(\s*)?|url\(\s*)[\'\"]?\s*((?:https?:)?//[^\'\")\s]{1,300})",
    re.IGNORECASE,
)

#: The page every wiki registers its gadgets on. Named here because it is not a
#: file with an extension and so is recognised by title alone. Two spellings
#: because they serve different readers: the lowercase one is what path matching
#: compares against, the titled one is what a maintainer opens.
GADGET_DEFINITION_PAGE = "mediawiki:gadgets-definition"
GADGET_DEFINITION_PAGE_TITLE = "MediaWiki:Gadgets-definition"

#: The definition options this analyzer reads. `rights` limits who the gadget is
#: served to; `default` turns it on for everyone who is not excluded; `hidden`
#: keeps it out of the gadget preferences list, so nobody can switch it on or
#: off there. All three are declarations by the wiki, not inferences from code.
#:
#: `hidden` is the other half of `default` and was measured with it: across the
#: same five definition pages, 99 of 487 entries declare `hidden` and 85 declare
#: `default`. Declared together -- 25 entries -- they say the gadget runs for
#: every reader it covers and none of them can turn it off, which is the
#: strongest reach a gadget can have; `hidden` on its own, the largest group at
#: 74, usually marks a module another gadget pulls in as a peer.
GADGET_RIGHTS_OPTION = "rights"
GADGET_DEFAULT_OPTION = "default"
GADGET_HIDDEN_OPTION = "hidden"

#: The options that narrow where a `default` gadget actually loads, mapped to
#: the words a reader outside the wiki would use for them. Reading `default`
#: without these overstates every scoped gadget: `default|namespaces=0` runs on
#: article pages and nowhere else, and `default|rights=sysop` is on by default
#: for administrators, neither of which is "every reader loads this".
#:
#: Reading `default` alone is wrong far more often than it is right: of those 85
#: `default` entries only 16 are unqualified, while 44 carry one or more of the
#: options below and 25 are also `hidden`. Across all 487 entries the limits
#: run actions 102, skins 82, namespaces 78, rights 69, categories 19,
#: contentModels 4.
#:
#: Keys are spelled as MediaWiki spells them, because the definition parser
#: transcribes option names rather than normalizing them, and `contentModels`
#: is the one that is not lowercase. `rights` is a limit here as well as a
#: findings source: `default|rights=sysop` is on by default for administrators,
#: which is a smaller audience than "every reader" by several orders.
GADGET_SCOPE_OPTIONS: dict[str, str] = {
    "actions": "page action",
    "categories": "page category",
    "contentModels": "content model",
    "namespaces": "namespace",
    "rights": "user right",
    "skins": "skin",
}

#: The option naming the ResourceLoader modules a gadget loads before its own
#: code runs, and the ecosystem those modules are reported under. A gadget has
#: no package.json, so this line is the only dependency manifest it has: across
#: the five definition pages 235 of 487 entries declare it, naming 71 distinct
#: modules in 518 declarations. Left unread, every on-wiki tool in the catalogue
#: had an empty dependency list by construction rather than by fact.
#:
#: `resourceloader` rather than `mediawiki` as the ecosystem name because it is
#: the registry the names resolve in, the way `npm` names a registry and not a
#: language, and because gadget dependencies must not collide with the pypi and
#: npm MediaWiki clients that already carry those names.
GADGET_DEPENDENCIES_OPTION = "dependencies"
GADGET_MODULE_ECOSYSTEM = "resourceloader"

#: Runtime, not build: ResourceLoader resolves these when the reader's browser
#: loads the page, so every one of them is code that actually ships. The
#: confidence matches a declared Python requirement (0.94) because it is the
#: same kind of statement -- a manifest naming what must be present -- read from
#: the wiki's own registry rather than inferred from source.
GADGET_MODULE_CATEGORY = "runtime"
GADGET_MODULE_CONFIDENCE = 0.94

#: What `rights=` may name, mapped onto the same value slugs the inferred rights
#: in ACTION_RIGHTS use, so a gadget that declares `rollback` and also calls
#: `action=rollback` produces one finding carrying both pieces of evidence
#: rather than two rows for one right. The label travels with the slug because
#: a raw MediaWiki right reads as jargon to anyone outside the wiki.
#:
#: No category column, and that absence is the point: every one of these is
#: reported under GADGET_DECLARED_RIGHT_CATEGORY, because the definition line
#: states who is served, not what the code does. A right the gadget was also
#: seen exercising is categorized by that sighting instead.
#:
#: Measured rather than imagined, and re-measured after the first reading proved
#: too narrow. The first pass read five definition pages -- en.wikipedia (113
#: gadgets), commons (142), de.wikipedia (62), fr.wikipedia (95), wikidata (76)
#: -- where 69 of 488 entries declare `rights=` and name exactly twenty-one
#: distinct rights. Reading fifteen more pages -- the es, ru, ja, it, pl, pt,
#: zh, nl, sv, ar, fa and he Wikipedia editions, plus meta, en.wikisource and
#: en.wiktionary, 1576 entries and 189 declarations -- found 36 declarations
#: naming seventeen further
#: rights, none of which the first table had. Five wikis were 19% short.
#:
#: The additions are not exotic. `protect`, `review` and `deleterevision` are
#: ordinary moderation, and they were missing only because the wikis that had
#: been read happen to gate those gadgets differently. That is the shape of the
#: error a single reading produces: not a strange long tail, but common rights
#: absent by accident of which pages were open.
#:
#: `edit` (18) and `upload`/`delete` (8 each) still carry most of the traffic;
#: the long tail is one or two sightings each. Unmeasured rights are not dropped
#: -- see `_gadget_right_row` -- so this table is a labelling aid, not a filter.
#:
#: A measurement taken once decays without saying so, and this one describes
#: pages other people edit. Every report now carries `declaredRightCount` and
#: `unknownDeclaredRightCount`, so the share of declared rights this table
#: cannot describe is a query rather than a re-reading of five wikis: while it
#: stays at zero the twenty-one below are still the whole story, and the first
#: run that reports otherwise names the rights to add.
GADGET_RIGHT_VOCABULARY: dict[str, tuple[str, str]] = {
    "autoconfirmed": ("autoconfirmed", "Autoconfirmed users only"),
    "autopatrol": ("autopatrol", "Have edits auto-patrolled"),
    "autoreview": ("autoreview", "Have edits auto-reviewed"),
    "block": ("block", "Block users"),
    "bot": ("bot", "Bot accounts only"),
    "browsearchive": ("browse-archive", "Search deleted pages"),
    "centralauth-rename": ("global-account-rename", "Rename global accounts"),
    "centralauth-suppress": ("global-account-suppress", "Suppress global accounts"),
    "createpage": ("create-page", "Create pages"),
    "delete": ("delete", "Delete pages"),
    "deletedhistory": ("deleted-history", "Read deleted page history"),
    "deletedtext": ("deleted-text", "Read deleted page text"),
    "deleterevision": ("revision-delete", "Delete or suppress revision data"),
    "edit": ("edit", "Edit pages"),
    "editeditorprotected": ("edit-editor-protected", "Edit editor-protected pages"),
    "editinterface": ("edit-interface", "Edit the site interface"),
    "editmyuserjs": ("edit-my-user-js", "Edit your own JavaScript"),
    "editprotected": ("edit-protected", "Edit protected pages"),
    "extendedconfirmed": ("extendedconfirmed", "Extended-confirmed users only"),
    "import": ("import", "Import pages"),
    "ipinfo-view-full": ("view-ip-information", "View full IP information"),
    "item-merge": ("wikibase-item-merge", "Merge Wikibase items"),
    "item-redirect": ("wikibase-item-redirect", "Create Wikibase item redirects"),
    "markbotedits": ("mark-bot-edits", "Mark edits as bot edits"),
    "minoredit": ("minor-edit", "Mark edits as minor"),
    "move": ("move", "Move pages"),
    "override-antispoof": ("override-username-check", "Override the username similarity check"),
    "patrol": ("patrol", "Patrol edits"),
    "protect": ("protect", "Protect pages"),
    "read": ("read", "Read pages"),
    "review": ("review", "Review pending changes"),
    "rollback": ("rollback", "Rollback edits"),
    "sendemail": ("send-email", "Send email to users"),
    "suppressredirect": ("suppress-redirect", "Move pages without leaving a redirect"),
    "templateeditor": ("template-editor", "Edit protected templates"),
    "undelete": ("undelete", "Undelete pages"),
    "upload": ("upload", "Upload files"),
    "viewmywatchlist": ("view-watchlist", "Read your watchlist"),
}

#: The category every declared right is reported under. `rights=` says who the
#: gadget is served to, which is not the same claim as "this tool performs that
#: action" -- the wiki gates a rollback gadget on that right because the gadget
#: rolls back, but the line itself only states the gate. Keeping the
#: whole vocabulary outside the write set leaves `writeActionsDetected`, and the
#: unauthenticated-write penalty it drives, to be settled by code that was
#: actually read. A right the table does not label is still a right the wiki
#: declared, so it is reported here under its own name rather than discarded:
#: five wikis are not every wiki, and a gadget limited to a right this analyzer
#: has never seen is exactly the one a reader most needs told about.
GADGET_DECLARED_RIGHT_CATEGORY = "restricted"

#: A declared right sits just under the confidence an observed `action=` call
#: earns (0.94): the wiki's own registry is a strong statement, but a sighting
#: in the code it describes is a stronger one.
GADGET_DECLARED_RIGHT_CONFIDENCE = 0.9

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

#: A version constraint that pins one release, in any of the spellings the
#: manifests use: `1.2.3`, `==1.2.3`, `=1.2.3`, `v1.2.3`. Everything else --
#: `^1.2`, `>=3.0`, `~> 2.0` -- is a range, and a range is not a version.
EXACT_VERSION_RE = re.compile(r"^(?:==|=|v)?\s*(\d+(?:\.\d+){0,3}(?:[-+][0-9A-Za-z.-]+)?)$")
#: Constraints that name no version at all. Recording them would turn "no
#: version declared" into "version declared as *", which reads as a fact.
UNVERSIONED_SPECS = frozenset({"*", "x", "latest", "any", "@latest"})
#: A dependency resolved from somewhere other than the registry. The string
#: after the marker is a URL or a path, never a version.
NON_VERSION_SPEC_PREFIXES = ("git+", "git:", "http://", "https://", "file:", "link:", "workspace:", "portal:", "npm:")
#: Where a version sits in a `gem "name", "~> 1.2"` line and in a
#: `name (1.2.3)` Gemfile.lock line.
#: The constraint in a `gem "name", "~> 1.2"` line. It has to be the second
#: positional argument: an option such as `gem "puma", group: "dev"` puts a
#: bare word after the comma, and reading that as a version would report the
#: group name as one.
GEM_VERSION_RE = re.compile(r"^\s*gem\s+[\"'][^\"']+[\"']\s*,\s*[\"']([^\"']+)[\"']")
GEM_LOCK_VERSION_RE = re.compile(r"^\s{4}[A-Za-z0-9_.-]+\s+\(([^)]+)\)")
#: `module/path v1.2.3` in a go.mod require block.
GO_VERSION_RE = re.compile(r"^\s*[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+\s+(v?\d[^\s/]*)")
#: The `go 1.21` line in a go.mod, which names the language version rather
#: than a module.
GO_DIRECTIVE_RE = re.compile(r"^go\s+(\d[0-9.]*)$")
#: The resolved version yarn and pnpm write on the line below a locator.
YARN_VERSION_RE = re.compile(r"^\s+[\"']?version[\"']?:?\s+[\"']?([^\"'\s,]+)[\"']?\s*$")


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


def _clean_context_string(value: object) -> str | None:
    text = str(value or "").strip()
    return text[:MAX_CONTEXT_STRING_CHARS] if text else None


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
