from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, PageParams, require
from app.core.permissions import Permission
from app.models import User
from app.schemas.common import Page
from app.schemas.product import (
    InventoryTransactionOut,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    StockAdjustmentCreate,
)
from app.services import idempotency_service, inventory_service, product_service

router = APIRouter(prefix="/products", tags=["Products"])

Reader = Annotated[User, Depends(require(Permission.PRODUCT_READ))]
Writer = Annotated[User, Depends(require(Permission.PRODUCT_WRITE))]
StockAdjuster = Annotated[User, Depends(require(Permission.STOCK_ADJUST))]


@router.get("", response_model=Page[ProductOut])
def list_products(
    db: DbSession,
    _: Reader,
    pagination: PageParams,
    search: str | None = None,
    is_active: bool | None = None,
    low_stock: bool = False,
):
    return product_service.list_products(
        db,
        search=search,
        is_active=is_active,
        low_stock=low_stock,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(data: ProductCreate, db: DbSession, user: Writer):
    return product_service.create_product(db, data, user)


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: DbSession, _: Reader):
    return product_service.get_product(db, product_id)


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, data: ProductUpdate, db: DbSession, user: Writer):
    return product_service.update_product(db, product_id, data, user)


@router.delete("/{product_id}", response_model=ProductOut, summary="Deactivate a product (soft delete)")
def deactivate_product(product_id: int, db: DbSession, user: Writer):
    return product_service.deactivate_product(db, product_id, user)


@router.post(
    "/{product_id}/stock-adjustments",
    response_model=InventoryTransactionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Restock or manually adjust stock (recorded in the inventory ledger)",
    description="Supports an `Idempotency-Key` header, so a retried restock is applied once.",
)
def adjust_stock(
    product_id: int,
    data: StockAdjustmentCreate,
    request: Request,
    response: Response,
    db: DbSession,
    user: StockAdjuster,
):
    claim = idempotency_service.claim_from(request, user.id, f"POST /products/{product_id}/stock-adjustments", data)
    if claim and (existing := idempotency_service.lookup(db, claim)):
        response.headers[idempotency_service.REPLAYED_HEADER] = "true"
        return inventory_service.get_transaction(db, existing.resource_id)
    try:
        return inventory_service.adjust_stock(db, product_id, data, user, idempotency=claim)
    except IntegrityError:
        db.rollback()
        if claim and (existing := idempotency_service.lookup(db, claim)):
            response.headers[idempotency_service.REPLAYED_HEADER] = "true"
            return inventory_service.get_transaction(db, existing.resource_id)
        raise
