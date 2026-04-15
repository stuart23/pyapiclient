"""For each Airflow OpenAPI model, exercise whatever CRUD the dynamic client can infer."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from dynamicapiclient.exceptions import (
    DynamicAPIClientHTTPError,
    DynamicAPIClientModelError,
    DynamicAPIClientValidationError,
)
from dynamicapiclient.models import ModelInstance

pytestmark = pytest.mark.integration


def _minimal_required_kwargs(schema: dict[str, Any]) -> dict[str, Any]:
    """Fill ``required`` keys with type-shaped placeholders (best-effort)."""
    req = schema.get("required") or []
    props = schema.get("properties") or {}
    out: dict[str, Any] = {}
    for key in req:
        sub = props.get(key)
        if not isinstance(sub, dict):
            out[key] = None
            continue
        st = sub.get("type")
        if isinstance(st, list):
            st = next((x for x in st if x != "null"), st[0] if st else None)
        if st == "string":
            out[key] = f"auto_{uuid.uuid4().hex[:12]}"
        elif st == "integer":
            out[key] = 1
        elif st == "number":
            out[key] = 1.0
        elif st == "boolean":
            out[key] = False
        elif st == "array":
            out[key] = []
        elif st == "object" or "properties" in sub:
            out[key] = _minimal_required_kwargs(sub)
        else:
            out[key] = None
    return out


def _patch_kwargs_for_model(model_name: str, schema: dict[str, Any]) -> dict[str, Any]:
    if model_name == "VariableBody":
        return {"value": f"patched_{uuid.uuid4().hex[:8]}"}
    props = schema.get("properties") or {}
    for name, sub in props.items():
        if not isinstance(sub, dict):
            continue
        if name in ("name", "key", "dag_id", "connection_id", "pool_name", "variable_key"):
            continue
        if sub.get("type") == "integer":
            return {name: 2}
        if sub.get("type") == "string":
            return {name: f"p_{uuid.uuid4().hex[:8]}"}
    return {"slots": 2}


def _cross_delete_body_resource(airflow_api: Any, body_name: str, row: ModelInstance) -> bool:
    """Delete a resource created via a *Body model using the matching *Response model."""
    if not body_name.endswith("Body"):
        return False
    resp_name = body_name[:-4] + "Response"
    if not hasattr(airflow_api.models, resp_name):
        return False
    resp_cls = getattr(airflow_api.models, resp_name)
    b = resp_cls.objects._bindings()
    if b.delete is None:
        return False
    inst = ModelInstance(resp_cls, dict(row._data))
    if inst.pk is None:
        return False
    resp_cls.objects.delete(inst)
    return True


def _run_one_model(airflow_api: Any, model_name: str) -> tuple[list[str], list[str]]:
    """Return (success_tags, failure_messages)."""
    Model = getattr(airflow_api.models, model_name)
    mgr = Model.objects
    b = mgr._bindings()
    ok: list[str] = []
    bad: list[str] = []

    has_op = any((b.create, b.retrieve, b.list_op, b.update, b.delete))
    if not has_op:
        return ok, bad

    instance: ModelInstance | None = None
    created = False

    if b.list_op:
        try:
            params: dict[str, Any] = {}
            if "limit" in (b.list_query_params or []):
                params["limit"] = 5
            qs = mgr.filter(**params) if params else mgr.all()
            instance = qs.first()
            if instance is not None:
                ok.append("list")
        except (DynamicAPIClientValidationError, DynamicAPIClientHTTPError, DynamicAPIClientModelError) as e:
            bad.append(f"list: {e}")

    if b.retrieve and instance is None:
        defaults: dict[str, str] = {"PoolResponse": "default_pool"}
        pk = defaults.get(model_name)
        if pk is not None:
            try:
                instance = mgr.get(pk)
                ok.append("get_default")
            except (DynamicAPIClientValidationError, DynamicAPIClientHTTPError, DynamicAPIClientModelError) as e:
                bad.append(f"get_default: {e}")

    if b.retrieve and instance is not None and "get" not in ok and "get_default" not in ok:
        try:
            got = mgr.get(instance.pk)
            if got.pk != instance.pk:
                bad.append("get: pk mismatch")
            else:
                ok.append("get")
                instance = got
        except (DynamicAPIClientValidationError, DynamicAPIClientHTTPError, DynamicAPIClientModelError) as e:
            bad.append(f"get: {e}")

    if b.create:
        try:
            if model_name == "PoolBody":
                kwargs: dict[str, Any] = {"name": f"cr_{uuid.uuid4().hex[:18]}", "slots": 1}
            elif model_name == "VariableBody":
                kwargs = {"key": f"cr_{uuid.uuid4().hex[:18]}", "value": "integration"}
            else:
                kwargs = _minimal_required_kwargs(mgr._schema())
            instance = mgr.create(**kwargs)
            created = True
            ok.append("create")
        except (DynamicAPIClientValidationError, DynamicAPIClientHTTPError, DynamicAPIClientModelError) as e:
            bad.append(f"create: {e}")

    if b.update and instance is not None and instance.pk is not None:
        try:
            patch = _patch_kwargs_for_model(model_name, mgr._schema())
            instance = mgr.update(instance, **patch)
            ok.append("update")
        except (DynamicAPIClientValidationError, DynamicAPIClientHTTPError, DynamicAPIClientModelError) as e:
            bad.append(f"update: {e}")

    deleted = False
    if b.delete and instance is not None and instance.pk is not None:
        safe = created or str(instance.pk).startswith("cr_")
        if model_name == "PoolResponse" and str(instance.pk) == "default_pool":
            safe = False
        if safe:
            try:
                mgr.delete(instance)
                ok.append("delete")
                deleted = True
            except (DynamicAPIClientValidationError, DynamicAPIClientHTTPError, DynamicAPIClientModelError) as e:
                bad.append(f"delete: {e}")

    if created and not deleted and model_name.endswith("Body"):
        try:
            if instance is not None and _cross_delete_body_resource(airflow_api, model_name, instance):
                ok.append("delete_via_response")
                deleted = True
        except (DynamicAPIClientValidationError, DynamicAPIClientHTTPError, DynamicAPIClientModelError) as e:
            bad.append(f"delete_via_response: {e}")

    if b.create and created and not deleted:
        bad.append("create_without_delete")

    if has_op and not ok and not bad:
        bad.append("no_entry_point")

    return ok, bad


def test_airflow_all_models_best_effort_crud(airflow_api):
    """
    Every registered model runs list/get/create/update/delete where bindings exist.

    Failures are aggregated so one weak schema does not mask others; models with no
    inferred operations are ignored.
    """
    failures: list[str] = []
    for name in sorted(airflow_api.models.model_names()):
        ok, bad = _run_one_model(airflow_api, name)
        if not bad:
            continue
        if bad == ["no_entry_point"]:
            # Request-only schemas wired to PATCH without a discoverable row.
            continue
        failures.append(f"{name}: ok={ok!r} errors={bad!r}")

    assert not failures, "model CRUD issues:\n" + "\n".join(failures)
