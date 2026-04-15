"""Integration tests against a live Apache Airflow REST API (OpenAPI v1)."""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration


def _api_base() -> str:
    return os.environ.get("AIRFLOW_API_BASE_URL", "http://127.0.0.1:8080/api/v1").rstrip("/")


def _http_auth() -> tuple[str, str]:
    return (
        os.environ.get("AIRFLOW_API_USER", "airflow"),
        os.environ.get("AIRFLOW_API_PASSWORD", "airflow"),
    )


def _delete_pool(pool_name: str) -> None:
    r = httpx.delete(
        f"{_api_base()}/pools/{pool_name}",
        auth=_http_auth(),
        timeout=float(os.environ.get("AIRFLOW_HTTP_TIMEOUT", "60")),
    )
    if r.status_code not in (204, 404):
        r.raise_for_status()


def test_airflow_pool_get_default(airflow_api):
    """GET /pools/{pool_name} for the built-in default pool."""
    pool = airflow_api.models.Pool.objects.get("default_pool")
    assert pool._data.get("name") == "default_pool"
    assert "slots" in pool._data


def test_airflow_pool_create_and_get(airflow_api):
    """POST /pools then GET using the dynamic Pool model (Pool schema has flat properties)."""
    name = f"dynapicli_{uuid.uuid4().hex[:20]}"
    try:
        created = airflow_api.models.Pool.objects.create(name=name, slots=1)
        assert created._data.get("name") == name
        fetched = airflow_api.models.Pool.objects.get(name)
        assert fetched._data.get("name") == name
        assert int(fetched._data.get("slots", 0)) >= 1
    finally:
        _delete_pool(name)
