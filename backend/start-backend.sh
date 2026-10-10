#!/usr/bin/env bash
set -euo pipefail

BACKEND="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESK="$(cd "$BACKEND/.." && pwd)"

if [[ ! -x "$DESK/.venv/bin/python" ]]; then
  python3 -m venv "$DESK/.venv"
fi

if ! "$DESK/.venv/bin/python" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  "$DESK/.venv/bin/pip" install -r "$BACKEND/requirements.txt"
fi

if [[ ! -f "$DESK/.env" && -f "$DESK/.env.example" ]]; then
  cp "$DESK/.env.example" "$DESK/.env"
fi

cd "$BACKEND"
exec "$DESK/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
