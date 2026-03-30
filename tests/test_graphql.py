from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest
import respx

from dynamicapiclient.api import api_make
from dynamicapiclient.exceptions import DynamicAPIClientModelError, DynamicAPIClientSpecError
from dynamicapiclient.graphql_support import (
    build_graphql_model_classes,
    looks_like_graphql_sdl,
    parse_graphql_schema,
    require_graphql,
)


def test_require_graphql_ok() -> None:
    require_graphql()


def test_looks_like_graphql_sdl() -> None:
    assert looks_like_graphql_sdl("type Query { x: Int }")
    assert looks_like_graphql_sdl('{"data":{"__schema":{"queryType":{"name":"Query"}}}}')
    assert not looks_like_graphql_sdl("openapi: 3.0.3\n")
    assert not looks_like_graphql_sdl("type: object\n")


def test_parse_graphql_sdl_roundtrip() -> None:
    sdl = Path(__file__).resolve().parent / "fixtures" / "library.graphql"
    schema = parse_graphql_schema(sdl.read_text(encoding="utf-8"))
    assert schema.query_type is not None
    assert schema.mutation_type is not None


def test_parse_introspection_json() -> None:
    schema = parse_graphql_schema(
        json.dumps(
            {
                "__schema": {
                    "queryType": {"name": "Query"},
                    "mutationType": {"name": "Mutation"},
                    "subscriptionType": None,
                    "types": [
                        {
                            "kind": "OBJECT",
                            "name": "Query",
                            "fields": [],
                            "interfaces": [],
                            "enumValues": None,
                            "possibleTypes": None,
                            "inputFields": None,
                            "ofType": None,
                        },
                        {
                            "kind": "OBJECT",
                            "name": "Mutation",
                            "fields": [],
                            "interfaces": [],
                            "enumValues": None,
                            "possibleTypes": None,
                            "inputFields": None,
                            "ofType": None,
                        },
                    ],
                    "directives": [],
                }
            }
        )
    )
    assert schema.query_type.name == "Query"


@respx.mock
def test_api_make_graphql_from_http_url(library_graphql_path: Path) -> None:
    sdl = library_graphql_path.read_text(encoding="utf-8")
    respx.get("https://spec.example/schema.graphql").mock(
        return_value=httpx.Response(200, text=sdl)
    )
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {"authors": []}}))
    hc = httpx.Client(transport=transport, base_url="https://api.example")
    api = api_make(
        "https://spec.example/schema.graphql",
        base_url="https://api.example",
        http_client=hc,
    )
    assert api.spec_family == "graphql"
    list(api.models.Author.objects.all())
    api.close()


@respx.mock
def test_api_make_graphql_from_http_url_without_base_url_uses_origin(library_graphql_path: Path) -> None:
    sdl = library_graphql_path.read_text(encoding="utf-8")
    respx.get("https://spec.example/schema.graphql").mock(
        return_value=httpx.Response(200, text=sdl)
    )
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {"authors": []}}))
    hc = httpx.Client(transport=transport, base_url="https://spec.example")
    api = api_make("https://spec.example/schema.graphql", http_client=hc)
    assert api.spec_family == "graphql"
    list(api.models.Author.objects.all())
    api.close()


def test_api_make_graphql_str_path(library_graphql_path: Path) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {"authors": []}}))
    hc = httpx.Client(transport=transport, base_url="https://gql.test")
    api = api_make(str(library_graphql_path), base_url="https://gql.test", http_client=hc)
    assert api.spec_family == "graphql"
    api.close()


def test_api_make_graphql_requires_base(tmp_path: Path) -> None:
    p = tmp_path / "s.graphql"
    p.write_text("type Query { x: Int }", encoding="utf-8")
    with pytest.raises(DynamicAPIClientSpecError, match="Pass base_url"):
        api_make(p)


def test_api_make_graphql_empty_base_url_override_raises(tmp_path: Path) -> None:
    p = tmp_path / "s.graphql"
    p.write_text("type Query { x: Int }", encoding="utf-8")
    with pytest.raises(DynamicAPIClientSpecError, match="empty"):
        api_make(p, base_url="   ")


def test_api_make_graphql_file_with_base_url_logs_info(
    library_graphql_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="dynamicapiclient.api")
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {}}))
    hc = httpx.Client(transport=transport, base_url="https://gql.test")
    api = api_make(library_graphql_path, base_url="https://gql.test", http_client=hc)
    api.close()
    assert any("no HTTP URL in the document" in r.message for r in caplog.records)


@respx.mock
def test_api_make_graphql_http_override_logs_info(
    library_graphql_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    sdl = library_graphql_path.read_text(encoding="utf-8")
    respx.get("https://spec.example/schema.graphql").mock(
        return_value=httpx.Response(200, text=sdl)
    )
    caplog.set_level(logging.INFO, logger="dynamicapiclient.api")
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {"authors": []}}))
    hc = httpx.Client(transport=transport, base_url="https://api.example")
    api = api_make(
        "https://spec.example/schema.graphql",
        base_url="https://api.example",
        http_client=hc,
    )
    api.close()
    assert any("URL origin" in r.message for r in caplog.records)


def test_build_graphql_model_classes_smoke(library_graphql_path: Path) -> None:
    schema = parse_graphql_schema(library_graphql_path.read_text(encoding="utf-8"))
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {}}))
    hc = httpx.Client(transport=transport, base_url="https://gql.test")
    from dynamicapiclient.client import HTTPClient

    http = HTTPClient("https://gql.test", client=hc)
    reg = build_graphql_model_classes(schema, graphql_path="/graphql", http_client=http)
    assert "Author" in reg and "Book" in reg


def test_graphql_author_crud_mock(library_graphql_path: Path) -> None:
    authors: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        q = body.get("query", "")
        variables = body.get("variables") or {}
        if "createAuthor" in q:
            inp = variables.get("input", {})
            aid = str(len(authors) + 1)
            row = {"id": aid, **inp}
            authors[aid] = row
            return httpx.Response(200, json={"data": {"createAuthor": row}})
        if "authors(" in q or q.strip().startswith("query") and "authors" in q:
            lst = list(authors.values())
            return httpx.Response(200, json={"data": {"authors": lst}})
        if "author(" in q:
            pk = variables.get("id")
            row = authors.get(str(pk))
            return httpx.Response(200, json={"data": {"author": row}})
        if "updateAuthor" in q:
            pk = str(variables.get("id"))
            upd = variables.get("input", {})
            if pk in authors:
                authors[pk].update(upd)
            return httpx.Response(200, json={"data": {"updateAuthor": authors[pk]}})
        if "deleteAuthor" in q:
            pk = str(variables.get("id"))
            authors.pop(pk, None)
            return httpx.Response(200, json={"data": {"deleteAuthor": True}})
        return httpx.Response(200, json={"errors": [{"message": "unhandled"}]})

    transport = httpx.MockTransport(handler)
    hc = httpx.Client(transport=transport, base_url="https://gql.test")
    api = api_make(library_graphql_path, base_url="https://gql.test", http_client=hc)
    assert api.spec_family == "graphql"
    a = api.models.Author.objects.create(name="Ada", email="a@b.c")
    assert a.pk == "1"
    g = api.models.Author.objects.get(pk="1")
    assert g._data["name"] == "Ada"
    assert len(list(api.models.Author.objects.all())) == 1
    api.models.Author.objects.update(a, email="x@y.z")
    assert a._data["email"] == "x@y.z"
    api.models.Author.objects.delete(a)
    assert list(authors.values()) == []
    api.close()


def test_graphql_post_errors_raise(library_graphql_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"errors": [{"message": "bad"}]})
    )
    hc = httpx.Client(transport=transport, base_url="https://gql.test")
    api = api_make(library_graphql_path, base_url="https://gql.test", http_client=hc)
    with pytest.raises(DynamicAPIClientModelError, match="GraphQL errors"):
        api.models.Author.objects.create(name="A", email="b@c.d")
    api.close()


def test_graphql_filter_unknown_arg(library_graphql_path: Path) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {"authors": []}}))
    hc = httpx.Client(transport=transport, base_url="https://gql.test")
    api = api_make(library_graphql_path, base_url="https://gql.test", http_client=hc)
    with pytest.raises(DynamicAPIClientModelError, match="Unknown GraphQL arguments"):
        list(api.models.Author.objects.filter(nope="x"))
    api.close()


def test_client_post_graphql_success() -> None:
    def h(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"hello": 1}})

    from dynamicapiclient.client import HTTPClient

    transport = httpx.MockTransport(h)
    with HTTPClient("https://x", client=httpx.Client(transport=transport)) as c:
        d = c.post_graphql("/g", "query { hello }")
    assert d == {"hello": 1}


def test_parse_graphql_schema_empty() -> None:
    with pytest.raises(DynamicAPIClientSpecError, match="empty"):
        parse_graphql_schema("   ")


def test_parse_graphql_schema_bad_json() -> None:
    with pytest.raises(DynamicAPIClientSpecError, match="Invalid JSON"):
        parse_graphql_schema("{not json")


def test_parse_graphql_schema_invalid_sdl() -> None:
    with pytest.raises(DynamicAPIClientSpecError, match="Invalid GraphQL SDL"):
        parse_graphql_schema("type Broken {")


def test_parse_graphql_schema_json_not_introspection() -> None:
    with pytest.raises(DynamicAPIClientSpecError, match="introspection"):
        parse_graphql_schema('{"openapi":"3.0.0"}')


def test_navigate_graphql_payload_missing_key() -> None:
    from dynamicapiclient.graphql_support import navigate_graphql_payload

    with pytest.raises(DynamicAPIClientModelError, match="missing key"):
        navigate_graphql_payload({"a": 1}, ("b",))


def test_build_list_query_document_with_vars(library_graphql_path: Path) -> None:
    from dynamicapiclient.graphql_support import build_list_query_document, parse_graphql_schema

    schema = parse_graphql_schema(library_graphql_path.read_text(encoding="utf-8"))
    q = schema.query_type
    assert q is not None
    field = q.fields["authors"]
    arg_sdls = {n: str(a.type) for n, a in field.args.items()}  # fallback if needed
    from dynamicapiclient.graphql_support import _type_to_variable_type_sdl

    arg_sdls = {n: _type_to_variable_type_sdl(a.type) for n, a in field.args.items()}
    arg_types = {n: a.type for n, a in field.args.items()}
    doc, vars_ = build_list_query_document(
        "authors",
        "id name email",
        {"name": "Z"},
        arg_sdls,
        arg_types,
    )
    assert "name" in doc and "$name" in doc
    assert vars_["name"] == "Z"


def test_input_json_schema_scalar_variants() -> None:
    from dynamicapiclient.graphql_support import _input_to_json_schema, parse_graphql_schema

    schema = parse_graphql_schema(
        """
        input Scalars { price: Float, n: Int!, ok: Boolean!, x: String }
        type Query { _: Int }
        """
    )
    inp = schema.type_map["Scalars"]
    js = _input_to_json_schema(inp)
    assert js["properties"]["price"]["type"] == "number"
    assert js["properties"]["n"]["type"] == "integer"


def test_graphql_fetch_list_not_array(library_graphql_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"data": {"authors": {}}})
    )
    hc = httpx.Client(transport=transport, base_url="https://gql.test")
    api = api_make(library_graphql_path, base_url="https://gql.test", http_client=hc)
    with pytest.raises(DynamicAPIClientModelError, match="list"):
        list(api.models.Author.objects.all())
    api.close()


def test_coerce_graphql_variable_id() -> None:
    from graphql.type.definition import GraphQLNonNull, GraphQLScalarType
    from graphql.type.scalars import GraphQLID

    from dynamicapiclient.graphql_support import coerce_graphql_variable

    assert coerce_graphql_variable(GraphQLNonNull(GraphQLID), 5) == "5"


def test_graphql_book_create_mock(library_graphql_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        q = body.get("query", "")
        if "createBook" in q:
            inp = body.get("variables", {}).get("input", {})
            return httpx.Response(
                200,
                json={"data": {"createBook": {"id": "10", **inp}}},
            )
        return httpx.Response(200, json={"errors": [{"message": "x"}]})

    transport = httpx.MockTransport(handler)
    hc = httpx.Client(transport=transport, base_url="https://gql.test")
    api = api_make(library_graphql_path, base_url="https://gql.test", http_client=hc)
    b = api.models.Book.objects.create(title="T", authorId="1")
    assert b._data["title"] == "T"
    api.close()


def test_client_post_graphql_errors() -> None:
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"errors": [{"message": "e"}], "data": None})
    )
    from dynamicapiclient.client import HTTPClient

    with HTTPClient("https://x", client=httpx.Client(transport=transport)) as c:
        with pytest.raises(DynamicAPIClientModelError, match="GraphQL errors"):
            c.post_graphql("/g", "x")


def test_client_post_graphql_missing_data_key() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))
    from dynamicapiclient.client import HTTPClient

    with HTTPClient("https://x", client=httpx.Client(transport=transport)) as c:
        with pytest.raises(DynamicAPIClientModelError, match="data"):
            c.post_graphql("/g", "query { x }")


def test_client_post_graphql_data_not_object() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []}))
    from dynamicapiclient.client import HTTPClient

    with HTTPClient("https://x", client=httpx.Client(transport=transport)) as c:
        with pytest.raises(DynamicAPIClientModelError, match="object"):
            c.post_graphql("/g", "query { x }")


def test_client_post_graphql_raw_not_object() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text='"x"'))
    from dynamicapiclient.client import HTTPClient

    with HTTPClient("https://x", client=httpx.Client(transport=transport)) as c:
        with pytest.raises(DynamicAPIClientModelError, match="JSON object"):
            c.post_graphql("/g", "query { x }")
