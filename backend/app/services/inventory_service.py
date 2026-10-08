from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.database import transaction
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models import InventoryTransaction, InventoryTxnType, Product, User
from app.schemas.product import StockAdjustmentCreate
from app.services import audit_service, idempotency_service
from app.services.idempotency_service import IdempotencyClaim
from app.services.pagination import paginate


def lock_products(db: Session, product_ids: Iterable[int]) -> dict[int, Product]:
    """SELECT ... FOR UPDATE the given products.

    Rows are always locked in ascending id order so two transactions touching the same
    products cannot deadlock each other.
    """
    ids = sorted(set(product_ids))
    if not ids:
        return {}
    rows = db.scalars(select(Product).where(Product.id.in_(ids)).order_by(Product.id).with_for_update()).all()
    return {product.id: product for product in rows}


def record_movement(
    db: Session,
    product: Product,
    qty_change: int,
    txn_type: InventoryTxnType,
    user_id: int | None,
    *,
    order_id: int | None = None,
    note: str | None = None,
) -> InventoryTransaction:
    """Apply a stock change to an already-locked product and append it to the ledger."""
    new_balance = product.stock_qty + qty_change
    if new_balance < 0:
        raise BusinessRuleError(
            f"Stock for {product.sku} cannot go below zero (available {product.stock_qty}, change {qty_change})",
            code="NEGATIVE_STOCK",
        )
    product.stock_qty = new_balance
    txn = InventoryTransaction(
        product_id=product.id,
        order_id=order_id,
        txn_type=txn_type,
        qty_change=qty_change,
        balance_after=new_balance,
        note=note,
        created_by_id=user_id,
    )
    db.add(txn)
    return txn


def adjust_stock(
    db: Session,
    product_id: int,
    data: StockAdjustmentCreate,
    user: User,
    idempotency: IdempotencyClaim | None = None,
) -> InventoryTransaction:
    with transaction(db):
        reservation = idempotency_service.reserve(db, idempotency)
        product = lock_products(db, [product_id]).get(product_id)
        if product is None:
            raise NotFoundError(f"Product {product_id} not found")
        before = product.stock_qty
        txn = record_movement(db, product, data.quantity, data.txn_type, user.id, note=data.note)
        db.flush()
        audit_service.record(
            db,
            "stock.adjusted",
            actor=user,
            entity_type="product",
            entity_id=product.id,
            changes={"stock_qty": {"old": before, "new": product.stock_qty}},
            details={"sku": product.sku, "txn_type": data.txn_type.value, "quantity": data.quantity, "note": data.note},
        )
        idempotency_service.remember(reservation, "inventory_transaction", txn.id)
        txn_id = txn.id
    return get_transaction(db, txn_id)


def get_transaction(db: Session, txn_id: int) -> InventoryTransaction:
    return db.scalars(
        select(InventoryTransaction)
        .options(joinedload(InventoryTransaction.product), joinedload(InventoryTransaction.created_by))
        .where(InventoryTransaction.id == txn_id)
    ).one()


def list_transactions(
    db: Session,
    *,
    product_id: int | None,
    txn_type: InventoryTxnType | None,
    page: int,
    page_size: int,
):
    stmt = (
        select(InventoryTransaction)
        .options(joinedload(InventoryTransaction.product), joinedload(InventoryTransaction.created_by))
        .order_by(InventoryTransaction.created_at.desc(), InventoryTransaction.id.desc())
    )
    if product_id:
        stmt = stmt.where(InventoryTransaction.product_id == product_id)
    if txn_type:
        stmt = stmt.where(InventoryTransaction.txn_type == txn_type)
    return paginate(db, stmt, page, page_size)
