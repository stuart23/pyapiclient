from __future__ import annotations

import pytest

from pyapiclient.exceptions import PyAPIClientValidationError
from pyapiclient.validation import validate_payload


def test_validate_object_required_missing() -> None:
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
    with pytest.raises(PyAPIClientValidationError, match="missing"):
        validate_payload(schema, {}, context="body")


def test_validate_object_wrong_root_type() -> None:
    schema = {"type": "object", "properties": {}}
    with pytest.raises(PyAPIClientValidationError, match="expected object"):
        validate_payload(schema, [], context="body")


def test_validate_additional_props_false() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"a": {"type": "integer"}},
    }
    with pytest.raises(PyAPIClientValidationError, match="unknown field"):
        validate_payload(schema, {"a": 1, "b": 2}, context="body")


def test_validate_field_type() -> None:
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
    with pytest.raises(PyAPIClientValidationError, match="incompatible"):
        validate_payload(schema, {"n": "x"}, context="body")


def test_validate_nullable() -> None:
    schema = {"type": "object", "properties": {"n": {"type": "string", "nullable": True}}}
    validate_payload(schema, {"n": None}, context="body")


def test_validate_array_items() -> None:
    schema = {
        "type": "object",
        "properties": {"xs": {"type": "array", "items": {"type": "integer"}}},
    }
    with pytest.raises(PyAPIClientValidationError, match=r"field 'xs'\[0\]"):
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
    with pytest.raises(PyAPIClientValidationError, match="missing required field 'z'"):
        validate_payload(schema, {"inner": {}}, context="root")


def test_validate_primitive_schema() -> None:
    validate_payload({"type": "string"}, "hi", context="x")
    with pytest.raises(PyAPIClientValidationError, match="incompatible"):
        validate_payload({"type": "string"}, 3, context="x")


def test_validate_union_type_list() -> None:
    schema = {"type": ["integer", "string"]}
    validate_payload(schema, 1, context="u")
    validate_payload(schema, "a", context="u")
    with pytest.raises(PyAPIClientValidationError):
        validate_payload(schema, [], context="u")
