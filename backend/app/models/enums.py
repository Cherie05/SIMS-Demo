from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    SALES = "SALES"


class OrderStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"  # transient: approved, inventory being updated in the same transaction
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class InventoryTxnType(StrEnum):
    OPENING = "OPENING"
    SALE = "SALE"
    RESTOCK = "RESTOCK"
    ADJUSTMENT = "ADJUSTMENT"


class EmailStatus(StrEnum):
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class OtpPurpose(StrEnum):
    SIGNUP = "SIGNUP"  # prove ownership of the email address
    LOGIN = "LOGIN"  # second step of signing in
    PASSWORD_RESET = "PASSWORD_RESET"  # nosec B105 - forgot-password flow label, not a password


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY = "RETRY"
    DONE = "DONE"
    DEAD = "DEAD"  # failed max_attempts times: dead-letter, needs an operator
    EXPIRED = "EXPIRED"  # passed its deadline before it could run (e.g. a sign-in code)
