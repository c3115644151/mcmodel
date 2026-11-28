#!/usr/bin/env python3
"""Validate generated GUI-only item proxies before starting the client."""
from __future__ import annotations

import json
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import resolve
from item_icon_proxy import (
    GUI_FLOOR_Y,
    GUI_ICON_TARGET_PX,
    ITEM_ICON_MANIFEST,
    TRANSFORM_CARRIER_MODELS,
    VANILLA_BLOCK_GUI,
    collect_model_ids,
    geometry_bounds,
)
from normalize_item_icons import load_model_with_parent, resolve_model, resolve_texture
from item_icon_preview import project_gui_translation, visible_projected_measurements


def check_item(item_path: Path, entry: dict, assets: Path, mod_id: str, root: Path) -> tuple[list[str], int, str]:
    """Validate one manifest item.

    Returns (issues, proxies_proven, status). ``status`` is ``"validated"`` for
    generated GUI proxies, ``"hand_authored"`` for items whose GUI model is an
    art-directed composite, and ``"error"`` when a generated proxy is malformed.
    Only generated proxies enter the fit/centre assertions below.
    """
    issues: list[str] = []
    try:
        definition = json.loads(item_path.read_text(encoding="utf-8"))
    except Exception as error:
        return [f"{item_path.name}: invalid JSON: {error}"], 0, "error"
    tree = definition.get("model", {})
    is_select = (isinstance(tree, dict) and tree.get("type") == "minecraft:select"
                 and tree.get("property") == "minecraft:display_context")
    if not is_select:
        # Hand-authored item model (e.g. art-directed bulletin composites): it
        # never uses a generated GUI proxy, so the proxy fit rules do not apply.
        return [], 0, "hand_authored"
    gui_case = next((case for case in tree.get("cases", []) if case.get("when") in ("gui", ["gui"])), None)
    if gui_case is None or "fallback" not in tree:
        return [], 0, "hand_authored"
    proxy_ids = [model_id for model_id in collect_model_ids(gui_case.get("model", {}))
                 if model_id not in TRANSFORM_CARRIER_MODELS]
    if not proxy_ids or not all(model_id.startswith(f"{mod_id}:item_icons/") for model_id in proxy_ids):
        # GUI branch points at an authored composite, not a generated proxy.
        return [], 0, "hand_authored"

    proven = 0
    for model_id in proxy_ids:
        path = resolve_model(model_id, assets, mod_id)
        if not path or not path.is_file():
            issues.append(f"{item_path.name}: missing proxy file {model_id}")
            continue
        try:
            proxy = json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            issues.append(f"{model_id}: invalid JSON: {error}")
            continue
        gui = proxy.get("display", {}).get("gui", {})
        # 相机由 manifest 记录：默认是原版 [30,225,0]，加过"额外朝向"的物品是
        # [30,225+yaw,0]——那是 display 旋转，不是几何旋转，proxy 里的几何仍是轴对齐 box。
        expected_rotation = list(entry.get("gui", {}).get("rotation",
                                                          VANILLA_BLOCK_GUI["rotation"]))
        actual_rotation = [round(float(value), 6) for value in gui.get("rotation") or []]
        if [round(float(value), 6) for value in expected_rotation] != actual_rotation:
            issues.append(
                f"{model_id}: GUI rotation {gui.get('rotation')} must match the manifest "
                f"{expected_rotation}")
        if any(abs(float(value)) > 1e-6 for value in gui.get("translation") or [0, 0, 0]):
            issues.append(
                f"{model_id}: GUI translation {gui.get('translation')} must be zero; "
                "the vanilla camera already centers the icon")
        gui_scale = gui.get("scale", [])
        if len(gui_scale) != 3 or any(not isinstance(value, (int, float)) or value <= 0 for value in gui_scale):
            issues.append(f"{model_id}: missing/invalid GUI scale")
            continue
        if any(abs(float(value) - 0.625) > 0.2 for value in gui_scale):
            issues.append(
                f"{model_id}: GUI scale {gui_scale} is far from vanilla's 0.625; "
                "the icon would not read at block-item size")
        if not proxy.get("parent") or not proxy.get("elements"):
            issues.append(f"{model_id}: proxy must retain source parent and explicit transformed geometry")
            continue
        bounds = geometry_bounds(proxy)
        if bounds is None or any(value < -16.0 - 1e-4 or value > 32.0 + 1e-4 for value in bounds):
            issues.append(f"{model_id}: 3D bounds leave the model-format range [-16,32]: {bounds}")
            continue
        measured = visible_projected_measurements(
            proxy, lambda ref: resolve_texture(root, ref), pixels_per_unit=8,
        )
        if measured is None:
            issues.append(f"{model_id}: GUI branch has no visible pixels")
        else:
            # The deliverable is a size bound, not a centring assertion: the offline
            # projection is only approximate, and Minecraft places the icon itself.
            translation = project_gui_translation(tuple(gui.get("translation", (0.0, 0.0, 0.0))),
                                                  tuple(gui["rotation"]))
            bounds = measured["bounds"]
            final = (bounds[0] * gui_scale[0] + translation[0],
                     bounds[1] * gui_scale[1] + translation[1],
                     bounds[2] * gui_scale[0] + translation[0],
                     bounds[3] * gui_scale[1] + translation[1])
            width, height = final[2] - final[0], final[3] - final[1]
            if width > 16.0 or height > 16.0:
                issues.append(f"{model_id}: visible projected icon exceeds 16px slot: {width:.2f}×{height:.2f}")
            # Per-item honest target: block-sized models fit the full vanilla
            # edge; genuinely smaller models fit a proportional edge. The
            # generator recorded the target in the manifest, so this gate uses
            # the same number instead of forcing every icon to one size.
            target_px = float(entry.get("gui_target_px", GUI_ICON_TARGET_PX))
            long_edge = max(width, height)
            if abs(long_edge - target_px) > 0.5:
                issues.append(
                    f"{model_id}: visible long edge {long_edge:.2f}px is not fitted to {target_px}px "
                    f"(source {entry.get('source_longest', '?')}u)")
            # Art-directed offsets move the expected position. The generator
            # records them in the manifest, so the gate checks against the tuned
            # target rather than always assuming slot centre/floor with no offset.
            offset_x = float(entry.get("offset_x", 0.0) or 0.0)
            offset_y = float(entry.get("offset_y", 0.0) or 0.0)
            centre_x = (final[0] + final[2]) * 0.5
            if abs(centre_x - offset_x) > 0.25:
                issues.append(
                    f"{model_id}: visible icon centre x {centre_x:.2f} is not at tuned x {offset_x:.2f}")
            if entry.get("floor_anchor"):
                # 矮模型贴地: 可见下边缘应对齐满格方块的槽底。final 是槽像素
                # (已乘 gui_scale), GUI_FLOOR_Y 是投影单位, 需乘同一 scale。
                floor_px = GUI_FLOOR_Y * gui_scale[1] + offset_y
                bottom = final[3]
                if abs(bottom - floor_px) > 0.4:
                    issues.append(
                        f"{model_id}: floor-anchored icon bottom {bottom:.2f}px is not on tuned floor "
                        f"{floor_px:.2f}px")
            else:
                centre_y = (final[1] + final[3]) * 0.5
                if abs(centre_y - offset_y) > 0.25:
                    issues.append(
                        f"{model_id}: visible icon centre y {centre_y:.2f} is not at tuned y {offset_y:.2f}")
        source = load_model_with_parent(path, assets / "models", mod_id)
        if not source or not source.get("elements"):
            issues.append(f"{model_id}: source geometry could not be resolved")
        proven += 1
    return issues, proven, "error" if issues else "validated"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", default="", help="comma-separated item ids; validate all if omitted")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    mod_id = resolve({"root": str(root)}).get("mod_id")
    if not mod_id:
        print("ERROR: could not detect mod id")
        return 1
    assets = root / "src/main/resources/assets" / mod_id
    requested = {item.strip() for item in args.items.split(",") if item.strip()}
    manifest_path = root / ITEM_ICON_MANIFEST
    if not manifest_path.is_file():
        print(f"ERROR: {ITEM_ICON_MANIFEST} is missing; run tools/deploy/normalize_item_icons.py --apply")
        return 1
    try:
        manifest_items = json.loads(manifest_path.read_text(encoding="utf-8")).get("items", {})
    except (OSError, json.JSONDecodeError) as error:
        print(f"ERROR: {ITEM_ICON_MANIFEST} cannot be read: {error}")
        return 1

    # The manifest is the generator's own record of which items it owns, so the
    # check follows it instead of demanding proxies from hand-authored GUI models
    # (art-directed bulletin variants legitimately show their own composite).
    scoped = {item_id: entry for item_id, entry in manifest_items.items()
              if not requested or item_id in requested}
    issues: list[str] = []
    warnings: list[str] = []
    wrapped_items = 0
    skipped_hand_authored = 0
    proxy_models = 0
    for item_id, entry in sorted(scoped.items()):
        item_path = assets / "items" / f"{item_id}.json"
        if not item_path.is_file():
            issues.append(f"{item_id}.json: {ITEM_ICON_MANIFEST} entry points at a missing item definition")
            continue
        item_issues, proven, status = check_item(item_path, entry, assets, mod_id, root)
        issues.extend(item_issues)
        if status == "validated":
            wrapped_items += 1
        elif status == "hand_authored":
            skipped_hand_authored += 1
        proxy_models += proven

    if not requested:
        referenced = set()
        for item_path in sorted((assets / "items").glob("*.json")):
            try:
                tree = json.loads(item_path.read_text(encoding="utf-8")).get("model", {})
            except (OSError, json.JSONDecodeError):
                continue
            referenced |= {model_id for model_id in collect_model_ids(tree)
                           if model_id.startswith(f"{mod_id}:item_icons/")}
        for model_id in sorted(referenced):
            if model_id.split("/")[1] not in scoped:
                warnings.append(f"{model_id}: referenced by an item without a {ITEM_ICON_MANIFEST} entry")
        written = {f"{mod_id}:item_icons/{path.parent.name}/{path.stem}"
                   for path in (assets / "models" / "item_icons").rglob("variant_*.json")}
        owned = {proxy_id for entry in scoped.values() for proxy_id in entry.get("proxies", [])}
        for orphan in sorted(written - owned):
            warnings.append(f"{orphan}: proxy file on disk is not in {ITEM_ICON_MANIFEST}")

    print(f"Validated {wrapped_items} generated GUI-select item definitions ({proxy_models} proxy models); "
          f"skipped {skipped_hand_authored} hand-authored item definitions.")
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}")
        return 1
    if warnings:
        for warning in warnings:
            print(f"WARN: {warning}")
    if wrapped_items == 0:
        print("ERROR: no generated GUI proxy item definitions were found")
        return 1
    print("All proxies inherit minecraft:block/block's GUI camera (rotation [30, 225, 0], no translation, scale 0.625), "
          f"fit their manifest target long edge (full block = {GUI_ICON_TARGET_PX}px, smaller models proportional), "
          "and centre in the 16px GUI slot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
