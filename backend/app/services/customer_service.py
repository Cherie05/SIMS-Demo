from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import transaction
from app.core.exceptions import ConflictError, NotFoundError
from app.models import Customer, User
from app.schemas.customer import CustomerCreate, CustomerUpdate
from app.services import audit_service
from app.services.pagination import paginate

AUDITED_FIELDS = ["name", "email", "phone", "address", "is_active"]


def list_customers(db: Session, *, search: str | None, is_active: bool | None, page: int, page_size: int):
    stmt = select(Customer).order_by(Customer.name)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(Customer.name.ilike(pattern), Customer.email.ilike(pattern), Customer.phone.ilike(pattern))
        )
    if is_active is not None:
        stmt = stmt.where(Customer.is_active == is_active)
    return paginate(db, stmt, page, page_size)


def get_customer(db: Session, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError(f"Customer {customer_id} not found")
    return customer


def _ensure_unique_email(db: Session, email: str, exclude_id: int | None = None) -> None:
    stmt = select(Customer.id).where(Customer.email == email)
    if exclude_id:
        stmt = stmt.where(Customer.id != exclude_id)
    if db.scalar(stmt):
        raise ConflictError(f"A customer with email '{email}' already exists", code="DUPLICATE_EMAIL")


def create_customer(db: Session, data: CustomerCreate, user: User) -> Customer:
    with transaction(db):
        email = data.email.lower()
        _ensure_unique_email(db, email)
        customer = Customer(**data.model_dump(exclude={"email"}), email=email)
        db.add(customer)
        db.flush()
        audit_service.record(
            db,
            "customer.created",
            actor=user,
            entity_type="customer",
            entity_id=customer.id,
            details={"name": customer.name},
        )
    db.refresh(customer)
    return customer


def update_customer(db: Session, customer_id: int, data: CustomerUpdate, user: User) -> Customer:
    with transaction(db):
        customer = get_customer(db, customer_id)
        before = audit_service.snapshot(customer, AUDITED_FIELDS)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("email"):
            changes["email"] = changes["email"].lower()
            if changes["email"] != customer.email:
                _ensure_unique_email(db, changes["email"], exclude_id=customer.id)
        for field, value in changes.items():
            setattr(customer, field, value)
        diff = audit_service.diff(before, audit_service.snapshot(customer, AUDITED_FIELDS))
        if diff:
            audit_service.record(
                db, "customer.updated", actor=user, entity_type="customer", entity_id=customer.id, changes=diff
            )
    db.refresh(customer)
    return customer


def deactivate_customer(db: Session, customer_id: int, user: User) -> Customer:
    with transaction(db):
        customer = get_customer(db, customer_id)
        if customer.is_active:
            customer.is_active = False
            audit_service.record(
                db,
                "customer.deactivated",
                actor=user,
                entity_type="customer",
                entity_id=customer.id,
                changes={"is_active": {"old": True, "new": False}},
            )
    return customer
