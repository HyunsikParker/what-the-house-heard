#!/usr/bin/env bash
# One night, end to end. Needs `pip install -r requirements.txt` and a running llama.cpp server with Gemma (see README).
set -euo pipefail
PY="${PYTHON:-python3}"
OUT="${1:-out}"
"$PY" simulate.py "$OUT"
"$PY" detect.py "$OUT" "$OUT/events.json" ${TABPFN_MODEL_PATH:+--model-path "$TABPFN_MODEL_PATH"}
"$PY" narrate.py "$OUT/events.json" "$OUT/story.json"
"$PY" report.py "$OUT/events.json" "$OUT/story.json" "$OUT/report.html"
echo "open $OUT/report.html"
