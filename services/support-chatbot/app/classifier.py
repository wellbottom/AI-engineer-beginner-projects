"""Out-of-scope classifier seam for the Support Chatbot (Requirement 5.4).

Requirement 5.4 says that when a user message is *detected to fall outside the
configured set of supported topics*, the service returns a single canned reply and
generates no other assistant reply. The detection itself is an **injectable seam**
so it can be stubbed in tests and swapped for a more capable implementation (e.g. an
LLM-based classifier) without touching the streaming/persistence logic.

A classifier is any callable ``(message: str, history: list[Turn]) -> bool`` that
returns ``True`` when the message is out of scope.

This module ships a small, **deliberately conservative** default keyword classifier
(:func:`make_keyword_classifier`): it flags a message as out-of-scope only when it
contains an explicit off-topic signal (e.g. "weather", "stock price", "medical
advice"). The conservative default avoids misclassifying ordinary support chatter or
greetings as out-of-scope; a production deployment can inject a stronger classifier.
The default deny-list is overridable via the ``SUPPORT_OUT_OF_SCOPE_KEYWORDS`` env
var (comma-separated) so the configured topic boundary can be tuned without code
changes.
"""

from __future__ import annotations

import os
from typing import Callable, Iterable, Mapping, Sequence

from .session_store import Turn

__all__ = [
    "Classifier",
    "make_keyword_classifier",
    "load_classifier",
    "DEFAULT_DENY_KEYWORDS",
    "ENV_DENY_KEYWORDS",
]

#: A classifier predicate: ``(message, history) -> is_out_of_scope``.
Classifier = Callable[[str, "list[Turn]"], bool]

#: Env var to override the default deny-list (comma-separated keywords).
ENV_DENY_KEYWORDS = "SUPPORT_OUT_OF_SCOPE_KEYWORDS"

#: Default off-topic signals for the bundled persona (ACME Cloud support). These
#: are clearly unrelated to accounts/billing/features/setup/troubleshooting.
DEFAULT_DENY_KEYWORDS: tuple[str, ...] = (
    "weather",
    "stock price",
    "sports score",
    "medical advice",
    "legal advice",
    "write me a poem",
    "recipe",
    "horoscope",
    "election",
)


def make_keyword_classifier(deny_keywords: Iterable[str] = DEFAULT_DENY_KEYWORDS) -> Classifier:
    """Build a conservative keyword-based out-of-scope classifier.

    The returned predicate flags a message as out-of-scope iff it contains any of
    ``deny_keywords`` (case-insensitive substring match). Conversation ``history``
    is accepted for signature compatibility but not used by this simple default.

    Args:
        deny_keywords: Off-topic signal phrases. Defaults to
            :data:`DEFAULT_DENY_KEYWORDS`.

    Returns:
        A :data:`Classifier` callable.
    """
    keywords = tuple(kw.lower() for kw in deny_keywords if kw and kw.strip())

    def classify(message: str, history: "list[Turn]") -> bool:  # noqa: ARG001 - history unused by default
        lowered = message.lower()
        return any(kw in lowered for kw in keywords)

    return classify


def load_classifier(*, env: Mapping[str, str] | None = None) -> Classifier:
    """Resolve the active classifier at startup from configuration (Requirement 5.4).

    Reads the optional ``SUPPORT_OUT_OF_SCOPE_KEYWORDS`` override (comma-separated)
    and returns a keyword classifier built from it, falling back to
    :data:`DEFAULT_DENY_KEYWORDS`. Injecting ``env`` keeps this testable.
    """
    environ = env if env is not None else os.environ
    raw = (environ.get(ENV_DENY_KEYWORDS) or "").strip()
    if raw:
        keywords: Sequence[str] = [part.strip() for part in raw.split(",") if part.strip()]
        return make_keyword_classifier(keywords)
    return make_keyword_classifier()
