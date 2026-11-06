---
spec_id: 002-store-tasks-in-postgres-so-they-survive
shape: service-python
spec_hash: 443ad5636536
summary: Postgres-backed TaskStore (psycopg 3, identity ordering, self-created schema), 503 on storage failure, DB-aware /ready, real-Postgres tests
tasks:
  - id: t1
    title: Replace the in-memory TaskStore with a Postgres-backed store
    files: [pyproject.toml, uv.lock, src/taskboard5_api/tasks/store.py, src/taskboard5_api/tasks/__init__.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Postgres test fixtures and retire the AC-001.7 test
    files: [tests/conftest.py, tests/test_tasks.py]
    covers: [AC-002.1, AC-002.3, AC-002.6]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: App factory, schema at startup, 503 handler and database-aware /ready
    files: [src/taskboard5_api/main.py, src/taskboard5_api/tasks/router.py, docs/env-vars.md]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6]
    parallel_safe: true
    depends_on: [t1]
---

# Plan — 002 Store tasks in Postgres so they survive restarts and are shared by every instance

Contract, store interface, schema and test fixtures are in [design.md](design.md); the lasting decision is
[ADR-001](../../adr/001-postgres-task-storage.md). Level 1: t1; level 2: t2 and t3 in parallel (disjoint files).
The gitops side (postgres resource, `uses: postgres`, replicas 2) belongs to the gitops repo's slice of the system
plan, so this plan has no gitops task.

## t1 — Replace the in-memory TaskStore with a Postgres-backed store

**Files:** pyproject.toml, uv.lock, src/taskboard5_api/tasks/store.py, src/taskboard5_api/tasks/__init__.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6
**Goal:** a `TaskStore(database_url)` that persists tasks in the `tasks` table, orders them by an identity column,
creates its schema idempotently and turns every storage failure into `StorageUnavailableError`, plus the per-app
store lookup `task_store_for(app)` and the `get_task_store(request)` dependency.

**Implementation notes:**
- `pyproject.toml`: add `psycopg[binary]>=3.2` to `dependencies` and `testcontainers[postgres]>=4.8` to the `dev`
  extra; regenerate the lock with `devbox run -- uv lock` (never `uv add`/`pip`); `devbox run audit` stays clean.
- `store.py`: `StorageUnavailableError(Exception)`; `TaskStore.__init__(database_url: str | None)` does no I/O.
- Private `_connect()`: raises `StorageUnavailableError` when the URL is `None`/empty; else
  `psycopg.connect(url, connect_timeout=2, options="-c statement_timeout=3000")`.
- Wrap every operation so `psycopg.OperationalError` and `psycopg.InterfaceError` become `StorageUnavailableError`
  (chain with `from`); other `psycopg.Error`s propagate (500). Log the failure with structlog (never the URL).
- `ensure_schema()`: one transaction: `SELECT pg_advisory_xact_lock(<fixed bigint>)` then the `CREATE TABLE IF NOT
  EXISTS tasks (...)` from design.md (Data); sets `self._schema_ready = True` on success.
- `add(data)`: ensure the schema once, then `INSERT INTO tasks (id, title, due_date)` with `uuid.uuid4()`,
  `data.title` unchanged and `date.fromisoformat(data.due_date)` or `NULL`; commit; return
  `Task(id=str(id), title=data.title, due_date=data.due_date)`. Parameterised SQL only (bandit).
- `list()`: ensure the schema once, `SELECT id, title, due_date FROM tasks ORDER BY seq`; map to `Task` with
  `str(id)` and `due_date.isoformat()` or `None`.
- `ping() -> bool`: `SELECT 1` on a new connection; `False` on any storage failure, never raises.
- `task_store_for(app: FastAPI) -> TaskStore`: return `app.state.task_store`, creating it on first use from
  `getattr(app.state, "database_url", None) or os.environ.get("DATABASE_URL")`.
  `get_task_store(request: Request) -> TaskStore` returns `task_store_for(request.app)`. Remove the module-level
  `_store` singleton.
- `__init__.py`: re-export `StorageUnavailableError` and `task_store_for` as well; update the package docstring.

**Done when:** `devbox run quality` and `devbox run audit` pass; the HTTP acceptance tests pass only after t2 and t3.

## t2 — Postgres test fixtures and retire the AC-001.7 test

**Files:** tests/conftest.py, tests/test_tasks.py
**Covers:** AC-002.1, AC-002.3, AC-002.6
**Goal:** every test runs against a real Postgres through the fixtures named in design.md (Test seam), the spec-001
tests keep passing unchanged in substance against it, and the withdrawn AC-001.7 test is gone.

**Implementation notes:**
- `conftest.py`: session autouse fixture `database_url`: `TEST_DATABASE_URL` if set, else start
  `PostgresContainer("postgres:16-alpine", driver=None)` and use its connection URL (plain `postgresql://`); set
  `os.environ["DATABASE_URL"]`; stop the container at session end.
- `empty_database` (function): `TaskStore(database_url).ensure_schema()`, then `TRUNCATE tasks RESTART IDENTITY`
  over a direct psycopg connection; yield `database_url`.
- `db_outage` (function): a `DatabaseSwitch` class: a threaded TCP relay bound to `127.0.0.1:<free port>` that
  forwards to the test database host/port; `.url` is `database_url` with host/port replaced; `.cut()` closes the
  listener and every relayed socket (connects are refused); `.restore()` re-binds the same port (`SO_REUSEADDR`);
  teardown restores and stops it.
- Keep the existing `client` fixture; it works because `DATABASE_URL` is set before the first request.
- `test_tasks.py`: `tasks_client` uses `empty_database` and `TestClient(create_app())` (no dependency override,
  no no-arg `TaskStore()`); keep every AC-001.1 to AC-001.6 and AC-001.8 test and its assertions as they are.
- `test_tasks.py`: delete `test_restart_loses_tasks` (AC-001.7, withdrawn 2026-11-06); update the module docstring
  to say it runs against Postgres.
- Do not touch `tests/test_tasks_postgres.py` (spec-002 acceptance tests, written by the tester).

**Done when:** with t3 merged, `devbox run test` passes: the spec-001 tests, `test_health.py`, metrics, tracing and
the spec-002 acceptance tests; no test references AC-001.7.

## t3 — App factory, schema at startup, 503 handler and database-aware /ready

**Files:** src/taskboard5_api/main.py, src/taskboard5_api/tasks/router.py, docs/env-vars.md
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6
**Goal:** apps built by `create_app()` use the Postgres store, create the schema on startup, answer storage
failures with the contract's 503 and report readiness from the database on every call.

**Implementation notes:**
- `main.py`: `create_app(database_url: str | None = None) -> FastAPI` builds the app (metrics middleware, tasks
  router, `/health`, `/ready`, `/ping`, `/metrics`) and sets `app.state.database_url`; module-level
  `app = create_app()` stays the uvicorn entry point. `configure_logging`/`configure_tracing` stay at module level.
- Lifespan: on startup `task_store_for(app).ensure_schema()`; on `StorageUnavailableError` log a warning and
  continue (the store retries lazily on first use).
- `app.add_exception_handler(StorageUnavailableError, ...)` returns
  `JSONResponse(status_code=503, content={"detail": "Task storage unavailable"})`.
- `/ready` takes `store: Annotated[TaskStore, Depends(get_task_store)]`; `200 {"status": "ready"}` if
  `store.ping()`, else `JSONResponse(status_code=503, content={"status": "not ready"})`.
- `/health` unchanged and without any store dependency.
- `router.py`: keep both handlers and their signatures; only adjust imports if needed. Validation still happens
  before the store is called (422 unchanged).
- `docs/env-vars.md`: a "Storage" section: `DATABASE_URL` (no default; unset means 503 and not ready), the fixed
  2 s connect / 3 s statement timeouts, `TEST_DATABASE_URL` (tests only).

**Done when:** every acceptance test for AC-002.1 to AC-002.6 and the spec-001 tests pass under `devbox run ci`
(with t2), and `/health` answers 200 with `DATABASE_URL` pointing at a closed port.
