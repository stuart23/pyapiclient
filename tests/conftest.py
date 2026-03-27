from __future__ import annotations

import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def library_oas3_path() -> pathlib.Path:
    return FIXTURES / "library_oas3.yaml"


@pytest.fixture
def swagger2_path() -> pathlib.Path:
    return FIXTURES / "swagger2_library.json"


@pytest.fixture
def library_graphql_path() -> pathlib.Path:
    return FIXTURES / "library.graphql"
