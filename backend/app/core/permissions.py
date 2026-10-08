"""Authorization model: role-based access control expressed as fine-grained permissions.

Endpoints ask for a permission (never a role), so a role's powers are defined in exactly one place
and are easy to review. Anything not granted here is denied. Object-level rules (sales staff see
only their own orders, nobody approves their own order) live in the services, next to the data.

The web app receives the signed-in user's permissions from /auth/me and hides what they can't use;
the API enforces the same rules regardless of what the UI shows.
"""

from enum import StrEnum

from app.models.enums import UserRole


class Permission(StrEnum):
    DASHBOARD_READ = "dashboard:read"
    PRODUCT_READ = "product:read"
    PRODUCT_WRITE = "product:write"
    STOCK_ADJUST = "stock:adjust"
    INVENTORY_READ = "inventory:read"
    CUSTOMER_READ = "customer:read"
    CUSTOMER_WRITE = "customer:write"
    CUSTOMER_DEACTIVATE = "customer:deactivate"
    ORDER_CREATE = "order:create"
    ORDER_READ_OWN = "order:read:own"
    ORDER_READ_ALL = "order:read:all"
    ORDER_CANCEL_ANY = "order:cancel:any"
    ORDER_APPROVE = "order:approve"
    SETTINGS_READ = "settings:read"
    SETTINGS_WRITE = "settings:write"
    USER_MANAGE = "user:manage"
    AUDIT_READ = "audit:read"
    SYSTEM_READ = "system:read"
    SYSTEM_OPERATE = "system:operate"


_SALES = {
    Permission.DASHBOARD_READ,
    Permission.PRODUCT_READ,
    Permission.INVENTORY_READ,
    Permission.CUSTOMER_READ,
    Permission.CUSTOMER_WRITE,
    Permission.ORDER_CREATE,
    Permission.ORDER_READ_OWN,
    Permission.SETTINGS_READ,
}
_MANAGER = _SALES | {
    Permission.PRODUCT_WRITE,
    Permission.STOCK_ADJUST,
    Permission.CUSTOMER_DEACTIVATE,
    Permission.ORDER_READ_ALL,
    Permission.ORDER_CANCEL_ANY,
    Permission.ORDER_APPROVE,
}
_ADMIN = _MANAGER | {
    Permission.SETTINGS_WRITE,
    Permission.USER_MANAGE,
    Permission.AUDIT_READ,
    Permission.SYSTEM_READ,
    Permission.SYSTEM_OPERATE,
}

ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.SALES: frozenset(_SALES),
    UserRole.MANAGER: frozenset(_MANAGER),
    UserRole.ADMIN: frozenset(_ADMIN),
}


def permissions_for(role: UserRole) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(role: UserRole, permission: Permission) -> bool:
    return permission in permissions_for(role)
