"""Vercel Python serverless entrypoint.

Exposes the FastAPI app for the @vercel/python runtime. All ``/api/*`` requests
are rewritten to this function (see ../vercel.json). The backend lives under
``backend/``, so we put it on sys.path and import its app.
"""

import os
import sys

_BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# The backend's web package is named ``api`` — the same name as this Vercel
# functions directory. If the runtime pre-bound this directory as a namespace
# package (no __init__.py), drop it so ``import api.*`` resolves to backend/api
# (a real package now first on sys.path).
_existing = sys.modules.get("api")
if _existing is not None and getattr(_existing, "__file__", None) is None:
    del sys.modules["api"]

from api.main import app  # noqa: E402

__all__ = ["app"]
