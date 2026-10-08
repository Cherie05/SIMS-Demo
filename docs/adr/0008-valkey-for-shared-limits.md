# 0008 Valkey for shared rate limits, with graceful fallback

**Context.** In-process rate limits stop working once there is more than one API replica.

**Decision.** Rate-limit counters (sliding windows for sign-in, sign-up and password reset; fixed
per-minute budgets per user and per IP) live in Valkey 9, the BSD-licensed Redis fork (the redis-py
client works unchanged). If Valkey is unreachable the limiter falls back to per-process memory,
counts the failure in a metric and logs a warning once a minute: protection degrades instead of
disappearing, and an alert fires.

**Consequences.** Valkey holds nothing that must survive a restart (no persistence, 64 MB LRU).
Caching of expensive reads could reuse it later.
