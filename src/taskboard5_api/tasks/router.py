"""HTTP routes for tasks."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from taskboard5_api.tasks.models import Task, TaskCreate
from taskboard5_api.tasks.store import TaskStore, get_task_store

router = APIRouter(tags=["tasks"])


@router.post("/tasks", status_code=201, response_model=Task)
def create_task(body: TaskCreate, store: Annotated[TaskStore, Depends(get_task_store)]) -> Task:
    """Create a task."""
    return store.add(body)


@router.get("/tasks", response_model=list[Task])
def list_tasks(store: Annotated[TaskStore, Depends(get_task_store)]) -> list[Task]:
    """List all tasks, oldest first."""
    return store.list()
