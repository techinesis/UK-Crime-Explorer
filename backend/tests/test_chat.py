"""Tests for the AI chat layer.

Two groups:

1. **Tool-call shapes** — the tool registry, filter normalisation, and each tool
   implementation (run against the real snapshotted data, like test_api).
2. **End-to-end** — :func:`core.chat.run_chat` driven by a *mocked* Anthropic
   client (canned tool_use → text), exercising the tool-use loop, the action
   protocol, and the audit trail without any network call. Plus a thin HTTP-layer
   check of the route + graceful 503.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import chat as chat_core
from core.chat import (
    DEFAULT_FILTERS,
    TOOLS,
    dispatch_tool,
    normalize_filters,
    run_chat,
    tool_get_weights,
    tool_query_data,
    tool_set_filters,
)


# --------------------------------------------------------------------------- #
# A minimal fake Anthropic client
# --------------------------------------------------------------------------- #


class _FakeMessages:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    """Returns canned responses in order. Content blocks are plain dicts, which
    core.chat reads via its dict/attr-agnostic accessor."""

    def __init__(self, responses: list) -> None:
        self.messages = _FakeMessages(responses)


def _text(text: str):
    return SimpleNamespace(content=[{"type": "text", "text": text}])


def _tool_use(tool_id: str, name: str, args: dict):
    return SimpleNamespace(content=[{"type": "tool_use", "id": tool_id, "name": name, "input": args}])


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
# End-to-end loop against a mocked LLM
# --------------------------------------------------------------------------- #


def test_run_chat_query_flow_returns_grounded_text_and_audit():
    client = FakeClient(
        [
            _tool_use("t1", "query_data", {"metric": "composite", "level": "borough", "top_n": 5}),
            _text("The top five boroughs by composite demand are listed above."),
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
            _tool_use("t2", "set_filters", {"categories": ["Robbery"], "borough": "Westminster", "year": 2024}),
            _text("Done — the map now shows robbery in Westminster for 2024."),
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
    client = FakeClient([_text("ok")])
    long_history = [{"role": "user", "content": f"msg {i}"} for i in range(40)]
    run_chat(long_history, client=client)
    sent = client.messages.calls[0]["messages"]
    assert len(sent) == chat_core.MAX_CONTEXT_MESSAGES


# --------------------------------------------------------------------------- #
# HTTP layer (route wiring + graceful degradation)
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def http_client():
    pytest.importorskip("slowapi")
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as client:
        yield client


def test_health_reports_unconfigured_without_a_key(http_client, monkeypatch):
    monkeypatch.setattr(chat_core, "chat_available", lambda: False)
    body = http_client.get("/api/chat/health").json()
    assert body == {"configured": False}


def test_chat_returns_503_when_not_configured(http_client, monkeypatch):
    monkeypatch.setattr(chat_core, "chat_available", lambda: False)
    res = http_client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert res.status_code == 503
    assert res.json() == {"error": "AI chat is not configured"}


def test_chat_end_to_end_over_http_with_mocked_client(http_client, monkeypatch):
    monkeypatch.setattr(chat_core, "chat_available", lambda: True)
    monkeypatch.setattr(
        chat_core,
        "build_client",
        lambda: FakeClient(
            [
                _tool_use("t1", "get_weights", {}),
                _text("Preventability is a literature-anchored multiplier."),
            ]
        ),
    )

    res = http_client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "How is preventability calculated?"}]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["text"] == "Preventability is a literature-anchored multiplier."
    assert body["tool_calls"][0]["name"] == "get_weights"
    assert body["actions"] == []
