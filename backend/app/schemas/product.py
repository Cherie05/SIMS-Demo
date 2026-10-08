from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from app.models.enums import InventoryTxnType
from app.schemas.common import InputModel, Money, OutputModel, UtcDateTime
from app.schemas.user import UserSummary

SKU_PATTERN = r"^[A-Za-z0-9_-]+$"


class ProductCreate(InputModel):
    sku: str = Field(min_length=2, max_length=50, pattern=SKU_PATTERN)
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    opening_stock: int = Field(default=0, ge=0, le=1_000_000)
    reorder_level: int = Field(default=10, ge=0, le=1_000_000)

    @field_validator("sku")
    @classmethod
    def upper_sku(cls, value: str) -> str:
        return value.upper()


class ProductUpdate(InputModel):
    """Stock is deliberately not editable here; use stock adjustments so the ledger stays complete."""

    sku: str | None = Field(default=None, min_length=2, max_length=50, pattern=SKU_PATTERN)
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    reorder_level: int | None = Field(default=None, ge=0, le=1_000_000)
    is_active: bool | None = None

    @field_validator("sku")
    @classmethod
    def upper_sku(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class ProductSummary(OutputModel):
    id: int
    sku: str
    name: str


class ProductOut(ProductSummary):
    description: str | None
    unit_price: Money
    stock_qty: int
    reorder_level: int
    is_active: bool
    is_low_stock: bool
    created_at: UtcDateTime
    updated_at: UtcDateTime


class StockAdjustmentCreate(InputModel):
    txn_type: InventoryTxnType = InventoryTxnType.RESTOCK
    quantity: int = Field(description="Positive to add stock; negative allowed only for ADJUSTMENT")
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def check_quantity(self):
        if self.txn_type not in (InventoryTxnType.RESTOCK, InventoryTxnType.ADJUSTMENT):
            raise ValueError("txn_type must be RESTOCK or ADJUSTMENT")
        if self.quantity == 0:
            raise ValueError("quantity must not be zero")
        if self.txn_type == InventoryTxnType.RESTOCK and self.quantity < 0:
            raise ValueError("RESTOCK quantity must be positive")
        if abs(self.quantity) > 1_000_000:
            raise ValueError("quantity is too large")
        if self.txn_type == InventoryTxnType.ADJUSTMENT and not self.note:
            raise ValueError("a note is required for manual adjustments")
        return self


class InventoryTransactionOut(OutputModel):
    id: int
    product: ProductSummary
    order_id: int | None
    txn_type: InventoryTxnType
    qty_change: int
    balance_after: int
    note: str | None
    created_by: UserSummary | None
    created_at: UtcDateTime
