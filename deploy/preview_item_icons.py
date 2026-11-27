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

# Minecraft 的 GUI 槽位(slot)是 18x18 游戏像素，中间的 16x16 才是图标绘制区，
# 四周各 1px 是格子边框。预览以 ICON_ZOOM 倍放大：图标绘制在 ICON_CANVAS(64px)
# 里，但玩家眼里的"格子"是含边框的 18px(SLOT_FRAME_CANVAS=72px)。格子框必须按
# 18px 画、图标绘制区居中其中，才能还原游戏里图标相对格子的真实占比。
SLOT_PIXELS = 16                        # 图标绘制区(游戏像素)
SLOT_FRAME_PIXELS = 18                  # 完整格子含边框(游戏像素), MC 的 SLOT_SIZE
ICON_ZOOM = 4
ICON_CANVAS = SLOT_PIXELS * ICON_ZOOM          # 64px = 16px 图标绘制区
SLOT_FRAME_CANVAS = SLOT_FRAME_PIXELS * ICON_ZOOM  # 72px = 18px 完整格子(含边框)
ICON_INSET = (SLOT_FRAME_CANVAS - ICON_CANVAS) // 2  # 4px = 1px 边框 ×4
CELL_PAD = 4                            # 格子外的留白，不属于格子本身

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import resolve
from item_icon_proxy import VANILLA_BLOCK_GUI, collect_model_ids
from item_icon_preview import (project_gui_translation, render_projected_icon,
                               visible_projected_measurements)
from item_ids import official_items
from normalize_item_icons import load_model_with_parent, resolve_model, resolve_texture


def preview_model_ids(gui_node: dict) -> list[str]:
    """Model ids to draw for a GUI icon.

    A minecraft:component select (e.g. water_barrel's stored_amount) picks ONE
    mutually exclusive state at render time. Drawing every case's ids stacked
    paints all four water levels at once, covering the barrel in a blue slab.
    With no live item component in an offline preview, the fallback is the
    honest neutral state (an empty barrel).
    """
    if isinstance(gui_node, dict) and gui_node.get("type") in ("minecraft:select", "minecraft:condition"):
        fallback = gui_node.get("fallback")
        if fallback is not None:
            return collect_model_ids(fallback)
    return collect_model_ids(gui_node)


def registered_item_ids(root: Path) -> set[str]:
    """Item ids the creative tab offers - the honest inventory-item set.

    Registration alone is not enough: ModItems also registers internal render parts
    (globe_sphere_render, wheelbarrow_wheel, weather_vane_base, ...) and the bulletin
    page variants. Those are components the player never holds, so listing them next
    to real furniture misrepresents the icon set. The creative tab is the line.
    """
    return set(official_items(root))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path("build/item_icon_preview.png"))
    parser.add_argument("--report", type=Path, default=Path("build/item_icon_preview.json"))
    parser.add_argument("--columns", type=int, default=8)
    parser.add_argument("--cell", type=int, default=SLOT_FRAME_CANVAS + 2 * CELL_PAD,
                        help="cell pitch in preview pixels; the drawn slot box is always "
                             f"exactly one vanilla slot ({SLOT_FRAME_CANVAS}px = {SLOT_FRAME_PIXELS}px x {ICON_ZOOM}, "
                             f"icon drawn in the centred {ICON_CANVAS}px area)")
    parser.add_argument("--items", default="", help="comma-separated item ids; default is all")
    parser.add_argument("--vanilla-reference", action="store_true",
                        help="prepend a full-cube baseline rendered with the same vanilla GUI transform")
    parser.add_argument("--all-proxies", action="store_true",
                        help="include every GUI proxy in item/*.json, including model components "
                             "(bulletin variants, rug tiles, render parts, empty states). Default "
                             "shows only ids registered as real inventory items in ModItems.")
    args = parser.parse_args()

    root = (args.root or Path.cwd()).resolve()
    mod_id = resolve({"root": str(root)}).get("mod_id")
    if not mod_id:
        parser.error(f"could not detect mod id under {root}")
    assets_root = root / "src/main/resources/assets" / mod_id
    items_dir = assets_root / "items"
    requested = {part.strip() for part in args.items.split(",") if part.strip()}
    registered = registered_item_ids(root)
    # 默认只列真正注册过的物品：item/*.json 里还混着贴图切片、bulletin 变体和
    # globe/wheelbarrow 渲染组件，它们不是可持有的 inventory 图标，不该混进预览。
    include_all = bool(requested) or args.all_proxies
    omitted_components = 0
    entries = []

    for item_path in sorted(items_dir.glob("*.json")):
        if requested and item_path.stem not in requested:
            continue
        if not include_all and item_path.stem not in registered:
            omitted_components += 1
            continue
        definition = json.loads(item_path.read_text(encoding="utf-8"))
        model_root = definition.get("model", {})
        cases = model_root.get("cases", []) if model_root.get("type") == "minecraft:select" else []
        gui_node = next((case.get("model") for case in cases if case.get("when") in ("gui", ["gui"])), None)
        if gui_node is None:
            continue
        model_ids = preview_model_ids(gui_node)
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
    cell = max(args.cell, SLOT_FRAME_CANVAS + 2 * CELL_PAD)
    label_height = 20
    rows = (len(entries) + columns - 1) // columns
    sheet = Image.new("RGBA", (columns * cell, rows * (cell + label_height)), (58, 58, 58, 255))
    draw, font = ImageDraw.Draw(sheet), ImageFont.load_default()
    for index, entry in enumerate(entries):
        x, y = (index % columns) * cell, (index // columns) * (cell + label_height)
        # 格子框 = 一个完整原版 slot(18px)，居中放在 cell 内；图标绘制区(16px)
        # 再居中放进格子框，四周各留 ICON_INSET(1px 边框 ×4)——这正是游戏里
        # 图标相对格子的布局。Pillow rectangle 是闭区间，远边减 1 才是精确 72px。
        fx = x + (cell - SLOT_FRAME_CANVAS) // 2
        fy = y + (cell - SLOT_FRAME_CANVAS) // 2
        draw.rectangle((fx, fy, fx + SLOT_FRAME_CANVAS - 1, fy + SLOT_FRAME_CANVAS - 1),
                       fill=(133, 133, 133, 255), outline=(225, 225, 225, 255))
        sprite = entry.pop("icon")
        sheet.alpha_composite(sprite, (fx + ICON_INSET, fy + ICON_INSET))
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
    if omitted_components:
        print(f"Omitted {omitted_components} model components not registered as inventory items "
              f"(use --all-proxies to include them).")
    print("This offline preview does not emulate lighting, depth rasterization, or atlas sampling.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
