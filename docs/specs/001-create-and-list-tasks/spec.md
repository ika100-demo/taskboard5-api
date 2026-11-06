---
spec_id: 001-create-and-list-tasks
title: Create and list tasks
status: done
priority: P1
shape: service-python
---

# 001 — Create and list tasks

## Problem

The taskboard5 Task API has health, readiness and ping endpoints but no tasks yet, so no client of the taskboard5 system can record or show any work. Callers need a minimal way to add a task, with a title and optionally a due date, and to read back all tasks. Keeping the tasks in memory is enough for now: it lets the rest of the system be built against a real API before storage is decided.

## Stories

As a client of the Task API, I want to create a task with a title and an optional due date, so that the work is recorded.

As a client of the Task API, I want to list all tasks, so that I can show what has been recorded.

## Acceptance criteria

- **AC-001.1** Given the service is running, when a caller sends `POST /tasks` with `{"title": "Buy milk"}`, then the response is `201` with a JSON body holding a server-assigned `id` (a UUID string), `"title": "Buy milk"` and `"due_date": null`. (smoke)
- **AC-001.2** Given the service is running, when a caller sends `POST /tasks` with `{"title": "File taxes", "due_date": "2026-12-01"}` or with a past date such as `"2020-01-01"`, then the response is `201` and the body holds the `due_date` exactly as sent.
- **AC-001.3** Given the service is running, when a caller sends `POST /tasks` with the title missing, not a string, empty, only whitespace, or longer than 200 characters, then the response is `422` with the framework's standard validation error body naming the `title` field, and no task is added to the list.
- **AC-001.4** Given the service is running, when a caller sends `POST /tasks` with a `due_date` that is not a calendar date in `YYYY-MM-DD` form (for example `"tomorrow"`, `"2026-13-01"`, `"2026-02-30"` or `"2026-12-01T10:00:00"`), then the response is `422` with the framework's standard validation error body naming the `due_date` field, and no task is added to the list.
- **AC-001.5** Given tasks "A", "B" and "C" were created in that order, when a caller sends `GET /tasks`, then the response is `200` with a JSON array of those three tasks in creation order (oldest first), each with `id`, `title` and `due_date` as they were returned on creation. (smoke)
- **AC-001.6** Given no task has been created since the service started, when a caller sends `GET /tasks`, then the response is `200` with an empty JSON array `[]`.
- **AC-001.7** Given tasks were created, when the service restarts, then `GET /tasks` returns `[]` (tasks are kept in memory only, in every environment).
- **AC-001.8** Given the service is running, when a caller sends `POST /tasks` with `{"title": "  Buy milk "}` (a 200-character title is also accepted), then the response is `201` and the title in the response and in `GET /tasks` is exactly as sent, without trimming.

## Non-goals

- Persistent storage; tasks are lost on restart.
- A cap on the number of tasks held in memory.
- Reading, updating, completing or deleting a single task.
- Filtering, sorting options, search or pagination of the list.
- Authentication, users or per-user task lists.
- A version prefix on the path.
- Consistency across several running instances. Deployment dependency: the taskboard5 system runs this service with exactly one replica until storage exists; that is set in the taskboard5 gitops repo's `system.yaml`, not in this repo.

## Open questions

- ~~Confirm: the resource path is `/tasks`, with no version prefix?~~ Answered: yes, see AC-001.1 to AC-001.6.
- ~~What form should task ids take?~~ Answered: server-assigned UUID strings, see AC-001.1.
- ~~What is the maximum title length, and should whitespace be trimmed?~~ Answered: 1 to 200 characters, whitespace-only rejected, stored exactly as sent, see AC-001.3 and AC-001.8.
- ~~What format does `due_date` use?~~ Answered: optional, date only `YYYY-MM-DD`, see AC-001.2 and AC-001.4.
- ~~May a due date lie in the past?~~ Answered: yes, see AC-001.2.
- ~~In what order does the list return tasks?~~ Answered: creation order, oldest first, see AC-001.5.
- ~~Confirm the response codes?~~ Answered: `201` create, `200` list, `422` with the framework's standard error body, see AC-001.1 to AC-001.6.
- ~~Should the number of tasks be capped?~~ Answered: no cap, see Non-goals.
- ~~Exactly one replica until storage exists?~~ Answered: yes, set in the taskboard5 gitops repo, see Non-goals (deployment dependency).
- ~~Confirm: a restart empties the list in every environment?~~ Answered: yes, see AC-001.7.

## Changelog

- 2026-11-06 created
- 2026-11-06 amended: open questions answered; clarified AC-001.2 (past dates accepted), AC-001.3/AC-001.4 (standard error body), AC-001.5 (oldest first), AC-001.7 (every environment); added AC-001.8 (title stored without trimming); one-replica deployment dependency recorded under Non-goals.
- 2026-11-06 approved
- 2026-11-06 building
- 2026-11-06 done
