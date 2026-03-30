"""Targeted tests to keep package coverage ≥90% (branch-aware)."""

from __future__ import annotations

import json
import pathlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dynamicapiclient.exceptions import (
    DynamicAPIClientConfigurationError,
    DynamicAPIClientModelError,
    DynamicAPIClientSpecError,
)
from dynamicapiclient.graphql_support import (
    build_graphql_model_classes,
    graphql_execute_data,
    parse_graphql_schema,
)
from dynamicapiclient.loader import load_spec, read_source_text


def test_require_graphql_when_core_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import dynamicapiclient.graphql_support as gs

    monkeypatch.setattr(gs, "build_schema", None)
    with pytest.raises(DynamicAPIClientConfigurationError, match="graphql-core"):
        gs.require_graphql()


def test_parse_graphql_introspection_missing_inner_schema() -> None:
    with pytest.raises(DynamicAPIClientSpecError, match="__schema"):
        parse_graphql_schema('{"data": {"queryType": {"name": "Q"}}}')


def test_parse_graphql_introspection_build_client_schema_fails() -> None:
    bad = json.dumps({"__schema": {"types": "not-a-list"}})
    with pytest.raises(DynamicAPIClientSpecError, match="Invalid GraphQL introspection"):
        parse_graphql_schema(bad)


def test_parse_graphql_sdl_non_graphql_error_wrapped() -> None:
    with pytest.raises(DynamicAPIClientSpecError, match="Invalid GraphQL SDL"):
        parse_graphql_schema("type Broken { y: }}")


def test_graphql_execute_data_not_object() -> None:
    class BadClient:
        def post_graphql(self, path: str, document: str, variables: dict | None = None):
            return []

    with pytest.raises(DynamicAPIClientModelError, match="not an object"):
        graphql_execute_data(BadClient(), "/g", "query { x }", None)


def test_build_graphql_model_classes_no_inferrable_types(tmp_path: Path) -> None:
    sdl = """
    type Thing { other: Thing }
    type Query { t: Thing }
    type Mutation { _: Int }
    """
    schema = parse_graphql_schema(sdl)
    mock_http = MagicMock()
    with pytest.raises(DynamicAPIClientSpecError, match="No GraphQL object"):
        build_graphql_model_classes(schema, graphql_path="/graphql", http_client=mock_http)


def test_looks_like_graphql_schema_keyword() -> None:
    from dynamicapiclient.graphql_support import looks_like_graphql_sdl

    text = """
    schema { query: Q }
    type Q { x: Int }
    """
    assert looks_like_graphql_sdl(text)


def test_load_spec_path_read_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "spec.yaml"
    p.write_text("openapi: 3.0.0\n", encoding="utf-8")
    real_read = pathlib.Path.read_text

    def _read(self: pathlib.Path, *a: object, **kw: object) -> str:
        if self.resolve() == p.resolve():
            raise OSError("mock read failure")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "read_text", _read)
    with pytest.raises(DynamicAPIClientSpecError, match="Cannot read specification file"):
        load_spec(p)


def test_read_source_text_str_path_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "f.txt"
    p.write_text("hi", encoding="utf-8")
    real_read = pathlib.Path.read_text

    def _read(self: pathlib.Path, *a: object, **kw: object) -> str:
        if self.resolve() == p.resolve():
            raise OSError("read failed")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "read_text", _read)
    with pytest.raises(DynamicAPIClientSpecError, match="Cannot read file"):
        read_source_text(str(p), timeout=5.0)


def test_object_output_schema_required_scalar() -> None:
    from dynamicapiclient.graphql_support import _object_output_schema, parse_graphql_schema

    schema = parse_graphql_schema(
        """
        type T { id: ID!, name: String }
        type Query { _: Int }
        """
    )
    t = schema.type_map["T"]
    js = _object_output_schema(t)
    assert "id" in js.get("required", [])


def test_input_to_json_schema_no_required_fields() -> None:
    from dynamicapiclient.graphql_support import _input_to_json_schema, parse_graphql_schema

    schema = parse_graphql_schema(
        """
        input Opt { a: String }
        type Query { _: Int }
        """
    )
    inp = schema.type_map["Opt"]
    js = _input_to_json_schema(inp)
    assert "required" not in js


def test_scalar_selection_builtin_name_branch() -> None:
    from dynamicapiclient.graphql_support import _scalar_selection_lines, parse_graphql_schema

    schema = parse_graphql_schema(
        """
        type Odd { String: String, Int: Int }
        type Query { _: Int }
        """
    )
    odd = schema.type_map["Odd"]
    lines = _scalar_selection_lines(odd)
    assert "String" in lines and "Int" in lines


def test_author_like_path_nested_field() -> None:
    from dynamicapiclient.graphql_support import _author_like_path, parse_graphql_schema

    schema = parse_graphql_schema(
        """
        type Author { id: ID!, name: String }
        type AuthorPayload { author: Author }
        type Query { _: Int }
        """
    )
    payload = schema.type_map["AuthorPayload"]
    author = schema.type_map["Author"]
    target, path = _author_like_path(payload, author)
    assert target == author
    assert path == ("author",)


def test_graphql_enum_fragment_in_schema_builder() -> None:
    from dynamicapiclient.graphql_support import _graphql_type_to_json_schema_fragment, parse_graphql_schema
    from graphql.type.definition import GraphQLEnumType

    schema = parse_graphql_schema(
        """
        enum Role { A B }
        type Query { _: Int }
        """
    )
    role = schema.type_map["Role"]
    assert isinstance(role, GraphQLEnumType)
    frag = _graphql_type_to_json_schema_fragment(role, role)
    assert frag == {"type": "string"}


def test_coerce_graphql_variable_non_id() -> None:
    from graphql.type.scalars import GraphQLString

    from dynamicapiclient.graphql_support import coerce_graphql_variable

    assert coerce_graphql_variable(GraphQLString, "x") == "x"


def test_graphql_path_normalized_leading_slash(library_graphql_path: Path) -> None:
    import httpx

    from dynamicapiclient import api_make

    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {"authors": []}}))
    hc = httpx.Client(transport=transport, base_url="https://gql.test")
    api = api_make(
        library_graphql_path,
        base_url="https://gql.test",
        graphql_path="graphql",
        http_client=hc,
    )
    assert api.spec_family == "graphql"
    api.close()


def test_parse_graphql_introspection_data_wrong_type() -> None:
    with pytest.raises(DynamicAPIClientSpecError, match="__schema"):
        parse_graphql_schema('{"data": []}')


def test_parse_graphql_sdl_generic_exception_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dynamicapiclient.graphql_support as gs

    def boom(_raw: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(gs, "build_schema", boom)
    with pytest.raises(DynamicAPIClientSpecError, match="Invalid GraphQL SDL"):
        parse_graphql_schema("type Q { x: Int }")


def test_navigate_graphql_payload_missing_key() -> None:
    from dynamicapiclient.graphql_support import navigate_graphql_payload
    from dynamicapiclient.exceptions import DynamicAPIClientModelError

    with pytest.raises(DynamicAPIClientModelError, match="missing key"):
        navigate_graphql_payload({"a": 1}, ("b",))


def test_looks_like_graphql_sdl_empty() -> None:
    from dynamicapiclient.graphql_support import looks_like_graphql_sdl

    assert looks_like_graphql_sdl("") is False
    assert looks_like_graphql_sdl("   ") is False


def test_build_list_query_document_unknown_param() -> None:
    from dynamicapiclient.graphql_support import build_list_query_document
    from dynamicapiclient.exceptions import DynamicAPIClientModelError

    msg = "Unknown GraphQL arguments"
    with pytest.raises(DynamicAPIClientModelError, match=msg):
        build_list_query_document(
            "authors",
            "id name",
            {"nope": 1},
            {"limit": "Int!"},
            {"limit": object()},
        )


def test_build_graphql_model_classes_duplicate_safe_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dynamicapiclient.api as api_mod

    monkeypatch.setattr(api_mod, "_sanitize_identifier", lambda _name: "Dup")

    sdl = """
    type Book { id: ID!, title: String }
    type Author { id: ID!, name: String }
    type Query { books: [Book!], authors: [Author!] }
    type Mutation { _: Int }
    """
    schema = parse_graphql_schema(sdl)
    mock_http = MagicMock()
    with pytest.raises(DynamicAPIClientSpecError, match="both map"):
        build_graphql_model_classes(
            schema,
            graphql_path="/graphql",
            http_client=mock_http,
        )


def test_openapi_get_base_url_non_spec_error_wrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    from dynamicapiclient import api_make
    import dynamicapiclient.api as api_mod

    p = tmp_path / "o.yaml"
    p.write_text(
        "openapi: 3.0.0\n"
        "info: {title: t, version: '1'}\n"
        "paths: {}\n"
        "components:\n"
        "  schemas:\n"
        "    X:\n"
        "      type: object\n",
        encoding="utf-8",
    )

    def boom(*_a: object, **_k: object) -> None:
        raise ValueError("bad base")

    monkeypatch.setattr(api_mod, "openapi_spec_base_url", boom)
    with pytest.raises(DynamicAPIClientSpecError, match="bad base"):
        tr = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
        api_make(p, base_url=None, http_client=httpx.Client(transport=tr))


def test_api_make_resolved_schema_recursion_error_wrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    from dynamicapiclient import api_make
    import dynamicapiclient.api as api_mod

    p = tmp_path / "o.yaml"
    p.write_text(
        "openapi: 3.0.0\n"
        "info: {title: t, version: '1'}\n"
        "paths: {}\n"
        "components:\n"
        "  schemas:\n"
        "    X:\n"
        "      type: object\n",
        encoding="utf-8",
    )

    def rec(*_a: object, **_k: object) -> None:
        raise RecursionError("deep")

    monkeypatch.setattr(api_mod, "resolved_schema", rec)
    with pytest.raises(DynamicAPIClientSpecError, match="cycle"):
        tr = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
        hc = httpx.Client(transport=tr)
        api_make(p, base_url="https://x.test", http_client=hc)
