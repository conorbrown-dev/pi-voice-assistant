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
sudo apt install -y python3-venv portaudio19-dev alsa-utils
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[voice,piper]'
```

Download and unpack the `vosk-model-en-us-0.22-lgraph` English Vosk model somewhere on the Pi, then point the assistant to it:

```bash
export VOSK_MODEL_PATH=/home/pi/models/vosk-model-en-us-0.22-lgraph
pi-assistant
```

Piper is the default local neural voice engine. This repository includes the `en_GB-alba-medium` model and its required `.onnx.json` configuration file; it keeps the model loaded and plays generated audio with `aplay`. Select another model with `--piper-model /path/to/voice.onnx`; place its matching `/path/to/voice.onnx.json` alongside it. Test the audio route with `speaker-test -t wav -c 2`. The Vosk adapter selects the first USB microphone by default and uses its advertised sample rate; pass `--device N` after checking `python -m sounddevice` if required. If a microphone needs an explicit rate, use `--sample-rate 48000`. You can use `--text` to run without microphone hardware during setup.

## Wake word

The assistant listens for `Computer` by default. Say `Computer, list commands`, or say `Computer` and give the command within eight seconds. Configure a different word with `--wake-word "Jarvis"` or set `PI_ASSISTANT_WAKE_WORD` for a service. To accept every recognized phrase without a wake word, start with `--wake-word ""`.

If a spoken command is not recognized, run `pi-assistant --show-transcript` and use the displayed `Heard:` text to confirm what the microphone and Vosk model decoded. `list command` (singular), `list commands`, and `what are the commands` all open the command list.

To use the former eSpeak engine instead, start with `pi-assistant --tts espeak --speech-rate 125 --pitch 40`. Piper voice samples and additional voice names are available from the official project.

```bash
pi-assistant --text
```

All state is stored locally at `~/.local/share/pi-voice-assistant/assistant.db` by default. Override it with `--database /path/to/assistant.db`.

## Run at boot (systemd)

Copy and adjust the bundled service (especially `User`, `WorkingDirectory`, `VOSK_MODEL_PATH`, and the Piper model path):

```bash
sudo cp deploy/pi-voice-assistant.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pi-voice-assistant
```

## Development

```bash
python -m unittest discover -s tests -v
```
