"""HTTP helpers for Airflow integration tests (Airflow 3: origin + /api/v2 paths)."""

from __future__ import annotations

import os
from urllib.parse import quote

import httpx


def airflow_origin() -> str:
    """Scheme + host + port (no ``/api/...`` suffix)."""
    legacy = os.environ.get("AIRFLOW_API_BASE_URL", "").strip().rstrip("/")
    if legacy and "/api/" not in legacy:
        return legacy
    if legacy:
        return legacy.split("/api/")[0].rstrip("/") or "http://127.0.0.1:8080"
    return os.environ.get("AIRFLOW_ORIGIN", "http://127.0.0.1:8080").rstrip("/")


def http_auth_token() -> str:
    """JWT from ``POST /auth/token`` (same credentials as conftest)."""
    user = os.environ.get("AIRFLOW_API_USER", "airflow")
    password = os.environ.get("AIRFLOW_API_PASSWORD", "airflow")
    timeout = float(os.environ.get("AIRFLOW_HTTP_TIMEOUT", "120"))
    r = httpx.post(
        f"{airflow_origin()}/auth/token",
        json={"username": user, "password": password},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError(f"auth/token missing access_token: {data!r}")
    return token


def http_timeout() -> float:
    return float(os.environ.get("AIRFLOW_HTTP_TIMEOUT", "120"))