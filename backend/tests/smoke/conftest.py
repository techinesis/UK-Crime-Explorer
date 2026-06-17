"""Shared fixtures for the end-to-end smoke suite.

These fixtures drive the real FastAPI app against the committed data snapshot —
no LLM call, no network. The chat HTTP fixture (``mock_llm``) stubs the Anthropic
client so the streaming route runs deterministically and offline.

Import convention matches the rest of the suite: bare module names
(``from api.main import app``, ``from core import chat as chat_core``), never
``backend.``-prefixed. pytest runs with ``backend/`` as the rootdir.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

import pytest

from core import chat as chat_core

# --------------------------------------------------------------------------- #
# Fake Anthropic streaming client (mirrors backend/tests/test_chat.py)
# --------------------------------------------------------------------------- #
# run_chat_stream() consumes a client whose ``messages.stream(**kwargs)`` returns
# a context manager exposing a ``text_stream`` iterator and ``get_final_message()``.
# We return canned turns in order so the SSE route emits deterministic events
# without ever importing ``anthropic`` or touching the network.


class _FakeStream:
    """One assistant turn: streams ``text_deltas`` then exposes a final message
    whose content is ``blocks`` (plain dicts)."""

    def __init__(self, text_deltas: list[str], blocks: list[dict]) -> None:
        self.text_stream = iter(text_deltas)
        self._final = SimpleNamespace(content=blocks, stop_reason="end_turn")

    def __enter__(self) -> "_FakeStream":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def get_final_message(self) -> SimpleNamespace:
        return self._final


class _FakeStreamMessages:
    def __init__(self, turns: list[_FakeStream]) -> None:
        self._turns = list(turns)
        self.calls: list[dict] = []

    def stream(self, **kwargs: object) -> _FakeStream:
        self.calls.append(kwargs)
        return self._turns.pop(0)


class FakeClient:
    """Returns the given streaming turns in order (one per model round-trip)."""

    def __init__(self, turns: list[_FakeStream]) -> None:
        self.messages = _FakeStreamMessages(turns)


def _text_turn(text: str) -> _FakeStream:
    """A final-answer turn: streams ``text`` (as two deltas) with a text block."""
    mid = max(1, len(text) // 2)
    return _FakeStream([text[:mid], text[mid:]], [{"type": "text", "text": text}])


def _tool_turn(tool_id: str, name: str, args: dict) -> _FakeStream:
    """A tool-use turn: no visible text, one tool_use block."""
    return _FakeStream([], [{"type": "tool_use", "id": tool_id, "name": name, "input": args}])


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def client():
    """A TestClient bound to the real app. Entering the context manager triggers
    the lifespan startup, which warms the crime frame, weights, and meta cache."""
    pytest.importorskip("slowapi")  # the chat route and its rate limiter need it
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def meta(client):
    """The parsed GET /api/meta response, fetched once per test module."""
    res = client.get("/api/meta")
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture
def sample_filter() -> dict:
    """One borough, one category, one year-month. ``level``/``metric`` are set by
    the test; everything else is a concrete, data-bearing selection."""
    return {
        "categories": ["Drugs"],
        "tier": "All tiers",
        "year": 2024,
        "months": [3],
        "borough": "Camden",
        "severity_basis": "mean",
        "city": "london",
    }


@pytest.fixture
def mock_llm():
    """Context-manager factory that stubs the Anthropic client used by the chat
    route, so POST /api/chat streams a canned response offline.

    Usage::

        with mock_llm():                       # default: set_filters turn + reply
            res = client.post("/api/chat", json=...)
        with mock_llm([_tool_turn(...), _text_turn(...)]):
            ...

    Patches ``core.chat.build_client`` (api.chat calls ``chat_core.build_client``)
    and forces ``chat_core.chat_available`` True so the pre-flight gate passes.
    """

    def _default_turns() -> list[_FakeStream]:
        # A tool turn (yields a tool_call + an action event) then a reply turn.
        return [
            _tool_turn("t1", "set_filters", {"borough": "Camden"}),
            _text_turn("Filtered the map to Camden."),
        ]

    @contextmanager
    def _mock(turns: list[_FakeStream] | None = None):
        chosen = _default_turns() if turns is None else turns
        with mock.patch.object(chat_core, "chat_available", lambda: True), mock.patch.object(
            chat_core, "build_client", lambda: FakeClient(list(chosen))
        ):
            yield

    return _mock
