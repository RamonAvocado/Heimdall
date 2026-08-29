"""Exception hierarchy for Heimdall.

Providers should raise these, never bare ``ValueError`` / ``KeyError``. The
conformance kit (:mod:`heimdall.testing`) checks for this.
"""

from __future__ import annotations


class HeimdallError(Exception):
    """Base class for every error raised by Heimdall."""


class ProviderError(HeimdallError):
    """A problem with a provider itself (not the request or the upstream)."""


class ProviderNotFound(ProviderError):
    """Asked the registry for a provider id that is not registered."""


class ConfigError(ProviderError):
    """A provider was constructed without required configuration."""


class RequestError(HeimdallError):
    """The :class:`~heimdall.contracts.FetchRequest` is invalid for this provider."""


class SchemaError(HeimdallError):
    """A frame does not match the :class:`~heimdall.contracts.SchemaSpec` it claims."""


class UpstreamError(HeimdallError):
    """The upstream service or client library failed (network, HTTP, parsing)."""
