#!/usr/bin/env bash
set -euo pipefail

# Build script for tv_downloader using PyInstaller (macOS)
# - Produces a onefile binary in dist/tv_downloader
# - Keeps tv_downloader.json as a separate runtime asset copied next to the executable
# - Reuses an active virtualenv when present, otherwise creates a local .venv_build

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"

PY=${PY:-python3}

if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  PY=$(command -v python)
else
  VENV_DIR="$SCRIPT_DIR/.venv_build"
  if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating local virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1090
  source "$VENV_DIR/bin/activate"
  PY=$(command -v python)
  echo "Using Python: $($PY -c 'import sys; print(sys.executable)')"
  echo "Upgrading pip and installing dependencies..."
  "$PY" -m pip install --upgrade pip >/dev/null
  if [[ -f "$PROJECT_ROOT/requirements.txt" ]]; then
    "$PY" -m pip install -r "$PROJECT_ROOT/requirements.txt" >/dev/null
  fi
fi

# Ensure PyInstaller is available
if ! "$PY" -c 'import PyInstaller' >/dev/null 2>&1; then
  echo "Installing PyInstaller into the build environment..."
  "$PY" -m pip install pyinstaller >/dev/null
fi

APP_NAME="tv_downloader"
ENTRY="tv_downloader.py"
CONFIG_FILE="tv_downloader.json"

# Clean old build outputs
rm -rf build dist "${APP_NAME}.spec"

# Run PyInstaller
env PYTHONWARNINGS=ignore "$PY" -m PyInstaller \
  --onefile \
  --name "$APP_NAME" \
  --collect-submodules helium \
  --collect-submodules selenium \
  "$ENTRY"

# Copy runtime assets alongside the executable
if [[ -f "$CONFIG_FILE" ]]; then
  cp "$CONFIG_FILE" dist/
fi

# Show resulting artifacts
ls -lh dist

echo
echo "Build complete. Run example from $(basename "$SCRIPT_DIR")/:"
echo "  ./dist/${APP_NAME}"
