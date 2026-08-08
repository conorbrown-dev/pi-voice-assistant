from __future__ import annotations

from datetime import datetime, timedelta

from .commands import normalize_phrase, parse, parse_reminder_schedule, parse_reminder_time, strip_punctuation
from .models import Reminder
from .storage import Store


class Assistant:
    def __init__(self, store: Store, wake_word: str | None = None, wake_timeout_seconds: int = 20) -> None:
        self.store = store
        self.store.requeue_announced_reminders()
        self.awaiting_reminder: Reminder | None = None
        self.awaiting_todo = False
        self.awaiting_reminder_task = False
        self.pending_reminder_text: str | None = None
        wake_word_label = " ".join((wake_word or "").split())
        self.wake_word = wake_word_label.lower() or None
        self.wake_word_label = wake_word_label
        self.wake_timeout = timedelta(seconds=wake_timeout_seconds)
        self.awake_until: datetime | None = None

    def handle(self, spoken: str, now: datetime | None = None) -> str | None:
        now = now or datetime.now()
        if self.awaiting_todo:
            return self._add_requested_todo(spoken, now)
        if self.awaiting_reminder_task or self.pending_reminder_text is not None:
            return self._add_requested_reminder(spoken, now)
        if self._is_wake_word(spoken):
            self.awake_until = now + self.wake_timeout
            return "How can I help?"
        spoken = self._command_after_wake_word(spoken, now)
        if spoken is None:
            return None
        command = parse(spoken, now)
        if command.kind == "help":
            return self.help_text()
        if command.kind == "add_todo":
            text = self._todo_text(command.text)
            self.store.add_todo(text, now)
            return f"Confirmed. Todo added successfully: {text}."
        if command.kind == "add_todo_prompt":
            self.awaiting_todo = True
            return "What todo would you like to add?"
        if command.kind == "list_todos":
            todos = self.store.list_todos()
            if not todos:
                return "You have no active todos."
            return "Your todos are: " + "; ".join(strip_punctuation(todo.text) for todo in todos) + "."
        if command.kind == "archive_todo":
            todo = self.store.archive_todo(command.text, now)
            return f"Confirmed. Todo archived successfully: {strip_punctuation(todo.text)}." if todo else f"I could not find an active todo named {command.text}."
        if command.kind == "add_reminder":
            return self._save_reminder(command.text, command.due_at, now, command.recurrence)  # type: ignore[arg-type]
        if command.kind == "add_reminder_prompt":
            self.awaiting_reminder_task = True
            return "What should I remind you about?"
        if command.kind == "invalid_reminder":
            return f"Please say a reminder such as: {self.begin_with_wake_word('say remind me to call Sam in 10 minutes.')}"
        if command.kind == "complete_reminder":
            if not self.awaiting_reminder:
                return "There is no reminder waiting for confirmation."
            repeats = self.store.complete_reminder(self.awaiting_reminder.id, now)
            self.awaiting_reminder = None
            return "Confirmed. Recurring reminder scheduled for its next occurrence." if repeats else "Confirmed. Reminder marked complete."
        if command.kind == "snooze_reminder":
            if not self.awaiting_reminder:
                return "There is no reminder waiting to delay."
            due_at = now + timedelta(minutes=command.minutes or 0)
            self.store.snooze_reminder(self.awaiting_reminder.id, due_at)
            self.awaiting_reminder = None
            return f"Confirmed. Reminder delayed for {command.minutes} minutes."
        return f"I did not understand that. {self.begin_with_wake_word('say list commands')} to hear what I can do."

    def _is_wake_word(self, spoken: str) -> bool:
        return bool(self.wake_word and normalize_phrase(spoken) == self.wake_word)

    def begin_with_wake_word(self, command: str) -> str:
        if self.wake_word:
            return f"Say {self.wake_word_label}, then {command}"
        return command[:1].upper() + command[1:]

    def help_text(self) -> str:
        return (
            "You can say add todo, or add reminder followed by what and when. "
            "You can also say list todos, or archive todo followed by its name. "
            "The command categories are todos and reminders. "
            "A reminder can repeat every hour, every 3 hours, or every day at 7 am. "
            "For an announced reminder, say done, or delay followed by minutes."
        )

    def _add_requested_todo(self, spoken: str, now: datetime) -> str:
        text = self._todo_text(spoken)
        if not text:
            return "I did not hear a todo. What todo would you like to add?"
        self.awaiting_todo = False
        self.store.add_todo(text, now)
        return f"Confirmed. Todo added successfully: {text}."

    def _add_requested_reminder(self, spoken: str, now: datetime) -> str:
        if self.awaiting_reminder_task:
            text = strip_punctuation(spoken)
            if not text:
                return "I did not hear the reminder. What should I remind you about?"
            self.awaiting_reminder_task = False
            self.pending_reminder_text = text
            return f"When should I remind you about {text}?"
        schedule_text = strip_punctuation(spoken)
        due_at, recurrence = parse_reminder_schedule(schedule_text, now)
        if due_at is None:
            due_at = parse_reminder_time(schedule_text, now)
        if due_at is None:
            return "Please say when, for example: in 10 minutes, every hour, or every day at 7 am."
        text = self.pending_reminder_text
        self.pending_reminder_text = None
        return self._save_reminder(text, due_at, now, recurrence)

    def _save_reminder(self, text: str, due_at: datetime, now: datetime, recurrence: str | None = None) -> str:
        reminder = self.store.add_reminder(strip_punctuation(text), due_at, now, recurrence)
        clock = reminder.due_at.strftime("%I:%M %p").lstrip("0")
        prefix = "Confirmed. Recurring reminder set" if recurrence else "Confirmed. Reminder set"
        return f"{prefix} for {reminder.due_at.strftime('%A')} at {clock}: {reminder.text}."

    @staticmethod
    def _todo_text(text: str) -> str:
        return strip_punctuation(text)

    def _command_after_wake_word(self, spoken: str, now: datetime) -> str | None:
        if not self.wake_word:
            return spoken
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
            if self.wake_word:
                instruction = (
                    f"Say {self.wake_word_label}, then say done, or say {self.wake_word_label}, "
                    "then say delay followed by a number of minutes."
                )
            else:
                instruction = "Say done, or delay followed by a number of minutes."
            messages.append(f"Reminder: {strip_punctuation(reminder.text)}. {instruction}")
        return messages
