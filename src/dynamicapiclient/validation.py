"""Lightweight JSON-schema subset validation for request/response bodies."""

from __future__ import annotations

from typing import Any

from dynamicapiclient.exceptions import DynamicAPIClientValidationError


def _type_ok(value: Any, schema: dict[str, Any]) -> bool:
    t = schema.get("type")
    if t is None:
        return True
    if isinstance(t, list):
        return any(_single_type_ok(value, x) for x in t)
    return _single_type_ok(value, t)


def _single_type_ok(value: Any, t: str) -> bool:
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "array":
        return isinstance(value, list)
    if t == "object":
        return isinstance(value, dict)
    return True


def validate_payload(schema: dict[str, Any], data: Any, *, context: str) -> None:
    """
    Validate ``data`` against a resolved schema object (subset of JSON Schema).

    Raises DynamicAPIClientValidationError on failure.
    """
    if schema.get("type") == "object" or "properties" in schema:
        if not isinstance(data, dict):
            raise DynamicAPIClientValidationError(f"{context}: expected object, got {type(data).__name__}.")
        props = schema.get("properties")
        if not isinstance(props, dict):
            props = {}
        required = schema.get("required")
        req_list = required if isinstance(required, list) else []
        errors: list[str] = []
        for key in req_list:
            if key not in data or data[key] is None:
                errors.append(f"missing required field {key!r}")
        for key, val in data.items():
            if key not in props:
                if schema.get("additionalProperties") is False:
                    errors.append(f"unknown field {key!r}")
                continue
            sub = props[key]
            if not isinstance(sub, dict):
                continue
            if val is None and sub.get("nullable") is True:
                continue
            if not _type_ok(val, sub):
                errors.append(
                    f"field {key!r}: value {val!r} incompatible with type {sub.get('type')!r}"
                )
            if isinstance(val, list) and sub.get("type") == "array":
                items = sub.get("items")
                if isinstance(items, dict):
                    for i, item in enumerate(val):
                        if not _type_ok(item, items):
                            errors.append(
                                f"field {key!r}[{i}]: incompatible with items schema type {items.get('type')!r}"
                            )
            if isinstance(val, dict) and sub.get("type") == "object" and "properties" in sub:
                try:
                    validate_payload(sub, val, context=f"{context}.{key}")
                except DynamicAPIClientValidationError as e:
                    errors.extend(e.errors or [str(e)])
        if errors:
            detail = "; ".join(errors)
            raise DynamicAPIClientValidationError(f"{context} validation failed: {detail}", errors=errors)
        return

    if not _type_ok(data, schema):
        raise DynamicAPIClientValidationError(
            f"{context}: value {data!r} incompatible with type {schema.get('type')!r}."
        )
