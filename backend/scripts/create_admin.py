"""Create (or reset the password of) an administrator account.

For production, where demo data is never loaded:

    python -m scripts.create_admin --email admin@company.com --name "Jane Admin"

The password is read from the ADMIN_PASSWORD environment variable, or prompted for
(without echo) when it isn't set. The same password policy as the API applies.
"""

import argparse
import getpass
import os
import sys

from pydantic import ValidationError
from sqlalchemy import select

from app.core import clock
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import User, UserRole
from app.schemas.user import UserCreate
from app.services import audit_service, session_service, settings_service


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password for the new admin: ")
    try:
        data = UserCreate(name=args.name, email=args.email, password=password, role=UserRole.ADMIN)
    except ValidationError as exc:
        sys.exit("; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()))

    with SessionLocal() as db:
        settings_service.ensure_defaults(db)
        email = data.email.lower()
        user = db.scalar(select(User).where(User.email == email))
        if user:
            user.password_hash = hash_password(data.password)
            user.password_changed_at = clock.utcnow()
            user.role, user.is_active = UserRole.ADMIN, True
            user.email_verified_at = user.email_verified_at or clock.utcnow()
            # break-glass reset: existing sessions must not survive a password reset
            session_service.revoke_all(db, user.id, reason="admin")
            action = "updated"
        else:
            user = User(
                name=data.name,
                email=email,
                password_hash=hash_password(data.password),
                role=UserRole.ADMIN,
                email_verified_at=clock.utcnow(),
            )
            db.add(user)
            db.flush()
            action = "created"
        # Run from a shell on the server: the audit trail records it as a system action.
        audit_service.record(
            db,
            f"user.admin_{action}_by_cli",
            actor_id=user.id,
            actor_email=email,
            entity_type="user",
            entity_id=user.id,
            details={"source": "scripts.create_admin"},
        )
        db.commit()
    print(f"Admin {email} {action}.")


if __name__ == "__main__":
    main()
