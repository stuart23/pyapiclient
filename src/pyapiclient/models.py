"""Django-like dynamic models and managers."""

from __future__ import annotations

import re
from typing import Any, Iterator, Mapping

from pyapiclient.client import HTTPClient
from pyapiclient.exceptions import PyAPIClientModelError, PyAPIClientValidationError
from pyapiclient.graphql_support import (
    GraphQLModelRuntime,
    build_list_query_document,
    graphql_execute_data,
    navigate_graphql_payload,
)
from pyapiclient.routing import ModelBindings, OperationBinding
from pyapiclient.validation import validate_payload


def expand_path(template: str, values: Mapping[str, Any]) -> str:
    out = template
    for key, val in values.items():
        out = out.replace("{" + key + "}", str(val))
    if re.search(r"\{[^}]+\}", out):
        missing = re.findall(r"\{([^}]+)\}", out)
        raise PyAPIClientModelError(
            f"Could not expand path {template!r}; missing values for: {', '.join(missing)}"
        )
    return out


def _normalize_list_payload(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("items", "results", "data", "records"):
            v = raw.get(key)
            if isinstance(v, list):
                return v
        for v in raw.values():
            if isinstance(v, list):
                return v
    raise PyAPIClientModelError(f"List endpoint returned unexpected payload type {type(raw).__name__}.")


def _serialize_value(prop_schema: dict[str, Any], value: Any) -> Any:
    if isinstance(value, ModelInstance):
        pk = value.pk
        if pk is None:
            raise PyAPIClientValidationError(
                f"Related instance {value!r} has no primary key; save it before linking."
            )
        ptype = prop_schema.get("type")
        if ptype in ("integer", "number", "string"):
            return pk
        if ptype == "object" or "properties" in prop_schema:
            nested = prop_schema.get("properties") or {}
            if "id" in nested:
                return {"id": pk}
            return {"id": pk}
        return pk
    return value


def build_request_body(properties_schema: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    props = properties_schema.get("properties")
    if not isinstance(props, dict):
        props = {}
    body: dict[str, Any] = {}
    for key, val in kwargs.items():
        if key not in props:
            raise PyAPIClientValidationError(f"Unknown field {key!r} for this model.")
        body[key] = _serialize_value(props[key], val)
    return body


class ModelInstance:
    """Single row / resource instance (like a Django model instance)."""

    __slots__ = ("_model", "_data")

    def __init__(self, model: type, data: dict[str, Any]) -> None:
        self._model = model
        self._data = dict(data)

    @property
    def pk(self) -> Any:
        d = self._data
        if "id" in d and d["id"] is not None:
            return d["id"]
        return None

    def __repr__(self) -> str:
        name = getattr(self._model, "__name__", "Model")
        return f"<{name}: {self._data!r}>"

    def refresh_from_api(self) -> None:
        """Reload this instance using the retrieve endpoint and ``pk``."""
        if self.pk is None:
            raise PyAPIClientModelError("Cannot refresh: instance has no primary key.")
        mgr = getattr(self._model, "objects", None)
        if mgr is None:
            raise PyAPIClientModelError("Model has no objects manager.")
        fresh = mgr.get(pk=self.pk)
        self._data.clear()
        self._data.update(fresh._data)


class QuerySet:
    """Lazy-ish collection returned by ``filter`` / ``all`` (executes on iteration or len)."""

    __slots__ = ("_manager", "_params", "_cache")

    def __init__(self, manager: Manager, params: dict[str, Any] | None = None) -> None:
        self._manager = manager
        self._params = dict(params or {})
        self._cache: list[ModelInstance] | None = None

    def _fetch(self) -> list[ModelInstance]:
        if self._cache is None:
            self._cache = self._manager._fetch_list(self._params)
        return self._cache

    def __iter__(self) -> Iterator[ModelInstance]:
        return iter(self._fetch())

    def __len__(self) -> int:
        return len(self._fetch())

    def first(self) -> ModelInstance | None:
        rows = self._fetch()
        return rows[0] if rows else None

    def __repr__(self) -> str:
        return f"<QuerySet {self._manager._model.__name__} params={self._params!r}>"


class Manager:
    """``Model.objects`` — create, get, filter, all, update, delete."""

    __slots__ = ("_model",)

    def __init__(self, model: type) -> None:
        self._model = model

    def _bindings(self) -> ModelBindings:
        return getattr(self._model, "_pyapiclient_bindings")

    def _client(self) -> HTTPClient:
        return getattr(self._model, "_pyapiclient_client")

    def _schema(self) -> dict[str, Any]:
        return getattr(self._model, "_pyapiclient_schema")

    def _is_graphql(self) -> bool:
        return getattr(self._model, "_pyapiclient_kind", "openapi") == "graphql"

    def _gql_rt(self) -> GraphQLModelRuntime:
        return getattr(self._model, "_pyapiclient_graphql")

    def _require(self, op: OperationBinding | None, name: str) -> OperationBinding:
        if op is None:
            raise PyAPIClientModelError(
                f"No {name} operation could be inferred from the OpenAPI spec for "
                f"{self._model.__name__}. Check that POST/GET/PATCH/DELETE paths reference this schema."
            )
        return op

    def create(self, **kwargs: Any) -> ModelInstance:
        if self._is_graphql():
            return self._graphql_create(**kwargs)
        b = self._bindings()
        op = self._require(b.create, "create")
        schema = self._schema()
        body = build_request_body(schema, kwargs)
        validate_payload(schema, body, context="request body")
        path = expand_path(op.path_template, {})
        raw = self._client().request_json(op.method.upper(), path, json_body=body)
        if raw is None:
            raise PyAPIClientModelError("Create returned empty body; cannot build model instance.")
        if not isinstance(raw, dict):
            raise PyAPIClientModelError(f"Create expected object JSON, got {type(raw).__name__}.")
        validate_payload(schema, raw, context="response body")
        return ModelInstance(self._model, raw)

    def _graphql_create(self, **kwargs: Any) -> ModelInstance:
        rt = self._gql_rt()
        if not rt.create_document or not rt.create_field_name:
            raise PyAPIClientModelError(
                f"No create mutation could be inferred for GraphQL type {self._model.__name__}."
            )
        schema = rt.create_input_schema
        body = build_request_body(schema, kwargs)
        validate_payload(schema, body, context="request body")
        variables = {rt.create_var_key: body}
        data = graphql_execute_data(self._client(), rt.graphql_path, rt.create_document, variables)
        node = data[rt.create_field_name]
        payload = navigate_graphql_payload(node, rt.create_result_path)
        if not isinstance(payload, dict):
            raise PyAPIClientModelError("GraphQL create payload must be an object.")
        validate_payload(self._schema(), payload, context="response body")
        return ModelInstance(self._model, payload)

    def get(self, *args: Any, **kwargs: Any) -> ModelInstance:
        if self._is_graphql():
            return self._graphql_get(*args, **kwargs)
        if args:
            if len(args) != 1 or kwargs:
                raise PyAPIClientModelError("get() accepts either a single positional pk or keyword pk= / id=.")
            pk = args[0]
        else:
            pk = kwargs.pop("pk", kwargs.pop("id", None))
            if kwargs:
                raise PyAPIClientModelError(
                    f"get() unexpected keyword arguments: {', '.join(sorted(kwargs.keys()))}"
                )
            if pk is None:
                raise PyAPIClientModelError("get() requires pk or id.")
        b = self._bindings()
        op = self._require(b.retrieve, "retrieve")
        if not op.path_param_name:
            raise PyAPIClientModelError("retrieve binding has no path parameter name.")
        path = expand_path(op.path_template, {op.path_param_name: pk})
        raw = self._client().request_json(op.method.upper(), path)
        if not isinstance(raw, dict):
            raise PyAPIClientModelError(f"get() expected object JSON, got {type(raw).__name__}.")
        validate_payload(self._schema(), raw, context="response body")
        return ModelInstance(self._model, raw)

    def _graphql_get(self, *args: Any, **kwargs: Any) -> ModelInstance:
        rt = self._gql_rt()
        if not rt.get_document or not rt.get_field_name:
            raise PyAPIClientModelError(
                f"No single-item query could be inferred for GraphQL type {self._model.__name__}."
            )
        if args:
            if len(args) != 1 or kwargs:
                raise PyAPIClientModelError("get() accepts either a single positional pk or keyword pk= / id=.")
            pk = args[0]
        else:
            pk = kwargs.pop("pk", kwargs.pop("id", None))
            if kwargs:
                raise PyAPIClientModelError(
                    f"get() unexpected keyword arguments: {', '.join(sorted(kwargs.keys()))}"
                )
            if pk is None:
                raise PyAPIClientModelError("get() requires pk or id.")
        data = graphql_execute_data(self._client(), rt.graphql_path, rt.get_document, {"id": str(pk)})
        node = data[rt.get_field_name]
        if node is None:
            raise PyAPIClientModelError(f"No GraphQL record returned for id={pk!r}.")
        payload = navigate_graphql_payload(node, rt.get_result_path)
        if not isinstance(payload, dict):
            raise PyAPIClientModelError("GraphQL get payload must be an object.")
        validate_payload(self._schema(), payload, context="response body")
        return ModelInstance(self._model, payload)

    def all(self) -> QuerySet:
        return QuerySet(self, {})

    def filter(self, **params: Any) -> QuerySet:
        if self._is_graphql():
            rt = self._gql_rt()
            if not rt.list_field:
                raise PyAPIClientModelError(
                    f"No list query could be inferred for GraphQL type {self._model.__name__}."
                )
            allowed = set(rt.list_arg_sdls)
            if allowed:
                bad = set(params) - allowed
                if bad:
                    raise PyAPIClientModelError(
                        f"Unknown GraphQL arguments for list field {rt.list_field!r}: {', '.join(sorted(bad))}. "
                        f"Allowed: {', '.join(sorted(allowed)) or '(none declared)'}"
                    )
            return QuerySet(self, params)
        b = self._bindings()
        if b.list_op is None:
            raise PyAPIClientModelError(
                f"No list operation for {self._model.__name__}; filter() is unavailable."
            )
        allowed = set(b.list_query_params or [])
        if allowed:
            bad = set(params) - allowed
            if bad:
                raise PyAPIClientModelError(
                    f"Unknown query parameters for list endpoint: {', '.join(sorted(bad))}. "
                    f"Allowed: {', '.join(sorted(allowed)) or '(none declared)'}"
                )
        return QuerySet(self, params)

    def _fetch_list(self, params: dict[str, Any]) -> list[ModelInstance]:
        if self._is_graphql():
            return self._graphql_fetch_list(params)
        b = self._bindings()
        op = self._require(b.list_op, "list")
        path = expand_path(op.path_template, {})
        raw = self._client().request_json(op.method.upper(), path, params=params or None)
        items = _normalize_list_payload(raw)
        schema = self._schema()
        out: list[ModelInstance] = []
        for item in items:
            if not isinstance(item, dict):
                raise PyAPIClientModelError(f"List item must be object, got {type(item).__name__}.")
            validate_payload(schema, item, context="list item")
            out.append(ModelInstance(self._model, item))
        return out

    def _graphql_fetch_list(self, params: dict[str, Any]) -> list[ModelInstance]:
        rt = self._gql_rt()
        if not rt.list_field:
            raise PyAPIClientModelError(
                f"No list query could be inferred for GraphQL type {self._model.__name__}."
            )
        doc, variables = build_list_query_document(
            rt.list_field,
            rt.selection,
            params,
            rt.list_arg_sdls,
            rt.list_arg_types,
        )
        data = graphql_execute_data(self._client(), rt.graphql_path, doc, variables)
        raw_list = data.get(rt.list_field)
        if raw_list is None:
            return []
        if not isinstance(raw_list, list):
            raise PyAPIClientModelError(f"GraphQL list field {rt.list_field!r} must return a list.")
        schema = self._schema()
        out: list[ModelInstance] = []
        for item in raw_list:
            if not isinstance(item, dict):
                raise PyAPIClientModelError(f"List item must be object, got {type(item).__name__}.")
            validate_payload(schema, item, context="list item")
            out.append(ModelInstance(self._model, item))
        return out

    def update(self, instance: ModelInstance, **kwargs: Any) -> ModelInstance:
        if self._is_graphql():
            return self._graphql_update(instance, **kwargs)
        if not isinstance(instance, ModelInstance):
            raise PyAPIClientModelError("update() requires a model instance as first argument.")
        if instance._model is not self._model:
            raise PyAPIClientModelError("update() instance belongs to a different model.")
        if instance.pk is None:
            raise PyAPIClientModelError("Cannot update instance without primary key.")
        b = self._bindings()
        op = self._require(b.update, "update")
        if not op.path_param_name:
            raise PyAPIClientModelError("update binding has no path parameter name.")
        schema = self._schema()
        body = build_request_body(schema, kwargs)
        merged = {**instance._data, **body}
        validate_payload(schema, merged, context="update body")
        path = expand_path(op.path_template, {op.path_param_name: instance.pk})
        raw = self._client().request_json(op.method.upper(), path, json_body=body)
        if raw is None:
            instance._data.update(body)
            return instance
        if not isinstance(raw, dict):
            raise PyAPIClientModelError(f"update() expected object JSON, got {type(raw).__name__}.")
        validate_payload(schema, raw, context="response body")
        instance._data.clear()
        instance._data.update(raw)
        return instance

    def _graphql_update(self, instance: ModelInstance, **kwargs: Any) -> ModelInstance:
        if not isinstance(instance, ModelInstance):
            raise PyAPIClientModelError("update() requires a model instance as first argument.")
        if instance._model is not self._model:
            raise PyAPIClientModelError("update() instance belongs to a different model.")
        if instance.pk is None:
            raise PyAPIClientModelError("Cannot update instance without primary key.")
        rt = self._gql_rt()
        if not rt.update_document or not rt.update_field_name:
            raise PyAPIClientModelError(
                f"No update mutation could be inferred for GraphQL type {self._model.__name__}."
            )
        schema = rt.update_input_schema
        body = build_request_body(schema, kwargs)
        merged = {**instance._data, **body}
        validate_payload(self._schema(), merged, context="update body")
        variables = {"id": str(instance.pk), rt.update_var_key: body}
        data = graphql_execute_data(self._client(), rt.graphql_path, rt.update_document, variables)
        node = data[rt.update_field_name]
        payload = navigate_graphql_payload(node, rt.update_result_path)
        if not isinstance(payload, dict):
            raise PyAPIClientModelError("GraphQL update payload must be an object.")
        validate_payload(self._schema(), payload, context="response body")
        instance._data.clear()
        instance._data.update(payload)
        return instance

    def delete(self, instance: ModelInstance) -> None:
        if self._is_graphql():
            self._graphql_delete(instance)
            return
        if not isinstance(instance, ModelInstance):
            raise PyAPIClientModelError("delete() requires a model instance.")
        if instance._model is not self._model:
            raise PyAPIClientModelError("delete() instance belongs to a different model.")
        if instance.pk is None:
            raise PyAPIClientModelError("Cannot delete instance without primary key.")
        b = self._bindings()
        op = self._require(b.delete, "delete")
        if not op.path_param_name:
            raise PyAPIClientModelError("delete binding has no path parameter name.")
        path = expand_path(op.path_template, {op.path_param_name: instance.pk})
        self._client().request_json(op.method.upper(), path)

    def _graphql_delete(self, instance: ModelInstance) -> None:
        if not isinstance(instance, ModelInstance):
            raise PyAPIClientModelError("delete() requires a model instance.")
        if instance._model is not self._model:
            raise PyAPIClientModelError("delete() instance belongs to a different model.")
        if instance.pk is None:
            raise PyAPIClientModelError("Cannot delete instance without primary key.")
        rt = self._gql_rt()
        if not rt.delete_document or not rt.delete_field_name:
            raise PyAPIClientModelError(
                f"No delete mutation could be inferred for GraphQL type {self._model.__name__}."
            )
        graphql_execute_data(
            self._client(),
            rt.graphql_path,
            rt.delete_document,
            {"id": str(instance.pk)},
        )