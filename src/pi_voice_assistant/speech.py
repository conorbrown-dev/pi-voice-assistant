from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import time
import wave
from urllib.error import URLError
from urllib.request import Request, urlopen
from abc import ABC, abstractmethod
from array import array
from collections import deque
from math import isqrt
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

    def __init__(self, model_path: Path, audio_device: str | None = None, padding_ms: int = 200) -> None:
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
        self.padding_ms = max(0, padding_ms)

    def say(self, text: str) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav") as source_file, tempfile.NamedTemporaryFile(suffix=".wav") as audio_file:
            with wave.open(source_file.name, "wb") as wav_file:
                self.voice.synthesize_wav(text, wav_file)
            source_file.flush()
            _pad_wav(source_file.name, audio_file.name, self.padding_ms)
            audio_file.flush()
            if shutil.which("aplay"):
                command = ["aplay", "-q"]
                if self.audio_device:
                    command.extend(["-D", self.audio_device])
                command.append(audio_file.name)
            elif shutil.which("afplay"):
                if self.audio_device:
                    raise RuntimeError("--audio-device is supported only by ALSA playback.")
                command = ["afplay", audio_file.name]
            else:
                raise RuntimeError("Install an audio player: alsa-utils on Linux or afplay on macOS.")
            subprocess.run(command, check=True)


def _pad_wav(source_path: str, output_path: str, padding_ms: int) -> None:
    """Add silence around generated speech to avoid playback-device clipping."""
    with wave.open(source_path, "rb") as source:
        params = source.getparams()
        frames = source.readframes(source.getnframes())
    padding_frames = params.framerate * padding_ms // 1000
    silence = b"\0" * (padding_frames * params.nchannels * params.sampwidth)
    with wave.open(output_path, "wb") as output:
        output.setparams(params)
        output.writeframes(silence)
        output.writeframes(frames)
        output.writeframes(silence)


class Listener(ABC):
    @abstractmethod
    def listen(self, timeout: float | None = None) -> str | None: ...

    def close(self) -> None:
        """Release resources held by a listener."""


class TextListener(Listener):
    def listen(self, timeout: float | None = None) -> str | None:
        try:
            return input("You: ").strip() or None
        except EOFError:
            return None


class WhisperListener(Listener):
    """Offline Whisper transcription through a persistent whisper.cpp server."""

    def __init__(
        self,
        device: int | None,
        sample_rate: int | None,
        model_path: Path,
        binary: str = "whisper-cli",
        speech_threshold: int = 200,
        silence_threshold: int = 150,
        silence_seconds: float = 0.9,
        pre_roll_seconds: float = 0.8,
        show_audio_level: bool = False,
        prompt: str = "Computer. Add todo. List todos. Archive todo. Remind me to.",
        save_audio_directory: Path | None = None,
        threads: int = 4,
        max_phrase_seconds: float = 4.0,
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
        # A silence threshold at or above the start threshold treats ordinary
        # speech as quiet and cuts commands short. Keep a clear hysteresis
        # gap even when a command-line override is supplied.
        self.silence_threshold = min(silence_threshold, max(1, int(speech_threshold * 0.75)))
        self.silence_seconds = max(0.8, silence_seconds)
        self.pre_roll_seconds = pre_roll_seconds
        self.show_audio_level = show_audio_level
        self.prompt = prompt
        self.save_audio_directory = save_audio_directory
        self.threads = threads
        self.max_phrase_seconds = max(1.0, max_phrase_seconds)
        self.server_process: subprocess.Popen[bytes] | None = None
        self.server_port: int | None = None
        self.server_binary = self._find_server_binary(binary)
        if self.server_binary:
            self._start_server()

    def listen(self, timeout: float | None = None) -> str | None:
        audio: queue.Queue[bytes] = queue.Queue()

        def callback(indata, frames, time, status):  # type: ignore[no-untyped-def]
            if status and self.show_audio_level:
                print(f"Microphone status: {status}")
            # A status flag can accompany usable input data. Dropping the
            # whole block creates audible gaps and damages transcription.
            audio.put(bytes(indata))

        silence_frames = int(self.sample_rate * self.silence_seconds)
        maximum_frames = int(self.sample_rate * self.max_phrase_seconds)
        maximum_pre_roll_frames = int(self.sample_rate * self.pre_roll_seconds)
        pre_roll: deque[bytes] = deque()
        pre_roll_frames = 0
        recorded: list[bytes] = []
        trailing_levels: deque[tuple[int, bool]] = deque()
        trailing_frames = 0
        trailing_quiet_frames = 0
        frames = 0
        last_level_report_at = 0.0
        with self.sd.RawInputStream(samplerate=self.sample_rate, blocksize=0, device=self.device,
                                    dtype="int16", channels=1, latency="high", callback=callback):
            while True:
                data = audio.get(timeout=timeout if not recorded else None)
                level = _rms_int16(data)
                now = time.monotonic()
                if self.show_audio_level and not recorded and now - last_level_report_at >= 1.0:
                    print(f"Microphone input level: {level} (speech threshold: {self.speech_threshold})")
                    last_level_report_at = now
                if not recorded and level < self.speech_threshold:
                    pre_roll.append(data)
                    pre_roll_frames += len(data) // 2
                    while len(pre_roll) > 1 and pre_roll_frames > maximum_pre_roll_frames:
                        pre_roll_frames -= len(pre_roll.popleft()) // 2
                    continue
                if not recorded:
                    recorded.extend(pre_roll)
                    frames = sum(len(chunk) // 2 for chunk in recorded)
                    if self.show_audio_level:
                        print(f"Capture started (input level: {level}).")
                recorded.append(data)
                frames += len(data) // 2
                block_frames = len(data) // 2
                is_quiet = level < self.silence_threshold
                trailing_levels.append((block_frames, is_quiet))
                trailing_frames += block_frames
                if is_quiet:
                    trailing_quiet_frames += block_frames
                quiet_enough = (
                    trailing_frames >= silence_frames
                    and trailing_quiet_frames / trailing_frames >= 0.85
                )
                if quiet_enough or frames >= maximum_frames:
                    if self.show_audio_level:
                        quiet_percent = 100 * trailing_quiet_frames / trailing_frames if trailing_frames else 0
                        print(
                            f"Captured {frames / self.sample_rate:.1f} seconds of audio "
                            f"(ending level: {level}, trailing quiet: {quiet_percent:.0f}%)."
                        )
                    return self._transcribe(b"".join(recorded))
                while trailing_frames > silence_frames and trailing_levels:
                    old_frames, old_is_quiet = trailing_levels.popleft()
                    trailing_frames -= old_frames
                    if old_is_quiet:
                        trailing_quiet_frames -= old_frames

    def _transcribe(self, audio: bytes) -> str | None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "utterance.wav"
            output_path = Path(directory) / "transcript"
            whisper_audio = _resample_int16(audio, self.sample_rate, 16000)
            with wave.open(str(input_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                wav_file.writeframes(whisper_audio)
            if self.save_audio_directory:
                self.save_audio_directory.mkdir(parents=True, exist_ok=True)
                saved_path = self.save_audio_directory / f"whisper-capture-{time.time_ns()}.wav"
                shutil.copyfile(input_path, saved_path)
                print(f"Saved Whisper audio: {saved_path}")
            if self.server_process:
                return self._transcribe_with_server(input_path)
            result = subprocess.run(
                [self.binary, "-m", str(self.model_path), "-f", str(input_path), "-l", "en", "-t", str(self.threads), "-bo", "1", "-tpi", "0", "--prompt", self.prompt, "-nt", "-np", "-otxt", "-of", str(output_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(f"whisper-cli failed: {result.stderr.strip() or result.stdout.strip()}")
            transcript_path = output_path.with_suffix(".txt")
            return transcript_path.read_text().strip() if transcript_path.is_file() else None

    @staticmethod
    def _find_server_binary(binary: str) -> str | None:
        binary_path = Path(binary)
        if binary_path.is_file():
            sibling = binary_path.with_name("whisper-server")
            return str(sibling) if sibling.is_file() else None
        return shutil.which("whisper-server")

    def _start_server(self) -> None:
        import socket

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.server_port = port
        self.server_process = subprocess.Popen(
            [self.server_binary, "-m", str(self.model_path), "--host", "127.0.0.1", "--port", str(port), "-t", str(self.threads), "-nt"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.server_process.poll() is not None:
                self.server_process = None
                raise RuntimeError("whisper-server exited while loading the model.")
            try:
                with urlopen(f"http://127.0.0.1:{port}/", timeout=0.2):
                    return
            except URLError:
                time.sleep(0.05)
        self.close()
        raise RuntimeError("Timed out while loading whisper-server.")

    def _transcribe_with_server(self, input_path: Path) -> str | None:
        if self.server_port is None:
            raise RuntimeError("whisper-server is not running.")
        boundary = f"----pi-voice-assistant-{time.time_ns()}"
        fields = {
            "language": "en",
            "prompt": self.prompt,
            "response_format": "json",
            "no_timestamps": "true",
            "no_language_probabilities": "true",
            "best_of": "1",
            "temperature": "0.0",
            "temperature_inc": "0.0",
        }
        body: list[bytes] = []
        for name, value in fields.items():
            body.extend((f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(), value.encode(), b"\r\n"))
        body.extend((
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="utterance.wav"\r\n',
            b"Content-Type: audio/wav\r\n\r\n",
            input_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ))
        request = Request(
            f"http://127.0.0.1:{self.server_port}/inference",
            data=b"".join(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                return json.loads(response.read())["text"].strip() or None
        except (URLError, KeyError, json.JSONDecodeError) as error:
            raise RuntimeError(f"whisper-server transcription failed: {error}") from error

    def close(self) -> None:
        if not self.server_process:
            return
        self.server_process.terminate()
        try:
            self.server_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.server_process.kill()
            self.server_process.wait()
        self.server_process = None


def _rms_int16(audio: bytes) -> int:
    """Return the RMS level of native little-endian signed 16-bit PCM audio."""
    samples = array("h")
    samples.frombytes(audio)
    if not samples:
        return 0
    return isqrt(sum(sample * sample for sample in samples) // len(samples))


def _resample_int16(audio: bytes, source_rate: int, target_rate: int) -> bytes:
    """Linearly resample mono, signed 16-bit PCM without external tooling."""
    if source_rate == target_rate:
        return audio
    source = array("h")
    source.frombytes(audio)
    if not source:
        return audio
    output = array("h")
    output_length = len(source) * target_rate // source_rate
    for index in range(output_length):
        position = index * source_rate
        left = position // target_rate
        remainder = position % target_rate
        right = min(left + 1, len(source) - 1)
        value = (source[left] * (target_rate - remainder) + source[right] * remainder) // target_rate
        output.append(value)
    return output.tobytes()


class VoskListener(Listener):
    """Microphone listener; VOSK_MODEL_PATH must point to an unpacked Vosk model."""
    def __init__(self, device: int | None = None, sample_rate: int | None = None) -> None:
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model
        except ImportError as error:
            raise RuntimeError("Install Vosk support: pip install -e '.[vosk]'") from error
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
            audio.put(bytes(indata))
        with self.sd.RawInputStream(samplerate=self.sample_rate, blocksize=8000, device=self.device,
                                    dtype="int16", channels=1, callback=callback):
            while True:
                if self.recognizer.AcceptWaveform(audio.get(timeout=timeout)):
                    result = json.loads(self.recognizer.Result()).get("text", "").strip()
                    if result:
                        return result
