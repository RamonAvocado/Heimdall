from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from heimdall._contracts import FetchRequest
from heimdall.errors import RequestError


def test_instance_fetch_takes_a_request_with_params(dummy_provider) -> None:
    request = FetchRequest("X", params={"limit": 3})

    assert dummy_provider.fetch(request).request.params == {"limit": 3}
    assert asyncio.run(dummy_provider.afetch(request)).request.params == {"limit": 3}

    day = datetime(2024, 1, 1)
    with pytest.raises(RequestError):  # validated like the string form
        dummy_provider.fetch(FetchRequest("X", start=day, end=day))
    with pytest.raises(TypeError):
        dummy_provider.fetch(request, interval="1d")
