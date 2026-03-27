from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pyapiclient.api import api_make
from pyapiclient.exceptions import PyAPIClientSpecError


def test_api_make_wraps_unexpected_get_base_url_error(library_oas3_path: Path) -> None:
    with patch("pyapiclient.api.get_base_url", side_effect=RuntimeError("boom")):
        with pytest.raises(PyAPIClientSpecError, match="boom"):
            api_make(library_oas3_path)


def test_api_make_wraps_recursion_resolving_schema(tmp_path: Path) -> None:
    p = tmp_path / "s.yaml"
    p.write_text(
        """
openapi: 3.0.3
info: {title: x, version: '1'}
servers: [{url: 'https://x'}]
paths: {}
components:
  schemas:
    R:
      type: object
""",
        encoding="utf-8",
    )
    with patch("pyapiclient.api.resolved_schema", side_effect=RecursionError("deep")):
        with pytest.raises(PyAPIClientSpecError, match="could not be resolved"):
            api_make(p)
