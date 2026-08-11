#!/usr/bin/env bash
set -euo pipefail

# Varuna360 Core - macOS app bundle build (Nuitka).
#
# SUPPORTED PYTHON: 3.10 to 3.11 (3.12+ works only if you can compile
# pyswisseph from source; see the preflight below).
#
# Nuitka `--mode=app` on macOS means: standalone bundle, NOT onefile. The
# compiled code and every --include-data-* payload land side by side in
# Varuna360Core.app/Contents/MacOS/.

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build script must be run on macOS."
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
TARGET_ARCH="${TARGET_ARCH:-}"
APP_NAME="Varuna360 Core"
APP_BUNDLE_NAME="Varuna360Core"
APP_BUNDLE_ID="com.varuna360.core"
OUT_DIR="$ROOT_DIR/dist/macos"
NUITKA_CACHE_DIR="$ROOT_DIR/build/nuitka-cache"

# The icon Nuitka converts to .icns. varuna360_lite.png is the BLUE cat — the
# Core/Lite brand. varuna360.png (the red cat) is the full/Pro app's icon; the
# Windows/AppImage Core builds still ship it by accident of the same default,
# so this script is deliberately the first to use the Core-blue asset.
# (The old script pointed at a varuna-logo.webp that never existed.)
ICON_SRC="${ICON_SRC:-$ROOT_DIR/icon/varuna360_lite.png}"

# Version comes from the VERSION file, never from a constant in this script.
# A hardcoded value goes stale silently and ships a wrong CFBundleVersion.
if [[ -n "${APP_VERSION:-}" ]]; then
  :
elif [[ -f "$ROOT_DIR/VERSION" ]]; then
  APP_VERSION="$(tr -d ' \t\r\n' < "$ROOT_DIR/VERSION")"
else
  APP_VERSION="0.0.0"
  echo "WARNING: no VERSION file at $ROOT_DIR/VERSION; using $APP_VERSION."
  echo "         Set APP_VERSION=x.y.z to override."
fi

if [[ ! "$APP_VERSION" =~ ^[0-9]+(\.[0-9]+){0,3}$ ]]; then
  echo "APP_VERSION must look like 1.2.3, got: $APP_VERSION"
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python not found at $PYTHON_BIN"
  echo "Set PYTHON_BIN=/path/to/python or create the project .venv first."
  exit 1
fi

# ---------------------------------------------------------------------------
# Preflight: Python version and the dependencies that fail late and obscurely
# ---------------------------------------------------------------------------
PY_VER="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_MAJOR="${PY_VER%%.*}"
PY_MINOR="${PY_VER##*.}"

if (( PY_MAJOR != 3 || PY_MINOR < 10 )); then
  echo "Python $PY_VER is too old. Varuna360 Core needs Python 3.10 or newer."
  exit 1
fi

if (( PY_MINOR > 11 )); then
  cat <<EOF
NOTE: building with Python $PY_VER.
      pyswisseph's latest release (2.10.3.2, June 2023) publishes wheels for
      cp36 to cp311 only. On Python 3.12+ pip has to build it from C source,
      which needs the Xcode command line tools. Python 3.11 is the smoothest
      environment for this build.
EOF
  if ! xcode-select -p >/dev/null 2>&1; then
    echo "      Xcode command line tools are NOT installed."
    echo "      Install them with: xcode-select --install"
  fi
fi

MISSING_MODULES=()
for module in swisseph PySide6 timezonefinder; do
  if ! "$PYTHON_BIN" -c "import $module" >/dev/null 2>&1; then
    MISSING_MODULES+=("$module")
  fi
done

if (( ${#MISSING_MODULES[@]} > 0 )); then
  echo "These runtime modules cannot be imported by $PYTHON_BIN:"
  printf '  %s\n' "${MISSING_MODULES[@]}"
  echo
  echo "Install the runtime dependencies first:"
  echo "  $PYTHON_BIN -m pip install -r $ROOT_DIR/requirements.txt"
  for module in "${MISSING_MODULES[@]}"; do
    if [[ "$module" == "swisseph" && $PY_MINOR -gt 11 ]]; then
      echo
      echo "swisseph comes from the pyswisseph package. On Python $PY_VER there is"
      echo "no wheel, so pip compiles it from C source and needs the Xcode command"
      echo "line tools (xcode-select --install). Using Python 3.11 avoids this."
    fi
  done
  exit 1
fi

if ! "$PYTHON_BIN" -m nuitka --version >/dev/null 2>&1; then
  echo "Nuitka is not installed for $PYTHON_BIN"
  echo "Install it with: $PYTHON_BIN -m pip install -U nuitka ordered-set zstandard imageio"
  exit 1
fi

# Nuitka converts a PNG icon to .icns through imageio and hard-exits without it.
if [[ "$ICON_SRC" != *.icns ]] && ! "$PYTHON_BIN" -c "import imageio" >/dev/null 2>&1; then
  echo "imageio is required to convert $ICON_SRC into a macOS .icns icon."
  echo "Install it with: $PYTHON_BIN -m pip install -U imageio"
  exit 1
fi

if [[ ! -f "$ICON_SRC" ]]; then
  echo "Missing icon source: $ICON_SRC"
  echo "Set ICON_SRC=/path/to/icon.png (or .icns) to override."
  exit 1
fi

PYTHON_ARCH="$("$PYTHON_BIN" -c 'import platform; print(platform.machine())')"
if [[ -z "$TARGET_ARCH" ]]; then
  TARGET_ARCH="$PYTHON_ARCH"
fi

if [[ "$TARGET_ARCH" != "arm64" && "$TARGET_ARCH" != "x86_64" ]]; then
  echo "Unsupported target architecture: $TARGET_ARCH"
  echo "Expected arm64 or x86_64."
  exit 1
fi

if [[ "$PYTHON_ARCH" != "$TARGET_ARCH" ]]; then
  echo "Python architecture ($PYTHON_ARCH) does not match target ($TARGET_ARCH)."
  echo "Use a $TARGET_ARCH Python environment via PYTHON_BIN."
  exit 1
fi

if "$PYTHON_BIN" -m nuitka --help 2>&1 | grep -q -- '--target-arch'; then
  TARGET_ARCH_ARG="--target-arch=$TARGET_ARCH"
else
  TARGET_ARCH_ARG="--macos-target-arch=$TARGET_ARCH"
fi

mkdir -p "$OUT_DIR" "$NUITKA_CACHE_DIR"
cd "$ROOT_DIR"
export NUITKA_CACHE_DIR

DATA_ARGS=()
for data_dir in img icon data docs ephe libaditya/ephe; do
  if [[ -d "$ROOT_DIR/$data_dir" ]]; then
    DATA_ARGS+=("--include-data-dir=$ROOT_DIR/$data_dir=$data_dir")
  else
    echo "WARNING: skipping missing data directory $data_dir"
  fi
done

for optional_file in VERSION app_settings.json settings.json map_tiles_cache.db; do
  if [[ -f "$ROOT_DIR/$optional_file" ]]; then
    DATA_ARGS+=("--include-data-files=$ROOT_DIR/$optional_file=$optional_file")
  fi
done

# Package DATA, not just package code. Nuitka copies data files only for
# packages it has a rule for (nuitka/plugins/standard/
# standard.nuitka-package.config.yml already covers certifi, qt_material and
# tzdata). timezonefinder has no such rule, and its ~60 MB data/ directory
# (zone_ids.npy, zone_positions.npy, *.fbs, timezone_names.txt,
# hole_registry.json) is what every timezone-from-map lookup reads. Without
# this flag the app builds fine and then fails at runtime on the first chart
# whose timezone is resolved from coordinates.
INCLUDE_ARGS=(
  --include-package=timezonefinder
  --include-package-data=timezonefinder
  --include-module=geopy.geocoders
  --include-module=jwt
  --include-module=cryptography
  --include-module=requests
)

if "$PYTHON_BIN" -c "import geocoder" >/dev/null 2>&1; then
  INCLUDE_ARGS+=(--include-module=geocoder)
fi

"$PYTHON_BIN" -m nuitka \
  --mode=app \
  "$TARGET_ARCH_ARG" \
  --static-libpython=no \
  --deployment \
  --enable-plugin=pyside6 \
  --macos-app-name="$APP_NAME" \
  --macos-signed-app-name="$APP_BUNDLE_ID" \
  --macos-app-version="$APP_VERSION" \
  --macos-app-mode=gui \
  --macos-app-icon="$ICON_SRC" \
  --company-name="Varuna360" \
  --product-name="$APP_NAME" \
  --file-version="$APP_VERSION" \
  --product-version="$APP_VERSION" \
  --output-dir="$OUT_DIR" \
  --output-filename="$APP_BUNDLE_NAME" \
  --remove-output \
  --disable-cache=bytecode \
  --include-package=AI_tools \
  --include-package=apps \
  --include-package=browser_tools \
  --include-package=cache \
  --include-package=core \
  --include-package=libaditya \
  --include-package=managers \
  --include-package=panels \
  --include-package=state \
  --include-package=tools \
  --include-package=ui \
  --include-package=utils \
  --include-package=visualizations \
  "${INCLUDE_ARGS[@]}" \
  --nofollow-import-to=tkinter \
  --nofollow-import-to=customtkinter \
  --nofollow-import-to=matplotlib \
  --nofollow-import-to=IPython \
  --nofollow-import-to=notebook \
  "${DATA_ARGS[@]}" \
  "$ROOT_DIR/run_app.py"

BUILT_APP="$OUT_DIR/run_app.app"
TARGET_APP="$OUT_DIR/$APP_BUNDLE_NAME.app"
if [[ -d "$BUILT_APP" && "$BUILT_APP" != "$TARGET_APP" ]]; then
  # Previous bundles are moved aside, never deleted, so a working build is
  # never lost to a bad one. Clear build/previous-bundles/ by hand.
  if [[ -e "$TARGET_APP" ]]; then
    ATTIC="$ROOT_DIR/build/previous-bundles"
    mkdir -p "$ATTIC"
    mv "$TARGET_APP" "$ATTIC/$APP_BUNDLE_NAME-$(date +%Y%m%d-%H%M%S).app"
  fi
  mv "$BUILT_APP" "$TARGET_APP"
fi

# Post-build check: a missing timezonefinder data directory is invisible until
# a user tries to place a birth location, so verify it here instead.
TZF_DATA="$TARGET_APP/Contents/MacOS/timezonefinder/data"
if [[ -d "$TZF_DATA" ]]; then
  echo "timezonefinder data bundled: $(ls -1 "$TZF_DATA" | wc -l | tr -d ' ') files"
else
  echo "ERROR: timezonefinder data is missing from the bundle ($TZF_DATA)."
  echo "       Timezone lookup from the map would fail at runtime."
  exit 1
fi

echo
echo "Built unsigned app bundle:"
echo "$TARGET_APP"
echo "Version: $APP_VERSION"
echo "Architecture: $TARGET_ARCH"
