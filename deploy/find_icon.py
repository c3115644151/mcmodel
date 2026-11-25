"""Locate the lamp icon in a screenshot, crop it, and print a colour census.

A fixed crop box would have to be guessed per screenshot, and a plain "warm pixel" search also
matches the wooden UI and the stone floor, so the locator keeps only the largest connected warm
blob: the icon is one solid piece at slot scale, background noise is not.
"""
import argparse
import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

# Amber paper and the cream bulb behind it. Both are saturated warm; the slot frame, the wooden
# inventory background and the stone floor are not.
AMBER = (150, 90, 40)
CREAM = (215, 195, 130)


def warm_mask(pixels):
    red = pixels[:, :, 0].astype(np.int16)
    green = pixels[:, :, 1].astype(np.int16)
    blue = pixels[:, :, 2].astype(np.int16)
    amber = (red > AMBER[0]) & (green > AMBER[1]) & (blue < 110) & (red - blue > 70)
    cream = (red > CREAM[0]) & (green > CREAM[1]) & (blue > 100) & (red - blue > 60)
    return amber | cream


def largest_blob(mask, cap=40000, region=None, min_fill=0.2):
    height, width = mask.shape
    if region is not None:
        x0, y0, x1, y1 = region
        inside = np.zeros_like(mask, dtype=bool)
        inside[max(0, y0):min(height, y1), max(0, x0):min(width, x1)] = True
        mask = mask & inside
    seen = np.zeros_like(mask, dtype=bool)
    best = None
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or seen[y, x]:
                continue
            queue = deque([(y, x)])
            seen[y, x] = True
            count = 0
            low = [y, x]
            high = [y, x]
            while queue:
                cy, cx = queue.popleft()
                count += 1
                low[0], low[1] = min(low[0], cy), min(low[1], cx)
                high[0], high[1] = max(high[0], cy), max(high[1], cx)
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        queue.append((ny, nx))
            if count > cap:
                continue
            box_width = high[1] - low[1] + 1
            box_height = high[0] - low[0] + 1
            if count / float(box_width * box_height) < min_fill:
                continue
            if best is None or count > best[0]:
                best = (count, low, high)
    return best


def classify(pixel):
    red, green, blue = pixel[:3]
    if red > 150 and red - blue > 70:
        return "amber" if green < 200 else "cream"
    if abs(red - green) < 26 and abs(green - blue) < 26:
        return "grey"
    return "other"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--pad", type=int, default=4)
    parser.add_argument("--zoom", type=int, default=6)
    parser.add_argument("--min", type=int, default=200, help="smallest acceptable icon in pixels")
    parser.add_argument("--region", default=None,
                        help="x0,y0,x1,y1 search window; the caller knows which screen it opened")
    parser.add_argument("--fill", type=float, default=0.2, help="lowest accepted blob fill ratio")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    source = Path(args.image)
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    pixels = np.asarray(image)
    region = tuple(int(value) for value in args.region.split(",")) if args.region else None
    blob = largest_blob(warm_mask(pixels), region=region, min_fill=args.fill)
    if blob is None or blob[0] < args.min:
        print(json.dumps({"image": str(source), "found": 0, "best": None if blob is None else blob[0]}))
        return 1
    count, low, high = blob
    left = max(0, low[1] - args.pad)
    top = max(0, low[0] - args.pad)
    right = min(image.width, high[1] + args.pad + 1)
    bottom = min(image.height, high[0] + args.pad + 1)
    crop = image.crop((left, top, right, bottom))
    crop.resize((crop.width * args.zoom, crop.height * args.zoom), Image.NEAREST).save(args.out)
    counts = {}
    for pixel in crop.getdata():
        name = classify(pixel)
        counts[name] = counts.get(name, 0) + 1
    total = float(crop.width * crop.height)
    print(json.dumps({
        "image": str(source),
        "box": [left, top, right, bottom],
        "icon_pixels": count,
        "size": [crop.width, crop.height],
        "census": {name: round(100.0 * value / total, 1) for name, value in sorted(counts.items())},
        "out": args.out,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
