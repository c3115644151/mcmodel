#!/usr/bin/env python3
"""Fit Minecraft's effective GUI face shading from a real in-game capture.

The offline renderer paints every face with a shade factor. Earlier tables were
copied from FaceBakery's directional constants (up 1.0 / down 0.5 / sides 0.8 /
0.6) and then hand-tuned; both were guesses. This script measures instead: it
renders each icon flat (shade 1.0), tags every pixel with the face direction that
owns it, and divides the game capture by the flat render. Where the difference is
a pure multiply, that ratio *is* the factor the game applied to that face.

Writes a per-face table (median and spread over all items) plus the per-item
breakdown for the worst offenders, so a new table can be justified by data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compare_game_icons import ROOT, offline_icon, SHADING
from icon_crop import SLOT_BACKGROUND, slot_grid

FACE_NAMES = {1: "down", 2: "up", 3: "north", 4: "south", 5: "west", 6: "east"}


def slots_from_plan(plan_path: Path, wanted: set[str]):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    for round_entry in plan["rounds"]:
        image_path = Path(round_entry["image"])
        if not image_path.is_absolute():
            image_path = ROOT / image_path
        if not image_path.is_file():
            continue
        with Image.open(image_path) as opened:
            image = opened.convert("RGBA")
        pixels = np.asarray(image)
        grid = slot_grid(pixels)
        if grid is None:
            continue
        left, top, pitch, scale = grid
        size = 16 * scale
        for slot, item in enumerate(round_entry["items"]):
            if wanted and item not in wanted:
                continue
            column, row = slot % 9, slot // 9
            draw_left = left + column * pitch
            draw_top = top + row * pitch
            crop = image.crop((draw_left, draw_top, draw_left + size, draw_top + size))
            yield item, np.asarray(crop), scale


def ratio_samples(entry, icon_flat, ids, scale: int, min_level: float):
    """Per-face multiplicative ratios for one item, or None when unusable."""
    canvas = Image.new("RGBA", icon_flat.size, SLOT_BACKGROUND + (255,))
    flat = np.asarray(Image.alpha_composite(canvas, icon_flat))[:, :, :3].astype(np.float64)
    game = entry[:, :, :3].astype(np.float64)
    if ids is None or ids.shape[0] != game.shape[0]:
        return None
    usable = (ids > 0) & (flat.max(axis=2) >= min_level)
    if not usable.any():
        return None
    ratio = game / np.maximum(flat, 1.0)
    # 每个面取通道中位数，避免单像素采样噪声主导
    out: dict[int, tuple[float, int]] = {}
    for face_id in np.unique(ids[usable]):
        mask = usable & (ids == face_id)
        if mask.sum() < max(4, 2 * scale * scale):
            continue
        out[int(face_id)] = (float(np.median(ratio[mask])), int(mask.sum()))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="build/shots/game_icon_sheet2_plan.json")
    parser.add_argument("--items", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--report", default="build/shots/shade_fit.json")
    parser.add_argument("--min-level", type=float, default=24.0,
                        help="ignore flat-render pixels darker than this (ratio noise)")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = ROOT / plan_path
    wanted = {part.strip() for part in args.items.split(",") if part.strip()}

    meta = resolve_meta()
    mod_id = meta["mod_id"]
    assets_root = ROOT / "src/main/resources/assets" / mod_id

    per_face: dict[int, list[float]] = {}
    per_item: list[dict] = []
    for item, game, scale in slots_from_plan(plan_path, wanted):
        rendered = offline_icon(ROOT, assets_root, item, 16 * scale, mod_id,
                               SHADING["flat"], return_face_ids=True)
        if rendered is None:
            continue
        icon_flat, ids = rendered
        samples = ratio_samples(game, icon_flat, ids, scale, args.min_level)
        if not samples:
            continue
        row = {"item": item, "faces": {}, "elements": {}}
        for face_id, (value, count) in samples.items():
            direction = face_id % 8
            element = face_id // 8
            per_face.setdefault(direction, []).append(value)
            row["faces"][FACE_NAMES.get(direction, str(direction))] = {
                "ratio": round(value, 3), "pixels": count}
            row["elements"].setdefault(str(element), {})[FACE_NAMES.get(direction, str(direction))] = round(value, 3)
        # 一个图标整体是否只是"整片偏移"：看各面比值的离散度
        values = [value for value, _ in samples.values()]
        row["spread"] = round(max(values) - min(values), 3) if len(values) > 1 else 0.0
        per_item.append(row)
        if args.limit and len(per_item) >= args.limit:
            break

    if not per_item:
        print("no items measured")
        return 1

    table = {}
    print(f"items={len(per_item)}")
    print(f"{'face':<6} {'median':>7} {'p10':>7} {'p90':>7}  samples")
    for face_id in sorted(per_face):
        values = np.array(per_face[face_id])
        median = float(np.median(values))
        table[FACE_NAMES.get(face_id, str(face_id))] = {
            "median": round(median, 4),
            "p10": round(float(np.percentile(values, 10)), 4),
            "p90": round(float(np.percentile(values, 90)), 4),
            "samples": int(values.size),
        }
        print(f"{FACE_NAMES.get(face_id, str(face_id)):<6} {median:>7.3f} "
              f"{np.percentile(values, 10):>7.3f} {np.percentile(values, 90):>7.3f}  {values.size}")

    consistent = sorted(per_item, key=lambda r: -r["spread"])[:8]
    print("worst per-item spread (largest face-to-face disagreement):")
    for row in consistent:
        faces = ", ".join(f"{name}={data['ratio']:.2f}"
                          for name, data in sorted(row["faces"].items()))
        print(f"  {row['item']:<24} spread={row['spread']:.2f}  {faces}")

    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"table": table, "items": per_item},
                                      ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"report -> {report_path}")
    return 0


def resolve_meta():
    from normalize_item_icons import resolve
    return resolve({"root": str(ROOT)})


if __name__ == "__main__":
    raise SystemExit(main())
