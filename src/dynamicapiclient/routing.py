"""Map OpenAPI paths and operations to model CRUD bindings."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from dynamicapiclient.exceptions import DynamicAPIClientSpecError
from dynamicapiclient.spec import get_schemas


@dataclass
class OperationBinding:
    """Resolved HTTP operation for a model."""

    path_template: str
    method: str
    path_param_name: str | None = None  # for /items/{id}


@dataclass
class ModelBindings:
    create: OperationBinding | None = None
    retrieve: OperationBinding | None = None
    list_op: OperationBinding | None = None
    update: OperationBinding | None = None
    delete: OperationBinding | None = None
    # query param names supported on list (from OpenAPI parameters)
    list_query_params: list[str] = field(default_factory=list)
    # When POST response schema differs from request body (e.g. *Body vs *Response).
    create_response_ref: str | None = None


def _ref_to_schema_name(ref: str, family: str) -> str | None:
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    if family == "swagger2" and ref.startswith("#/definitions/"):
        return ref.split("/")[-1]
    if family == "openapi3" and ref.startswith("#/components/schemas/"):
        return ref.split("/")[-1]
    return None


def _operation_body_schema_ref(op: dict[str, Any], family: str) -> str | None:
    if family == "openapi3":
        rb = op.get("requestBody")
        if not isinstance(rb, dict):
            return None
        content = rb.get("content")
        if not isinstance(content, dict):
            return None
        for _mt, body in content.items():
            if not isinstance(body, dict):
                continue
            schema = body.get("schema")
            if isinstance(schema, dict) and "$ref" in schema:
                return _ref_to_schema_name(schema["$ref"], family)
        return None
    # swagger 2
    params = op.get("parameters")
    if not isinstance(params, list):
        return None
    for p in params:
        if not isinstance(p, dict):
            continue
        if p.get("in") == "body":
            schema = p.get("schema")
            if isinstance(schema, dict) and "$ref" in schema:
                return _ref_to_schema_name(schema["$ref"], family)
    return None


def _response_schema_ref(op: dict[str, Any], family: str) -> str | None:
    responses = op.get("responses")
    if not isinstance(responses, dict):
        return None
    for code in ("200", "201", "default"):
        r = responses.get(code)
        if not isinstance(r, dict):
            continue
        if family == "openapi3":
            content = r.get("content")
            if isinstance(content, dict):
                for _mt, body in content.items():
                    if not isinstance(body, dict):
                        continue
                    schema = body.get("schema")
                    if isinstance(schema, dict) and "$ref" in schema:
                        return _ref_to_schema_name(schema["$ref"], family)
                    # array of ref
                    if isinstance(schema, dict) and schema.get("type") == "array":
                        items = schema.get("items")
                        if isinstance(items, dict) and "$ref" in items:
                            return _ref_to_schema_name(items["$ref"], family)
        else:
            schema = r.get("schema")
            if isinstance(schema, dict) and "$ref" in schema:
                return _ref_to_schema_name(schema["$ref"], family)
            if isinstance(schema, dict) and schema.get("type") == "array":
                items = schema.get("items")
                if isinstance(items, dict) and "$ref" in items:
                    return _ref_to_schema_name(items["$ref"], family)
    return None


def _deref_schema_node(
    schema: dict[str, Any] | None,
    family: str,
    defs: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve leading ``$ref`` chains against ``defs`` (components/schemas or definitions)."""
    if not isinstance(schema, dict):
        return {}
    if not defs:
        return schema
    seen: set[str] = set()
    cur: Any = schema
    while isinstance(cur, dict) and "$ref" in cur:
        name = _ref_to_schema_name(cur["$ref"], family)
        if not name or name in seen or name not in defs:
            break
        seen.add(name)
        nxt = defs[name]
        if not isinstance(nxt, dict):
            return {}
        cur = nxt
    return cur if isinstance(cur, dict) else {}


def _list_item_ref_from_response(
    op: dict[str, Any],
    family: str,
    defs: dict[str, Any] | None = None,
) -> str | None:
    """If 200 response is array of $ref or a wrapper object with an array-of-$ref field, return item name."""
    responses = op.get("responses")
    if not isinstance(responses, dict):
        return None
    for code in ("200", "201"):
        r = responses.get(code)
        if not isinstance(r, dict):
            continue
        schema: dict[str, Any] | None = None
        if family == "openapi3":
            content = r.get("content")
            if isinstance(content, dict):
                for _mt, body in content.items():
                    if isinstance(body, dict) and isinstance(body.get("schema"), dict):
                        schema = body["schema"]
                        break
        else:
            if isinstance(r.get("schema"), dict):
                schema = r["schema"]
        if not schema:
            continue
        schema = _deref_schema_node(schema, family, defs)
        if schema.get("type") == "array":
            items = schema.get("items")
            if isinstance(items, dict) and "$ref" in items:
                return _ref_to_schema_name(items["$ref"], family)
        props = schema.get("properties")
        if isinstance(props, dict):
            items = props.get("items") or props.get("results") or props.get("data")
            if isinstance(items, dict):
                if "$ref" in items:
                    return _ref_to_schema_name(items["$ref"], family)
                if items.get("type") == "array":
                    it = items.get("items")
                    if isinstance(it, dict) and "$ref" in it:
                        return _ref_to_schema_name(it["$ref"], family)
            for _key, pschema in props.items():
                if not isinstance(pschema, dict):
                    continue
                node = _deref_schema_node(pschema, family, defs)
                if node.get("type") == "array":
                    it = node.get("items")
                    if isinstance(it, dict) and "$ref" in it:
                        return _ref_to_schema_name(it["$ref"], family)
    return None


def _path_params_for_op(op: dict[str, Any], family: str, path: str) -> list[str]:
    names: list[str] = []
    params = op.get("parameters")
    if isinstance(params, list):
        for p in params:
            if isinstance(p, dict) and p.get("in") == "path":
                n = p.get("name")
                if isinstance(n, str):
                    names.append(n)
    if not names:
        names = re.findall(r"\{([^/}]+)\}", path)
    return names


def _list_query_params(op: dict[str, Any]) -> list[str]:
    out: list[str] = []
    params = op.get("parameters")
    if not isinstance(params, list):
        return out
    for p in params:
        if isinstance(p, dict) and p.get("in") == "query":
            n = p.get("name")
            if isinstance(n, str):
                out.append(n)
    return out


def build_bindings(spec: dict[str, Any], family: str, schema_names: set[str]) -> dict[str, ModelBindings]:
    """
    Infer CRUD bindings from paths. Later operations win if multiple match the same schema+verb.
    """
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise DynamicAPIClientSpecError("'paths' must be an object.")

    bindings: dict[str, ModelBindings] = {n: ModelBindings() for n in schema_names}
    defs = get_schemas(spec, family)

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            if method not in path_item:
                continue
            op = path_item[method]
            if not isinstance(op, dict):
                continue
            path_params = _path_params_for_op(op, family, path)
            has_path_var = bool(path_params)

            body_ref = _operation_body_schema_ref(op, family) if method in ("post", "put", "patch") else None
            resp_ref = _response_schema_ref(op, family)
            list_ref = _list_item_ref_from_response(op, family, defs)

            if method == "post" and body_ref and body_ref in bindings:
                b = bindings[body_ref]
                b.create = OperationBinding(path_template=path, method="post")
                crsp = _response_schema_ref(op, family)
                if crsp and crsp != body_ref:
                    b.create_response_ref = crsp

            if method == "get":
                if has_path_var and resp_ref and resp_ref in bindings:
                    b = bindings[resp_ref]
                    b.retrieve = OperationBinding(
                        path_template=path,
                        method="get",
                        path_param_name=path_params[0],
                    )
                elif not has_path_var and list_ref and list_ref in bindings:
                    b = bindings[list_ref]
                    b.list_op = OperationBinding(path_template=path, method="get")
                    b.list_query_params = _list_query_params(op)

            if method in ("put", "patch") and body_ref and body_ref in bindings and has_path_var:
                b = bindings[body_ref]
                b.update = OperationBinding(
                    path_template=path,
                    method=method,
                    path_param_name=path_params[0],
                )

            if method == "delete" and has_path_var:
                target = resp_ref if resp_ref and resp_ref in bindings else None
                if target:
                    b = bindings[target]
                    b.delete = OperationBinding(
                        path_template=path,
                        method="delete",
                        path_param_name=path_params[0],
                    )
                else:
                    for _name, mb in bindings.items():
                        if mb.retrieve and mb.retrieve.path_template == path:
                            mb.delete = OperationBinding(
                                path_template=path,
                                method="delete",
                                path_param_name=path_params[0],
                            )
                            break

    return bindings
