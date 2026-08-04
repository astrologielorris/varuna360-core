#!/usr/bin/env bash
set -euo pipefail

# Varuna360 Core - DMG and ZIP packaging for the Nuitka app bundle.
#
# The bundle is ad-hoc signed by Nuitka (its default --macos-sign-identity),
# which is what lets it run at all on Apple Silicon, but it is NOT signed with
# a Developer ID and NOT notarized. Anyone who downloads the DMG gets a
# quarantine attribute and Gatekeeper will refuse the first launch; see the
# note this script prints at the end.

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This packaging script must be run on macOS."
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Varuna360Core"
VOLUME_NAME="Varuna360 Core"
TARGET_ARCH="${TARGET_ARCH:-}"
DIST_DIR="$ROOT_DIR/dist/macos"
APP_PATH="$DIST_DIR/$APP_NAME.app"
STAGING_DIR="$ROOT_DIR/build/dmg-staging"
ATTIC_DIR="$ROOT_DIR/build/previous-packages"

# Same rule as the build script: the version comes from the VERSION file.
if [[ -n "${APP_VERSION:-}" ]]; then
  :
elif [[ -f "$ROOT_DIR/VERSION" ]]; then
  APP_VERSION="$(tr -d ' \t\r\n' < "$ROOT_DIR/VERSION")"
else
  APP_VERSION=""
fi

if [[ ! -d "$APP_PATH" ]]; then
  echo "Missing app bundle: $APP_PATH"
  echo "Build it first with: scripts/build_macos_nuitka.sh"
  exit 1
fi

APP_EXECUTABLE="$APP_PATH/Contents/MacOS/$APP_NAME"
if [[ ! -f "$APP_EXECUTABLE" ]]; then
  echo "Missing app executable: $APP_EXECUTABLE"
  exit 1
fi

DETECTED_ARCH="$(lipo -archs "$APP_EXECUTABLE")"
if [[ -z "$TARGET_ARCH" ]]; then
  TARGET_ARCH="$DETECTED_ARCH"
fi

if [[ "$TARGET_ARCH" != "arm64" && "$TARGET_ARCH" != "x86_64" ]]; then
  echo "Unsupported target architecture: $TARGET_ARCH"
  echo "This script packages one architecture at a time (arm64 or x86_64)."
  echo "lipo reported: $DETECTED_ARCH"
  exit 1
fi

if [[ "$DETECTED_ARCH" != "$TARGET_ARCH" ]]; then
  echo "App architecture ($DETECTED_ARCH) does not match package target ($TARGET_ARCH)."
  exit 1
fi

# Fail early rather than shipping a bundle whose timezone data never made it in.
if [[ ! -d "$APP_PATH/Contents/MacOS/timezonefinder/data" ]]; then
  echo "Refusing to package: timezonefinder data is missing from the bundle."
  echo "Rebuild with scripts/build_macos_nuitka.sh (it passes --include-package-data)."
  exit 1
fi

if [[ -n "$APP_VERSION" ]]; then
  BASENAME="$APP_NAME-$APP_VERSION-macos-$TARGET_ARCH-unsigned"
else
  BASENAME="$APP_NAME-macos-$TARGET_ARCH-unsigned"
fi
DMG_PATH="$DIST_DIR/$BASENAME.dmg"
ZIP_PATH="$DIST_DIR/$BASENAME.zip"

# Nothing here deletes: previous artifacts are moved into build/previous-packages
# so a good package is never lost to a bad rebuild. Clear that folder by hand.
mkdir -p "$ATTIC_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
for stale in "$STAGING_DIR" "$DMG_PATH" "$ZIP_PATH"; do
  if [[ -e "$stale" ]]; then
    mv "$stale" "$ATTIC_DIR/$(basename "$stale").$STAMP"
  fi
done

mkdir -p "$STAGING_DIR" "$DIST_DIR"

ditto "$APP_PATH" "$STAGING_DIR/$APP_NAME.app"
ln -s /Applications "$STAGING_DIR/Applications"

hdiutil create \
  -volname "$VOLUME_NAME" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$ZIP_PATH"

echo
echo "Built unsigned packages:"
echo "$DMG_PATH"
echo "$ZIP_PATH"
if [[ -n "$APP_VERSION" ]]; then
  echo "Version: $APP_VERSION"
fi
echo
echo "These are ad-hoc signed only, so macOS quarantines them on download."
echo "First launch instructions for users: right click the app, choose Open,"
echo "then confirm. Or from a terminal:"
echo "  xattr -dr com.apple.quarantine /Applications/$APP_NAME.app"
