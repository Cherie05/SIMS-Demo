from typing import Literal

from pydantic import Field, field_validator

from app.models.enums import ApprovalStatus, EmailStatus, OrderStatus
from app.schemas.common import InputModel, Money, OutputModel, UtcDateTime
from app.schemas.customer import CustomerSummary
from app.schemas.product import ProductSummary
from app.schemas.user import UserSummary


class OrderItemIn(InputModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100_000)


class OrderCreate(InputModel):
    customer_id: int = Field(gt=0)
    items: list[OrderItemIn] = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("items")
    @classmethod
    def no_duplicate_products(cls, items: list[OrderItemIn]) -> list[OrderItemIn]:
        product_ids = [item.product_id for item in items]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("each product may appear only once per order; combine the quantities")
        return items


class ApproveRequest(InputModel):
    comment: str | None = Field(default=None, max_length=500)


class RejectRequest(InputModel):
    comment: str = Field(min_length=3, max_length=500, description="Reason for rejection (required)")


class CancelRequest(InputModel):
    reason: str | None = Field(default=None, max_length=500)


class OrderItemOut(OutputModel):
    id: int
    product: ProductSummary
    quantity: int
    unit_price: Money
    line_total: Money


class ApprovalOut(OutputModel):
    id: int
    status: ApprovalStatus
    threshold_amount: Money
    requested_at: UtcDateTime
    decided_by: UserSummary | None
    decided_at: UtcDateTime | None
    comment: str | None


class StatusHistoryOut(OutputModel):
    id: int
    from_status: OrderStatus | None
    to_status: OrderStatus
    changed_by: UserSummary | None
    comment: str | None
    created_at: UtcDateTime


class EmailLogOut(OutputModel):
    id: int
    to_email: str
    subject: str
    template: str
    # QUEUED: waiting in the outbox for the background worker (retried with backoff if delivery fails)
    status: EmailStatus | Literal["QUEUED"]
    error: str | None
    created_at: UtcDateTime


class OrderListItem(OutputModel):
    id: int
    order_number: str
    status: OrderStatus
    customer: CustomerSummary
    created_by: UserSummary
    total_amount: Money
    requires_approval: bool
    created_at: UtcDateTime
    completed_at: UtcDateTime | None


class OrderOut(OrderListItem):
    subtotal: Money
    tax_rate: Money
    tax_amount: Money
    notes: str | None
    items: list[OrderItemOut]
    approval: ApprovalOut | None
    history: list[StatusHistoryOut]
    emails: list[EmailLogOut] = []


class ApprovalListItem(OutputModel):
    id: int
    status: ApprovalStatus
    threshold_amount: Money
    requested_at: UtcDateTime
    decided_by: UserSummary | None
    decided_at: UtcDateTime | None
    comment: str | None
    order: OrderListItem
