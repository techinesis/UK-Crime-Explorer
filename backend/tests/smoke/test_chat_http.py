"""Smoke test 5: the chat HTTP layer — health, SSE streaming, and rate limiting.

GET /api/chat/health reports configuration (always 200). POST /api/chat returns
503 when unconfigured, otherwise streams Server-Sent Events; under the mock_llm
stub it emits a deterministic reply plus a tool_call and an action event. The rate
limiter caps the route at 20 requests/minute/IP, so the 21st returns 429.

No real Anthropic call is ever made: mock_llm stubs the client, and the
unconfigured cases short-circuit before any client is built.
"""

from __future__ import annotations

import json

import pytest

from api import chat as api_chat
from core import chat as chat_core

_ONE_MESSAGE = {"messages": [{"role": "user", "content": "Show me Camden"}]}


def _parse_sse(body: str) -> list[dict]:
    """Decode an SSE body into the list of JSON event payloads."""
    events = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:") :].strip()))
    return events


@pytest.mark.smoke
def test_chat_http(client, mock_llm, monkeypatch):
    # --- health: always 200; `configured` mirrors availability -----------------
    monkeypatch.setattr(chat_core, "chat_available", lambda: True)
    res = client.get("/api/chat/health")
    assert res.status_code == 200
    assert res.json() == {"configured": True}

    monkeypatch.setattr(chat_core, "chat_available", lambda: False)
    res = client.get("/api/chat/health")
    assert res.status_code == 200
    assert res.json() == {"configured": False}

    # --- POST /api/chat returns 503 when unconfigured (no stream started) -------
    res = client.post("/api/chat", json=_ONE_MESSAGE)
    assert res.status_code == 503
    assert res.json() == {"error": "AI chat is not configured"}

    # --- POST /api/chat streams SSE under the mocked client --------------------
    with mock_llm():
        res = client.post("/api/chat", json={**_ONE_MESSAGE, "persona": "police"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(res.text)
    kinds = [e["type"] for e in events]
    assert kinds, "no SSE events parsed"
    assert kinds[-1] == "done", f"stream did not terminate with 'done': {kinds}"
    reply = "".join(e["text"] for e in events if e["type"] == "text")
    assert reply == "Filtered the map to Camden.", f"unexpected reply: {reply!r}"
    assert any(e["type"] == "tool_call" for e in events), "no tool_call event in stream"
    assert any(e["type"] == "action" for e in events), "no action event in stream"

    # --- multi-turn payload reaches the mocked LLM with every turn intact ------
    with mock_llm() as fake:
        res = client.post(
            "/api/chat",
            json={
                "messages": [
                    {"role": "user", "content": "Show me Camden"},
                    {"role": "assistant", "content": "Here is Camden."},
                    {"role": "user", "content": "Now Westminster"},
                ],
                "persona": "police",
            },
        )
    assert res.status_code == 200
    sent = fake.messages.calls[0]["messages"]
    assert [m["content"] for m in sent] == [
        "Show me Camden",
        "Here is Camden.",
        "Now Westminster",
    ], f"history not forwarded intact: {sent}"

    # --- rate limit: the 21st request inside the window returns 429 ------------
    assert api_chat._limiter is not None, "rate limiter not configured"
    api_chat._limiter.reset()  # isolate the burst from the requests above
    monkeypatch.setattr(chat_core, "chat_available", lambda: False)  # fast 503, no client
    statuses = [client.post("/api/chat", json=_ONE_MESSAGE).status_code for _ in range(21)]
    assert statuses[-1] == 429, f"21st request not rate-limited: {statuses}"
    assert 429 not in statuses[:20], f"rate limit tripped before the 21st: {statuses}"
    api_chat._limiter.reset()  # leave the in-memory store clean for any later run
