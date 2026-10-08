# 0006 Permissions on top of roles; deny by default

**Context.** Role checks scattered across endpoints are hard to review and easy to forget.

**Decision.** Three roles map to fine-grained permissions in one file (`backend/app/core/permissions.py`).
Every endpoint declares the permission it needs; object-level rules (sales staff see only their own
orders, nobody approves their own order, the last administrator can't be removed) live in the
services. A test walks the whole OpenAPI document and fails if any operation outside an explicit
public list lacks authentication. Users who may not see an order get 404, not 403, so order ids
can't be probed. The web app renders by permission, never by role name.

**Consequences.** A new role or permission set is a change in one reviewed place. Attribute-based
rules (e.g. approval limits per manager) would extend the service-level checks.
