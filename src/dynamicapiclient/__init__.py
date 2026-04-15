"""Dynamic ORM-style API clients from OpenAPI 2/3 or GraphQL schemas."""

from dynamicapiclient.api import api_make
from dynamicapiclient.validation import relax_openapi_missing_required
from dynamicapiclient.exceptions import (
    DynamicAPIClientConfigurationError,
    DynamicAPIClientError,
    DynamicAPIClientHTTPError,
    DynamicAPIClientModelError,
    DynamicAPIClientSpecError,
    DynamicAPIClientValidationError,
)

__all__ = [
    "api_make",
    "relax_openapi_missing_required",
    "DynamicAPIClientError",
    "DynamicAPIClientSpecError",
    "DynamicAPIClientConfigurationError",
    "DynamicAPIClientHTTPError",
    "DynamicAPIClientValidationError",
    "DynamicAPIClientModelError",
]

# Django-style alias (user-facing example uses camelCase apiMake)
apiMake = api_make
