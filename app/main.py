
from contextlib import asynccontextmanager

from fastapi import FastAPI

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
app.include_router(reports_router)
app.include_router(images_router)
app.include_router(claims_router)



@app.get("/api/health", tags=["System"])
def health_check():
    return {
        "status": "healthy",
        "service": "ai-lost-and-found",
        "version": "0.1.0",
    }
