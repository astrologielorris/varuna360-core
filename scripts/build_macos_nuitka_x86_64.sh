#!/usr/bin/env bash
set -euo pipefail

# Build and package the Intel (x86_64) macOS bundle.
# Everything real happens in build_macos_nuitka.sh; this only pins the arch
# and the Intel interpreter. Supported Python: 3.10 to 3.11 (see that script).

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build script must be run on macOS."
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv-x86_64/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Intel Python not found at $PYTHON_BIN"
  echo "Create an x86_64 environment at .venv-x86_64 or set PYTHON_BIN."
  exit 1
fi

FOUND_ARCH="$("$PYTHON_BIN" -c 'import platform; print(platform.machine())')"
if [[ "$FOUND_ARCH" != "x86_64" ]]; then
  echo "$PYTHON_BIN reports architecture $FOUND_ARCH, not x86_64."
  echo "On Apple Silicon create the Intel environment under Rosetta:"
  echo "  arch -x86_64 /usr/local/bin/python3 -m venv $ROOT_DIR/.venv-x86_64"
  exit 1
fi

export TARGET_ARCH=x86_64
export PYTHON_BIN

"$ROOT_DIR/scripts/build_macos_nuitka.sh"
"$ROOT_DIR/scripts/package_macos_dmg.sh"
