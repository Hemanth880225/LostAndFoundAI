
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ItemReport
from app.schemas.reports import ItemReportCreate


def create_report(
    db: Session,
    payload: ItemReportCreate,
) -> ItemReport:
    """Create and persist a new lost-item or found-item report."""

    # Convert the validated Pydantic object into a dictionary.
    report_data = payload.model_dump()

    # Create the SQLAlchemy model instance.
    report = ItemReport(
        **report_data,
        status="active",
    )

    # Save the report and retrieve its generated database ID.
    try:
        db.add(report)
        db.commit()
        db.refresh(report)

    except Exception:
        db.rollback()
        raise

    return report


def get_report(
    db: Session,
    report_id: int,
) -> ItemReport | None:
    """Retrieve a report by its primary key."""

    return db.get(ItemReport, report_id)


def list_reports(
    db: Session,
    report_type: str | None = None,
    limit: int = 20,
) -> list[ItemReport]:
    """List recent reports, optionally filtered by report type."""

    if limit < 1 or limit > 100:
        raise ValueError("Limit must be between 1 and 100.")

    statement = select(ItemReport)

    if report_type is not None:
        if report_type not in {"lost", "found"}:
            raise ValueError(
                "Report type must be either lost or found."
            )

        statement = statement.where(
            ItemReport.report_type == report_type
        )

    statement = statement.order_by(
        ItemReport.created_at.desc()
    ).limit(limit)

    return list(db.scalars(statement).all())
