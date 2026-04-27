#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="Second Brain"
APP_DIR="$ROOT_DIR/dist/mac/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
BACKEND_DIR="$RESOURCES_DIR/backend"
BUILD_CACHE_DIR="$ROOT_DIR/.build/macos"
ICON_SVG="$ROOT_DIR/frontend/public/app-icon.svg"
ICONSET_DIR="$BUILD_CACHE_DIR/AppIcon.iconset"
ICON_PNG="$BUILD_CACHE_DIR/AppIcon-1024.png"

if [[ -e "$APP_DIR" ]]; then
  echo "Build output already exists: $APP_DIR"
  echo "Move or remove it before rebuilding."
  exit 1
fi

if [[ ! -x "$ROOT_DIR/backend/venv/bin/python" ]]; then
  echo "Missing backend virtualenv: backend/venv/bin/python"
  echo "Create it and install backend/requirements.txt first."
  exit 1
fi

echo "Building frontend..."
cd "$ROOT_DIR/frontend"
npm run build

echo "Creating app bundle..."
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR" "$BACKEND_DIR" "$BUILD_CACHE_DIR/clang-module-cache" "$BUILD_CACHE_DIR/swift-module-cache"

CLANG_MODULE_CACHE_PATH="$BUILD_CACHE_DIR/clang-module-cache" \
swiftc -module-cache-path "$BUILD_CACHE_DIR/swift-module-cache" \
  "$ROOT_DIR/macos/SecondBrainApp.swift" \
  -o "$MACOS_DIR/SecondBrain" \
  -framework Cocoa \
  -framework WebKit

cp "$ROOT_DIR/macos/Info.plist" "$CONTENTS_DIR/Info.plist"

if command -v rsvg-convert >/dev/null 2>&1; then
  echo "Generating app icon..."
  rm -rf "$ICONSET_DIR"
  mkdir -p "$ICONSET_DIR"
  rsvg-convert -w 1024 -h 1024 "$ICON_SVG" -o "$ICON_PNG"
  sips -z 16 16 "$ICON_PNG" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
  sips -z 32 32 "$ICON_PNG" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
  sips -z 32 32 "$ICON_PNG" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
  sips -z 64 64 "$ICON_PNG" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 "$ICON_PNG" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
  sips -z 256 256 "$ICON_PNG" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
  sips -z 256 256 "$ICON_PNG" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
  sips -z 512 512 "$ICON_PNG" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 "$ICON_PNG" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
  cp "$ICON_PNG" "$ICONSET_DIR/icon_512x512@2x.png"
  python3 "$ROOT_DIR/scripts/make_icns.py" "$ICONSET_DIR" "$RESOURCES_DIR/AppIcon.icns"
else
  echo "rsvg-convert is required to generate AppIcon.icns."
  exit 1
fi

ditto "$ROOT_DIR/frontend/dist" "$RESOURCES_DIR/frontend"
ditto "$ROOT_DIR/backend/app" "$BACKEND_DIR/app"
ditto "$ROOT_DIR/backend/venv" "$BACKEND_DIR/venv"
cp "$ROOT_DIR/backend/requirements.txt" "$BACKEND_DIR/requirements.txt"
chmod +x "$MACOS_DIR/SecondBrain"

echo "Created: $APP_DIR"
echo "Runtime data directory: ~/Library/Application Support/Second Brain"
