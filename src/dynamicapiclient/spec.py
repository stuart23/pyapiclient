"""OpenAPI 2/3 detection, schema extraction, and local $ref resolution."""

from __future__ import annotations

import re
from typing import Any

from dynamicapiclient.exceptions import DynamicAPIClientSpecError


def detect_version(spec: dict[str, Any]) -> tuple[str, str]:
    """
    Return (family, version_string).

    family is 'swagger2' or 'openapi3'.
    """
    if "swagger" in spec:
        ver = str(spec.get("swagger", ""))
        if ver != "2.0":
            raise DynamicAPIClientSpecError(f"Unsupported Swagger version {ver!r}; only 2.0 is supported.")
        return "swagger2", ver
    if "openapi" in spec:
        ver = str(spec.get("openapi", ""))
        m = re.match(r"^3\.(0|1)(\.\d+)?$", ver)
        if not m:
            raise DynamicAPIClientSpecError(
                f"Unsupported openapi field {ver!r}; only 3.0.x and 3.1.x are supported."
            )
        return "openapi3", ver
    raise DynamicAPIClientSpecError("Not a recognized OpenAPI document (missing 'swagger' or 'openapi' key).")


def get_schemas(spec: dict[str, Any], family: str) -> dict[str, Any]:
    """Return mapping of schema name -> raw schema object."""
    if family == "swagger2":
        defs = spec.get("definitions")
        if defs is None:
            return {}
        if not isinstance(defs, dict):
            raise DynamicAPIClientSpecError("'definitions' must be an object.")
        return defs
    components = spec.get("components")
    if not isinstance(components, dict):
        return {}
    schemas = components.get("schemas")
    if schemas is None:
        return {}
    if not isinstance(schemas, dict):
        raise DynamicAPIClientSpecError("'components.schemas' must be an object.")
    return schemas


def openapi_spec_base_url(spec: dict[str, Any], family: str) -> str | None:
    """
    Return the HTTP base URL declared in the OpenAPI document, or ``None`` if missing.

    Malformed ``servers`` / ``host`` shapes still raise :class:`DynamicAPIClientSpecError`.
    """
    if family == "swagger2":
        schemes = spec.get("schemes") or ["https"]
        scheme = schemes[0] if isinstance(schemes, list) and schemes else "https"
        if not isinstance(scheme, str):
            scheme = "https"
        host = spec.get("host") or ""
        if not host or not str(host).strip():
            return None
        base_path = spec.get("basePath") or ""
        path = base_path if base_path.startswith("/") else f"/{base_path}" if base_path else ""
        return f"{scheme}://{host}".rstrip("/") + (path.rstrip("/") if path else "")
    servers = spec.get("servers")
    if not servers or not isinstance(servers, list) or len(servers) == 0:
        return None
    first = servers[0]
    if not isinstance(first, dict):
        raise DynamicAPIClientSpecError("'servers[0]' must be an object with 'url'.")
    url = first.get("url")
    if not url or not isinstance(url, str):
        raise DynamicAPIClientSpecError("OpenAPI 3 'servers[0].url' is missing or invalid.")
    return url.rstrip("/")


def get_base_url(spec: dict[str, Any], family: str, override: str | None) -> str:
    """Resolve base URL without logging (tests and low-level callers)."""
    if override is not None:
        u = override.strip().rstrip("/")
        if not u:
            raise DynamicAPIClientSpecError("base_url override is empty.")
        return u
    spec_url = openapi_spec_base_url(spec, family)
    if spec_url is None:
        if family == "swagger2":
            raise DynamicAPIClientSpecError(
                "Swagger 2.0 spec has no 'host'; pass base_url=... to api_make()."
            )
        raise DynamicAPIClientSpecError(
            "OpenAPI 3 spec has no 'servers' entry; pass base_url=... to api_make()."
        )
    return spec_url


def _json_pointer_resolve(doc: dict[str, Any], pointer: str) -> Any:
    if not pointer.startswith("#/"):
        raise DynamicAPIClientSpecError(f"Only internal JSON pointers are supported (got {pointer!r}).")
    parts = pointer[2:].split("/")
    node: Any = doc
    for raw in parts:
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or key not in node:
            raise DynamicAPIClientSpecError(f"Invalid $ref path: {pointer!r}")
        node = node[key]
    return node


def resolve_refs(spec: dict[str, Any], node: Any, seen: frozenset[str]) -> Any:
    """
    Return a deep copy of ``node`` with internal ``#/`` references inlined.

    External references and recursion beyond ``seen`` raise DynamicAPIClientSpecError.
    """
    if isinstance(node, dict):
        if "$ref" in node and len(node) == 1:
            ref = node["$ref"]
            if not isinstance(ref, str):
                raise DynamicAPIClientSpecError("$ref must be a string.")
            if ref in seen:
                raise DynamicAPIClientSpecError(f"Circular $ref detected: {ref}")
            target = _json_pointer_resolve(spec, ref)
            return resolve_refs(spec, target, seen | {ref})
        return {k: resolve_refs(spec, v, seen) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve_refs(spec, item, seen) for item in node]
    return node


def resolved_schema(spec: dict[str, Any], name: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DynamicAPIClientSpecError(f"Schema {name!r} must be an object.")
    out = resolve_refs(spec, raw, frozenset())
    if not isinstance(out, dict):
        raise DynamicAPIClientSpecError(f"Resolved schema {name!r} is not an object.")
    return out
