from __future__ import annotations

from pathlib import Path

import pytest

from pyapiclient.api import api_make
from pyapiclient.exceptions import PyAPIClientSpecError


def test_api_make_openapi_json_after_sniff_pyapiclient_error(
    swagger2_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def flaky_read(source: str | Path, *, timeout: float) -> str:
        calls.append(1)
        if len(calls) == 1:
            raise PyAPIClientSpecError("sniff path unavailable")
        from pyapiclient.loader import read_source_text as real_read

        return real_read(source, timeout=timeout)

    monkeypatch.setattr("pyapiclient.api.read_source_text", flaky_read)
    api = api_make(swagger2_path, http_client=None)
    assert api.spec_family == "swagger2"
    api.close()


def test_graphql_create_payload_not_object(library_graphql_path: Path) -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"createAuthor": "not-an-object"}})

    transport = httpx.MockTransport(handler)
    hc = httpx.Client(transport=transport, base_url="https://gql.test")
    api = api_make(library_graphql_path, base_url="https://gql.test", http_client=hc)
    with pytest.raises(Exception, match="object"):
        api.models.Author.objects.create(name="A", email="b@c.d")
    api.close()


def test_graphql_get_payload_not_object(library_graphql_path: Path) -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"author": []}})

    transport = httpx.MockTransport(handler)
    hc = httpx.Client(transport=transport, base_url="https://gql.test")
    api = api_make(library_graphql_path, base_url="https://gql.test", http_client=hc)
    with pytest.raises(Exception, match="object"):
        api.models.Author.objects.get(pk="1")
    api.close()
