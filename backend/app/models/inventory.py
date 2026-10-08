from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import InventoryTxnType
from app.models.order import SalesOrder
from app.models.product import Product
from app.models.user import User


class InventoryTransaction(Base):
    """Append-only stock ledger. Every change to products.stock_qty writes one row here."""

    __tablename__ = "inventory_transactions"
    __table_args__ = (Index("ix_inventory_transactions_product_created", "product_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"), index=True)
    txn_type: Mapped[InventoryTxnType] = mapped_column(
        Enum(InventoryTxnType, name="inventory_txn_type"), nullable=False
    )
    qty_change: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    product: Mapped[Product] = relationship()
    order: Mapped[SalesOrder | None] = relationship()
    created_by: Mapped[User | None] = relationship()
