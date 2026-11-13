#!/usr/bin/env bash
# Makes the eMesh promo videos (1:1): records what the bot shows against the fake Telegram of the tests
# (guion_<lang>.json, spot_<lang>.json) and renders the spot with its music (out/emesh_spot_<lang>.mp4) and the
# walkthrough (out/emesh_promo_<lang>.mp4).
# Needs: the dev requirements (Python), Node with Playwright and Chromium, ffmpeg with libx264 and aac.
# Usage: tools/promo_video/make.sh [lang ...]      Only render (no Python): node tools/promo_video/render_spot.js
set -euo pipefail
cd "$(dirname "$0")/../.."
PYTHON="${PYTHON:-python}"
[ -x .venv/bin/python ] && PYTHON=.venv/bin/python
"$PYTHON" -m pytest -p tests.conftest tools/promo_video/capture.py -q -n 0 -p no:cacheprovider
node tools/promo_video/render_spot.js "$@"
node tools/promo_video/render.js "$@"
