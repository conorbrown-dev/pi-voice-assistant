#!/usr/bin/env bash
# One-time trusted-device installer for Orange Castle Assistant.
set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || { printf 'Run with sudo: sudo bash scripts/install-device.sh\n' >&2; exit 1; }

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${SUDO_USER:-pi}"
USER_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"
INSTALL_ROOT="${USER_HOME:-/home/$SERVICE_USER}/orange-castle-assistant"
UPDATE_BRANCH="main"
REPOSITORY_URL="$(git -C "$SOURCE_ROOT" remote get-url origin 2>/dev/null || true)"

usage() {
    printf 'Usage: sudo bash scripts/install-device.sh [--repository URL] [--branch BRANCH] [--user USER] [--install-root PATH]\n'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repository) REPOSITORY_URL="$2"; shift 2 ;;
        --branch) UPDATE_BRANCH="$2"; shift 2 ;;
        --user) SERVICE_USER="$2"; USER_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"; INSTALL_ROOT="${USER_HOME:-/home/$SERVICE_USER}/orange-castle-assistant"; shift 2 ;;
        --install-root) INSTALL_ROOT="$2"; shift 2 ;;
        --help) usage; exit 0 ;;
        *) usage >&2; exit 1 ;;
    esac
done

[[ -n "$REPOSITORY_URL" ]] || { printf 'Provide --repository URL, or run from a Git checkout with origin configured.\n' >&2; exit 1; }
id "$SERVICE_USER" >/dev/null || { printf 'User does not exist: %s\n' "$SERVICE_USER" >&2; exit 1; }

run_as_device_user() {
    runuser -u "$SERVICE_USER" -- "$@"
}

if [[ -e "$INSTALL_ROOT" && ! -d "$INSTALL_ROOT/.git" ]]; then
    printf 'Install path exists and is not an Orange Castle Git checkout: %s\n' "$INSTALL_ROOT" >&2
    exit 1
fi
if [[ ! -d "$INSTALL_ROOT/.git" ]]; then
    install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$(dirname "$INSTALL_ROOT")"
    run_as_device_user git clone --branch "$UPDATE_BRANCH" "$REPOSITORY_URL" "$INSTALL_ROOT"
fi

bash "$INSTALL_ROOT/scripts/setup.sh" --system-deps-only
run_as_device_user bash "$INSTALL_ROOT/scripts/setup.sh" --skip-system-deps
run_as_device_user npm --prefix "$INSTALL_ROOT/web" ci
run_as_device_user npm --prefix "$INSTALL_ROOT/web" run build

install -d -m 0755 /etc/orange-castle
cat > /etc/orange-castle/updater.conf <<EOF
INSTALL_ROOT=$INSTALL_ROOT
SERVICE_USER=$SERVICE_USER
UPDATE_BRANCH=$UPDATE_BRANCH
VOICE_SERVICE=orange-castle-voice.service
DASHBOARD_SERVICE=orange-castle-dashboard.service
EOF
if [[ ! -e /etc/orange-castle/voice.env ]]; then
cat > /etc/orange-castle/voice.env <<'EOF'
# Set these for the microphone and speakers attached to this Raspberry Pi.
PI_ASSISTANT_WAKE_WORD=Computer
# PI_ASSISTANT_AUDIO_DEVICE=sysdefault:CARD=Headphones
EOF
fi
chmod 0644 /etc/orange-castle/updater.conf /etc/orange-castle/voice.env

for unit in orange-castle-voice.service orange-castle-dashboard.service orange-castle-updater.service; do
    sed -e "s|__INSTALL_ROOT__|$INSTALL_ROOT|g" -e "s|__SERVICE_USER__|$SERVICE_USER|g" "$INSTALL_ROOT/deploy/$unit" > "/etc/systemd/system/$unit"
done
install -m 0644 "$INSTALL_ROOT/deploy/orange-castle-updater.timer" /etc/systemd/system/orange-castle-updater.timer
systemctl daemon-reload
if systemctl list-unit-files --type=service | grep -q '^pi-voice-assistant.service'; then
    systemctl disable --now pi-voice-assistant.service || true
fi
systemctl enable --now orange-castle-voice.service orange-castle-dashboard.service orange-castle-updater.timer

STATE_DIR="$INSTALL_ROOT/.orange-castle"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$STATE_DIR"
initial_commit="$(run_as_device_user git -C "$INSTALL_ROOT" rev-parse HEAD)"
printf 'previous_commit=initial-install\ninstalled_commit=%s\nupdated_at=%s\n' "$initial_commit" "$(date --iso-8601=seconds)" > "$STATE_DIR/previous-update.txt"
chown "$SERVICE_USER:$SERVICE_USER" "$STATE_DIR/previous-update.txt"

printf 'Orange Castle Assistant is installed. Dashboard: http://localhost:8080\n'
