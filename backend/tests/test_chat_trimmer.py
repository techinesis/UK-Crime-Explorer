"""Pure unit tests for the deterministic history trimmer (core/chat_history.py).

The trimmer is duck-typed; we feed it real ``ChatMessage`` objects (the shape it
sees in production) so the tests double as a contract check on the schema.
"""

from __future__ import annotations

from api.chat import ChatMessage, ChatToolCall, ChatToolResult
from core.chat_history import (
    DEFAULT_HISTORY_TOKEN_BUDGET,
    TOOL_CALL_OVERHEAD_TOKENS,
    trim_history,
)


def _msg(role: str, content: str, *, tool_calls=None, tool_results=None) -> ChatMessage:
    return ChatMessage(role=role, content=content, tool_calls=tool_calls, tool_results=tool_results)


def test_constants_match_spec():
    assert DEFAULT_HISTORY_TOKEN_BUDGET == 8000
    assert TOOL_CALL_OVERHEAD_TOKENS == 40


def test_empty_returns_empty():
    assert trim_history([]) == []


def test_under_budget_keeps_all_in_order():
    msgs = [_msg("user", "aaaa"), _msg("assistant", "bbbb"), _msg("user", "cccc")]
    out = trim_history(msgs, budget=100)
    assert out == msgs


def test_exactly_at_budget_is_inclusive():
    # 20 chars -> 5 tokens each; two of them sum to exactly the budget.
    msgs = [_msg("user", "x" * 20), _msg("assistant", "y" * 20)]
    out = trim_history(msgs, budget=10)
    assert out == msgs


def test_over_budget_drops_oldest_preserves_order():
    m1, m2, m3 = _msg("user", "x" * 20), _msg("assistant", "y" * 20), _msg("user", "z" * 20)
    out = trim_history([m1, m2, m3], budget=10)
    assert out == [m2, m3]  # oldest dropped, chronological order preserved
    assert m1 not in out
    assert sum(len(m.content) // 4 for m in out) <= 10


def test_single_oversized_message_is_kept():
    big = _msg("user", "x" * 40)  # 10 tokens, alone over a budget of 5
    assert trim_history([big], budget=5) == [big]


def test_oversized_newest_among_others_keeps_just_newest():
    small = _msg("user", "x" * 4)  # 1 token
    big = _msg("assistant", "y" * 40)  # 10 tokens, newest
    # The newest is always kept; the older one no longer fits.
    assert trim_history([small, big], budget=5) == [big]


def test_tool_calls_overhead_is_counted():
    # Three 1-token messages; the newest carries tool_calls (+40 overhead).
    m1 = _msg("user", "aaaa")
    m2 = _msg("user", "bbbb")
    m3 = _msg(
        "assistant",
        "cccc",
        tool_calls=[ChatToolCall(name="get_weights", input={"category": "Drugs"}, id="t1")],
    )
    budget = 42  # newest (41) + one 1-token message fits; the third does not.
    assert trim_history([m1, m2, m3], budget=budget) == [m2, m3]
    # Same content WITHOUT the tool overhead all fits at the same budget,
    # proving the +40 is what dropped the oldest turn.
    plain = [_msg(m.role, m.content) for m in (m1, m2, m3)]
    assert trim_history(plain, budget=budget) == plain


def test_tool_results_also_incur_overhead():
    m = _msg(
        "assistant",
        "cccc",
        tool_results=[ChatToolResult(tool_use_id="t1", name="get_weights", output={"ok": True})],
    )
    pre = _msg("user", "aaaa")  # 1 token
    # m is 1 content token + 40 overhead = 41; with budget 41 the preceding
    # 1-token message no longer fits.
    assert trim_history([pre, m], budget=41) == [m]
