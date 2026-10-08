import csv
import io
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.deps import DbSession, PageParams, require
from app.core import clock
from app.core.permissions import Permission
from app.models import User
from app.schemas.common import Page
from app.schemas.system import AuditLogOut
from app.services import audit_service

router = APIRouter(prefix="/audit-logs", tags=["Audit"])

Auditor = Annotated[User, Depends(require(Permission.AUDIT_READ))]
EXPORT_LIMIT = 10_000
CSV_COLUMNS = [
    "id", "occurred_at", "actor_id", "actor_email", "actor_role", "action", "outcome",
    "entity_type", "entity_id", "changes", "details", "ip_address", "user_agent", "request_id",
]  # fmt: skip


class AuditFilters:
    def __init__(
        self,
        action: Annotated[
            str | None, Query(max_length=64, description="Action or prefix, e.g. 'auth' or 'order.approved'")
        ] = None,
        actor_id: int | None = None,
        entity_type: Annotated[str | None, Query(max_length=40)] = None,
        entity_id: Annotated[str | None, Query(max_length=64)] = None,
        outcome: Literal["success", "failure", "denied"] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ):
        self.values: dict[str, Any] = {
            "action": action,
            "actor_id": actor_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "outcome": outcome,
            "date_from": date_from,
            "date_to": date_to,
        }


Filters = Annotated[AuditFilters, Depends()]


@router.get("", response_model=Page[AuditLogOut], summary="Search the audit trail")
def list_audit_logs(db: DbSession, _: Auditor, pagination: PageParams, filters: Filters):
    return audit_service.list_audit_logs(db, **filters.values, page=pagination.page, page_size=pagination.page_size)


def _safe_cell(value) -> str:
    """Spreadsheet apps run cells starting with = + - @ as formulas (CSV injection): neutralise them."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get(
    "/export",
    summary=f"Download the matching entries as CSV (newest {EXPORT_LIMIT:,})",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {}}}},
)
def export_audit_logs(db: DbSession, user: Auditor, filters: Filters):
    page = audit_service.list_audit_logs(db, **filters.values, page=1, page_size=EXPORT_LIMIT)
    audit_service.record(db, "audit.exported", actor=user, details={"rows": len(page["items"]), **filters.values})
    db.commit()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for entry in page["items"]:
        out = AuditLogOut.model_validate(entry).model_dump(mode="json")
        writer.writerow([_safe_cell(out[column]) for column in CSV_COLUMNS])
    filename = f"sims-audit-{clock.utcnow():%Y%m%d-%H%M%S}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
