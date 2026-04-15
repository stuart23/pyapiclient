from __future__ import annotations

import pytest

from dynamicapiclient.exceptions import DynamicAPIClientValidationError
from dynamicapiclient.validation import relax_openapi_missing_required, validate_payload


def test_validate_object_required_missing() -> None:
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
    with pytest.raises(DynamicAPIClientValidationError, match="missing"):
        validate_payload(schema, {}, context="body")


def test_relax_openapi_missing_required_allows_absent_keys_on_response() -> None:
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
    with relax_openapi_missing_required():
        validate_payload(schema, {}, context="response body")
    with pytest.raises(DynamicAPIClientValidationError, match="missing"):
        validate_payload(schema, {}, context="request body")


def test_validate_object_wrong_root_type() -> None:
    schema = {"type": "object", "properties": {}}
    with pytest.raises(DynamicAPIClientValidationError, match="expected object"):
        validate_payload(schema, [], context="body")


def test_validate_additional_props_false() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"a": {"type": "integer"}},
    }
    with pytest.raises(DynamicAPIClientValidationError, match="unknown field"):
        validate_payload(schema, {"a": 1, "b": 2}, context="body")


def test_validate_field_type() -> None:
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
    with pytest.raises(DynamicAPIClientValidationError, match="incompatible"):
        validate_payload(schema, {"n": "x"}, context="body")


def test_validate_nullable() -> None:
    schema = {"type": "object", "properties": {"n": {"type": "string", "nullable": True}}}
    validate_payload(schema, {"n": None}, context="body")


def test_validate_array_items() -> None:
    schema = {
        "type": "object",
        "properties": {"xs": {"type": "array", "items": {"type": "integer"}}},
    }
    with pytest.raises(DynamicAPIClientValidationError, match=r"field 'xs'\[0\]"):
        validate_payload(schema, {"xs": ["a"]}, context="body")


def test_validate_nested_object() -> None:
    schema = {
        "type": "object",
        "properties": {
            "inner": {
                "type": "object",
                "required": ["z"],
                "properties": {"z": {"type": "boolean"}},
            }
        },
    }
    with pytest.raises(DynamicAPIClientValidationError, match="missing required field 'z'"):
        validate_payload(schema, {"inner": {}}, context="root")


def test_validate_primitive_schema() -> None:
    validate_payload({"type": "string"}, "hi", context="x")
    with pytest.raises(DynamicAPIClientValidationError, match="incompatible"):
        validate_payload({"type": "string"}, 3, context="x")


def test_validate_union_type_list() -> None:
    schema = {"type": ["integer", "string"]}
    validate_payload(schema, 1, context="u")
    validate_payload(schema, "a", context="u")
    with pytest.raises(DynamicAPIClientValidationError):
        validate_payload(schema, [], context="u")


def test_validate_properties_not_dict_uses_empty() -> None:
    schema = {"type": "object", "properties": "nope", "required": ["a"]}
    with pytest.raises(DynamicAPIClientValidationError, match="missing"):
        validate_payload(schema, {}, context="body")


def test_validate_required_not_list_treated_as_empty() -> None:
    schema = {
        "type": "object",
        "required": "x",
        "properties": {"a": {"type": "string"}},
    }
    validate_payload(schema, {"a": "ok"}, context="body")


def test_validate_subschema_not_dict_skipped() -> None:
    schema = {"type": "object", "properties": {"a": "not-a-schema"}}
    validate_payload(schema, {"a": 123}, context="body")


def test_validate_number_and_boolean_fields() -> None:
    schema = {
        "type": "object",
        "properties": {"n": {"type": "number"}, "b": {"type": "boolean"}},
    }
    validate_payload(schema, {"n": 1.5, "b": False}, context="body")
    with pytest.raises(DynamicAPIClientValidationError):
        validate_payload(schema, {"n": True, "b": True}, context="body")


def test_validate_unknown_json_schema_type_accepts_value() -> None:
    schema = {"type": "object", "properties": {"x": {"type": "weird"}}}
    validate_payload(schema, {"x": object()}, context="body")


def test_validate_unknown_fields_allowed_when_additional_not_false() -> None:
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
    validate_payload(schema, {"a": 1, "extra": "ok"}, context="body")


def test_validate_nested_errors_extend_inner_list() -> None:
    schema = {
        "type": "object",
        "properties": {
            "inner": {
                "type": "object",
                "required": ["u", "v"],
                "properties": {
                    "u": {"type": "string"},
                    "v": {"type": "string"},
                },
            }
        },
    }
    with pytest.raises(DynamicAPIClientValidationError) as ei:
        validate_payload(schema, {"inner": {}}, context="root")
    err = ei.value
    assert err.errors and len(err.errors) >= 2


def test_validate_array_items_schema_not_dict_no_item_checks() -> None:
    schema = {
        "type": "object",
        "properties": {"xs": {"type": "array", "items": True}},
    }
    validate_payload(schema, {"xs": [1, 2, 3]}, context="body")
