from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Command:
    kind: str
    text: str = ""
    due_at: datetime | None = None
    minutes: int | None = None


HELP = (
    "You can say: add todo followed by a task; list todos; archive todo followed by a task; "
    "or remind me to do something in 10 minutes, at 3 pm, or at 3 pm tomorrow."
)


def parse(text: str, now: datetime) -> Command:
    raw_phrase = " ".join(text.strip().split())
    # Vosk transcripts do not include punctuation consistently and sometimes
    # hear the final "s" in "commands" as singular.  Normalize those
    # presentation differences before matching fixed commands.
    phrase = re.sub(r"[^a-z0-9']+", " ", raw_phrase.lower()).strip()
    if phrase in {
        "list command",
        "list commands",
        "just commands",
        "help",
        "what can i say",
        "what are the commands",
        "commands",
    }:
        return Command("help")
    if phrase in {"list todo", "list todos", "list todo items", "list my todos"}:
        return Command("list_todos")
    match = re.fullmatch(r"(?:add )?todo(?: item)?(?: called)? (.+)", raw_phrase, re.IGNORECASE)
    if match:
        return Command("add_todo", match.group(1))
    match = re.fullmatch(r"(?:archive|remove|complete) todo(?: item)? (.+)", raw_phrase, re.IGNORECASE)
    if match:
        return Command("archive_todo", match.group(1))
    if phrase in {"done", "i'm done", "im done", "complete it", "completed"}:
        return Command("complete_reminder")
    match = re.fullmatch(r"(?:delay|snooze)(?: it)? (\d+) minutes?", phrase)
    if match:
        return Command("snooze_reminder", minutes=int(match.group(1)))
    reminder = re.fullmatch(r"(?:remind me to|set (?:a )?reminder to) (.+)", raw_phrase, re.IGNORECASE)
    if reminder:
        task, due_at = _parse_reminder(reminder.group(1), now)
        if task and due_at:
            return Command("add_reminder", task, due_at)
        return Command("invalid_reminder")
    return Command("unknown")


def _parse_reminder(value: str, now: datetime) -> tuple[str | None, datetime | None]:
    relative = re.fullmatch(r"(.+?) in (\d+) (minutes?|hours?)", value, re.IGNORECASE)
    if relative:
        amount = int(relative.group(2))
        unit = relative.group(3)
        return relative.group(1), now + (timedelta(hours=amount) if unit.startswith("hour") else timedelta(minutes=amount))
    absolute = re.fullmatch(r"(.+?) at (\d{1,2})(?::(\d{2}))?\s*(am|pm)( tomorrow)?", value, re.IGNORECASE)
    if not absolute:
        return None, None
    task, hour_text, minute_text, meridiem, tomorrow = absolute.groups()
    hour, minute = int(hour_text), int(minute_text or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return None, None
    hour = hour % 12 + (12 if meridiem.lower() == "pm" else 0)
    due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if tomorrow:
        due_at += timedelta(days=1)
    elif due_at <= now:
        due_at += timedelta(days=1)
    return task, due_at
