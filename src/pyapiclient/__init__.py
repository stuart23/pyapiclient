"""Dynamic ORM-style API clients from OpenAPI 2/3 or GraphQL schemas."""

from pyapiclient.api import api_make
from pyapiclient.exceptions import (
    PyAPIClientConfigurationError,
    PyAPIClientError,
    PyAPIClientHTTPError,
    PyAPIClientModelError,
    PyAPIClientSpecError,
    PyAPIClientValidationError,
)

__all__ = [
    "api_make",
    "PyAPIClientError",
    "PyAPIClientSpecError",
    "PyAPIClientConfigurationError",
    "PyAPIClientHTTPError",
    "PyAPIClientValidationError",
    "PyAPIClientModelError",
]

# Django-style alias (user-facing example uses camelCase apiMake)
apiMake = api_make
