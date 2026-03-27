from __future__ import annotations

import pytest

from pyapiclient.exceptions import PyAPIClientSpecError
from pyapiclient.routing import (
    OperationBinding,
    _list_item_ref_from_response,
    _list_query_params,
    _operation_body_schema_ref,
    _path_params_for_op,
    _ref_to_schema_name,
    _response_schema_ref,
    build_bindings,
)


def test_ref_to_schema_name() -> None:
    assert _ref_to_schema_name("#/definitions/X", "swagger2") == "X"
    assert _ref_to_schema_name("#/components/schemas/Y", "openapi3") == "Y"
    assert _ref_to_schema_name("#/other", "openapi3") is None


def test_operation_body_schema_ref_oas3() -> None:
    op = {
        "requestBody": {
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/A"}}}
        }
    }
    assert _operation_body_schema_ref(op, "openapi3") == "A"


def test_operation_body_schema_ref_oas3_missing() -> None:
    assert _operation_body_schema_ref({}, "openapi3") is None


def test_operation_body_schema_ref_swagger2() -> None:
    op = {"parameters": [{"in": "body", "schema": {"$ref": "#/definitions/W"}}]}
    assert _operation_body_schema_ref(op, "swagger2") == "W"


def test_operation_body_schema_ref_swagger2_bad_params() -> None:
    assert _operation_body_schema_ref({"parameters": "x"}, "swagger2") is None


def test_response_schema_ref_oas3() -> None:
    op = {
        "responses": {
            "200": {
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/A"}}}
            }
        }
    }
    assert _response_schema_ref(op, "openapi3") == "A"


def test_response_schema_ref_oas3_array() -> None:
    op = {
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "schema": {"type": "array", "items": {"$ref": "#/components/schemas/A"}}
                    }
                }
            }
        }
    }
    assert _response_schema_ref(op, "openapi3") == "A"


def test_response_schema_ref_swagger2() -> None:
    op = {"responses": {"200": {"schema": {"$ref": "#/definitions/W"}}}}
    assert _response_schema_ref(op, "swagger2") == "W"


def test_list_item_ref_wrapper_object() -> None:
    op = {
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "items": {"type": "array", "items": {"$ref": "#/components/schemas/A"}}
                            },
                        }
                    }
                }
            }
        }
    }
    assert _list_item_ref_from_response(op, "openapi3") == "A"


def test_list_item_ref_results_key() -> None:
    op = {
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "results": {"$ref": "#/components/schemas/A"}
                            },
                        }
                    }
                }
            }
        }
    }
    assert _list_item_ref_from_response(op, "openapi3") == "A"


def test_path_params_fallback_braces() -> None:
    op: dict = {}
    assert _path_params_for_op(op, "openapi3", "/a/{x}/b/{y}") == ["x", "y"]


def test_list_query_params() -> None:
    op = {"parameters": [{"in": "query", "name": "q"}, {"in": "header", "name": "h"}]}
    assert _list_query_params(op) == ["q"]


def test_build_bindings_paths_not_object() -> None:
    with pytest.raises(PyAPIClientSpecError, match="paths"):
        build_bindings({"paths": []}, "openapi3", {"A"})


def test_build_bindings_happy() -> None:
    spec = {
        "paths": {
            "/authors": {
                "get": {
                    "parameters": [{"in": "query", "name": "name"}],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/Author"},
                                    }
                                }
                            }
                        }
                    },
                },
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Author"}
                            }
                        }
                    },
                    "responses": {"201": {}},
                },
            },
            "/authors/{id}": {
                "get": {
                    "parameters": [{"name": "id", "in": "path", "required": True}],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Author"}
                                }
                            }
                        }
                    },
                },
                "delete": {
                    "parameters": [{"name": "id", "in": "path", "required": True}],
                    "responses": {"204": {"description": "x"}},
                },
            },
        }
    }
    b = build_bindings(spec, "openapi3", {"Author"})
    mb = b["Author"]
    assert isinstance(mb.create, OperationBinding)
    assert isinstance(mb.retrieve, OperationBinding)
    assert isinstance(mb.list_op, OperationBinding)
    assert mb.list_query_params == ["name"]
    assert isinstance(mb.delete, OperationBinding)
