"""Auditable append-only rewards ledger and deterministic calculation engine."""

import math
from typing import List, Optional, Tuple
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import config
from app.db.models import Claim, EvidenceAuditLog, ItemReport, RewardLedger


def calculate_points(
    item_value: float,
    rate: Optional[float] = None,
) -> Tuple[float, int, bool, Optional[float]]:
    """Deterministically calculate eligible reward rupees and integer points."""
    clean_rate = rate if rate is not None else config.DEFAULT_REWARD_RATE
    raw_reward = item_value * clean_rate

    is_capped = False
    cap_value = None

    if raw_reward > config.MAX_REWARD_RUPEES:
        eligible_rupees = config.MAX_REWARD_RUPEES
        is_capped = True
        cap_value = config.MAX_REWARD_RUPEES
    elif raw_reward < config.MIN_REWARD_RUPEES:
        eligible_rupees = config.MIN_REWARD_RUPEES
    else:
        eligible_rupees = round(raw_reward, 2)

    points = math.floor(eligible_rupees * config.POINTS_PER_RUPEE)
    return eligible_rupees, points, is_capped, cap_value


def record_recovery_reward(
    db: Session,
    claim: Claim,
    verified_value: float,
    recipient_email: str,
    recipient_name: Optional[str],
    reviewer_label: str,
    notes: str,
    idempotency_key: Optional[str] = None,
) -> RewardLedger:
    """Record an immutable credit transaction in the append-only ledger."""
    clean_email = recipient_email.strip().lower()
    clean_idem = (idempotency_key or f"reward_found_{claim.found_report_id}_claim_{claim.id}").strip()

    # 1. Check idempotency key collision
    existing_key = db.scalars(
        select(RewardLedger).where(RewardLedger.idempotency_key == clean_idem)
    ).first()
    if existing_key is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transaction with idempotency key '{clean_idem}' has already been processed.",
        )

    # 2. Prevent duplicate reward credits for the same recovery
    existing_reward = db.scalars(
        select(RewardLedger).where(
            RewardLedger.found_report_id == claim.found_report_id,
            RewardLedger.transaction_type == "recovery_reward",
        )
    ).first()
    if existing_reward is not None:
        # Check if it was subsequently reversed
        reversal = db.scalars(
            select(RewardLedger).where(
                RewardLedger.reversal_ref == existing_reward.transaction_id
            )
        ).first()
        if reversal is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A reward transaction ({existing_reward.transaction_id}) has already been issued for this recovery.",
            )

    # 3. Calculate points
    eligible_rupees, points, _, _ = calculate_points(verified_value)

    # 4. Insert ledger entry
    entry = RewardLedger(
        transaction_id=str(uuid.uuid4()),
        idempotency_key=clean_idem,
        recipient_email=clean_email,
        recipient_name=recipient_name.strip() if recipient_name else None,
        found_report_id=claim.found_report_id,
        claim_id=claim.id,
        points=points,
        reward_rupees=eligible_rupees,
        verified_item_value=verified_value,
        reward_rate=config.DEFAULT_REWARD_RATE,
        points_per_rupee=config.POINTS_PER_RUPEE,
        transaction_type="recovery_reward",
        reviewer_label=reviewer_label,
        notes=notes.strip(),
    )
    db.add(entry)

    # 5. Audit entry on claim
    audit = EvidenceAuditLog(
        claim_id=claim.id,
        action="REWARD_CREDITED",
        actor_label=reviewer_label,
        notes=f"Credited {points} points (₹{eligible_rupees}) to {clean_email}. TxID: {entry.transaction_id}",
    )
    db.add(audit)

    db.commit()
    db.refresh(entry)
    return entry


def reverse_reward_transaction(
    db: Session,
    transaction_id: str,
    reviewer_label: str,
    reason: str,
) -> RewardLedger:
    """Safely reverse a previous reward transaction by creating an offsetting negative entry."""
    original = db.scalars(
        select(RewardLedger).where(RewardLedger.transaction_id == transaction_id)
    ).first()
    if original is None:
        raise HTTPException(status_code=404, detail=f"Transaction '{transaction_id}' not found.")

    if original.transaction_type != "recovery_reward":
        raise HTTPException(status_code=400, detail="Only 'recovery_reward' transactions can be reversed.")

    # Check if already reversed
    existing_reversal = db.scalars(
        select(RewardLedger).where(RewardLedger.reversal_ref == original.transaction_id)
    ).first()
    if existing_reversal is not None:
        raise HTTPException(status_code=400, detail="This transaction has already been reversed.")

    reversal_entry = RewardLedger(
        transaction_id=str(uuid.uuid4()),
        idempotency_key=f"rev_{original.transaction_id}_{uuid.uuid4().hex[:6]}",
        recipient_email=original.recipient_email,
        recipient_name=original.recipient_name,
        found_report_id=original.found_report_id,
        claim_id=original.claim_id,
        points=-original.points,
        reward_rupees=-original.reward_rupees,
        verified_item_value=original.verified_item_value,
        reward_rate=original.reward_rate,
        points_per_rupee=original.points_per_rupee,
        transaction_type="reversal",
        reviewer_label=reviewer_label,
        reversal_ref=original.transaction_id,
        notes=f"Reversal of {original.transaction_id}: {reason.strip()}",
    )
    db.add(reversal_entry)

    audit = EvidenceAuditLog(
        claim_id=original.claim_id,
        action="REWARD_REVERSED",
        actor_label=reviewer_label,
        notes=f"Reversed {original.points} points. Reversal TxID: {reversal_entry.transaction_id}. Reason: {reason.strip()}",
    )
    db.add(audit)

    db.commit()
    db.refresh(reversal_entry)
    return reversal_entry


def get_account_ledger_summary(
    db: Session,
    email: str,
) -> Tuple[int, float, int, List[RewardLedger]]:
    """Compute current points balance and fetch transaction history for an account."""
    clean_email = email.strip().lower()
    txs = db.scalars(
        select(RewardLedger)
        .where(RewardLedger.recipient_email == clean_email)
        .order_by(RewardLedger.created_at.desc())
    ).all()

    total_points = sum(t.points for t in txs)
    # Ensure balance doesn't display negative in UI
    net_points = max(0, total_points)
    est_rupees = round(net_points / config.POINTS_PER_RUPEE, 2)
    approved_count = len([t for t in txs if t.transaction_type == "recovery_reward"])

    return net_points, est_rupees, approved_count, txs
