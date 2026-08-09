#!/usr/bin/env bash
# Apply a trusted Git update, then roll back if either Orange Castle service fails.
set -euo pipefail

CONFIG_FILE="${ORANGE_CASTLE_UPDATE_CONFIG:-/etc/orange-castle/updater.conf}"
[[ -r "$CONFIG_FILE" ]] || { printf 'Updater configuration not found: %s\n' "$CONFIG_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
source "$CONFIG_FILE"

: "${INSTALL_ROOT:?INSTALL_ROOT is required}"
: "${SERVICE_USER:?SERVICE_USER is required}"
: "${UPDATE_BRANCH:=main}"
: "${VOICE_SERVICE:=orange-castle-voice.service}"
: "${DASHBOARD_SERVICE:=orange-castle-dashboard.service}"

[[ "$(id -u)" -eq 0 ]] || { printf 'Run the updater through systemd or sudo.\n' >&2; exit 1; }
[[ -d "$INSTALL_ROOT/.git" ]] || { printf 'Not a Git checkout: %s\n' "$INSTALL_ROOT" >&2; exit 1; }
command -v flock >/dev/null || { printf 'flock is required for safe updates.\n' >&2; exit 1; }

STATE_DIR="$INSTALL_ROOT/.orange-castle"
mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/update.lock"
flock -n 9 || { printf 'An Orange Castle update is already running.\n'; exit 0; }

run_as_device_user() {
    runuser -u "$SERVICE_USER" -- "$@"
}

git_as_device_user() {
    run_as_device_user git -C "$INSTALL_ROOT" -c safe.directory="$INSTALL_ROOT" "$@"
}

service_ready() {
    local attempt
    for attempt in {1..20}; do
        if systemctl is-active --quiet "$VOICE_SERVICE" && systemctl is-active --quiet "$DASHBOARD_SERVICE"; then
            return 0
        fi
        sleep 1
    done
    return 1
}

prepare_current_checkout() {
    [[ -x "$INSTALL_ROOT/.venv/bin/python" ]] || {
        printf 'No virtual environment at %s; run install-device.sh first.\n' "$INSTALL_ROOT" >&2
        return 1
    }
    run_as_device_user "$INSTALL_ROOT/.venv/bin/python" -m pip install --upgrade -e "$INSTALL_ROOT[voice,piper]"
    run_as_device_user npm --prefix "$INSTALL_ROOT/web" ci
    run_as_device_user npm --prefix "$INSTALL_ROOT/web" run build
}

current_commit="$(git_as_device_user rev-parse HEAD)"
git_as_device_user fetch --quiet --prune origin "$UPDATE_BRANCH"
target_commit="$(git_as_device_user rev-parse "origin/$UPDATE_BRANCH")"

if [[ "$current_commit" == "$target_commit" ]]; then
    printf 'Orange Castle Assistant is already current at %s.\n' "$current_commit"
    exit 0
fi

printf 'Updating Orange Castle Assistant from %s to %s.\n' "$current_commit" "$target_commit"
systemctl stop "$VOICE_SERVICE" "$DASHBOARD_SERVICE"

rollback() {
    printf 'Update failed; restoring %s.\n' "$current_commit" >&2
    git_as_device_user reset --hard "$current_commit"
    prepare_current_checkout || true
    systemctl restart "$VOICE_SERVICE" "$DASHBOARD_SERVICE" || true
    printf 'failed_commit=%s\nprevious_commit=%s\nfailed_at=%s\n' "$target_commit" "$current_commit" "$(date --iso-8601=seconds)" > "$STATE_DIR/last-update-failure.txt"
}

trap rollback ERR
git_as_device_user reset --hard "$target_commit"
prepare_current_checkout
systemctl restart "$VOICE_SERVICE" "$DASHBOARD_SERVICE"
service_ready
trap - ERR

printf 'previous_commit=%s\ninstalled_commit=%s\nupdated_at=%s\n' "$current_commit" "$target_commit" "$(date --iso-8601=seconds)" > "$STATE_DIR/previous-update.txt"
rm -f "$STATE_DIR/last-update-failure.txt"
printf 'Orange Castle Assistant updated successfully to %s.\n' "$target_commit"
