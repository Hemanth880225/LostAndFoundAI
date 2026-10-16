"""API router for Reward Points policy, calculation, crediting, and ledger history."""

from typing import Annotated, Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.reviewer_auth import require_reviewer
from app.db.database import get_db
from app.db.models import RewardLedger
from app.extensions.rewards.schemas import (
    AccountBalanceResponse,
    CreditRewardRequest,
    ReverseRewardRequest,
    RewardCalculationRequest,
    RewardCalculationResponse,
    RewardPolicyResponse,
    RewardTransactionItem,
)
from app.extensions.rewards.service import (
    get_current_policy,
    get_user_balance_response,
    simulate_reward_preview,
    validate_and_credit_recovery_reward,
    validate_and_reverse_reward,
)

router = APIRouter(
    prefix="/api/rewards",
    tags=["Reward Points"],
)

DatabaseSession = Annotated[Session, Depends(get_db)]
ReviewerAuth = Annotated[str, Depends(require_reviewer)]


@router.get(
    "/policy",
    response_model=RewardPolicyResponse,
    summary="Get active reward points policy",
    description="Returns current conversion rate (5 points = ₹1), caps, and programme rules.",
)
def get_policy_endpoint() -> RewardPolicyResponse:
    """Public transparency endpoint detailing the rewards formula and limits."""
    return get_current_policy()


@router.post(
    "/calculate-preview",
    response_model=RewardCalculationResponse,
    summary="Preview reward points for an item value",
    description="Simulate the points and estimated rupee value based on verified item price.",
)
def calculate_preview_endpoint(
    payload: RewardCalculationRequest,
) -> RewardCalculationResponse:
    """Calculate reward estimation without recording any transaction."""
    return simulate_reward_preview(
        item_value=payload.item_value,
        custom_rate=payload.custom_rate,
    )


@router.get(
    "/balance/{email}",
    response_model=AccountBalanceResponse,
    summary="Check student or helper reward points balance",
    description="Returns total earned points, estimated rupee equivalent, and auditable history.",
)
def get_balance_endpoint(
    email: str,
    db: DatabaseSession,
) -> AccountBalanceResponse:
    """Retrieve verified points ledger balance for an email address."""
    return get_user_balance_response(db=db, email=email)


@router.post(
    "/credit",
    response_model=RewardTransactionItem,
    status_code=status.HTTP_201_CREATED,
    summary="Credit verified recovery reward points",
    description="Authorized reviewer credits reward to finder only after confirmed item handover.",
)
def credit_reward_endpoint(
    payload: CreditRewardRequest,
    db: DatabaseSession,
    reviewer: ReviewerAuth,
) -> RewardTransactionItem:
    """Award verified points to a finder following confirmed physical handover."""
    entry = validate_and_credit_recovery_reward(
        db=db,
        payload=payload,
        reviewer_label=reviewer,
    )
    return RewardTransactionItem.model_validate(entry)


@router.post(
    "/reverse",
    response_model=RewardTransactionItem,
    summary="Reverse a reward transaction",
    description="Authorized reviewer safely offsets a transaction with negative ledger entry.",
)
def reverse_reward_endpoint(
    payload: ReverseRewardRequest,
    db: DatabaseSession,
    reviewer: ReviewerAuth,
) -> RewardTransactionItem:
    """Offset a previous transaction with full audit trail."""
    entry = validate_and_reverse_reward(
        db=db,
        payload=payload,
        reviewer_label=reviewer,
    )
    return RewardTransactionItem.model_validate(entry)


@router.get(
    "/ledger",
    response_model=List[RewardTransactionItem],
    summary="Inspect rewards audit ledger",
    description="Reviewer-only access to full history of credit, adjustment, and reversal transactions.",
)
def view_ledger_endpoint(
    db: DatabaseSession,
    reviewer: ReviewerAuth,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> List[RewardTransactionItem]:
    """Inspect system-wide ledger history."""
    entries = db.scalars(
        select(RewardLedger)
        .order_by(RewardLedger.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [RewardTransactionItem.model_validate(e) for e in entries]
