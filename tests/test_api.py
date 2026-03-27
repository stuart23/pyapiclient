from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from pyapiclient import api_make
from pyapiclient.api import ModelsNamespace, _sanitize_identifier
from pyapiclient.exceptions import PyAPIClientSpecError


def test_sanitize_identifier_basic() -> None:
    assert _sanitize_identifier("Author") == "Author"
    assert _sanitize_identifier("Foo-Bar") == "Foo_Bar"
    assert _sanitize_identifier("1st") == "_1st"


def test_sanitize_identifier_empty() -> None:
    with pytest.raises(PyAPIClientSpecError, match="cannot be empty"):
        _sanitize_identifier("")


def test_sanitize_identifier_only_symbols_becomes_underscores() -> None:
    assert _sanitize_identifier("%%%") == "___"


def test_models_namespace_dir_getattr_len_iter_repr() -> None:
    class M1:
        __name__ = "M1"

    class M2:
        __name__ = "M2"

    ns = ModelsNamespace({"A": M1, "B": M2})
    assert dir(ns) == ["A", "B"]
    assert ns.A is M1
    assert len(ns) == 2
    assert set(ns.model_names()) == {"A", "B"}
    assert "A" in repr(ns)
    assert list(ns) == [M1, M2]


def test_models_namespace_missing() -> None:
    ns = ModelsNamespace({})
    with pytest.raises(AttributeError, match="Model 'Z' not found"):
        ns.Z  # noqa: B018


def test_models_namespace_private_getattr() -> None:
    ns = ModelsNamespace({})
    with pytest.raises(AttributeError):
        ns._private_thing  # noqa: B018


def test_api_context_manager_and_props(library_oas3_path: Path) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
    hc = httpx.Client(transport=transport, base_url="https://api.example.com/v1")
    with api_make(library_oas3_path, http_client=hc) as api:
        assert api.spec_version == "3.0.3"
        assert api.spec_family == "openapi3"
        assert "Author" in dir(api.models)


def test_api_make_minimal_crud(library_oas3_path: Path) -> None:
    authors: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        segs = [x for x in request.url.path.rstrip("/").split("/") if x]
        if request.method == "POST" and segs and segs[-1] == "authors":
            data = json.loads(request.content.decode()) if request.content else {}
            row = {"id": len(authors) + 1, **data}
            authors.append(row)
            return httpx.Response(201, json=row)
        if request.method == "GET" and segs and segs[-1] == "authors" and len(segs) >= 1:
            return httpx.Response(200, json=authors)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    hc = httpx.Client(transport=transport, base_url="https://api.example.com/v1")
    api = api_make(library_oas3_path, http_client=hc)
    a = api.models.Author.objects.create(name="N", email="e@e.e")
    assert a.pk == 1
    api.close()


def test_api_make_book_create(library_oas3_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        segs = [x for x in request.url.path.rstrip("/").split("/") if x]
        if request.method == "POST" and segs and segs[-1] == "books":
            data = json.loads(request.content.decode()) if request.content else {}
            row = {"id": 1, **data}
            return httpx.Response(201, json=row)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    hc = httpx.Client(transport=transport, base_url="https://api.example.com/v1")
    api = api_make(library_oas3_path, http_client=hc)
    b = api.models.Book.objects.create(title="T", author_id=1)
    assert b.pk == 1


def test_api_make_no_schemas(tmp_path: Path) -> None:
    p = tmp_path / "empty.yaml"
    p.write_text(
        "openapi: 3.0.3\ninfo: {title: x, version: '1'}\npaths: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(PyAPIClientSpecError, match="No schema definitions"):
        api_make(p, base_url="https://x")


def test_api_make_duplicate_sanitized_names(tmp_path: Path) -> None:
    p = tmp_path / "dup.yaml"
    p.write_text(
        """
openapi: 3.0.3
info: {title: x, version: '1'}
servers: [{url: 'https://x'}]
paths: {}
components:
  schemas:
    A-B:
      type: object
      properties: {x: {type: string}}
    A_B:
      type: object
      properties: {y: {type: string}}
""",
        encoding="utf-8",
    )
    with pytest.raises(PyAPIClientSpecError, match="both map to model attribute"):
        api_make(p)


def test_api_make_headers_and_base_override(library_oas3_path: Path) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        segs = [x for x in request.url.path.rstrip("/").split("/") if x]
        if request.method == "GET" and segs and segs[-1] == "authors":
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    hc = httpx.Client(transport=transport, base_url="https://other.example/v1")
    api = api_make(
        library_oas3_path,
        base_url="https://other.example/v1",
        headers={"Authorization": "Bearer t"},
        http_client=hc,
    )
    list(api.models.Author.objects.all())
    assert seen.get("auth") == "Bearer t"
    api.close()


def test_api_make_swagger2_widget(swagger2_path: Path) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"id": 1, "name": "w"}))
    hc = httpx.Client(transport=transport, base_url="https://legacy.example.com/api")
    api = api_make(swagger2_path, http_client=hc)
    w = api.models.Widget.objects.get(1)
    assert w._data["name"] == "w"
    api.close()
