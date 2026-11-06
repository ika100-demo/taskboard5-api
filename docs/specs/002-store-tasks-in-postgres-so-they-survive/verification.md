# Verification — 002 Store tasks in Postgres so they survive restarts and are shared by every instance

**Result:** pass
**Commit:** d9c9e5a · **Base:** 9013abd · **Trace:** 6/6 criteria named by tests (`tests/test_tasks_postgres.py`, unchanged since the red commit 8b5a10a)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-002.1 | met | `tests/test_tasks_postgres.py::test_tasks_survive_restart_in_creation_order` | `src/taskboard5_api/tasks/store.py:80-85` (insert, untrimmed title, uuid4), `store.py:95` (`ORDER BY seq`), `store.py:21` (identity column), `main.py:47-50` (`create_app`) | Creates "A", "  B ", "C" (due 2020-01-01) through one app, reads through a fresh `create_app()`; asserts 200 and list equals the creation responses exactly (id, title, due_date, order). |
| AC-002.2 | met | `tests/test_tasks_postgres.py::test_schema_created_on_startup_and_list_empty` | `main.py:34-40` (lifespan `ensure_schema`), `store.py:59-63` (advisory lock + `CREATE TABLE IF NOT EXISTS`), `store.py:69-71` (lazy fallback) | Drops the table, starts a fresh app, asserts 200 and `[]`. |
| AC-002.3 | met | `tests/test_tasks_postgres.py::test_two_instances_share_tasks_in_order` | `store.py:121-128` (per-app store), `store.py:95` | Two apps alive at once on the same DB; POST on first, GET on second equals created objects in order. |
| AC-002.4 | met | `tests/test_tasks_postgres.py::test_create_during_outage_is_503_and_not_stored` | `store.py:44-46` (connect_timeout=2, statement_timeout=3000), `store.py:48-57` (OperationalError/InterfaceError -> StorageUnavailableError), `main.py:43-44,53` (503 handler) | Asserts 503, exact body, JSON content type, elapsed < 5 s, and after restore GET /tasks (200) has no "lost". Commit happens only on clean exit of the `with` block (`store.py:80-84`). |
| AC-002.5 | met | `tests/test_tasks_postgres.py::test_list_during_outage_is_503` | `store.py:89-105`, `main.py:43-44,53` | Asserts 503, exact body, elapsed < 5 s. |
| AC-002.6 | met | `tests/test_tasks_postgres.py::test_ready_follows_database_health_stays_ok` | `main.py:60-65` (`/ready` via `store.ping()` each call), `store.py:107-118` (ping never raises), `main.py:55-58` (`/health` has no store dependency) | Asserts ready 200 -> cut -> 503 `{"status": "not ready"}`, `/health` 200 `{"status": "ok"}` -> restore -> 200 `{"status": "ready"}` on the same app (no restart). |

Observation (not a failure): the outage tests exercise the "connection refused" case only; the 2 s connect / 3 s
statement timeouts for a hanging database are configured (`store.py:44-46`) but not exercised by a test. The
criteria's "within 5 seconds" is proven for the refused case, which is what the design's test seam specifies.

## Spec-001 regression

`tests/test_tasks.py` now builds `TestClient(create_app())` on `empty_database` (Postgres); AC-001.1..6 and .8 tests
kept with their assertions; only `test_restart_loses_tasks` (AC-001.7, withdrawn per System context "Notes for this
repo") was removed, and spec 001's spec.md/plan.md record the withdrawal. Acceptable.

## Non-goals

The spec lists no non-goals. No code beyond storage, 503 handling and `/ready` was added; `PG*` variables are ignored
as the design says; no template-owned layout (no header/footer/navigation in this API) touched. ✔

## Deviations from the plan

- `docs/adr/001-postgres-task-storage.md`, `docs/specs/001-create-and-list-tasks/{spec,plan}.md` and this spec's
  design/plan/spec are in no task's `files`: planning artefacts (ADR referenced by design.md; AC-001.7 withdrawal
  required by the System context). Acceptable.
- `src/taskboard5_api/tasks/router.py` is listed in t3 but unchanged: the plan allowed "imports only, if any". Acceptable.
- `db_outage` teardown restores then cuts (stops) the relay, whereas design.md says "restores on teardown": test-only,
  no effect on behaviour. Acceptable.
- All tasks t1..t3 are `done: true`.

## Contract

Matches `design.md` and the System context: 503 body `{"detail": "Task storage unavailable"}` (`main.py:44`),
`/ready` 200 `{"status": "ready"}` / 503 `{"status": "not ready"}` (`main.py:64-65`), `/health` 200 independent of
the database, connect timeout 2 s and statement timeout 3 s (`store.py:44-46`), ordering by identity column, ids as
canonical UUID strings, schema as in design.md Data (`store.py:19-27`), `DATABASE_URL` unset -> 503
(`store.py:42-43`). ✔
