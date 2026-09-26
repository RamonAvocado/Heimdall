"""Copy-paste starting point for a new provider - not a real provider.

Rename the class, change ``id``, and replace the body of ``_fetch`` with a
real upstream call (see ``heimdall.providers.fred`` for one that does HTTP).
This one stays in-memory so it needs no mocking to test.
"""

from __future__ import annotations

import polars as pl

from heimdall._contracts import FetchRequest, FetchResult
from heimdall._provider import Capabilities, Provider
from heimdall._time import utcnow
from heimdall.schemas import OBSERVATIONS  # reuse a shared SchemaSpec when the shape fits


class TemplateProvider(Provider):
    id = "template"
    capabilities = Capabilities(data_kinds=(OBSERVATIONS.name,))

    def _fetch(self, request: FetchRequest) -> FetchResult:
        # Replace this with: call the upstream, parse the response, build a
        # frame matching the columns of the SchemaSpec above.
        frame = pl.DataFrame(
            {
                "timestamp": [utcnow()],
                "series_id": [request.resource],
                "value": [0.0],
            }
        )

        OBSERVATIONS.validate(frame)
        return FetchResult(
            frame=frame,
            schema=OBSERVATIONS,
            provider_id=self.id,
            request=request,
            retrieved_at=utcnow(),
        )
