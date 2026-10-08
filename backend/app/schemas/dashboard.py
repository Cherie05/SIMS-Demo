from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import InputModel, Money


class SalesSummary(BaseModel):
    total_revenue: Money
    revenue_this_month: Money
    revenue_today: Money
    completed_orders: int
    average_order_value: Money


class OrderCounts(BaseModel):
    total: int
    pending_approval: int
    completed: int
    rejected: int
    cancelled: int


class ApprovalStats(BaseModel):
    pending: int
    approved: int
    rejected: int
    cancelled: int
    pending_value: Money
    average_decision_hours: float | None


class InventoryStats(BaseModel):
    active_products: int
    total_units: int
    inventory_value: Money
    low_stock: int
    out_of_stock: int


class DashboardSummary(BaseModel):
    sales: SalesSummary
    orders: OrderCounts
    approvals: ApprovalStats
    inventory: InventoryStats
    customers: int


class SalesTrendPoint(BaseModel):
    date: date
    revenue: Money
    orders: int


class TopProduct(BaseModel):
    product_id: int
    sku: str
    name: str
    quantity_sold: int
    revenue: Money


class AppSettingsOut(BaseModel):
    approval_threshold: Money
    tax_rate: Money


class AppSettingsUpdate(InputModel):
    approval_threshold: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
