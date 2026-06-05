"""FastAPI chat router: POST /api/chat (SSE) and GET /api/chat/health.

POST /api/chat streams Server-Sent Events (``text/event-stream``). Each line is
``data: {json}\\n\\n`` where the JSON is one of:

    {"type": "text", "text": "<delta>"}                         # reply chunk
    {"type": "tool_call", "name", "args", "result_summary"}     # audit badge
    {"type": "action", "action": {"type": "set_filters",        # apply after text
                                  "payload": {...}}}
    {"type": "done"}                                            # terminal
    {"type": "error", "error": "..."}                           # mid-stream failure

Pre-flight failures (before the stream starts) return plain JSON with a non-200
status instead: 503 ``{"error": "AI chat is not configured"}`` when unconfigured,
400 for empty input, 502 if the Anthropic client cannot be constructed.

Graceful degradation: if ANTHROPIC_API_KEY is unset (or the chat deps are not
installed), POST returns 503 and GET /api/chat/health reports
``{"configured": false}`` so the frontend hides the panel entirely. The rest of
the dashboard is unaffected.

Rate limiting (20/min/IP) uses slowapi. slowapi lives only in the *full* backend
requirements, not the lean Vercel function, so its import is guarded: without it
the health route still answers (configured: false) and POST returns 503, rather
than breaking app import.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from api.schemas import MapRequest
from core import chat as chat_core

# slowapi is optional at import time (absent from the lean prod function).
try:
    from slowapi import Limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    _SLOWAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only where slowapi is absent
    _SLOWAPI_AVAILABLE = False

RATE_LIMIT = "20/minute"
_NOT_CONFIGURED = {"error": "AI chat is not configured"}

router = APIRouter()
_limiter = Limiter(key_func=get_remote_address) if _SLOWAPI_AVAILABLE else None


# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    # The dashboard's current filter state, sent as context so the assistant can
    # reason about "the current view". Optional.
    filters: MapRequest | None = None
    # Stakeholder persona: "police" | "examiner" | "community". Unknown -> police.
    persona: str = "police"


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("/api/chat/health")
def chat_health() -> dict[str, bool]:
    """Whether the chat panel should be shown. The frontend polls this on mount."""
    return {"configured": chat_core.chat_available() and _SLOWAPI_AVAILABLE}


def _sse(event: dict[str, Any]) -> str:
    """Encode one event as an SSE ``data:`` frame."""
    return f"data: {json.dumps(event)}\n\n"


def _run_chat_request(body: ChatRequest) -> Response:
    """Shared handler body (wrapped by the rate-limited route).

    Returns a plain ``JSONResponse`` for pre-flight failures (so the client gets a
    real status code), otherwise a ``StreamingResponse`` of SSE events.
    """
    if not (chat_core.chat_available() and _SLOWAPI_AVAILABLE):
        return JSONResponse(status_code=503, content=_NOT_CONFIGURED)

    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    if not messages:
        return JSONResponse(status_code=400, content={"error": "messages must not be empty"})

    current_filters = body.filters.model_dump() if body.filters is not None else None
    persona = chat_core.resolve_persona(body.persona)

    # Construct the client up front so a config/connection failure is a clean 502
    # (not a half-open stream the client can't distinguish from success).
    try:
        client = chat_core.build_client()
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to the client
        return JSONResponse(
            status_code=502,
            content={"error": f"The AI assistant could not be reached: {exc}"},
        )

    def event_stream() -> Iterator[str]:
        try:
            for event in chat_core.run_chat_stream(
                messages, client=client, persona=persona, current_filters=current_filters
            ):
                yield _sse(event)
        except Exception as exc:  # noqa: BLE001 - status is already 200; report in-band
            yield _sse(
                {"type": "error", "error": f"The AI assistant could not complete the request: {exc}"}
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if _SLOWAPI_AVAILABLE:

    @router.post("/api/chat")
    @_limiter.limit(RATE_LIMIT)
    async def chat_endpoint(request: Request, body: ChatRequest) -> Response:  # noqa: ARG001
        # `request` is required by slowapi to identify the client IP.
        return _run_chat_request(body)

else:  # pragma: no cover - lean function path (no slowapi)

    @router.post("/api/chat")
    async def chat_endpoint(body: ChatRequest) -> Response:
        return JSONResponse(status_code=503, content=_NOT_CONFIGURED)


# --------------------------------------------------------------------------- #
# App registration
# --------------------------------------------------------------------------- #


def _rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": "Too many messages. Please wait a moment and try again."},
    )


def register_chat(app: Any) -> None:
    """Mount the chat router on an existing FastAPI app and wire rate limiting.

    Called from api.main so the chat shares the app's CORS config. Safe to call
    even when slowapi is unavailable (the router still mounts; POST returns 503).
    """
    if _SLOWAPI_AVAILABLE:
        app.state.limiter = _limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.include_router(router)
