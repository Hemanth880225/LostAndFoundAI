"""Service layer for Guest Finder, Anonymous Reporting, and Transit Recovery."""

import secrets
from datetime import date, datetime
from typing import List, Optional, Tuple
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Claim,
    ClaimHandoverRecord,
    GuestCoordinationMessage,
    GuestHandoverVerification,
    GuestRecoveryReport,
    ItemImage,
    ItemReport,
)
from app.extensions.guest_recovery.schemas import (
    AccountLinkResponse,
    CoordinationMessageCreate,
    CoordinationMessageResponse,
    GuestCaseDetailResponse,
    GuestFoundReportCreate,
    GuestLostReportCreate,
    GuestReportReceipt,
    HandoverCodeGenerateRequest,
    HandoverCodeResponse,
    HandoverConfirmationRequest,
    HandoverConfirmationResponse,
    PublicReportSafeView,
)
from app.routers.images import persist_image_and_embed, validate_image_file
from app.services.claim_service import complete_handover as core_complete_handover
from app.services.matching_service import get_or_create_text_embedding


SAFETY_NOTICE = (
    "SAFETY ADVISORY: Never agree to meet a stranger at a private residence, isolated area, or in the dark. "
    "Always carry out handovers at a well-lit, public, staffed facility such as a Railway Station Helpdesk, "
    "Police Help Post, Campus Security Office, or Metro Customer Assistance Counter."
)

ANONYMOUS_NOTICE = (
    "You have chosen to submit this report anonymously. Your contact information will NOT be stored or requested. "
    "To return this item safely, please deposit it at an official lost-and-found facility (e.g. Railway Station Master desk, "
    "Police Helpdesk, or Campus Security) or monitor this case page using your secure Case Reference."
)


def _generate_case_ref(prefix: str = "GF") -> str:
    """Generate a high-entropy, human-readable case reference (e.g. GF-9B2F-4A1C)."""
    p1 = secrets.token_hex(2).upper()
    p2 = secrets.token_hex(2).upper()
    return f"{prefix}-{p1}-{p2}"


def _generate_handover_code() -> str:
    """Generate a one-time, cryptographically secure handover confirmation code."""
    p1 = secrets.token_hex(2).upper()
    p2 = secrets.token_hex(2).upper()
    return f"HO-{p1}-{p2}"


async def create_guest_found_report(
    db: Session,
    payload: GuestFoundReportCreate,
    image_files: Optional[List[UploadFile]] = None,
    base_url: str = "",
) -> GuestReportReceipt:
    """Create a found-item report for a guest finder without requiring account creation."""
    ev_date = payload.event_date or date.today()

    # 1. Create the foundational ItemReport
    report = ItemReport(
        report_type="found",
        item_name=payload.item_name,
        category=payload.category,
        color=payload.color,
        brand=payload.brand,
        model=payload.model,
        description=payload.description,
        event_date=ev_date,
        location_text=payload.location_text,
        latitude=payload.latitude,
        longitude=payload.longitude,
        status="active",
        created_at=datetime.utcnow(),
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    # 2. Process and persist any attached images
    if image_files:
        for file in image_files:
            if hasattr(file, "filename") and file.filename:
                try:
                    contents, extension, content_type = await validate_image_file(file)
                    persist_image_and_embed(
                        db=db,
                        report_id=report.id,
                        contents=contents,
                        extension=extension,
                        content_type=content_type,
                        original_filename=file.filename,
                    )
                except Exception:
                    # Continue gracefully if an individual image validation fails
                    continue

    # 3. Create or reuse text embeddings
    try:
        get_or_create_text_embedding(db, report)
    except Exception:
        pass

    # 4. Generate secure case credentials
    case_ref = _generate_case_ref(prefix="GF")
    secret_key = secrets.token_hex(24)

    # 5. Persist GuestRecoveryReport metadata (private contents & contact details strictly isolated)
    guest_meta = GuestRecoveryReport(
        report_id=report.id,
        case_reference=case_ref,
        secret_key=secret_key,
        guest_role="finder",
        is_anonymous=payload.is_anonymous,
        contact_method=payload.contact_method if not payload.is_anonymous else "none",
        contact_value=payload.contact_value if not payload.is_anonymous else None,
        journey_type=payload.journey_type,
        pickup_location=payload.pickup_location,
        dropoff_location=payload.dropoff_location,
        vehicle_identifier=payload.vehicle_identifier,
        route_notes=payload.route_notes,
        approximate_time=payload.approximate_time or datetime.utcnow().strftime("%I:%M %p"),
        private_contents=payload.private_contents,
        distinctive_marks=payload.distinctive_marks,
        qr_source=payload.qr_source,
        preferred_handover_mode=payload.preferred_handover_mode,
        handover_facility_name=payload.handover_facility_name,
        created_at=datetime.utcnow(),
    )
    db.add(guest_meta)
    db.commit()
    db.refresh(guest_meta)

    # 6. Initialize coordination message thread
    init_text = ANONYMOUS_NOTICE if payload.is_anonymous else (
        "Your report has been submitted. Claimants can reach out via this secure coordination channel "
        "without seeing your personal phone number or email."
    )
    init_msg = GuestCoordinationMessage(
        guest_report_id=guest_meta.id,
        sender_role="system",
        message_text=init_text,
        is_safe_location_suggestion=payload.is_anonymous,
        created_at=datetime.utcnow(),
    )
    db.add(init_msg)
    db.commit()

    tracking_url = f"{base_url.rstrip('/')}/guest/case/{case_ref}?key={secret_key}"
    handover_advice = (
        "Deposit the item at an authorized station/police desk if you cannot hold it."
        if payload.is_anonymous
        else "Keep the item in a safe place until a claimant is verified."
    )

    return GuestReportReceipt(
        case_reference=case_ref,
        secret_key=secret_key,
        report_id=report.id,
        guest_role="finder",
        item_name=report.item_name,
        category=report.category,
        is_anonymous=payload.is_anonymous,
        journey_type=payload.journey_type,
        pickup_location=payload.pickup_location,
        dropoff_location=payload.dropoff_location,
        created_at=report.created_at,
        tracking_url=tracking_url,
        handover_advice=handover_advice,
        safety_guidance=SAFETY_NOTICE,
    )


async def create_guest_lost_report(
    db: Session,
    payload: GuestLostReportCreate,
    image_files: Optional[List[UploadFile]] = None,
    base_url: str = "",
) -> GuestReportReceipt:
    """Create a lost-item report for a passenger who does not know driver details."""
    ev_date = payload.event_date or date.today()

    report = ItemReport(
        report_type="lost",
        item_name=payload.item_name,
        category=payload.category,
        color=payload.color,
        brand=payload.brand,
        model=payload.model,
        description=payload.description,
        event_date=ev_date,
        location_text=payload.location_text,
        latitude=payload.latitude,
        longitude=payload.longitude,
        status="active",
        created_at=datetime.utcnow(),
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    if image_files:
        for file in image_files:
            if hasattr(file, "filename") and file.filename:
                try:
                    contents, extension, content_type = await validate_image_file(file)
                    persist_image_and_embed(
                        db=db,
                        report_id=report.id,
                        contents=contents,
                        extension=extension,
                        content_type=content_type,
                        original_filename=file.filename,
                    )
                except Exception:
                    continue

    try:
        get_or_create_text_embedding(db, report)
    except Exception:
        pass

    case_ref = _generate_case_ref(prefix="GL")
    secret_key = secrets.token_hex(24)

    guest_meta = GuestRecoveryReport(
        report_id=report.id,
        case_reference=case_ref,
        secret_key=secret_key,
        guest_role="passenger",
        is_anonymous=False,
        contact_method=payload.contact_method,
        contact_value=payload.contact_value,
        journey_type=payload.journey_type,
        pickup_location=payload.pickup_location,
        dropoff_location=payload.dropoff_location,
        vehicle_identifier=payload.vehicle_identifier,
        route_notes=payload.route_notes,
        approximate_time=payload.approximate_time,
        private_contents=payload.private_contents,
        distinctive_marks=payload.distinctive_marks,
        created_at=datetime.utcnow(),
    )
    db.add(guest_meta)
    db.commit()
    db.refresh(guest_meta)

    init_msg = GuestCoordinationMessage(
        guest_report_id=guest_meta.id,
        sender_role="system",
        message_text=(
            "Lost item report registered. When a matching found item is reported, "
            "you can verify ownership and coordinate handover safely through this portal."
        ),
        created_at=datetime.utcnow(),
    )
    db.add(init_msg)
    db.commit()

    tracking_url = f"{base_url.rstrip('/')}/guest/case/{case_ref}?key={secret_key}"

    return GuestReportReceipt(
        case_reference=case_ref,
        secret_key=secret_key,
        report_id=report.id,
        guest_role="passenger",
        item_name=report.item_name,
        category=report.category,
        is_anonymous=False,
        journey_type=payload.journey_type,
        pickup_location=payload.pickup_location,
        dropoff_location=payload.dropoff_location,
        created_at=report.created_at,
        tracking_url=tracking_url,
        handover_advice="Monitor your case page for possible transit matches.",
        safety_guidance=SAFETY_NOTICE,
    )


def authenticate_guest_case(
    db: Session,
    case_reference: str,
    secret_key: str,
) -> GuestRecoveryReport:
    """Validate case reference and secret key, returning the authorized GuestRecoveryReport."""
    meta = db.scalars(
        select(GuestRecoveryReport).where(GuestRecoveryReport.case_reference == case_reference.strip().upper())
    ).first()

    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_reference}' was not found.",
        )

    if not secrets.compare_digest(meta.secret_key, secret_key.strip()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid secret access key for this case.",
        )

    return meta


def get_guest_case_details(
    db: Session,
    case_reference: str,
    secret_key: str,
) -> GuestCaseDetailResponse:
    """Retrieve complete, authenticated case details including private info and messages."""
    meta = authenticate_guest_case(db, case_reference, secret_key)
    report = db.get(ItemReport, meta.report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Associated item report not found.")

    # Fetch images
    images = db.scalars(
        select(ItemImage).where(ItemImage.report_id == report.id).order_by(ItemImage.id.asc())
    ).all()
    image_urls = [f"/{img.image_path.lstrip('/')}" for img in images]

    # Fetch coordination messages
    msgs = db.scalars(
        select(GuestCoordinationMessage)
        .where(GuestCoordinationMessage.guest_report_id == meta.id)
        .order_by(GuestCoordinationMessage.id.asc())
    ).all()
    msg_responses = [
        CoordinationMessageResponse(
            id=m.id,
            sender_role=m.sender_role,
            message_text=m.message_text,
            is_safe_location_suggestion=m.is_safe_location_suggestion,
            created_at=m.created_at,
        )
        for m in msgs
    ]

    # Active handover verification
    active_handover = None
    hv = db.scalars(
        select(GuestHandoverVerification).where(GuestHandoverVerification.guest_report_id == meta.id)
    ).first()
    if hv:
        active_handover = HandoverCodeResponse(
            handover_code=hv.handover_code,
            claim_id=hv.claim_id,
            status=hv.status,
            agreed_location_type=hv.agreed_location_type,
            agreed_location_name=hv.agreed_location_name,
            agreed_location_address=hv.agreed_location_address,
            instructions="Present this code at the agreed staffed location. Do not share it over unverified phone calls.",
        )

    # Curated safe handover suggestions
    suggested_facilities = [
        {
            "name": "Railway Station Master & Help Desk",
            "type": "transit",
            "description": "24/7 staffed lost property and customer assistance desk.",
            "recommended": True,
        },
        {
            "name": "Local Police Station / Help Post",
            "type": "police",
            "description": "Statutory public custody with formal property intake receipt.",
            "recommended": True,
        },
        {
            "name": "Campus Security Command Desk",
            "type": "campus_security",
            "description": "Designated intake counter for college campus recoveries.",
            "recommended": True,
        },
    ]

    return GuestCaseDetailResponse(
        case_reference=meta.case_reference,
        report_id=report.id,
        guest_role=meta.guest_role,
        item_name=report.item_name,
        category=report.category,
        color=report.color,
        brand=report.brand,
        model=report.model,
        public_description=report.description,
        location_text=report.location_text,
        latitude=report.latitude,
        longitude=report.longitude,
        event_date=report.event_date,
        approximate_time=meta.approximate_time,
        journey_type=meta.journey_type,
        pickup_location=meta.pickup_location,
        dropoff_location=meta.dropoff_location,
        vehicle_identifier=meta.vehicle_identifier,
        route_notes=meta.route_notes,
        is_anonymous=meta.is_anonymous,
        contact_method=meta.contact_method,
        contact_value=meta.contact_value,
        private_contents=meta.private_contents,
        distinctive_marks=meta.distinctive_marks,
        preferred_handover_mode=meta.preferred_handover_mode,
        handover_facility_name=meta.handover_facility_name,
        linked_account_email=meta.linked_account_email,
        report_status=report.status,
        created_at=report.created_at,
        images=image_urls,
        messages=msg_responses,
        active_handover=active_handover,
        suggested_handover_facilities=suggested_facilities,
    )


def post_coordination_message(
    db: Session,
    case_reference: str,
    secret_key: str,
    payload: CoordinationMessageCreate,
    sender_role: str = "finder",
) -> CoordinationMessageResponse:
    """Send a privacy-preserving message inside the case's coordination channel."""
    meta = authenticate_guest_case(db, case_reference, secret_key)

    msg = GuestCoordinationMessage(
        guest_report_id=meta.id,
        sender_role=sender_role,
        message_text=payload.message_text.strip(),
        is_safe_location_suggestion=payload.is_safe_location_suggestion,
        created_at=datetime.utcnow(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    return CoordinationMessageResponse(
        id=msg.id,
        sender_role=msg.sender_role,
        message_text=msg.message_text,
        is_safe_location_suggestion=msg.is_safe_location_suggestion,
        created_at=msg.created_at,
    )


def issue_handover_code(
    db: Session,
    case_reference: str,
    secret_key: str,
    payload: HandoverCodeGenerateRequest,
) -> HandoverCodeResponse:
    """Generate a one-time handover confirmation code after claim verification."""
    meta = authenticate_guest_case(db, case_reference, secret_key)

    # Verify claim exists and targets this report
    claim = db.get(Claim, payload.claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found.")

    if claim.found_report_id != meta.report_id:
        raise HTTPException(
            status_code=400,
            detail="Specified claim does not correspond to this found item report.",
        )

    # Check for existing handover verification
    existing = db.scalars(
        select(GuestHandoverVerification).where(GuestHandoverVerification.guest_report_id == meta.id)
    ).first()

    code = _generate_handover_code() if not existing else existing.handover_code

    if not existing:
        hv = GuestHandoverVerification(
            guest_report_id=meta.id,
            claim_id=claim.id,
            handover_code=code,
            status="code_issued",
            agreed_location_type=payload.agreed_location_type,
            agreed_location_name=payload.agreed_location_name,
            agreed_location_address=payload.agreed_location_address,
            created_at=datetime.utcnow(),
        )
        db.add(hv)
    else:
        existing.agreed_location_type = payload.agreed_location_type
        existing.agreed_location_name = payload.agreed_location_name
        existing.agreed_location_address = payload.agreed_location_address
        existing.status = "code_issued"
        hv = existing

    # Post system message into thread
    loc_info = f"{payload.agreed_location_name} ({payload.agreed_location_type.replace('_', ' ').title()})"
    sys_msg = GuestCoordinationMessage(
        guest_report_id=meta.id,
        claim_id=claim.id,
        sender_role="system",
        message_text=(
            f"Handover scheduled at: {loc_info}. Handover Code issued. "
            "Meet at the public, staffed desk and verify the item in person before confirming."
        ),
        is_safe_location_suggestion=True,
        created_at=datetime.utcnow(),
    )
    db.add(sys_msg)
    db.commit()

    return HandoverCodeResponse(
        handover_code=code,
        claim_id=claim.id,
        status="code_issued",
        agreed_location_type=payload.agreed_location_type,
        agreed_location_name=payload.agreed_location_name,
        agreed_location_address=payload.agreed_location_address,
        instructions="Exchange this one-time code only at the agreed public location.",
    )


def confirm_handover(
    db: Session,
    case_reference: str,
    secret_key: str,
    payload: HandoverConfirmationRequest,
) -> HandoverConfirmationResponse:
    """Validate handover code and mark the recovery as completed."""
    meta = authenticate_guest_case(db, case_reference, secret_key)

    hv = db.scalars(
        select(GuestHandoverVerification).where(GuestHandoverVerification.guest_report_id == meta.id)
    ).first()

    if not hv:
        raise HTTPException(status_code=404, detail="No active handover verification for this case.")

    if not secrets.compare_digest(hv.handover_code.strip().upper(), payload.handover_code.strip().upper()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect handover verification code.",
        )

    if hv.status == "completed":
        return HandoverConfirmationResponse(
            success=True,
            handover_code=hv.handover_code,
            status="completed",
            completed_at=hv.completed_at,
            message="Handover was already confirmed completed.",
        )

    # Update verification
    if payload.confirmed_by == "finder":
        hv.confirmed_by_finder = True
    else:
        hv.confirmed_by_claimant = True

    hv.status = "completed"
    hv.completed_at = datetime.utcnow()

    # Update underlying ItemReport and Claim
    report = db.get(ItemReport, meta.report_id)
    if report:
        report.status = "returned"

    claim = db.get(Claim, hv.claim_id)
    if claim:
        claim.status = "completed"

        # Record ClaimHandoverRecord if not already present
        existing_hr = db.scalars(
            select(ClaimHandoverRecord).where(ClaimHandoverRecord.claim_id == claim.id)
        ).first()
        if not existing_hr:
            hr = ClaimHandoverRecord(
                claim_id=claim.id,
                handover_note=payload.notes or f"Verified safe transit handover at {hv.agreed_location_name}.",
                reviewer_label="guest_transit_handover",
                handed_over_at=datetime.utcnow(),
            )
            db.add(hr)

    # Post completion system message
    db.add(GuestCoordinationMessage(
        guest_report_id=meta.id,
        claim_id=hv.claim_id,
        sender_role="system",
        message_text=f"Handover successfully confirmed completed at {hv.agreed_location_name}. Recovery concluded.",
        created_at=datetime.utcnow(),
    ))
    db.commit()

    return HandoverConfirmationResponse(
        success=True,
        handover_code=hv.handover_code,
        status="completed",
        completed_at=hv.completed_at,
        message="Recovery successfully completed. Safe handover recorded.",
    )


def link_guest_account(
    db: Session,
    case_reference: str,
    secret_key: str,
    email: str,
    full_name: Optional[str] = None,
) -> AccountLinkResponse:
    """Link a verified email account to an anonymous or guest case for reward eligibility."""
    meta = authenticate_guest_case(db, case_reference, secret_key)

    clean_email = email.strip().lower()
    meta.linked_account_email = clean_email
    meta.linked_at = datetime.utcnow()
    db.commit()

    return AccountLinkResponse(
        success=True,
        case_reference=meta.case_reference,
        linked_account_email=clean_email,
        reward_eligibility="eligible_after_handover",
        message=(
            f"Account {clean_email} linked successfully. Once item recovery is verified and completed, "
            "value-based reward points can be credited to this account."
        ),
    )


def get_public_safe_report(
    db: Session,
    report_id: int,
) -> PublicReportSafeView:
    """Return a public view of a report that strictly omits private contents and contacts."""
    report = db.get(ItemReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")

    meta = db.scalars(
        select(GuestRecoveryReport).where(GuestRecoveryReport.report_id == report.id)
    ).first()

    images_count = db.scalars(
        select(ItemImage).where(ItemImage.report_id == report.id)
    ).all()

    return PublicReportSafeView(
        id=report.id,
        report_type=report.report_type,
        item_name=report.item_name,
        category=report.category,
        color=report.color,
        brand=report.brand,
        model=report.model,
        description=report.description,  # General public description only
        event_date=report.event_date,
        location_text=report.location_text,
        journey_type=meta.journey_type if meta else None,
        pickup_location=meta.pickup_location if meta else None,
        dropoff_location=meta.dropoff_location if meta else None,
        approximate_time=meta.approximate_time if meta else None,
        image_count=len(images_count),
        status=report.status,
    )
