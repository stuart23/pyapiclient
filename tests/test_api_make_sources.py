"""Coverage for ``api_make(source)``: ``Path``, filesystem path as ``str``, and ``https`` spec URL."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from dynamicapiclient import api_make

# Public copy of the library fixture (same as in README).
LIBRARY_OAS3_GITHUB_RAW = (
    "https://raw.githubusercontent.com/stuart23/dynamicapiclient/"
    "refs/heads/main/tests/fixtures/library_oas3.yaml"
)


def test_api_make_accepts_path_object(library_oas3_path: Path) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
    hc = httpx.Client(transport=transport, base_url="https://api.example.com/v1")
    api = api_make(library_oas3_path, http_client=hc)
    assert api.spec_family == "openapi3"
    assert "Author" in dir(api.models)
    api.close()


def test_api_make_accepts_str_filesystem_path(library_oas3_path: Path) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
    hc = httpx.Client(transport=transport, base_url="https://api.example.com/v1")
    api = api_make(str(library_oas3_path), http_client=hc)
    assert api.spec_family == "openapi3"
    assert "Author" in dir(api.models)
    api.close()


@pytest.mark.network
def test_api_make_accepts_https_url_github_raw_fixture() -> None:
    """Fetches the real fixture YAML from GitHub (outbound HTTPS)."""
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
    hc = httpx.Client(transport=transport, base_url="https://api.example.com/v1")
    api = api_make(LIBRARY_OAS3_GITHUB_RAW, http_client=hc)
    assert api.spec_family == "openapi3"
    assert "Author" in dir(api.models) and "Book" in dir(api.models)
    api.close()
