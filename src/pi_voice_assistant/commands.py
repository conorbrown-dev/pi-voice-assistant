from __future__ import annotations

import re
import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta


@dataclass(frozen=True)
class Command:
    kind: str
    text: str = ""
    due_at: datetime | None = None
    minutes: int | None = None
    recurrence: str | None = None


HELP = (
    "You can say: add todo followed by a task; list todos; archive todo followed by a task; "
    "or remind me to do something in 10 minutes, at 3 pm, or at 3 pm tomorrow."
)


def strip_punctuation(text: str) -> str:
    """Remove punctuation while preserving word boundaries and letter case."""
    # Whisper may emit a time suffix as "p.m." or "p m". Join it before
    # stripping punctuation so schedule parsing consistently sees "pm".
    text = re.sub(r"\b([AaPp])\s*\.?\s*[Mm]\b", r"\1m", text)
    return " ".join(re.sub(r"[^A-Za-z0-9]+", " ", text.replace("'", "")).split())


def normalize_phrase(text: str) -> str:
    """Normalize transcription text for case-insensitive intent matching."""
    return strip_punctuation(text).lower()


def parse(text: str, now: datetime) -> Command:
    raw_phrase = strip_punctuation(text)
    # Speech recognition often separates the compound word "todo" into
    # "to do" (or hears "two do"). Treat those as the command keyword.
    raw_phrase = re.sub(r"\b(?:to|two)\s+do\b", "todo", raw_phrase, flags=re.IGNORECASE)
    command_phrase = raw_phrase
    # Vosk transcripts do not include punctuation consistently and sometimes
    # hear the final "s" in "commands" as singular.  Normalize those
    # presentation differences before matching fixed commands.
    phrase = normalize_phrase(raw_phrase)
    if phrase in {
        "list command",
        "list commands",
        "just commands",
        "help",
        "what can i say",
        "what are the commands",
        "commands",
    } or re.fullmatch(r"(?:can you |could you |please )?(?:list|show|tell me|what are) (?:the )?commands", phrase):
        return Command("help")
    if phrase in {"list todo", "list todos", "list todo items", "list my todos"} or re.fullmatch(
        r"(?:can you |could you |please )?(?:list|show)(?: my)? todos?", phrase
    ):
        return Command("list_todos")
    if re.fullmatch(r"(?:add )?todo(?: item)?", command_phrase, re.IGNORECASE):
        return Command("add_todo_prompt")
    match = re.fullmatch(r"(?:add )?todo(?: item)?(?: called)? (.+)", command_phrase, re.IGNORECASE)
    if match:
        return Command("add_todo", match.group(1))
    match = re.fullmatch(r"do (.+)", command_phrase, re.IGNORECASE)
    if match:
        return Command("add_todo", match.group(1))
    match = re.fullmatch(r"(?:archive|remove|complete) todo(?: item)? (.+)", command_phrase, re.IGNORECASE)
    if match:
        return Command("archive_todo", match.group(1))
    if re.fullmatch(r"(?:add|set)(?: a)? reminder", command_phrase, re.IGNORECASE):
        return Command("add_reminder_prompt")
    if phrase in {"complete reminder", "complete a reminder"}:
        return Command("complete_reminder_prompt")
    if phrase in {"delay reminder", "delay this reminder", "snooze reminder"}:
        return Command("delay_reminder_prompt")
    match = re.fullmatch(r"(?:delay|snooze)(?: it)? (.+) minutes?", phrase)
    if match:
        minutes = parse_spoken_number(match.group(1))
        if minutes is not None:
            return Command("snooze_reminder", minutes=minutes)
    reminder = re.fullmatch(r"(?:remind me to|set (?:a )?reminder to|add (?:a )?reminder(?: to)?) (.+)", command_phrase, re.IGNORECASE)
    if reminder:
        task, due_at, recurrence = _parse_reminder(reminder.group(1), now)
        if task and due_at:
            return Command("add_reminder", task, due_at, recurrence=recurrence)
        return Command("invalid_reminder")
    return Command("unknown")


def parse_delay_minutes(text: str) -> int | None:
    """Parse the duration spoken after the delay-reminder prompt."""
    phrase = normalize_phrase(text)
    match = re.fullmatch(r"(?:(?:for|by) )?(.+?) minutes?", phrase)
    return parse_spoken_number(match.group(1)) if match else None


def _parse_reminder(value: str, now: datetime) -> tuple[str | None, datetime | None, str | None]:
    repeating = re.fullmatch(r"(.+?) (every .+)", value, re.IGNORECASE)
    if repeating:
        due_at, recurrence = parse_reminder_schedule(repeating.group(2), now)
        return repeating.group(1), due_at, recurrence
    relative = re.fullmatch(r"(.+?) (in .+? (?:minutes?|hours?))", value, re.IGNORECASE)
    if relative:
        return relative.group(1), parse_reminder_time(relative.group(2), now), None
    absolute = re.fullmatch(r"(.+?) (at \d{1,2}(?:\s+\d{2})?\s*(?:am|pm)(?: tomorrow)?)", value, re.IGNORECASE)
    if not absolute:
        return None, None, None
    return absolute.group(1), parse_reminder_time(absolute.group(2), now), None


def parse_reminder_schedule(value: str, now: datetime) -> tuple[datetime | None, str | None]:
    interval = re.fullmatch(r"every (?:(.+?) )?(hours?|days?)", value, re.IGNORECASE)
    if interval:
        amount = parse_spoken_number(interval.group(1) or "1")
        if amount is None:
            return None, None
        minutes = amount * (60 if interval.group(2).lower().startswith("hour") else 24 * 60)
        return now + timedelta(minutes=minutes), json.dumps({"kind": "interval", "minutes": minutes})
    daily = re.fullmatch(r"every day at (.+)", value, re.IGNORECASE)
    if not daily:
        return None, None
    times = []
    for hour_text, minute_text, meridiem in re.findall(r"(\d{1,2})(?:\s+(\d{2}))?\s*(am|pm)", daily.group(1), re.IGNORECASE):
        hour, minute = int(hour_text), int(minute_text or 0)
        if not 1 <= hour <= 12 or minute > 59:
            return None, None
        hour = hour % 12 + (12 if meridiem.lower() == "pm" else 0)
        times.append(time(hour, minute))
    if not times:
        return None, None
    times = sorted(set(times))
    for day_offset in range(0, 2):
        date = (now + timedelta(days=day_offset)).date()
        for scheduled_time in times:
            candidate = datetime.combine(date, scheduled_time)
            if candidate > now:
                return candidate, json.dumps({"kind": "daily_times", "times": [item.isoformat() for item in times]})
    return None, None


def parse_reminder_time(value: str, now: datetime) -> datetime | None:
    relative = re.fullmatch(r"in (.+?) (minutes?|hours?)", value, re.IGNORECASE)
    if relative:
        amount = parse_spoken_number(relative.group(1))
        if amount is None:
            return None
        unit = relative.group(2)
        return now + (timedelta(hours=amount) if unit.startswith("hour") else timedelta(minutes=amount))
    absolute = re.fullmatch(r"at (\d{1,2})(?:\s+(\d{2}))?\s*(am|pm)( tomorrow)?", value, re.IGNORECASE)
    if not absolute:
        return None
    hour_text, minute_text, meridiem, tomorrow = absolute.groups()
    hour, minute = int(hour_text), int(minute_text or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return None
    hour = hour % 12 + (12 if meridiem.lower() == "pm" else 0)
    due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if tomorrow:
        due_at += timedelta(days=1)
    elif due_at <= now:
        due_at += timedelta(days=1)
    return due_at


def parse_spoken_number(value: str) -> int | None:
    """Parse a positive digit or common English number phrase up to 99."""
    if value.isdigit():
        return int(value)
    words = value.lower().split()
    ones = {
        "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
        "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
        "eighteen": 18, "nineteen": 19,
    }
    tens = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
    if len(words) == 1:
        return ones.get(words[0], tens.get(words[0]))
    if len(words) == 2 and words[0] in tens and words[1] in ones and ones[words[1]] < 10:
        return tens[words[0]] + ones[words[1]]
    return None
