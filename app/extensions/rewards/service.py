"""Service layer orchestrating recovery reward validation, policy enforcement, and account balances."""

from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core import config
from app.db.models import Claim, ItemReport, RewardLedger
from app.extensions.rewards.ledger import (
    calculate_points,
    get_account_ledger_summary,
    record_recovery_reward,
    reverse_reward_transaction,
)
from app.extensions.rewards.schemas import (
    AccountBalanceResponse,
    CreditRewardRequest,
    ReverseRewardRequest,
    RewardCalculationResponse,
    RewardPolicyResponse,
    RewardTransactionItem,
)

POLICY_DISCLAIMER = (
    "Reward points represent merit recognition under college lost-and-found guidelines. "
    "Points are calculated as 5 points per ₹1 of eligible recovery reward value. "
    "Points are NOT a banking deposit, cash wallet, or guaranteed financial instrument."
)

POLICY_FORMULA = (
    "eligible_reward_rupees = clamp(verified_item_value * 10%, min=₹50, max=₹2,000)\n"
    "points_awarded = floor(eligible_reward_rupees * 5 points/₹1)"
)


def get_current_policy() -> RewardPolicyResponse:
    """Return the active rewards policy configuration."""
    return RewardPolicyResponse(
        points_per_rupee=config.POINTS_PER_RUPEE,
        default_reward_rate=config.DEFAULT_REWARD_RATE,
        min_reward_rupees=config.MIN_REWARD_RUPEES,
        max_reward_rupees=config.MAX_REWARD_RUPEES,
        max_unverified_value_cap=config.MAX_UNVERIFIED_VALUE_CAP,
        formula=POLICY_FORMULA,
        programme_disclaimer=POLICY_DISCLAIMER,
    )


def simulate_reward_preview(
    item_value: float,
    custom_rate: Optional[float] = None,
) -> RewardCalculationResponse:
    """Calculate reward points preview for an item value."""
    rate = custom_rate or config.DEFAULT_REWARD_RATE
    eligible_rupees, points, is_capped, cap_value = calculate_points(item_value, rate)
    return RewardCalculationResponse(
        verified_item_value=item_value,
        reward_rate=rate,
        eligible_reward_rupees=eligible_rupees,
        points_awarded=points,
        points_per_rupee=config.POINTS_PER_RUPEE,
        is_capped=is_capped,
        cap_applied_rupees=cap_value,
    )


def validate_and_credit_recovery_reward(
    db: Session,
    payload: CreditRewardRequest,
    reviewer_label: str,
) -> RewardLedger:
    """Enforce strict handover completion and anti-collusion before crediting points."""
    # 1. Fetch claim
    claim = db.get(Claim, payload.claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")

    # 2. Strict Requirement: Item must have completed physical return
    if claim.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Reward cannot be awarded. Claim #{claim.id} is currently '{claim.status}'. "
                "Points may ONLY be credited after physical handover is completed and recorded."
            ),
        )

    # 3. Anti-abuse: Claimant cannot be rewarded for finding their own claimed item
    if claim.contact_email.strip().lower() == payload.recipient_email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Self-awarding is prohibited: Claimant email cannot be the reward recipient.",
        )

    # 4. Record ledger transaction
    return record_recovery_reward(
        db=db,
        claim=claim,
        verified_value=payload.verified_item_value,
        recipient_email=payload.recipient_email,
        recipient_name=payload.recipient_name,
        reviewer_label=reviewer_label,
        notes=payload.notes,
        idempotency_key=payload.idempotency_key,
    )


def validate_and_reverse_reward(
    db: Session,
    payload: ReverseRewardRequest,
    reviewer_label: str,
) -> RewardLedger:
    """Reverse a previous reward with full audit logging."""
    return reverse_reward_transaction(
        db=db,
        transaction_id=payload.transaction_id,
        reviewer_label=reviewer_label,
        reason=payload.reason,
    )


def get_user_balance_response(
    db: Session,
    email: str,
) -> AccountBalanceResponse:
    """Retrieve points balance and transaction history for an account."""
    clean_email = email.strip().lower()
    total_pts, est_rupees, count, txs = get_account_ledger_summary(db=db, email=clean_email)

    items = [
        RewardTransactionItem(
            transaction_id=t.transaction_id,
            points=t.points,
            reward_rupees=t.reward_rupees,
            verified_item_value=t.verified_item_value,
            transaction_type=t.transaction_type,
            found_report_id=t.found_report_id,
            claim_id=t.claim_id,
            reviewer_label=t.reviewer_label,
            notes=t.notes,
            created_at=t.created_at,
        )
        for t in txs
    ]

    return AccountBalanceResponse(
        recipient_email=clean_email,
        total_points=total_pts,
        estimated_programme_value_rupees=est_rupees,
        points_per_rupee=config.POINTS_PER_RUPEE,
        approved_rewards_count=count,
        transactions=items,
        programme_notice=POLICY_DISCLAIMER,
    )
