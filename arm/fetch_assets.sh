#!/usr/bin/env bash
# Downloads the large files the arm panel needs but the repo doesn't store:
#   vendor/mediapipe/  MediaPipe Tasks Vision 0.10.14 (hand tracking + cup detection), ~22 MB
#   sim/SO101/         official SO-101 MuJoCo model (only for sim_primera.py), ~15 MB, with --sim
# Downloads resume where they stopped, so a flaky network only costs time.
set -euo pipefail
cd "$(dirname "$0")"

fetch() {  # fetch <url> <file>
  local url=$1 file=$2
  mkdir -p "$(dirname "$file")"
  for _ in $(seq 1 30); do
    curl -sSfL -C - --speed-limit 1024 --speed-time 30 -o "$file" "$url" && { echo "ok   $file"; return 0; }
    sleep 3
  done
  echo "FAIL $file" >&2
  return 1
}

CDN=https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14
MODELS=https://storage.googleapis.com/mediapipe-models
fetch "$CDN/vision_bundle.mjs" vendor/mediapipe/vision_bundle.mjs
fetch "$CDN/wasm/vision_wasm_internal.js" vendor/mediapipe/wasm/vision_wasm_internal.js
fetch "$CDN/wasm/vision_wasm_internal.wasm" vendor/mediapipe/wasm/vision_wasm_internal.wasm
fetch "$MODELS/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task" vendor/mediapipe/hand_landmarker.task
fetch "$MODELS/object_detector/efficientdet_lite0/int8/1/efficientdet_lite0.tflite" vendor/mediapipe/efficientdet_lite0.tflite

if [[ "${1:-}" == "--sim" ]]; then
  SIM=https://raw.githubusercontent.com/TheRobotStudio/SO-ARM100/main/Simulation/SO101
  for f in scene.xml so101_new_calib.xml joints_properties.xml; do fetch "$SIM/$f" "sim/SO101/$f"; done
  for f in $(grep -o 'file="[^"]*\.stl"' sim/SO101/so101_new_calib.xml | sed 's/file="\(.*\)"/\1/' | sort -u); do
    fetch "$SIM/assets/$f" "sim/SO101/assets/$f"
  done
fi
