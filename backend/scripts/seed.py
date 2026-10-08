"""Load demo data: users, customers, products and ~60 days of order history.

Usage (from backend/):  python -m scripts.seed          # skips if data already exists
                        python -m scripts.seed --force  # wipes all data first

Orders are created through the real order service, so stock, ledger, approvals and status
history are all consistent. Timestamps are then spread over the past month for the dashboard.
"""

import random
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select, update

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import InsufficientStockError
from app.core.security import hash_password
from app.models import (
    AppSetting,
    Customer,
    EmailLog,
    IdempotencyKey,
    InventoryTransaction,
    OrderApproval,
    OrderStatusHistory,
    OutboxJob,
    Product,
    SalesOrder,
    SalesOrderItem,
    User,
    UserRole,
)
from app.schemas.order import OrderCreate, OrderItemIn
from app.schemas.product import ProductCreate
from app.services import order_service, product_service, settings_service

HISTORY_DAYS = 60
# Reproducible demo data, not security: the standard generator is the right tool here.
_rng = random.Random(42)  # nosec B311

USERS = [
    ("Asha Admin", "admin@example.com", "Admin@123", UserRole.ADMIN),
    ("Manoj Manager", "manager@example.com", "Manager@123", UserRole.MANAGER),
    ("Sneha Sales", "sales@example.com", "Sales@123", UserRole.SALES),
    ("Rahul Sales", "sales2@example.com", "Sales@123", UserRole.SALES),
]

CUSTOMERS = [
    ("Acme Retail Pvt Ltd", "purchase@acme-retail.example.com", "+91 98480 11111", "12 MG Road, Hyderabad"),
    ("Bluewave Traders", "orders@bluewave.example.com", "+91 98480 22222", "45 Anna Salai, Chennai"),
    ("Crescent Office Supplies", "buy@crescent.example.com", "+91 98480 33333", "7 Park Street, Kolkata"),
    ("Delta Tech Solutions", "procure@deltatech.example.com", "+91 98480 44444", "88 Whitefield, Bengaluru"),
    ("Evergreen Schools Trust", "admin@evergreen.example.com", "+91 98480 55555", "3 FC Road, Pune"),
    ("Fusion Hospitality", "stores@fusionhotels.example.com", "+91 98480 66666", "21 Marine Drive, Mumbai"),
    ("Galaxy Clinics", "it@galaxyclinics.example.com", "+91 98480 77777", "9 Banjara Hills, Hyderabad"),
    ("Horizon Logistics", "ops@horizonlog.example.com", "+91 98480 88888", "14 Sector 18, Noida"),
]

PRODUCTS = [
    ("LAP-001", 'Laptop 14" i5 / 16GB / 512GB', "Business laptop", "58500.00", 40, 8),
    ("LAP-002", 'Laptop 15" i7 / 32GB / 1TB', "Performance laptop", "92000.00", 15, 5),
    ("MON-024", 'Monitor 24" IPS FHD', "Office monitor", "11500.00", 60, 10),
    ("MON-027", 'Monitor 27" QHD', "Design monitor", "23800.00", 25, 6),
    ("KBD-100", "Wireless Keyboard & Mouse Combo", None, "1850.00", 150, 25),
    ("HDS-200", "USB Headset with Mic", None, "2400.00", 90, 20),
    ("PRN-300", "Laser Printer Mono", "30 ppm, duplex", "16500.00", 12, 4),
    ("UPS-600", "UPS 600VA", None, "3900.00", 35, 8),
    ("RTR-AX3", "Wi-Fi 6 Router AX3000", None, "6200.00", 28, 6),
    ("SSD-1TB", "External SSD 1TB", None, "7800.00", 45, 10),
    ("CAM-HD", "1080p Webcam", None, "3100.00", 7, 10),
    ("CHR-ERG", "Ergonomic Office Chair", None, "14200.00", 3, 5),
]


def _wipe(db) -> None:
    # Sessions, codes and recovery codes go with their users (ON DELETE CASCADE). The audit trail is
    # append-only by design (database triggers), so a demo reset leaves it in place.
    for model in (
        OutboxJob,
        IdempotencyKey,
        EmailLog,
        InventoryTransaction,
        OrderStatusHistory,
        OrderApproval,
        SalesOrderItem,
        SalesOrder,
        Product,
        Customer,
        AppSetting,
        User,
    ):
        db.execute(delete(model))
    db.commit()


def _backdate(db, order_id: int, when: datetime) -> None:
    """Shift an order and its related rows to a past timestamp (demo data only)."""
    order = db.get(SalesOrder, order_id)
    db.execute(update(SalesOrder).where(SalesOrder.id == order_id).values(created_at=when, updated_at=when))
    if order.completed_at:
        done = when + timedelta(hours=_rng.randint(1, 20)) if order.requires_approval else when
        db.execute(update(SalesOrder).where(SalesOrder.id == order_id).values(completed_at=done))
    db.execute(update(OrderStatusHistory).where(OrderStatusHistory.order_id == order_id).values(created_at=when))
    db.execute(update(InventoryTransaction).where(InventoryTransaction.order_id == order_id).values(created_at=when))
    db.execute(update(OrderApproval).where(OrderApproval.order_id == order_id).values(requested_at=when))
    db.execute(
        update(OrderApproval)
        .where(OrderApproval.order_id == order_id, OrderApproval.decided_at.is_not(None))
        .values(decided_at=when + timedelta(hours=_rng.randint(1, 20)))
    )
    db.commit()


def seed(force: bool = False) -> None:
    _rng.seed(42)
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)):
            if not force:
                print("Data already present - skipping seed (use --force to reset).")
                return
            _wipe(db)

        settings_service.ensure_defaults(db)

        now = datetime.now(UTC).replace(tzinfo=None)
        users = [
            User(name=name, email=email, password_hash=hash_password(password), role=role, email_verified_at=now)
            for name, email, password, role in USERS
        ]
        db.add_all(users)
        db.commit()
        admin = next(u for u in users if u.role == UserRole.ADMIN)
        manager = next(u for u in users if u.role == UserRole.MANAGER)
        sales_reps = [u for u in users if u.role == UserRole.SALES]

        customers = [Customer(name=n, email=e, phone=p, address=a) for n, e, p, a in CUSTOMERS]
        db.add_all(customers)
        db.commit()

        products = []
        for sku, name, desc, price, stock, reorder in PRODUCTS:
            # Seed extra opening stock so the generated history leaves realistic levels behind.
            data = ProductCreate(
                sku=sku,
                name=name,
                description=desc,
                unit_price=Decimal(price),
                opening_stock=stock * 6 if stock > 10 else stock,
                reorder_level=reorder,
            )
            products.append(product_service.create_product(db, data, admin))

        now = datetime.now(UTC).replace(tzinfo=None)
        sellable = [p for p in products if p.stock_qty > 10]
        created = 0
        # Two months of history, so the dashboard can compare a 30-day period with the one before.
        for days_ago in range(HISTORY_DAYS - 1, 0, -1):
            for _ in range(_rng.choice([0, 1, 1, 2])):
                rep = _rng.choice(sales_reps)
                lines = _rng.sample(sellable, k=_rng.randint(1, 3))
                items = [
                    OrderItemIn(product_id=p.id, quantity=_rng.randint(1, 2 if p.unit_price > 20000 else 4))
                    for p in lines
                ]
                try:
                    order = order_service.create_order(
                        db, OrderCreate(customer_id=_rng.choice(customers).id, items=items), rep
                    )
                except InsufficientStockError:
                    continue  # the random basket asked for more than is left; skip it
                if order.requires_approval and days_ago > 2:
                    roll = _rng.random()
                    if roll < 0.7:
                        try:
                            order_service.approve_order(db, order.id, manager, "Approved - regular customer")
                        except InsufficientStockError:
                            order_service.reject_order(db, order.id, manager, "Not enough stock left to fulfil")
                    elif roll < 0.9:
                        order_service.reject_order(db, order.id, manager, "Discount not authorised, please re-quote")
                    else:
                        order_service.cancel_order(db, order.id, rep, "Customer withdrew the request")
                when = now - timedelta(days=days_ago, hours=_rng.randint(0, 8), minutes=_rng.randint(0, 59))
                _backdate(db, order.id, when)
                created += 1

        # A few orders left waiting in the manager's approval queue.
        by_sku = {p.sku: p for p in products}
        pending = [
            (sales_reps[0], customers[3], [("LAP-002", 1), ("MON-027", 2)], "Urgent: new branch office setup"),
            (sales_reps[1], customers[5], [("LAP-001", 2)], None),
        ]
        for hours_ago, (rep, customer, basket, notes) in zip((5, 2), pending, strict=True):
            order = order_service.create_order(
                db,
                OrderCreate(
                    customer_id=customer.id,
                    items=[OrderItemIn(product_id=by_sku[sku].id, quantity=qty) for sku, qty in basket],
                    notes=notes,
                ),
                rep,
            )
            _backdate(db, order.id, now - timedelta(hours=hours_ago))
            created += 1

        # History is backdated demo data: its notification emails must not be sent now.
        db.execute(delete(OutboxJob))
        db.commit()
        print(f"Seeded {len(USERS)} users, {len(customers)} customers, {len(products)} products, {created} orders.")
        print("Logins: admin@example.com / Admin@123, manager@example.com / Manager@123, sales@example.com / Sales@123")


if __name__ == "__main__":
    if settings.is_production:
        # Demo users have published passwords; never create them on a real system.
        sys.exit("Refusing to load demo data with ENVIRONMENT=production. Use `python -m scripts.create_admin`.")
    seed(force="--force" in sys.argv)
