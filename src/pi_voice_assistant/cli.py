from __future__ import annotations

import argparse
import queue
import time
from pathlib import Path

from .assistant import Assistant
from .speech import EspeakSpeaker, TextListener, VoskListener
from .storage import Store


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline Pi voice assistant")
    parser.add_argument("--database", type=Path, default=Path.home() / ".local/share/pi-voice-assistant/assistant.db")
    parser.add_argument("--text", action="store_true", help="Use terminal input instead of USB microphone")
    parser.add_argument("--device", type=int, help="sounddevice input device index")
    parser.add_argument("--sample-rate", type=int, help="Microphone sample rate; defaults to the device's advertised rate")
    parser.add_argument("--show-transcript", action="store_true", help="Print each recognized phrase for microphone troubleshooting")
    args = parser.parse_args()
    store, speaker = Store(args.database), EspeakSpeaker()
    try:
        assistant = Assistant(store)
        listener = TextListener() if args.text else VoskListener(args.device, args.sample_rate)
        speaker.say("Pi assistant ready. Say list commands for help.")
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
                speaker.say(assistant.handle(spoken))
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
