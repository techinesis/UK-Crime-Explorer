"""FastAPI chat router: POST /api/chat and GET /api/chat/health.

Phase 1 returns plain JSON (no streaming). Shape:

    {
      "text": str,                         # the assistant's reply
      "actions": [{"type": "set_filters",  # applied client-side after render
                   "payload": {...}}],
      "tool_calls": [{"name", "args",      # surfaced as audit badges in the UI
                      "result_summary"}]
    }

Graceful degradation: if ANTHROPIC_API_KEY is unset (or the chat deps are not
installed), POST /api/chat returns 503 ``{"error": "AI chat is not configured"}``
and GET /api/chat/health reports ``{"configured": false}`` so the frontend hides
the panel entirely. The rest of the dashboard is unaffected.

Rate limiting (20/min/IP) uses slowapi. slowapi lives only in the *full* backend
requirements, not the lean Vercel function, so its import is guarded: without it
the health route still answers (configured: false) and POST returns 503, rather
than breaking app import.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
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


# The 200 response shape (documented here, serialised straight from run_chat):
#   {"text": str,
#    "actions": [{"type": "set_filters", "payload": <partial MapRequest>}],
#    "tool_calls": [{"name": str, "args": object, "result_summary": str}]}
# Error paths return {"error": str} with a 4xx/5xx status, so the route emits
# JSONResponse directly rather than via a response_model.


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("/api/chat/health")
def chat_health() -> dict[str, bool]:
    """Whether the chat panel should be shown. The frontend polls this on mount."""
    return {"configured": chat_core.chat_available() and _SLOWAPI_AVAILABLE}


def _run_chat_request(body: ChatRequest) -> JSONResponse:
    """Shared handler body (wrapped by the rate-limited route)."""
    if not (chat_core.chat_available() and _SLOWAPI_AVAILABLE):
        return JSONResponse(status_code=503, content=_NOT_CONFIGURED)

    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    if not messages:
        return JSONResponse(status_code=400, content={"error": "messages must not be empty"})

    current_filters = body.filters.model_dump() if body.filters is not None else None

    try:
        client = chat_core.build_client()
        result = chat_core.run_chat(messages, client=client, current_filters=current_filters)
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to the client
        return JSONResponse(
            status_code=502,
            content={"error": f"The AI assistant could not complete the request: {exc}"},
        )

    return JSONResponse(status_code=200, content=result)


if _SLOWAPI_AVAILABLE:

    @router.post("/api/chat")
    @_limiter.limit(RATE_LIMIT)
    async def chat_endpoint(request: Request, body: ChatRequest) -> JSONResponse:  # noqa: ARG001
        # `request` is required by slowapi to identify the client IP.
        return _run_chat_request(body)

else:  # pragma: no cover - lean function path (no slowapi)

    @router.post("/api/chat")
    async def chat_endpoint(body: ChatRequest) -> JSONResponse:
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
