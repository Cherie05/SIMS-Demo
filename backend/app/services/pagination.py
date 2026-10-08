from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


def paginate(db: Session, stmt: Select, page: int, page_size: int) -> dict[str, Any]:
    """Run a SELECT with LIMIT/OFFSET and a matching COUNT(*)."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = db.scalars(stmt.limit(page_size).offset((page - 1) * page_size)).unique().all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}
