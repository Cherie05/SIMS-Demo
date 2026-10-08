from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require
from app.core.permissions import Permission
from app.models import User
from app.schemas.dashboard import (
    AppSettingsOut,
    AppSettingsUpdate,
    DashboardSummary,
    SalesTrendPoint,
    TopProduct,
)
from app.services import dashboard_service, settings_service

router = APIRouter(tags=["Dashboard & Settings"])

DashboardReader = Annotated[User, Depends(require(Permission.DASHBOARD_READ))]


@router.get("/dashboard/summary", response_model=DashboardSummary)
def summary(db: DbSession, _: DashboardReader):
    return dashboard_service.get_summary(db)


@router.get("/dashboard/sales-trend", response_model=list[SalesTrendPoint])
def sales_trend(db: DbSession, _: DashboardReader, days: Annotated[int, Query(ge=1, le=730)] = 30):
    return dashboard_service.get_sales_trend(db, days)


@router.get("/dashboard/top-products", response_model=list[TopProduct])
def top_products(
    db: DbSession,
    _: DashboardReader,
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
    days: Annotated[int | None, Query(ge=1, le=730, description="Only the last N days")] = None,
):
    return dashboard_service.get_top_products(db, limit, days)


@router.get("/settings", response_model=AppSettingsOut)
def get_settings(db: DbSession, _: Annotated[User, Depends(require(Permission.SETTINGS_READ))]):
    return settings_service.get_app_settings(db)


@router.put("/settings", response_model=AppSettingsOut)
def update_settings(
    data: AppSettingsUpdate, db: DbSession, admin: Annotated[User, Depends(require(Permission.SETTINGS_WRITE))]
):
    return settings_service.update_app_settings(db, data, admin)
