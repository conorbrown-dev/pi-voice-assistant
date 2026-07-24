# Pi Voice Assistant

A small, offline-first voice assistant for a Raspberry Pi with a USB microphone and speakers. It manages todos and reminders in a local SQLite database, announces reminders, and lets you complete or delay them by voice.

## What it understands

- `add todo buy milk`
- `list todos`
- `archive todo buy milk`
- `list commands`
- `remind me to take the bins out at 7:30 pm tomorrow`
- `remind me to stretch in 10 minutes`
- `done` / `complete` when a reminder is announced
- `delay 15 minutes` / `snooze 15 minutes` when a reminder is announced

The command parser deliberately keeps the language small and predictable. It supports reminders `in N minutes|hours`, `at H:MM am|pm`, and `at H:MM am|pm tomorrow`.

## Raspberry Pi setup

Use Raspberry Pi OS Bookworm or later and Python 3.11+.

```bash
sudo apt update
sudo apt install -y python3-venv portaudio19-dev alsa-utils cmake build-essential
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[voice,piper]'
```

Build the local Whisper recognizer and download its English `base.en` model:

```bash
git clone https://github.com/ggml-org/whisper.cpp.git ~/whisper.cpp
cmake -S ~/whisper.cpp -B ~/whisper.cpp/build
cmake --build ~/whisper.cpp/build --config Release
mkdir -p models
sh ~/whisper.cpp/models/download-ggml-model.sh base.en
cp ~/whisper.cpp/models/ggml-base.en.bin models/
```

Run the assistant with the USB microphone's tested sample rate and direct headphone output:

```bash
pi-assistant --sample-rate 44100 --audio-device sysdefault:CARD=Headphones \
  --whisper-binary ~/whisper.cpp/build/bin/whisper-cli
```

Piper is the default local neural voice engine. This repository includes the `en_GB-alba-medium` model and its required `.onnx.json` configuration file; it keeps the model loaded and plays generated audio with `aplay`. Select another model with `--piper-model /path/to/voice.onnx`; place its matching `/path/to/voice.onnx.json` alongside it. If ALSA's default output is misconfigured, route Piper directly to the headphone jack with `--audio-device sysdefault:CARD=Headphones`. Test that route with `speaker-test -D sysdefault:CARD=Headphones -t wav -c 2`.

Whisper is the default speech recognizer. It records one utterance after detecting speech and transcribes it locally with `whisper.cpp`; start with `--sample-rate 44100` for the USB microphone tested here. Use `--show-audio-level` to inspect capture duration and tune `--speech-threshold` if needed. To retain the previous Vosk listener, download and unpack `vosk-model-en-us-0.22-lgraph`, set `VOSK_MODEL_PATH` to its directory, and start with `--stt vosk`.

## Wake word

The assistant listens for `Computer` by default. Say `Computer, list commands`, or say `Computer` and give the command within 20 seconds. Configure a different word with `--wake-word "Jarvis"` or set `PI_ASSISTANT_WAKE_WORD` for a service. Change the delay with `--wake-timeout 30`. To accept every recognized phrase without a wake word, start with `--wake-word ""`.

If a spoken command is not recognized, run `pi-assistant --show-transcript` and use the displayed `Heard:` text to confirm what the speech recognizer decoded. `list command` (singular), `list commands`, and `what are the commands` all open the command list.

To use the former eSpeak engine instead, start with `pi-assistant --tts espeak --speech-rate 125 --pitch 40`. Piper voice samples and additional voice names are available from the official project.

```bash
pi-assistant --text
```

All state is stored locally at `~/.local/share/pi-voice-assistant/assistant.db` by default. Override it with `--database /path/to/assistant.db`.

## Run at boot (systemd)

Copy and adjust the bundled service (especially `User`, `WorkingDirectory`, the Whisper/Piper model paths, and the audio device):

```bash
sudo cp deploy/pi-voice-assistant.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pi-voice-assistant
```

## Development

```bash
python -m unittest discover -s tests -v
```
