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
sudo apt install -y python3-venv espeak-ng portaudio19-dev
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[voice]'
```

Download a small English Vosk model and unpack it somewhere on the Pi, then point the assistant to it:

```bash
export VOSK_MODEL_PATH=/home/pi/models/vosk-model-small-en-us-0.15
pi-assistant
```

`espeak-ng` is used to speak replies. The Vosk adapter selects the first USB microphone by default and uses its advertised sample rate; pass `--device N` after checking `python -m sounddevice` if required. If a microphone needs an explicit rate, use `--sample-rate 48000`. You can use `--text` to run without microphone hardware during setup.

If a spoken command is not recognized, run `pi-assistant --show-transcript` and use the displayed `Heard:` text to confirm what the microphone and Vosk model decoded. `list command` (singular), `list commands`, and `what are the commands` all open the command list.

```bash
pi-assistant --text
```

All state is stored locally at `~/.local/share/pi-voice-assistant/assistant.db` by default. Override it with `--database /path/to/assistant.db`.

## Run at boot (systemd)

Copy and adjust the bundled service (especially `User`, `WorkingDirectory`, and `VOSK_MODEL_PATH`):

```bash
sudo cp deploy/pi-voice-assistant.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pi-voice-assistant
```

## Development

```bash
python -m unittest discover -s tests -v
```
