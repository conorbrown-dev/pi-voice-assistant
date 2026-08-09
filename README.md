# Orange Castle Assistant

A small, offline-first family assistant for a Raspberry Pi with a USB microphone and speakers. It manages todos and reminders in a local SQLite database, announces reminders, and lets you complete or delay them by voice.

## What it understands

- `add todo buy milk`
- `list todos`
- `archive todo buy milk`
- `list commands`
- `remind me to take the bins out at 7:30 pm tomorrow`
- `remind me to stretch in 10 minutes`
- `add reminder pray every day at 7 am, 12 pm, and 3 pm`
- `add reminder drink water every hour`
- `done` / `complete` when a reminder is announced
- `delay 15 minutes` / `snooze 15 minutes` when a reminder is announced

The command parser deliberately keeps the language small and predictable. It supports reminders `in N minutes|hours`, `at H:MM am|pm`, and `at H:MM am|pm tomorrow`.

## Install and run

On Raspberry Pi OS, Debian/Ubuntu, Fedora, Arch Linux, or macOS, the bootstrap
script installs the required system audio library, creates a virtual
environment, builds `whisper.cpp`, and downloads the default English model.
It may ask for your password to install the system packages.

```bash
bash scripts/run.sh
```

On its first run, `scripts/run.sh` invokes `scripts/setup.sh` automatically.
You can also run the setup script directly if you want to install everything
without launching the assistant.

Pass normal assistant options through the runner:

```bash
bash scripts/run.sh --sample-rate 44100 --audio-device sysdefault:CARD=Headphones
```

The script supports macOS and common Linux distributions. Windows is not yet
supported because the audio playback and microphone setup use ALSA/PortAudio.
On an unsupported distribution, it stops before changing anything and lists
the required packages.

Piper is the default local neural voice engine. This repository includes the `en_GB-alba-medium` model and its required `.onnx.json` configuration file; it keeps the model loaded and plays generated audio with `aplay`. Select another model with `--piper-model /path/to/voice.onnx`; place its matching `/path/to/voice.onnx.json` alongside it. If ALSA's default output is misconfigured, route Piper directly to the headphone jack with `--audio-device sysdefault:CARD=Headphones`. Test that route with `speaker-test -D sysdefault:CARD=Headphones -t wav -c 2`. Piper adds 200 ms of silence before and after each reply to prevent audio devices clipping the first or final word; adjust this with `--audio-padding-ms`.

Whisper is the default speech recognizer. It records one utterance after detecting speech and transcribes it locally with `whisper.cpp`; start with `--sample-rate 44100` for the USB microphone tested here. Use `--show-audio-level` to inspect live microphone levels and capture duration. `--speech-threshold` controls when capture starts, while the lower `--silence-threshold` and `--silence-seconds` control when it ends. The defaults of 200 and 150 suit a typical USB microphone; if the displayed level stays below the speech threshold while you talk, choose the correct device or lower both thresholds. The listener retains 0.8 seconds before speech starts and 0.9 seconds after the last detected speech, reducing clipped first and last words. Tune these with `--pre-roll-seconds` and `--silence-seconds`. The application keeps the silence threshold below the start threshold and uses at least 0.8 seconds of trailing quiet to avoid cutting commands short. A four-second hard cap prevents noisy input from keeping short wake words and commands open indefinitely; change it with `--max-phrase-seconds`. Use `--save-whisper-audio captures` to retain the exact 16 kHz WAV sent to Whisper for playback and debugging. To retain the previous Vosk listener, install `pip install -e '.[vosk]'`, download and unpack `vosk-model-en-us-0.22-lgraph`, set `VOSK_MODEL_PATH` to its directory, and start with `--stt vosk`.

For responsiveness, the assistant starts a local `whisper-server` once and keeps the model loaded instead of launching and loading `whisper-cli` for every utterance. It uses all available CPU cores by default and ends an utterance after 0.9 seconds of quiet. Set `--whisper-threads N` to limit Whisper's CPU use.

On the first terminal launch, the assistant speaks a request to select the microphone while displaying the available device IDs. Type the chosen ID in the terminal; it is saved in the local assistant database and reused on later launches. Use `--device ID` for a one-run override, or `--select-microphone` to hear the selection prompt and replace the saved device. Non-interactive launches such as systemd reuse the saved device when it is available.

If Whisper does not react to speech, test PortAudio capture directly before changing transcription settings:

```bash
bash scripts/run.sh --list-microphones
bash scripts/run.sh --test-microphone --device 1
```

The input level should rise clearly while you speak. If it remains at zero, the issue is the selected device, microphone mute state, cable, or operating-system audio configuration—not Whisper.

## Wake word

The assistant listens for `Computer` by default. Say `Computer` by itself; it replies “How can I help?” and listens for one command within 20 seconds. The wake word is only an activation and is not part of command matching. Configure a different word with `--wake-word "Jarvis"` or set `PI_ASSISTANT_WAKE_WORD` for a service. Change the delay with `--wake-timeout 30`. To accept every recognized phrase without a wake word, start with `--wake-word ""`.

For a todo, say `Computer`, wait for the prompt, then say `add todo`. The assistant asks “What todo would you like to add?”; answer with the task and it confirms the saved todo.

Reminders can repeat at an interval with `every hour`, `every 3 hours`, or `every day`, or at one or more daily clock times with `every day at 7 am, 12 pm, and 3 pm`. When a recurring reminder is announced and you say `done`, it schedules its next occurrence.

If a spoken command is not recognized, run `pi-assistant --show-transcript` and use the displayed `Heard:` text to confirm what the speech recognizer decoded. `list command` (singular), `list commands`, and `what are the commands` all open the command list.

To use the former eSpeak engine instead, start with `pi-assistant --tts espeak --speech-rate 125 --pitch 40`. Piper voice samples and additional voice names are available from the official project.

```bash
pi-assistant --text
```

All state is stored locally at `~/.local/share/pi-voice-assistant/assistant.db` by default. Override it with `--database /path/to/assistant.db`.

## Touchscreen dashboard

The optional React and Tailwind touchscreen dashboard shares the assistant's
local database. It has Today, Todos, Reminders, Shopping List, and Weather
views. Todos, shopping items, and reminders can be added or completed from the
screen; a completed recurring reminder schedules its next occurrence exactly
as it does through voice. Weather uses Open-Meteo and requires internet access.

```bash
bash scripts/run-dashboard.sh
```

Open `http://localhost:8080` on the touchscreen. The dashboard binds only to
the local device by default. To expose it to trusted devices on your home
network, start it with `bash scripts/run-dashboard.sh --host 0.0.0.0` and open
`http://PI_IP:8080`. The first run installs JavaScript dependencies and builds
the dashboard. For frontend development, run `npm install && npm run dev` in
`web/`, alongside `pi-dashboard` in another terminal.

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
