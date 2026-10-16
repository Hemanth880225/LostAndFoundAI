
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import ItemImage, ItemReport
from app.services.matching_service import find_matches

router = APIRouter(
    prefix="/api/reports",
    tags=["Reports"],
)



class ItemReportCreate(BaseModel):
    report_type: Literal["lost", "found"]
    item_name: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=2, max_length=80)

    color: str | None = Field(default=None, max_length=50)
    brand: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)

    description: str = Field(min_length=5, max_length=2000)
    event_date: date
    location_text: str = Field(min_length=2, max_length=255)

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_coordinates(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError(
                "Latitude and longitude must be provided together."
            )
        return self


class ItemReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_type: Literal["lost", "found"]
    item_name: str
    category: str
    color: str | None
    brand: str | None
    model: str | None
    description: str
    event_date: date
    location_text: str
    latitude: float | None
    longitude: float | None
    status: str
    created_at: datetime


@router.post("", response_model=ItemReportResponse, status_code=status.HTTP_201_CREATED)
def create_report(payload: ItemReportCreate, db: Session = Depends(get_db)):
    report = ItemReport(**payload.model_dump())
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


@router.get("", response_model=list[ItemReportResponse])
def list_reports(
    report_type: Literal["lost", "found"] | None = None,
    category: str | None = None,
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    statement = select(ItemReport).where(ItemReport.status == "active")
    if report_type:
        statement = statement.where(ItemReport.report_type == report_type)
    if category:
        statement = statement.where(func.lower(ItemReport.category) == category.lower())
    statement = statement.order_by(ItemReport.created_at.desc()).offset(offset).limit(limit)
    return db.scalars(statement).all()


@router.get("/{report_id}", response_model=ItemReportResponse)
def get_report(report_id: int, db: Session = Depends(get_db)):
    report = db.get(ItemReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return report


@router.get("/{report_id}/matches")
def report_matches(
    report_id: int,
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    try:
        return find_matches(db, report_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
