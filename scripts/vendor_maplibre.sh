#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="$ROOT_DIR/src/trailgen/renderer/vendor"
VERSION="${1:-3.6.2}"

mkdir -p "$DEST_DIR"

curl -fsSL "https://unpkg.com/maplibre-gl@${VERSION}/dist/maplibre-gl.css" \
  -o "$DEST_DIR/maplibre-gl.css"

curl -fsSL "https://unpkg.com/maplibre-gl@${VERSION}/dist/maplibre-gl.js" \
  -o "$DEST_DIR/maplibre-gl.js"

echo "Vendored MapLibre GL ${VERSION} into $DEST_DIR"
