from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Todo:
    id: int
    text: str
    created_at: datetime
    archived_at: datetime | None


@dataclass(frozen=True)
class Reminder:
    id: int
    text: str
    due_at: datetime
    status: str
    created_at: datetime

