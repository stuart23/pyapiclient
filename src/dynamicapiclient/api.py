"""Public ``api_make`` factory."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from dynamicapiclient.client import HTTPClient
from dynamicapiclient.exceptions import DynamicAPIClientSpecError
from dynamicapiclient.graphql_support import (
    build_graphql_model_classes,
    looks_like_graphql_sdl,
    parse_graphql_schema,
    require_graphql,
)
from dynamicapiclient.loader import fetch_url_text, load_spec, parse_openapi_document, read_source_text
from dynamicapiclient.models import Manager
from dynamicapiclient.routing import build_bindings
from dynamicapiclient.spec import detect_version, get_schemas, openapi_spec_base_url, resolved_schema

logger = logging.getLogger(__name__)


def _is_http_url(s: str) -> bool:
    parsed = urlparse(s)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _is_graphql_path(source: str | Path) -> bool:
    if isinstance(source, Path):
        return source.suffix.lower() in (".graphql", ".gql")
    if isinstance(source, str) and not _is_http_url(source.strip()):
        p = Path(source.strip()).expanduser()
        return p.is_file() and p.suffix.lower() in (".graphql", ".gql")
    return False


def _graphql_http_origin(http_source: str) -> str | None:
    """If ``http_source`` is an http(s) URL, return ``scheme://netloc``; else ``None``."""
    s = http_source.strip()
    if not _is_http_url(s):
        return None
    p = urlparse(s)
    if not p.scheme or not p.netloc:
        return None
    return f"{p.scheme}://{p.netloc}".rstrip("/")


def _resolve_openapi_base_url(spec: dict[str, Any], family: str, base_url: str | None) -> str:
    spec_url = openapi_spec_base_url(spec, family)
    if base_url is not None:
        u = base_url.strip().rstrip("/")
        if not u:
            raise DynamicAPIClientSpecError("base_url override is empty.")
        if spec_url is not None:
            logger.info(
                "api_make: using base_url=%r from argument; OpenAPI spec defines %r.",
                u,
                spec_url,
            )
        else:
            logger.info(
                "api_make: using base_url=%r from argument; OpenAPI spec has no server URL.",
                u,
            )
        return u
    if spec_url is None:
        if family == "swagger2":
            raise DynamicAPIClientSpecError(
                "Swagger 2.0 spec has no 'host'; pass base_url=... to api_make()."
            )
        raise DynamicAPIClientSpecError(
            "OpenAPI 3 spec has no 'servers' entry; pass base_url=... to api_make()."
        )
    return spec_url


def _sanitize_identifier(name: str) -> str:
    """Ensure schema name is a valid Python attribute (best effort)."""
    if not name:
        raise DynamicAPIClientSpecError("Schema name cannot be empty.")
    out = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    if out[0].isdigit():
        out = "_" + out
    if not out.isidentifier():
        raise DynamicAPIClientSpecError(f"Cannot map schema name {name!r} to a Python identifier.")
    return out


class ModelsNamespace:
    """
    ``api.models`` — discover models via ``dir()``, attribute access, and iteration.
    """

    __slots__ = ("_registry", "_registry_display")

    def __init__(self, registry: dict[str, type]) -> None:
        # public API names -> model class (Python-safe keys)
        self._registry = dict(registry)
        self._registry_display = {k: v.__name__ for k, v in self._registry.items()}

    def __getattr__(self, name: str) -> type:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._registry:
            return self._registry[name]
        available = ", ".join(sorted(self._registry)) or "(none)"
        raise AttributeError(
            f"Model {name!r} not found. Available models: {available}."
        )

    def __dir__(self) -> list[str]:
        return sorted(self._registry)

    def __iter__(self) -> Any:
        return iter(self._registry.values())

    def __len__(self) -> int:
        return len(self._registry)

    def __repr__(self) -> str:
        names = ", ".join(sorted(self._registry))
        return f"<dynamicapiclient.ModelsNamespace [{names}]>"

    def model_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._registry))


class API:
    """
    Root object returned by ``api_make`` — holds ``models`` and the HTTP client.
    """

    __slots__ = ("models", "_http", "_spec", "_version", "_family")

    def __init__(
        self,
        *,
        models: ModelsNamespace,
        http_client: HTTPClient,
        spec: dict[str, Any],
        version: str,
        family: str,
    ) -> None:
        self.models = models
        self._http = http_client
        self._spec = spec
        self._version = version
        self._family = family

    @property
    def spec_version(self) -> str:
        """OpenAPI/Swagger version or ``graphql`` for GraphQL schemas."""
        return self._version

    @property
    def spec_family(self) -> str:
        """``openapi3``, ``swagger2``, or ``graphql``."""
        return self._family

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> API:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _api_from_openapi_spec(
    spec: dict[str, Any],
    *,
    base_url: str | None,
    headers: dict[str, str] | None,
    timeout: float,
    http_client: httpx.Client | None,
) -> API:
    family, ver = detect_version(spec)
    schemas_raw = get_schemas(spec, family)
    if not schemas_raw:
        raise DynamicAPIClientSpecError("No schema definitions found (definitions / components.schemas).")

    try:
        resolved_base = _resolve_openapi_base_url(spec, family, base_url)
    except DynamicAPIClientSpecError:
        raise
    except Exception as e:  # defensive
        raise DynamicAPIClientSpecError(str(e)) from e

    schema_names = set(schemas_raw.keys())
    bindings_map = build_bindings(spec, family, schema_names)

    http = HTTPClient(resolved_base, headers=headers, timeout=timeout, client=http_client)

    registry: dict[str, type] = {}
    for raw_name in sorted(schema_names):
        safe = _sanitize_identifier(raw_name)
        if safe in registry:
            other = getattr(registry[safe], "__name__", safe)
            raise DynamicAPIClientSpecError(
                f"Schema names {other!r} and {raw_name!r} both map to model attribute {safe!r}."
            )
        try:
            res_schema = resolved_schema(spec, raw_name, schemas_raw[raw_name])
        except DynamicAPIClientSpecError:
            raise
        except RecursionError as e:
            raise DynamicAPIClientSpecError(f"Schema {raw_name!r} could not be resolved ($ref cycle?).") from e

        bindings = bindings_map[raw_name]

        model_cls = type(
            raw_name,
            (),
            {
                "__module__": "dynamicapiclient.dynamic",
                "_dynamicapiclient_schema": res_schema,
                "_dynamicapiclient_bindings": bindings,
                "_dynamicapiclient_client": http,
                "__doc__": f"Dynamic model for OpenAPI schema {raw_name!r}.",
            },
        )
        model_cls.objects = Manager(model_cls)
        registry[safe] = model_cls

    models_ns = ModelsNamespace(registry)
    return API(models=models_ns, http_client=http, spec=spec, version=ver, family=family)


def _api_from_graphql_text(
    text: str,
    *,
    base_url: str | None,
    graphql_path: str,
    headers: dict[str, str] | None,
    timeout: float,
    http_client: httpx.Client | None,
    source_http_url: str | None = None,
) -> API:
    require_graphql()
    schema = parse_graphql_schema(text)
    inferred = _graphql_http_origin(source_http_url) if source_http_url else None
    if base_url is not None:
        u = str(base_url).strip().rstrip("/")
        if not u:
            raise DynamicAPIClientSpecError("base_url override is empty.")
        if inferred is not None:
            logger.info(
                "api_make: using base_url=%r from argument; GraphQL schema was loaded from %r (URL origin %r).",
                u,
                source_http_url,
                inferred,
            )
        else:
            logger.info(
                "api_make: using base_url=%r from argument; GraphQL schema has no HTTP URL in the document.",
                u,
            )
        resolved = u
    elif inferred is not None:
        resolved = inferred
    else:
        raise DynamicAPIClientSpecError(
            "GraphQL schema has no server URL. Pass base_url=... to api_make(), "
            "or load the schema from an http(s) URL whose origin should be used as the API base."
        )
    gp = graphql_path.strip() or "/graphql"
    if not gp.startswith("/"):
        gp = "/" + gp
    http = HTTPClient(resolved, headers=headers, timeout=timeout, client=http_client)
    registry = build_graphql_model_classes(schema, graphql_path=gp, http_client=http)
    models_ns = ModelsNamespace(registry)
    meta = {"kind": "graphql", "graphql_path": gp}
    return API(
        models=models_ns,
        http_client=http,
        spec=meta,
        version="graphql",
        family="graphql",
    )


def api_make(
    source: str | Path,
    *,
    base_url: str | None = None,
    graphql_path: str = "/graphql",
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
    http_client: httpx.Client | None = None,
) -> API:
    """
    Build a Django-like API from an OpenAPI 2/3 document or a GraphQL schema (SDL or introspection JSON).

    Parameters
    ----------
    source:
        HTTPS URL or filesystem path to JSON/YAML OpenAPI, ``.graphql`` / ``.gql`` SDL, or introspection JSON.
    base_url:
        HTTP root for requests. If omitted, the URL from the OpenAPI ``servers`` / ``host`` entry is used;
        for GraphQL loaded from an ``http(s)`` schema URL, the URL's origin (scheme + host) is used.
        Passing ``base_url`` always wins and is logged at INFO. If the spec defines no server URL and
        ``base_url`` is omitted, :class:`DynamicAPIClientSpecError` is raised.
    graphql_path:
        URL path for GraphQL POST (default ``/graphql``). Only used for GraphQL schemas.
    headers:
        Default headers for every request (e.g. authorization).
    timeout:
        HTTP timeout in seconds when DynamicAPIClient creates its own client.
    http_client:
        Optional pre-built ``httpx.Client`` (for testing). When set, ``base_url`` should match
        the client's base URL or full URLs must work for your transport.
    """
    if _is_graphql_path(source):
        text = read_source_text(source, timeout=timeout)
        return _api_from_graphql_text(
            text,
            base_url=base_url,
            graphql_path=graphql_path,
            headers=headers,
            timeout=timeout,
            http_client=http_client,
            source_http_url=None,
        )

    if isinstance(source, str) and _is_http_url(source.strip()):
        src = source.strip()
        text = fetch_url_text(src, timeout=timeout)
        if looks_like_graphql_sdl(text):
            return _api_from_graphql_text(
                text,
                base_url=base_url,
                graphql_path=graphql_path,
                headers=headers,
                timeout=timeout,
                http_client=http_client,
                source_http_url=src,
            )
        spec = parse_openapi_document(text)
        return _api_from_openapi_spec(
            spec,
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            http_client=http_client,
        )

    if isinstance(source, Path) and source.suffix.lower() in (".yaml", ".yml"):
        spec = load_spec(source, timeout=timeout)
        return _api_from_openapi_spec(
            spec,
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            http_client=http_client,
        )

    try:
        sniff = read_source_text(source, timeout=timeout)
    except DynamicAPIClientSpecError:
        sniff = None
    if sniff and looks_like_graphql_sdl(sniff):
        return _api_from_graphql_text(
            sniff,
            base_url=base_url,
            graphql_path=graphql_path,
            headers=headers,
            timeout=timeout,
            http_client=http_client,
            source_http_url=None,
        )

    spec = load_spec(source, timeout=timeout)
    return _api_from_openapi_spec(
        spec,
        base_url=base_url,
        headers=headers,
        timeout=timeout,
        http_client=http_client,
    )
