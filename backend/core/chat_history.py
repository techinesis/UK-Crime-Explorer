"""Deterministic chat-history trimmer.

Long conversations would otherwise balloon the payload sent to the LLM on every
turn. This keeps the *most recent* whole messages within a fixed token budget,
cutting at message boundaries (never mid-message). It is a pure function so it is
trivially unit-testable.

Decoupling: this lives in ``core`` and must not import the api-layer
``ChatMessage`` (that would invert the ``api -> core`` dependency). It therefore
works structurally — any object exposing ``role`` / ``content`` and, optionally,
``tool_calls`` / ``tool_results`` — read via ``getattr``. The system / persona
prompt is passed separately to the Anthropic client (never inside the message
list), so the trimmer structurally cannot touch it.

Token counting is a fast approximation (``len(content) // 4`` plus a flat
overhead for any message carrying tool calls/results). The Anthropic tokeniser is
deliberately *not* called per request — overkill for this workload.
"""

from __future__ import annotations

from typing import Protocol, Sequence, TypeVar

# History budget, in approximate tokens, EXCLUDING the system prompt (which is
# sent separately and never trimmed). Roughly 80 turns at a typical message
# length — the demo will not approach this.
DEFAULT_HISTORY_TOKEN_BUDGET = 8000

# Flat surcharge for any message that carries tool calls or tool results, to
# account for the tool payload that would accompany it.
TOOL_CALL_OVERHEAD_TOKENS = 40


class HistoryMessage(Protocol):
    """Structural type the trimmer needs. ``tool_calls`` / ``tool_results`` are
    optional and read via ``getattr`` so plain ``role``/``content`` objects fit."""

    role: str
    content: str


M = TypeVar("M", bound=HistoryMessage)


def _approx_tokens(message: HistoryMessage) -> int:
    """Fast token estimate for a single message."""
    tokens = len(message.content) // 4
    if getattr(message, "tool_calls", None) or getattr(message, "tool_results", None):
        tokens += TOOL_CALL_OVERHEAD_TOKENS
    return tokens


def trim_history(
    messages: Sequence[M], *, budget: int = DEFAULT_HISTORY_TOKEN_BUDGET
) -> list[M]:
    """Return the most recent messages whose summed approx-token cost fits in
    ``budget``, preserving chronological (oldest-first) order.

    - Iterates newest -> oldest, cutting at message boundaries.
    - Exactly-at-budget is inclusive (the break is on ``> budget``).
    - The single newest message is always kept, even if it alone exceeds the
      budget (so the model always sees at least the latest turn).
    - Empty input returns an empty list.
    """
    if not messages:
        return []

    kept: list[M] = []
    total = 0
    for message in reversed(messages):
        cost = _approx_tokens(message)
        if kept and total + cost > budget:
            break
        kept.append(message)
        total += cost
    kept.reverse()
    return kept
