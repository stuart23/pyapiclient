"""Shared fixtures for integration tests (live HTTP services)."""

from __future__ import annotations

import os

import httpx
import pytest

from dynamicapiclient import api_make

# OpenAPI document for the stable Airflow REST API (must match docker image tag).
AIRFLOW_OPENAPI_URL = os.environ.get(
    "AIRFLOW_OPENAPI_URL",
    "https://raw.githubusercontent.com/apache/airflow/2.10.5/airflow/api_connexion/openapi/v1.yaml",
)


def airflow_integration_enabled() -> bool:
    return os.environ.get("RUN_AIRFLOW_INTEGRATION", "").lower() in ("1", "true", "yes")


@pytest.fixture(scope="module")
def airflow_api():
    """Dynamic client built from the Airflow OpenAPI spec, talking to a real webserver."""
    if not airflow_integration_enabled():
        pytest.skip(
            "Set RUN_AIRFLOW_INTEGRATION=1 and start the stack: "
            "docker compose -f docker-compose.airflow.yml up -d --wait"
        )
    base = os.environ.get("AIRFLOW_API_BASE_URL", "http://127.0.0.1:8080/api/v1").rstrip("/")
    user = os.environ.get("AIRFLOW_API_USER", "airflow")
    password = os.environ.get("AIRFLOW_API_PASSWORD", "airflow")
    timeout = float(os.environ.get("AIRFLOW_HTTP_TIMEOUT", "60"))
    client = httpx.Client(base_url=base, auth=(user, password), timeout=timeout)
    api = api_make(AIRFLOW_OPENAPI_URL, base_url=base, http_client=client)
    try:
        yield api
    finally:
        api.close()
        client.close()
