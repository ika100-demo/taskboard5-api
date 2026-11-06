# Design — 002 Store tasks in Postgres so they survive restarts and are shared by every instance

The HTTP contract of spec 001 (`POST /tasks`, `GET /tasks`, request/response shapes, validation, `201`/`200`/`422`)
does not change. This spec adds storage in Postgres, `503` on storage failure and a database-aware `/ready`.
The System context of spec.md (contract, timeouts) is binding; this file repeats the parts a test asserts on.

## Decisions

- **Postgres through psycopg 3, one short-lived connection per operation.** `psycopg[binary]` (wheels ship libpq,
  so the slim Dockerfile needs no change). Each store call opens a connection with `connect_timeout=2` and
  `options="-c statement_timeout=3000"`, runs one transaction and closes it. Reason: the service stays stateless,
  there are no stale pooled connections after a database outage, so recovery needs no restart (AC-002.6), and the
  traffic of a task board is tiny. ADR: [docs/adr/001-postgres-task-storage.md](../../adr/001-postgres-task-storage.md).
- **Configuration from `DATABASE_URL` only** (injected by the gitops `uses: postgres`; the `PG*` variables are
  ignored). It is read when an app's store is first needed, not at import, so tests can set it after importing
  `taskboard5_api.main`. When it is unset, every storage call fails as "storage unavailable" (503, `/ready` 503);
  the process still starts and `/health` answers 200.
- **The service creates its own schema** with idempotent DDL (AC-002.2), no migration tool: one table, created by
  `TaskStore.ensure_schema()` inside a transaction holding `pg_advisory_xact_lock(<fixed key>)` so two replicas
  starting together do not race on `CREATE TABLE IF NOT EXISTS`. It runs in the app's lifespan startup (best
  effort: a failure is logged, startup continues) and lazily before the first `add`/`list` of a store that has not
  yet ensured it (covers a DB that was down at startup and `TestClient` used without `with`). The store remembers
  success per instance.
- **Ordering by a database identity column** `seq BIGINT GENERATED ALWAYS AS IDENTITY`; `GET /tasks` is
  `ORDER BY seq`. Never by clock time (spec Notes, AC-002.1, AC-002.3).
- **Ids stay `str(uuid.uuid4())`**, generated in Python, stored in a `UUID` column and returned with `str()`
  (canonical lowercase, same as spec 001). `due_date` is a `DATE` column, returned with `date.isoformat()`; for a
  value that passed the `YYYY-MM-DD` validator this is exactly the string sent.
- **Storage failure is one exception type.** The store converts `psycopg.OperationalError` and
  `psycopg.InterfaceError` (connection refused, connect timeout, `QueryCanceled` from the statement timeout, a
  connection lost mid-call) and a missing `DATABASE_URL` into `StorageUnavailableError`. An exception handler in
  `main.py` maps it to `503 {"detail": "Task storage unavailable"}` (AC-002.4, AC-002.5). Other `psycopg.Error`s
  (programming errors) stay `500`: a bug must not look like an outage. `add` commits only after the insert
  succeeded, so a 503 never leaves a task behind (AC-002.4).
- **App factory.** `main.py` gets `create_app(database_url: str | None = None) -> FastAPI` and keeps
  `app = create_app()` for uvicorn. Each app owns its store in `app.state`, so a test builds "a restarted service"
  or "a second instance" with another `create_app()` against the same database (AC-002.1, AC-002.3). Logging and
  tracing stay configured once at module import (prometheus metrics are module-level, so several apps are safe).
- **`/ready` checks the database on every call** (`SELECT 1` on a new connection, 2 s connect timeout);
  **`/health` never touches it** (AC-002.6).
- **Tests use a real Postgres via testcontainers** (`testcontainers[postgres]`, image `postgres:16-alpine`), or an
  existing database when `TEST_DATABASE_URL` is set (for a runner without Docker). No devbox.json change: Docker is
  already required for `image-build`, GitHub-hosted CI runners have it, and devbox recipes are platform-owned.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `pyproject.toml`, `uv.lock` | add `psycopg[binary]>=3.2` (runtime), `testcontainers[postgres]>=4.8` (dev) | changed |
| `src/taskboard5_api/tasks/store.py` | Postgres `TaskStore`, `StorageUnavailableError`, `task_store_for(app)`, `get_task_store(request)` | changed (rewritten) |
| `src/taskboard5_api/tasks/__init__.py` | also re-exports `StorageUnavailableError`, `task_store_for` | changed |
| `src/taskboard5_api/tasks/router.py` | unchanged signatures; dependency is the new `get_task_store` | changed (imports only, if any) |
| `src/taskboard5_api/main.py` | `create_app()`, lifespan `ensure_schema`, 503 handler, DB-aware `/ready` | changed |
| `docs/env-vars.md` | `DATABASE_URL`, `TEST_DATABASE_URL`, fixed timeouts | changed |
| `tests/conftest.py` | Postgres fixtures (below) | changed |
| `tests/test_tasks.py` | spec-001 fixture against Postgres; AC-001.7 test removed | changed |

Public interface (signatures only):

```python
# tasks/store.py
class StorageUnavailableError(Exception): ...

class TaskStore:
    def __init__(self, database_url: str | None) -> None: ...  # no I/O in the constructor
    def ensure_schema(self) -> None: ...      # idempotent DDL under an advisory lock; raises StorageUnavailableError
    def add(self, data: TaskCreate) -> Task: ...   # INSERT + COMMIT; raises StorageUnavailableError
    def list(self) -> list[Task]: ...         # ORDER BY seq; raises StorageUnavailableError
    def ping(self) -> bool: ...               # SELECT 1; False on any storage failure, never raises

def task_store_for(app: FastAPI) -> TaskStore: ...
    # returns app.state.task_store, building it on first use from
    # app.state.database_url (create_app argument) or os.environ["DATABASE_URL"]

def get_task_store(request: Request) -> TaskStore: ...   # = task_store_for(request.app); the FastAPI dependency

# main.py
def create_app(database_url: str | None = None) -> FastAPI: ...
app: FastAPI  # = create_app()
```

`/ready` and both task routes receive the store through `Depends(get_task_store)`, so
`app.dependency_overrides[get_task_store]` still works.

## Contract

Unchanged from spec 001 for `201`, `200` and `422` (see `docs/specs/001-create-and-list-tasks/design.md`). Added:

- `POST /tasks` with a valid body while storage is unavailable → `503`, body exactly
  `{"detail": "Task storage unavailable"}`, `Content-Type: application/json`, answered within 5 s; nothing stored
  (AC-002.4). A body that fails validation is still `422` (validation runs before the store is touched).
- `GET /tasks` while storage is unavailable → `503`, body exactly `{"detail": "Task storage unavailable"}`,
  within 5 s (AC-002.5).
- `GET /tasks` → `200` with every task in the database, `ORDER BY seq` (creation order across all instances and
  restarts), each element equal to the object `POST /tasks` returned (AC-002.1, AC-002.3). `[]` on a database whose
  table was just created (AC-002.2).
- `GET /ready` → `200 {"status": "ready"}` when `SELECT 1` succeeds; `503 {"status": "not ready"}` otherwise,
  evaluated on every call, recovering without restart (AC-002.6).
- `GET /health` → `200 {"status": "ok"}` regardless of the database (AC-002.6).

"Unavailable" covers: connection refused, host unreachable or connect not completed within 2 s, a statement
exceeding 3 s, the connection dropping during the call, `DATABASE_URL` unset.

## Data

```sql
CREATE TABLE IF NOT EXISTS tasks (
    seq        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- creation order
    id         UUID NOT NULL UNIQUE,
    title      TEXT NOT NULL,                                     -- stored untrimmed
    due_date   DATE NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()                 -- informational only, never used for ordering
);
```

Created by `ensure_schema()` (plan t1). No migration of the in-memory data: it never survived a restart.

## Test seam (fixtures in `tests/conftest.py`, plan t2)

Acceptance tests for spec 002 go in `tests/test_tasks_postgres.py` and use only these fixtures and the public
interface above:

| Fixture | Scope | What it gives |
|---|---|---|
| `database_url` | session, autouse | a reachable Postgres URL (`postgresql://...`): `TEST_DATABASE_URL` if set, else a started `PostgresContainer("postgres:16-alpine")`. Also sets `os.environ["DATABASE_URL"]` to it, so the module-level `app` and every `create_app()` use it. |
| `empty_database` | function | ensures the `tasks` table exists and `TRUNCATE tasks RESTART IDENTITY`; yields `database_url`. |
| `db_outage` | function | a `DatabaseSwitch` with `.url` (a local TCP relay to the test database on a fixed free port), `.cut()` (closes the listener and every relayed connection: connects are refused) and `.restore()` (listens on the same port again). Starts restored; restores on teardown. |
| `client` | function | `TestClient(app)` for the module-level app (existing). |

Patterns:

- Restart (AC-002.1): create through `TestClient(create_app())`, then read through a new `TestClient(create_app())`.
- Two instances (AC-002.3): two `create_app()` apps alive at the same time against `database_url`.
- No schema (AC-002.2): `DROP TABLE IF EXISTS tasks`, then `with TestClient(create_app()) as c: c.get("/tasks")`.
  A test that drops the table must use a fresh `create_app()`: an existing app's store remembers that it already
  ensured the schema. `empty_database` recreates the table for later tests.
- Outage (AC-002.4 to AC-002.6): `create_app(database_url=db_outage.url)`, `db_outage.cut()`, assert `503` and
  elapsed time < 5 s, `db_outage.restore()`, assert recovery on the same app (no restart).

## Risks

- **Connection per operation** costs a TCP + auth handshake per request (a few ms in-cluster). Accepted for this
  load; `psycopg_pool` is the upgrade path, and the store's interface hides the choice.
- **Self-hosted CI runner without Docker** (`vars.CI_RUNNER`): testcontainers cannot start; set `TEST_DATABASE_URL`
  on that runner. GitHub-hosted runners are fine.
- **Schema evolution**: idempotent `CREATE ... IF NOT EXISTS` only works for additive changes; the first
  non-additive change must introduce a migration tool (ADR-001 records this).
- **Replicas**: gitops moves to 2 replicas only after this image runs in dev (system plan); nothing in this repo
  depends on the replica count.
