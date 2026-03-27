from __future__ import annotations

import pytest

from pyapiclient.exceptions import PyAPIClientSpecError
from pyapiclient.spec import (
    detect_version,
    get_base_url,
    get_schemas,
    resolve_refs,
    resolved_schema,
)


def test_detect_swagger2() -> None:
    f, v = detect_version({"swagger": "2.0"})
    assert f == "swagger2" and v == "2.0"


def test_detect_swagger_unsupported() -> None:
    with pytest.raises(PyAPIClientSpecError, match="Unsupported Swagger"):
        detect_version({"swagger": "3.0"})


def test_detect_openapi3() -> None:
    f, v = detect_version({"openapi": "3.0.3"})
    assert f == "openapi3" and v == "3.0.3"


def test_detect_openapi31() -> None:
    f, v = detect_version({"openapi": "3.1.0"})
    assert f == "openapi3"


def test_detect_openapi_unsupported() -> None:
    with pytest.raises(PyAPIClientSpecError, match="Unsupported openapi"):
        detect_version({"openapi": "2.0"})


def test_detect_missing() -> None:
    with pytest.raises(PyAPIClientSpecError, match="Not a recognized"):
        detect_version({})


def test_get_schemas_swagger2() -> None:
    s = get_schemas({"definitions": {"A": {"type": "object"}}}, "swagger2")
    assert "A" in s


def test_get_schemas_swagger2_missing_definitions() -> None:
    assert get_schemas({}, "swagger2") == {}


def test_get_schemas_swagger2_bad_definitions() -> None:
    with pytest.raises(PyAPIClientSpecError, match="definitions"):
        get_schemas({"definitions": []}, "swagger2")


def test_get_schemas_oas3() -> None:
    spec = {"components": {"schemas": {"B": {"type": "string"}}}}
    s = get_schemas(spec, "openapi3")
    assert s["B"] == {"type": "string"}


def test_get_schemas_oas3_no_components() -> None:
    assert get_schemas({}, "openapi3") == {}


def test_get_schemas_oas3_bad_schemas() -> None:
    with pytest.raises(PyAPIClientSpecError, match="components.schemas"):
        get_schemas({"components": {"schemas": "x"}}, "openapi3")


def test_get_base_url_override() -> None:
    u = get_base_url({}, "swagger2", "https://override.example")
    assert u == "https://override.example"


def test_get_base_url_override_empty() -> None:
    with pytest.raises(PyAPIClientSpecError, match="empty"):
        get_base_url({}, "swagger2", "  ")


def test_get_base_url_swagger_no_host() -> None:
    with pytest.raises(PyAPIClientSpecError, match="host"):
        get_base_url({"swagger": "2.0"}, "swagger2", None)


def test_get_base_url_swagger_ok() -> None:
    u = get_base_url(
        {"swagger": "2.0", "host": "h.test", "basePath": "/v1", "schemes": ["http"]},
        "swagger2",
        None,
    )
    assert u == "http://h.test/v1"


def test_get_base_url_oas3_no_servers() -> None:
    with pytest.raises(PyAPIClientSpecError, match="servers"):
        get_base_url({"openapi": "3.0.0"}, "openapi3", None)


def test_get_base_url_oas3_bad_servers() -> None:
    with pytest.raises(PyAPIClientSpecError, match="servers"):
        get_base_url({"openapi": "3.0.0", "servers": []}, "openapi3", None)


def test_get_base_url_oas3_bad_first_server() -> None:
    with pytest.raises(PyAPIClientSpecError, match="servers\\[0\\]"):
        get_base_url({"openapi": "3.0.0", "servers": ["x"]}, "openapi3", None)


def test_get_base_url_oas3_bad_url() -> None:
    with pytest.raises(PyAPIClientSpecError, match="url"):
        get_base_url({"openapi": "3.0.0", "servers": [{}]}, "openapi3", None)


def test_get_base_url_oas3_ok() -> None:
    u = get_base_url(
        {"openapi": "3.0.0", "servers": [{"url": "https://x.y/"}]},
        "openapi3",
        None,
    )
    assert u == "https://x.y"


def test_resolve_refs_simple() -> None:
    spec = {
        "components": {
            "schemas": {
                "A": {"type": "object", "properties": {"x": {"$ref": "#/components/schemas/B"}}},
                "B": {"type": "string"},
            }
        }
    }
    node = spec["components"]["schemas"]["A"]
    out = resolve_refs(spec, node, frozenset())
    assert out["properties"]["x"] == {"type": "string"}


def test_resolve_refs_external_disallowed() -> None:
    with pytest.raises(PyAPIClientSpecError, match="internal"):
        resolve_refs({}, {"$ref": "http://other/x.json"}, frozenset())


def test_resolve_refs_invalid_pointer() -> None:
    with pytest.raises(PyAPIClientSpecError, match="Invalid"):
        resolve_refs({"a": 1}, {"$ref": "#/b"}, frozenset())


def test_resolve_refs_circular() -> None:
    spec = {"x": {"$ref": "#/y"}, "y": {"$ref": "#/x"}}
    with pytest.raises(PyAPIClientSpecError, match="Circular"):
        resolve_refs(spec, spec["x"], frozenset())


def test_resolve_refs_bad_ref_type() -> None:
    with pytest.raises(PyAPIClientSpecError, match="ref must be a string"):
        resolve_refs({"a": 1}, {"$ref": 1}, frozenset())  # type: ignore[dict-item]


def test_resolved_schema_not_object() -> None:
    with pytest.raises(PyAPIClientSpecError, match="object"):
        resolved_schema({}, "n", "bad")  # type: ignore[arg-type]
