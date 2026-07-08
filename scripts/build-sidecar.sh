#!/usr/bin/env bash
# Package the Python backend as a Tauri sidecar binary (macOS / Linux).
# Mirror of scripts/build-sidecar.bat. Run from anywhere; project root is
# derived from this script's location.
#
# Output: apps/desktop/src-tauri/binaries/personal-assistant-server-<target-triple>
# (e.g. ...-aarch64-apple-darwin, ...-x86_64-unknown-linux-gnu)
#
# Requires: uv (on PATH), Python 3.12+, PyInstaller (via `uv sync --extra dev`).
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

export PYTHONUTF8=1

# Detect the Tauri target triple. Tauri requires Rust, so prefer `rustc -vV`;
# fall back to uname for machines without rustc in PATH.
if command -v rustc >/dev/null 2>&1; then
    TARGET_TRIPLE="$(rustc -vV | awk '/^host:/ {print $2}')"
else
    OS="$(uname -s)"
    ARCH="$(uname -m)"
    case "$OS" in
        Darwin)
            case "$ARCH" in
                arm64|aarch64) TRIPLE_ARCH=aarch64 ;;
                *) TRIPLE_ARCH=x86_64 ;;
            esac
            TARGET_TRIPLE="$TRIPLE_ARCH-apple-darwin"
            ;;
        Linux)
            TARGET_TRIPLE="x86_64-unknown-linux-gnu"
            ;;
        *)
            echo "[build-sidecar] unsupported OS: $OS (this script targets macOS/Linux; use build-sidecar.bat on Windows)" >&2
            exit 1
            ;;
    esac
fi

echo "=== [1/2] PyInstaller (target: $TARGET_TRIPLE) ==="
if ! command -v uv >/dev/null 2>&1; then
    echo "[build-sidecar] uv not found on PATH. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi
uv run pyinstaller personal_assistant.spec --noconfirm

echo "=== [2/2] Copy artifact to Tauri binaries ==="
# On Unix PyInstaller produces dist/personal-assistant-server (no .exe suffix).
SRC="dist/personal-assistant-server"
if [ ! -f "$SRC" ]; then
    echo "[build-sidecar] expected artifact not found: $SRC" >&2
    exit 1
fi
OUT="apps/desktop/src-tauri/binaries/personal-assistant-server-$TARGET_TRIPLE"
mkdir -p "$(dirname "$OUT")"
cp -f "$SRC" "$OUT"
echo "=== Done: $OUT ==="
echo "Next: cd apps/desktop && npm run tauri dev   (or npm run tauri build for a .app/.dmg / AppImage)"
