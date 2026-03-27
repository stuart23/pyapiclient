from __future__ import annotations

import httpx
import pytest

from pyapiclient.client import HTTPClient
from pyapiclient.exceptions import PyAPIClientHTTPError


def test_post_graphql_prepends_slash_to_path() -> None:
    seen: list[str] = []

    def h(r: httpx.Request) -> httpx.Response:
        seen.append(r.url.path)
        return httpx.Response(200, json={"data": {}})

    from pyapiclient.client import HTTPClient

    transport = httpx.MockTransport(h)
    with HTTPClient("https://a", client=httpx.Client(transport=transport)) as c:
        c.post_graphql("relative/graphql", "query { x }")
    assert seen[0].endswith("/relative/graphql")


def test_http_client_context_manager() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    with HTTPClient("https://a", client=httpx.Client(transport=transport)) as c:
        c.request_json("GET", "/z")


def test_client_path_adds_leading_slash() -> None:
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={}) if r.url.path.endswith("/z") else httpx.Response(500)
    )
    with HTTPClient("https://a", client=httpx.Client(transport=transport)) as c:
        c.request_json("GET", "z")


def test_client_own_base_url_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/items"
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HTTPClient("https://api.test", client=httpx.Client(transport=transport)) as c:
        data = c.request_json("GET", "/items")
    assert data == {"ok": True}


def test_client_injected_full_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://api.test/v1/x")
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    plain = httpx.Client(transport=transport)
    with HTTPClient("https://api.test/v1", client=plain) as c:
        c.request_json("GET", "/x")


def test_client_http_error() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500, text="err"))
    with HTTPClient("https://a", client=httpx.Client(transport=transport)) as c:
        with pytest.raises(PyAPIClientHTTPError, match="HTTP 500"):
            c.request_json("GET", "/z")


def test_client_bad_json() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text="not-json{"))
    with HTTPClient("https://a", client=httpx.Client(transport=transport)) as c:
        with pytest.raises(PyAPIClientHTTPError, match="valid JSON"):
            c.request_json("GET", "/z")


def test_client_204_empty() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(204))
    with HTTPClient("https://a", client=httpx.Client(transport=transport)) as c:
        assert c.request_json("DELETE", "/z") is None


def test_client_request_error() -> None:
    def boom(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=r)

    transport = httpx.MockTransport(boom)
    with HTTPClient("https://a", client=httpx.Client(transport=transport)) as c:
        with pytest.raises(PyAPIClientHTTPError, match="Request failed"):
            c.request_json("GET", "/z")
