from __future__ import annotations

from pyapiclient.exceptions import PyAPIClientHTTPError, PyAPIClientValidationError


def test_pyapiclient_http_error_attrs() -> None:
    e = PyAPIClientHTTPError("msg", status_code=418, response_body="body")
    assert e.status_code == 418
    assert e.response_body == "body"
    assert str(e) == "msg"


def test_pyapiclient_validation_error_errors() -> None:
    e = PyAPIClientValidationError("top", errors=["a", "b"])
    assert e.errors == ["a", "b"]
