import pytest
from fastapi import HTTPException

from app.core.reviewer_auth import require_reviewer


TEST_KEY = "test-only-reviewer-key"


def test_authentication_succeeds_with_valid_key(monkeypatch):
    monkeypatch.setenv("REVIEWER_API_KEY", TEST_KEY)

    result = require_reviewer(TEST_KEY)

    assert result == "reviewer"


@pytest.mark.parametrize("api_key", [None, "", "wrong-key"])
def test_authentication_rejects_invalid_key(monkeypatch, api_key):
    monkeypatch.setenv("REVIEWER_API_KEY", TEST_KEY)

    with pytest.raises(HTTPException) as exc_info:
        require_reviewer(api_key)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Invalid reviewer credentials."


def test_authentication_rejects_missing_configuration(monkeypatch):
    monkeypatch.delenv("REVIEWER_API_KEY", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        require_reviewer(TEST_KEY)

    assert exc_info.value.status_code == 503
    assert (
        exc_info.value.detail
        == "Reviewer authentication is not configured."
    )


def test_authentication_rejects_whitespace_key(monkeypatch):
    monkeypatch.setenv("REVIEWER_API_KEY", TEST_KEY)

    with pytest.raises(HTTPException) as exc_info:
        require_reviewer("   ")

    assert exc_info.value.status_code == 403


def test_authentication_is_case_sensitive(monkeypatch):
    monkeypatch.setenv("REVIEWER_API_KEY", TEST_KEY)

    with pytest.raises(HTTPException) as exc_info:
        require_reviewer(TEST_KEY.upper())

    assert exc_info.value.status_code == 403
