from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from pi_voice_assistant.assistant import Assistant
from pi_voice_assistant.commands import parse
from pi_voice_assistant.storage import Store


class AssistantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "assistant.db")
        self.assistant = Assistant(self.store)
        self.now = datetime(2026, 7, 22, 10, 0)

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def test_todo_lifecycle(self) -> None:
        self.assertEqual(self.assistant.handle("add todo buy milk", self.now), "Added todo: buy milk.")
        self.assertEqual(self.assistant.handle("list todos", self.now), "Your todos are: buy milk.")
        self.assertEqual(self.assistant.handle("archive todo buy milk", self.now), "Archived todo: buy milk.")
        self.assertEqual(self.assistant.handle("list todo", self.now), "You have no active todos.")

    def test_reminder_can_complete(self) -> None:
        reply = self.assistant.handle("remind me to call Sam in 10 minutes", self.now)
        self.assertIn("Reminder set", reply)
        messages = self.assistant.check_reminders(self.now + timedelta(minutes=10))
        self.assertEqual(messages, ["Reminder: call Sam. Say done, or delay followed by a number of minutes."])
        self.assertEqual(self.assistant.handle("done", self.now + timedelta(minutes=10)), "Great, I marked that reminder complete.")
        self.assertEqual(self.store.due_reminders(self.now + timedelta(days=1)), [])

    def test_reminder_can_snooze(self) -> None:
        self.assistant.handle("remind me to stretch in 1 minute", self.now)
        self.assistant.check_reminders(self.now + timedelta(minutes=1))
        self.assertEqual(self.assistant.handle("delay 15 minutes", self.now + timedelta(minutes=1)), "Okay, I will remind you again in 15 minutes.")
        self.assertEqual(self.assistant.check_reminders(self.now + timedelta(minutes=15)), [])
        self.assertEqual(len(self.assistant.check_reminders(self.now + timedelta(minutes=16)),), 1)

    def test_absolute_reminder_rolls_to_next_day(self) -> None:
        command = parse("remind me to feed the cat at 9 am", self.now)
        self.assertEqual(command.due_at, datetime(2026, 7, 23, 9, 0))

    def test_invalid_reminder_explains_format(self) -> None:
        self.assertIn("Please say a reminder", self.assistant.handle("remind me to walk later", self.now))

    def test_help_accepts_common_recognition_variations(self) -> None:
        for phrase in ("list command", "List commands!", "just commands", "what are the commands"):
            self.assertEqual(parse(phrase, self.now).kind, "help")

    def test_wake_word_can_prefix_or_precede_a_command(self) -> None:
        assistant = Assistant(self.store, wake_word="Computer")
        self.assertIsNone(assistant.handle("list commands", self.now))
        self.assertIn("You can say", assistant.handle("Computer, list commands", self.now))
        self.assertIn("You can say", assistant.handle("Computer and list commands", self.now))
        self.assertIsNone(assistant.handle("Computer", self.now))
        self.assertIn("You can say", assistant.handle("list commands", self.now + timedelta(seconds=7)))


if __name__ == "__main__":
    unittest.main()
