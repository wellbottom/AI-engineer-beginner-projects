"""Unit tests for the ``ai_shared.errors`` structured error hierarchy.

Covers the shared JSON envelope, HTTP-status mapping, and the per-subclass
fields (Requirements 3.7, 3.8).
"""

from __future__ import annotations

import pytest

from ai_shared.errors import (
    AISharedError,
    EmbeddingsError,
    ImageProviderError,
    ImageTimeoutError,
    LLMGatewayError,
    LLMTimeoutError,
    MissingConfigError,
    PersistenceError,
    SearchError,
    ValidationError,
)


def test_base_to_dict_envelope():
    err = AISharedError(action="doing thing", reason="it broke", details={"k": "v"})
    assert err.to_dict() == {
        "error": {"action": "doing thing", "reason": "it broke", "details": {"k": "v"}}
    }


def test_to_dict_returns_copy_of_details():
    err = AISharedError(action="a", reason="r", details={"k": "v"})
    payload = err.to_dict()
    payload["error"]["details"]["k"] = "mutated"
    # Mutating the serialized copy must not affect the error's own details.
    assert err.details == {"k": "v"}


def test_validation_error_fields_and_status():
    err = ValidationError(field="temperature", constraint="must be within 0.0–2.0")
    assert err.http_status == 422
    assert err.field == "temperature"
    assert err.constraint == "must be within 0.0–2.0"
    body = err.to_dict()["error"]
    assert body["details"]["field"] == "temperature"
    assert body["details"]["constraint"] == "must be within 0.0–2.0"


def test_missing_config_error_names_and_no_http_status():
    err = MissingConfigError(names=["DB_HOST", "LLM_API_KEY"])
    assert err.http_status is None  # startup abort, not HTTP-served
    assert err.names == ["DB_HOST", "LLM_API_KEY"]
    assert err.to_dict()["error"]["details"]["names"] == ["DB_HOST", "LLM_API_KEY"]
    assert "DB_HOST" in err.reason and "LLM_API_KEY" in err.reason


def test_missing_config_error_is_ai_shared_error():
    assert issubclass(MissingConfigError, AISharedError)


def test_search_error_optional_sub_question():
    plain = SearchError(reason="provider down")
    assert "sub_question" not in plain.to_dict()["error"]["details"]

    scoped = SearchError(reason="provider down", sub_question="What is X?")
    assert scoped.sub_question == "What is X?"
    assert scoped.to_dict()["error"]["details"]["sub_question"] == "What is X?"


@pytest.mark.parametrize(
    "cls, expected_status",
    [
        (LLMTimeoutError, 504),
        (LLMGatewayError, 502),
        (SearchError, 502),
        (EmbeddingsError, 502),
        (ImageProviderError, 502),
        (ImageTimeoutError, 504),
        (PersistenceError, 502),
    ],
)
def test_http_status_mapping(cls, expected_status):
    assert cls().http_status == expected_status


def test_defaults_fill_action_and_reason():
    err = LLMTimeoutError()
    body = err.to_dict()["error"]
    assert body["action"]  # non-empty default action
    assert body["reason"]  # non-empty default reason
