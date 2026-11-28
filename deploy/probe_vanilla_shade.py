#!/usr/bin/env python3
"""Compare vanilla GUI item shading with the offline renderer.

The mod's own icons measured north/south faces at ~0.40x and east/west at ~0.60x
of their flat texture colour, which looks like per-face shading. The 26.1 item
render path (ItemFeatureRenderer) applies no lighter at all, so the only way to
tell whether that factor is the engine or an artefact of our own proxies is to
photograph a vanilla item and run the same fit on it.

Uses a capture produced by tools/mcpfabric/icon_sheet.mjs with ids like
"minecraft:stone" (uniform texture on all six faces, so every visible face is a
direct sample of the same sprite).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compare_game_icons import ROOT
from icon_crop import slot_grid
from item_icon_preview import render_projected_icon
from normalize_item_icons import load_model_with_parent

VANILLA_ASSETS = ROOT / "build/neoform/neoFormJoined26.1.2-1/steps/transformSource/transformed/assets"
FACE_NAMES = {1: "down", 2: "up", 3: "north", 4: "south", 5: "west", 6: "east"}


def vanilla_model(model_id: str):
    path = VANILLA_ASSETS / "minecraft/models" / f"{model_id}.json"
    if not path.is_file():
        raise SystemExit(f"missing vanilla model {path}")
    return load_model_with_parent(path, VANILLA_ASSETS, "minecraft")


def vanilla_texture(ref: str):
    _, _, path = ref.partition(":")
    candidate = VANILLA_ASSETS / "minecraft/textures" / f"{path}.png"
    return candidate if candidate.is_file() else None


def find_slot(plan_path: Path, item: str):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    for round_entry in plan["rounds"]:
        image_path = Path(round_entry["image"])
        if not image_path.is_absolute():
            image_path = ROOT / image_path
        if not image_path.is_file():
            continue
        with Image.open(image_path) as opened:
            image = opened.convert("RGBA")
        grid = slot_grid(np.asarray(image))
        if grid is None:
            continue
        left, top, pitch, scale = grid
        size = 16 * scale
        for slot, entry in enumerate(round_entry["items"]):
            if entry != item:
                continue
            column, row = slot % 9, slot // 9
            draw_left, draw_top = left + column * pitch, top + row * pitch
            return np.asarray(image.crop((draw_left, draw_top, draw_left + size, draw_top + size))), scale
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--item", default="minecraft:stone")
    parser.add_argument("--model", default="block/stone")
    parser.add_argument("--report", default="build/shots/vanilla_shade.json")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = ROOT / plan_path
    game, scale = find_slot(plan_path, args.item)
    if game is None:
        raise SystemExit(f"{args.item} not present in {plan_path}")

    model = vanilla_model(args.model)
    size = 16 * scale
    icon, ids = render_projected_icon(model, vanilla_texture, size=size,
                                     return_face_ids=True)
    flat = np.asarray(icon)[:, :, :3].astype(np.float64)
    game_rgb = game[:, :, :3].astype(np.float64)
    # ids 里存的是 element*8 + 方向；香草方块是单个 cube，方向用 id % 8 还原。
    direction = ids % 8

    print(f"{args.item}: scale={scale} size={size}")
    rows = {}
    for dir_id in sorted({int(v) for v in np.unique(direction) if v}):
        mask = (direction == dir_id) & (flat.max(axis=2) > 8)
        if mask.sum() < 4:
            continue
        ratio = float(np.median(game_rgb[mask] / np.maximum(flat[mask], 1.0)))
        rows[FACE_NAMES.get(dir_id, str(dir_id))] = {"ratio": round(ratio, 3),
                                                     "pixels": int(mask.sum())}
        print(f"  {FACE_NAMES.get(dir_id, dir_id):<6} ratio={ratio:.3f}  pixels={mask.sum()}")
    if not rows:
        print("  no measurable faces (offline render empty?)")
        return 1
    ratios = [row["ratio"] for row in rows.values()]
    print(f"  spread max-min = {max(ratios) - min(ratios):.3f}")

    report = Path(args.report)
    if not report.is_absolute():
        report = ROOT / report
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"item": args.item, "model": args.model, "faces": rows},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"report -> {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
