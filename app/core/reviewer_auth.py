
import hmac
import os
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader


reviewer_key_header = APIKeyHeader(
    name="X-Reviewer-Key",
    auto_error=False,
)


def require_reviewer(
    api_key: Annotated[
        str | None,
        Depends(reviewer_key_header),
    ],
) -> str:
    """Allow access only when the reviewer key is valid."""

    expected_key = os.getenv("REVIEWER_API_KEY")

    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reviewer authentication is not configured.",
        )

    if not api_key or not hmac.compare_digest(
        api_key,
        expected_key,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid reviewer credentials.",
        )

    return "reviewer"
