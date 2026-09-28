# Celery workers use synchronous DB sessions and receive the Tenant explicitly

The API uses SQLAlchemy's async engine. Celery workers use its sync engine, and both run on the same `psycopg` 3 driver. We kept Celery for its maturity and Flower monitoring, and rejected Taskiq (smaller ecosystem) and `asyncio.run()` inside tasks (event-loop and pool bugs).

Workers never pass through the API middleware, so every task takes `tenant_id` as its first argument and opens its session through one `tenant_session(tenant_id)` helper that sets the RLS context. A CI check fails any task that does not use it.

## Consequences

- Tasks are per item (one CV, one Score Result), acknowledged late, and idempotent through unique keys such as `(scoring_run_id, application_id)`. A redelivered task upserts rather than duplicating.
- Canvas chords are avoided. Batch progress comes from counting item rows, not from a Redis chord.
