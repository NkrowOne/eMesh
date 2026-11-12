#!/usr/bin/env bash
# Makes the eMesh promo video (1:1): records the guion from the real bot against the fake Telegram of the tests
# (guion_<lang>.json) and renders it (out/emesh_promo_<lang>.mp4).
# Needs: the dev requirements (Python), Node with Playwright and Chromium, ffmpeg with libx264.
# Usage: tools/promo_video/make.sh [lang ...]      Only render (no Python): node tools/promo_video/render.js
set -euo pipefail
cd "$(dirname "$0")/../.."
PYTHON="${PYTHON:-python}"
[ -x .venv/bin/python ] && PYTHON=.venv/bin/python
"$PYTHON" -m pytest -p tests.conftest tools/promo_video/capture.py -q -n 0 -p no:cacheprovider
node tools/promo_video/render.js "$@"
