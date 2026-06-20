#!/usr/bin/env bash
# PHAGENTIC — run the web UI locally (with Web Bluetooth support).
#
#   ./run.sh            # serve on http://localhost:5173 and open the browser
#   ./run.sh 8000       # use a different port
#
# Web Bluetooth needs a secure context, which "localhost" satisfies — so the
# ⌁ connect button works straight from here, no hub required. Use Chrome or Edge
# (Firefox/Safari don't support Web Bluetooth). First load needs internet (the
# renderer pulls React from a CDN).
set -euo pipefail

PORT="${1:-5173}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
DIR="$ROOT/frontend"
URL="http://localhost:$PORT/"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to serve the UI." >&2
  exit 1
fi
if [ ! -f "$DIR/index.html" ]; then
  echo "frontend/index.html not found at $DIR" >&2
  exit 1
fi

echo "PHAGENTIC UI  →  $URL"
echo "Open in Chrome or Edge, then click  ⌁ connect  to pair the Bioreactor over Bluetooth."
echo "(No hardware? It runs a built-in simulation. Ctrl+C to stop.)"

# Open the browser a moment after the server comes up (best-effort, non-fatal).
( sleep 1; (xdg-open "$URL" >/dev/null 2>&1 || open "$URL" >/dev/null 2>&1 || true) ) &

cd "$DIR"
exec python3 -m http.server "$PORT"
