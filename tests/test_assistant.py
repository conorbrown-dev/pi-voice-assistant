from __future__ import annotations

import tempfile
import unittest
import wave
from datetime import datetime, timedelta
from pathlib import Path

from pi_voice_assistant.assistant import Assistant
from pi_voice_assistant.cli import choose_microphone_device, startup_greeting
from pi_voice_assistant.commands import parse
from pi_voice_assistant.storage import Store
from pi_voice_assistant.speech import _pad_wav


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
        self.assertEqual(self.assistant.handle("add todo buy milk", self.now), "Confirmed. Todo added successfully: buy milk.")
        self.assertEqual(self.assistant.handle("list todos", self.now), "Your todos are: buy milk.")
        self.assertEqual(self.assistant.handle("archive todo buy milk", self.now), "Confirmed. Todo archived successfully: buy milk.")
        self.assertEqual(self.assistant.handle("list todo", self.now), "You have no active todos.")

    def test_shopping_items_are_stored_and_archived(self) -> None:
        item = self.store.add_shopping_item("milk", self.now)
        self.assertEqual([stored.text for stored in self.store.list_shopping_items()], ["milk"])
        self.assertTrue(self.store.archive_shopping_item(item.id, self.now))
        self.assertEqual(self.store.list_shopping_items(), [])

    def test_do_phrase_adds_a_todo(self) -> None:
        self.assertEqual(self.assistant.handle("do buy milk", self.now), "Confirmed. Todo added successfully: buy milk.")

    def test_add_todo_can_collect_the_task_in_a_second_turn(self) -> None:
        assistant = Assistant(self.store, wake_word="Computer")
        self.assertEqual(assistant.handle("Computer", self.now), "How can I help?")
        self.assertEqual(assistant.handle("add todo", self.now), "What todo would you like to add?")
        self.assertEqual(assistant.handle("buy milk", self.now), "Confirmed. Todo added successfully: buy milk.")
        self.assertEqual([todo.text for todo in self.store.list_todos()], ["buy milk"])

    def test_spaced_todo_is_normalized(self) -> None:
        self.assertEqual(self.assistant.handle("add to do buy milk", self.now), "Confirmed. Todo added successfully: buy milk.")

    def test_archive_matches_existing_todo_with_transcription_punctuation(self) -> None:
        self.store.add_todo("Put lawnmower belt on.", self.now)
        self.assertEqual(
            self.assistant.handle("archive todo Put lawnmower belt on", self.now),
            "Confirmed. Todo archived successfully: Put lawnmower belt on.",
        )

    def test_punctuation_is_ignored_in_todos_and_reminders(self) -> None:
        self.assertEqual(self.assistant.handle("add todo. Buy, milk!", self.now), "Confirmed. Todo added successfully: Buy milk.")
        self.assertEqual(self.assistant.handle("archive todo: Buy milk?", self.now), "Confirmed. Todo archived successfully: Buy milk.")
        reply = self.assistant.handle("remind me to call Sam, in 10 minutes!", self.now)
        self.assertIn("Reminder set", reply)
        self.assertEqual(self.store.due_reminders(self.now + timedelta(minutes=10))[0].text, "call Sam")

    def test_add_reminder_alias(self) -> None:
        reply = self.assistant.handle("add reminder call Sam in 10 minutes", self.now)
        self.assertIn("Confirmed. Reminder set", reply)

    def test_add_reminder_can_collect_task_and_time_in_separate_turns(self) -> None:
        assistant = Assistant(self.store, wake_word="Computer")
        self.assertEqual(assistant.handle("Computer", self.now), "How can I help?")
        self.assertEqual(assistant.handle("add reminder", self.now), "What should I remind you about?")
        self.assertEqual(assistant.handle("call Sam", self.now), "When should I remind you about call Sam?")
        self.assertIn("Confirmed. Reminder set", assistant.handle("in 10 minutes", self.now))

    def test_reminder_time_accepts_spoken_numbers(self) -> None:
        assistant = Assistant(self.store, wake_word="Computer")
        assistant.handle("Computer", self.now)
        assistant.handle("add reminder", self.now)
        assistant.handle("brush teeth", self.now)
        self.assertIn("Confirmed. Reminder set", assistant.handle("in five minutes", self.now))

    def test_add_a_reminder_starts_the_multi_turn_prompt(self) -> None:
        assistant = Assistant(self.store, wake_word="Computer")
        assistant.handle("Computer", self.now)
        self.assertEqual(assistant.handle("add a reminder", self.now), "What should I remind you about?")

    def test_interval_reminder_repeats_after_completion(self) -> None:
        reply = self.assistant.handle("add reminder drink water every hour", self.now)
        self.assertIn("Confirmed. Recurring reminder set", reply)
        due = self.store.due_reminders(self.now + timedelta(hours=1))
        self.assertEqual(len(due), 1)
        self.assistant.check_reminders(self.now + timedelta(hours=1))
        self.assertEqual(
            self.assistant.handle("complete reminder", self.now + timedelta(hours=1)),
            "Which reminder would you like to complete?",
        )
        self.assertEqual(
            self.assistant.handle("drink water", self.now + timedelta(hours=1)),
            "Confirmed. Reminder occurrence completed successfully: drink water.",
        )
        self.assertEqual(len(self.store.due_reminders(self.now + timedelta(hours=2))), 1)

    def test_daily_recurrence_accepts_multiple_clock_times(self) -> None:
        command = parse("add reminder pray every day at 12 pm 3 pm and 7 pm", self.now)
        self.assertEqual(command.kind, "add_reminder")
        self.assertEqual(command.due_at, datetime(2026, 7, 22, 12, 0))
        self.assertIsNotNone(command.recurrence)

    def test_daily_recurrence_accepts_punctuated_pm(self) -> None:
        command = parse("add reminder brush teeth every day at 9 p.m.", self.now)
        self.assertEqual(command.kind, "add_reminder")
        self.assertEqual(command.due_at, datetime(2026, 7, 22, 21, 0))

    def test_whisper_punctuation_is_accepted(self) -> None:
        assistant = Assistant(self.store, wake_word="Computer")
        self.assertEqual(assistant.handle("Computer.", self.now), "How can I help?")
        self.assertEqual(assistant.handle("Add todo. Buy milk.", self.now), "Confirmed. Todo added successfully: Buy milk.")

    def test_reminder_can_complete(self) -> None:
        reply = self.assistant.handle("remind me to call Sam in 10 minutes", self.now)
        self.assertIn("Reminder set", reply)
        messages = self.assistant.check_reminders(self.now + timedelta(minutes=10))
        self.assertEqual(
            messages,
            [
                "Reminder: call Sam. To delay this reminder say delay reminder.",
                "To complete this reminder say complete reminder.",
            ],
        )
        self.assertEqual(self.assistant.handle("complete reminder", self.now + timedelta(minutes=10)), "Which reminder would you like to complete?")
        self.assertEqual(self.assistant.handle("call Sam", self.now + timedelta(minutes=10)), "Confirmed. Reminder completed successfully: call Sam.")
        self.assertEqual(self.store.due_reminders(self.now + timedelta(days=1)), [])

    def test_complete_reminder_is_a_wake_word_guided_interaction(self) -> None:
        assistant = Assistant(self.store, wake_word="Computer")
        self.store.add_reminder("call Sam", self.now + timedelta(minutes=10), self.now)
        assistant.check_reminders(self.now + timedelta(minutes=10))
        self.assertEqual(assistant.handle("Computer", self.now + timedelta(minutes=10)), "How can I help?")
        self.assertEqual(
            assistant.handle("complete reminder", self.now + timedelta(minutes=10)),
            "Which reminder would you like to complete?",
        )
        self.assertEqual(
            assistant.handle("Call Sam.", self.now + timedelta(minutes=10)),
            "Confirmed. Reminder completed successfully: call Sam.",
        )
        self.assertEqual(assistant.check_reminders(self.now + timedelta(days=1)), [])

    def test_reminder_can_snooze(self) -> None:
        self.assistant.handle("remind me to stretch in 1 minute", self.now)
        self.assistant.check_reminders(self.now + timedelta(minutes=1))
        self.assertEqual(self.assistant.handle("delay 15 minutes", self.now + timedelta(minutes=1)), "Confirmed. Reminder delayed for 15 minutes.")
        self.assertEqual(self.assistant.check_reminders(self.now + timedelta(minutes=15)), [])
        self.assertEqual(len(self.assistant.check_reminders(self.now + timedelta(minutes=16)),), 2)

    def test_delay_reminder_is_a_guided_interaction(self) -> None:
        assistant = Assistant(self.store, wake_word="Computer")
        self.store.add_reminder("stretch", self.now + timedelta(minutes=1), self.now)
        assistant.check_reminders(self.now + timedelta(minutes=1))
        self.assertEqual(
            assistant.handle("Computer, delay reminder", self.now + timedelta(minutes=1)),
            "How long would you like to delay this reminder?",
        )
        self.assertEqual(
            assistant.handle("fifteen minutes", self.now + timedelta(minutes=1)),
            "Confirmed. Reminder delayed successfully for 15 minutes.",
        )
        self.assertEqual(assistant.check_reminders(self.now + timedelta(minutes=15)), [])
        self.assertEqual(len(assistant.check_reminders(self.now + timedelta(minutes=16)),), 2)

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
        self.assertIn("You can say add todo", assistant.handle("Computer, list commands", self.now))
        self.assertEqual(assistant.handle("Computer", self.now), "How can I help?")
        self.assertIn("You can say add todo", assistant.handle("list commands", self.now + timedelta(seconds=19)))

    def test_spoken_guidance_includes_the_wake_word(self) -> None:
        assistant = Assistant(self.store, wake_word="Computer")
        self.assertEqual(assistant.handle("Computer", self.now), "How can I help?")
        self.assertIn("You can say add todo", assistant.handle("list commands", self.now))
        self.assertEqual(assistant.handle("Computer", self.now), "How can I help?")
        self.assertIn("Say Computer, then say list commands", assistant.handle("something unexpected", self.now))
        self.assertEqual(assistant.handle("Computer", self.now), "How can I help?")
        assistant.handle("remind me to call Sam in 10 minutes", self.now)
        self.assertEqual(
            assistant.check_reminders(self.now + timedelta(minutes=10)),
            [
                "Reminder: call Sam. To delay this reminder say Computer, delay reminder.",
                "To complete this reminder say Computer, complete reminder.",
            ],
        )

    def test_startup_greeting_uses_local_time_of_day(self) -> None:
        self.assertEqual(startup_greeting(datetime(2026, 7, 22, 9, 0)), "Good morning. Setup is complete and I am ready. Say Computer to begin.")
        self.assertEqual(startup_greeting(datetime(2026, 7, 22, 13, 0)), "Good afternoon. Setup is complete and I am ready. Say Computer to begin.")
        self.assertEqual(startup_greeting(datetime(2026, 7, 22, 19, 0)), "Good evening. Setup is complete and I am ready. Say Computer to begin.")

    def test_microphone_picker_lists_inputs_and_retries_invalid_device_ids(self) -> None:
        prompts = iter(("not-a-device", "9", "2"))
        output: list[str] = []
        selected = choose_microphone_device(
            [
                {"name": "Built-in output", "max_input_channels": 0},
                {"name": "USB microphone", "max_input_channels": 1},
                {"name": "Webcam microphone", "max_input_channels": 2},
            ],
            input_fn=lambda _: next(prompts),
            output_fn=output.append,
        )
        self.assertEqual(selected, 2)
        self.assertEqual(output[0], "Available microphone devices:")
        self.assertIn("  1: USB microphone (1 input channel)", output)
        self.assertIn("  2: Webcam microphone (2 input channels)", output)
        self.assertEqual(output.count("Please enter one of the listed microphone device IDs."), 2)

    def test_microphone_device_is_stored_locally(self) -> None:
        self.assertIsNone(self.store.microphone_device())
        self.store.set_microphone_device(3)
        self.assertEqual(self.store.microphone_device(), 3)
        self.store.set_microphone_device(7)
        self.assertEqual(self.store.microphone_device(), 7)

    def test_wav_padding_preserves_audio_and_adds_silence(self) -> None:
        source = Path(self.directory.name) / "source.wav"
        padded = Path(self.directory.name) / "padded.wav"
        with wave.open(str(source), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(1000)
            wav_file.writeframes(b"\x01\x00" * 3)
        _pad_wav(str(source), str(padded), 2)
        with wave.open(str(padded), "rb") as wav_file:
            self.assertEqual(wav_file.getnframes(), 7)
            self.assertEqual(wav_file.readframes(7), b"\0" * 4 + b"\x01\x00" * 3 + b"\0" * 4)


if __name__ == "__main__":
    unittest.main()
