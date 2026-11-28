#!/usr/bin/env python3
"""Diff offline GUI icon renders against the real in-game container slots.

The in-game sheet (tools/mcpfabric/icon_sheet.mjs + build_game_icon_sheet.py) is the
ground truth: those pixels are what Minecraft's own renderer produced for the same
proxy models. This script renders the same models with the offline renderer at the
same scale, crops both to the 16x16 icon draw area, and reports per-item metrics so
renderer changes can be judged by numbers instead of impressions.

Metrics per item (all lengths in game pixels):
  iou        alpha-mask intersection over union (silhouette agreement)
  rgb_mae    mean |delta| over the union of opaque pixels
  dx, dy     centroid offset, offline minus game, positive = offline is right/down
  w, h       bounding size of each side and their ratio
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from icon_crop import SLOT_BACKGROUND, slot_grid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from config import resolve
from item_icon_proxy import VANILLA_BLOCK_GUI
from item_icon_preview import (project_gui_translation, render_projected_icon,
                               visible_projected_measurements)
from normalize_item_icons import load_model_with_parent, resolve_model, resolve_texture
from preview_item_icons import preview_model_ids

ROOT = Path(__file__).resolve().parents[2]

# GUI item rendering applies no face shading: ItemFeatureRenderer.renderItem
# emits baked quads straight to the item render type with light coords and layer
# tint only, and materialInfo().shade() is read solely by BlockModelLighter
# (block/chunk path). "flat" is therefore the parity table; the other two exist
# so the residual can be measured against the old assumptions, not as options.
from item_icon_preview import SHADE_FLAT, SHADE_GAME

SHADING = {
    # What the game actually does; fitted by tools/deploy/diag_gui_shading.py.
    "game": SHADE_GAME,
    "flat": SHADE_FLAT,
    "vanilla": {"up": 1.0, "down": 0.5, "north": 0.8, "south": 0.8,
                "west": 0.6, "east": 0.6},
    "legacy": {"up": 1.0, "down": 0.55, "north": 0.78, "south": 0.88,
               "west": 0.68, "east": 0.92},
}


def offline_icon(root: Path, assets_root: Path, item_id: str, size: int,
                 mod_id: str, face_shade: dict[str, float],
                 return_face_ids: bool = False):
    item_path = assets_root / "items" / f"{item_id}.json"
    if not item_path.is_file():
        return None
    definition = json.loads(item_path.read_text(encoding="utf-8"))
    model_root = definition.get("model", {})
    cases = model_root.get("cases", []) if model_root.get("type") == "minecraft:select" else []
    gui_node = next((case.get("model") for case in cases if case.get("when") in ("gui", ["gui"])), None)
    if gui_node is None:
        return None
    layers = []
    for model_id in preview_model_ids(gui_node):
        model_path = resolve_model(model_id, assets_root, mod_id)
        model = load_model_with_parent(model_path, assets_root, mod_id) if model_path else None
        if not model or not model.get("elements"):
            continue
        gui_transform = model.get("display", {}).get("gui", {})
        scale = tuple(gui_transform.get("scale", VANILLA_BLOCK_GUI["scale"]))
        rotation = tuple(gui_transform.get("rotation", VANILLA_BLOCK_GUI["rotation"]))
        translation = tuple(gui_transform.get("translation", (0.0, 0.0, 0.0)))
        offset = project_gui_translation(translation, rotation)
        rendered = render_projected_icon(model, lambda ref: resolve_texture(root, ref),
                                         scale, rotation, size=size, projection_offset=offset,
                                         face_shade=face_shade,
                                         return_face_ids=return_face_ids)
        layers.append(rendered)
    if not layers:
        return None
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ids = None
    if return_face_ids:
        import numpy as np
        ids = np.zeros((size, size), dtype=np.uint16)
    for layer in layers:
        if return_face_ids:
            layer, layer_ids = layer
            if layer_ids is not None:
                present = np.asarray(layer.getchannel("A")) > 0
                ids[present] = layer_ids[present]
        icon = Image.alpha_composite(icon, layer)
    return (icon, ids) if return_face_ids else icon


def silhouette(pixels: np.ndarray) -> np.ndarray:
    """Item pixels inside a slot: anything that is not the flat slot background.

    The slot background is an opaque flat #8B8B8B, so alpha cannot separate the item
    from it - both are opaque. Comparing against the background colour is the only
    reliable silhouette signal in a real screenshot.
    """
    diff = np.abs(pixels[:, :, :3].astype(np.int16)
                  - np.array(SLOT_BACKGROUND, dtype=np.int16)).sum(axis=2)
    return diff > 6


def mask_centroid(mask: np.ndarray) -> tuple[float, float]:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return (0.0, 0.0)
    return (float(xs.mean()), float(ys.mean()))


def bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return (0, 0, 0, 0)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def compare(game: np.ndarray, offline: np.ndarray, scale: float) -> dict:
    """Compare two RGBA arrays of identical size; lengths are divided back to game px."""
    g_alpha = silhouette(game)
    o_alpha = silhouette(offline)
    union = g_alpha | o_alpha
    inter = g_alpha & o_alpha
    iou = float(inter.sum()) / float(union.sum()) if union.any() else 1.0
    rgb_mae = 0.0
    if union.any():
        diff = np.abs(game[:, :, :3].astype(np.int16) - offline[:, :, :3].astype(np.int16)).sum(axis=2)
        rgb_mae = float(diff[union].mean()) / 3.0
    gcx, gcy = mask_centroid(g_alpha)
    ocx, ocy = mask_centroid(o_alpha)
    gb, ob = bbox(g_alpha), bbox(o_alpha)
    return {
        "iou": round(iou, 4),
        "rgb_mae": round(rgb_mae, 2),
        "dx": round((ocx - gcx) / scale, 3),
        "dy": round((ocy - gcy) / scale, 3),
        "game_w": round((gb[2] - gb[0]) / scale, 2),
        "game_h": round((gb[3] - gb[1]) / scale, 2),
        "off_w": round((ob[2] - ob[0]) / scale, 2),
        "off_h": round((ob[3] - ob[1]) / scale, 2),
        "coverage_game": round(float(g_alpha.mean()), 4),
        "coverage_off": round(float(o_alpha.mean()), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="build/shots/game_icon_sheet_plan.json")
    parser.add_argument("--report", default="build/shots/icon_diff.json")
    parser.add_argument("--sheet", default="build/shots/icon_diff.png")
    parser.add_argument("--items", default="", help="comma-separated ids; default all")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--shade", choices=sorted(SHADING), default="game")
    parser.add_argument("--groups-per-row", type=int, default=4)
    args = parser.parse_args()

    face_shade = SHADING[args.shade]

    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = ROOT / plan_path
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    wanted = {part.strip() for part in args.items.split(",") if part.strip()}

    root = ROOT
    meta = resolve({"root": str(root)})
    mod_id = meta.get("mod_id")
    assets_root = root / "src/main/resources/assets" / mod_id

    entries: list[dict] = []
    panels: list[tuple[str, np.ndarray, np.ndarray]] = []
    for round_entry in plan["rounds"]:
        image_path = Path(round_entry["image"])
        if not image_path.is_absolute():
            image_path = ROOT / image_path
        items = round_entry["items"]
        if not image_path.is_file():
            continue
        with Image.open(image_path) as opened:
            image = opened.convert("RGBA")
        pixels = np.asarray(image)
        grid = slot_grid(pixels)
        if grid is None:
            print(f"{image_path.name}: no container slot grid")
            continue
        left, top, pitch, scale = grid
        size = 16 * scale
        for slot, item in enumerate(items):
            if wanted and item not in wanted:
                continue
            if not wanted and args.limit and len(entries) >= args.limit:
                break
            column, row = slot % 9, slot // 9
            draw_left = left + column * pitch
            draw_top = top + row * pitch
            game = np.asarray(image.crop((draw_left, draw_top, draw_left + size, draw_top + size)))
            icon = offline_icon(root, assets_root, item, size, mod_id, face_shade)
            if icon is None:
                continue
            # Composite over the same flat slot background the game draws, so the
            # RGB numbers compare what a player sees rather than transparent black.
            canvas = Image.new("RGBA", icon.size, SLOT_BACKGROUND + (255,))
            off = np.asarray(Image.alpha_composite(canvas, icon))
            metrics = compare(game, off, float(scale))
            metrics["item"] = item
            entries.append(metrics)
            panels.append((item, game, off))
        if args.limit and len(entries) >= args.limit:
            break

    if not entries:
        print("no items compared")
        return 1

    entries.sort(key=lambda e: (e["iou"], -e["rgb_mae"]))
    ious = [e["iou"] for e in entries]
    maes = [e["rgb_mae"] for e in entries]
    print(f"shade={args.shade}  items={len(entries)}")
    print(f"  iou  min={min(ious):.3f} mean={sum(ious)/len(ious):.3f}")
    print(f"  rgb  min={min(maes):.1f} mean={sum(maes)/len(maes):.1f} max={max(maes):.1f}")
    worst = entries[:8]
    print("  worst by silhouette:")
    for e in worst:
        print(f"    {e['item']:<26} iou={e['iou']:.3f} rgb={e['rgb_mae']:.1f} "
              f"d=({e['dx']:+.2f},{e['dy']:+.2f}) size {e['game_w']:.1f}x{e['game_h']:.1f}"
              f" vs {e['off_w']:.1f}x{e['off_h']:.1f}")

    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"shade": args.shade, "items": entries},
                                      ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    sheet_path = Path(args.sheet)
    if not sheet_path.is_absolute():
        sheet_path = ROOT / sheet_path
    if panels:
        size = panels[0][1].shape[0]
        gap, label = 4, 18
        per_row = max(1, args.groups_per_row)
        group_w = 3 * size + 2 * gap
        rows = (len(panels) + per_row - 1) // per_row
        sheet = Image.new("RGBA", (per_row * (group_w + gap), rows * (size + label)), (24, 24, 28, 255))
        draw = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.truetype("arial.ttf", 10)
        except OSError:
            font = ImageFont.load_default()
        for index, (item, game, off) in enumerate(panels):
            gx = (index % per_row) * (group_w + gap)
            gy = (index // per_row) * (size + label)
            ov = np.zeros_like(game)
            ov[:, :, 0] = 255  # game-only pixels red
            ov[:, :, 1] = 255  # offline-only pixels green
            g_a, o_a = game[:, :, 3] > 127, off[:, :, 3] > 127
            ov[g_a & ~o_a] = (255, 60, 60, 255)
            ov[o_a & ~g_a] = (60, 255, 60, 255)
            ov[g_a & o_a] = (40, 40, 40, 255)
            draw.rectangle((gx, gy, gx + 3 * size + 2 * gap - 1, gy + size - 1), fill=(90, 90, 95, 255))
            sheet.alpha_composite(Image.fromarray(game), (gx, gy))
            sheet.alpha_composite(Image.fromarray(off), (gx + size + gap, gy))
            sheet.alpha_composite(Image.fromarray(ov), (gx + 2 * (size + gap), gy))
            threshold = next((e for e in entries if e["item"] == item), None)
            label_text = item[:22]
            if threshold:
                label_text += f"  iou {threshold['iou']:.2f} rgb {threshold['rgb_mae']:.0f}"
            draw.text((gx + 1, gy + size + 3), label_text, fill=(225, 225, 230, 255), font=font)
        sheet_path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(sheet_path)
        print(f"sheet -> {sheet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
