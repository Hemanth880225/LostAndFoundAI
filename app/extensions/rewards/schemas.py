"""Schemas for Value-Based Reward Points, Policy, and Ledger."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RewardPolicyResponse(BaseModel):
    """Configuration parameters and rules governing reward points."""
    points_per_rupee: int
    default_reward_rate: float
    min_reward_rupees: float
    max_reward_rupees: float
    max_unverified_value_cap: float
    formula: str
    programme_disclaimer: str


class RewardCalculationRequest(BaseModel):
    """Payload to simulate or preview reward points for an item value."""
    item_value: float = Field(gt=0.0, description="Estimated or verified item retail value in INR")
    custom_rate: Optional[float] = Field(default=None, ge=0.01, le=0.50, description="Optional custom reward percentage (e.g. 0.10 for 10%)")


class RewardCalculationResponse(BaseModel):
    """Computed reward preview based on current policy."""
    verified_item_value: float
    reward_rate: float
    eligible_reward_rupees: float
    points_awarded: int
    points_per_rupee: int
    is_capped: bool
    cap_applied_rupees: Optional[float] = None


class CreditRewardRequest(BaseModel):
    """Payload for an authorized reviewer to credit points after verified recovery."""
    claim_id: int = Field(gt=0, description="ID of the completed claim")
    verified_item_value: float = Field(gt=0.0, description="Verified item value in INR agreed during review")
    recipient_email: EmailStr = Field(description="Email of the finder/helper receiving the reward")
    recipient_name: Optional[str] = Field(default=None, max_length=120, description="Name of the finder")
    notes: str = Field(min_length=5, max_length=1000, description="Reviewer justification or valuation source")
    idempotency_key: Optional[str] = Field(default=None, max_length=100, description="Unique client transaction key to prevent duplicate credits")


class ReverseRewardRequest(BaseModel):
    """Payload to reverse a previously credited reward transaction with full audit."""
    transaction_id: str = Field(..., description="UUID of the original transaction to reverse")
    reason: str = Field(min_length=5, max_length=1000, description="Factual justification for transaction reversal")


class RewardTransactionItem(BaseModel):
    """Auditable ledger entry representation."""
    model_config = ConfigDict(from_attributes=True)

    transaction_id: str
    points: int
    reward_rupees: float
    verified_item_value: float
    transaction_type: str
    found_report_id: int
    claim_id: int
    reviewer_label: str
    notes: str
    created_at: datetime


class AccountBalanceResponse(BaseModel):
    """Summary of student/helper reward points and history."""
    recipient_email: str
    total_points: int
    estimated_programme_value_rupees: float
    points_per_rupee: int
    approved_rewards_count: int
    transactions: List[RewardTransactionItem]
    programme_notice: str = "Reward points represent program recognition value under college policy, not a cash bank balance."
