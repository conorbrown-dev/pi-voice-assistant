from __future__ import annotations

import re
from datetime import datetime, timedelta

from .commands import HELP, parse
from .models import Reminder
from .storage import Store


class Assistant:
    def __init__(self, store: Store, wake_word: str | None = None, wake_timeout_seconds: int = 8) -> None:
        self.store = store
        self.store.requeue_announced_reminders()
        self.awaiting_reminder: Reminder | None = None
        self.wake_word = " ".join((wake_word or "").lower().split()) or None
        self.wake_timeout = timedelta(seconds=wake_timeout_seconds)
        self.awake_until: datetime | None = None

    def handle(self, spoken: str, now: datetime | None = None) -> str | None:
        now = now or datetime.now()
        spoken = self._command_after_wake_word(spoken, now)
        if spoken is None:
            return None
        command = parse(spoken, now)
        if command.kind == "help":
            return HELP
        if command.kind == "add_todo":
            self.store.add_todo(command.text, now)
            return f"Added todo: {command.text}."
        if command.kind == "list_todos":
            todos = self.store.list_todos()
            if not todos:
                return "You have no active todos."
            return "Your todos are: " + "; ".join(todo.text for todo in todos) + "."
        if command.kind == "archive_todo":
            todo = self.store.archive_todo(command.text, now)
            return f"Archived todo: {todo.text}." if todo else f"I could not find an active todo named {command.text}."
        if command.kind == "add_reminder":
            reminder = self.store.add_reminder(command.text, command.due_at, now)  # type: ignore[arg-type]
            clock = reminder.due_at.strftime("%I:%M %p").lstrip("0")
            return f"Reminder set for {reminder.due_at.strftime('%A')} at {clock}: {reminder.text}."
        if command.kind == "invalid_reminder":
            return "Please say a reminder such as: remind me to call Sam in 10 minutes."
        if command.kind == "complete_reminder":
            if not self.awaiting_reminder:
                return "There is no reminder waiting for confirmation."
            self.store.complete_reminder(self.awaiting_reminder.id)
            self.awaiting_reminder = None
            return "Great, I marked that reminder complete."
        if command.kind == "snooze_reminder":
            if not self.awaiting_reminder:
                return "There is no reminder waiting to delay."
            due_at = now + timedelta(minutes=command.minutes or 0)
            self.store.snooze_reminder(self.awaiting_reminder.id, due_at)
            self.awaiting_reminder = None
            return f"Okay, I will remind you again in {command.minutes} minutes."
        return "I did not understand that. Say list commands to hear what I can do."

    def _command_after_wake_word(self, spoken: str, now: datetime) -> str | None:
        if not self.wake_word:
            return spoken
        normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", spoken.lower()).split())
        if normalized == self.wake_word:
            self.awake_until = now + self.wake_timeout
            return None
        match = re.match(rf"^\s*{re.escape(self.wake_word)}(?:\s+|[,.!?]+)(.+)$", spoken, re.IGNORECASE)
        if match:
            self.awake_until = None
            return match.group(1).strip()
        if self.awake_until and now <= self.awake_until:
            self.awake_until = None
            return spoken
        self.awake_until = None
        return None

    def check_reminders(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now()
        if self.awaiting_reminder:
            return []
        messages: list[str] = []
        reminders = self.store.due_reminders(now)
        if reminders:
            reminder = reminders[0]
            self.store.mark_announced(reminder.id)
            self.awaiting_reminder = reminder
            messages.append(f"Reminder: {reminder.text}. Say done, or delay followed by a number of minutes.")
        return messages
