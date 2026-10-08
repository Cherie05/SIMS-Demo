# 0001 Modular monolith, not microservices

**Context.** One team, one bounded business area (sales orders, stock, approvals), strong
consistency needs (an approval must deduct stock in the same transaction), a short delivery window.

**Decision.** A single FastAPI codebase organised by domain (identity, sales, inventory, platform)
with service functions as the only path between domains, deployed as stateless replicas plus a
background worker.

**Consequences.** One transaction covers an approval, its stock movements, audit entry and email
jobs - no distributed transactions or sagas. Domains can be extracted later along the service
boundaries if a team or scaling need appears. The cost is a shared release cadence.
