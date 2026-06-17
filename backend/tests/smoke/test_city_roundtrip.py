"""Smoke test (Phase 2): the set_filters tool round-trips the `city` parameter.

Multi-city support is committed for London, Birmingham, Manchester, and
Liverpool. This guards that the chat layer's filter normalisation accepts each
known city and rejects an unknown one — rather than silently dropping or mangling
the value, which would point the dashboard at the wrong dataset.

Pure normalisation (no borough, so no data load): fast and offline.
"""

from __future__ import annotations

import pytest

from core.chat import dispatch_tool
from core.data import KNOWN_CITIES


@pytest.mark.smoke
def test_set_filters_city_roundtrip():
    for city in KNOWN_CITIES:
        result, action, summary = dispatch_tool("set_filters", {"city": city})
        assert "error" not in result, f"{city}: {result.get('error')}"
        assert action is not None, f"{city}: no action emitted"
        assert action["type"] == "set_filters"
        assert action["payload"]["city"] == city, f"{city}: city did not round-trip"
        assert result["applied"]["city"] == city

    # An unknown city is rejected (tool error, no action), not silently accepted.
    result, action, summary = dispatch_tool("set_filters", {"city": "atlantis"})
    assert action is None
    assert "error" in result, "unknown city was not rejected"
