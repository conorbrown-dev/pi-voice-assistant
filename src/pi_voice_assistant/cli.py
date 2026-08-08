from __future__ import annotations

import argparse
import os
import queue
import sys
import time
from array import array
from datetime import datetime
from math import isqrt
from pathlib import Path

from .assistant import Assistant
from .speech import EspeakSpeaker, PiperSpeaker, Speaker, TextListener, VoskListener, WhisperListener
from .storage import Store


DEFAULT_PIPER_MODEL = Path(__file__).resolve().parents[2] / "en_GB-alba-medium.onnx"
DEFAULT_WHISPER_MODEL = Path(__file__).resolve().parents[2] / "models/ggml-base.en.bin"


def startup_greeting(now: datetime | None = None, wake_word: str = "Computer") -> str:
    hour = (now or datetime.now()).hour
    time_of_day = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
    instruction = f"Say {wake_word} to begin." if wake_word else "Say list commands to hear what I can do."
    return f"Good {time_of_day}. Setup is complete and I am ready. {instruction}"


def choose_microphone_device(
    devices: list[dict[str, object]],
    input_fn: object = input,
    output_fn: object = print,
) -> int | None:
    """List usable microphone devices and return the selected sounddevice ID."""
    microphones = [
        (index, device)
        for index, device in enumerate(devices)
        if int(device["max_input_channels"]) > 0
    ]
    if not microphones:
        raise RuntimeError("No microphone input devices were found.")

    output_fn("Available microphone devices:")  # type: ignore[operator]
    valid_ids = set()
    for index, device in microphones:
        valid_ids.add(index)
        channels = int(device["max_input_channels"])
        output_fn(f"  {index}: {device['name']} ({channels} input channel{'s' if channels != 1 else ''})")  # type: ignore[operator]

    while True:
        try:
            response = input_fn("Microphone device ID: ").strip()  # type: ignore[operator]
        except EOFError:
            return None
        try:
            selected_id = int(response)
        except ValueError:
            selected_id = -1
        if selected_id in valid_ids:
            return selected_id
        output_fn("Please enter one of the listed microphone device IDs.")  # type: ignore[operator]


def prompt_for_microphone_device(devices: list[dict[str, object]] | None = None) -> int | None:
    return choose_microphone_device(devices if devices is not None else microphone_devices())


def microphone_devices() -> list[dict[str, object]]:
    try:
        import sounddevice as sd
    except ImportError as error:
        raise RuntimeError("Install voice extras: pip install -e '.[voice]'") from error
    return list(sd.query_devices())


def list_microphone_devices() -> None:
    devices = microphone_devices()
    microphones = [
        (index, device)
        for index, device in enumerate(devices)
        if int(device["max_input_channels"]) > 0
    ]
    if not microphones:
        print("No microphone input devices found.")
        return
    print("Available microphone devices:")
    for index, device in microphones:
        print(f"  {index}: {device['name']} ({int(device['max_input_channels'])} input channels)")


def select_saved_microphone_device(
    device: int | None,
    store: Store,
    speaker: Speaker | None = None,
    force_prompt: bool = False,
) -> int | None:
    """Use an explicit or saved device, prompting only when selection is needed."""
    if device is not None:
        return device
    devices = microphone_devices()
    valid_ids = {index for index, item in enumerate(devices) if int(item["max_input_channels"]) > 0}
    saved_device = store.microphone_device()
    if not force_prompt and saved_device in valid_ids:
        print(f"Using saved microphone device ID: {saved_device}")
        return saved_device
    if not sys.stdin.isatty():
        if saved_device is not None:
            print(f"Saved microphone device ID {saved_device} is unavailable; using the system default.")
        return None
    if speaker:
        speaker.say("Please select a microphone device. The available device IDs are displayed in the terminal. Type the device ID and press Enter.")
    selected_device = prompt_for_microphone_device(devices)
    if selected_device is not None:
        store.set_microphone_device(selected_device)
        if speaker:
            speaker.say(f"Microphone device {selected_device} selected.")
    return selected_device


def test_microphone(device: int | None, sample_rate: int | None) -> None:
    """Print live RMS values directly from PortAudio until Ctrl-C is pressed."""
    try:
        import sounddevice as sd
    except ImportError as error:
        raise RuntimeError("Install voice extras: pip install -e '.[voice]'") from error
    if sample_rate is None:
        sample_rate = int(sd.query_devices(device, "input")["default_samplerate"])
    levels: queue.Queue[bytes] = queue.Queue()

    def callback(indata, frames, time_info, status):  # type: ignore[no-untyped-def]
        if status:
            print(f"Microphone status: {status}")
        levels.put(bytes(indata))

    print(f"Testing microphone device {device} at {sample_rate} Hz. Speak normally; press Ctrl-C to stop.")
    with sd.RawInputStream(samplerate=sample_rate, blocksize=0, device=device, dtype="int16", channels=1, callback=callback):
        try:
            while True:
                samples = array("h")
                samples.frombytes(levels.get())
                level = isqrt(sum(sample * sample for sample in samples) // len(samples)) if samples else 0
                print(f"Input level: {level}")
        except KeyboardInterrupt:
            print("Microphone test stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline Pi voice assistant")
    parser.add_argument("--database", type=Path, default=Path.home() / ".local/share/pi-voice-assistant/assistant.db")
    parser.add_argument("--text", action="store_true", help="Use terminal input instead of USB microphone")
    parser.add_argument("--stt", choices=("whisper", "vosk"), default="whisper", help="Speech recognition engine (default: whisper)")
    parser.add_argument("--device", type=int, help="sounddevice input device index")
    parser.add_argument("--select-microphone", action="store_true", help="Prompt for and save a microphone device ID")
    parser.add_argument("--list-microphones", action="store_true", help="List detected microphone device IDs and exit")
    parser.add_argument("--test-microphone", action="store_true", help="Print live microphone levels and exit with Ctrl-C")
    parser.add_argument("--sample-rate", type=int, help="Microphone sample rate; defaults to the device's advertised rate")
    parser.add_argument("--whisper-model", type=Path, default=Path(os.environ.get("WHISPER_MODEL_PATH", str(DEFAULT_WHISPER_MODEL))), help="Path to the whisper.cpp ggml model")
    parser.add_argument("--whisper-binary", default=os.environ.get("WHISPER_BINARY", "whisper-cli"), help="whisper.cpp executable (default: whisper-cli)")
    parser.add_argument("--speech-threshold", type=int, default=200, help="Input level that starts a Whisper utterance (default: 200)")
    parser.add_argument("--silence-threshold", type=int, default=150, help="Input level treated as silence after speech starts (default: 150)")
    parser.add_argument("--silence-seconds", type=float, default=0.9, help="Quiet time that ends a Whisper utterance (default: 0.9)")
    parser.add_argument("--pre-roll-seconds", type=float, default=0.8, help="Audio retained before speech starts (default: 0.8)")
    parser.add_argument("--max-phrase-seconds", type=float, default=4.0, help="Maximum duration of one spoken phrase (default: 4.0)")
    parser.add_argument("--whisper-threads", type=int, default=max(1, os.cpu_count() or 4), help="CPU threads for Whisper (default: all available cores)")
    parser.add_argument("--show-audio-level", action="store_true", help="Print live microphone levels plus Whisper capture duration")
    parser.add_argument("--whisper-prompt", default="Computer. Add todo. List todos. Archive todo. Remind me to.", help="Command-domain prompt for Whisper")
    parser.add_argument("--save-whisper-audio", type=Path, help="Directory in which to keep the WAV sent to Whisper")
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
    parser.add_argument("--audio-padding-ms", type=int, default=200, help="Silence before and after Piper speech to prevent clipping (default: 200)")
    args = parser.parse_args()
    if args.list_microphones:
        list_microphone_devices()
        return
    store = Store(args.database)
    listener: Listener | None = None
    try:
        if args.test_microphone:
            args.device = select_saved_microphone_device(args.device, store, force_prompt=args.select_microphone)
            test_microphone(args.device, args.sample_rate)
            return
        speaker: Speaker
        if args.tts == "piper":
            speaker = PiperSpeaker(args.piper_model, audio_device=args.audio_device, padding_ms=args.audio_padding_ms)
        else:
            speaker = EspeakSpeaker(args.voice, args.speech_rate, args.pitch)
        if not args.text:
            args.device = select_saved_microphone_device(
                args.device,
                store,
                speaker,
                force_prompt=args.select_microphone,
            )
        assistant = Assistant(store, wake_word=args.wake_word, wake_timeout_seconds=args.wake_timeout)
        if args.text:
            listener = TextListener()
        elif args.stt == "whisper":
            print(f"Speech recognition: Whisper ({args.whisper_model})")
            listener = WhisperListener(
                args.device,
                args.sample_rate,
                args.whisper_model,
                args.whisper_binary,
                args.speech_threshold,
                args.silence_threshold,
                args.silence_seconds,
                args.pre_roll_seconds,
                args.show_audio_level,
                args.whisper_prompt,
                args.save_whisper_audio,
                args.whisper_threads,
                args.max_phrase_seconds,
            )
        else:
            print("Speech recognition: Vosk")
            listener = VoskListener(args.device, args.sample_rate)
        greeting = startup_greeting(wake_word=args.wake_word)
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
        if listener:
            listener.close()
        store.close()


if __name__ == "__main__":
    main()
