from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
import yaml

from pyapiclient.exceptions import PyAPIClientConfigurationError, PyAPIClientHTTPError, PyAPIClientSpecError
from pyapiclient.loader import _guess_format_from_path, _looks_like_url, _parse_text, load_spec


def test_looks_like_url() -> None:
    assert _looks_like_url("https://example.com/x")
    assert not _looks_like_url("/tmp/foo.yaml")
    assert not _looks_like_url("notaurl")


def test_guess_format_from_path(tmp_path: Path) -> None:
    assert _guess_format_from_path(tmp_path / "a.yaml") == "yaml"
    assert _guess_format_from_path(tmp_path / "a.yml") == "yaml"
    assert _guess_format_from_path(tmp_path / "a.json") == "json"
    assert _guess_format_from_path(tmp_path / "a.txt") == "yaml"


def test_parse_text_json_invalid() -> None:
    with pytest.raises(PyAPIClientSpecError, match="Invalid JSON"):
        _parse_text("{", "json")


def test_parse_text_yaml_invalid() -> None:
    with pytest.raises(PyAPIClientSpecError, match="Invalid YAML"):
        _parse_text(":\n:", "yaml")


def test_parse_text_empty() -> None:
    with pytest.raises(PyAPIClientSpecError, match="empty"):
        _parse_text("   ", "json")


def test_parse_text_not_object() -> None:
    with pytest.raises(PyAPIClientSpecError, match="object"):
        _parse_text("[1]", "json")


def test_load_spec_file_missing(tmp_path: Path) -> None:
    p = tmp_path / "nope.yaml"
    with pytest.raises(PyAPIClientSpecError, match="does not exist"):
        load_spec(p)


def test_load_spec_path_object(library_oas3_path: Path) -> None:
    data = load_spec(library_oas3_path)
    assert data["openapi"] == "3.0.3"


def test_load_spec_path_str(library_oas3_path: Path) -> None:
    data = load_spec(str(library_oas3_path))
    assert "paths" in data


def test_load_spec_bad_type() -> None:
    with pytest.raises(PyAPIClientConfigurationError):
        load_spec(123)  # type: ignore[arg-type]


def test_load_spec_empty_string() -> None:
    with pytest.raises(PyAPIClientConfigurationError):
        load_spec("   ")


def test_load_spec_neither_url_nor_file() -> None:
    with pytest.raises(PyAPIClientSpecError, match="not a valid URL"):
        load_spec("definitely-not-a-file-xyz-123.yaml")


@respx.mock
def test_load_spec_url_success() -> None:
    payload = {"openapi": "3.0.0", "info": {"title": "T", "version": "1"}, "paths": {}}
    respx.get("https://spec.test/openapi.yaml").mock(
        return_value=httpx.Response(200, text=json.dumps(payload))
    )
    data = load_spec("https://spec.test/openapi.yaml")
    assert data["openapi"] == "3.0.0"


@respx.mock
def test_load_spec_url_http_error() -> None:
    respx.get("https://spec.test/missing").mock(return_value=httpx.Response(404, text="no"))
    with pytest.raises(PyAPIClientHTTPError, match="404"):
        load_spec("https://spec.test/missing")


@respx.mock
def test_load_spec_url_network() -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=httpx.Request("GET", "https://x"))

    respx.get("https://spec.test/boom").mock(side_effect=boom)
    with pytest.raises(PyAPIClientSpecError, match="Network"):
        load_spec("https://spec.test/boom")


@respx.mock
def test_load_spec_url_yaml_content_type() -> None:
    doc = {"openapi": "3.0.1", "info": {"title": "T", "version": "1"}, "paths": {}}
    respx.get("https://spec.test/y").mock(
        return_value=httpx.Response(
            200,
            content=yaml.safe_dump(doc),
            headers={"content-type": "application/octet-stream"},
        )
    )
    data = load_spec("https://spec.test/y")
    assert data["openapi"] == "3.0.1"


@respx.mock
def test_load_spec_url_empty_body() -> None:
    respx.get("https://spec.test/e").mock(return_value=httpx.Response(200, text=""))
    with pytest.raises(PyAPIClientSpecError, match="empty"):
        load_spec("https://spec.test/e")
