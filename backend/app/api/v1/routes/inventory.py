from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, PageParams, require
from app.core.permissions import Permission
from app.models import InventoryTxnType, User
from app.schemas.common import Page
from app.schemas.product import InventoryTransactionOut
from app.services import inventory_service

router = APIRouter(prefix="/inventory", tags=["Inventory"])


@router.get("/transactions", response_model=Page[InventoryTransactionOut], summary="Stock movement ledger")
def list_transactions(
    db: DbSession,
    _: Annotated[User, Depends(require(Permission.INVENTORY_READ))],
    pagination: PageParams,
    product_id: int | None = None,
    txn_type: InventoryTxnType | None = None,
):
    return inventory_service.list_transactions(
        db, product_id=product_id, txn_type=txn_type, page=pagination.page, page_size=pagination.page_size
    )
