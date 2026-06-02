"""Tests for the AI chat layer.

Three groups:

1. **Tool-call shapes** — the tool registry, filter normalisation, and each tool
   implementation (run against the real snapshotted data, like test_api).
2. **End-to-end** — the tool-use loop driven by a *mocked* Anthropic streaming
   client (canned text deltas + tool_use turns), exercising both the streaming
   generator (:func:`core.chat.run_chat_stream`) and the assembling wrapper
   (:func:`core.chat.run_chat`), the action protocol, and the audit trail —
   without any network call.
3. **HTTP** — the SSE route + persona + graceful 503.

The mocked client mimics the Anthropic streaming surface used by run_chat_stream:
``client.messages.stream(**kwargs)`` returns a context manager exposing a
``text_stream`` iterator and ``get_final_message()`` (a Message with ``content``
blocks). Content blocks are plain dicts, read via core.chat's dict/attr-agnostic
accessor.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import chat as chat_core
from core.chat import (
    DEFAULT_FILTERS,
    PERSONAS,
    TOOLS,
    dispatch_tool,
    normalize_filters,
    resolve_persona,
    run_chat,
    run_chat_stream,
    tool_get_weights,
    tool_query_data,
    tool_set_filters,
)


# --------------------------------------------------------------------------- #
# A minimal fake Anthropic *streaming* client
# --------------------------------------------------------------------------- #


class _FakeStream:
    """One assistant turn: streams ``text_deltas`` then exposes a final message
    whose content is ``blocks`` (plain dicts)."""

    def __init__(self, text_deltas: list[str], blocks: list[dict]) -> None:
        self.text_stream = iter(text_deltas)
        self._final = SimpleNamespace(content=blocks, stop_reason="end_turn")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._final


class _FakeStreamMessages:
    def __init__(self, turns: list) -> None:
        self._turns = list(turns)
        self.calls: list[dict] = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return self._turns.pop(0)


class FakeClient:
    """Returns canned streaming turns in order."""

    def __init__(self, turns: list) -> None:
        self.messages = _FakeStreamMessages(turns)


def _text_turn(text: str) -> _FakeStream:
    """A final-answer turn: streams the text (as two deltas) with a text block."""
    mid = max(1, len(text) // 2)
    return _FakeStream([text[:mid], text[mid:]], [{"type": "text", "text": text}])


def _tool_turn(tool_id: str, name: str, args: dict) -> _FakeStream:
    """A tool-use turn: no visible text, one tool_use block."""
    return _FakeStream([], [{"type": "tool_use", "id": tool_id, "name": name, "input": args}])


# --------------------------------------------------------------------------- #
# Tool registry shape
# --------------------------------------------------------------------------- #


def test_tool_registry_has_the_four_phase1_tools():
    names = {t["name"] for t in TOOLS}
    assert names == {"set_filters", "query_data", "get_weights", "read_docs"}


def test_every_tool_declares_a_valid_input_schema():
    for tool in TOOLS:
        assert tool["name"]
        assert tool["description"]
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema


def test_filter_tools_expose_the_map_request_fields():
    by_name = {t["name"]: t for t in TOOLS}
    props = by_name["set_filters"]["input_schema"]["properties"]
    assert {"categories", "tier", "year", "months", "borough", "level", "metric", "severity_basis"} <= set(props)
    # query_data adds a ranking size and read_docs requires a topic.
    assert "top_n" in by_name["query_data"]["input_schema"]["properties"]
    assert by_name["read_docs"]["input_schema"]["required"] == ["topic"]


# --------------------------------------------------------------------------- #
# Filter normalisation
# --------------------------------------------------------------------------- #


def test_normalize_filters_keeps_only_provided_keys():
    out = normalize_filters({"metric": "composite", "level": "borough"})
    assert out == {"metric": "composite", "level": "borough"}


def test_normalize_filters_handles_year_sentinels():
    assert normalize_filters({"year": "All years"}) == {"year": None}
    assert normalize_filters({"year": 2024}) == {"year": 2024}
    assert normalize_filters({"year": None}) == {"year": None}


def test_normalize_filters_rejects_bad_enums_and_months():
    with pytest.raises(ValueError):
        normalize_filters({"metric": "bogus"})
    with pytest.raises(ValueError):
        normalize_filters({"level": "country"})
    with pytest.raises(ValueError):
        normalize_filters({"severity_basis": "mode"})
    with pytest.raises(ValueError):
        normalize_filters({"months": [13]})


# --------------------------------------------------------------------------- #
# Tool implementations (against the real snapshot)
# --------------------------------------------------------------------------- #


def test_set_filters_emits_a_partial_action():
    result, action, summary = tool_set_filters(
        {"categories": ["Robbery"], "borough": "Westminster", "year": 2024}
    )
    assert action == {
        "type": "set_filters",
        "payload": {"categories": ["Robbery"], "borough": "Westminster", "year": 2024},
    }
    assert result["applied"] == action["payload"]
    assert "Robbery" in summary


def test_query_data_ranks_boroughs_by_composite():
    result, action, summary = tool_query_data(
        {"metric": "composite", "level": "borough", "top_n": 5}
    )
    assert action is None  # query never changes the user's view
    assert result["level"] == "borough"
    assert result["metric"] == "composite"
    assert result["unit_count"] == 33

    top = result["top"]
    assert len(top) == 5
    # ranked descending and grounded (name + numeric value + crime count)
    values = [row["value"] for row in top]
    assert values == sorted(values, reverse=True)
    assert all(row["name"] for row in top)
    assert result["vmax"] >= 1.0
    assert "borough/composite" in summary


def test_query_data_defaults_to_unfiltered_view():
    result, _, _ = tool_query_data({"metric": "raw", "level": "borough"})
    assert result["filters_applied"] == DEFAULT_FILTERS | {"metric": "raw", "level": "borough"}


def test_get_weights_returns_the_full_anchored_table():
    result, action, summary = tool_get_weights({})
    assert action is None
    rows = result["categories"]
    assert len(rows) == 14
    assert all("preventability_anchor" in row for row in rows)


def test_read_docs_surfaces_literature_anchors_for_preventability():
    pytest.importorskip("rank_bm25")
    result, action, summary = dispatch_tool("read_docs", {"topic": "how is preventability calculated"})
    assert action is None
    chunks = result["chunks"]
    assert chunks, "expected at least one documentation chunk"
    blob = " ".join(chunk["text"] for chunk in chunks)
    # The literature anchors live in PREVENTABILITY_14 / the docs corpus.
    assert "Weisburd" in blob or "Braga" in blob


def test_dispatch_unknown_tool_returns_error_not_crash():
    result, action, summary = dispatch_tool("teleport", {})
    assert action is None
    assert "error" in result


def test_dispatch_tool_catches_tool_errors():
    # A bad enum inside set_filters should be reported, not raised.
    result, action, summary = dispatch_tool("set_filters", {"metric": "bogus"})
    assert action is None
    assert "error" in result


# --------------------------------------------------------------------------- #
# Personas
# --------------------------------------------------------------------------- #


def test_resolve_persona_maps_known_and_defaults_unknown():
    assert resolve_persona("examiner") == "examiner"
    assert resolve_persona("COMMUNITY") == "community"
    assert resolve_persona(None) == "police"
    assert resolve_persona("nonsense") == "police"


def test_system_blocks_swap_persona_but_keep_a_stable_cached_core():
    police = chat_core._system_blocks(None, "police")
    examiner = chat_core._system_blocks(None, "examiner")
    # First block is the shared core, marked for prompt caching, identical across
    # personas (so switching persona still hits the cache).
    assert police[0]["cache_control"] == {"type": "ephemeral"}
    assert police[0]["text"] == examiner[0]["text"]
    # Second block is the persona preamble — and it differs.
    assert police[1]["text"] == PERSONAS["police"]["preamble"]
    assert examiner[1]["text"] == PERSONAS["examiner"]["preamble"]
    assert police[1]["text"] != examiner[1]["text"]


# --------------------------------------------------------------------------- #
# End-to-end loop against a mocked streaming LLM
# --------------------------------------------------------------------------- #


def test_run_chat_query_flow_returns_grounded_text_and_audit():
    client = FakeClient(
        [
            _tool_turn("t1", "query_data", {"metric": "composite", "level": "borough", "top_n": 5}),
            _text_turn("The top five boroughs by composite demand are listed above."),
        ]
    )
    result = run_chat(
        [{"role": "user", "content": "Which five boroughs have the highest preventable harm?"}],
        client=client,
    )

    assert result["text"] == "The top five boroughs by composite demand are listed above."
    assert result["actions"] == []  # a query produces no dashboard action
    assert len(result["tool_calls"]) == 1
    call = result["tool_calls"][0]
    assert call["name"] == "query_data"
    assert "borough/composite" in call["result_summary"]

    # The loop ran twice: tool_use round, then the final text round, and the
    # second request carried a tool_result back to the model.
    assert len(client.messages.calls) == 2
    follow_up = client.messages.calls[1]["messages"][-1]
    assert follow_up["role"] == "user"
    assert follow_up["content"][0]["type"] == "tool_result"


def test_run_chat_set_filters_flow_produces_an_action():
    client = FakeClient(
        [
            _tool_turn("t2", "set_filters", {"categories": ["Robbery"], "borough": "Westminster", "year": 2024}),
            _text_turn("Done — the map now shows robbery in Westminster for 2024."),
        ]
    )
    result = run_chat(
        [{"role": "user", "content": "Show me robbery in Westminster in 2024"}],
        client=client,
    )

    assert result["actions"] == [
        {
            "type": "set_filters",
            "payload": {"categories": ["Robbery"], "borough": "Westminster", "year": 2024},
        }
    ]
    assert result["tool_calls"][0]["name"] == "set_filters"
    assert "robbery" in result["text"].lower()


def test_run_chat_caps_context_to_recent_messages():
    client = FakeClient([_text_turn("ok")])
    long_history = [{"role": "user", "content": f"msg {i}"} for i in range(40)]
    run_chat(long_history, client=client)
    sent = client.messages.calls[0]["messages"]
    assert len(sent) == chat_core.MAX_CONTEXT_MESSAGES


# --------------------------------------------------------------------------- #
# Streaming generator: event sequence
# --------------------------------------------------------------------------- #


def test_stream_query_flow_emits_text_then_tool_call_then_done():
    client = FakeClient(
        [
            _tool_turn("t1", "query_data", {"metric": "composite", "level": "borough", "top_n": 5}),
            _text_turn("Westminster leads."),
        ]
    )
    events = list(
        run_chat_stream([{"role": "user", "content": "top boroughs?"}], client=client)
    )
    kinds = [e["type"] for e in events]

    assert kinds[-1] == "done"  # terminal event
    assert "tool_call" in kinds
    assert "action" not in kinds  # query_data never yields an action
    # Reassembling the text deltas gives the final answer.
    text = "".join(e["text"] for e in events if e["type"] == "text")
    assert text == "Westminster leads."
    tool_call = next(e for e in events if e["type"] == "tool_call")
    assert tool_call["name"] == "query_data"


def test_stream_set_filters_flow_emits_action_before_done():
    client = FakeClient(
        [
            _tool_turn("t2", "set_filters", {"categories": ["Robbery"], "borough": "Westminster"}),
            _text_turn("Showing robbery in Westminster."),
        ]
    )
    events = list(
        run_chat_stream([{"role": "user", "content": "show robbery in westminster"}], client=client)
    )
    kinds = [e["type"] for e in events]

    assert kinds[-1] == "done"
    assert kinds.index("action") < kinds.index("done")  # action arrives before done
    action = next(e for e in events if e["type"] == "action")
    assert action["action"] == {
        "type": "set_filters",
        "payload": {"categories": ["Robbery"], "borough": "Westminster"},
    }


def test_stream_passes_persona_into_the_system_prompt():
    client = FakeClient([_text_turn("hi")])
    list(run_chat_stream([{"role": "user", "content": "hello"}], client=client, persona="examiner"))
    system = client.messages.calls[0]["system"]
    assert system[1]["text"] == PERSONAS["examiner"]["preamble"]


# --------------------------------------------------------------------------- #
# HTTP layer (SSE route + persona + graceful degradation)
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def http_client():
    pytest.importorskip("slowapi")
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as client:
        yield client


def _parse_sse(body: str) -> list[dict]:
    import json

    events = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:") :].strip()))
    return events


def test_health_reports_unconfigured_without_a_key(http_client, monkeypatch):
    monkeypatch.setattr(chat_core, "chat_available", lambda: False)
    body = http_client.get("/api/chat/health").json()
    assert body == {"configured": False}


def test_chat_returns_503_when_not_configured(http_client, monkeypatch):
    monkeypatch.setattr(chat_core, "chat_available", lambda: False)
    res = http_client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert res.status_code == 503
    assert res.json() == {"error": "AI chat is not configured"}


def test_chat_streams_sse_events_over_http_with_mocked_client(http_client, monkeypatch):
    monkeypatch.setattr(chat_core, "chat_available", lambda: True)
    monkeypatch.setattr(
        chat_core,
        "build_client",
        lambda: FakeClient(
            [
                _tool_turn("t1", "get_weights", {}),
                _text_turn("Preventability is a literature-anchored multiplier."),
            ]
        ),
    )

    res = http_client.post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": "How is preventability calculated?"}],
            "persona": "examiner",
        },
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(res.text)
    kinds = [e["type"] for e in events]
    assert kinds[-1] == "done"
    text = "".join(e["text"] for e in events if e["type"] == "text")
    assert text == "Preventability is a literature-anchored multiplier."
    tool_call = next(e for e in events if e["type"] == "tool_call")
    assert tool_call["name"] == "get_weights"
    assert "action" not in kinds
