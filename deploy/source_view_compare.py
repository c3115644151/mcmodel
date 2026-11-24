#!/usr/bin/env python3
"""Put a Blockbench source view next to an in-game shot and print both colour profiles.

Judging a model from a screenshot I cropped myself has gone wrong repeatedly: the light is wrong, the
crop misses half the object, and a small thumbnail gets read as "two cubes" when it is one. This tool
removes the guesswork - it crops both pictures to their own content, scales them to one height, and
reports the colour mix of each so the comparison is a table as well as a picture.

  .venv\\Scripts\\python.exe tools/deploy/source_view_compare.py \\
      --source build/blockbench_source_previews/party_lights.png \\
      --live build/shots/pl_v13.png \\
      --crop 780,320,1240,700 --out build/pl/compare.png

The source view must come from Blockbench itself (tools/deploy/preview_brewing_sources.ps1, or
tools/mcpfabric/bb_mcp.mjs capture_screenshot). A render of the JSON by another tool is a different
renderer and cannot settle what the artist's own viewport shows.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from PIL import Image
import numpy as np


def content_box(image: Image.Image, background=None) -> tuple[int, int, int, int]:
    """Crop to everything that is not the dominant flat background colour."""
    array = np.array(image.convert("RGB")).astype(int)
    if background is None:
        colours = Counter(map(tuple, array.reshape(-1, 3)))
        background = colours.most_common(1)[0][0]
    mask = np.abs(array - np.array(background)).sum(axis=2) > 24
    rows = np.nonzero(mask.any(axis=1))[0]
    cols = np.nonzero(mask.any(axis=0))[0]
    if not len(rows) or not len(cols):
        return 0, 0, image.width, image.height
    return int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1


def profile(image: Image.Image, top: int = 8) -> list[tuple[tuple[int, int, int], float]]:
    """Colour mix quantised to 32 steps per channel, so a blended render shows a spread of hues."""
    array = np.array(image.convert("RGB")).reshape(-1, 3)
    quantised = (array // 32) * 32
    counts = Counter(map(tuple, quantised))
    total = sum(counts.values()) or 1
    return [(colour, 100.0 * count / total) for colour, count in counts.most_common(top)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Blockbench viewport capture")
    parser.add_argument("--live", required=True, help="in-game screenshot")
    parser.add_argument("--crop", default=None, help="x0,y0,x1,y1 window inside the live shot")
    parser.add_argument("--out", required=True)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()

    source = Image.open(args.source).convert("RGB")
    source = source.crop(content_box(source))
    live = Image.open(args.live).convert("RGB")
    # The live shot keeps whatever --crop says: its background is a world, not a flat colour, so an
    # automatic content box would happily crop to the grass and drop the model.
    if args.crop:
        live = live.crop(tuple(int(value) for value in args.crop.split(",")))

    def scaled(image: Image.Image) -> Image.Image:
        factor = args.height / image.height
        return image.resize((max(1, int(image.width * factor)), args.height), Image.NEAREST)

    source, live = scaled(source), scaled(live)
    gap = 16
    canvas = Image.new("RGB", (source.width + live.width + gap, args.height), (18, 18, 20))
    canvas.paste(source, (0, 0))
    canvas.paste(live, (source.width + gap, 0))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    print(f"wrote {out} {canvas.width}x{canvas.height}")

    for label, image in (("source viewport", source), ("in game", live)):
        print(f"\n{label} colour mix (32-step quantised):")
        for colour, share in profile(image):
            print(f"  {share:5.1f}%  rgb{colour}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
