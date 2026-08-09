#!/usr/bin/env bash
# Start an already-built dashboard. Updates build it before this service restarts.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXECUTABLE="$ROOT/.venv/bin/orange-castle-dashboard"

if [[ ! -x "$EXECUTABLE" ]]; then
    printf 'Dashboard is not installed. Run scripts/setup.sh and build web/ first.\n' >&2
    exit 1
fi
if [[ ! -f "$ROOT/web/dist/index.html" ]]; then
    printf 'Dashboard assets are missing. Run npm run build in web/.\n' >&2
    exit 1
fi

exec "$EXECUTABLE" "$@"
