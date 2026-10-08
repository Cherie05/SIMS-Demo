from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, PageParams, require
from app.core.permissions import Permission
from app.models import ApprovalStatus, OrderStatus, User
from app.schemas.common import Page
from app.schemas.order import (
    ApprovalListItem,
    ApproveRequest,
    CancelRequest,
    EmailLogOut,
    OrderCreate,
    OrderListItem,
    OrderOut,
    RejectRequest,
)
from app.services import idempotency_service, order_service

router = APIRouter(tags=["Orders & Approvals"])

OrderCreator = Annotated[User, Depends(require(Permission.ORDER_CREATE))]
OrderReader = Annotated[User, Depends(require(Permission.ORDER_READ_OWN))]
Approver = Annotated[User, Depends(require(Permission.ORDER_APPROVE))]


def _order_out(db, order) -> OrderOut:
    result = OrderOut.model_validate(order)
    result.emails = [EmailLogOut.model_validate(log) for log in order_service.get_order_emails(db, order.id)]
    return result


@router.post(
    "/orders",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a sales order (auto-completes, or waits for manager approval above the threshold)",
    description=(
        "Send an `Idempotency-Key` header (any unique string per order) to make retries safe: "
        "repeating the request with the same key returns the original order instead of creating a "
        "second one, with the response header `Idempotent-Replayed: true`."
    ),
)
def create_order(data: OrderCreate, request: Request, response: Response, db: DbSession, user: OrderCreator):
    claim = idempotency_service.claim_from(request, user.id, "POST /orders", data)
    if claim and (existing := idempotency_service.lookup(db, claim)):
        response.headers[idempotency_service.REPLAYED_HEADER] = "true"
        return _order_out(db, order_service.get_order(db, existing.resource_id, user))
    try:
        order = order_service.create_order(db, data, user, idempotency=claim)
    except IntegrityError:
        # A concurrent retry with the same key won the race: answer with its order.
        db.rollback()
        if claim and (existing := idempotency_service.lookup(db, claim)):
            response.headers[idempotency_service.REPLAYED_HEADER] = "true"
            return _order_out(db, order_service.get_order(db, existing.resource_id, user))
        raise
    return _order_out(db, order)


@router.get("/orders", response_model=Page[OrderListItem], summary="Orders (sales staff see only their own)")
def list_orders(
    db: DbSession,
    user: OrderReader,
    pagination: PageParams,
    status: OrderStatus | None = None,
    customer_id: int | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    mine: bool = False,
):
    return order_service.list_orders(
        db,
        user,
        status=status,
        customer_id=customer_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
        mine=mine,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: DbSession, user: OrderReader):
    return _order_out(db, order_service.get_order(db, order_id, user))


@router.post("/orders/{order_id}/cancel", response_model=OrderOut, summary="Cancel an order awaiting approval")
def cancel_order(order_id: int, db: DbSession, user: OrderReader, data: CancelRequest | None = None):
    order = order_service.cancel_order(db, order_id, user, data.reason if data else None)
    return _order_out(db, order)


@router.get("/approvals", response_model=Page[ApprovalListItem], summary="Approval queue and decision history")
def list_approvals(
    db: DbSession,
    _: Approver,
    pagination: PageParams,
    status: ApprovalStatus | None = None,
):
    return order_service.list_approvals(db, status=status, page=pagination.page, page_size=pagination.page_size)


@router.post("/orders/{order_id}/approve", response_model=OrderOut, summary="Approve: deducts stock and completes")
def approve_order(order_id: int, db: DbSession, approver: Approver, data: ApproveRequest | None = None):
    order = order_service.approve_order(db, order_id, approver, data.comment if data else None)
    return _order_out(db, order)


@router.post("/orders/{order_id}/reject", response_model=OrderOut, summary="Reject with a mandatory reason")
def reject_order(order_id: int, data: RejectRequest, db: DbSession, approver: Approver):
    order = order_service.reject_order(db, order_id, approver, data.comment)
    return _order_out(db, order)
