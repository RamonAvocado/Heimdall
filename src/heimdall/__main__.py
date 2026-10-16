"""`python -m heimdall`: print `heimdall.catalog()` as JSON."""

import json

from heimdall import catalog

print(json.dumps(catalog(), indent=2))
