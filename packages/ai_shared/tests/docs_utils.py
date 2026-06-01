"""Shared helpers for the per-project documentation property tests.

These helpers discover the six mini-project documentation directories by path
(``services/<slug>``) and parse the Markdown docs (``README.md`` / ``guide.md`` /
``key.md``). They back the Property 29/30/31 tests for Requirement 10.

The tests are pure file-scanning: they never touch the database or any provider,
so they have no environment prerequisites beyond the repo checkout.
"""

from __future__ import annotations

import re
from pathlib import Path

# Repo root: tests/ -> ai_shared/ -> packages/ -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICES_DIR = REPO_ROOT / "services"

# The six mini-projects, identified by their service directory slug. This is the
# canonical enumeration the doc-structure properties quantify over.
PROJECT_SLUGS: tuple[str, ...] = (
    "llm-playground",
    "support-chatbot",
    "web-agent",
    "deep-research",
    "image-service",
    "capstone",
)

# The three Project_Docs files required for every mini-project (Requirement 10.1).
DOC_FILES: tuple[str, ...] = ("README.md", "guide.md", "key.md")

# Required section headings per file type (design "Documentation Model";
# Requirements 10.2, 10.3, 10.4). Order is the canonical document order but the
# uniformity property compares heading *sets*.
REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "README.md": ("Purpose", "Setup Steps", "Run Command"),
    "guide.md": ("Navigate to Project", "Submit a Request", "View the Response"),
    "key.md": (
        "Operation Process",
        "Request/Response Flow",
        "Core Mechanism",
        "External Providers",
    ),
}

# The closed set of external providers a key.md may name (Requirement 10.5).
ALL_PROVIDERS: frozenset[str] = frozenset(
    {
        "LLM_Gateway",
        "Search_Provider",
        "Vector_Store",
        "Embeddings_Service",
        "Image_Provider",
    }
)

# Each project's ACTUAL external-provider dependencies (the oracle for Property 31),
# derived from the built services. Every one of the six depends on at least one;
# a hypothetical no-dependency project would map to ``frozenset()`` and its key.md
# would state it depends on none.
EXPECTED_PROVIDERS: dict[str, frozenset[str]] = {
    "llm-playground": frozenset({"LLM_Gateway"}),
    "support-chatbot": frozenset({"LLM_Gateway"}),
    "web-agent": frozenset({"Search_Provider", "LLM_Gateway"}),
    "deep-research": frozenset(
        {"Search_Provider", "LLM_Gateway", "Embeddings_Service", "Vector_Store"}
    ),
    "image-service": frozenset({"Image_Provider"}),
    "capstone": frozenset({"LLM_Gateway", "Embeddings_Service", "Vector_Store"}),
}

# All 15 unordered pairs of distinct projects (for the cross-project uniformity
# quantifier in Property 29).
PROJECT_PAIRS: tuple[tuple[str, str], ...] = tuple(
    (PROJECT_SLUGS[i], PROJECT_SLUGS[j])
    for i in range(len(PROJECT_SLUGS))
    for j in range(i + 1, len(PROJECT_SLUGS))
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
# Match a provider token only as a whole word (case-sensitive: provider names are
# proper identifiers, so "image_provider" or "llm gateway" must NOT match).
_PROVIDER_RES: dict[str, re.Pattern[str]] = {
    name: re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
    for name in ALL_PROVIDERS
}


def doc_path(slug: str, filename: str) -> Path:
    """Absolute path to one Project_Docs file."""
    return SERVICES_DIR / slug / filename


def read_doc(slug: str, filename: str) -> str:
    """Read a doc file as UTF-8 text (raises if it does not exist)."""
    return doc_path(slug, filename).read_text(encoding="utf-8")


def heading_texts(markdown: str) -> list[str]:
    """All ATX heading texts (any level) in document order, trimmed."""
    out: list[str] = []
    for line in markdown.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            out.append(m.group(2).strip())
    return out


def section_headings(markdown: str) -> set[str]:
    """The set of level-2 (``##``) section headings in the document.

    The Documentation Model uses ``##`` for the named sections of every file type,
    so the uniformity property compares the level-2 heading sets (ignoring the
    level-1 document title, which is project-specific).
    """
    out: set[str] = set()
    for line in markdown.splitlines():
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) == 2:
            out.add(m.group(2).strip())
    return out


def section_body(markdown: str, heading: str) -> str:
    """Return the text under a ``## <heading>`` section, up to the next ``##``.

    Used to scope provider detection to the ``External Providers`` section so a
    provider mentioned only in prose elsewhere does not count.
    """
    lines = markdown.splitlines()
    collecting = False
    body: list[str] = []
    for line in lines:
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) == 2:
            if collecting:
                break
            collecting = m.group(2).strip() == heading
            continue
        if collecting:
            body.append(line)
    return "\n".join(body)


def _list_item_lines(body: str) -> str:
    """Join only the Markdown list-item lines (``-``/``*`` bullets) of a body.

    The External Providers section names each *actual* dependency as a bullet and
    then names the *non*-dependencies in a plain "It does not depend on ..."
    sentence. Scoping detection to bullet lines counts only the listed providers
    and ignores the negative prose, so a project is never credited with a provider
    it explicitly disclaims.
    """
    items = [
        ln
        for ln in body.splitlines()
        if re.match(r"^\s*[-*]\s+", ln)
    ]
    return "\n".join(items)


def providers_listed(external_providers_body: str) -> set[str]:
    """The set of canonical provider names listed in an External Providers body.

    Only Markdown list items are scanned (see ``_list_item_lines``); detection is
    case-sensitive and whole-word so only the exact canonical identifiers (e.g.
    ``LLM_Gateway``) count.
    """
    items = _list_item_lines(external_providers_body)
    return {name for name, pat in _PROVIDER_RES.items() if pat.search(items)}


def states_depends_on_none(external_providers_body: str) -> bool:
    """True if the body explicitly states the project depends on none of them."""
    return "depends on none" in external_providers_body.lower()
