#!/usr/bin/env bash
# Run the repository-local installation with its repository-local Whisper build.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXECUTABLE="$ROOT/.venv/bin/pi-assistant"
WHISPER_BINARY="$ROOT/.tools/whisper.cpp/build/bin/whisper-cli"

if [ ! -x "$EXECUTABLE" ] || [ ! -x "$WHISPER_BINARY" ]; then
    printf 'First-run setup is required; installing dependencies and building whisper.cpp...\n'
    bash "$ROOT/scripts/setup.sh"
fi

[ -x "$EXECUTABLE" ] || {
    printf 'Setup did not create pi-assistant. Review the setup output above.\n' >&2
    exit 1
}
[ -x "$WHISPER_BINARY" ] || {
    printf 'Setup did not build whisper-cli. Review the setup output above.\n' >&2
    exit 1
}

exec "$EXECUTABLE" --whisper-binary "$WHISPER_BINARY" "$@"
