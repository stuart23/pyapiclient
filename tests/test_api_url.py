from __future__ import annotations

from pathlib import Path

import httpx
import respx

from pyapiclient.api import api_make

# Published OpenAPI document for Apache Airflow’s stable REST API (same path as docs).
AIRFLOW_OPENAPI_SPEC_URL = (
    "https://airflow.apache.org/docs/apache-airflow/3.1.6/_specs/v2-rest-api-generated.yaml"
)


@respx.mock
def test_api_make_openapi_from_airflow_docs_url_string() -> None:
    """``api_make`` accepts an http(s) URL as ``source`` (not only a local path)."""
    # The real file is huge; mock the docs URL with a tiny OpenAPI 3.1 fragment in the same style.
    yaml_body = """
openapi: 3.1.0
info:
  title: Airflow API
  version: "2"
servers:
  - url: https://airflow.example.com
paths:
  /api/v2/version:
    get:
      operationId: get_version
      responses:
        "200":
          description: OK
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/VersionInfo"
components:
  schemas:
    VersionInfo:
      type: object
      required: [version, git_version]
      properties:
        version:
          type: string
        git_version:
          type: string
          nullable: true
"""
    respx.get(AIRFLOW_OPENAPI_SPEC_URL).mock(
        return_value=httpx.Response(200, text=yaml_body)
    )
    api = api_make(AIRFLOW_OPENAPI_SPEC_URL)
    assert api.spec_family == "openapi3"
    assert api.spec_version.startswith("3.1")
    assert "VersionInfo" in dir(api.models)
    api.close()


@respx.mock
def test_api_make_openapi_from_http_url(swagger2_path: Path) -> None:
    body = swagger2_path.read_text(encoding="utf-8")
    respx.get("https://spec.example/swagger.json").mock(
        return_value=httpx.Response(200, text=body)
    )
    api = api_make("https://spec.example/swagger.json")
    assert api.spec_family == "swagger2"
    assert "Widget" in dir(api.models)
    api.close()
