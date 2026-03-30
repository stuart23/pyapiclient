from __future__ import annotations

from dynamicapiclient.exceptions import DynamicAPIClientHTTPError, DynamicAPIClientValidationError


def test_dynamicapiclient_http_error_attrs() -> None:
    e = DynamicAPIClientHTTPError("msg", status_code=418, response_body="body")
    assert e.status_code == 418
    assert e.response_body == "body"
    assert str(e) == "msg"


def test_dynamicapiclient_validation_error_errors() -> None:
    e = DynamicAPIClientValidationError("top", errors=["a", "b"])
    assert e.errors == ["a", "b"]
