"""Shared fixtures for integration tests (live HTTP services)."""

from __future__ import annotations

import os

import httpx
import pytest

from dynamicapiclient import api_make

# OpenAPI 3.1 for Airflow 3.2 public API (match docker-compose image tag).
_DEFAULT_SPEC = (
    "https://raw.githubusercontent.com/apache/airflow/3.2.0/"
    "airflow-core/src/airflow/api_fastapi/core_api/openapi/v2-rest-api-generated.yaml"
)
AIRFLOW_OPENAPI_URL = os.environ.get("AIRFLOW_OPENAPI_URL", _DEFAULT_SPEC)


def airflow_integration_enabled() -> bool:
    return os.environ.get("RUN_AIRFLOW_INTEGRATION", "").lower() in ("1", "true", "yes")


def _airflow_origin() -> str:
    """Scheme + host + port only (OpenAPI paths include ``/api/v2/...``)."""
    legacy = os.environ.get("AIRFLOW_API_BASE_URL", "").strip().rstrip("/")
    if legacy and "/api/" not in legacy:
        return legacy
    if legacy:
        # Allow old CI env e.g. .../api/v1 -> strip to origin.
        return legacy.split("/api/")[0].rstrip("/") or "http://127.0.0.1:8080"
    return os.environ.get("AIRFLOW_ORIGIN", "http://127.0.0.1:8080").rstrip("/")


def _fetch_jwt(origin: str, user: str, password: str, timeout: float) -> str:
    r = httpx.post(
        f"{origin}/auth/token",
        json={"username": user, "password": password},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError(f"auth/token missing access_token: {data!r}")
    return token


@pytest.fixture(scope="module")
def airflow_api():
    """``api_make`` Airflow OpenAPI client + httpx session (integration exercises the ORM as-is)."""
    if not airflow_integration_enabled():
        pytest.skip(
            "Set RUN_AIRFLOW_INTEGRATION=1 and start the stack: "
            "docker compose -f docker-compose.airflow.yml up -d --wait"
        )
    origin = _airflow_origin()
    user = os.environ.get("AIRFLOW_API_USER", "airflow")
    password = os.environ.get("AIRFLOW_API_PASSWORD", "airflow")
    timeout = float(os.environ.get("AIRFLOW_HTTP_TIMEOUT", "120"))
    token = _fetch_jwt(origin, user, password, timeout)
    headers = {"Authorization": f"Bearer {token}"}
    client = httpx.Client(base_url=origin, headers=headers, timeout=timeout)
    api = api_make(AIRFLOW_OPENAPI_URL, base_url=origin, http_client=client)
    try:
        yield api
    finally:
        api.close()
        client.close()


@pytest.fixture
def airflow_http(airflow_api):
    """HTTPClient shared by generated models (use ``PoolResponse`` as anchor type)."""
    return airflow_api.models.PoolResponse._dynamicapiclient_client  # noqa: SLF001
