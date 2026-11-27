#!/usr/bin/env python3
"""Assemble real in-game container screenshots into one labelled GUI icon sheet.

Reads the plan written by tools/mcpfabric/icon_sheet.mjs (round image -> item order),
finds the container panel in each screenshot (same anchor icon_crop.py uses), crops
every slot, and lays them out 9 per row so each chest round forms three full rows.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from icon_crop import SLOT_SIZE, slot_grid

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="build/shots/game_icon_sheet_plan.json")
    parser.add_argument("--out", default="build/shots/game_icon_sheet.png")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = ROOT / plan_path
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    zoom = int(plan.get("zoom", 5))

    cells: list[tuple[str, Image.Image | None]] = []
    for round_entry in plan["rounds"]:
        image_path = Path(round_entry["image"])
        if not image_path.is_absolute():
            image_path = ROOT / image_path
        items = round_entry["items"]
        if not image_path.is_file():
            cells.extend((item, None) for item in items)
            continue
        with Image.open(image_path) as opened:
            image = opened.convert("RGBA")
        pixels = np.asarray(image)
        grid = slot_grid(pixels)
        if grid is None:
            print(f"{image_path.name}: no container slot grid")
            cells.extend((item, None) for item in items)
            continue
        # x0/y0 is the slot(0,0) item draw area; the shot has no slot frame in it.
        left, top, pitch, scale = grid
        for slot, item in enumerate(items):
            column, row = slot % 9, slot // 9
            slot_left = left + column * pitch
            slot_top = top + row * pitch
            crop = image.crop((slot_left, slot_top,
                               slot_left + 16 * scale, slot_top + 16 * scale))
            cells.append((item, crop))

    cell = SLOT_SIZE * zoom  # 18px slot frame: 16px draw area + 1px border either side
    label = 20
    columns = 9
    rows = (len(cells) + columns - 1) // columns
    sheet = Image.new("RGBA", (columns * cell, rows * (cell + label)), (30, 30, 34, 255))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 9)
    except OSError:
        font = ImageFont.load_default()
    missing = 0
    for index, (item, crop) in enumerate(cells):
        x, y = (index % columns) * cell, (index // columns) * (cell + label)
        draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(138, 138, 143, 255))
        if crop is None:
            missing += 1
            draw.line((x, y, x + cell - 1, y + cell - 1), fill=(180, 60, 60, 255))
        else:
            sheet.alpha_composite(crop.resize((cell, cell), Image.NEAREST), (x, y))
        draw.text((x + 1, y + cell + 3), item[:16], fill=(230, 230, 235, 255), font=font)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    print(f"{len(cells)} icons ({missing} missing) -> {out_path}  cell={cell}px scale={zoom}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
