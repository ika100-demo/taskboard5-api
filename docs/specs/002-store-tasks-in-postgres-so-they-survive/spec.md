---
spec_id: 002-store-tasks-in-postgres-so-they-survive
title: Store tasks in Postgres so they survive restarts and are shared by every instance
status: building
priority: P1
shape: service-python
parent: ika100-demo/taskboard5-gitops:001-persistent-tasks-and-web-task-board
---

# 002 — Store tasks in Postgres so they survive restarts and are shared by every instance

## Problem

The taskboard5 Task API can create and list tasks, but it holds them in memory: every restart or redeploy empties the list, and the API must run as exactly one instance. The taskboard5 website shows only a starter page, so nobody can see or add tasks without calling the API by hand. Tasks need to survive restarts and people need a page where they can read the board and add to it; only then is the system usable as a task board.

## System context

Slice of the system plan `001-persistent-tasks-and-web-task-board` in `ika100-demo/taskboard5-gitops` for `taskboard5-api` (service-python). The system criteria and the contract below are binding: every criterion of this spec implements one of them and names it: `(system AC-<NNN>.<n>)`.

### System criteria

- **AC-001.1** Given tasks "A", "B" and "C" were created in that order, when the Task API is restarted or redeployed, then `GET /tasks` returns `200` with the same three tasks, each with the same `id`, `title` and `due_date` as returned on creation, in creation order (oldest first).
- **AC-001.2** Given the task storage is unreachable, when a caller sends `POST /tasks` or `GET /tasks`, then the response is `503` with a JSON error body, no task is added, and the Task API's readiness check reports not ready until storage is reachable again.
- **AC-001.9** Given the Task API runs as 2 instances in dev, when a task is created through one instance, then `GET /tasks` answered by the other instance lists it, with the same `id`, `title` and `due_date`.

### Contract

The only cross-repo calls are from the taskboard5-web **server** to the Task API. The browser talks only to
taskboard5-web. Base URL: env var `API_URL` on the web server (dev: `http://taskboard5-api`, no trailing slash).
All bodies are JSON (`Content-Type: application/json`), UTF-8.

**Task object**

| field | type | notes |
|---|---|---|
| `id` | string | server-assigned UUID |
| `title` | string | 1 to 200 characters, not only whitespace, stored and returned exactly as sent (no trimming) |
| `due_date` | string or null | calendar date `YYYY-MM-DD`; past dates allowed; `null` when none |

**`GET /tasks`**: no parameters.
- `200` — JSON array of Task objects, every task, oldest first (creation order). `[]` when there is none.
- `503` — `{"detail": "Task storage unavailable"}` when the database cannot be reached.

**`POST /tasks`**: body `{"title": "<string>", "due_date": "<YYYY-MM-DD>" | null}`; `due_date` may be omitted.
The web app sends `due_date: null` when no date is picked.
- `201` — the created Task object. It is durable and visible to `GET /tasks` on every instance once returned.
- `422` — FastAPI's standard validation body `{"detail": [{"loc": ["body", "title"|"due_date"], "msg": ..., "type": ...}, ...]}`; nothing stored.
- `503` — `{"detail": "Task storage unavailable"}`; nothing stored.

**`GET /ready`** (Kubernetes probe, not called by the web app): `200 {"status": "ready"}` when the database answers,
`503 {"status": "not ready"}` otherwise. **`GET /health`**: `200` regardless of the database.

**Web app (browser-facing, same origin):** `GET /` renders the board; the add-task submit goes to a same-origin
endpoint of the web app (Server Action or `/api/...` route; the web repo picks). The board's texts are exactly:
"No tasks yet", "No due date", "Title is required", "Title must be at most 200 characters",
"Tasks could not be loaded. Please try again later.", "The task could not be saved. Please try again."

### Errors

- Task API errors are JSON with a `detail` field: a string for `503`, FastAPI's validation list for `422`.
  Unhandled server errors are `500` with a JSON body; callers must not rely on its content.
- The web server treats `GET /tasks` as successful only on `200` with a JSON array; anything else (`503`, `500`,
  any other status, a non-JSON or malformed body, a connection error, a timeout) shows
  "Tasks could not be loaded. Please try again later." and the page itself still answers `200`.
- The web server treats `POST /tasks` as successful only on `201` with a Task object. A `422` whose `loc` names
  `title` shows the matching title message next to the field (normally prevented by the form's own check);
  every other outcome (`422` on `due_date`, `503`, `500`, any other status, a malformed body, a connection error,
  a timeout) shows "The task could not be saved. Please try again." In every failure case the entered values stay
  and the task is not added to the board. The web app does not retry automatically.
- The web app never forwards Task API error bodies or its URL to the browser.

### Timeouts

- Web server -> `GET /tasks`: 5 seconds total (connect + response). On timeout: the load-error message.
- Web server -> `POST /tasks`: 5 seconds total. On timeout: the save-error message. A create that the API completed
  after the timeout may show up on the next page reload; that is accepted (no idempotency key in this spec).
- Task API -> Postgres: connect timeout 2 seconds, statement timeout 3 seconds, so a request with storage down
  answers `503` within 5 seconds. `/ready` uses the same 2-second connect timeout.
- Task API down or not ready: Kubernetes removes not-ready pods from the Service; when no pod is ready, the web
  server gets a connection error and shows the load or save message. The web app's own `/api/ready` does not
  depend on the Task API, so the board stays up while the API is down.

### Provided by the system

The gitops part of this plan wires these for this repo; rely on them, do not ask for them again:

- resource `postgres`: env `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`

### Notes for this repo

Withdraw AC-001.7 of this repo's spec 001 (restart empties the list) and its "Persistent storage" and
"Consistency across several running instances" non-goals; every other criterion of spec 001 (shapes, 201/200/422,
untrimmed titles, UUID ids) stays as it is and its tests must keep passing against Postgres.
Connection settings come from DATABASE_URL (also PG* are injected). Creation order must not rely on clock time
alone across instances: use a database sequence / identity column for ordering.
Tests need a real Postgres (testcontainers or the devbox service); the unreachable case can stop the container
or point DATABASE_URL at a closed port.

## Stories

<!-- As a <persona>, I want <goal>, so that <benefit>. -->

## Acceptance criteria

- **AC-002.1** Given tasks "A", "B" and "C" were created with POST /tasks in that order (one with due_date "2020-01-01", one with the title "  B "), when the service is restarted against the same database, then GET /tasks returns 200 with exactly those three tasks, each with the id, title and due_date returned on creation, oldest first (system AC-001.1)
- **AC-002.2** Given the database named by DATABASE_URL has no tasks table yet, when the service starts, then it creates its schema itself and GET /tasks returns 200 with [] (system AC-001.1)
- **AC-002.3** Given two service instances use the same database, when a task is created with POST /tasks on the first, then GET /tasks on the second lists it with the same id, title and due_date, in creation order (system AC-001.9)
- **AC-002.4** Given the database is unreachable, when a caller sends POST /tasks with a valid body, then the response is 503 with {"detail": "Task storage unavailable"} within 5 seconds, and after the database is reachable again GET /tasks does not contain that task (system AC-001.2)
- **AC-002.5** Given the database is unreachable, when a caller sends GET /tasks, then the response is 503 with {"detail": "Task storage unavailable"} within 5 seconds (system AC-001.2)
- **AC-002.6** Given the database is unreachable, when GET /ready is called, then it answers 503 with {"status": "not ready"} while GET /health still answers 200; once the database is reachable again, GET /ready answers 200 with {"status": "ready"} without a restart (system AC-001.2)

## Non-goals

## Open questions

<!-- One bullet per question the user must answer; approval is refused while any is open. Strike answered ones (~~…~~) and fold the answer into the criteria. -->

## Changelog

- 2026-11-06 created from the system plan, with its criteria (spec 147)
- 2026-11-06 approved
- 2026-11-06 building
