#!/usr/bin/env bash
# Sonora — one-click launcher (macOS / Linux)
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install it (https://www.python.org/downloads/) and run start.sh again."
  exit 1
fi

echo "Installing the HD voice engine (first run only, ~1 min)..."
python3 -m pip install --quiet edge-tts imageio-ffmpeg numpy || {
  echo "Could not install dependencies. Check your internet connection and try again."
  exit 1
}

echo
echo "Sonora is starting - opening http://localhost:8000"
(xdg-open http://localhost:8000 2>/dev/null || open http://localhost:8000 2>/dev/null) &
python3 server.py
echo
echo "Sonora has stopped."
