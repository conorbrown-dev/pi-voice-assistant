from __future__ import annotations

import argparse
import os
import queue
import time
from datetime import datetime
from pathlib import Path

from .assistant import Assistant
from .speech import EspeakSpeaker, PiperSpeaker, Speaker, TextListener, VoskListener
from .storage import Store


DEFAULT_PIPER_MODEL = Path(__file__).resolve().parents[2] / "en_GB-alba-medium.onnx"


def startup_greeting(now: datetime | None = None) -> str:
    hour = (now or datetime.now()).hour
    time_of_day = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
    return f"Good {time_of_day}, let me know what I can do for you today."


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline Pi voice assistant")
    parser.add_argument("--database", type=Path, default=Path.home() / ".local/share/pi-voice-assistant/assistant.db")
    parser.add_argument("--text", action="store_true", help="Use terminal input instead of USB microphone")
    parser.add_argument("--device", type=int, help="sounddevice input device index")
    parser.add_argument("--sample-rate", type=int, help="Microphone sample rate; defaults to the device's advertised rate")
    parser.add_argument("--show-transcript", action="store_true", help="Print each recognized phrase for microphone troubleshooting")
    parser.add_argument("--voice", default="en-us", help="eSpeak NG voice name (default: en-us)")
    parser.add_argument("--speech-rate", type=int, default=145, help="Speech speed in words per minute (default: 145)")
    parser.add_argument("--pitch", type=int, default=45, help="Speech pitch from 0 to 99 (default: 45)")
    parser.add_argument(
        "--wake-word",
        default=os.environ.get("PI_ASSISTANT_WAKE_WORD", "Computer"),
        help='Wake word required before a command; use "" to disable (default: Computer)',
    )
    parser.add_argument(
        "--wake-timeout",
        type=int,
        default=20,
        help="Seconds to wait for a command after the wake word (default: 20)",
    )
    parser.add_argument("--tts", choices=("piper", "espeak"), default="piper", help="Speech engine (default: piper)")
    parser.add_argument(
        "--piper-model",
        type=Path,
        default=Path(
            os.environ.get(
                "PIPER_MODEL_PATH",
                str(DEFAULT_PIPER_MODEL),
            )
        ),
        help="Path to the Piper .onnx voice model",
    )
    parser.add_argument(
        "--audio-device",
        default=os.environ.get("PI_ASSISTANT_AUDIO_DEVICE"),
        help="ALSA output device for Piper, for example sysdefault:CARD=Headphones",
    )
    args = parser.parse_args()
    store = Store(args.database)
    try:
        speaker: Speaker
        if args.tts == "piper":
            speaker = PiperSpeaker(args.piper_model, audio_device=args.audio_device)
        else:
            speaker = EspeakSpeaker(args.voice, args.speech_rate, args.pitch)
        assistant = Assistant(store, wake_word=args.wake_word, wake_timeout_seconds=args.wake_timeout)
        listener = TextListener() if args.text else VoskListener(args.device, args.sample_rate)
        greeting = startup_greeting()
        print(f"Assistant: {greeting}")
        speaker.say(greeting)
        while True:
            for message in assistant.check_reminders():
                speaker.say(message)
            try:
                spoken = listener.listen(timeout=1.0 if not args.text else None)
            except queue.Empty:
                continue
            if spoken:
                if args.show_transcript and not args.text:
                    print(f"Heard: {spoken}")
                reply = assistant.handle(spoken)
                if reply:
                    print(f"Assistant: {reply}")
                    speaker.say(reply)
                elif args.show_transcript and not args.text:
                    print(f'Ignored: say "{args.wake_word}" before a command.')
            elif args.text:
                break
            if args.text:
                time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nStopping assistant.")
    finally:
        store.close()


if __name__ == "__main__":
    main()
