"""A deliberately small retry helper.

Cross-cutting concerns (retry, rate limiting, caching) are host-side wrappers
in Heimdall, not something every provider reimplements inside ``fetch``. This
module is the documented starting point and the seam a fuller middleware stack
would grow from; it is not applied automatically anywhere.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import TypeVar

from heimdall._logging import get_logger
from heimdall.errors import UpstreamError

_R = TypeVar("_R")
_log = get_logger("retry")


def retry(
    attempts: int = 3,
    *,
    base_delay: float = 0.5,
    backoff: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (UpstreamError,),
) -> Callable[[Callable[..., _R]], Callable[..., _R]]:
    """Retry a callable on transient failure with exponential backoff.

    Wrap a provider call from the host side::

        result = retry(attempts=4)(provider.fetch)(request)
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    def decorator(func: Callable[..., _R]) -> Callable[..., _R]:
        @functools.wraps(func)
        def wrapper(*args: object, **kwargs: object) -> _R:
            delay = base_delay
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == attempts:
                        raise
                    _log.warning(
                        "retrying after transient failure",
                        attempt=attempt,
                        attempts=attempts,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    time.sleep(delay)
                    delay *= backoff
            raise AssertionError("unreachable")

        return wrapper

    return decorator
