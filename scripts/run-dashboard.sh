#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
WEB_DIR="$PROJECT_DIR/web"

if [[ ! -x "$VENV_DIR/bin/orange-castle-dashboard" ]]; then
  echo "The Python environment is missing. Running setup first."
  bash "$PROJECT_DIR/scripts/setup.sh"
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js 20 or newer and npm are required for the touchscreen dashboard."
  exit 1
fi
if [[ ! -d "$WEB_DIR/node_modules" ]]; then
  (cd "$WEB_DIR" && npm install)
fi
(cd "$WEB_DIR" && npm run build)
exec "$VENV_DIR/bin/orange-castle-dashboard" "$@"
