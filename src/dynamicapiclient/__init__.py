"""Dynamic ORM-style API clients from OpenAPI 2/3 or GraphQL schemas."""

from dynamicapiclient.api import api_make
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
    "DynamicAPIClientError",
    "DynamicAPIClientSpecError",
    "DynamicAPIClientConfigurationError",
    "DynamicAPIClientHTTPError",
    "DynamicAPIClientValidationError",
    "DynamicAPIClientModelError",
]

# Django-style alias (user-facing example uses camelCase apiMake)
apiMake = api_make
