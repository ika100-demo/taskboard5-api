# Verification — 001 Create and list tasks

**Result:** pass
**Commit:** 7891025 · **Base:** 8022a93 · **Trace:** 8/8 criteria named by tests (smoke: AC-001.1, AC-001.5)

Tests are unchanged since the red commit `3ed97a7` (`git diff 3ed97a7..HEAD -- tests` is empty). `devbox run ci` is green; the smoke tests skip without `SMOKE_BASE_URL` and run against dev after deploy.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-001.1 | met | `tests/test_tasks.py::test_create_task_returns_201_with_id_title_and_null_due_date`, `tests/test_smoke_tasks.py::test_smoke_ac_001_1_create_task` | `src/taskboard5_api/tasks/router.py:15-18`, `src/taskboard5_api/tasks/store.py:18` | Asserts 201, exactly three keys, canonical UUID string, title, `due_date` null. |
| AC-001.2 | met | `tests/test_tasks.py::test_create_task_echoes_due_date_including_past[2026-12-01,2020-01-01]` | `src/taskboard5_api/tasks/models.py:25-34` | Validated string returned unchanged; no comparison with today. |
| AC-001.3 | met | `tests/test_tasks.py::test_invalid_title_is_422_and_nothing_stored` (missing, int, bool, object, array, null, `""`, whitespace, 201 chars) | `src/taskboard5_api/tasks/models.py:14`, `:17-23` | Asserts 422, `detail` list, `loc == ["body","title"]`, and `GET /tasks == []` afterwards. |
| AC-001.4 | met | `tests/test_tasks.py::test_invalid_due_date_is_422_and_nothing_stored` (`tomorrow`, `2026-13-01`, `2026-02-30`, `2026-12-01T10:00:00`, `20261201`) | `src/taskboard5_api/tasks/models.py:8`, `:15`, `:31-33` | Regex fullmatch rejects the time part; `fromisoformat` rejects invalid month/day; `StrictStr` rejects the number. Nothing stored asserted. |
| AC-001.5 | met | `tests/test_tasks.py::test_list_returns_tasks_in_creation_order`, `tests/test_smoke_tasks.py::test_smoke_ac_001_5_list_in_creation_order` | `src/taskboard5_api/tasks/store.py:19-26`, `router.py:21-24` | List equals the three created objects in order; smoke filters by its own ids (shared dev list). |
| AC-001.6 | met | `tests/test_tasks.py::test_list_is_empty_initially` | `src/taskboard5_api/tasks/store.py:13`, `:29` | 200 and `[]`. |
| AC-001.7 | met | `tests/test_tasks.py::test_restart_loses_tasks` | `src/taskboard5_api/tasks/store.py:29-34` | Restart simulated with a fresh `TaskStore` via the design's test seam; the code holds state only in a module-level in-memory object, so a new process starts empty in every environment. |
| AC-001.8 | met | `tests/test_tasks.py::test_title_is_stored_without_trimming[  Buy milk , 200×y]` | `src/taskboard5_api/tasks/models.py:21-23`, `store.py:18` | Asserts 201 and exact title in both POST response and GET list; 200-char title accepted. |

Observation (not blocking): `\d` in `models.py:8` also matches non-ASCII digits; if `date.fromisoformat` accepts them, a full-width date would be stored. No criterion or contract example covers it; consider `[0-9]` or `re.ASCII` later.

## Non-goals

No persistence, no cap, no single-task read/update/delete routes, no filtering/sorting/pagination, no auth, no version prefix. Template-owned code untouched: `main.py` gains only the import and `app.include_router` (`main.py:15`, `:24`); probes, metrics middleware and tracing unchanged. ✔

## Deviations from the plan

- `router.py:16`, `:22` use `Annotated[TaskStore, Depends(get_task_store)]` instead of `= Depends(...)` (ruff B008). Same behaviour; acceptable.
- `tests/test_tasks.py`, `tests/test_smoke_tasks.py` and the spec/plan/design docs are outside every task's `files`: acceptance tests and spec lifecycle files; acceptable.
- g1 (gitops `replicas: 1`) has no `done` and is not in this repo's diff: it is draft PR https://github.com/ika100-demo/taskboard5-gitops/pull/4, `order: before-merge`. Acceptable, provided it is merged before this repo's PR.
- `tasks/__init__.py:1` docstring still says "models and in-memory store" although it now also exports `router`; cosmetic.

## Contract

Matches `design.md`: `POST /tasks` 201 with exactly `id`/`title`/`due_date`, 422 standard FastAPI body with `loc` `["body", field]`, `GET /tasks` 200 array oldest first, no other paths, store behind `get_task_store` with a lock. ✔
