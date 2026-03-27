"""Error types for pyAPIClient."""


class PyAPIClientError(Exception):
    """Base exception for all pyAPIClient errors."""


class PyAPIClientSpecError(PyAPIClientError):
    """Invalid, unsupported, or unreadable OpenAPI specification."""


class PyAPIClientConfigurationError(PyAPIClientError):
    """Invalid client configuration (base URL, auth, options)."""


class PyAPIClientHTTPError(PyAPIClientError):
    """HTTP request failed or returned an unexpected response."""

    def __init__(self, message: str, *, status_code: int | None = None, response_body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class PyAPIClientValidationError(PyAPIClientError):
    """Request or response data failed schema validation."""

    def __init__(self, message: str, *, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or []


class PyAPIClientModelError(PyAPIClientError):
    """Model operation failed (missing binding, wrong usage)."""
