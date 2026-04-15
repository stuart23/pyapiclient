from __future__ import annotations

import json
from urllib.parse import quote

import httpx
import pytest

from dynamicapiclient.client import HTTPClient
from dynamicapiclient.exceptions import DynamicAPIClientModelError, DynamicAPIClientValidationError
from dynamicapiclient.models import (
    Manager,
    ModelInstance,
    QuerySet,
    _normalize_list_payload,
    _serialize_value,
    build_request_body,
    expand_path,
)
from dynamicapiclient.routing import ModelBindings, OperationBinding
from dynamicapiclient.validation import validate_payload


def _author_schema() -> dict:
    return {
        "type": "object",
        "required": ["name"],
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "email": {"type": "string"},
        },
    }


def _make_author_model(client: HTTPClient, bindings: ModelBindings | None = None) -> type:
    b = bindings or ModelBindings(
        create=OperationBinding("/authors", "post"),
        retrieve=OperationBinding("/authors/{id}", "get", path_param_name="id"),
        list_op=OperationBinding("/authors", "get"),
        update=OperationBinding("/authors/{id}", "patch", path_param_name="id"),
        delete=OperationBinding("/authors/{id}", "delete", path_param_name="id"),
        list_query_params=["name"],
    )
    return type(
        "Author",
        (),
        {
            "_dynamicapiclient_schema": _author_schema(),
            "_dynamicapiclient_bindings": b,
            "_dynamicapiclient_client": client,
        },
    )


def test_expand_path_ok() -> None:
    assert expand_path("/a/{x}/b", {"x": 1}) == "/a/1/b"


def test_expand_path_encodes_path_segment() -> None:
    assert expand_path("/dags/{dag_id}", {"dag_id": "a/b"}) == "/dags/" + quote("a/b", safe="")


def test_model_instance_pk_from_retrieve_path_param() -> None:
    c = HTTPClient("https://x", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))))
    b = ModelBindings(
        retrieve=OperationBinding("/v/{variable_key}", "get", path_param_name="variable_key"),
    )
    m = type(
        "Var",
        (),
        {
            "_dynamicapiclient_schema": {},
            "_dynamicapiclient_bindings": b,
            "_dynamicapiclient_client": c,
        },
    )
    m.objects = Manager(m)
    inst = ModelInstance(m, {"key": "mykey", "value": "v"})
    assert inst.pk == "mykey"


def test_model_instance_pk_pool_name_from_name_alias() -> None:
    c = HTTPClient("https://x", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))))
    b = ModelBindings(
        retrieve=OperationBinding("/pools/{pool_name}", "get", path_param_name="pool_name"),
    )
    m = type(
        "Pool",
        (),
        {
            "_dynamicapiclient_schema": {},
            "_dynamicapiclient_bindings": b,
            "_dynamicapiclient_client": c,
        },
    )
    m.objects = Manager(m)
    inst = ModelInstance(m, {"name": "default_pool", "slots": 1})
    assert inst.pk == "default_pool"


def test_expand_path_missing_placeholder() -> None:
    with pytest.raises(DynamicAPIClientModelError, match="Could not expand"):
        expand_path("/a/{missing}", {})


def test_normalize_list_direct() -> None:
    assert _normalize_list_payload([{"id": 1}]) == [{"id": 1}]


def test_normalize_list_none() -> None:
    assert _normalize_list_payload(None) == []


def test_normalize_list_wrapped() -> None:
    assert _normalize_list_payload({"items": [{"id": 1}]}) == [{"id": 1}]


def test_normalize_list_records_key() -> None:
    assert _normalize_list_payload({"records": [1, 2]}) == [1, 2]


def test_normalize_list_first_array_in_dict() -> None:
    assert _normalize_list_payload({"meta": 1, "rows": [2, 3]}) == [2, 3]


def test_normalize_list_named_collection_key() -> None:
    assert _normalize_list_payload({"dags": [{"dag_id": "d"}], "total_entries": 1}) == [{"dag_id": "d"}]


def test_normalize_list_prefers_longest_object_array() -> None:
    assert _normalize_list_payload({"meta": [{"k": 1}], "dags": [{"dag_id": "a"}, {"dag_id": "b"}]}) == [
        {"dag_id": "a"},
        {"dag_id": "b"},
    ]


def test_normalize_list_bad() -> None:
    with pytest.raises(DynamicAPIClientModelError, match="unexpected"):
        _normalize_list_payload(42)


def test_serialize_primitive() -> None:
    assert _serialize_value({"type": "string"}, "x") == "x"


def test_serialize_model_instance_integer_fk() -> None:
    m = _make_author_model(HTTPClient("https://x", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))))
    inst = ModelInstance(m, {"id": 5, "name": "a"})
    assert _serialize_value({"type": "integer"}, inst) == 5


def test_serialize_model_instance_object_shape() -> None:
    m = _make_author_model(HTTPClient("https://x", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))))
    inst = ModelInstance(m, {"id": 2, "name": "b"})
    assert _serialize_value({"type": "object", "properties": {"id": {"type": "integer"}}}, inst) == {"id": 2}


def test_serialize_model_no_pk() -> None:
    m = _make_author_model(HTTPClient("https://x", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))))
    inst = ModelInstance(m, {"name": "x"})
    with pytest.raises(DynamicAPIClientValidationError, match="primary key"):
        _serialize_value({"type": "integer"}, inst)


def test_build_request_body_unknown_field() -> None:
    with pytest.raises(DynamicAPIClientValidationError, match="Unknown field"):
        build_request_body(_author_schema(), {"nope": 1})


def test_build_request_body_ok() -> None:
    body = build_request_body(_author_schema(), {"name": "Z"})
    assert body == {"name": "Z"}


def test_validate_request_body_missing_required_after_build() -> None:
    schema = _author_schema()
    body = build_request_body(schema, {})
    with pytest.raises(DynamicAPIClientValidationError, match="missing required field 'name'"):
        validate_payload(schema, body, context="request body")


def test_manager_create_missing_required_field() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = _make_author_model(client)
    m.objects = Manager(m)
    with pytest.raises(DynamicAPIClientValidationError, match="missing required field 'name'"):
        m.objects.create(email="e@e.e")


def _author_schema_name_and_email_required() -> dict:
    return {
        "type": "object",
        "required": ["name", "email"],
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "email": {"type": "string"},
        },
    }


def test_manager_create_missing_second_required_field() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = type(
        "Author",
        (),
        {
            "_dynamicapiclient_schema": _author_schema_name_and_email_required(),
            "_dynamicapiclient_bindings": ModelBindings(
                create=OperationBinding("/authors", "post"),
            ),
            "_dynamicapiclient_client": client,
        },
    )
    m.objects = Manager(m)
    with pytest.raises(DynamicAPIClientValidationError, match="missing required field 'email'"):
        m.objects.create(name="N")


def test_manager_update_merged_body_missing_required_field() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = type(
        "Author",
        (),
        {
            "_dynamicapiclient_schema": _author_schema_name_and_email_required(),
            "_dynamicapiclient_bindings": ModelBindings(
                create=OperationBinding("/authors", "post"),
                update=OperationBinding("/authors/{id}", "patch", path_param_name="id"),
            ),
            "_dynamicapiclient_client": client,
        },
    )
    m.objects = Manager(m)
    inst = ModelInstance(m, {"id": 1, "name": "A"})
    with pytest.raises(DynamicAPIClientValidationError, match="missing required field 'email'"):
        m.objects.update(inst, name="B")


def test_model_instance_repr() -> None:
    m = _make_author_model(HTTPClient("https://x", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))))
    r = repr(ModelInstance(m, {"id": 1}))
    assert "Author" in r


def test_model_instance_refresh_no_pk() -> None:
    m = _make_author_model(HTTPClient("https://x", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))))
    m.objects = Manager(m)
    inst = ModelInstance(m, {"name": "x"})
    with pytest.raises(DynamicAPIClientModelError, match="primary key"):
        inst.refresh_from_api()


def test_model_instance_refresh_no_manager() -> None:
    client = HTTPClient("https://x", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))))
    m = type(
        "NoObjects",
        (),
        {
            "_dynamicapiclient_schema": _author_schema(),
            "_dynamicapiclient_bindings": ModelBindings(),
            "_dynamicapiclient_client": client,
        },
    )
    inst = ModelInstance(m, {"id": 1})
    with pytest.raises(DynamicAPIClientModelError, match="objects manager"):
        inst.refresh_from_api()


def test_queryset_repr_len_iter_first() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=[{"id": 1, "name": "A", "email": "a@b.c"}])

    transport = httpx.MockTransport(handler)
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = _make_author_model(client)
    m.objects = Manager(m)
    qs = QuerySet(m.objects, {})
    assert "QuerySet" in repr(qs)
    assert len(qs) == 1
    assert qs.first() is not None
    assert list(qs)[0].pk == 1
    assert len(calls) == 1


def test_manager_create_get_list_update_delete() -> None:
    state: dict[str, list] = {"authors": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        url = str(request.url)
        segs = [p for p in path.rstrip("/").split("/") if p]
        if request.method == "POST" and segs == ["authors"]:
            data = json.loads(request.content.decode()) if request.content else {}
            row = {"id": len(state["authors"]) + 1, **data}
            state["authors"].append(row)
            return httpx.Response(201, json=row)
        if request.method == "GET" and segs == ["authors"]:
            return httpx.Response(200, json=state["authors"])
        if request.method == "GET" and len(segs) == 2 and segs[0] == "authors" and segs[1].isdigit():
            aid = int(segs[1])
            for a in state["authors"]:
                if a["id"] == aid:
                    return httpx.Response(200, json=a)
            return httpx.Response(404)
        if request.method == "PATCH" and len(segs) == 2 and segs[0] == "authors" and segs[1].isdigit():
            aid = int(segs[1])
            patch = json.loads(request.content.decode()) if request.content else {}
            for a in state["authors"]:
                if a["id"] == aid:
                    a.update(patch)
                    return httpx.Response(200, json=a)
            return httpx.Response(404)
        if request.method == "DELETE" and len(segs) == 2 and segs[0] == "authors" and segs[1].isdigit():
            aid = int(segs[1])
            state["authors"][:] = [a for a in state["authors"] if a["id"] != aid]
            return httpx.Response(204)
        return httpx.Response(500, text=f"unhandled {request.method} {url}")

    transport = httpx.MockTransport(handler)
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = _make_author_model(client)
    m.objects = Manager(m)

    a = m.objects.create(name="N", email="e@e.e")
    assert a.pk == 1
    g = m.objects.get(pk=1)
    assert g._data["name"] == "N"
    rows = list(m.objects.all())
    assert len(rows) == 1
    fq = m.objects.filter(name="N")
    assert len(fq) == 1
    m.objects.update(a, email="x@x.x")
    assert a._data["email"] == "x@x.x"
    m.objects.delete(a)
    assert state["authors"] == []


def test_manager_create_empty_response() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(201))
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = _make_author_model(client)
    m.objects = Manager(m)
    with pytest.raises(DynamicAPIClientModelError, match="empty body"):
        m.objects.create(name="x", email="y")


def test_manager_create_non_object_json() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(201, json=[1]))
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = _make_author_model(client)
    m.objects = Manager(m)
    with pytest.raises(DynamicAPIClientModelError, match="object JSON"):
        m.objects.create(name="x", email="y")


def test_manager_get_errors() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"id": 1, "name": "a", "email": "b"}))
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = _make_author_model(client)
    m.objects = Manager(m)
    with pytest.raises(DynamicAPIClientModelError, match="get\\(\\) accepts"):
        m.objects.get(1, extra=1)  # type: ignore[call-arg]
    with pytest.raises(DynamicAPIClientModelError, match="unexpected keyword"):
        m.objects.get(pk=1, bad=2)  # type: ignore[call-arg]
    with pytest.raises(DynamicAPIClientModelError, match="requires pk"):
        m.objects.get()


def test_manager_get_non_object() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json="nope"))
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = _make_author_model(client)
    m.objects = Manager(m)
    with pytest.raises(DynamicAPIClientModelError, match="object JSON"):
        m.objects.get(1)


def test_manager_no_bindings() -> None:
    empty = ModelBindings()
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = type(
        "X",
        (),
        {
            "_dynamicapiclient_schema": _author_schema(),
            "_dynamicapiclient_bindings": empty,
            "_dynamicapiclient_client": client,
        },
    )
    m.objects = Manager(m)
    with pytest.raises(DynamicAPIClientModelError, match="No create"):
        m.objects.create(name="a", email="b")
    with pytest.raises(DynamicAPIClientModelError, match="No retrieve"):
        m.objects.get(1)
    with pytest.raises(DynamicAPIClientModelError, match="No list"):
        m.objects.filter()
    with pytest.raises(DynamicAPIClientModelError, match="No list"):
        list(m.objects.all())


def test_manager_filter_unknown_query() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = _make_author_model(client)
    m.objects = Manager(m)
    with pytest.raises(DynamicAPIClientModelError, match="Unknown query"):
        m.objects.filter(badparam=1)


def test_manager_list_item_not_object() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=[1]))
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = _make_author_model(client)
    m.objects = Manager(m)
    with pytest.raises(DynamicAPIClientModelError, match="List item"):
        list(m.objects.all())


def test_manager_update_delete_errors() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"id": 1, "name": "a", "email": "e"}))
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = _make_author_model(client)
    m.objects = Manager(m)
    other = type("Other", (), {})()
    with pytest.raises(DynamicAPIClientModelError, match="model instance"):
        m.objects.update(other, name="z")  # type: ignore[arg-type]
    inst = ModelInstance(m, {"id": 1, "name": "a", "email": "e"})
    other_m = _make_author_model(client)
    other_m.objects = Manager(other_m)
    bad_inst = ModelInstance(other_m, {"id": 1, "name": "a", "email": "e"})
    with pytest.raises(DynamicAPIClientModelError, match="different model"):
        m.objects.update(bad_inst, name="z")
    no_pk = ModelInstance(m, {"name": "a", "email": "e"})
    with pytest.raises(DynamicAPIClientModelError, match="primary key"):
        m.objects.update(no_pk, name="z")
    with pytest.raises(DynamicAPIClientModelError, match="model instance"):
        m.objects.delete(other)  # type: ignore[arg-type]
    with pytest.raises(DynamicAPIClientModelError, match="different model"):
        m.objects.delete(bad_inst)
    with pytest.raises(DynamicAPIClientModelError, match="primary key"):
        m.objects.delete(no_pk)


def test_manager_update_204_merge() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(204))
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = _make_author_model(client)
    m.objects = Manager(m)
    inst = ModelInstance(m, {"id": 1, "name": "old", "email": "e"})
    out = m.objects.update(inst, name="new")
    assert out._data["name"] == "new"


def test_manager_update_non_object_body() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json="x"))
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = _make_author_model(client)
    m.objects = Manager(m)
    inst = ModelInstance(m, {"id": 1, "name": "a", "email": "e"})
    with pytest.raises(DynamicAPIClientModelError, match="object JSON"):
        m.objects.update(inst, name="z")


def test_manager_retrieve_no_path_param() -> None:
    b = ModelBindings(
        retrieve=OperationBinding("/x/{id}", "get", path_param_name=None),
        create=OperationBinding("/x", "post"),
    )
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"id": 1, "name": "a", "email": "e"}))
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = type(
        "Author",
        (),
        {"_dynamicapiclient_schema": _author_schema(), "_dynamicapiclient_bindings": b, "_dynamicapiclient_client": client},
    )
    m.objects = Manager(m)
    with pytest.raises(DynamicAPIClientModelError, match="path parameter"):
        m.objects.get(1)


def test_manager_delete_no_path_param() -> None:
    b = ModelBindings(
        delete=OperationBinding("/x/{id}", "delete", path_param_name=None),
        create=OperationBinding("/x", "post"),
    )
    transport = httpx.MockTransport(lambda r: httpx.Response(204))
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = type(
        "Author",
        (),
        {"_dynamicapiclient_schema": _author_schema(), "_dynamicapiclient_bindings": b, "_dynamicapiclient_client": client},
    )
    m.objects = Manager(m)
    inst = ModelInstance(m, {"id": 1, "name": "a", "email": "e"})
    with pytest.raises(DynamicAPIClientModelError, match="path parameter"):
        m.objects.delete(inst)


def test_model_instance_refresh_ok() -> None:
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"id": 1, "name": "fresh", "email": "e"})
    )
    client = HTTPClient("https://api", client=httpx.Client(transport=transport))
    m = _make_author_model(client)
    m.objects = Manager(m)
    inst = ModelInstance(m, {"id": 1, "name": "stale", "email": "e"})
    inst.refresh_from_api()
    assert inst._data["name"] == "fresh"
