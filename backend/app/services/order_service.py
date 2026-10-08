"""Sales order lifecycle and approval workflow.

    create ──► total <= threshold ──► APPROVED ──► COMPLETED   (stock deducted immediately)
          └──► total >  threshold ──► PENDING_APPROVAL
                                         ├── approve ──► APPROVED ──► COMPLETED (stock deducted)
                                         ├── reject  ──► REJECTED
                                         └── cancel  ──► CANCELLED

Every state change runs in a single database transaction, together with its audit entry and the
outbox jobs for its emails. Stock is validated when the order is created and validated again,
under row locks, at the moment it is deducted.
"""

import secrets
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core import metrics
from app.core.database import transaction
from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    InsufficientStockError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.permissions import Permission, has_permission
from app.models import (
    ApprovalStatus,
    Customer,
    EmailLog,
    InventoryTxnType,
    OrderApproval,
    OrderStatus,
    OrderStatusHistory,
    Product,
    SalesOrder,
    SalesOrderItem,
    User,
)
from app.schemas.order import OrderCreate
from app.services import (
    audit_service,
    feature_flags,
    idempotency_service,
    inventory_service,
    notification_service,
    outbox_service,
    settings_service,
    user_service,
)
from app.services.idempotency_service import IdempotencyClaim
from app.services.pagination import paginate

CENTS = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _generate_order_number() -> str:
    return f"SO-{_utcnow():%Y%m%d}-{secrets.token_hex(3).upper()}"


def _add_history(
    db: Session,
    order: SalesOrder,
    to_status: OrderStatus,
    user: User | None,
    comment: str | None = None,
) -> None:
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status=order.status,
            to_status=to_status,
            changed_by_id=user.id if user else None,
            comment=comment,
        )
    )
    order.status = to_status


def _check_stock(items: list[tuple[int, int]], products: dict[int, Product]) -> None:
    """Raise InsufficientStockError listing every line that cannot be fulfilled."""
    shortages = []
    for product_id, quantity in items:
        product = products[product_id]
        if product.stock_qty < quantity:
            shortages.append(
                {
                    "product_id": product.id,
                    "sku": product.sku,
                    "name": product.name,
                    "requested": quantity,
                    "available": product.stock_qty,
                }
            )
    if shortages:
        names = ", ".join(f"{s['sku']} (requested {s['requested']}, available {s['available']})" for s in shortages)
        raise InsufficientStockError(f"Insufficient stock for: {names}", details=shortages)


def _fulfil(db: Session, order: SalesOrder, user: User) -> None:
    """Lock products, re-check stock, deduct it and mark the order COMPLETED.

    Must be called inside an open transaction with the order in APPROVED state.
    """
    products = inventory_service.lock_products(db, [item.product_id for item in order.items])
    _check_stock([(item.product_id, item.quantity) for item in order.items], products)
    for item in order.items:
        inventory_service.record_movement(
            db,
            products[item.product_id],
            -item.quantity,
            InventoryTxnType.SALE,
            user.id,
            order_id=order.id,
            note=f"Sale {order.order_number}",
        )
    _add_history(db, order, OrderStatus.COMPLETED, user, "Inventory updated, order completed")
    order.completed_at = _utcnow()


# ----------------------------------------------------------------------------------- create


def create_order(db: Session, data: OrderCreate, user: User, idempotency: IdempotencyClaim | None = None) -> SalesOrder:
    with transaction(db):
        reservation = idempotency_service.reserve(db, idempotency)
        feature_flags.require(
            db, "orders.create", "Order intake is paused by an administrator. Please try again later."
        )
        customer = db.get(Customer, data.customer_id)
        if customer is None:
            raise NotFoundError(f"Customer {data.customer_id} not found")
        if not customer.is_active:
            raise BusinessRuleError(f"Customer '{customer.name}' is inactive", code="CUSTOMER_INACTIVE")

        requested = [(item.product_id, item.quantity) for item in data.items]
        # Lock the rows now: for orders under the threshold we deduct stock in this same transaction.
        products = inventory_service.lock_products(db, [product_id for product_id, _ in requested])

        missing = [product_id for product_id, _ in requested if product_id not in products]
        if missing:
            raise NotFoundError(f"Products not found: {missing}", code="PRODUCT_NOT_FOUND", details=missing)
        inactive = [products[pid].sku for pid, _ in requested if not products[pid].is_active]
        if inactive:
            raise BusinessRuleError(
                f"Inactive products cannot be ordered: {', '.join(inactive)}", code="PRODUCT_INACTIVE"
            )
        _check_stock(requested, products)

        app_settings = settings_service.get_app_settings(db)
        threshold, tax_rate = app_settings["approval_threshold"], app_settings["tax_rate"]

        order = SalesOrder(
            order_number=_generate_order_number(),
            customer_id=customer.id,
            created_by_id=user.id,
            notes=data.notes,
            tax_rate=tax_rate,
        )
        subtotal = Decimal("0")
        for product_id, quantity in requested:
            product = products[product_id]
            line_total = _money(product.unit_price * quantity)
            subtotal += line_total
            order.items.append(
                SalesOrderItem(
                    product_id=product.id,
                    quantity=quantity,
                    unit_price=product.unit_price,
                    line_total=line_total,
                )
            )
        order.subtotal = _money(subtotal)
        order.tax_amount = _money(subtotal * tax_rate / Decimal(100))
        order.total_amount = order.subtotal + order.tax_amount
        order.requires_approval = order.total_amount > threshold
        if order.requires_approval:
            order.status = OrderStatus.PENDING_APPROVAL
            comment = (
                f"Total {order.total_amount:,.2f} exceeds the approval threshold of {threshold:,.2f}; "
                "manager approval required"
            )
        else:
            order.status = OrderStatus.APPROVED
            comment = f"Auto-approved: total within the approval threshold of {threshold:,.2f}"

        db.add(order)
        db.flush()
        db.add(
            OrderStatusHistory(
                order_id=order.id, from_status=None, to_status=order.status, changed_by_id=user.id, comment=comment
            )
        )

        if order.requires_approval:
            db.add(OrderApproval(order_id=order.id, status=ApprovalStatus.PENDING, threshold_amount=threshold))
            # Emails to the approvers commit with the order (transactional outbox).
            notification_service.enqueue_approval_requests(db, order.id, user_service.get_approvers(db))
        else:
            _fulfil(db, order, user)

        audit_service.record(
            db,
            "order.created",
            actor=user,
            entity_type="order",
            entity_id=order.id,
            details={
                "order_number": order.order_number,
                "customer_id": customer.id,
                "total_amount": order.total_amount,
                "threshold": threshold,
                "status": order.status.value,
                "lines": len(order.items),
            },
        )
        idempotency_service.remember(reservation, "order", order.id)
        order_id = order.id
        outcome = "pending_approval" if order.requires_approval else "auto_approved"
    metrics.ORDERS_CREATED.labels(outcome).inc()
    return get_order(db, order_id)


# ----------------------------------------------------------------------------------- read


def _order_query():
    return select(SalesOrder).options(
        joinedload(SalesOrder.customer),
        joinedload(SalesOrder.created_by),
    )


def _ensure_can_view(order: SalesOrder, user: User) -> None:
    # 404, not 403: other people's order ids must not be discoverable by probing.
    if not has_permission(user.role, Permission.ORDER_READ_ALL) and order.created_by_id != user.id:
        raise NotFoundError(f"Order {order.id} not found")


def get_order(db: Session, order_id: int, user: User | None = None) -> SalesOrder:
    order = db.scalar(
        _order_query()
        .options(
            selectinload(SalesOrder.items).joinedload(SalesOrderItem.product),
            joinedload(SalesOrder.approval).joinedload(OrderApproval.decided_by),
            selectinload(SalesOrder.history).joinedload(OrderStatusHistory.changed_by),
        )
        .where(SalesOrder.id == order_id)
        .execution_options(populate_existing=True)
    )
    if order is None:
        raise NotFoundError(f"Order {order_id} not found")
    if user is not None:
        _ensure_can_view(order, user)
    return order


def get_order_emails(db: Session, order_id: int) -> list[EmailLog | dict]:
    """Delivered/failed emails, then the ones still queued for the background worker."""
    sent: list[EmailLog | dict] = list(
        db.scalars(select(EmailLog).where(EmailLog.order_id == order_id).order_by(EmailLog.id)).all()
    )
    order = db.get(SalesOrder, order_id)
    for job in outbox_service.pending_for_order(db, order_id):
        recipient_id = job.payload.get("recipient_id") or (order.created_by_id if order else None)
        recipient = db.get(User, recipient_id) if recipient_id else None
        sent.append(
            {
                "id": -job.id,
                "to_email": recipient.email if recipient else "",
                "subject": "Waiting to be sent" if job.attempts == 0 else f"Retrying (attempt {job.attempts})",
                "template": job.job_type.removeprefix("email."),
                "status": "QUEUED",
                "error": job.last_error,
                "created_at": job.created_at,
            }
        )
    return sent


def list_orders(
    db: Session,
    user: User,
    *,
    status: OrderStatus | None,
    customer_id: int | None,
    search: str | None,
    date_from: date | None,
    date_to: date | None,
    mine: bool,
    page: int,
    page_size: int,
):
    stmt = _order_query().order_by(SalesOrder.created_at.desc(), SalesOrder.id.desc())
    if not has_permission(user.role, Permission.ORDER_READ_ALL) or mine:
        stmt = stmt.where(SalesOrder.created_by_id == user.id)
    if status:
        stmt = stmt.where(SalesOrder.status == status)
    if customer_id:
        stmt = stmt.where(SalesOrder.customer_id == customer_id)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.join(SalesOrder.customer).where(
            or_(SalesOrder.order_number.ilike(pattern), Customer.name.ilike(pattern))
        )
    if date_from:
        stmt = stmt.where(SalesOrder.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(SalesOrder.created_at <= datetime.combine(date_to, time.max))
    return paginate(db, stmt, page, page_size)


def list_approvals(db: Session, *, status: ApprovalStatus | None, page: int, page_size: int):
    stmt = (
        select(OrderApproval)
        .options(
            joinedload(OrderApproval.decided_by),
            joinedload(OrderApproval.order).joinedload(SalesOrder.customer),
            joinedload(OrderApproval.order).joinedload(SalesOrder.created_by),
        )
        .order_by(OrderApproval.requested_at.desc(), OrderApproval.id.desc())
    )
    if status:
        stmt = stmt.where(OrderApproval.status == status)
    return paginate(db, stmt, page, page_size)


def pending_approval_count(db: Session) -> int:
    return db.scalar(select(func.count(OrderApproval.id)).where(OrderApproval.status == ApprovalStatus.PENDING)) or 0


# ----------------------------------------------------------------------------------- decisions


def _lock_pending_order(db: Session, order_id: int) -> tuple[SalesOrder, OrderApproval]:
    """Lock the order row so two managers can't decide the same order concurrently."""
    order = db.scalar(
        select(SalesOrder)
        .options(selectinload(SalesOrder.items), joinedload(SalesOrder.approval))
        .where(SalesOrder.id == order_id)
        .with_for_update(of=SalesOrder)
        .execution_options(populate_existing=True)
    )
    if order is None:
        raise NotFoundError(f"Order {order_id} not found")
    if order.status != OrderStatus.PENDING_APPROVAL or order.approval is None:
        raise ConflictError(
            f"Order {order.order_number} is {order.status.value}, not awaiting approval",
            code="ORDER_NOT_PENDING",
        )
    return order, order.approval


def _ensure_not_own_order(order: SalesOrder, approver: User) -> None:
    if order.created_by_id == approver.id:
        raise PermissionDeniedError(
            "You cannot approve or reject an order you created", code="SELF_APPROVAL_NOT_ALLOWED"
        )


def approve_order(db: Session, order_id: int, approver: User, comment: str | None) -> SalesOrder:
    with transaction(db):
        order, approval = _lock_pending_order(db, order_id)
        _ensure_not_own_order(order, approver)

        approval.status = ApprovalStatus.APPROVED
        approval.decided_by_id = approver.id
        approval.decided_at = _utcnow()
        approval.comment = comment

        _add_history(db, order, OrderStatus.APPROVED, approver, comment or "Approved by manager")
        # Raises InsufficientStockError if stock ran out since the order was placed; the whole
        # transaction (including the approval above) is then rolled back and the order stays pending.
        _fulfil(db, order, approver)
        _record_decision(db, order, approver, "order.approved", comment)
    metrics.APPROVAL_DECISIONS.labels("approved").inc()
    return get_order(db, order_id)


def _record_decision(db: Session, order: SalesOrder, user: User, action: str, comment: str | None) -> None:
    audit_service.record(
        db,
        action,
        actor=user,
        entity_type="order",
        entity_id=order.id,
        details={"order_number": order.order_number, "total_amount": order.total_amount, "comment": comment},
    )
    if action != "order.cancelled":
        notification_service.enqueue_decision(db, order.id)


def reject_order(db: Session, order_id: int, approver: User, comment: str) -> SalesOrder:
    with transaction(db):
        order, approval = _lock_pending_order(db, order_id)
        _ensure_not_own_order(order, approver)

        approval.status = ApprovalStatus.REJECTED
        approval.decided_by_id = approver.id
        approval.decided_at = _utcnow()
        approval.comment = comment

        _add_history(db, order, OrderStatus.REJECTED, approver, comment)
        _record_decision(db, order, approver, "order.rejected", comment)
    metrics.APPROVAL_DECISIONS.labels("rejected").inc()
    return get_order(db, order_id)


def cancel_order(db: Session, order_id: int, user: User, reason: str | None) -> SalesOrder:
    with transaction(db):
        order, approval = _lock_pending_order(db, order_id)
        if order.created_by_id != user.id:
            if not has_permission(user.role, Permission.ORDER_READ_ALL):
                raise NotFoundError(f"Order {order_id} not found")
            if not has_permission(user.role, Permission.ORDER_CANCEL_ANY):
                raise PermissionDeniedError("Only the creator or a manager can cancel this order")

        approval.status = ApprovalStatus.CANCELLED
        approval.decided_by_id = user.id
        approval.decided_at = _utcnow()
        approval.comment = reason

        _add_history(db, order, OrderStatus.CANCELLED, user, reason or "Cancelled")
        _record_decision(db, order, user, "order.cancelled", reason)
    return get_order(db, order_id)
