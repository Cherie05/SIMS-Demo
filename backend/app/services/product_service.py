from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import transaction
from app.core.exceptions import ConflictError, NotFoundError
from app.models import InventoryTxnType, Product, User
from app.schemas.product import ProductCreate, ProductUpdate
from app.services import audit_service, inventory_service
from app.services.pagination import paginate


def list_products(
    db: Session,
    *,
    search: str | None,
    is_active: bool | None,
    low_stock: bool,
    page: int,
    page_size: int,
):
    stmt = select(Product).order_by(Product.name)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(or_(Product.name.ilike(pattern), Product.sku.ilike(pattern)))
    if is_active is not None:
        stmt = stmt.where(Product.is_active == is_active)
    if low_stock:
        stmt = stmt.where(Product.stock_qty <= Product.reorder_level)
    return paginate(db, stmt, page, page_size)


def get_product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError(f"Product {product_id} not found")
    return product


def _ensure_unique_sku(db: Session, sku: str, exclude_id: int | None = None) -> None:
    stmt = select(Product.id).where(Product.sku == sku)
    if exclude_id:
        stmt = stmt.where(Product.id != exclude_id)
    if db.scalar(stmt):
        raise ConflictError(f"SKU '{sku}' is already in use", code="DUPLICATE_SKU")


AUDITED_FIELDS = ["sku", "name", "description", "unit_price", "reorder_level", "is_active"]


def create_product(db: Session, data: ProductCreate, user: User) -> Product:
    with transaction(db):
        _ensure_unique_sku(db, data.sku)
        product = Product(**data.model_dump(exclude={"opening_stock"}), stock_qty=0)
        db.add(product)
        db.flush()
        if data.opening_stock:
            inventory_service.record_movement(
                db, product, data.opening_stock, InventoryTxnType.OPENING, user.id, note="Opening stock"
            )
        audit_service.record(
            db,
            "product.created",
            actor=user,
            entity_type="product",
            entity_id=product.id,
            details={
                "sku": product.sku,
                "name": product.name,
                "unit_price": product.unit_price,
                "opening_stock": data.opening_stock,
            },
        )
    db.refresh(product)
    return product


def update_product(db: Session, product_id: int, data: ProductUpdate, user: User) -> Product:
    with transaction(db):
        product = get_product(db, product_id)
        before = audit_service.snapshot(product, AUDITED_FIELDS)
        changes = data.model_dump(exclude_unset=True)
        if "sku" in changes and changes["sku"] != product.sku:
            _ensure_unique_sku(db, changes["sku"], exclude_id=product.id)
        for field, value in changes.items():
            setattr(product, field, value)
        diff = audit_service.diff(before, audit_service.snapshot(product, AUDITED_FIELDS))
        if diff:
            audit_service.record(
                db, "product.updated", actor=user, entity_type="product", entity_id=product.id, changes=diff
            )
    db.refresh(product)
    return product


def deactivate_product(db: Session, product_id: int, user: User) -> Product:
    """Soft delete: products referenced by orders must never be hard-deleted."""
    with transaction(db):
        product = get_product(db, product_id)
        if product.is_active:
            product.is_active = False
            audit_service.record(
                db,
                "product.deactivated",
                actor=user,
                entity_type="product",
                entity_id=product.id,
                changes={"is_active": {"old": True, "new": False}},
            )
    return product
