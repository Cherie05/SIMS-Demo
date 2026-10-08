from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import case, func, literal_column, select
from sqlalchemy.orm import Session

from app.models import (
    ApprovalStatus,
    Customer,
    OrderApproval,
    OrderStatus,
    Product,
    SalesOrder,
    SalesOrderItem,
)

ZERO = Decimal("0")
CENTS = Decimal("0.01")


def _today() -> date:
    return datetime.now(UTC).date()


def get_summary(db: Session) -> dict:
    today = _today()
    month_start = datetime.combine(today.replace(day=1), time.min)
    day_start = datetime.combine(today, time.min)
    completed = SalesOrder.status == OrderStatus.COMPLETED

    sales = db.execute(
        select(
            func.coalesce(func.sum(SalesOrder.total_amount), ZERO),
            func.coalesce(
                func.sum(case((SalesOrder.completed_at >= month_start, SalesOrder.total_amount), else_=ZERO)), ZERO
            ),
            func.coalesce(
                func.sum(case((SalesOrder.completed_at >= day_start, SalesOrder.total_amount), else_=ZERO)), ZERO
            ),
            func.count(SalesOrder.id),
        ).where(completed)
    ).one()
    total_revenue, revenue_month, revenue_today, completed_count = sales

    status_counts = dict(db.execute(select(SalesOrder.status, func.count()).group_by(SalesOrder.status)).all())

    approval_counts = dict(db.execute(select(OrderApproval.status, func.count()).group_by(OrderApproval.status)).all())
    pending_value = db.scalar(
        select(func.coalesce(func.sum(SalesOrder.total_amount), ZERO)).where(
            SalesOrder.status == OrderStatus.PENDING_APPROVAL
        )
    )
    avg_decision_seconds = db.scalar(
        select(
            func.avg(func.timestampdiff(literal_column("SECOND"), OrderApproval.requested_at, OrderApproval.decided_at))
        ).where(OrderApproval.status.in_([ApprovalStatus.APPROVED, ApprovalStatus.REJECTED]))
    )

    inventory = db.execute(
        select(
            func.count(Product.id),
            func.coalesce(func.sum(Product.stock_qty), 0),
            func.coalesce(func.sum(Product.stock_qty * Product.unit_price), ZERO),
            func.coalesce(func.sum(case((Product.stock_qty <= Product.reorder_level, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Product.stock_qty == 0, 1), else_=0)), 0),
        ).where(Product.is_active.is_(True))
    ).one()

    customers = db.scalar(select(func.count(Customer.id)).where(Customer.is_active.is_(True))) or 0

    return {
        "sales": {
            "total_revenue": total_revenue,
            "revenue_this_month": revenue_month,
            "revenue_today": revenue_today,
            "completed_orders": completed_count,
            "average_order_value": (total_revenue / completed_count).quantize(CENTS) if completed_count else ZERO,
        },
        "orders": {
            "total": sum(status_counts.values()),
            "pending_approval": status_counts.get(OrderStatus.PENDING_APPROVAL, 0),
            "completed": status_counts.get(OrderStatus.COMPLETED, 0),
            "rejected": status_counts.get(OrderStatus.REJECTED, 0),
            "cancelled": status_counts.get(OrderStatus.CANCELLED, 0),
        },
        "approvals": {
            "pending": approval_counts.get(ApprovalStatus.PENDING, 0),
            "approved": approval_counts.get(ApprovalStatus.APPROVED, 0),
            "rejected": approval_counts.get(ApprovalStatus.REJECTED, 0),
            "cancelled": approval_counts.get(ApprovalStatus.CANCELLED, 0),
            "pending_value": pending_value,
            "average_decision_hours": round(float(avg_decision_seconds) / 3600, 2)
            if avg_decision_seconds is not None
            else None,
        },
        "inventory": {
            "active_products": inventory[0],
            "total_units": int(inventory[1]),
            "inventory_value": inventory[2],
            "low_stock": int(inventory[3]),
            "out_of_stock": int(inventory[4]),
        },
        "customers": customers,
    }


def get_sales_trend(db: Session, days: int) -> list[dict]:
    """Daily completed revenue for the last `days` days, with zero-filled gaps."""
    end = _today()
    start = end - timedelta(days=days - 1)
    day = func.date(SalesOrder.completed_at)
    rows = db.execute(
        select(day, func.sum(SalesOrder.total_amount), func.count(SalesOrder.id))
        .where(
            SalesOrder.status == OrderStatus.COMPLETED,
            SalesOrder.completed_at >= datetime.combine(start, time.min),
        )
        .group_by(day)
    ).all()
    by_day = {row[0]: (row[1], row[2]) for row in rows}
    return [
        {
            "date": current,
            "revenue": by_day.get(current, (ZERO, 0))[0],
            "orders": by_day.get(current, (ZERO, 0))[1],
        }
        for current in (start + timedelta(days=offset) for offset in range(days))
    ]


def get_top_products(db: Session, limit: int, days: int | None = None) -> list[dict]:
    """Best sellers by revenue from completed orders, optionally only the last `days` days."""
    revenue = func.sum(SalesOrderItem.line_total)
    stmt = (
        select(Product.id, Product.sku, Product.name, func.sum(SalesOrderItem.quantity), revenue)
        .join(SalesOrderItem, SalesOrderItem.product_id == Product.id)
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.order_id)
        .where(SalesOrder.status == OrderStatus.COMPLETED)
    )
    if days:
        since = datetime.combine(_today() - timedelta(days=days - 1), time.min)
        stmt = stmt.where(SalesOrder.completed_at >= since)
    rows = db.execute(stmt.group_by(Product.id, Product.sku, Product.name).order_by(revenue.desc()).limit(limit)).all()
    return [{"product_id": r[0], "sku": r[1], "name": r[2], "quantity_sold": int(r[3]), "revenue": r[4]} for r in rows]
