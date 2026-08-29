"""Time helpers shared across the package."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Timezone-aware current time in UTC (used for ``FetchResult.retrieved_at``)."""
    return datetime.now(UTC)
