
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from pathlib import Path

from app.db.database import Base, engine
from app.db import models  # Registers ItemReport with Base.metadata
from app.routers.reports import router as reports_router
from app.routers.images import router as images_router
from app.routers.claims import router as claims_router



@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="AI Lost & Found API",
    description="AI-assisted lost item discovery and recovery.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(reports_router)
app.include_router(images_router)
app.include_router(claims_router)

ROOT = Path(__file__).resolve().parents[1]
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
app.mount("/uploads", StaticFiles(directory=ROOT / "uploads", check_dir=False), name="uploads")
templates = Jinja2Templates(directory=ROOT / "app" / "templates")


@app.get("/", include_in_schema=False)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="home.html", context={"active": "home"})


@app.get("/browse", include_in_schema=False)
def browse_page(request: Request):
    return templates.TemplateResponse(request=request, name="browse.html", context={"active": "browse"})


@app.get("/report/{report_type}", include_in_schema=False)
def report_form_page(request: Request, report_type: str):
    if report_type not in {"lost", "found"}:
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request=request, name="report_form.html", context={"active": "report", "report_type": report_type})


@app.get("/reports/{report_id}", include_in_schema=False)
def report_detail_page(request: Request, report_id: int):
    return templates.TemplateResponse(request=request, name="detail.html", context={"active": "", "report_id": report_id})


@app.get("/reports/{report_id}/matches", include_in_schema=False)
def matches_page(request: Request, report_id: int):
    return templates.TemplateResponse(request=request, name="matches.html", context={"active": "", "report_id": report_id})


@app.get("/my-reports", include_in_schema=False)
def my_reports_page(request: Request):
    return templates.TemplateResponse(request=request, name="placeholder.html", context={"active": "", "page_title": "My reports", "message": "Personal report history requires sign-in, which this API does not currently provide."})


@app.get("/my-claims", include_in_schema=False)
def my_claims_page(request: Request):
    return templates.TemplateResponse(request=request, name="placeholder.html", context={"active": "", "page_title": "My claims", "message": "Claim submission is available on found report pages. A private claims inbox requires sign-in, which this API does not currently provide."})


@app.get("/help", include_in_schema=False)
def help_page(request: Request):
    return templates.TemplateResponse(request=request, name="help.html", context={"active": "help"})



@app.get("/api/health", tags=["System"])
def health_check():
    return {
        "status": "healthy",
        "service": "ai-lost-and-found",
        "version": "0.1.0",
    }
