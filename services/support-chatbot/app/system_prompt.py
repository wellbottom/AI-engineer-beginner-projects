"""Configurable support persona system prompt, loaded once at startup (Req. 5.3).

The Support Chatbot uses a configurable system prompt that defines the assistant's
support persona and the set of supported topics. Per Requirement 5.3 it is loaded
**once at Backend_Service startup** (in :mod:`app.main`'s lifespan) and then held
on ``app.state`` for the lifetime of the process — it is not re-read per request.

**Source of the prompt (documented).** The prompt text is resolved at startup by
:func:`load_system_prompt` in this precedence order:

1. ``SUPPORT_SYSTEM_PROMPT`` — the literal prompt text, if set and non-empty.
2. ``SUPPORT_SYSTEM_PROMPT_FILE`` — a path to a UTF-8 text file whose contents are
   the prompt, if set and the file is readable.
3. The bundled default file ``app/support_system_prompt.txt`` shipped with the
   service.
4. A hard-coded :data:`DEFAULT_SYSTEM_PROMPT` fallback (so the service always has a
   persona even with no configuration and no file).

This keeps the persona/topics configurable (an env var for quick overrides or a
checked-in file for longer prompts) while guaranteeing a sensible default. The
function is pure with respect to its ``env``/``base_dir`` arguments, so tests inject
a fake environment and a temp directory to exercise each source deterministically.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

__all__ = [
    "load_system_prompt",
    "DEFAULT_SYSTEM_PROMPT",
    "ENV_PROMPT",
    "ENV_PROMPT_FILE",
    "DEFAULT_PROMPT_FILENAME",
]

#: Env var carrying the literal prompt text.
ENV_PROMPT = "SUPPORT_SYSTEM_PROMPT"
#: Env var carrying a path to a file whose contents are the prompt.
ENV_PROMPT_FILE = "SUPPORT_SYSTEM_PROMPT_FILE"
#: Bundled default prompt file shipped alongside this module.
DEFAULT_PROMPT_FILENAME = "support_system_prompt.txt"

#: Hard-coded last-resort persona (used only if no env var and no file resolve).
DEFAULT_SYSTEM_PROMPT = (
    "You are Aria, a friendly and knowledgeable customer support assistant for "
    "the ACME Cloud Platform. You help customers with questions about ACME Cloud "
    "accounts, billing and subscriptions, product features, setup and "
    "configuration, and troubleshooting. Answer clearly and concisely, stay "
    "polite and professional, and only address topics related to ACME Cloud "
    "products and support. If a request falls outside these supported topics, "
    "politely say it is outside what you can help with."
)


def load_system_prompt(
    *,
    env: Mapping[str, str] | None = None,
    base_dir: Path | None = None,
) -> str:
    """Resolve the configurable support system prompt (Requirement 5.3).

    Resolution precedence (first non-empty wins): the ``SUPPORT_SYSTEM_PROMPT``
    literal, then the file named by ``SUPPORT_SYSTEM_PROMPT_FILE``, then the
    bundled ``support_system_prompt.txt``, then :data:`DEFAULT_SYSTEM_PROMPT`.

    Args:
        env: Environment mapping to read (defaults to ``os.environ``). Injectable
            so tests can supply a fake environment.
        base_dir: Directory containing the bundled default file (defaults to this
            module's directory). Injectable for tests.

    Returns:
        The resolved prompt text (always non-empty).
    """
    environ = env if env is not None else os.environ
    root = base_dir if base_dir is not None else Path(__file__).resolve().parent

    # 1) Literal env var.
    literal = (environ.get(ENV_PROMPT) or "").strip()
    if literal:
        return literal

    # 2) File path env var.
    file_path = (environ.get(ENV_PROMPT_FILE) or "").strip()
    if file_path:
        text = _read_text(Path(file_path))
        if text:
            return text

    # 3) Bundled default file.
    bundled = _read_text(root / DEFAULT_PROMPT_FILENAME)
    if bundled:
        return bundled

    # 4) Hard-coded fallback.
    return DEFAULT_SYSTEM_PROMPT


def _read_text(path: Path) -> str:
    """Return the stripped UTF-8 contents of ``path``, or ``""`` if unreadable."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
