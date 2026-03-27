from __future__ import annotations

from pathlib import Path

import pytest

from pyapiclient.exceptions import PyAPIClientConfigurationError, PyAPIClientSpecError
from pyapiclient.loader import parse_openapi_document, read_source_text


def test_parse_openapi_document_json_minimal() -> None:
    d = parse_openapi_document('{"swagger": "2.0", "info": {"title": "t", "version": "1"}}')
    assert d["swagger"] == "2.0"


def test_parse_openapi_document_empty() -> None:
    with pytest.raises(PyAPIClientSpecError, match="empty"):
        parse_openapi_document("   ")


def test_read_source_text_str_local_file(library_oas3_path: Path) -> None:
    text = read_source_text(str(library_oas3_path), timeout=30.0)
    assert "openapi:" in text


def test_read_source_text_bad_type() -> None:
    with pytest.raises(PyAPIClientConfigurationError):
        read_source_text(123, timeout=1)  # type: ignore[arg-type]


def test_read_source_text_missing_str_path() -> None:
    with pytest.raises(PyAPIClientSpecError, match="Could not read"):
        read_source_text("no-such-file-xyz-12345.json", timeout=1)
