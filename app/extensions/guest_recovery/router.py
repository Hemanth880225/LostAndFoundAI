"""API Router for Guest Finder, Anonymous Reporting, Transit Matching, and Handover."""

import json
from datetime import date
from typing import Annotated, List, Optional
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.extensions.guest_recovery.matching import find_guest_matches
from app.extensions.guest_recovery.qr import (
    build_transit_destination_url,
    generate_qr_svg,
)
from app.extensions.guest_recovery.schemas import (
    AccountLinkRequest,
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
    TransitQRConfigResponse,
)
from app.extensions.guest_recovery.service import (
    SAFETY_NOTICE,
    confirm_handover,
    create_guest_found_report,
    create_guest_lost_report,
    get_guest_case_details,
    get_public_safe_report,
    issue_handover_code,
    link_guest_account,
    post_coordination_message,
)

router = APIRouter(
    prefix="/api/guest",
    tags=["Guest & Transit Recovery"],
)

DatabaseSession = Annotated[Session, Depends(get_db)]


def _extract_secret_key(
    request: Request,
    key_query: Optional[str] = None,
    x_guest_key: Optional[str] = None,
) -> str:
    """Extract guest secret key from query parameter or X-Guest-Key header."""
    key = x_guest_key or key_query or request.headers.get("X-Guest-Key")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required secret key. Provide 'key' in query params or 'X-Guest-Key' in headers.",
        )
    return key.strip()


@router.post(
    "/found",
    response_model=GuestReportReceipt,
    status_code=status.HTTP_201_CREATED,
    summary="Guest finder reports a found item",
)
async def submit_guest_found_endpoint(
    request: Request,
    db: DatabaseSession,
    files: List[UploadFile] = File(default=[]),
):
    """
    Submit a found item report as a guest without creating an account.
    Supports either JSON payload or multipart/form-data with photos.
    """
    content_type = request.headers.get("content-type", "")
    all_files = list(files) if files else []

    if "multipart/form-data" in content_type:
        form = await request.form()
        # Collect any files sent under 'files', 'file', 'images', 'image'
        for k in ("files", "file", "images", "image"):
            for v in form.getlist(k):
                if hasattr(v, "filename") and hasattr(v, "read") and v not in all_files:
                    all_files.append(v)

        def form_str(k: str) -> Optional[str]:
            v = form.get(k)
            return str(v).strip() if v is not None and str(v).strip() != "" else None

        ev_date = None
        ev_date_str = form_str("event_date")
        if ev_date_str:
            try:
                ev_date = date.fromisoformat(ev_date_str)
            except ValueError:
                pass

        is_anon = form_str("is_anonymous")
        is_anon_bool = is_anon is not None and is_anon.lower() in ("true", "1", "yes")

        lat_val = form_str("latitude")
        long_val = form_str("longitude")

        payload = GuestFoundReportCreate(
            item_name=form_str("item_name") or "Found Belonging",
            category=form_str("category") or "Personal Items",
            description=form_str("description") or "Item found while travelling.",
            color=form_str("color"),
            brand=form_str("brand"),
            model=form_str("model"),
            location_text=form_str("location_text") or "Transit location",
            latitude=float(lat_val) if lat_val else None,
            longitude=float(long_val) if long_val else None,
            event_date=ev_date,
            approximate_time=form_str("approximate_time"),
            journey_type=form_str("journey_type"),
            pickup_location=form_str("pickup_location"),
            dropoff_location=form_str("dropoff_location"),
            vehicle_identifier=form_str("vehicle_identifier"),
            route_notes=form_str("route_notes"),
            is_anonymous=is_anon_bool,
            contact_method=form_str("contact_method") or "none",
            contact_value=form_str("contact_value"),
            private_contents=form_str("private_contents"),
            distinctive_marks=form_str("distinctive_marks"),
            qr_source=form_str("qr_source"),
            preferred_handover_mode=form_str("preferred_handover_mode") or "official_facility",
            handover_facility_name=form_str("handover_facility_name"),
        )
    else:
        # JSON body
        body = await request.json()
        payload = GuestFoundReportCreate(**body)

    base_url = str(request.base_url)
    return await create_guest_found_report(
        db=db,
        payload=payload,
        image_files=all_files,
        base_url=base_url,
    )


@router.post(
    "/lost",
    response_model=GuestReportReceipt,
    status_code=status.HTTP_201_CREATED,
    summary="Passenger reports a lost item as a guest",
)
async def submit_guest_lost_endpoint(
    request: Request,
    db: DatabaseSession,
    files: List[UploadFile] = File(default=[]),
):
    """
    Submit a lost-item report as a passenger without knowing the driver's identity.
    Supports either JSON payload or multipart/form-data.
    """
    content_type = request.headers.get("content-type", "")
    all_files = list(files) if files else []

    if "multipart/form-data" in content_type:
        form = await request.form()
        for k in ("files", "file", "images", "image"):
            for v in form.getlist(k):
                if hasattr(v, "filename") and hasattr(v, "read") and v not in all_files:
                    all_files.append(v)

        def form_str(k: str) -> Optional[str]:
            v = form.get(k)
            return str(v).strip() if v is not None and str(v).strip() != "" else None

        ev_date = None
        ev_date_str = form_str("event_date")
        if ev_date_str:
            try:
                ev_date = date.fromisoformat(ev_date_str)
            except ValueError:
                pass

        lat_val = form_str("latitude")
        long_val = form_str("longitude")

        payload = GuestLostReportCreate(
            item_name=form_str("item_name") or "Lost Belonging",
            category=form_str("category") or "Personal Items",
            description=form_str("description") or "Item left behind in transit.",
            color=form_str("color"),
            brand=form_str("brand"),
            model=form_str("model"),
            location_text=form_str("location_text") or "Transit route",
            latitude=float(lat_val) if lat_val else None,
            longitude=float(long_val) if long_val else None,
            event_date=ev_date,
            approximate_time=form_str("approximate_time"),
            journey_type=form_str("journey_type"),
            pickup_location=form_str("pickup_location"),
            dropoff_location=form_str("dropoff_location"),
            vehicle_identifier=form_str("vehicle_identifier"),
            route_notes=form_str("route_notes"),
            contact_method=form_str("contact_method") or "email",
            contact_value=form_str("contact_value"),
            private_contents=form_str("private_contents"),
            distinctive_marks=form_str("distinctive_marks"),
        )
    else:
        body = await request.json()
        payload = GuestLostReportCreate(**body)

    base_url = str(request.base_url)
    return await create_guest_lost_report(
        db=db,
        payload=payload,
        image_files=all_files,
        base_url=base_url,
    )


@router.get(
    "/cases/{case_reference}",
    response_model=GuestCaseDetailResponse,
    summary="Get authenticated guest case details",
)
def get_case_endpoint(
    case_reference: str,
    request: Request,
    db: DatabaseSession,
    key: Optional[str] = Query(default=None),
    x_guest_key: Optional[str] = Header(default=None),
):
    """Retrieve full details of a guest case using the secret access key."""
    secret_key = _extract_secret_key(request, key, x_guest_key)
    return get_guest_case_details(db, case_reference, secret_key)


@router.post(
    "/cases/{case_reference}/messages",
    response_model=CoordinationMessageResponse,
    summary="Post privacy-preserving coordination message",
)
def post_message_endpoint(
    case_reference: str,
    payload: CoordinationMessageCreate,
    request: Request,
    db: DatabaseSession,
    key: Optional[str] = Query(default=None),
    x_guest_key: Optional[str] = Header(default=None),
    role: str = Query(default="finder"),
):
    """Send a coordination message between finder and claimant without exposing phone numbers."""
    secret_key = _extract_secret_key(request, key, x_guest_key)
    sender_role = "claimant" if role == "claimant" else "finder"
    return post_coordination_message(db, case_reference, secret_key, payload, sender_role=sender_role)


@router.post(
    "/cases/{case_reference}/handover/generate-code",
    response_model=HandoverCodeResponse,
    summary="Generate one-time handover confirmation code",
)
def generate_handover_code_endpoint(
    case_reference: str,
    payload: HandoverCodeGenerateRequest,
    request: Request,
    db: DatabaseSession,
    key: Optional[str] = Query(default=None),
    x_guest_key: Optional[str] = Header(default=None),
):
    """Generate a one-time handover code for a verified claimant at a safe public location."""
    secret_key = _extract_secret_key(request, key, x_guest_key)
    return issue_handover_code(db, case_reference, secret_key, payload)


@router.post(
    "/cases/{case_reference}/handover/confirm",
    response_model=HandoverConfirmationResponse,
    summary="Confirm handover completion using code",
)
def confirm_handover_endpoint(
    case_reference: str,
    payload: HandoverConfirmationRequest,
    request: Request,
    db: DatabaseSession,
    key: Optional[str] = Query(default=None),
    x_guest_key: Optional[str] = Header(default=None),
):
    """Validate one-time handover code and mark the recovery as completed."""
    secret_key = _extract_secret_key(request, key, x_guest_key)
    return confirm_handover(db, case_reference, secret_key, payload)


@router.post(
    "/cases/{case_reference}/link-account",
    response_model=AccountLinkResponse,
    summary="Link verified account for reward eligibility",
)
def link_account_endpoint(
    case_reference: str,
    payload: AccountLinkRequest,
    request: Request,
    db: DatabaseSession,
    key: Optional[str] = Query(default=None),
    x_guest_key: Optional[str] = Header(default=None),
):
    """Link an email address to a guest case so the finder can receive reward points upon recovery."""
    secret_key = _extract_secret_key(request, key, x_guest_key)
    return link_guest_account(db, case_reference, secret_key, payload.email, payload.full_name)


@router.get(
    "/reports/{report_id}/safe",
    response_model=PublicReportSafeView,
    summary="Get sanitized public view of a report",
)
def get_safe_report_endpoint(
    report_id: int,
    db: DatabaseSession,
):
    """Public report view with sensitive interior contents and contact information strictly omitted."""
    return get_public_safe_report(db, report_id)


@router.get(
    "/matches/{report_id}",
    summary="Find journey and time-aware match candidates",
)
def get_guest_matches_endpoint(
    report_id: int,
    db: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    min_score: Annotated[float, Query(ge=0.0, le=100.0)] = 30.0,
):
    """Evaluate candidate reports considering CLIP embeddings, journey type, route, and time."""
    return find_guest_matches(db, report_id, limit=limit, min_score=min_score)


@router.get(
    "/transit/qr-config",
    response_model=TransitQRConfigResponse,
    summary="Generate transit QR code and destination URL",
)
def get_transit_qr_endpoint(
    request: Request,
    provider: str = Query(default="PuneAutoUnion", description="Identifier of the transport provider or union"),
    hub: str = Query(default="PuneRailwayStation", description="Name of the hub, stand, or travel terminal"),
):
    """Generate configurable QR landing destination and pure Python vector SVG."""
    base_url = str(request.base_url)
    dest_url = build_transit_destination_url(base_url, provider_id=provider, hub_name=hub)
    svg_data = generate_qr_svg(dest_url, box_size=8, border=3)

    return TransitQRConfigResponse(
        provider_id=provider,
        provider_name=provider.replace("_", " ").title(),
        hub_name=hub.replace("_", " ").title(),
        destination_url=dest_url,
        qr_svg=svg_data,
        safety_notice="Park vehicle safely before scanning or submitting reports. Do not operate phone while driving.",
    )
