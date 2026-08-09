# Orange Castle Assistant progress

## Completed

- Replaced the Vosk-first flow with local Whisper speech recognition.
- Added guided wake-word, todo, reminder, recurring-reminder, completion, and delay interactions.
- Added microphone selection and persisted the selected device locally.
- Added the React/Tailwind touchscreen dashboard with Today, Todos, Reminders, Shopping, and Weather views.
- Tailored the dashboard for Sapulpa, Oklahoma, Fahrenheit temperatures, and Orange Castle Assistant branding.

## In progress

- Git-hosted, device-managed updates with automatic service restart and rollback.

## Next family-device steps

1. Run `sudo bash scripts/install-device.sh` once on each trusted Raspberry Pi.
2. Set the repository URL, branch, install path, device user, and audio settings in the generated configuration files.
3. Push approved changes to the configured Git branch; the device checks every 15 minutes by default.
