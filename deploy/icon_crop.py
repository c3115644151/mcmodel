"""Crop one item icon out of a container screenshot and print a colour census.

Guessing a crop box, or hunting for warm pixels, both fail on a real screen: JEI's item list, the
wooden UI and the player's own copy of the icon are all the same colour. A container screen is
laid out from a flat panel, so the panel is found first - the largest block of vanilla's container
grey - and the first slot is then a fixed offset inside it. That offset is the same for every
container screen, and the GUI scale falls out of the panel's own size.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

PANEL_GREY = (198, 198, 198)
# The vanilla container texture is 176x166 at scale 1 and its first slot starts at (8, 18).
PANEL_SIZE = (176, 166)
SLOT_INSET = (8, 18)
SLOT_SIZE = 18


def panel_origin(pixels, tolerance=3):
    """Bounding box of the flat container panel, which anchors every slot on the screen."""
    distance = np.abs(pixels[:, :, :3].astype(np.int16) - np.array(PANEL_GREY, dtype=np.int16)).sum(axis=2)
    mask = distance <= tolerance * 3
    # The panel is one large rectangle, so its rows and columns are dense: take the extremes of the
    # dense rows instead of the extremes of every stray pixel of similar grey.
    rows = np.where(mask.sum(axis=1) > 80)[0]
    cols = np.where(mask.sum(axis=0) > 60)[0]
    if rows.size == 0 or cols.size == 0:
        return None
    return int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1


def classify(pixel):
    red, green, blue = int(pixel[0]), int(pixel[1]), int(pixel[2])
    if red > 150 and red - blue > 70:
        return "amber" if green < 200 else "cream"
    if abs(red - green) < 26 and abs(green - blue) < 26:
        return "grey"
    return "other"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--slot", type=int, default=0, help="container slot index to crop")
    parser.add_argument("--zoom", type=int, default=6)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    source = Path(args.image)
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    pixels = np.asarray(image)
    panel = panel_origin(pixels)
    if panel is None:
        print(json.dumps({"image": str(source), "found": 0, "reason": "no container panel"}))
        return 1
    left, top, right, bottom = panel
    scale = max(1, round((right - left) / float(PANEL_SIZE[0])))
    column = args.slot % 9
    row = args.slot // 9
    slot_left = left + (SLOT_INSET[0] + column * SLOT_SIZE) * scale
    slot_top = top + (SLOT_INSET[1] + row * SLOT_SIZE) * scale
    crop = image.crop((slot_left, slot_top, slot_left + SLOT_SIZE * scale, slot_top + SLOT_SIZE * scale))
    crop.resize((crop.width * args.zoom, crop.height * args.zoom), Image.NEAREST).save(args.out)
    counts = {}
    for pixel in np.asarray(crop).reshape(-1, 4):
        name = classify(pixel)
        counts[name] = counts.get(name, 0) + 1
    total = float(crop.width * crop.height)
    print(json.dumps({
        "image": str(source),
        "panel": panel,
        "gui_scale": scale,
        "slot_box": [slot_left, slot_top, slot_left + SLOT_SIZE * scale, slot_top + SLOT_SIZE * scale],
        "census": {name: round(100.0 * value / total, 1) for name, value in sorted(counts.items())},
        "out": args.out,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
