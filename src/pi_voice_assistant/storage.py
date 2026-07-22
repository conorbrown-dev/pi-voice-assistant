from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from .models import Reminder, Todo


class Store:
    def __init__(self, database: Path) -> None:
        database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database)
        self.connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY,
                text TEXT NOT NULL COLLATE NOCASE,
                created_at TEXT NOT NULL,
                archived_at TEXT
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                due_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'announced', 'completed')),
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS due_reminders ON reminders(status, due_at);
            """
        )
        self.connection.commit()

    @staticmethod
    def _time(value: datetime) -> str:
        return value.isoformat(timespec="seconds")

    @staticmethod
    def _parse_time(value: str) -> datetime:
        return datetime.fromisoformat(value)

    def add_todo(self, text: str, now: datetime) -> Todo:
        cursor = self.connection.execute(
            "INSERT INTO todos(text, created_at) VALUES (?, ?)", (text, self._time(now))
        )
        self.connection.commit()
        return Todo(cursor.lastrowid, text, now, None)

    def list_todos(self) -> list[Todo]:
        rows = self.connection.execute(
            "SELECT * FROM todos WHERE archived_at IS NULL ORDER BY created_at, id"
        ).fetchall()
        return [Todo(r["id"], r["text"], self._parse_time(r["created_at"]), None) for r in rows]

    def archive_todo(self, text: str, now: datetime) -> Todo | None:
        row = self.connection.execute(
            "SELECT * FROM todos WHERE archived_at IS NULL AND text = ? ORDER BY id LIMIT 1", (text,)
        ).fetchone()
        if row is None:
            return None
        self.connection.execute("UPDATE todos SET archived_at = ? WHERE id = ?", (self._time(now), row["id"]))
        self.connection.commit()
        return Todo(row["id"], row["text"], self._parse_time(row["created_at"]), now)

    def add_reminder(self, text: str, due_at: datetime, now: datetime) -> Reminder:
        cursor = self.connection.execute(
            "INSERT INTO reminders(text, due_at, status, created_at) VALUES (?, ?, 'pending', ?)",
            (text, self._time(due_at), self._time(now)),
        )
        self.connection.commit()
        return Reminder(cursor.lastrowid, text, due_at, "pending", now)

    def due_reminders(self, now: datetime) -> list[Reminder]:
        rows = self.connection.execute(
            "SELECT * FROM reminders WHERE status = 'pending' AND due_at <= ? ORDER BY due_at, id",
            (self._time(now),),
        ).fetchall()
        return [self._reminder(row) for row in rows]

    def requeue_announced_reminders(self) -> None:
        """Make reminders awaiting a response audible again after a service restart."""
        self.connection.execute("UPDATE reminders SET status = 'pending' WHERE status = 'announced'")
        self.connection.commit()

    def mark_announced(self, reminder_id: int) -> None:
        self.connection.execute("UPDATE reminders SET status = 'announced' WHERE id = ?", (reminder_id,))
        self.connection.commit()

    def complete_reminder(self, reminder_id: int) -> None:
        self.connection.execute("UPDATE reminders SET status = 'completed' WHERE id = ?", (reminder_id,))
        self.connection.commit()

    def snooze_reminder(self, reminder_id: int, due_at: datetime) -> None:
        self.connection.execute(
            "UPDATE reminders SET status = 'pending', due_at = ? WHERE id = ?", (self._time(due_at), reminder_id)
        )
        self.connection.commit()

    def _reminder(self, row: sqlite3.Row) -> Reminder:
        return Reminder(row["id"], row["text"], self._parse_time(row["due_at"]), row["status"], self._parse_time(row["created_at"]))
