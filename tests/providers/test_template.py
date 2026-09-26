from __future__ import annotations

from heimdall._contracts import FetchRequest
from heimdall.providers._template import TemplateProvider
from heimdall.testing import ProviderContractTests


class TestTemplateContract(ProviderContractTests):
    def make_provider(self) -> TemplateProvider:
        return TemplateProvider()

    def sample_request(self) -> FetchRequest:
        return FetchRequest(resource="example")
