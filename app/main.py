
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db.database import Base, engine
from app.db import models  # Register SQLAlchemy models
from app.routers.reports import router as reports_router
from app.routers.images import router as images_router
from app.routers.claims import router as claims_router
from app.extensions.safe_handover.router import router as handover_router
from app.extensions.claims_verification.router import router as claims_verification_router
from app.extensions.admin_review.router import router as admin_review_router
from app.extensions.rewards.router import router as rewards_router
from app.extensions.guest_recovery.router import router as guest_recovery_router
from app.extensions.product_links.router import router as product_links_router
from app.extensions.campus.router import router as campus_router
from app.extensions.attribute_matching.router import router as attribute_matching_router
from app.extensions.attribute_matching.models import ItemAttributeRecord  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"
UPLOADS_DIR = ROOT / "uploads"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database tables when the application starts and run safe migrations."""
    Base.metadata.create_all(bind=engine)
    try:
        with engine.connect() as conn:
            cursor = conn.connection.cursor()
            cursor.execute("PRAGMA table_info(item_images)")
            columns = [row[1] for row in cursor.fetchall()]
            if columns and "original_filename" not in columns:
                cursor.execute(
                    "ALTER TABLE item_images ADD COLUMN original_filename VARCHAR(255)"
                )
                conn.connection.commit()
    except Exception:
        pass
    yield


app = FastAPI(
    title="AI Lost & Found API",
    description="AI-assisted lost item discovery and recovery.",
    version="0.1.0",
    lifespan=lifespan,
)

# Existing backend API routers — preserve these.
app.include_router(reports_router)
app.include_router(images_router)
app.include_router(claims_router)
app.include_router(handover_router)
app.include_router(claims_verification_router)
app.include_router(admin_review_router)
app.include_router(rewards_router)
app.include_router(guest_recovery_router)
app.include_router(product_links_router)
app.include_router(campus_router)
app.include_router(attribute_matching_router)

# Frontend static assets and uploaded images.
app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static",
)
app.mount(
    "/uploads",
    StaticFiles(directory=UPLOADS_DIR, check_dir=False),
    name="uploads",
)

templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.get("/", include_in_schema=False)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"active": "home"},
    )


@app.get("/browse", include_in_schema=False)
def browse_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="browse.html",
        context={"active": "browse"},
    )


@app.get("/search/image", include_in_schema=False)
def image_search_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="image_search.html",
        context={"active": "image-search"},
    )


@app.get("/travel-handover", include_in_schema=False)
def travel_handover_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="travel_handover.html",
        context={"active": "travel-handover"},
    )


@app.get("/report/{report_type}", include_in_schema=False)

def report_form_page(request: Request, report_type: str):
    if report_type not in {"lost", "found"}:
        raise HTTPException(status_code=404)

    return templates.TemplateResponse(
        request=request,
        name="report_form.html",
        context={
            "active": "report",
            "report_type": report_type,
        },
    )


@app.get("/reports/{report_id}", include_in_schema=False)
def report_detail_page(request: Request, report_id: int):
    return templates.TemplateResponse(
        request=request,
        name="detail.html",
        context={
            "active": "",
            "report_id": report_id,
        },
    )


@app.get("/reports/{report_id}/matches", include_in_schema=False)
def matches_page(request: Request, report_id: int):
    return templates.TemplateResponse(
        request=request,
        name="matches.html",
        context={
            "active": "",
            "report_id": report_id,
        },
    )


@app.get("/my-reports", include_in_schema=False)
def my_reports_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="my_reports.html",
        context={"active": "my-reports"},
    )


@app.get("/my-claims", include_in_schema=False)
def my_claims_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="my_claims.html",
        context={"active": "my-claims"},
    )


@app.get("/claims/{claim_id}", include_in_schema=False)
def claim_status_page(request: Request, claim_id: int):
    return templates.TemplateResponse(
        request=request,
        name="claim_status.html",
        context={"active": "claims", "claim_id": claim_id},
    )


@app.get("/admin/review", include_in_schema=False)
def admin_review_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="admin_review.html",
        context={"active": "admin-review"},
    )


@app.get("/rewards", include_in_schema=False)
def rewards_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="rewards.html",
        context={"active": "rewards"},
    )


@app.get("/guest/found", include_in_schema=False)
def guest_found_page(request: Request, provider: str | None = None, hub: str | None = None):
    return templates.TemplateResponse(
        request=request,
        name="guest_found.html",
        context={"active": "guest-found", "provider": provider or "", "hub": hub or ""},
    )


@app.get("/guest/lost", include_in_schema=False)
def guest_lost_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="guest_lost.html",
        context={"active": "guest-lost"},
    )


@app.get("/guest/case/{case_reference}", include_in_schema=False)
def guest_case_page(request: Request, case_reference: str, key: str | None = None):
    return templates.TemplateResponse(
        request=request,
        name="guest_case.html",
        context={"active": "guest-case", "case_reference": case_reference, "initial_key": key or ""},
    )


@app.get("/transit/qr", include_in_schema=False)
def transit_qr_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="transit_qr.html",
        context={"active": "transit-qr"},
    )


@app.get("/help", include_in_schema=False)
def help_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="help.html",
        context={"active": "help"},
    )


@app.get("/api/health", tags=["System"])
def health_check():
    return {
        "status": "healthy",
        "service": "ai-lost-and-found",
        "version": "0.1.0",
    }
