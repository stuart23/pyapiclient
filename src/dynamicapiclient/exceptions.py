"""Error types for DynamicAPIClient."""


class DynamicAPIClientError(Exception):
    """Base exception for all DynamicAPIClient errors."""


class DynamicAPIClientSpecError(DynamicAPIClientError):
    """Invalid, unsupported, or unreadable OpenAPI specification."""


class DynamicAPIClientConfigurationError(DynamicAPIClientError):
    """Invalid client configuration (base URL, auth, options)."""


class DynamicAPIClientHTTPError(DynamicAPIClientError):
    """HTTP request failed or returned an unexpected response."""

    def __init__(self, message: str, *, status_code: int | None = None, response_body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class DynamicAPIClientValidationError(DynamicAPIClientError):
    """Request or response data failed schema validation."""

    def __init__(self, message: str, *, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or []


class DynamicAPIClientModelError(DynamicAPIClientError):
    """Model operation failed (missing binding, wrong usage)."""
