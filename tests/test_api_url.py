from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from pyapiclient.api import api_make


@respx.mock
def test_api_make_openapi_from_http_url(swagger2_path: Path) -> None:
    body = swagger2_path.read_text(encoding="utf-8")
    respx.get("https://spec.example/swagger.json").mock(
        return_value=httpx.Response(200, text=body)
    )
    api = api_make("https://spec.example/swagger.json")
    assert api.spec_family == "swagger2"
    assert "Widget" in dir(api.models)
    api.close()
