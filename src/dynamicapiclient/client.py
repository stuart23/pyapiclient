"""HTTP client wrapper."""

from __future__ import annotations

from typing import Any

import httpx

from dynamicapiclient.exceptions import DynamicAPIClientHTTPError, DynamicAPIClientModelError


class HTTPClient:
    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = dict(headers or {})
        self._timeout = timeout
        self._own_client = client is None
        self._client = client or httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers=self._headers,
        )

    def close(self) -> None:
        if self._own_client:
            self._client.close()

    def __enter__(self) -> HTTPClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def post_graphql(
        self,
        path: str,
        query: str,
        *,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        POST a GraphQL document. Returns the ``data`` object (raises if ``errors`` present).
        """
        if not path.startswith("/"):
            path = "/" + path
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        raw = self.request_json("POST", path, json_body=payload)
        if not isinstance(raw, dict):
            raise DynamicAPIClientModelError("GraphQL HTTP response must be a JSON object.")
        if raw.get("errors"):
            raise DynamicAPIClientModelError(f"GraphQL errors: {raw.get('errors')}")
        data = raw.get("data")
        if data is None:
            raise DynamicAPIClientModelError("GraphQL response is missing a top-level 'data' key.")
        if not isinstance(data, dict):
            raise DynamicAPIClientModelError("GraphQL 'data' must be an object.")
        return data

    def request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """
        Perform HTTP request; return parsed JSON or None for empty 204 body.
        ``path`` must start with / (relative to base_url).
        """
        if not path.startswith("/"):
            path = "/" + path
        target = path if self._own_client else f"{self._base_url}{path}"
        try:
            response = self._client.request(
                method.upper(),
                target,
                json=json_body,
                params=params,
                headers=self._headers or None,
            )
        except httpx.RequestError as e:
            raise DynamicAPIClientHTTPError(f"Request failed: {e}") from e

        if response.status_code >= 400:
            raise DynamicAPIClientHTTPError(
                f"HTTP {response.status_code} for {method.upper()} {path}",
                status_code=response.status_code,
                response_body=response.text[:4000] if response.text else None,
            )

        if response.status_code == 204 or not response.content:
            return None

        ct = (response.headers.get("content-type") or "").lower()
        if "json" not in ct and response.text.strip():
            # Some APIs omit content-type; try JSON anyway
            pass
        try:
            return response.json()
        except ValueError as e:
            raise DynamicAPIClientHTTPError(
                f"Response is not valid JSON ({response.status_code}) for {path}",
                status_code=response.status_code,
                response_body=response.text[:2000] if response.text else None,
            ) from e
