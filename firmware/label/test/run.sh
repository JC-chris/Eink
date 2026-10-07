#!/bin/sh
# Compileert de C-decoder en test hem tegen frames die de Python-backend maakt.
set -e
cd "$(dirname "$0")"
ROOT=../../..
OUT=$(mktemp -d)
cc -std=c11 -Wall -Wextra -Werror -O2 -o "$OUT/test" test_eink_image.c ../src/eink_image.c
PYTHONPATH=$ROOT/backend python3 - "$OUT" <<'PY'
import sys
from eink_cloud.displays import DISPLAY_TYPES
from eink_cloud.render import LabelContent, render_frame
out = sys.argv[1]
content = LabelContent("Runderbiefstuk", 1295, "kg", origin="Nederland", promo_text="Weekaanbieding")
for d in DISPLAY_TYPES.values():
    frame, _ = render_frame(content, d)
    open(f"{out}/{d.id}.frame", "wb").write(frame.encode())
    open(f"{out}/{d.id}.raw", "wb").write(frame.raw)
PY
for f in "$OUT"/*.frame; do
	printf '%s: ' "$(basename "$f" .frame)"
	"$OUT/test" "$f" "${f%.frame}.raw"
done
rm -rf "$OUT"
