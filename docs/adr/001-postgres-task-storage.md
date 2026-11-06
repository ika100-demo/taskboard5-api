# ADR-001: Tasks are stored in Postgres via psycopg 3, schema created by the service

## Status

Accepted (spec 002, 2026-11-06).

## Context

Spec 001 kept tasks in memory, so a restart emptied the list and the API had to run as one replica. Spec 002
(system plan 001-persistent-tasks-and-web-task-board) requires tasks to survive restarts and be shared by every
instance. The system's gitops-app provides a CloudNativePG `postgres` resource and injects `DATABASE_URL` and `PG*`.
The contract fixes a 2 s connect timeout, a 3 s statement timeout, `503 {"detail": "Task storage unavailable"}` on
storage failure and a `/ready` that checks the database on every call.

## Decision

- Postgres is the task store, reached with **psycopg 3** (`psycopg[binary]`), configured only by `DATABASE_URL`.
- **One short-lived connection per store operation** (`connect_timeout=2`, `statement_timeout=3000`), no pool.
- **The service owns its schema**: idempotent `CREATE TABLE IF NOT EXISTS` under a Postgres advisory lock, run at
  startup and lazily before first use. No migration tool while every schema change is additive.
- Creation order comes from a database **identity column**, never from clock time.
- Connection failures, timeouts and a missing `DATABASE_URL` become one `StorageUnavailableError`, mapped to 503.
- Tests run against a **real Postgres** started with testcontainers, or `TEST_DATABASE_URL` when Docker is absent.

## Consequences

**Positive:** stateless replicas; automatic recovery after a database outage (no stale pooled connections); no
extra deploy step or init container for the schema; tests exercise the real SQL.

**Negative:** a connect handshake per request (switch to `psycopg_pool` behind the same `TaskStore` interface if
load grows); the first non-additive schema change must introduce a migration tool (e.g. Alembic) in a new ADR;
the test suite needs Docker or a reachable test database.
