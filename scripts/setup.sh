#!/usr/bin/env bash
# Set up a local development/runtime environment for Orange Castle Assistant.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
WHISPER_DIR="$ROOT/.tools/whisper.cpp"
MODEL_DIR="$ROOT/models"
MODEL_PATH="$MODEL_DIR/ggml-base.en.bin"
SKIP_SYSTEM_DEPS=false
SYSTEM_DEPS_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-system-deps) SKIP_SYSTEM_DEPS=true ;;
        --system-deps-only) SYSTEM_DEPS_ONLY=true ;;
        *) printf 'setup: unknown option: %s\n' "$1" >&2; exit 1 ;;
    esac
    shift
done

fail() {
    printf 'setup: %s\n' "$*" >&2
    exit 1
}

as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        command -v sudo >/dev/null || fail "sudo is required to install system packages."
        sudo "$@"
    fi
}

install_system_dependencies() {
    case "$(uname -s)" in
        Darwin)
            command -v brew >/dev/null || fail "Install Homebrew first: https://brew.sh"
            brew install python git portaudio cmake node
            ;;
        Linux)
            [ -r /etc/os-release ] || fail "Unsupported Linux distribution. Install Python 3.11+, PortAudio, ALSA tools, CMake, a C++ compiler, make, and Git."
            . /etc/os-release
            case "${ID:-}" in
                debian|ubuntu|raspbian)
                    as_root apt-get update
                    as_root apt-get install -y python3 python3-venv portaudio19-dev alsa-utils cmake build-essential git curl nodejs npm
                    ;;
                fedora)
                    as_root dnf install -y python3 portaudio-devel alsa-utils cmake gcc-c++ make git curl nodejs npm
                    ;;
                arch|manjaro)
                    as_root pacman -Sy --needed python portaudio alsa-utils cmake base-devel git curl nodejs npm
                    ;;
                *)
                    fail "Unsupported Linux distribution (${ID:-unknown}). Install Python 3.11+, PortAudio, ALSA tools, CMake, a C++ compiler, make, and Git."
                    ;;
            esac
            ;;
        *) fail "Unsupported operating system. This bootstrap supports macOS and common Linux distributions." ;;
    esac
}

if [[ "$SKIP_SYSTEM_DEPS" != true ]]; then
    install_system_dependencies
fi
if [[ "$SYSTEM_DEPS_ONLY" == true ]]; then
    exit 0
fi
command -v "$PYTHON_BIN" >/dev/null || fail "Python was not found: $PYTHON_BIN"
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    fail "Python 3.11 or newer is required."
fi
command -v git >/dev/null || fail "Git was not found after installing system dependencies."

if [ ! -d "$WHISPER_DIR/.git" ]; then
    mkdir -p "$(dirname "$WHISPER_DIR")"
    git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "$WHISPER_DIR"
fi

cmake -S "$WHISPER_DIR" -B "$WHISPER_DIR/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$WHISPER_DIR/build" --config Release
[ -x "$WHISPER_DIR/build/bin/whisper-cli" ] || fail "whisper.cpp built without whisper-cli."

mkdir -p "$MODEL_DIR"
if [ ! -f "$MODEL_PATH" ]; then
    (cd "$WHISPER_DIR" && sh models/download-ggml-model.sh base.en)
    cp "$WHISPER_DIR/models/ggml-base.en.bin" "$MODEL_PATH"
fi

"$PYTHON_BIN" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/python" -m pip install -e "$ROOT[voice,piper]"

printf '\nSetup complete. Start the assistant with:\n  bash scripts/run.sh\n'
