"""Load OpenAPI documents from URLs or local paths."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from pyapiclient.exceptions import PyAPIClientConfigurationError, PyAPIClientHTTPError, PyAPIClientSpecError

_YAML_SAFE_TAGS = (
    "application/json",
    "application/yaml",
    "application/x-yaml",
    "text/yaml",
    "text/x-yaml",
    "text/plain",
)


def _looks_like_url(s: str) -> bool:
    parsed = urlparse(s)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _guess_format_from_path(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in (".yaml", ".yml"):
        return "yaml"
    if suf == ".json":
        return "json"
    return "yaml"


def parse_openapi_document(text: str) -> dict[str, Any]:
    """Parse YAML or JSON text into an OpenAPI dict (used after a single HTTP fetch)."""
    raw = text.strip()
    if not raw:
        raise PyAPIClientSpecError("OpenAPI document is empty.")
    fmt = "json" if re.search(r"^\s*\{", raw) else "yaml"
    return _parse_text(raw, fmt)


def _parse_text(text: str, fmt: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise PyAPIClientSpecError("Specification file is empty.")
    if fmt == "json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise PyAPIClientSpecError(f"Invalid JSON: {e}") from e
    else:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise PyAPIClientSpecError(f"Invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise PyAPIClientSpecError("OpenAPI document must be a JSON/YAML object at the root.")
    return data


def load_spec(source: str | Path, *, timeout: float = 60.0) -> dict[str, Any]:
    """
    Load a raw OpenAPI 2 or 3 document as a dict.

    ``source`` may be an http(s) URL or a filesystem path (str or Path).
    """
    if isinstance(source, Path):
        path = source.expanduser().resolve()
        if not path.is_file():
            raise PyAPIClientSpecError(f"Specification path does not exist or is not a file: {path}")
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as e:
            raise PyAPIClientSpecError(f"Cannot read specification file: {e}") from e
        return _parse_text(raw, _guess_format_from_path(path))

    if not isinstance(source, str):
        raise PyAPIClientConfigurationError(
            f"Source must be a URL string or pathlib.Path, got {type(source).__name__}."
        )

    source = source.strip()
    if not source:
        raise PyAPIClientConfigurationError("Source URL or path is empty.")

    if _looks_like_url(source):
        return _load_from_url(source, timeout=timeout)

    path = Path(source).expanduser()
    if path.exists() and path.is_file():
        return load_spec(path, timeout=timeout)

    raise PyAPIClientSpecError(
        f"Could not load specification: not a valid URL and not an existing file: {source!r}"
    )


def fetch_url_text(url: str, *, timeout: float) -> str:
    """Download URL body as text (used for OpenAPI and GraphQL schema detection)."""
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise PyAPIClientHTTPError(
            f"Failed to fetch document ({e.response.status_code}): {url}",
            status_code=e.response.status_code,
            response_body=e.response.text[:2000] if e.response.text else None,
        ) from e
    except httpx.RequestError as e:
        raise PyAPIClientSpecError(f"Network error while fetching document: {e}") from e

    text = response.text
    if not text.strip():
        raise PyAPIClientSpecError("Fetched document is empty.")
    return text


def _load_from_url(url: str, *, timeout: float) -> dict[str, Any]:
    text = fetch_url_text(url, timeout=timeout)
    fmt = "json" if re.search(r"^\s*\{", text) else "yaml"
    return _parse_text(text, fmt)


def read_source_text(source: str | Path, *, timeout: float) -> str:
    """Read raw UTF-8 text from a local path or URL."""
    if isinstance(source, Path):
        path = source.expanduser().resolve()
        if not path.is_file():
            raise PyAPIClientSpecError(f"Specification path does not exist or is not a file: {path}")
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            raise PyAPIClientSpecError(f"Cannot read file: {e}") from e

    if not isinstance(source, str):
        raise PyAPIClientConfigurationError(
            f"Source must be a URL string or pathlib.Path, got {type(source).__name__}."
        )

    s = source.strip()
    if not s:
        raise PyAPIClientConfigurationError("Source URL or path is empty.")

    if _looks_like_url(s):
        return fetch_url_text(s, timeout=timeout)

    path = Path(s).expanduser()
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            raise PyAPIClientSpecError(f"Cannot read file: {e}") from e

    raise PyAPIClientSpecError(
        f"Could not read specification text: not a valid URL and not an existing file: {source!r}"
    )
