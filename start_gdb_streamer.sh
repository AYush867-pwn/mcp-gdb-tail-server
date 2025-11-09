#!/usr/bin/env bash
# Wrapper so Claude runs the MCP entrypoint inside the venv

VENV_DIR="/Users/ayushjoshi/lpu/AIDebugger/env"
SCRIPT_DIR="/Users/ayushjoshi/lpu/AIDebugger"
ENTRYPOINT="mcp_entrypoint.py"

cd "$SCRIPT_DIR" || exit 1

if [ -f "$VENV_DIR/bin/activate" ]; then
  # shellcheck disable=SC1090
  . "$VENV_DIR/bin/activate"
  echo "[wrapper] activated venv: $VENV_DIR" >&2
fi

exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/$ENTRYPOINT"
