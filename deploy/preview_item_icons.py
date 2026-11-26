#!/usr/bin/env python3
"""Render a contact sheet of generated GUI-only one-block item proxies.

The preview uses actual model elements, face UVs, and texture alpha. It applies
Minecraft's vanilla block GUI transform to the projection, but omits lighting and
the game's rasterization pipeline; it is an asset QA report, not a screenshot.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 原版 GUI 槽位是 16x16 像素。预览把每个图标渲染到 ICON_CANVAS 的画布上，
# 比例固定 ZOOM 倍，仅为便于观看；格子背景必须正好等于这个画布，否则格子
# 会比图标代表的真实 slot 大一圈，看不出图标在真实格子里的占比。
SLOT_PIXELS = 16
ICON_ZOOM = 4
ICON_CANVAS = SLOT_PIXELS * ICON_ZOOM   # 64px 画布 == 一个原版 16px slot
CELL_PAD = 4                            # 格子外的留白，不属于格子本身

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import resolve
from item_icon_proxy import VANILLA_BLOCK_GUI, collect_model_ids
from item_icon_preview import (project_gui_translation, render_projected_icon,
                               visible_projected_measurements)
from normalize_item_icons import load_model_with_parent, resolve_model, resolve_texture


def creative_tab_item_ids(root: Path) -> set[str]:
    """Read the project's explicit creative-tab output list, excluding renderer internals."""
    registry = root / "src/main/java/com/pastoralhome/registry/ModCreativeTabs.java"
    if not registry.is_file():
        return set()
    source = registry.read_text(encoding="utf-8")
    fields = re.findall(r"output\.accept\s*\(\s*ModItems\.([A-Z0-9_]+)\.get\(\)\s*\)", source)
    return {field.lower() for field in fields}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path("build/item_icon_preview.png"))
    parser.add_argument("--report", type=Path, default=Path("build/item_icon_preview.json"))
    parser.add_argument("--columns", type=int, default=8)
    parser.add_argument("--cell", type=int, default=ICON_CANVAS + 2 * CELL_PAD,
                        help="cell pitch in preview pixels; the drawn slot box is always "
                             f"exactly one vanilla slot ({ICON_CANVAS}px = {SLOT_PIXELS}px x {ICON_ZOOM})")
    parser.add_argument("--items", default="", help="comma-separated item ids; default is all")
    parser.add_argument("--vanilla-reference", action="store_true",
                        help="prepend a full-cube baseline rendered with the same vanilla GUI transform")
    parser.add_argument("--include-hidden", action="store_true",
                        help="include registered renderer-only items not listed in the creative tab")
    args = parser.parse_args()

    root = (args.root or Path.cwd()).resolve()
    mod_id = resolve({"root": str(root)}).get("mod_id")
    if not mod_id:
        parser.error(f"could not detect mod id under {root}")
    assets_root = root / "src/main/resources/assets" / mod_id
    items_dir = assets_root / "items"
    requested = {part.strip() for part in args.items.split(",") if part.strip()}
    creative_items = creative_tab_item_ids(root)
    include_everything = args.include_hidden or bool(requested) or not creative_items
    omitted_hidden = 0
    entries = []

    for item_path in sorted(items_dir.glob("*.json")):
        if requested and item_path.stem not in requested:
            continue
        if not include_everything and item_path.stem not in creative_items:
            omitted_hidden += 1
            continue
        definition = json.loads(item_path.read_text(encoding="utf-8"))
        model_root = definition.get("model", {})
        cases = model_root.get("cases", []) if model_root.get("type") == "minecraft:select" else []
        gui_node = next((case.get("model") for case in cases if case.get("when") in ("gui", ["gui"])), None)
        if gui_node is None:
            continue
        model_ids = collect_model_ids(gui_node)
        icon_layers = []
        projected = []
        for model_index, model_id in enumerate(model_ids):
            model_path = resolve_model(model_id, assets_root, mod_id)
            model = load_model_with_parent(model_path, assets_root, mod_id) if model_path else None
            if not model or not model.get("elements"):
                continue
            measured = visible_projected_measurements(
                model, lambda ref: resolve_texture(root, ref), pixels_per_unit=8,
            )
            if not measured:
                continue
            gui_transform = model.get("display", {}).get("gui", {})
            gui_scale = tuple(gui_transform.get("scale", VANILLA_BLOCK_GUI["scale"]))
            gui_rotation = tuple(model.get("display", {}).get("gui", {}).get("rotation", VANILLA_BLOCK_GUI["rotation"]))
            gui_translation = tuple(gui_transform.get("translation", (0.0, 0.0, 0.0)))
            screen_translation = project_gui_translation(gui_translation, gui_rotation)
            bounds = measured["bounds"]
            bounds = (bounds[0] * gui_scale[0] + screen_translation[0],
                      bounds[1] * gui_scale[1] + screen_translation[1],
                      bounds[2] * gui_scale[0] + screen_translation[0],
                      bounds[3] * gui_scale[1] + screen_translation[1])
            rendered = render_projected_icon(model, lambda ref: resolve_texture(root, ref),
                                             gui_scale, gui_rotation, size=ICON_CANVAS,
                                             projection_offset=screen_translation)
            icon_layers.append(rendered)
            projected.append(bounds)

        if not icon_layers:
            continue
        icon = Image.new("RGBA", (ICON_CANVAS, ICON_CANVAS), (0, 0, 0, 0))
        for layer in icon_layers:
            icon = Image.alpha_composite(icon, layer)
        bounds = (min(b[0] for b in projected), min(b[1] for b in projected),
                  max(b[2] for b in projected), max(b[3] for b in projected))
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        center_offset = ((bounds[0] + bounds[2]) * 0.5,
                         (bounds[1] + bounds[3]) * 0.5)
        ink = sum(1 for value in icon.getchannel("A").get_flattened_data() if value) / float(ICON_CANVAS * ICON_CANVAS)
        entries.append({
            "item": item_path.stem,
            "gui_models": model_ids,
            "projected_gui_size": [round(width, 3), round(height, 3)],
            "projected_gui_center_offset": [round(center_offset[0], 3), round(center_offset[1], 3)],
            "alpha_coverage": round(ink, 4),
            "bounds_within_16px_cell": width <= 16.0 and height <= 16.0,
            "centered_within_half_pixel": max(abs(value) for value in center_offset) <= 0.5,
            "icon": icon,
        })

    if args.vanilla_reference:
        faces = {name: {"uv": [0, 0, 16, 16], "texture": "#reference"}
                 for name in ("north", "east", "south", "west", "up", "down")}
        reference_model = {
            "textures": {"reference": "minecraft:block/reference"},
            "elements": [{"from": [0, 0, 0], "to": [16, 16, 16], "faces": faces}],
            "display": {"gui": VANILLA_BLOCK_GUI},
        }
        measured = visible_projected_measurements(reference_model, lambda _ref: None)
        bounds = measured["bounds"]
        scale = VANILLA_BLOCK_GUI["scale"][0]
        icon = render_projected_icon(reference_model, lambda _ref: None,
                                     tuple(VANILLA_BLOCK_GUI["scale"]),
                                     tuple(VANILLA_BLOCK_GUI["rotation"]), size=ICON_CANVAS)
        reference = {
            "item": "vanilla_full_block_reference",
            "gui_models": ["minecraft:block/cube_all"],
            "projected_gui_size": [round((bounds[2] - bounds[0]) * scale, 3),
                                   round((bounds[3] - bounds[1]) * scale, 3)],
            "projected_gui_center_offset": [0.0, 0.0],
            "alpha_coverage": round(sum(1 for value in icon.getchannel("A").getdata() if value)
                                     / float(ICON_CANVAS * ICON_CANVAS), 4),
            "bounds_within_16px_cell": True,
            "centered_within_half_pixel": True,
            "icon": icon,
        }
        entries.insert(0, reference)

    if not entries:
        parser.error("no item definitions with generated GUI proxy cases found; run normalize_item_icons.py --apply first")
    columns = max(1, args.columns)
    cell = max(args.cell, ICON_CANVAS + 2 * CELL_PAD)
    label_height = 20
    rows = (len(entries) + columns - 1) // columns
    sheet = Image.new("RGBA", (columns * cell, rows * (cell + label_height)), (58, 58, 58, 255))
    draw, font = ImageDraw.Draw(sheet), ImageFont.load_default()
    for index, entry in enumerate(entries):
        x, y = (index % columns) * cell, (index // columns) * (cell + label_height)
        # 格子背景 = 图标画布 = 一个原版 16px slot，居中放在 cell 内。
        # 不把背景画成整个 cell，否则格子比图标代表的真实 slot 大一圈。
        sx = x + (cell - ICON_CANVAS) // 2
        sy = y + (cell - ICON_CANVAS) // 2
        # Pillow's rectangle is inclusive: sx+ICON_CANVAS would draw ICON_CANVAS+1 px.
        # Subtract 1 on the far edge so the box is exactly one vanilla slot.
        draw.rectangle((sx, sy, sx + ICON_CANVAS - 1, sy + ICON_CANVAS - 1),
                       fill=(133, 133, 133, 255), outline=(225, 225, 225, 255))
        sprite = entry.pop("icon")
        sheet.alpha_composite(sprite, (sx, sy))
        draw.text((x + 3, y + cell + 2), entry["item"][:14], fill=(255, 255, 255, 255), font=font)
        draw.text((x + 3, y + cell + 11), f'{entry["projected_gui_size"][0]:.1f}x{entry["projected_gui_size"][1]:.1f} {entry["alpha_coverage"]:.0%}',
                  fill=(210, 210, 210, 255), font=font)

    output = args.output if args.output.is_absolute() else root / args.output
    report_path = args.report if args.report.is_absolute() else root / args.report
    output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    report_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Rendered {len(entries)} generated GUI proxy previews to {output}")
    print(f"Wrote projected size report to {report_path}")
    if omitted_hidden:
        print(f"Omitted {omitted_hidden} registered renderer-only items not listed in the creative tab.")
    print("This offline preview does not emulate lighting, depth rasterization, or atlas sampling.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
