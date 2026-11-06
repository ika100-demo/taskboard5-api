# Design — 001 Create and list tasks

## Decisions

- **One `tasks` package, three modules** (models, store, router), mounted into the existing `main.app` with `include_router`. `main.py` keeps its probes and metrics untouched; the feature does not introduce an app factory.
- **In-memory store behind a FastAPI dependency.** `TaskStore` holds the tasks in an insertion-ordered list guarded by a `threading.Lock` (sync handlers run in the threadpool, so concurrent `POST`s must not interleave). A module-level singleton is returned by `get_task_store()`, and handlers receive it through `Depends(get_task_store)`. Reason: tests get a fresh, empty store per test (AC-001.6) and simulate a restart (AC-001.7) with `app.dependency_overrides[get_task_store]`, without touching process globals. A new process starts with an empty store, so AC-001.7 holds in every environment.
- **Strict input validation in the request model, not the handler.** Every rejection is FastAPI's standard `RequestValidationError` 422 body (AC-001.3, AC-001.4); the handler only runs on a valid body, so a rejected request never reaches the store.
  - `title`: `StrictStr` with `min_length=1`, `max_length=200`, plus a field validator that rejects a value with no non-whitespace character. `StrictStr` states "a JSON string, nothing else" in the type itself. The value is never stripped or normalised (AC-001.8).
  - `due_date`: `StrictStr | None`, default `None`. A field validator requires a string that fully matches `^\d{4}-\d{2}-\d{2}$` and parses with `datetime.date.fromisoformat`. Reason: pydantic's native `date` type also accepts Unix timestamps and `"2026-12-01T00:00:00"`, which the spec rules out (AC-001.4). No check against today: past dates are valid (AC-001.2). The validated string is stored and returned unchanged, which is "exactly as sent" (AC-001.2).
  - Unknown extra fields in the body are ignored (pydantic default); the spec does not ask to reject them.
- **Ids** are `str(uuid.uuid4())`, assigned by the store on add (AC-001.1).
- **Single replica, single worker.** The store is per process. The Dockerfile already runs one uvicorn worker; the gitops entry pins `replicas: 1` explicitly (plan task g1) so no environment can be scaled out without first revisiting storage (spec Non-goals).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard5_api/tasks/__init__.py` | re-exports `Task`, `TaskCreate`, `TaskStore`, `get_task_store` (t1) and `router` (t2) | new |
| `src/taskboard5_api/tasks/models.py` | `TaskCreate` (request), `Task` (response) pydantic models and their validators | new |
| `src/taskboard5_api/tasks/store.py` | `TaskStore` (thread-safe, insertion-ordered), `get_task_store()` singleton dependency | new |
| `src/taskboard5_api/tasks/router.py` | `APIRouter` with `POST /tasks`, `GET /tasks` | new |
| `src/taskboard5_api/main.py` | `app.include_router(tasks_router)` | changed |

Public interface (signatures only):

```python
# models.py
class TaskCreate(BaseModel):
    title: StrictStr                   # 1..200 chars, at least one non-whitespace char, not trimmed
    due_date: StrictStr | None = None  # "YYYY-MM-DD", a real calendar date

class Task(BaseModel):
    id: str                   # UUID string
    title: str
    due_date: str | None

# store.py
class TaskStore:
    def add(self, data: TaskCreate) -> Task: ...   # assigns id, appends, returns the stored Task
    def list(self) -> list[Task]: ...              # a copy, oldest first

def get_task_store() -> TaskStore: ...             # the process-wide instance
```

## Contract

All bodies are `application/json`. No path prefix, no auth.

### `POST /tasks`

Request body:

```json
{"title": "Buy milk", "due_date": "2026-12-01"}
```

| Field | Type | Required | Rules |
|---|---|---|---|
| `title` | string | yes | 1 to 200 characters; not only whitespace; stored exactly as sent (no trimming) |
| `due_date` | string or `null` | no (default `null`) | `YYYY-MM-DD`, a valid calendar date; past dates allowed; no time part |

Responses:

- `201 Created` — the created task (AC-001.1, AC-001.2, AC-001.8):
  ```json
  {"id": "3f1c2e8a-6b0d-4c47-9a51-2d7e0b9f4a10", "title": "Buy milk", "due_date": null}
  ```
  `id` is a UUID string assigned by the server; `title` and `due_date` are exactly the values sent (`null` when `due_date` was omitted or `null`). The body has exactly these three keys.
- `422 Unprocessable Entity` — FastAPI's standard validation body; nothing is stored (AC-001.3, AC-001.4):
  ```json
  {"detail": [{"type": "<error type>", "loc": ["body", "title"], "msg": "<message>", "input": <value>}]}
  ```
  The binding part of the contract is: status `422`, a top-level `detail` array, and at least one entry whose `loc` is `["body", "title"]` (title errors) or `["body", "due_date"]` (due date errors). The `type`, `msg`, `input` (and any `ctx`/`url`) values are the framework's and are not part of the contract; tests must not assert on them. A missing title, a non-string title (number, boolean, object, array, `null`), `""`, a whitespace-only title and a 201-character title all yield a `title` entry. `"tomorrow"`, `"2026-13-01"`, `"2026-02-30"`, `"2026-12-01T10:00:00"` and a non-string `due_date` (for example `20261201`) all yield a `due_date` entry.

### `GET /tasks`

- `200 OK` — a JSON array of every task held by this process, in creation order, oldest first; each element equals the object `POST /tasks` returned for it (AC-001.5). `[]` when no task was created since the process started (AC-001.6, AC-001.7).
  ```json
  [{"id": "…", "title": "A", "due_date": null}, {"id": "…", "title": "B", "due_date": "2026-12-01"}]
  ```

No other methods or paths are added (`GET /tasks/{id}` stays `404`, other methods on `/tasks` stay `405`, per the framework; spec Non-goals).

### Test seam

Acceptance tests isolate state by overriding the dependency:

```python
from taskboard5_api.main import app
from taskboard5_api.tasks import TaskStore, get_task_store

app.dependency_overrides[get_task_store] = lambda: store   # store = TaskStore(), one per test; clear the override afterwards
```

A restart (AC-001.7) is a new `TaskStore()` in the override. Smoke tests (AC-001.1, AC-001.5) reach the service only through `SMOKE_BASE_URL`, create `smoke-<uuid>` titles, carry `@pytest.mark.writes` and assert only on the tasks they created and their relative order (the list is shared in dev).

## Data

In memory only: `list[Task]` inside `TaskStore`, lost on process exit. No cap (spec Non-goals). No migration.

## Risks

- **More than one replica or worker** would split the list between processes (a `GET` would miss tasks). Mitigated by g1 (explicit `replicas: 1` in system.yaml) and the existing single-worker `CMD`; storage is a later spec.
- **Unbounded memory**: no cap by decision; the 512Mi limit in system.yaml restarts the pod (emptying the list) if it is ever reached.
