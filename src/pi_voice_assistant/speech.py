from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
from abc import ABC, abstractmethod


class Speaker(ABC):
    @abstractmethod
    def say(self, text: str) -> None: ...


class EspeakSpeaker(Speaker):
    def say(self, text: str) -> None:
        if shutil.which("espeak-ng"):
            subprocess.run(["espeak-ng", text], check=False)
        else:
            print(f"Assistant: {text}")


class Listener(ABC):
    @abstractmethod
    def listen(self, timeout: float | None = None) -> str | None: ...


class TextListener(Listener):
    def listen(self, timeout: float | None = None) -> str | None:
        try:
            return input("You: ").strip() or None
        except EOFError:
            return None


class VoskListener(Listener):
    """Microphone listener; VOSK_MODEL_PATH must point to an unpacked Vosk model."""
    def __init__(self, device: int | None = None, sample_rate: int = 16000) -> None:
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model
        except ImportError as error:
            raise RuntimeError("Install voice extras: pip install -e '.[voice]'") from error
        model_path = os.environ.get("VOSK_MODEL_PATH")
        if not model_path:
            raise RuntimeError("Set VOSK_MODEL_PATH to an unpacked Vosk speech model.")
        self.sd, self.recognizer = sd, KaldiRecognizer(Model(model_path), sample_rate)
        self.device, self.sample_rate = device, sample_rate

    def listen(self, timeout: float | None = None) -> str | None:
        audio: queue.Queue[bytes] = queue.Queue()
        def callback(indata, frames, time, status):  # type: ignore[no-untyped-def]
            if not status:
                audio.put(bytes(indata))
        with self.sd.RawInputStream(samplerate=self.sample_rate, blocksize=8000, device=self.device,
                                    dtype="int16", channels=1, callback=callback):
            while True:
                if self.recognizer.AcceptWaveform(audio.get(timeout=timeout)):
                    result = json.loads(self.recognizer.Result()).get("text", "").strip()
                    if result:
                        return result

