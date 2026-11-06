---
spec_id: 001-create-and-list-tasks
shape: service-python
spec_hash: 756184979554
summary: In-memory POST /tasks and GET /tasks with strict title and due-date validation, one replica pinned in gitops
tasks:
  - id: t1
    title: Add task models and the in-memory task store
    files: [src/taskboard5_api/tasks/__init__.py, src/taskboard5_api/tasks/models.py, src/taskboard5_api/tasks/store.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7, AC-001.8]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Add the tasks router and mount it in the app
    files: [src/taskboard5_api/tasks/router.py, src/taskboard5_api/tasks/__init__.py, src/taskboard5_api/main.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7, AC-001.8]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: g1
    title: Pin taskboard5-api to exactly one replica in system.yaml
    repo: ika100-demo/taskboard5-gitops
    order: before-merge
    files: [applications/taskboard5/system.yaml]
    apps: [taskboard5-api-dev]
    covers: [AC-001.5]
    parallel_safe: true
    depends_on: []
---

# Plan — 001 Create and list tasks

Contract, validation rules and the test seam are in [design.md](design.md). Level 1: t1 and g1 in parallel; level 2: t2.

## t1 — Add task models and the in-memory task store

**Files:** src/taskboard5_api/tasks/__init__.py, src/taskboard5_api/tasks/models.py, src/taskboard5_api/tasks/store.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7, AC-001.8
**Goal:** the request/response models that encode every validation rule of the spec, and a thread-safe, insertion-ordered in-memory store reachable through a FastAPI dependency that tests can override.

**Implementation notes:**
- `models.py`: `TaskCreate.title: StrictStr = Field(min_length=1, max_length=200)` plus a `field_validator("title")` that raises `ValueError` when `not value.strip()`; it returns the value unchanged (no trimming, AC-001.8).
- `TaskCreate.due_date: StrictStr | None = None` (so `20261201` is rejected) with a `field_validator("due_date")` that, for non-`None`, requires `re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)` and a successful `datetime.date.fromisoformat(value)` (rejects `"tomorrow"`, `"2026-13-01"`, `"2026-02-30"`, `"2026-12-01T10:00:00"`), raising `ValueError` otherwise; it returns the string unchanged. No comparison with today (past dates allowed, AC-001.2).
- `Task`: `id: str`, `title: str`, `due_date: str | None`; serialises to exactly those three keys.
- `store.py`: `TaskStore` holding a `list[Task]` and a `threading.Lock`; `add(data: TaskCreate) -> Task` assigns `str(uuid.uuid4())`, appends under the lock and returns the task; `list() -> list[Task]` returns a copy under the lock, oldest first. No cap.
- `store.py`: a module-level `_store = TaskStore()` and `get_task_store() -> TaskStore` returning it.
- `__init__.py`: re-export `Task`, `TaskCreate`, `TaskStore`, `get_task_store` (`__all__`). t2 adds `router`.
- Docstrings and full type hints; `devbox run quality` clean.

**Done when:** `devbox run quality` passes; the HTTP acceptance tests for AC-001.1 to AC-001.8 can pass only after t2.

## t2 — Add the tasks router and mount it in the app

**Files:** src/taskboard5_api/tasks/router.py, src/taskboard5_api/tasks/__init__.py, src/taskboard5_api/main.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7, AC-001.8
**Goal:** expose `POST /tasks` (201) and `GET /tasks` (200) exactly as the design contract states, backed by the store from t1.

**Implementation notes:**
- `router.py`: `router = APIRouter(tags=["tasks"])`; `@router.post("/tasks", status_code=201, response_model=Task)` taking `body: TaskCreate` and `store: TaskStore = Depends(get_task_store)`, returning `store.add(body)`.
- `@router.get("/tasks", response_model=list[Task])` with the same dependency, returning `store.list()`.
- Sync handlers (`def`), consistent with `main.py`; validation errors stay FastAPI's default 422 handler (no custom exception handler).
- `__init__.py`: add `router` to the re-exports.
- `main.py`: `from .tasks import router as tasks_router` and `app.include_router(tasks_router)`; leave `/health`, `/ready`, `/ping`, `/metrics` and the middleware unchanged.
- The metrics middleware labels the new route `/tasks` automatically; nothing to add.

**Done when:** every acceptance test for AC-001.1 to AC-001.8 passes (the smoke tests for AC-001.1 and AC-001.5 against dev after deploy), and the existing health, metrics and tracing tests still pass under `devbox run ci`.

## g1 — Pin taskboard5-api to exactly one replica in system.yaml

**Repo:** ika100-demo/taskboard5-gitops (order: before-merge)
**Files:** applications/taskboard5/system.yaml
**Covers:** AC-001.5
**Goal:** make the spec's deployment dependency explicit: the in-memory list is only complete when one process serves every request, so the component runs with exactly one replica in every environment until storage exists. Today the replica count is only the renderer's default.

**Implementation notes:**
- Under `components.taskboard5-api`, add `replicas: 1` at the component level (it applies to dev now and to staging/prod once `/instance:promote` adds them), with the comment `# exactly one until storage exists (taskboard5-api spec 001: tasks are held in memory)`.
- Add no `scale:` and no per-instance `replicas`.
- Run `devbox run render`; the rendered dev Deployment already has `replicas: 1`, so no generated file should change. If one does, it joins this task's files.
- `devbox run ci` in the gitops repo passes.

**Done when:** `system.yaml` carries the explicit `replicas: 1`, `devbox run render-check` is clean, and the `taskboard5-api-dev` Argo app is Synced/Healthy.
