from fastapi import APIRouter, Depends

from app.api.deps import limit_by_client_ip
from app.api.v1.routes import (
    audit,
    auth,
    customers,
    dashboard,
    inventory,
    orders,
    products,
    system,
    telemetry,
    users,
)

api_router = APIRouter(dependencies=[Depends(limit_by_client_ip)])
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(customers.router)
api_router.include_router(products.router)
api_router.include_router(inventory.router)
api_router.include_router(orders.router)
api_router.include_router(dashboard.router)
api_router.include_router(audit.router)
api_router.include_router(system.router)
api_router.include_router(telemetry.router)
