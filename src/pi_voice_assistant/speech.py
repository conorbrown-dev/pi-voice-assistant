from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import wave
from audioop import rms
from abc import ABC, abstractmethod
from pathlib import Path


class Speaker(ABC):
    @abstractmethod
    def say(self, text: str) -> None: ...


class EspeakSpeaker(Speaker):
    def __init__(self, voice: str = "en-us", rate: int = 145, pitch: int = 45) -> None:
        self.voice = voice
        self.rate = rate
        self.pitch = pitch

    def say(self, text: str) -> None:
        if shutil.which("espeak-ng"):
            subprocess.run(
                ["espeak-ng", "--voice", self.voice, "--speed", str(self.rate), "--pitch", str(self.pitch), text],
                check=False,
            )
        else:
            print(f"Assistant: {text}")


class PiperSpeaker(Speaker):
    """Local neural speech using a downloaded Piper .onnx voice model."""

    def __init__(self, model_path: Path, audio_device: str | None = None) -> None:
        if not model_path.is_file():
            raise RuntimeError(
                f"Piper voice model not found: {model_path}. "
                "Install the Piper extra and download the configured voice model."
            )
        config_path = Path(f"{model_path}.json")
        if not config_path.is_file():
            raise RuntimeError(f"Piper voice config not found: {config_path}")
        try:
            from piper import PiperVoice
        except ImportError as error:
            raise RuntimeError("Install Piper: pip install -e '.[piper]'") from error
        self.voice = PiperVoice.load(str(model_path))
        self.audio_device = audio_device

    def say(self, text: str) -> None:
        if not shutil.which("aplay"):
            raise RuntimeError("Install ALSA playback support: sudo apt install alsa-utils")
        with tempfile.NamedTemporaryFile(suffix=".wav") as audio_file:
            with wave.open(audio_file, "wb") as wav_file:
                self.voice.synthesize_wav(text, wav_file)
            audio_file.flush()
            command = ["aplay", "-q"]
            if self.audio_device:
                command.extend(["-D", self.audio_device])
            command.append(audio_file.name)
            subprocess.run(command, check=True)


class Listener(ABC):
    @abstractmethod
    def listen(self, timeout: float | None = None) -> str | None: ...


class TextListener(Listener):
    def listen(self, timeout: float | None = None) -> str | None:
        try:
            return input("You: ").strip() or None
        except EOFError:
            return None


class WhisperListener(Listener):
    """Offline Whisper transcription through the whisper.cpp command-line tool."""

    def __init__(
        self,
        device: int | None,
        sample_rate: int | None,
        model_path: Path,
        binary: str = "whisper-cli",
        speech_threshold: int = 400,
    ) -> None:
        try:
            import sounddevice as sd
        except ImportError as error:
            raise RuntimeError("Install voice extras: pip install -e '.[voice]'") from error
        if not model_path.is_file():
            raise RuntimeError(f"Whisper model not found: {model_path}")
        if not shutil.which(binary) and not Path(binary).is_file():
            raise RuntimeError("Install whisper.cpp and make whisper-cli available on PATH.")
        if sample_rate is None:
            sample_rate = int(sd.query_devices(device, "input")["default_samplerate"])
        self.sd = sd
        self.device = device
        self.sample_rate = sample_rate
        self.model_path = model_path
        self.binary = binary
        self.speech_threshold = speech_threshold

    def listen(self, timeout: float | None = None) -> str | None:
        audio: queue.Queue[bytes] = queue.Queue()

        def callback(indata, frames, time, status):  # type: ignore[no-untyped-def]
            if not status:
                audio.put(bytes(indata))

        silence_frames = int(self.sample_rate * 1.2)
        maximum_frames = int(self.sample_rate * 12)
        recorded: list[bytes] = []
        silent_frames = 0
        with self.sd.RawInputStream(samplerate=self.sample_rate, blocksize=8000, device=self.device,
                                    dtype="int16", channels=1, callback=callback):
            while True:
                data = audio.get(timeout=timeout if not recorded else None)
                level = rms(data, 2)
                if not recorded and level < self.speech_threshold:
                    continue
                recorded.append(data)
                silent_frames = silent_frames + len(data) // 2 if level < self.speech_threshold else 0
                frames = sum(len(chunk) // 2 for chunk in recorded)
                if silent_frames >= silence_frames or frames >= maximum_frames:
                    return self._transcribe(b"".join(recorded))

    def _transcribe(self, audio: bytes) -> str | None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "utterance.wav"
            output_path = Path(directory) / "transcript"
            with wave.open(str(input_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(audio)
            result = subprocess.run(
                [self.binary, "-m", str(self.model_path), "-f", str(input_path), "-l", "en", "-nt", "-np", "-otxt", "-of", str(output_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(f"whisper-cli failed: {result.stderr.strip() or result.stdout.strip()}")
            transcript_path = output_path.with_suffix(".txt")
            return transcript_path.read_text().strip() if transcript_path.is_file() else None


class VoskListener(Listener):
    """Microphone listener; VOSK_MODEL_PATH must point to an unpacked Vosk model."""
    def __init__(self, device: int | None = None, sample_rate: int | None = None) -> None:
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model
        except ImportError as error:
            raise RuntimeError("Install voice extras: pip install -e '.[voice]'") from error
        model_path = os.environ.get("VOSK_MODEL_PATH")
        if not model_path:
            raise RuntimeError("Set VOSK_MODEL_PATH to an unpacked Vosk speech model.")
        # USB microphones commonly expose only 44.1 or 48 kHz, rather than
        # the 16 kHz used by many speech models. Vosk accepts the stream's
        # actual rate and resamples internally when needed.
        if sample_rate is None:
            sample_rate = int(sd.query_devices(device, "input")["default_samplerate"])
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
