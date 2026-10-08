from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, PageParams, require
from app.core.exceptions import PermissionDeniedError
from app.core.permissions import Permission, has_permission
from app.models import User
from app.schemas.common import Page
from app.schemas.customer import CustomerCreate, CustomerOut, CustomerUpdate
from app.services import customer_service

router = APIRouter(prefix="/customers", tags=["Customers"])

Reader = Annotated[User, Depends(require(Permission.CUSTOMER_READ))]
Writer = Annotated[User, Depends(require(Permission.CUSTOMER_WRITE))]
Deactivator = Annotated[User, Depends(require(Permission.CUSTOMER_DEACTIVATE))]


@router.get("", response_model=Page[CustomerOut])
def list_customers(
    db: DbSession,
    _: Reader,
    pagination: PageParams,
    search: str | None = None,
    is_active: bool | None = None,
):
    return customer_service.list_customers(
        db, search=search, is_active=is_active, page=pagination.page, page_size=pagination.page_size
    )


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(data: CustomerCreate, db: DbSession, user: Writer):
    return customer_service.create_customer(db, data, user)


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: int, db: DbSession, _: Reader):
    return customer_service.get_customer(db, customer_id)


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: int, data: CustomerUpdate, db: DbSession, user: Writer):
    if data.is_active is not None and not has_permission(user.role, Permission.CUSTOMER_DEACTIVATE):
        raise PermissionDeniedError("Only managers can activate or deactivate customers")
    return customer_service.update_customer(db, customer_id, data, user)


@router.delete("/{customer_id}", response_model=CustomerOut, summary="Deactivate a customer (soft delete)")
def deactivate_customer(customer_id: int, db: DbSession, user: Deactivator):
    return customer_service.deactivate_customer(db, customer_id, user)
