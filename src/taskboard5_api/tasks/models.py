"""Request and response models for tasks."""

import datetime
import re

from pydantic import BaseModel, Field, StrictStr, field_validator

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class TaskCreate(BaseModel):
    """Payload for creating a task."""

    title: StrictStr = Field(min_length=1, max_length=200)
    due_date: StrictStr | None = None

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        """Reject titles made only of whitespace; return the value untrimmed."""
        if not value.strip():
            raise ValueError("title must contain a non-whitespace character")
        return value

    @field_validator("due_date")
    @classmethod
    def _due_date_is_calendar_date(cls, value: str | None) -> str | None:
        """Require a real calendar date in YYYY-MM-DD form."""
        if value is None:
            return value
        if not _DATE_RE.fullmatch(value):
            raise ValueError("due_date must be in YYYY-MM-DD form")
        datetime.date.fromisoformat(value)
        return value


class Task(BaseModel):
    """A stored task."""

    id: str
    title: str
    due_date: str | None
